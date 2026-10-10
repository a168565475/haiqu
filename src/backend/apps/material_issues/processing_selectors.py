"""金工加工来源只读查询：不回填旧数据，不读取最新 BOM 重算。"""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Exists, OuterRef, Prefetch, Q
from rest_framework.exceptions import ValidationError

from .models import MaterialIssueAuditEvent, MaterialIssueLine, MaterialIssuePublicStockAllocation
from .selectors import accessible_material_issues


MAX_PIECES = 99_999_999_999_999  # 已有领料 Decimal(18,4) 的整数上限。


def readable_processing_lines(request):
    from apps.access_control.resource_scopes import resource_ids, has_legacy_permission
    queryset = processing_lines(request)
    permission = 'material_issues.view_metalprocessingsource'
    ids = resource_ids(request, permission, 'CRAFT', include_legacy=False)
    if ids is None:
        return queryset
    # A shared source has no craft of its own. Only actual linked orders establish visibility.
    selected = queryset.filter(
        Q(processing_source__original_handoffs__original_order__craft_id__in=ids)
        | Q(processing_source__p4_external_orders__craft_id__in=ids)
    ).distinct()
    if has_legacy_permission(request, permission):
        selected = selected | processing_lines(request, scoped=False).distinct()
    return selected


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()


def processing_lines(request, *, scoped=True, permission=None):
    from apps.access_control.resource_scopes import current_permission, has_resource_grant, filter_crafts
    from apps.outsourcing.models import OutsourcingOrderProduct
    from .models import MaterialIssue, MetalProcessingExternalOrder
    permission = permission or current_permission(request, 'material_issues.view_metalprocessingsource')
    issues = accessible_material_issues(request)
    if scoped and has_resource_grant(request, permission, 'CRAFT'):
        products = filter_crafts(OutsourcingOrderProduct.objects.all(), request, permission, 'order__craft_id', include_legacy=False)
        issues = issues | MaterialIssue.objects.filter(
            Q(product_line_id__in=products.values('schedule_product__product_line_id'))
            | Q(lines__processing_source__p4_external_orders__in=filter_crafts(
                MetalProcessingExternalOrder.objects.all(),
                request, permission, include_legacy=False))
        )
    metal_origin = MaterialIssueAuditEvent.objects.filter(
        issue_id=OuterRef("issue_id"), action="CREATED", snapshot__plan_source__plan_category="METAL",
    )
    return MaterialIssueLine.objects.filter(
        issue__in=issues, issue__status="ISSUED",
        issue__workshop__name="金工车间", line_type="RAW", conversion_snapshot__kind="PIPE",
    ).annotate(has_metal_origin=Exists(metal_origin)).filter(has_metal_origin=True).select_related(
        "issue__product_line", "issue__production_task", "requirement", "processing_source",
    ).prefetch_related(
        "batch_allocations",
        Prefetch("public_stock_allocations", queryset=MaterialIssuePublicStockAllocation.objects.select_related(
            "movement", "balance",
        )),
        Prefetch("issue__audit_events", queryset=MaterialIssueAuditEvent.objects.filter(action="CREATED")),
    ).order_by("-issue__issued_at", "issue_id", "line_number", "id")


def frozen_source(line):
    """冻结资料有缺口即阻止操作；不根据现行 BOM 猜补。"""
    try:
        issue, snapshot, requirement = line.issue, line.conversion_snapshot, line.requirement
        quantity = line.issued_quantity
        if quantity is None or quantity != quantity.to_integral_value() or not 0 < quantity <= MAX_PIECES:
            raise ValueError("已出库支数无效")
        if issue.status != "ISSUED" or line.line_type != "RAW" or snapshot["kind"] != "PIPE":
            raise ValueError("不是已出库管材")
        if not issue.production_task_id or not issue.product_line_id or not requirement:
            raise ValueError("缺少任务、产品或部位")
        if (issue.product_line.production_task_id != issue.production_task_id
                or requirement.production_task_id != issue.production_task_id
                or requirement.product_line_id != issue.product_line_id
                or str(requirement.component_identity) != str(snapshot["component_identity"])
                or str(line.raw_material_id) != str(snapshot["raw_material_id"])
                or str(issue.product_line_id) != str(snapshot["product_line_id"])):
            raise ValueError("来源身份不一致")
        for key in ("component_identity", "raw_material_id", "product_line_id", "bom_line_id", "bom_id"):
            UUID(str(snapshot[key]))
        if not snapshot.get("source_revision_hash"):
            raise ValueError("缺少冻结版本")
        pieces_per_bar = Decimal(str(snapshot["pieces_per_bar"]))
        length = Decimal(str(snapshot["raw_bar_length_m"]))
        if (not pieces_per_bar.is_finite() or pieces_per_bar <= 0
                or pieces_per_bar != pieces_per_bar.to_integral_value()
                or not length.is_finite() or length <= 0):
            raise ValueError("换算快照无效")
        events = list(issue.audit_events.all())
        origin = next((event for event in events if event.action == "CREATED"), None)
        if not origin or origin.snapshot.get("plan_source", {}).get("plan_category") != "METAL":
            raise ValueError("缺少金工领料来源")
        if issue.stock_mode == "PUBLIC_V2":
            return _public_frozen_source(line, snapshot, quantity, pieces_per_bar, length, origin)
        batches = list(line.batch_allocations.all())
        if not batches or sum(row.requested_pieces for row in batches) != quantity:
            raise ValueError("缺少对应实际出库的批次快照")
        for row in batches:
            if (row.bar_count <= 0 or row.requested_pieces != row.bar_count * pieces_per_bar
                    or row.meters != row.bar_count * length or not row.snapshot):
                raise ValueError("批次支根米与冻结快照不符")
            batch = row.snapshot
            if (str(batch["inbound_line_id"]) != str(row.inbound_line_id)
                    or not batch["inbound_number"] or Decimal(str(batch["raw_bar_length_m"])) != length
                    or batch["source_unit"] != "支" or batch["material_unit"] != "根"):
                raise ValueError("批次身份、根长或单位快照缺失或不一致")
        return {
            "issue_line_id": str(line.pk), "issue_id": str(issue.pk), "issue_number": issue.issue_number,
            "production_task_id": str(issue.production_task_id), "product_line_id": str(issue.product_line_id),
            "workshop_id": str(issue.workshop_id), "component_identity": snapshot["component_identity"],
            "part_name": snapshot.get("part_name", ""), "material_number": line.material_number_snapshot,
            "issued_pieces": int(quantity), "conversion_snapshot": snapshot,
            "plan_source": origin.snapshot["plan_source"],
            "bar_count": sum(row.bar_count for row in batches),
            "meters": str(sum((row.meters for row in batches), Decimal(0))),
            "batches": [{"allocation_id": str(row.pk), "inbound_line_id": str(row.inbound_line_id),
                         "pieces": row.requested_pieces, "bar_count": row.bar_count, "meters": str(row.meters),
                         "snapshot": row.snapshot} for row in sorted(batches, key=lambda row: str(row.pk))],
        }
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation) as exc:
        raise ValidationError({"source": "领料冻结资料缺失或不一致，不能登记或结清；请核对原领料明细。"}) from exc


def _public_frozen_source(line, snapshot, quantity, pieces_per_bar, length, origin):
    """公共来源由已出库流水证明实领数量，不读取当前余额或采购批次。"""
    from apps.inventory.public_stock_identity import validate_public_identity
    from apps.inventory.stock_services import InventoryStockValidationError

    issue = line.issue
    try:
        identity = validate_public_identity(snapshot.get("public_identity"))
    except InventoryStockValidationError as exc:
        raise ValueError("公共原料身份不完整") from exc
    if (identity["stock_kind"] != "RAW_PIPE" or identity["raw_material_id"] != str(line.raw_material_id)
            or identity["raw_bar_length_m"] != length or line.unit_snapshot != "支"):
        raise ValueError("公共原料身份与领料换算不符")
    allocations = list(line.public_stock_allocations.all())
    if not allocations or sum(row.requested_quantity for row in allocations) != quantity:
        raise ValueError("缺少公共库存实际出库分配")
    frozen = []
    for row in sorted(allocations, key=lambda item: str(item.pk)):
        movement = row.movement
        balance = row.balance
        if (row.stock_quantity <= 0 or row.stock_quantity != row.stock_quantity.to_integral_value()
                or row.requested_quantity != row.stock_quantity * pieces_per_bar
                or row.meter_quantity != row.stock_quantity * length
                or row.snapshot.get("identity_key") != identity["identity_key"]
                or balance.stock_kind != "RAW_PIPE" or balance.identity_key != identity["identity_key"]
                or balance.identity_snapshot != identity["identity_snapshot"]
                or str(balance.raw_material_id) != identity["raw_material_id"]
                or str(balance.unit_id) != identity["unit_id"] or balance.raw_bar_length_m != length):
            raise ValueError("公共库存支根米或实物身份不一致")
        if (movement is None or movement.balance_id != row.balance_id or movement.direction != "OUT"
                or movement.source_type != "MATERIAL_ISSUE" or movement.source_id != issue.pk
                or movement.source_line_id != row.pk or movement.production_task_id != issue.production_task_id
                or movement.product_line_id != issue.product_line_id
                or str(movement.bom_line_id) != str(snapshot["bom_line_id"])
                or movement.quantity != row.stock_quantity or movement.meter_quantity != row.meter_quantity
                or movement.after_quantity != movement.before_quantity - movement.quantity
                or movement.after_meter_quantity != movement.before_meter_quantity - movement.meter_quantity
                or movement.snapshot.get("issue_line_id") != str(line.pk)
                or movement.snapshot.get("public_identity") != snapshot["public_identity"]
                or movement.snapshot.get("conversion") != snapshot):
            raise ValueError("公共库存实际扣减流水与领料不一致")
        frozen.append({"allocation_id": str(row.pk), "balance_id": str(row.balance_id),
                       "movement_id": str(movement.pk), "pieces": int(row.requested_quantity),
                       "bar_count": int(row.stock_quantity), "meters": str(row.meter_quantity),
                       "snapshot": row.snapshot})
    return {
        "schema_version": 2, "stock_mode": "PUBLIC_V2",
        "issue_line_id": str(line.pk), "issue_id": str(issue.pk), "issue_number": issue.issue_number,
        "production_task_id": str(issue.production_task_id), "product_line_id": str(issue.product_line_id),
        "workshop_id": str(issue.workshop_id), "component_identity": snapshot["component_identity"],
        "part_name": snapshot.get("part_name", ""), "material_number": line.material_number_snapshot,
        "issued_pieces": int(quantity), "conversion_snapshot": snapshot,
        "plan_source": origin.snapshot["plan_source"],
        "bar_count": sum(int(row.stock_quantity) for row in allocations),
        "meters": str(sum((row.meter_quantity for row in allocations), Decimal(0))),
        "batches": [], "public_stock_allocations": frozen,
    }


def quantity_state(source, issued_pieces):
    completed = source.completed_pieces if source else 0
    reserved = source.reserved_pieces if source else 0
    dispatched = source.dispatched_pieces if source else 0
    received = source.internal_received_pieces if source else 0
    closed = bool(source and source.status == "CLOSED")
    return {"issued_pieces": issued_pieces, "completed_pieces": completed,
            "dispatched_pieces": dispatched, "reserved_pieces": reserved,
            "internal_received_pieces": received,
            "unfinished_pieces": issued_pieces - completed,
            "unallocated_pieces": completed - dispatched - reserved - received,
            "available_pieces": 0 if closed else completed - dispatched - reserved - received,
            "remaining_completion_pieces": 0 if closed else issued_pieces - completed,
            "status": "CLOSED" if closed else "OPEN", "version": source.version if source else 0}


def source_etag(line, source, snapshot):
    return '"' + digest({"line_id": str(line.pk), "snapshot": snapshot,
                         "quantities": quantity_state(source, snapshot["issued_pieces"])}) + '"'


def source_data(line, *, detail=False):
    source = getattr(line, "processing_source", None)
    result = {"issue_line_id": str(line.pk), "source_id": str(source.pk) if source else None,
              "issue_number": line.issue.issue_number, "production_task_id": str(line.issue.production_task_id),
              "product_line_id": str(line.issue.product_line_id),
              "component_identity": line.conversion_snapshot.get("component_identity"),
              "part_name": line.conversion_snapshot.get("part_name", ""), "unit": "支"}
    try:
        snapshot = frozen_source(line)
        if source and source.source_hash != digest(snapshot):
            raise ValidationError({"source": "原领料冻结资料已变化，请核对来源。"})
    except ValidationError as exc:
        result.update(can_register=False, can_close=False, blockers=exc.detail, etag=None)
        return result
    quantities = quantity_state(source, snapshot["issued_pieces"])
    result.update(**quantities, etag=source_etag(line, source, snapshot),
                  bar_count=snapshot["bar_count"], meters=snapshot["meters"],
                  can_register=quantities["status"] == "OPEN" and quantities["remaining_completion_pieces"] > 0,
                  can_close=quantities["status"] == "OPEN" and quantities["reserved_pieces"] == 0,
                  blockers=(["存在待外发占用，请先交接或取消分配。"] if quantities["reserved_pieces"] else []))
    if detail:
        result["source_snapshot"] = source.source_snapshot if source else snapshot
        result["completions"] = [] if not source else [
            {"id": str(row.pk), "good_pieces": row.good_pieces, "completion_date": row.completion_date.isoformat(),
             "actor_employee_id": str(row.actor_employee_id), "actor_name": row.actor_employee.display_name,
             "created_at": row.created_at.isoformat(), "source_version": row.source_version}
            for row in source.completions.select_related("actor_employee").all()]
        closure = getattr(source, "closure", None) if source else None
        result["closure"] = None if not closure else {
            "remark": closure.remark, "quantities": closure.quantity_snapshot,
            "actor_employee_id": str(closure.actor_employee_id), "actor_name": closure.actor_employee.display_name,
            "created_at": closure.created_at.isoformat(), "source_version": closure.source_version}
    return result
