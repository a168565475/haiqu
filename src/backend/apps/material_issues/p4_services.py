from apps.access_control import resource_scopes
from .p4_access import require_record, scoped_records, require_external_destination, can_record
from apps.inventory.public_stock_cutover import stock_write_transaction
"""P4 管材退回、重新加工、新外发和合格回货服务。

本模块只处理管材加工件的数量状态和半成品合格入库，不恢复原料库存、不创建不良品、不修改原外发单数量。
"""

from decimal import Decimal
import hashlib
import json
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.auth import active_employee_for
from apps.core.audit import write_audit_log
from apps.audit.models import AuditLog
from apps.inventory.models import MaterialStockQuality, WarehouseType, WarehouseZone
from apps.inventory.stock_services import credit_semi_finished_stock
from apps.inventory.public_bom_snapshot import build_output_identity
from apps.inventory.public_stock_identity import validate_public_identity
from apps.inventory.public_stock_mode import require_document_stock_mode
from apps.inventory.public_stock_services import credit_public_stock
from apps.organizations.models import Employee, EmployeeStatus
from apps.production_tasks.models import ProductionTask
from apps.outsourcing.material_flow import lock_request
from apps.outsourcing.models import (
    FactoryStatus, OutsourcingFactory, OutsourcingFactoryAllocation, OutsourcingFactoryCraft,
    OutsourcingDispatch, OutsourcingOrder, OutsourcingOrderStatus, OutsourcingReturn, OutsourcingReturnLine,
)
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus

from .models import (
    MaterialIssue, MaterialIssueLine, MetalProcessingClosure, MetalProcessingExternalClosure,
    MetalProcessingExternalGoodReturn, MetalProcessingExternalHandoff,
    MetalProcessingExternalOrder, MetalProcessingExternalOrderStatus,
    MetalProcessingOriginalHandoff, MetalProcessingRework, MetalProcessingSource,
    MetalProcessingUnsprayedReturn,
)
from .processing_selectors import digest, frozen_source, processing_lines, source_etag, source_data
from .legacy_public_transition import require_original_handoff_mode, trusted_handoff_transition


def p4_schema_ready():
    """既有入口仅在 P4 表已正式迁移后接入新账；不缓存迁移状态。"""
    return MigrationRecorder(connection).migration_qs.filter(
        app="material_issues", name="0007_metalprocessingoriginalhandoff_and_more",
    ).exists()


DIRECT_HANDOFF_LOCK_REASON = "该原单已有金工直接交接，请从管材外发工作台办理合格回货；旧原料发料、回货、退料、对账、完成、编辑和取消删除入口已锁定。"


def has_original_direct_handoff(order):
    return p4_schema_ready() and MetalProcessingOriginalHandoff.objects.filter(original_order_id=order.pk).exists()


def assert_legacy_original_route(order):
    """调用写入方须先锁原单；旧入口不能再次扣原料或把已加工件退成原料。"""
    if has_original_direct_handoff(order):
        raise Conflict(DIRECT_HANDOFF_LOCK_REASON)


def _payload_hash(payload):
    return digest(payload)


def _require_permission(request, codename):
    actor = active_employee_for(request.user)
    if not actor or not request.user.has_perm(f"material_issues.{codename}"):
        raise PermissionDenied("当前账号没有执行此操作的权限。")
    return actor


def _require_source_etag(request, line, source, snapshot):
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if expected != source_etag(line, source, snapshot):
        raise PreconditionFailed()


def _source_for_request(request, line_id, *, lock=True):
    queryset = processing_lines(request)
    if lock:
        # 与 P3 完成/结清共用「领料单 → 明细 → 加工来源」的锁顺序。
        hint = get_object_or_404(queryset, pk=line_id)
        MaterialIssue.objects.select_for_update().get(pk=hint.issue_id)
        queryset = queryset.select_for_update(of=("self",))
    line = get_object_or_404(queryset, pk=line_id)
    source = get_object_or_404(
        MetalProcessingSource.objects.select_for_update(of=("self",)).select_related("issue_line__issue", "issue_line__unit"),
        issue_line=line,
    )
    snapshot = frozen_source(line)
    if source.source_hash != digest(snapshot):
        raise Conflict("原领料冻结资料已变化，请先核对来源。")
    return line, source, snapshot


def _active_employee(employee_id, field="received_by_employee_id"):
    employee = Employee.objects.filter(
        pk=employee_id, status=EmployeeStatus.ACTIVE, archived_at__isnull=True,
    ).first()
    if employee is None:
        raise ValidationError({field: "接收人不存在、已停用或已归档。"})
    return employee


def _active_factory(factory_id):
    factory = OutsourcingFactory.objects.filter(pk=factory_id, status=FactoryStatus.ACTIVE).first()
    if factory is None:
        raise ValidationError({"factory_id": "加工厂不存在或已停用。"})
    return factory


def _p4_order_etag(order):
    return f'"metal-p4-order:{order.pk}:{order.version}"'


def _require_order_etag(request, order):
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if expected != _p4_order_etag(order):
        raise PreconditionFailed()


def _order_number():
    return f"P4-{timezone.localdate():%Y%m%d}-{uuid4().hex[:10].upper()}"


def _return_number():
    return f"P4-R-{timezone.localdate():%Y%m%d}-{uuid4().hex[:10].upper()}"


def _original_allocation(source, original_order, factory_id):
    """用冻结的任务、产品和 BOM 部位唯一匹配，不能按名称猜配。"""
    snapshot = source.source_snapshot
    if str(original_order.schedule.production_task_id) != snapshot.get("production_task_id"):
        raise ValidationError({"original_order_id": "原外发单与金工来源不属于同一生产任务。"})
    if original_order.craft.outsourcing_code != OutsourcingCode.POWDER_COATING:
        raise ValidationError({"original_order_id": "原外发单必须为喷塑外发单。"})
    allocations = list(OutsourcingFactoryAllocation.objects.filter(
        processing_item__order_product__order=original_order,
        processing_item__order_product__schedule_product__product_line_id=snapshot.get("product_line_id"),
        processing_item__bom_line_id=snapshot.get("conversion_snapshot", {}).get("bom_line_id"),
        factory_id=factory_id,
    ).select_related("processing_item__order_product__schedule_product")[:2])
    if len(allocations) != 1:
        raise ValidationError({"original_order_id": "原外发单未唯一匹配该产品、管材部位及加工厂分配，请核对。"})
    return allocations[0]


def original_handoff_totals(allocation):
    """调用写入方须先锁定原外发单；旧回货与未喷塑退回共用此实交上限。"""
    item = allocation.processing_item
    handoffs = MetalProcessingOriginalHandoff.objects.filter(
        original_order_id=item.order_product.order_id, factory_id=allocation.factory_id,
        source__source_snapshot__product_line_id=str(item.order_product.schedule_product.product_line_id),
        source__source_snapshot__conversion_snapshot__bom_line_id=str(item.bom_line_id),
    )
    return {
        "handoff_pieces": handoffs.aggregate(total=Sum("handoff_pieces"))["total"] or 0,
        "returned_unsprayed_pieces": MetalProcessingUnsprayedReturn.objects.filter(
            original_handoff__in=handoffs,
        ).aggregate(total=Sum("returned_pieces"))["total"] or 0,
        "returned_pieces": OutsourcingReturnLine.objects.filter(allocation=allocation).aggregate(
            total=Sum("returned_quantity"),
        )["total"] or 0,
    }


def _allocation_handoffs(allocation):
    item = allocation.processing_item
    return MetalProcessingOriginalHandoff.objects.filter(
        original_order_id=item.order_product.order_id, factory_id=allocation.factory_id,
        source__source_snapshot__product_line_id=str(item.order_product.schedule_product.product_line_id),
        source__source_snapshot__conversion_snapshot__bom_line_id=str(item.bom_line_id),
    ).select_related("source__issue_line__unit", "source__issue_line__issue", "original_order__schedule", "original_order__craft", "factory")


def _source_stock_identity(source):
    # 旧 P3 快照没有单位和颜色，兼容读取已出库领料行的冻结字段，绝不读取现行 BOM。
    snapshot = source.source_snapshot
    line = source.issue_line
    return {"production_task_id": snapshot["production_task_id"], "product_line_id": snapshot["product_line_id"],
            "bom_line_id": snapshot["conversion_snapshot"]["bom_line_id"],
            "component_identity": snapshot["component_identity"], "part_name": snapshot.get("part_name", ""),
            "color": line.color_snapshot, "unit_id": str(line.unit_id), "unit": line.unit_snapshot}


def _require_source_mode(order, source):
    if order.stock_mode != source.issue_line.issue.stock_mode:
        if isinstance(order, MetalProcessingExternalOrder) and order.stock_mode == "PUBLIC_V2":
            handoff = order.rework.unsprayed_return.original_handoff
            transition = trusted_handoff_transition(handoff)
            if (transition is not None and order.source_id == handoff.source_id
                    and order.original_return_id == order.rework.unsprayed_return_id
                    and order.rework.source_id == handoff.source_id):
                return
        raise Conflict("外发单与已领原料的库存版本不同，须先核对旧单接续，不能混用库存来源。")


def _source_output_identity(source, craft):
    """输出要求来自领料时冻结属性，不从后来编辑的 BOM 补历史。"""
    conversion = source.source_snapshot.get("conversion_snapshot", {})
    frozen = conversion.get("public_bom_snapshot")
    identity = build_output_identity(frozen, craft, source.issue_line.unit)
    if (str(frozen["line"]["id"]) != str(conversion.get("bom_line_id"))
            or str(frozen["line"]["section"]["bom_id"]) != str(conversion.get("bom_id"))
            or identity["identity_snapshot"].get("cutting_length_mm") != conversion.get("cutting_length_mm")):
        raise Conflict("领料冻结 BOM 部位或切割长度与加工来源不一致。")
    return identity


def _validate_output_craft(identity, craft):
    identity = validate_public_identity(identity)
    frozen_craft = identity["identity_snapshot"].get("completed_craft", {})
    if (identity["stock_kind"] != "SEMI" or identity["identity_snapshot"].get("semi_kind") != "PIPE"
            or frozen_craft != {"id": str(craft.pk), "craft_type": craft.craft_type, "code": craft.outsourcing_code}
            or craft.craft_type != CraftType.EXTERNAL or craft.outsourcing_code != OutsourcingCode.POWDER_COATING):
        raise Conflict("合格回货的实际喷塑工艺与交接冻结要求不一致。")
    return identity


def _public_handoff_identity(handoff):
    _require_source_mode(handoff.original_order, handoff.source)
    transition = trusted_handoff_transition(handoff)
    if transition is not None:
        return _validate_output_craft(transition.public_identity, handoff.original_order.craft)
    return _validate_output_craft(handoff.snapshot.get("public_output_identity"), handoff.original_order.craft)


def _rework_output_identity(rework, craft):
    handoff = rework.unsprayed_return.original_handoff
    identity = _public_handoff_identity(handoff)
    # 重加工件仍是同一实物，仅承接本次已选择的喷塑工艺，不重新读 BOM。
    identity = json.loads(json.dumps(identity))
    identity["identity_snapshot"]["completed_craft"] = {
        "id": str(craft.pk), "craft_type": craft.craft_type, "code": craft.outsourcing_code,
    }
    identity["identity_key"] = hashlib.sha256(json.dumps(identity["identity_snapshot"], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return _validate_output_craft(identity, craft)


def _public_external_identity(order, *, require_handoff=False):
    _require_source_mode(order, order.source)
    identity = _validate_output_craft(order.output_identity_snapshot, order.craft)
    if order.source.issue_line.issue.stock_mode == "LEGACY":
        if identity != _rework_output_identity(order.rework, order.craft):
            raise Conflict("再外发产物身份必须沿已接续原交接证据生成。")
    if require_handoff:
        handoff = getattr(order, "handoff", None)
        if handoff is None or handoff.snapshot.get("public_output_identity") != identity:
            raise Conflict("再外发实际交接缺少一致的冻结产物身份，不能入库。")
    return identity


def _handoff_stock_identity(handoff):
    identity = handoff.snapshot.get("stock_identity") or _source_stock_identity(handoff.source)
    if any(not identity.get(key) for key in ("production_task_id", "product_line_id", "bom_line_id", "component_identity", "unit_id", "unit")):
        raise ValidationError({"source": "直接交接的冻结库存身份不完整，请核对原领料记录。"})
    if handoff.original_order.stock_mode == "PUBLIC_V2" or trusted_handoff_transition(handoff) is not None:
        return {**identity, "public_output_identity": _public_handoff_identity(handoff)}
    return identity


def _allocation_for_handoff(handoff):
    allocation = _original_allocation(handoff.source, handoff.original_order, handoff.factory_id)
    frozen_id = handoff.snapshot.get("allocation_id")
    if frozen_id and frozen_id != str(allocation.pk):
        raise Conflict("原单加工分配与直接交接冻结记录不一致，请核对。")
    return allocation


def _original_good_return_etag(handoff, allocation, totals, identities):
    return '"' + digest({"handoff_id": str(handoff.pk), "allocation_id": str(allocation.pk),
        "source_version": handoff.source.version, "order_version": handoff.original_order.version,
        "order_status": handoff.original_order.status, "totals": totals, "identities": identities}) + '"'


def original_good_return_context(handoff, request=None):
    from .original_order_services import original_closure_data
    order = handoff.original_order
    closure = original_closure_data(order)
    result = {"original_order_id": str(order.pk), "original_order_number": order.order_number,
        "stock_mode": order.stock_mode, "original_stock_mode": order.stock_mode,
        "transitioned": False, "public_output_identity": None,
        "original_order_status": order.status, "factory_id": str(handoff.factory_id),
        "factory_name": handoff.snapshot.get("factory_name", handoff.factory.name),
        "part_name": handoff.source.source_snapshot.get("part_name", ""), "unit": "支",
        "allocation_id": None, "etag": None, "handoff_pieces": 0, "returned_good_pieces": 0,
        "returned_unsprayed_pieces": 0, "remaining_return_pieces": 0,
        "can_return": False, "blockers": [], "good_returns": [],
        "post_closure": order.status == OutsourcingOrderStatus.CLOSED, "closure": closure}
    try:
        allocation = _allocation_for_handoff(handoff)
        peers = list(_allocation_handoffs(allocation).order_by("id"))
        identities = [_handoff_stock_identity(row) for row in peers]
        totals = original_handoff_totals(allocation)
    except (ValidationError, Conflict) as exc:
        result["blockers"] = [str(exc.detail)]
        return result
    blockers = result["blockers"]
    try:
        public_mode = require_original_handoff_mode(order, peers)
        result["stock_mode"] = "PUBLIC_V2" if public_mode else order.stock_mode
        result["transitioned"] = public_mode and order.stock_mode == "LEGACY"
    except (ValidationError, Conflict) as exc:
        blockers.append(str(exc.detail))
    if not peers or any(identity != identities[0] for identity in identities[1:]):
        blockers.append("同一加工分配的多次交接存在不同冻结部位、颜色或单位，不能合并回货。")
    if OutsourcingDispatch.objects.filter(order=order).exists():
        blockers.append("原单同时存在仓库原料发料与直接交接，不能混合来源回货，请先核对。")
    if order.status not in {OutsourcingOrderStatus.PENDING_DISPATCH, OutsourcingOrderStatus.PROCESSING,
                            OutsourcingOrderStatus.PARTIAL_RETURN, OutsourcingOrderStatus.CLOSED}:
        blockers.append("原外发单已完成或已取消，不能登记合格回货。")
    if order.status == OutsourcingOrderStatus.CLOSED and closure is None:
        blockers.append("原单缺少结清快照，请先核对。")
    lines = list(OutsourcingReturnLine.objects.filter(allocation=allocation).select_related(
        "return_record__zone__warehouse", "return_record__received_by_employee", "return_record__confirmed_by_employee",
    ).order_by("return_record__confirmed_at", "id"))
    if any(row.quality != MaterialStockQuality.AVAILABLE or row.returned_quantity != row.returned_quantity.to_integral_value() for row in lines):
        blockers.append("原单存在不良或非整数回货记录，不能按直接交接合格支数合并。")
    good = sum((row.returned_quantity for row in lines if row.quality == MaterialStockQuality.AVAILABLE), Decimal(0))
    remaining = totals["handoff_pieces"] - totals["returned_pieces"] - totals["returned_unsprayed_pieces"]
    if remaining <= 0:
        blockers.append("当前已无可回货支数。")
    if request is not None and not can_record(request, "outsourcing.confirm_return_outsourcingorder", "handoff", handoff.pk):
        blockers.append("当前账号没有原单合格回货权限。")
    result.update(allocation_id=str(allocation.pk), handoff_pieces=totals["handoff_pieces"],
        returned_good_pieces=int(good), returned_unsprayed_pieces=totals["returned_unsprayed_pieces"],
        remaining_return_pieces=max(int(remaining), 0),
        unit=identities[0]["unit"] if identities else "支",
        etag=_original_good_return_etag(handoff, allocation, totals, identities), can_return=not blockers)
    if identities:
        result["public_output_identity"] = identities[0].get("public_output_identity")
    for line in lines:
        if line.quality != MaterialStockQuality.AVAILABLE:
            continue
        record = line.return_record
        result["good_returns"].append({"id": str(record.pk), "return_number": record.return_number,
            "good_pieces": int(line.returned_quantity), "zone_id": str(record.zone_id),
            "zone_name": f"{record.zone.warehouse.warehouse_name} / {record.zone.zone_name}",
            "received_by_employee_id": str(record.received_by_employee_id) if record.received_by_employee_id else None,
            "received_by_employee_name": record.received_by_employee.display_name if record.received_by_employee_id else "",
            "return_date": record.return_date.isoformat(), "remark": record.remark,
            "actor_name": record.confirmed_by_employee.display_name, "created_at": record.created_at.isoformat(),
            "post_closure": bool(line.snapshot.get("post_closure"))})
    return result


def original_direct_handoff_summary(order):
    if not has_original_direct_handoff(order):
        return []
    result, seen = [], set()
    fields = ("allocation_id", "part_name", "factory_id", "factory_name", "unit", "handoff_pieces",
              "returned_good_pieces", "returned_unsprayed_pieces", "remaining_return_pieces")
    for handoff in MetalProcessingOriginalHandoff.objects.filter(original_order=order).select_related("source", "factory"):
        handoff.original_order = order
        context = original_good_return_context(handoff)
        key = context["allocation_id"] or str(handoff.pk)
        if key not in seen:
            seen.add(key)
            result.append({key: context[key] for key in fields})
    return result


def _bump_original_order(order, actor, request, action, before):
    from apps.outsourcing.services import order_audit_snapshot
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["version", "status", "completed_at", "updated_by_employee", "updated_at"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action=action,
        actor_employee=actor, before_data=before, after_data=order_audit_snapshot(order),
        context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)


@stock_write_transaction
def confirm_original_good_return(*, request, handoff_id, request_id, good_pieces, zone_id,
                                 received_by_employee_id, return_date, remark):
    require_record(request, "outsourcing.confirm_return_outsourcingorder", "handoff", handoff_id)
    actor = active_employee_for(request.user)
    if not actor or not request.user.has_perm("outsourcing.confirm_return_outsourcingorder"):
        raise PermissionDenied("当前账号没有原单合格回货权限。")
    # 与旧回货共用请求锁和唯一回货请求字段，避免跨接口 UUID 冲突重复记账。
    lock_request("return", request_id)
    handoff = get_object_or_404(MetalProcessingOriginalHandoff.objects.filter(
        source__issue_line__in=processing_lines(request)), pk=handoff_id)
    payload = {"route": "METAL_ORIGINAL_GOOD_RETURN", "handoff_id": str(handoff_id),
        "actor_id": str(actor.pk), "good_pieces": good_pieces, "zone_id": str(zone_id),
        "received_by_employee_id": str(received_by_employee_id), "return_date": str(return_date), "remark": remark}
    request_hash = _payload_hash(payload)
    existing = OutsourcingReturn.objects.filter(client_request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != request_hash or existing.order_id != handoff.original_order_id:
            raise Conflict("相同回货请求标识已用于不同内容或操作人。")
        get_object_or_404(accessible_outsourcing_orders(request), pk=handoff.original_order_id)
        return original_good_return_context(handoff, request)
    line, source, _snapshot = _source_for_request(request, handoff.source.issue_line_id)
    handoff.source = source
    order = get_object_or_404(accessible_outsourcing_orders(request).select_for_update(of=("self",)).select_related(
        "schedule", "craft"), pk=handoff.original_order_id)
    handoff.original_order = order
    _require_source_mode(order, source)
    allocation = _allocation_for_handoff(handoff)
    public_mode = require_original_handoff_mode(order, list(_allocation_handoffs(allocation).order_by("id")))
    context = original_good_return_context(handoff, request)
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if expected != context["etag"]:
        raise PreconditionFailed()
    if not context["can_return"]:
        raise Conflict("；".join(context["blockers"]))
    remark = remark.strip()
    if context["post_closure"] and not remark:
        raise ValidationError({"remark": "原单结清后补登记必须填写原因备注。"})
    from apps.outsourcing.material_flow import quantity
    from apps.outsourcing.services import order_audit_snapshot
    quantity(good_pieces, "good_pieces", integer=True)
    if good_pieces > context["remaining_return_pieces"]:
        raise Conflict("合格回货与未喷塑退回合计不能超过该部位、该加工厂累计实际交接支数。")
    identity = _handoff_stock_identity(handoff)
    from apps.boms.models import BomLine
    from apps.reference_data.models import ProductionUnit
    task = ProductionTask.objects.select_for_update().get(pk=identity["production_task_id"])
    product_line = line.issue.product_line
    if str(product_line.pk) != identity["product_line_id"] or product_line.production_task_id != task.pk:
        raise Conflict("原交接的任务和产品冻结身份不一致。")
    if public_mode:
        from apps.production_tasks.models import ProductionTaskProduct
        product_line = ProductionTaskProduct.objects.select_for_update(of=("self",), no_key=True).get(pk=product_line.pk)
    bom_lines = BomLine.objects.select_for_update(of=("self",), no_key=True) if public_mode else BomLine.objects
    bom_line = get_object_or_404(bom_lines, pk=identity["bom_line_id"])
    unit = get_object_or_404(ProductionUnit, pk=identity["unit_id"])
    zones = WarehouseZone.objects.all() if public_mode else WarehouseZone.objects.select_for_update(of=("self",))
    zone = get_object_or_404(zones.select_related("warehouse"), pk=zone_id)
    if zone.status != "ACTIVE" or zone.warehouse.status != "ACTIVE" or zone.warehouse.warehouse_type != WarehouseType.SEMI_FINISHED:
        raise ValidationError({"zone_id": "合格回货只能进入启用的半成品库区。"})
    receiver = _active_employee(received_by_employee_id)
    before = order_audit_snapshot(order)
    record = OutsourcingReturn.objects.create(order=order, return_number=_return_number(), factory_id=handoff.factory_id,
        client_request_id=request_id, request_payload_hash=request_hash, zone=zone, received_by_employee=receiver,
        return_date=return_date, remark=remark, factory_snapshot={"id": str(handoff.factory_id), "name": context["factory_name"]},
        confirmed_by_employee=actor, confirmed_at=timezone.now())
    line_id = uuid4()
    snapshot = {**identity, "route": "METAL_ORIGINAL_GOOD_RETURN", "source_id": str(source.pk),
        "handoff_id": str(handoff.pk), "allocation_id": context["allocation_id"],
        "return_number": record.return_number, "order_number": order.order_number,
        "factory": context["factory_name"], "component": identity["part_name"],
        "completed_craft": order.craft_name_snapshot, "quality": MaterialStockQuality.AVAILABLE,
        "actor_employee_id": str(actor.pk), "actor_name": actor.display_name, "good_pieces": good_pieces,
        "post_closure": context["post_closure"]}
    transition = trusted_handoff_transition(handoff)
    if transition is not None:
        snapshot["public_transition_id"] = str(transition.pk)
        snapshot["original_stock_mode"] = "LEGACY"
        snapshot["transition_manifest_hash"] = transition.manifest_hash
    if public_mode:
        output_identity = _public_handoff_identity(handoff)
        movement = credit_public_stock(identity=output_identity, zone=zone, quantity=good_pieces,
            source_type="OUTSOURCING_RETURN", source_id=record.pk, source_line_id=line_id,
            actor_employee=actor, production_task=task, product_line=product_line, bom_line=bom_line,
            snapshot={**snapshot, "public_output_identity": output_identity,
                      "color": output_identity["identity_snapshot"]["color"],
                      "unit": output_identity["identity_snapshot"]["unit_name"]})
        stock_link = {"public_stock_movement": movement}
    else:
        movement = credit_semi_finished_stock(production_task=task, product_line=product_line, bom_line=bom_line,
            completed_craft=order.craft, color_snapshot=identity.get("color", ""), unit=unit, zone=zone,
            quality=MaterialStockQuality.AVAILABLE, quantity=good_pieces, source_type="OUTSOURCING_RETURN",
            source_id=record.pk, source_line_id=line_id, actor_employee=actor, snapshot=snapshot)
        stock_link = {"semi_finished_balance": movement.balance}
    OutsourcingReturnLine.objects.create(id=line_id, return_record=record, allocation_id=context["allocation_id"],
        returned_quantity=good_pieces, quality=MaterialStockQuality.AVAILABLE, **stock_link,
        snapshot=movement.snapshot)
    from .original_order_services import update_original_return_status
    update_original_return_status(order)
    _bump_original_order(order, actor, request, "DIRECT_GOOD_RETURN_CONFIRMED", before)
    return original_good_return_context(handoff, request)


def _handoff_return_state(handoff):
    returned = sum(row.returned_pieces for row in handoff.unsprayed_returns.all())
    try:
        allocation = _original_allocation(handoff.source, handoff.original_order, handoff.factory_id)
    except ValidationError as exc:
        return {"returned_unsprayed_pieces": returned, "remaining_return_pieces": 0,
                "return_blockers": exc.detail}
    totals = original_handoff_totals(allocation)
    remaining = min(handoff.handoff_pieces - returned,
                    totals["handoff_pieces"] - totals["returned_pieces"] - totals["returned_unsprayed_pieces"])
    return {"original_order_status": handoff.original_order.status, "returned_unsprayed_pieces": returned,
            "original_allocation_returned_pieces": str(totals["returned_pieces"]),
            "remaining_return_pieces": max(int(remaining), 0)}


def _source_result(source, line, request=None):
    handoffs = source.original_handoffs.all()
    if request is not None:
        handoffs = scoped_records(handoffs, request, "material_issues.view_metalprocessingsource", "original_order__craft_id")
    line.processing_source = source
    result = source_data(line, detail=True)
    result["original_handoffs"] = [
        {
            "id": str(row.pk), "original_order_id": str(row.original_order_id),
            "original_order_number": row.original_order.order_number,
            "factory_id": str(row.factory_id), "factory_name": row.factory.name,
            "handoff_pieces": row.handoff_pieces,
            "handoff_date": row.handoff_date.isoformat(),
            **_handoff_return_state(row),
            "unsprayed_returns": [
                unsprayed_return_result(item) | {
                    "completed_rework_pieces": sum(rework.completed_pieces for rework in item.reworks.all()),
                    "remaining_rework_pieces": item.returned_pieces - sum(rework.completed_pieces for rework in item.reworks.all()),
                    "reworks": [rework_result(rework, request) for rework in item.reworks.all()],
                }
                for item in row.unsprayed_returns.all()
            ],
        }
        for row in handoffs.select_related("factory", "source", "original_order__schedule", "original_order__craft").prefetch_related(
            "unsprayed_returns", "unsprayed_returns__reworks",
        ).all()
    ]
    return result


ALLOCATION_AUDIT_OBJECT = "METAL_PROCESSING_EXTERNAL_ORDER"
ALLOCATION_AUDIT_ACTION = "ALLOCATION_ADJUSTED"


def _allocation_context(order, request=None):
    # 已交接、已结清和已完成单都已使用过实物，继续占用本次重加工完成量。
    other = order.rework.external_orders.exclude(pk=order.pk).aggregate(total=Sum("allocated_pieces"))["total"] or 0
    maximum = order.rework.completed_pieces - other
    blockers = []
    if order.status != MetalProcessingExternalOrderStatus.PENDING_HANDOFF or order.handoff_pieces or getattr(order, "handoff", None):
        blockers.append("只有待交接且实际交接为0的新外发单可以调整分配。")
    if maximum <= 0:
        blockers.append("本次重新加工完成量已无可分配支数。")
    if request is None or not can_record(request, "material_issues.change_metalprocessingexternalorder", "external", order.pk):
        blockers.append("当前账号没有调整新外发单分配的权限。")
    return {"part_name": order.source.source_snapshot.get("part_name", ""),
            "issue_number": order.source.source_snapshot.get("issue_number", ""),
            "rework_completed_pieces": order.rework.completed_pieces, "other_allocated_pieces": other,
            "max_allocatable_pieces": max(maximum, 0),
            "remaining_allocatable_pieces": max(maximum - order.allocated_pieces, 0),
            "can_adjust": not blockers, "blockers": blockers}


def _order_result(order, request=None):
    closure = getattr(order, "closure", None)
    handoff = getattr(order, "handoff", None)
    return {
        "id": str(order.pk), "order_number": order.order_number,
        "stock_mode": order.stock_mode, "public_output_identity": order.output_identity_snapshot or None,
        "source_id": str(order.source_id), "rework_id": str(order.rework_id),
        "original_return_id": str(order.original_return_id), "factory_id": str(order.factory_id),
        "factory_name": order.factory.name, "craft_id": str(order.craft_id),
        "craft_name": order.craft.name, "allocated_pieces": order.allocated_pieces,
        "handoff_pieces": order.handoff_pieces, "returned_good_pieces": order.returned_good_pieces,
        "remaining_return_pieces": order.handoff_pieces - order.returned_good_pieces,
        "status": order.status, "version": order.version, "etag": _p4_order_etag(order),
        "allocation_context": _allocation_context(order, request),
        "allocation_history": [
            {"id": str(row.pk), "before_pieces": row.before_data["allocated_pieces"],
             "after_pieces": row.after_data["allocated_pieces"],
             "actor_employee_id": str(row.actor_employee_id) if row.actor_employee_id else None,
             "actor_name": row.actor_name_snapshot, "created_at": row.occurred_at.isoformat()}
            for row in AuditLog.objects.filter(object_type=ALLOCATION_AUDIT_OBJECT, object_id=order.pk,
                                               action=ALLOCATION_AUDIT_ACTION).order_by("-occurred_at", "-id")
        ],
        "handoff": None if handoff is None else {
            "id": str(handoff.pk), "handoff_pieces": handoff.handoff_pieces,
            "handoff_date": handoff.handoff_date.isoformat(),
        },
        "good_returns": [
            {
                "id": str(row.pk), "return_number": row.return_number,
                "good_pieces": row.good_pieces, "zone_id": str(row.zone_id),
                "return_date": row.return_date.isoformat(), "post_closure": row.post_closure,
                "remark": row.remark,
                "actor_employee_id": row.snapshot.get("actor_employee_id"),
                "actor_name": row.snapshot.get("actor_name", ""), "created_at": row.created_at.isoformat(),
            }
            for row in order.good_returns.select_related("zone").all()
        ],
        "closure": None if closure is None else {
            "id": str(closure.pk), "remark": closure.remark,
            "quantity_snapshot": closure.quantity_snapshot,
            "created_at": closure.created_at.isoformat(),
        },
    }


@stock_write_transaction
def create_original_handoff(*, request, issue_line_id, request_id, original_order_id, factory_id,
                            handoff_pieces, handoff_date):
    require_record(request, "material_issues.create_metalprocessingoriginalhandoff", "original", original_order_id)
    if resource_scopes.enabled():
        get_object_or_404(processing_lines(request), pk=issue_line_id)
    actor = _require_permission(request, "create_metalprocessingoriginalhandoff")
    lock_request("metal-p4-original-handoff", request_id)
    payload = {"issue_line_id": str(issue_line_id), "original_order_id": str(original_order_id),
               "factory_id": str(factory_id), "handoff_pieces": handoff_pieces,
               "handoff_date": str(handoff_date)}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingOriginalHandoff.objects.filter(request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同原外发交接内容。")
        return _source_result(existing.source, existing.source.issue_line, request)

    # 与新版金工入库、待发预留共用产品锁，先锁产品范围再取得单个旧来源锁。
    # 不能等看到入库记录后才加锁，否则并发的第一笔入库可能被遗漏。
    from apps.inventory.tube_processing_services import (
        assert_tube_quantity_available, lock_tube_product_scope, metal_component_limits,
    )
    hint = get_object_or_404(processing_lines(request).values('issue__product_line_id'), pk=issue_line_id)
    product_id = hint['issue__product_line_id']
    lock_tube_product_scope(product_id)
    line, source, snapshot = _source_for_request(request, issue_line_id)
    _require_source_etag(request, line, source, snapshot)
    if source.original_handoffs.filter(public_transition__isnull=False).exists():
        raise Conflict("该旧来源已按既有交接接续，不能继续新增旧交接；请先核对剩余在制件。")
    if source.status == "CLOSED":
        raise Conflict("原金工来源已结清，不能继续新增原外发交接。")
    if handoff_pieces <= 0:
        raise ValidationError({"handoff_pieces": "交接支数必须为正整数。"})
    available = source.completed_pieces - source.dispatched_pieces - source.reserved_pieces - source.internal_received_pieces
    if handoff_pieces > available:
        raise Conflict("交接支数超过当前可外发完成量。")
    from apps.inventory.models import InternalSemiFinishedReceipt
    from apps.outsourcing.models import TubeOutsourcingOrder
    new_quantity_flow = (
        getattr(settings, 'TUBE_OUTSOURCING_ENABLED', False)
        or InternalSemiFinishedReceipt.objects.filter(
            schedule_product__product_line_id=product_id, plan_category='METAL',
            source_snapshot__quantity_basis='WORK_REPORT_MINIMUM',
        ).exists()
        or TubeOutsourcingOrder.objects.filter(
            product_line_id=product_id, source_kind='METAL', status__in=['PENDING_DISPATCH', 'PROCESSING', 'COMPLETED'],
        ).exists()
    )
    if new_quantity_flow:
        basis = metal_component_limits(product_id)
        assert_tube_quantity_available(
            product_line_id=product_id,
            requested={str(line.requirement.component_identity): handoff_pieces},
            expected_revision=basis['revision'],
        )
    original_order = get_object_or_404(
        accessible_outsourcing_orders(request).select_for_update(of=("self",)).select_related("schedule", "craft"),
        pk=original_order_id,
    )
    if original_order.status in {OutsourcingOrderStatus.CLOSED, OutsourcingOrderStatus.COMPLETED, OutsourcingOrderStatus.CANCELLED}:
        raise Conflict("原外发单已结清、已完成或已取消，不能新增交接。")
    if OutsourcingDispatch.objects.filter(order=original_order).exists():
        raise Conflict("原外发单已有仓库原料发料记录，不能再混入金工直接交接。")
    factory = _active_factory(factory_id)
    allocation = _original_allocation(source, original_order, factory.pk)
    _require_source_mode(original_order, source)
    stock_identity = _source_stock_identity(source)
    output_identity = _source_output_identity(source, original_order.craft) if original_order.stock_mode == "PUBLIC_V2" else None
    comparison_identity = {**stock_identity, "public_output_identity": output_identity} if output_identity else stock_identity
    if any(_handoff_stock_identity(row) != comparison_identity for row in _allocation_handoffs(allocation)):
        raise Conflict("该分配已有不同冻结部位、颜色或单位的直接交接，不能合并。")
    totals = original_handoff_totals(allocation)
    from .original_order_services import cancelled_pending_pieces
    if totals["handoff_pieces"] + handoff_pieces > allocation.allocated_quantity - cancelled_pending_pieces(allocation):
        raise Conflict("累计实际交接支数超过原外发单该部位加工厂分配量。")
    from apps.outsourcing.services import order_audit_snapshot
    before = order_audit_snapshot(original_order)
    record = MetalProcessingOriginalHandoff.objects.create(
        source=source, original_order=original_order, factory=factory,
        handoff_pieces=handoff_pieces, handoff_date=handoff_date, actor_employee=actor,
        request_id=request_id, request_payload_hash=request_hash,
        snapshot={"source": snapshot, "stock_identity": stock_identity, "allocation_id": str(allocation.pk), "original_order_number": original_order.order_number,
                  "factory_name": factory.name, "handoff_pieces": handoff_pieces,
                  **({"public_output_identity": output_identity} if output_identity else {})},
    )
    source.dispatched_pieces += handoff_pieces
    source.version += 1
    source.save(update_fields=["dispatched_pieces", "version", "updated_at"])
    if original_order.status == OutsourcingOrderStatus.PENDING_DISPATCH:
        original_order.status = OutsourcingOrderStatus.PROCESSING
    _bump_original_order(original_order, actor, request, "DIRECT_HANDOFF_CONFIRMED", before)
    source.refresh_from_db()
    return _source_result(source, line, request) | {"operation_id": str(record.pk)}


@stock_write_transaction
def create_unsprayed_return(*, request, handoff_id, request_id, returned_pieces, received_by_employee_id,
                            storage_location, return_date, remark):
    require_record(request, "material_issues.register_metalprocessingunsprayedreturn", "handoff", handoff_id)
    actor = _require_permission(request, "register_metalprocessingunsprayedreturn")
    lock_request("metal-p4-unsprayed-return", request_id)
    payload = {"handoff_id": str(handoff_id), "returned_pieces": returned_pieces,
               "received_by_employee_id": str(received_by_employee_id),
               "storage_location": storage_location, "return_date": str(return_date), "remark": remark}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingUnsprayedReturn.objects.filter(request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同退回内容。")
        get_object_or_404(processing_lines(request), pk=existing.original_handoff.source.issue_line_id)
        get_object_or_404(accessible_outsourcing_orders(request), pk=existing.original_handoff.original_order_id)
        if existing.snapshot.get("actor_employee_id") != str(actor.pk):
            raise Conflict("相同请求标识不能用于不同操作人。")
        return unsprayed_return_result(existing)
    handoff = get_object_or_404(
        MetalProcessingOriginalHandoff.objects.select_for_update(of=("self",)).select_related("source__issue_line__issue", "original_order", "factory"),
        pk=handoff_id,
    )
    line, source, snapshot = _source_for_request(request, handoff.source.issue_line_id)
    _require_source_etag(request, line, source, snapshot)
    original_order = get_object_or_404(
        accessible_outsourcing_orders(request).select_for_update(of=("self",)).select_related("schedule", "craft"),
        pk=handoff.original_order_id,
    )
    if original_order.status in {OutsourcingOrderStatus.COMPLETED, OutsourcingOrderStatus.CANCELLED}:
        raise Conflict("原外发单已完成或已取消，不能新增未喷塑退回。")
    post_closure = original_order.status == OutsourcingOrderStatus.CLOSED
    remark = remark.strip()
    if post_closure:
        from .original_order_services import original_closure_data
        if original_closure_data(original_order) is None:
            raise Conflict("原单缺少结清快照，请先核对。")
        if not remark:
            raise ValidationError({"remark": "原单结清后补登记必须填写原因备注。"})
    handoff.original_order = original_order
    handoff.source = source
    allocation = _allocation_for_handoff(handoff)
    if trusted_handoff_transition(handoff) is not None:
        require_original_handoff_mode(original_order, list(_allocation_handoffs(allocation).order_by("id")))
    if OutsourcingDispatch.objects.filter(order=original_order).exists():
        raise Conflict("原单同时存在原料发料和直接交接，请先核对混合来源。")
    totals = original_handoff_totals(allocation)
    employee = _active_employee(received_by_employee_id)
    storage_location = storage_location.strip()
    if returned_pieces <= 0:
        raise ValidationError({"returned_pieces": "退回支数必须为正整数。"})
    already = handoff.unsprayed_returns.aggregate(total=Sum("returned_pieces"))["total"] or 0
    if already + returned_pieces > handoff.handoff_pieces:
        raise Conflict("未喷塑退回支数超过该次实际交接支数。")
    if totals["returned_pieces"] + totals["returned_unsprayed_pieces"] + returned_pieces > totals["handoff_pieces"]:
        raise Conflict("已回货及未喷塑退回累计超过原外发单该部位实际交接支数。")
    from apps.outsourcing.services import order_audit_snapshot
    before = order_audit_snapshot(original_order)
    record = MetalProcessingUnsprayedReturn.objects.create(
        original_handoff=handoff, returned_pieces=returned_pieces, received_by_employee=employee,
        storage_location=storage_location, remark=remark, return_date=return_date,
        request_id=request_id, request_payload_hash=request_hash,
        snapshot={"source": snapshot, "handoff_id": str(handoff.pk),
                  "original_order_number": handoff.original_order.order_number,
                  "factory_name": handoff.factory.name, "returned_pieces": returned_pieces,
                  "allocation_id": str(allocation.pk), "post_closure": post_closure,
                  "actor_employee_id": str(actor.pk), "actor_name": actor.display_name},
    )
    from .original_order_services import update_original_return_status
    update_original_return_status(original_order)
    _bump_original_order(original_order, actor, request, "DIRECT_UNSPRAYED_RETURN_CONFIRMED", before)
    return unsprayed_return_result(record)


def unsprayed_return_result(record):
    return {
        "id": str(record.pk), "handoff_id": str(record.original_handoff_id),
        "source_id": str(record.original_handoff.source_id),
        "original_order_id": str(record.original_handoff.original_order_id),
        "returned_pieces": record.returned_pieces,
        "received_by_employee_id": str(record.received_by_employee_id),
        "storage_location": record.storage_location, "return_date": record.return_date.isoformat(),
        "remark": record.remark, "inventory_effect": "NONE",
        "post_closure": bool(record.snapshot.get("post_closure")),
        "actor_employee_id": record.snapshot.get("actor_employee_id"),
        "actor_name": record.snapshot.get("actor_name", ""),
        "created_at": record.created_at.isoformat(),
    }


@stock_write_transaction
def create_rework(*, request, unsprayed_return_id, request_id, completed_pieces, completion_date):
    require_record(request, "material_issues.register_metalprocessingrework", "return", unsprayed_return_id)
    actor = _require_permission(request, "register_metalprocessingrework")
    lock_request("metal-p4-rework", request_id)
    payload = {"unsprayed_return_id": str(unsprayed_return_id), "completed_pieces": completed_pieces,
               "completion_date": str(completion_date)}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingRework.objects.filter(request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同重新加工内容。")
        return rework_result(existing, request)
    record = get_object_or_404(
        MetalProcessingUnsprayedReturn.objects.select_for_update(of=("self",)).select_related("original_handoff__source__issue_line__issue"),
        pk=unsprayed_return_id,
    )
    line, source, snapshot = _source_for_request(request, record.original_handoff.source.issue_line_id)
    if trusted_handoff_transition(record.original_handoff) is not None:
        allocation = _allocation_for_handoff(record.original_handoff)
        require_original_handoff_mode(record.original_handoff.original_order, list(_allocation_handoffs(allocation).order_by("id")))
    if completed_pieces <= 0:
        raise ValidationError({"completed_pieces": "重新加工合格支数必须为正整数。"})
    already = record.reworks.aggregate(total=Sum("completed_pieces"))["total"] or 0
    if already + completed_pieces > record.returned_pieces:
        raise Conflict("重新加工完成支数超过暂存退回支数。")
    rework = MetalProcessingRework.objects.create(
        unsprayed_return=record, source=source, completed_pieces=completed_pieces,
        completion_date=completion_date, actor_employee=actor, request_id=request_id,
        request_payload_hash=request_hash,
        snapshot={"source": snapshot, "unsprayed_return_id": str(record.pk), "completed_pieces": completed_pieces},
    )
    return rework_result(rework, request)


def rework_result(record, request=None):
    visible_orders = record.external_orders.all()
    if request is not None:
        visible_orders = scoped_records(visible_orders, request, "material_issues.view_metalprocessingsource")
    allocated = record.external_orders.aggregate(total=Sum("allocated_pieces"))["total"] or 0
    return {
        "id": str(record.pk), "unsprayed_return_id": str(record.unsprayed_return_id),
        "source_id": str(record.source_id), "completed_pieces": record.completed_pieces,
        "allocated_pieces": allocated, "remaining_allocatable_pieces": record.completed_pieces - allocated,
        "completion_date": record.completion_date.isoformat(), "external_order_ids": [str(row.pk) for row in visible_orders],
    }


def _validate_p4_factory_craft(factory_id, craft_id):
    factory = _active_factory(factory_id)
    craft = Craft.objects.filter(
        pk=craft_id, craft_type=CraftType.EXTERNAL, outsourcing_code=OutsourcingCode.POWDER_COATING,
        status=RecordStatus.ACTIVE,
    ).first()
    if craft is None:
        raise ValidationError({"craft_id": "请选择当前有效的喷塑外发工艺。"})
    if not OutsourcingFactoryCraft.objects.filter(factory=factory, craft=craft).exists():
        raise ValidationError({"factory_id": "所选加工厂未关联当前喷塑工艺。"})
    return factory, craft


@stock_write_transaction
def create_external_order(*, request, rework_id, request_id, factory_id, craft_id, allocated_pieces):
    require_record(request, "material_issues.create_metalprocessingexternalorder", "rework", rework_id)
    resource_scopes.require_craft(request, "material_issues.create_metalprocessingexternalorder", craft_id)
    require_external_destination(request, rework_id, craft_id)
    actor = _require_permission(request, "create_metalprocessingexternalorder")
    lock_request("metal-p4-external-order", request_id)
    payload = {"rework_id": str(rework_id), "factory_id": str(factory_id), "craft_id": str(craft_id),
               "allocated_pieces": allocated_pieces}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingExternalOrder.objects.filter(client_request_id=request_id).first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同新外发单内容。")
        return _order_result(existing, request)
    rework = get_object_or_404(
        MetalProcessingRework.objects.select_for_update().select_related("source", "unsprayed_return"),
        pk=rework_id,
    )
    get_object_or_404(processing_lines(request), pk=rework.source.issue_line_id)
    factory, craft = _validate_p4_factory_craft(factory_id, craft_id)
    allocated = rework.external_orders.aggregate(total=Sum("allocated_pieces"))["total"] or 0
    if allocated_pieces <= 0 or allocated + allocated_pieces > rework.completed_pieces:
        raise Conflict("新外发分配支数超过本次重新加工完成支数。")
    origin_order = rework.unsprayed_return.original_handoff.original_order
    _require_source_mode(origin_order, rework.source)
    handoff = rework.unsprayed_return.original_handoff
    allocation = _allocation_for_handoff(handoff)
    public_mode = require_original_handoff_mode(origin_order, list(_allocation_handoffs(allocation).order_by("id")))
    output_identity = _rework_output_identity(rework, craft) if public_mode else {}
    order = MetalProcessingExternalOrder.objects.create(
        stock_mode="PUBLIC_V2" if public_mode else origin_order.stock_mode, output_identity_snapshot=output_identity,
        order_number=_order_number(), rework=rework, source=rework.source,
        original_return=rework.unsprayed_return, factory=factory, craft=craft,
        allocated_pieces=allocated_pieces, client_request_id=request_id,
        request_payload_hash=request_hash, created_by_employee=actor, updated_by_employee=actor,
    )
    return _order_result(order, request)


@stock_write_transaction
def adjust_external_allocation(*, request, order_id, request_id, allocated_pieces):
    require_record(request, "material_issues.change_metalprocessingexternalorder", "external", order_id)
    actor = _require_permission(request, "change_metalprocessingexternalorder")
    lock_request("metal-p4-allocation", request_id)
    # 每次重试也先检查独立数据范围，不能凭已成功的请求号访问他人单据。
    scoped_orders = MetalProcessingExternalOrder.objects.filter(source__issue_line__in=processing_lines(request))
    hint = get_object_or_404(scoped_orders, pk=order_id)
    request_hash = _payload_hash({"order_id": str(order_id), "actor_id": str(actor.pk),
                                  "allocated_pieces": allocated_pieces})
    existing = AuditLog.objects.filter(object_type=ALLOCATION_AUDIT_OBJECT, action=ALLOCATION_AUDIT_ACTION,
                                      after_data__client_request_id=str(request_id)).first()
    if existing:
        if existing.object_id != hint.pk or existing.after_data.get("request_payload_hash") != request_hash:
            raise Conflict("相同请求标识已用于不同分配调整内容或操作人。")
        return _order_result(hint, request)
    # 与创建新外发单共用重加工记录锁，先锁共享上限，再锁本单，防止两单同时超占。
    rework = MetalProcessingRework.objects.select_for_update(of=("self",)).get(pk=hint.rework_id)
    order = get_object_or_404(scoped_orders.select_for_update(of=("self",)).select_related("factory", "craft"), pk=order_id)
    order.rework = rework
    _require_order_etag(request, order)
    context = _allocation_context(order, request)
    if not context["can_adjust"]:
        raise Conflict("；".join(context["blockers"]))
    if isinstance(allocated_pieces, bool) or not isinstance(allocated_pieces, int) or allocated_pieces <= 0:
        raise ValidationError({"allocated_pieces": "分配支数必须为正整数。"})
    if allocated_pieces > context["max_allocatable_pieces"]:
        raise Conflict("分配支数超过本次重加工完成量扣除其他外发单占用后的可分配上限。")
    before = {"allocated_pieces": order.allocated_pieces, "version": order.version}
    order.allocated_pieces = allocated_pieces
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["allocated_pieces", "version", "updated_by_employee", "updated_at"])
    write_audit_log(object_type=ALLOCATION_AUDIT_OBJECT, object_id=order.pk, action=ALLOCATION_AUDIT_ACTION,
        actor_employee=actor, before_data=before,
        after_data={"allocated_pieces": order.allocated_pieces, "version": order.version,
                    "client_request_id": str(request_id), "request_payload_hash": request_hash},
        context_type="METAL_PROCESSING_REWORK", context_id=rework.pk, request=request)
    return _order_result(order, request)


@stock_write_transaction
def confirm_external_handoff(*, request, order_id, request_id, handoff_date, handoff_pieces):
    require_record(request, "material_issues.confirm_metalprocessingexternalhandoff", "external", order_id)
    actor = _require_permission(request, "confirm_metalprocessingexternalhandoff")
    lock_request("metal-p4-external-handoff", request_id)
    payload = {"order_id": str(order_id), "handoff_date": str(handoff_date), "handoff_pieces": handoff_pieces}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingExternalHandoff.objects.filter(request_id=request_id).select_related("order").first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同新外发交接内容。")
        return _order_result(existing.order, request)
    order = get_object_or_404(MetalProcessingExternalOrder.objects.select_for_update().select_related("factory", "craft"), pk=order_id)
    _require_order_etag(request, order)
    if order.status != MetalProcessingExternalOrderStatus.PENDING_HANDOFF:
        raise Conflict("只有待交接的新外发单可以确认交接。")
    if handoff_pieces != order.allocated_pieces:
        raise ValidationError({"handoff_pieces": "新外发实际交接支数必须等于已保存分配支数。"})
    _require_source_mode(order, order.source)
    output_identity = _public_external_identity(order) if order.stock_mode == "PUBLIC_V2" else None
    handoff = MetalProcessingExternalHandoff.objects.create(
        order=order, handoff_pieces=handoff_pieces, handoff_date=handoff_date,
        actor_employee=actor, request_id=request_id, request_payload_hash=request_hash,
        snapshot={"order_number": order.order_number, "factory_name": order.factory.name,
                  "handoff_pieces": handoff_pieces,
                  **({"public_output_identity": output_identity} if output_identity else {})},
    )
    order.handoff_pieces = handoff_pieces
    order.status = MetalProcessingExternalOrderStatus.PROCESSING
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["handoff_pieces", "status", "version", "updated_by_employee", "updated_at"])
    return _order_result(order, request) | {"operation_id": str(handoff.pk)}


def _p4_stock_identity(order):
    line = MaterialIssueLine.objects.select_related("issue__production_task", "issue__product_line", "unit").get(
        pk=order.source.issue_line_id,
    )
    snapshot = order.source.source_snapshot
    try:
        from apps.boms.models import BomLine
        bom_line = BomLine.objects.get(pk=snapshot["conversion_snapshot"]["bom_line_id"])
    except (KeyError, BomLine.DoesNotExist) as exc:
        raise ValidationError({"source": "原管材来源缺少有效 BOM 部位，不能入半成品仓。"}) from exc
    return line, line.issue.production_task, line.issue.product_line, bom_line


@stock_write_transaction
def confirm_external_good_return(*, request, order_id, request_id, good_pieces, zone_id,
                                 received_by_employee_id, return_date, remark):
    require_record(request, "material_issues.confirm_metalprocessingexternalreturn", "external", order_id)
    actor = _require_permission(request, "confirm_metalprocessingexternalreturn")
    lock_request("metal-p4-external-good-return", request_id)
    payload = {"order_id": str(order_id), "good_pieces": good_pieces, "zone_id": str(zone_id),
               "received_by_employee_id": str(received_by_employee_id), "return_date": str(return_date),
               "remark": remark}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingExternalGoodReturn.objects.filter(request_id=request_id).select_related("order").first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同合格回货内容。")
        return _order_result(existing.order, request)
    order = get_object_or_404(MetalProcessingExternalOrder.objects.select_for_update(of=("self",)).select_related("factory", "craft", "source"), pk=order_id)
    get_object_or_404(processing_lines(request), pk=order.source.issue_line_id)
    _require_source_mode(order, order.source)
    public_mode = require_document_stock_mode(order)
    _require_order_etag(request, order)
    if order.status not in {MetalProcessingExternalOrderStatus.PROCESSING, MetalProcessingExternalOrderStatus.CLOSED}:
        raise Conflict("只有加工中或已结清的新外发单可以登记合格回货。")
    if order.status == MetalProcessingExternalOrderStatus.CLOSED and not remark.strip():
        raise ValidationError({"remark": "结清后的追加回货必须填写原因备注。"})
    handoff = getattr(order, "handoff", None)
    if handoff is None:
        raise Conflict("新外发单尚未确认实际交接。")
    if good_pieces <= 0:
        raise ValidationError({"good_pieces": "合格回货支数必须为正整数。"})
    if order.returned_good_pieces + good_pieces > order.handoff_pieces:
        raise Conflict("合格回货累计支数不能超过实际交接支数。")
    line, task, product_line, bom_line = _p4_stock_identity(order)
    output_identity = _public_external_identity(order, require_handoff=True) if public_mode else None
    # 与半成品领料、库存服务统一先锁任务再锁库区，避免双方互相等待。
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    if public_mode:
        from apps.boms.models import BomLine
        from apps.production_tasks.models import ProductionTaskProduct
        product_line = ProductionTaskProduct.objects.select_for_update(of=("self",), no_key=True).get(pk=product_line.pk)
        bom_line = BomLine.objects.select_for_update(of=("self",), no_key=True).get(pk=bom_line.pk)
    zones = WarehouseZone.objects.all() if public_mode else WarehouseZone.objects.select_for_update(of=("self",))
    zone = get_object_or_404(zones.select_related("warehouse"), pk=zone_id)
    if zone.status != "ACTIVE" or zone.warehouse.status != "ACTIVE" or zone.warehouse.warehouse_type != WarehouseType.SEMI_FINISHED:
        raise ValidationError({"zone_id": "合格回货只能进入启用的半成品库区。"})
    receiver = _active_employee(received_by_employee_id)
    record = MetalProcessingExternalGoodReturn.objects.create(
        order=order, return_number=_return_number(), good_pieces=good_pieces, zone=zone,
        received_by_employee=receiver, return_date=return_date, remark=remark,
        post_closure=order.status == MetalProcessingExternalOrderStatus.CLOSED,
        request_id=request_id, request_payload_hash=request_hash,
        snapshot={"order_number": order.order_number, "source_id": str(order.source_id),
                  "factory_name": order.factory.name, "part_name": order.source.source_snapshot.get("part_name", line.material_name_snapshot),
                  "component_identity": order.source.source_snapshot.get("component_identity"),
                  "quality": MaterialStockQuality.AVAILABLE, "good_pieces": good_pieces,
                   "actor_employee_id": str(actor.pk), "actor_name": actor.display_name,
                   **({"public_output_identity": output_identity,
                       "color": output_identity["identity_snapshot"]["color"],
                       "unit": output_identity["identity_snapshot"]["unit_name"]} if output_identity else {})},
    )
    if public_mode:
        movement = credit_public_stock(identity=output_identity, zone=zone, quantity=good_pieces,
            source_type="METAL_P4_EXTERNAL_RETURN", source_id=order.pk, source_line_id=record.pk,
            actor_employee=actor, production_task=task, product_line=product_line, bom_line=bom_line,
            snapshot=record.snapshot)
        record.public_stock_movement = movement
        record.snapshot = {**record.snapshot, "public_stock_balance_id": str(movement.balance_id)}
    else:
        movement = credit_semi_finished_stock(
            production_task=task, product_line=product_line, bom_line=bom_line,
            completed_craft=order.craft, color_snapshot=line.color_snapshot,
            unit=line.unit, zone=zone, quality=MaterialStockQuality.AVAILABLE,
            quantity=good_pieces, source_type="METAL_P4_EXTERNAL_RETURN", source_id=order.pk,
            source_line_id=record.pk, actor_employee=actor, snapshot=record.snapshot,
        )
        record.snapshot = {**record.snapshot, "semi_finished_balance_id": str(movement.balance_id)}
    record.save(update_fields=["snapshot", "public_stock_movement", "updated_at"])
    order.returned_good_pieces += good_pieces
    if order.returned_good_pieces == order.handoff_pieces:
        order.status = MetalProcessingExternalOrderStatus.COMPLETED
        order.completed_at = timezone.now()
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["returned_good_pieces", "status", "completed_at", "version", "updated_by_employee", "updated_at"])
    return _order_result(order, request) | {"operation_id": str(record.pk)}


@stock_write_transaction
def close_external_order(*, request, order_id, request_id, remark):
    require_record(request, "material_issues.close_metalprocessingexternalorder", "external", order_id)
    actor = _require_permission(request, "close_metalprocessingexternalorder")
    lock_request("metal-p4-external-close", request_id)
    payload = {"order_id": str(order_id), "remark": remark}
    request_hash = _payload_hash(payload)
    existing = MetalProcessingExternalClosure.objects.filter(request_id=request_id).select_related("order").first()
    if existing:
        if existing.request_payload_hash != request_hash:
            raise Conflict("相同请求标识已用于不同新外发结清内容。")
        return _order_result(existing.order, request)
    order = get_object_or_404(MetalProcessingExternalOrder.objects.select_for_update().select_related("factory", "craft"), pk=order_id)
    _require_order_etag(request, order)
    if order.status != MetalProcessingExternalOrderStatus.PROCESSING:
        raise Conflict("只有加工中的新外发单可以备注结清。")
    remark = remark.strip()
    if not remark:
        raise ValidationError({"remark": "结清备注去除空格后不能为空。"})
    handoff = getattr(order, "handoff", None)
    if handoff is None:
        raise Conflict("新外发单尚未确认实际交接。")
    closure = MetalProcessingExternalClosure.objects.create(
        order=order, remark=remark,
        quantity_snapshot={"handoff_pieces": order.handoff_pieces,
                           "returned_good_pieces": order.returned_good_pieces,
                           "difference_pieces": order.handoff_pieces - order.returned_good_pieces},
        actor_employee=actor, request_id=request_id, request_payload_hash=request_hash,
    )
    order.status = MetalProcessingExternalOrderStatus.CLOSED
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["status", "version", "updated_by_employee", "updated_at"])
    return _order_result(order, request) | {"operation_id": str(closure.pk)}


def available_p4_semi_identity(order):
    """返回该 P4 外发单对应部位的合格半成品总量；不按批次分配。"""
    if order.stock_mode == "PUBLIC_V2":
        from apps.inventory.models import PublicStockBalance
        identity = _public_external_identity(order)
        balances = list(PublicStockBalance.objects.select_related("zone__warehouse").filter(
            stock_kind="SEMI", identity_key=identity["identity_key"], unit_id=identity["unit_id"],
            unit__unit_name="支", unit__status="ACTIVE", unit__archived_at__isnull=True,
            quality=MaterialStockQuality.AVAILABLE, zone__status="ACTIVE", zone__warehouse__status="ACTIVE",
            zone__warehouse__warehouse_type=WarehouseType.SEMI_FINISHED, quantity__gt=0,
        ))
        if any(row.identity_snapshot != identity["identity_snapshot"] for row in balances):
            raise Conflict("公共半成品余额属性与冻结产物身份不一致，请先核对。")
        total = sum((row.quantity for row in balances), Decimal("0"))
        zones = [{"zone_id": str(row.zone_id), "zone_name": f"{row.zone.warehouse.warehouse_name} / {row.zone.zone_name}",
                  "available_pieces": str(row.quantity)} for row in balances]
        return {"stock_mode": "PUBLIC_V2", "public_output_identity": identity,
                "production_task_id": str(order.source.issue_line.issue.production_task_id),
                "product_line_id": str(order.source.issue_line.issue.product_line_id),
                "bom_line_id": order.source.source_snapshot["conversion_snapshot"]["bom_line_id"],
                "component_identity": order.source.source_snapshot.get("component_identity"),
                "part_name": identity["identity_snapshot"]["part_name"],
                "completed_craft_id": str(order.craft_id), "unit": "支", "available_pieces": str(total),
                "integer_required": True, "whole_bar_required": False, "batch_selection": False, "zones": zones}
    from apps.inventory.models import SemiFinishedStockBalance
    line, task, product_line, bom_line = _p4_stock_identity(order)
    balances = SemiFinishedStockBalance.objects.select_related("zone__warehouse").filter(
        production_task_id=task.pk, product_line_id=product_line.pk, bom_line_id=bom_line.pk,
        completed_craft_id=order.craft_id, color_snapshot=(line.color_snapshot or "").strip(),
        unit_id=line.unit_id, quality=MaterialStockQuality.AVAILABLE,
        zone__status="ACTIVE", zone__warehouse__status="ACTIVE", zone__warehouse__warehouse_type=WarehouseType.SEMI_FINISHED,
        quantity__gt=0,
    )
    total = sum((row.quantity for row in balances), Decimal("0"))
    zones = {}
    for row in balances:
        item = zones.setdefault(str(row.zone_id), {"zone_id": str(row.zone_id), "zone_name": f"{row.zone.warehouse.warehouse_name} / {row.zone.zone_name}", "available_pieces": Decimal("0")})
        item["available_pieces"] += row.quantity
    return {"production_task_id": str(task.pk), "product_line_id": str(product_line.pk),
            "bom_line_id": str(bom_line.pk), "component_identity": order.source.source_snapshot.get("component_identity"),
            "part_name": order.source.source_snapshot.get("part_name", line.material_name_snapshot),
            "unit": line.unit_snapshot, "available_pieces": str(total),
            "integer_required": True, "whole_bar_required": False,
            "zones": [{**item, "available_pieces": str(item["available_pieces"])} for item in zones.values()],
            "batch_selection": False}
