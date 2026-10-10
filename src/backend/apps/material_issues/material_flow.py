"""领料的部位及支根米口径；用户不选批次，确认出库时系统自动分配库存。"""
import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.boms.material_attributes import bom_attribute_fields
from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_issue
from apps.inventory.models import MaterialInboundLine, MaterialStockBalance, SemiFinishedStockBalance, WarehouseZone
from apps.inventory.pipe_stock_services import issue_pipe_material
from apps.inventory.stock_services import inbound_batch_available_quantities
from apps.outsourcing.dispatch_services import batch_candidates, confirmed_batches
from apps.products.material_identity import resolve_bom_line_raw_material
from apps.production_tasks.models import ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from .models import MaterialIssueBatchAllocation, OrderMaterialRequirement
from .pipe_requirements import PIPE_NAMESPACE, pipe_error, pipe_source_snapshot, sync_pipe_requirement


def pipe_specs(task_id, product_id):
    """沿用底座的稳定部位 ID；不能通过 GET 调用 sync_pipe_requirement。"""
    bom = Bom.objects.filter(production_task_id=task_id, product_line_id=product_id,
        archived_at__isnull=True).order_by("-version_number", "-id").first()
    if not bom or bom.status != "VERIFIED":
        return [], []
    product = ProductionTaskProduct.objects.get(pk=product_id)
    if product.quantity != bom.order_quantity:
        return [], []
    result, blockers = [], []
    unit = ProductionUnit.objects.filter(unit_name="支", archived_at__isnull=True, status="ACTIVE").first()
    for line in BomLine.objects.filter(section__bom=bom, cutting_length_mm__isnull=False).select_related("section__bom").order_by("id"):
        try:
            raw, _ = resolve_bom_line_raw_material(line)
            if not unit or not raw or raw.unit.unit_name != "根" or raw.category.category_name != "管材":
                raise pipe_error("MATERIAL_IDENTITY_UNRESOLVED", "管材须关联有效根制原料及支单位。")
            snapshot = {**pipe_source_snapshot(line, raw), "kind": "PIPE", "part_name": line.part_name}
            requirement_id = uuid.uuid5(PIPE_NAMESPACE, f"{task_id}:{product_id}:{line.component_identity}")
            result.append({"id": requirement_id, "line": line, "raw_material": raw, "unit": unit,
                "snapshot": snapshot, "revision": hashlib.sha256(json.dumps(pipe_source_snapshot(line, raw), sort_keys=True).encode()).hexdigest()})
        except ValidationError as error:
            blockers.append({"code": getattr(error, "api_error_code", "SOURCE_CHANGED"), "detail": str(error.detail),
                "product_line_id": str(product_id), "bom_line_id": str(line.pk), "section_code": "PROFILE"})
    return result, blockers


def pipe_requirement_rows(task_id, product_id, exclude_issue_id=None, *, public_stock=False):
    if public_stock:
        from .public_issue_services import public_pipe_requirement_rows
        return public_pipe_requirement_rows(task_id, product_id, exclude_issue_id=exclude_issue_id)
    from .services import pending_issue_quantities
    specs, blockers = pipe_specs(task_id, product_id)
    existing = {r.pk: r for r in OrderMaterialRequirement.objects.filter(pk__in=[s["id"] for s in specs])}
    pending, _ = pending_issue_quantities(requirement_ids=existing, exclude_issue_id=exclude_issue_id)
    # 管材候选只接受根制、同单根长度的批次；一次计算余量供各部位复用。
    lengths = {Decimal(spec["snapshot"]["raw_bar_length_m"]) for spec in specs}
    batches = list(confirmed_batches().filter(measurement_kind="PIPE", raw_bar_length_m__in=lengths)) if lengths else []
    available = inbound_batch_available_quantities(batches)
    rows = []
    for spec in specs:
        current, raw, snapshot = existing.get(spec["id"]), spec["raw_material"], spec["snapshot"]
        internal = current.internal_issued_quantity if current else 0
        external = current.outsourcing_issued_quantity if current else 0
        waiting = pending.get(spec["id"], 0)
        remaining = max(Decimal(snapshot["allowance_pieces"]) - internal - external - waiting, 0)
        candidates = batch_candidates(snapshot, batches, available)
        stock = sum((Decimal(row["available_input_quantity"]) for row in candidates), Decimal(0))
        rows.append({"requirement_id": str(spec["id"]), "stock_item_id": str(raw.pk), "line_type": "RAW", "section_code": "PROFILE",
            "material_number": raw.material_number, "material_name": raw.material_name, "specification": raw.specification,
            "part_names": [spec["line"].part_name] if spec["line"].part_name else [],
            "color": raw.color.color_name if raw.color_id else raw.color_snapshot, "unit": "支",
            "required_quantity": str(snapshot["allowance_pieces"]), "internal_issued_quantity": str(internal),
            "outsourcing_issued_quantity": str(external), "pending_issue_quantity": str(waiting), "order_remaining": str(remaining),
            "available_stock": str(stock), "max_issue_quantity": str(min(stock, remaining)),
            "warehouse_zones": list(dict.fromkeys(row["zone_name"] for row in candidates if row.get("zone_name"))),
            "bom_version": spec["line"].section.bom.version_number, "validation_errors": [],
             "conversion_snapshot": snapshot, "bom_attributes": bom_attribute_fields(spec["line"]),
             "batch_candidates": candidates})
    return rows, blockers


def sync_selected_pipes(issue, ids):
    specs, _ = pipe_specs(issue.production_task_id, issue.product_line_id)
    return [sync_pipe_requirement(s["line"].pk) for s in specs if s["id"] in ids]


def pipe_line_snapshot(requirement):
    source = requirement.contributions.filter(is_current=True).order_by("-created_at").first()
    if not source:
        raise pipe_error("SOURCE_CHANGED", "管材部位来源已失效。")
    snapshot = {**source.calculation_basis}
    snapshot.setdefault("pieces_per_bar", str(requirement.pieces_per_bar or source.bom_line.pieces_per_bar or ""))
    snapshot.setdefault("raw_bar_length_m", str(requirement.raw_bar_length_m or source.bom_line.raw_bar_length_m or ""))
    return {**snapshot, "kind": "PIPE", "part_name": source.bom_line.part_name,
            "bom_attributes": bom_attribute_fields(source.bom_line),
            "source_revision_hash": requirement.source_revision_hash}


def allocation_plan(quantity, snapshot):
    try:
        return pipe_issue(requested_pieces=quantity, pieces_per_bar=snapshot["pieces_per_bar"], raw_bar_length_m=snapshot["raw_bar_length_m"])
    except MaterialFlowValueError as error:
        raise pipe_error(error.code, str(error)) from error


def semi_errors(balance, quantity):
    errors = []
    if balance.quality != "AVAILABLE":
        errors.append("QUALITY_NOT_AVAILABLE")
    if (balance.zone.status != "ACTIVE" or balance.zone.warehouse.status != "ACTIVE"
            or balance.zone.warehouse.warehouse_type != "SEMI_FINISHED"):
        errors.append("WAREHOUSE_SCOPE_INVALID")
    if balance.unit.unit_name in {"支", "套"} and quantity != quantity.to_integral_value():
        errors.append("INTEGER_REQUIRED")
    return errors


def validate_pipe_lines(lines):
    required_bars, available_bars, errors = defaultdict(int), {}, []
    for line in lines:
        if line.conversion_snapshot.get("kind") != "PIPE":
            continue
        snapshot = line.conversion_snapshot
        try:
            plan = allocation_plan(line.requested_quantity, snapshot)
        except ValidationError:
            errors.append({"line_id": str(line.pk), "code": "PIPE_WHOLE_BAR_REQUIRED", "detail": "管材申请数量必须符合整根切割数量。"})
            continue
        pool = (snapshot["raw_material_id"], str(snapshot["raw_bar_length_m"]))
        required_bars[pool] += int(plan["bar_count"])
        if pool not in available_bars:
            available_bars[pool] = sum(
                (int(Decimal(row["available_quantity"])) for row in batch_candidates(snapshot)),
                0,
            )
    for pool, required in required_bars.items():
        if required > available_bars.get(pool, 0):
            errors.append({"code": "STOCK_INSUFFICIENT", "detail": "相同物料和规格的合格整根库存不足。"})
    return errors


def auto_allocate_pipe_lines(lines):
    """按先进先出自动分配管材库存；批次仅作为内部流水，不由领料人选择。"""
    pipe_lines = [line for line in lines if line.conversion_snapshot.get("kind") == "PIPE"]
    if not pipe_lines:
        return
    candidates_by_pool = {}
    remaining_by_batch = {}
    for line in pipe_lines:
        snapshot = line.conversion_snapshot
        pool = (snapshot["raw_material_id"], str(snapshot["raw_bar_length_m"]))
        if pool not in candidates_by_pool:
            candidates = batch_candidates(snapshot)
            candidates_by_pool[pool] = candidates
            for candidate in candidates:
                remaining_by_batch[candidate["inbound_line_id"]] = int(Decimal(candidate["available_quantity"]))
    MaterialIssueBatchAllocation.objects.filter(line__in=pipe_lines).delete()
    records = []
    for line in sorted(pipe_lines, key=lambda item: (item.line_number, str(item.pk))):
        snapshot = line.conversion_snapshot
        pool = (snapshot["raw_material_id"], str(snapshot["raw_bar_length_m"]))
        plan = allocation_plan(line.requested_quantity, snapshot)
        remaining_bars = int(plan["bar_count"])
        pieces_per_bar = int(snapshot["pieces_per_bar"])
        for candidate in candidates_by_pool[pool]:
            batch_id = candidate["inbound_line_id"]
            allocated_bars = min(remaining_by_batch[batch_id], remaining_bars)
            if allocated_bars <= 0:
                continue
            requested_pieces = allocated_bars * pieces_per_bar
            amount = allocation_plan(requested_pieces, snapshot)
            records.append(MaterialIssueBatchAllocation(
                line=line,
                inbound_line_id=batch_id,
                requested_pieces=amount["requested_pieces"],
                bar_count=amount["bar_count"],
                meters=amount["meters"],
                snapshot=json.loads(json.dumps(candidate, cls=DjangoJSONEncoder)),
            ))
            remaining_by_batch[batch_id] -= allocated_bars
            remaining_bars -= allocated_bars
            if remaining_bars == 0:
                break
        if remaining_bars:
            raise pipe_error("STOCK_INSUFFICIENT", "相同物料和规格的合格整根库存不足。")
    MaterialIssueBatchAllocation.objects.bulk_create(records)


def lock_issue_stock(issue):
    """与外发保持批次→库区→原料余额→半成品余额的稳定锁序。"""
    lines = list(issue.lines.all())
    batch_ids = set(MaterialIssueBatchAllocation.objects.filter(line__issue=issue).values_list("inbound_line_id", flat=True))
    for line in lines:
        if line.conversion_snapshot.get("kind") == "PIPE":
            batch_ids.update(row["inbound_line_id"] for row in batch_candidates(line.conversion_snapshot))
    batches = list(MaterialInboundLine.objects.select_for_update().filter(pk__in=batch_ids).order_by("id"))
    raw_ids = [line.raw_material_id for line in lines if line.raw_material_id]
    semi_ids = [line.semi_finished_balance_id for line in lines if line.semi_finished_balance_id]
    zones = {b.zone_id for b in batches}
    zones.update(MaterialStockBalance.objects.filter(raw_material_id__in=raw_ids).values_list("zone_id", flat=True))
    zones.update(SemiFinishedStockBalance.objects.filter(pk__in=semi_ids).values_list("zone_id", flat=True))
    list(WarehouseZone.objects.select_for_update().filter(pk__in=zones).order_by("id"))
    list(MaterialStockBalance.objects.select_for_update().filter(raw_material_id__in=raw_ids, quality="AVAILABLE")
         .order_by("raw_material_id", "unit_id", "zone_id", "id"))
    list(SemiFinishedStockBalance.objects.select_for_update().filter(pk__in=semi_ids).order_by("id"))


def issue_pipe_line(line, actor):
    records = list(line.batch_allocations.all())
    movements = issue_pipe_material(bom_line_id=line.conversion_snapshot["bom_line_id"],
        allocations=[{"inbound_line_id": r.inbound_line_id, "requested_pieces": r.requested_pieces, "source_line_id": r.pk} for r in records],
        source_type="MATERIAL_ISSUE", source_id=line.issue_id,
        source_revision_hash=line.conversion_snapshot["source_revision_hash"], actor_employee=actor)
    by_id = {str(m.source_line_id): m for m in movements}
    for record in records:
        movement = by_id[str(record.pk)]
        record.snapshot = {**record.snapshot, "after_bar_count": str(movement.after_quantity), "after_meters": str(movement.after_meter_quantity)}
        record.save(update_fields=["snapshot", "updated_at"])
    line.requirement.refresh_from_db()


def line_flow_data(line):
    if line.conversion_snapshot.get("public_identity"):
        from .public_issue_services import public_line_flow_data
        return public_line_flow_data(line)
    allocations = [{**r.snapshot, "id": str(r.pk), "inbound_line_id": str(r.inbound_line_id),
        "requested_pieces": str(r.requested_pieces), "bar_count": str(r.bar_count), "meters": str(r.meters)} for r in line.batch_allocations.all()]
    if not allocations and line.conversion_snapshot.get("kind") == "PIPE":
        plan = allocation_plan(line.requested_quantity, line.conversion_snapshot)
        return {"conversion_snapshot": line.conversion_snapshot, "batch_allocations": [],
            "bar_count": str(plan["bar_count"]), "meters": str(plan["meters"])}
    return {"conversion_snapshot": line.conversion_snapshot, "batch_allocations": allocations,
        "bar_count": str(sum(int(r["bar_count"]) for r in allocations)),
        "meters": str(sum((Decimal(r["meters"]) for r in allocations), Decimal("0.00")))}


def line_stock(line):
    if line.conversion_snapshot.get("public_identity"):
        from .public_issue_services import public_line_quantities
        return Decimal(public_line_quantities(line, exclude_issue_id=line.issue_id)["available_stock"])
    if line.conversion_snapshot.get("kind") == "PIPE":
        return sum((Decimal(r["available_input_quantity"]) for r in batch_candidates(line.conversion_snapshot)), Decimal(0))
    from apps.inventory.stock_services import available_stock
    return available_stock(line.raw_material_id, line.unit_id)
