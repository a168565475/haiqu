from apps.inventory.public_stock_cutover import stock_write_transaction
"""仅加工额度记账；禁止从本模块调用原料、半成品和工资记账服务。"""

from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.auth import active_employee_for

from .models import MaterialIssue, MetalProcessingClosure, MetalProcessingCompletion, MetalProcessingSource
from .processing_selectors import digest, frozen_source, processing_lines, quantity_state, source_data, source_etag


@stock_write_transaction
def record_processing(*, request, issue_line_id, data, operation):
    # 服务入口也验证权限，避免未来非 View 调用绕过权限边界。
    permission = {"completion": "register_metalprocessingcompletion", "close": "close_metalprocessingsource"}.get(operation)
    actor = active_employee_for(request.user)
    if not permission or not actor or not request.user.has_perm(f"material_issues.{permission}"):
        raise PermissionDenied("当前账号没有执行此操作的权限。")

    # 同一请求 UUID 的跨来源/跨动作重试串行化，记录表唯一约束为第二层保护。
    lock_key = int.from_bytes(bytes.fromhex(digest(f"metal-processing:{data['request_id']}"))[:8], signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
    sources = processing_lines(request, scoped=False, permission=f'material_issues.{permission}')
    hint = get_object_or_404(sources, pk=issue_line_id)
    MaterialIssue.objects.select_for_update().get(pk=hint.issue_id)
    line = get_object_or_404(sources.select_for_update(of=("self",)), pk=issue_line_id)
    source = MetalProcessingSource.objects.select_for_update().filter(issue_line=line).first()
    payload_hash = digest({"operation": operation, "issue_line_id": str(line.pk), "data": data})
    for model in (MetalProcessingCompletion, MetalProcessingClosure):
        existing = model.objects.filter(request_id=data["request_id"]).first()
        if existing:
            if (existing.request_payload_hash != payload_hash or existing.actor_employee_id != actor.pk
                    or source is None or existing.source_id != source.pk):
                raise Conflict("相同请求标识不能用于不同来源、操作人或提交内容。")
            return existing.result_snapshot

    snapshot = frozen_source(line)
    if source and source.source_hash != digest(snapshot):
        raise Conflict("原领料冻结资料已变化，请先核对来源。")
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if expected != source_etag(line, source, snapshot):
        raise PreconditionFailed()
    if source and source.status == "CLOSED":
        raise Conflict("该加工来源已结清，不能继续登记或结清。")
    if source is None:
        source = MetalProcessingSource.objects.create(
            issue_line=line, source_snapshot=snapshot, source_hash=digest(snapshot), issued_pieces=snapshot["issued_pieces"],
        )
    if operation == "completion":
        if source.completed_pieces + data["good_pieces"] > source.issued_pieces:
            raise ValidationError({"good_pieces": "累计完成支数不能超过该来源已实际领用支数。"})
        source.completed_pieces += data["good_pieces"]
        fields = {"good_pieces": data["good_pieces"], "completion_date": data["completion_date"]}
        model = MetalProcessingCompletion
    else:
        if source.reserved_pieces:
            raise Conflict("存在待外发占用，请先确认交接或取消分配后再结清。")
        fields = {"remark": data["remark"], "quantity_snapshot": quantity_state(source, source.issued_pieces)}
        source.status = "CLOSED"
        model = MetalProcessingClosure
    source.version += 1
    source.save(update_fields=["completed_pieces", "status", "version", "updated_at"])
    record = model.objects.create(source=source, actor_employee=actor, request_id=data["request_id"],
                                  request_payload_hash=payload_hash, source_version=source.version,
                                  result_snapshot={}, **fields)
    # 用锁内新状态构造响应；同请求重试始终返回首次成功结果及版本。
    line.processing_source = source
    result = source_data(line, detail=True)
    result["operation_id"] = str(record.pk)
    record.result_snapshot = result
    record.save(update_fields=["result_snapshot", "updated_at"])
    return result
