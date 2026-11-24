import uuid
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict

from .client import RECOGNITION_TIMEOUT_SECONDS, recognize
from .errors import AiProductionImportError, AiProviderNotConfigured
from .models import AiImportState, AiProductionImport
from .task_selection import active_result, active_task_key, has_created_tasks, require_task_key, task_choices
from .workbook_json import build_controlled_json
from .source_rules import confirmed_source_rules


MAPPING_WINDOW = timedelta(seconds=RECOGNITION_TIMEOUT_SECONDS * 2 + 60)


def _resolve_erp_matches(*, result, source, credentials, request):
    from .erp_assistant import resolve_erp_matches
    from .validation import validate_result

    return validate_result(resolve_erp_matches(result=result, source=source, credentials=credentials, request=request), source)


def _credentials(employee):
    from rest_framework.exceptions import NotFound

    try:
        from apps.ai_openai_config.services import get_active_credentials
        return get_active_credentials(employee)
    except NotFound as error:
        raise AiProviderNotConfigured() from error


def recognize_upload(*, employee, uploaded_file, request, client_request_id=None):
    request_id = client_request_id or uuid.uuid4()
    with transaction.atomic():
        existing = AiProductionImport.objects.filter(owner=employee, client_request_id=request_id).first()
        if existing is not None:
            return existing, True
    controlled = build_controlled_json(uploaded_file)
    with transaction.atomic():
        record = AiProductionImport.objects.create(
            owner=employee, client_request_id=request_id,
            original_name=controlled["original_name"], sha256=controlled["sha256"], size_bytes=controlled["size_bytes"],
            state=AiImportState.REVIEW, source=controlled["source"],
        )
    try:
        credentials = _credentials(employee)
        result, model = recognize(credentials=credentials, controlled=controlled,
                                  confirmed_source_rules=confirmed_source_rules(controlled["source"]))
    except AiProductionImportError as error:
        record.state = AiImportState.FAILED
        record.error_code = error.code
        record.issues = [{"issue_key": "system", "kind": error.code, "message": error.message, "source_ids": []}]
        record.save(update_fields=["state", "error_code", "issues", "updated_at"])
        raise
    with transaction.atomic():
        record = AiProductionImport.objects.select_for_update().get(pk=record.pk)
        record.model = model
        record.result = result
        record.issues = result.get("issues", [])
        record.result.setdefault("recognition_meta", {})["erp_assistant"] = {"status": "pending"}
        record.source = {**record.source, "mapping_started_at": timezone.now().isoformat()}
        record.save(update_fields=["model", "result", "issues", "source", "updated_at"])
    matched = None
    failure_code = "ERP_ASSISTANT_INTERNAL_ERROR"
    failure_message = "ERP 材料对应出现内部错误，文档识别结果已保留。"
    try:
        matched = _resolve_erp_matches(result=result, source=controlled["source"], credentials=credentials, request=request)
    except AiProductionImportError as error:
        failure_code, failure_message = error.code, error.message
        error.record_id = str(record.pk)
        raise
    finally:
        # 文档整理完成就独立保存；查库失败不能让用户重新识别已完成的文档。
        with transaction.atomic():
            record = AiProductionImport.objects.select_for_update().get(pk=record.pk)
            record.source = {key: value for key, value in record.source.items() if key != "mapping_started_at"}
            if matched is not None:
                record.result, record.issues, record.error_code = matched, matched.get("issues", []), ""
            else:
                record.result.setdefault("recognition_meta", {})["erp_assistant"] = {"status": "failed", "error_code": failure_code}
                record.error_code = failure_code
                record.issues = [*record.result.get("issues", []), {"issue_key": "erp_assistant", "kind": failure_code,
                                  "message": "文档识别结果已保存，ERP 材料对应未完成。" + failure_message, "source_ids": []}]
            record.save(update_fields=["result", "issues", "source", "error_code", "updated_at"])
    return record, False


def owned(employee, record_id):
    return get_object_or_404(AiProductionImport, owner=employee, pk=record_id)


def _mapping_active(record):
    started = parse_datetime(record.source.get("mapping_started_at", ""))
    return bool(started and started > timezone.now() - MAPPING_WINDOW)


def match_record_materials(*, employee, record_id, request):
    """仅补充已识别材料的ERP建议，保留所有任务核对稿和人工修改。"""
    with transaction.atomic():
        record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
        require_matching_etag(request, record)
        if has_created_tasks(record):
            raise Conflict("已创建任务的记录请在原任务和 BOM 中调整材料。")
        if not record.result or _mapping_active(record):
            raise Conflict("请等待当前识别完成后再对应材料。")
        started = timezone.now().isoformat()
        record.source = {**record.source, "mapping_started_at": started}
        record.save(update_fields=["source", "updated_at"])
    result = None
    try:
        result = _resolve_erp_matches(result=record.result, source=record.source,
                                      credentials=_credentials(employee), request=request)
    finally:
        # 无论第三方失败还是内部异常都解除本次进行中标记，异常本身继续上抛。
        with transaction.atomic():
            current = AiProductionImport.objects.select_for_update().get(pk=record.pk)
            if current.source.get("mapping_started_at") == started:
                current.source = {key: value for key, value in current.source.items() if key != "mapping_started_at"}
                fields = ["source", "updated_at"]
                if result is not None:
                    current.result = result
                    current.error_code = ""
                    current.issues = result.get("issues", [])
                    fields.extend(["result", "error_code", "issues"])
                current.save(update_fields=fields)
            elif result is not None:
                raise Conflict("记录已开始另一轮对应，请刷新查看最新结果。")
    return current


def remap_record(*, employee, record_id, request):
    """使用已保存的文字重新对应字段，失败时保留原有结果和核对稿。"""
    with transaction.atomic():
        record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
        require_matching_etag(request, record)
        if has_created_tasks(record):
            raise Conflict("已创建任务的记录不能重新识别，请在原任务和 BOM 中调整。")
        if _mapping_active(record) or (record.state == AiImportState.REVIEW and not record.result
                                      and record.updated_at > timezone.now() - MAPPING_WINDOW):
            raise Conflict("该记录正在对应 ERP 字段，请等待完成。")
        record.source = {**record.source, "mapping_started_at": timezone.now().isoformat()}
        record.save(update_fields=["source", "updated_at"])
    controlled = {"source": record.source, "original_name": record.original_name,
                  "sha256": record.sha256, "size_bytes": record.size_bytes}
    try:
        credentials = _credentials(employee)
        result, model = recognize(credentials=credentials, controlled=controlled,
                                  confirmed_source_rules=confirmed_source_rules(controlled["source"]))
        result = _resolve_erp_matches(result=result, source=controlled["source"], credentials=credentials, request=request)
    except AiProductionImportError:
        with transaction.atomic():
            current = AiProductionImport.objects.select_for_update().get(pk=record.pk)
            current.source = {key: value for key, value in current.source.items() if key != "mapping_started_at"}
            current.save(update_fields=["source", "updated_at"])
        raise
    with transaction.atomic():
        record = AiProductionImport.objects.select_for_update().get(pk=record.pk)
        source = {key: value for key, value in record.source.items()
                  if key not in {"mapping_started_at", "review_draft", "task_states", "active_task_key"}}
        source["previous_recognition"] = {"result": record.result, "review_draft": record.source.get("review_draft"),
                                          "task_states": record.source.get("task_states", {}),
                                          "active_task_key": active_task_key(record), "model": record.model}
        record.source = source
        record.result, record.model, record.issues = result, model, result.get("issues", [])
        record.state, record.error_code = AiImportState.REVIEW, ""
        record.save(update_fields=["source", "result", "model", "issues", "state", "error_code", "updated_at"])
    return record


def restore_previous_review(*, employee, record_id, request):
    with transaction.atomic():
        record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
        require_matching_etag(request, record)
        if _mapping_active(record) or has_created_tasks(record):
            raise Conflict("正在识别或已创建任务时不能恢复旧核对稿。")
        previous = record.source.get("previous_recognition")
        if not isinstance(previous, dict) or not previous.get("result"):
            raise Conflict("没有可恢复的上一版识别结果。")
        current = {"result": record.result, "review_draft": record.source.get("review_draft"),
                   "task_states": record.source.get("task_states", {}),
                   "active_task_key": active_task_key(record), "model": record.model}
        record.result = previous["result"]
        record.model = previous.get("model", record.model)
        record.issues = record.result.get("issues", [])
        record.source = {**record.source, "previous_recognition": current,
                         "review_draft": previous.get("review_draft"),
                         "task_states": previous.get("task_states", {}),
                         "active_task_key": previous.get("active_task_key", "main")}
        record.state, record.error_code = AiImportState.REVIEW, ""
        record.save(update_fields=["result", "model", "issues", "source", "state", "error_code", "updated_at"])
    return record


def save_review(*, employee, record_id, draft, request):
    with transaction.atomic():
        record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
        require_matching_etag(request, record)
        if _mapping_active(record):
            raise Conflict("正在对应 ERP 字段，请完成后再修改核对表单。")
        if not record.result:
            raise Conflict("识别完成后才能保存核对表单。")
        require_task_key(record, draft.get("task_key"))
        # 复用来源 JSON 的独立元数据区；不改动原始单元格、识别结果及其来源哈希。
        record.source = {**record.source, "review_draft": draft}
        record.save(update_fields=["source", "updated_at"])
    return record


def delete_record(*, employee, record_id, request):
    with transaction.atomic():
        record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
        require_matching_etag(request, record)
        if _mapping_active(record):
            raise Conflict("正在对应 ERP 字段，请完成后再删除记录。")
        if (record.state == AiImportState.REVIEW and not record.result
                and record.updated_at > timezone.now() - MAPPING_WINDOW):
            raise Conflict("该记录仍在识别中，请处理结束后再删除。")
        # task_id/bom_id 只是引用：仅删除识别记录，不调用业务单据或文件删除服务。
        identifier = str(record.pk)
        record.delete()
    return identifier


def snapshot(record):
    selected_result = active_result(record)
    task_status = ""
    task_products = []
    if record.task_id:
        from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
        task_status = ProductionTask.objects.filter(pk=record.task_id).values_list("status", flat=True).first() or ""
        task_products = list(
            ProductionTaskProduct.objects.filter(production_task_id=record.task_id)
            .order_by("line_number", "id")
            .values("id", "product_name_snapshot", "specification_snapshot", "quantity")
        )
        for item in task_products:
            item["id"] = str(item["id"])
            item["quantity"] = str(item["quantity"])
            item["client_key"] = record.source.get("created_product_keys", {}).get(item["id"], "")
    # 旧记录在外部请求开始前就写为 REVIEW；没有结果时不能当成已完成。
    pending = (record.state == AiImportState.REVIEW and not record.result) or _mapping_active(record)
    sources = {key: dict(value) for key, value in record.source.get("source_index", {}).items()}
    for sheet in record.source.get("sheets", []):
        for item in [*sheet.get("cells", []), *sheet.get("comments", [])]:
            source = sources.get(item.get("source_id"))
            if source is not None:
                source["sheet"] = sheet.get("name")
                source["text"] = item.get("text")
    return {
        "id": str(record.pk), "state": "RECOGNIZING" if pending else record.state, "phase": "recognition",
        "progress": {"stage": "recognizing" if pending else "failed" if record.state == AiImportState.FAILED else "completed",
                     "percent": None if pending else 100},
        "original_name": record.original_name, "sha256": record.sha256, "size_bytes": record.size_bytes,
        "model": record.model, "result": record.result, "issues": selected_result.get("issues", record.issues), "error_code": record.error_code,
        "active_task_key": active_task_key(record), "task_choices": task_choices(record),
        "has_created_tasks": has_created_tasks(record),
        "has_previous_recognition": bool(record.source.get("previous_recognition", {}).get("result")),
        "task_draft": selected_result.get("task", {}),
        "bom_draft": selected_result.get("boms", []),
        "review_draft": record.source.get("review_draft"),
        "task_id": record.task_id,
        "task_number": record.task_number,
        "task_status": task_status,
        "task_products": task_products,
        "bom_id": record.bom_id,
        "bom_ids": record.bom_ids or [],
        "source_summary": {
            "format": record.source.get("format"), "source_sha256": record.source.get("source_sha256"),
            "sheets": [{"name": item.get("name"), "state": item.get("state"), "dimension": item.get("dimension"),
                        "cell_count": len(item.get("cells", [])), "picture_count": len(item.get("pictures", []))}
                       for item in record.source.get("sheets", [])],
            "images": record.source.get("images", []), "limitations": record.source.get("limitations", []),
        },
        "sources": sources,
        "created_at": record.created_at, "updated_at": record.updated_at,
    }
