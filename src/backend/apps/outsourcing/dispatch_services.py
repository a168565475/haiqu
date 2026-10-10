from apps.access_control.resource_scopes import require_craft, require_order_craft
"""S6 外发实际发料，整单事务、按批次扣库、与厂内共用订单额度。"""
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.models import MaterialInboundLine, MaterialStockBalance, MaterialStockMovement, WarehouseZone
from apps.inventory.stock_services import inbound_batch_available_quantities, inbound_line_material, debit_material_stock
from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.requirements import sync_order_requirements
from apps.boms.material_attributes import bom_attribute_fields
from apps.production_scheduling.models import ProductionSchedule
from apps.production_tasks.models import ProductionTask

from .material_flow import quantity, pipe_amount, lock_request
from .models import OutsourcingOrder, OutsourcingMaterialItem, OutsourcingDispatch, OutsourcingDispatchLine


def material_items(order):
    return list(OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order=order)
        .select_related("bom_material_line__section__bom", "allocation__factory", "allocation__processing_item__order_product__schedule_product")
        .order_by("bom_material_line_id", "id"))


def ready_snapshot(item):
    snapshot = item.conversion_snapshot
    if snapshot.get("schema_version") != 2 or snapshot.get("kind") not in {"PIPE", "FABRIC", "OTHER"}:
        raise Conflict("旧口径外发单不能继续发料，请按新 BOM 重新创建。")
    return snapshot


def confirmed_batches():
    return MaterialInboundLine.objects.filter(inbound__status="CONFIRMED", accepted_quantity__gt=0).select_related(
        "inbound", "zone__warehouse", "location", "raw_material_information__unit", "purchase_order_line__bom_line"
    ).order_by("inbound__inbound_date", "created_at", "id")



def material_batches(raw_material_ids):
    # 旧入库行可能只保留 BOM 来源，仍需走原有的原料解析逻辑。
    return confirmed_batches().filter(
        Q(raw_material_information_id__in=raw_material_ids) | Q(raw_material_information__isnull=True)
    )


def batch_candidates(snapshot, batches=None, available=None):
    batches = list(confirmed_batches()) if batches is None else batches
    available = inbound_batch_available_quantities(batches) if available is None else available
    candidates = []
    for line in batches:
        raw = inbound_line_material(line)
        if raw is None or str(raw.pk) != snapshot["raw_material_id"] or available[line.pk] <= 0:
            continue
        is_pipe = snapshot["kind"] == "PIPE"
        if is_pipe and (line.measurement_kind != "PIPE" or line.raw_bar_length_m != Decimal(snapshot["raw_bar_length_m"])):
            continue
        if not is_pipe and (line.measurement_kind != "OTHER" or line.source_unit_text_snapshot not in {raw.unit.unit_name, raw.unit.unit_code}):
            continue
        if (line.zone.status != "ACTIVE" or line.zone.warehouse.status != "ACTIVE" or line.zone.warehouse.warehouse_type != "MATERIAL"
                or (line.location_id and line.location.status != "ACTIVE")):
            continue
        candidates.append({"inbound_line_id": str(line.pk), "inbound_number": line.inbound.inbound_number,
            "inbound_date": line.inbound.inbound_date, "zone_id": str(line.zone_id),
            "warehouse_name": line.zone.warehouse.warehouse_name, "zone_name": line.zone.zone_name,
            "location_name": line.location.location_number if line.location else "—",
            "source_unit": "支" if is_pipe else raw.unit.unit_name, "material_unit": raw.unit.unit_name,
            "same_unit": True, "accepted_quantity": str(line.accepted_quantity),
            "available_quantity": str(available[line.pk]),
            "available_input_quantity": str(available[line.pk] * snapshot["pieces_per_bar"] if is_pipe else available[line.pk]),
            "available_meters": str(available[line.pk] * line.raw_bar_length_m) if is_pipe else None,
            "raw_bar_length_m": str(line.raw_bar_length_m) if is_pipe else None})
    return candidates


def flow_dispatch_context(order):
    if order.stock_mode == "PUBLIC_V2":
        from .public_stock_services import public_dispatch_context
        return public_dispatch_context(order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    from apps.material_issues.material_flow import pipe_specs
    from apps.material_issues.models import OrderMaterialRequirement
    from apps.material_issues.requirements import build_requirement_specs
    from apps.material_issues.services import pending_issue_quantities

    assert_legacy_original_route(order)
    items = material_items(order)
    task_id = order.schedule.production_task_id
    specs_by_line = {}
    if any(ready_snapshot(item)["kind"] != "PIPE" for item in items):
        _, ordinary_specs, _, _ = build_requirement_specs(task_id)
        for spec in ordinary_specs:
            for contribution in spec["contributions"]:
                specs_by_line[contribution["bom_line"].pk] = spec
    pipe_product_ids = {
        item.allocation.processing_item.order_product.schedule_product.product_line_id
        for item in items if ready_snapshot(item)["kind"] == "PIPE"
    }
    for product_id in pipe_product_ids:
        pipe_rows, _ = pipe_specs(task_id, product_id)
        for spec in pipe_rows:
            specs_by_line[spec["line"].pk] = spec
    requirements = {
        row.pk: row for row in OrderMaterialRequirement.objects.filter(
            pk__in={spec["id"] for spec in specs_by_line.values()}
        )
    }
    pending, _ = pending_issue_quantities(requirement_ids=requirements)
    wanted = {ready_snapshot(item)["raw_material_id"] for item in items}
    batches = [line for line in material_batches(wanted) if (raw := inbound_line_material(line)) and str(raw.pk) in wanted]
    available = inbound_batch_available_quantities(batches)
    rows = []
    for item in items:
        snapshot = ready_snapshot(item)
        candidates = batch_candidates(snapshot, batches, available)
        zones = {}
        for candidate in candidates:
            zone = zones.setdefault(candidate["zone_id"], {
                "zone_id": candidate["zone_id"], "warehouse_name": candidate["warehouse_name"],
                "zone_name": candidate["zone_name"], "available_quantity": Decimal("0"),
                "available_input_quantity": Decimal("0"), "available_meters": Decimal("0"),
            })
            zone["available_quantity"] += Decimal(candidate["available_quantity"])
            zone["available_input_quantity"] += Decimal(candidate["available_input_quantity"])
            zone["available_meters"] += Decimal(candidate["available_meters"] or "0")
        zone_rows = [{**zone, "available_quantity": str(zone["available_quantity"]),
            "available_input_quantity": str(zone["available_input_quantity"]),
            "available_meters": str(zone["available_meters"]) if snapshot["kind"] == "PIPE" else None}
            for zone in zones.values()]
        spec = specs_by_line.get(item.bom_material_line_id)
        current = requirements.get(spec["id"]) if spec else None
        required = Decimal(spec["snapshot"]["allowance_pieces"] if snapshot["kind"] == "PIPE" else spec["required_quantity"]) if spec else Decimal("0")
        internal = current.internal_issued_quantity if current else Decimal("0")
        external = current.outsourcing_issued_quantity if current else Decimal("0")
        waiting = pending.get(current.pk, Decimal("0")) if current else Decimal("0")
        remaining = max(required - internal - external - waiting, Decimal("0"))
        stock = sum((Decimal(zone["available_input_quantity"]) for zone in zone_rows), Decimal("0"))
        rows.append({"material_item_id": str(item.pk), "factory_name": item.allocation.factory_snapshot.get("name", ""),
            "material_number": item.material_snapshot.get("material_number", ""), "material_name": item.material_snapshot.get("name", ""),
            "specification": item.material_snapshot.get("specification", ""), "color": item.material_snapshot.get("color", ""),
             "bom_attributes": item.material_snapshot.get("bom_attributes") or bom_attribute_fields(item.bom_material_line),
            "planned_issue_quantity": str(item.planned_piece_count if snapshot["kind"] == "PIPE" else item.planned_issue_quantity),
            "unit": "支" if snapshot["kind"] == "PIPE" else item.unit_text, "procurement_required_quantity": str(item.planned_issue_quantity),
            "procurement_unit": item.unit_text, "procurement_conversion": False, "suggested_conversion_factor": "1",
            "conversion_evidence": "", "identity_resolved": True, "planned_batches": item.material_snapshot.get("planned_batches", []), "conversion_snapshot": snapshot, "candidates": candidates,
            "zones": zone_rows, "required_quantity": str(required), "internal_issued_quantity": str(internal),
            "outsourcing_issued_quantity": str(external), "pending_issue_quantity": str(waiting),
            "order_remaining": str(remaining), "available_stock": str(stock),
            "max_issue_quantity": str(min(Decimal(item.planned_piece_count if snapshot["kind"] == "PIPE" else item.planned_issue_quantity), remaining, stock)),
            "quota_error": "" if spec else "当前材料的订单领料额度尚未就绪，请核对 BOM。"})
    return {"order_id": str(order.pk), "order_number": order.order_number, "materials": rows}


def change_pipe_balance(balance, amount, *, direction, source_type, source_id, source_line_id, task, actor, snapshot):
    """调用方已锁定来源和余额；根米必须同进同出。"""
    sign = 1 if direction == "IN" else -1
    before, before_meters = balance.quantity, balance.meter_quantity
    meters = amount * balance.raw_bar_length_m
    if sign < 0 and amount > before:
        raise Conflict("管材批次整根库存不足。")
    balance.quantity += sign * amount
    balance.meter_quantity += sign * meters
    balance.version += 1
    balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
    return MaterialStockMovement.objects.create(balance=balance, direction=direction, quantity=amount, meter_quantity=meters,
        before_quantity=before, after_quantity=balance.quantity, before_meter_quantity=before_meters,
        after_meter_quantity=balance.meter_quantity, source_type=source_type, source_id=source_id,
        source_line_id=source_line_id, production_task=task, actor_employee=actor, snapshot=snapshot)


@transaction.atomic
def confirm_flow_dispatch(*, order_id, request_id, line_inputs, remark, actor_employee, request):
    require_order_craft(request, "outsourcing.confirm_dispatch_outsourcingorder", order_id)
    from .services import _json_hash, _assert_order_source_unchanged, order_audit_snapshot
    digest = _json_hash({"order_id": str(order_id), "lines": line_inputs, "remark": remark})
    lock_request("dispatch", request_id)
    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related("schedule").get(pk=order_id)
    existing = OutsourcingDispatch.objects.filter(client_request_id=request_id).first()
    if existing:
        if existing.order_id != order.pk or existing.request_payload_hash != digest:
            raise Conflict("相同发料请求标识已用于不同内容。")
        return order
    require_matching_etag(request, order)
    from apps.inventory.public_stock_mode import require_document_stock_mode
    public = require_document_stock_mode(order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    if order.status != "PENDING_DISPATCH":
        raise Conflict("只有待外发单可以确认发料。")
    if public:
        from .public_stock_services import confirm_public_dispatch
        return confirm_public_dispatch(order, request_id=request_id, digest=digest, line_inputs=line_inputs,
            remark=remark, actor_employee=actor_employee, request=request)
    ProductionSchedule.objects.select_for_update().get(pk=order.schedule_id)
    task = ProductionTask.objects.select_for_update().get(pk=order.schedule.production_task_id)
    _assert_order_source_unchanged(order)
    items = material_items(order)
    by_id = {item.pk: item for item in items}
    selected_ids = {row["material_item_id"] for row in line_inputs}
    if not line_inputs or not selected_ids.issubset(by_id):
        raise ValidationError({"lines": "请填写有效的发料材料、库区和数量。"})
    if len(selected_ids) < len(by_id):
        current_quota = {row["material_item_id"]: Decimal(row["max_issue_quantity"])
            for row in flow_dispatch_context(order)["materials"]}
        if any(current_quota.get(str(item.pk), Decimal("1")) > 0 for item in items if item.pk not in selected_ids):
            raise ValidationError({"lines": "本次可领大于 0 的材料必须填写发料数量。"})
    selected_items = [item for item in items if item.pk in selected_ids]
    requirements = {}
    nonpipe = [item for item in selected_items if ready_snapshot(item)["kind"] != "PIPE"]
    if nonpipe:
        _, ordinary, blockers, _ = sync_order_requirements(task.pk)
        targets = {str(item.bom_material_line_id) for item in nonpipe}
        products = {str(item.allocation.processing_item.order_product.schedule_product.product_line_id) for item in nonpipe}
        relevant = [b for b in blockers if b.get("bom_line_id") in targets or (not b.get("bom_line_id") and b.get("product_line_id") in products)]
        if relevant:
            raise ValidationError({"materials": "订单原料来源尚未就绪。", "blockers": relevant})
        for requirement in ordinary:
            for contribution in requirement.contributions.filter(is_current=True):
                requirements[contribution.bom_line_id] = requirement
    for line_id in sorted({item.bom_material_line_id for item in selected_items if ready_snapshot(item)["kind"] == "PIPE"}, key=str):
        requirements[line_id] = sync_pipe_requirement(line_id)
    explicit_batch_ids = {row["inbound_line_id"] for row in line_inputs if row.get("inbound_line_id")}
    selected_zone_ids = {row["zone_id"] for row in line_inputs if row.get("zone_id")}
    batches = {line.pk: line for line in confirmed_batches().select_for_update(of=("self",)).filter(
        Q(pk__in=explicit_batch_ids) | Q(zone_id__in=selected_zone_ids)
    ).order_by("id")}
    if not explicit_batch_ids.issubset(batches):
        raise ValidationError({"lines": "所选批次未质检或已不存在。"})
    zone_ids = selected_zone_ids | {line.zone_id for line in batches.values()}
    zones = {zone.pk: zone for zone in WarehouseZone.objects.select_for_update().filter(pk__in=zone_ids).order_by("id")}
    if not selected_zone_ids.issubset(zones):
        raise ValidationError({"lines": "所选库区已不存在。"})
    raw_ids = {snapshot["raw_material_id"] for snapshot in (ready_snapshot(item) for item in selected_items)}
    balances = list(MaterialStockBalance.objects.select_for_update().filter(raw_material_id__in=raw_ids,
        zone_id__in=zone_ids, quality="AVAILABLE").order_by("raw_material_id", "unit_id", "zone_id", "id"))
    balance_by_batch = {balance.inbound_line_id: balance for balance in balances if balance.measurement_kind == "PIPE"}
    all_batches = [line for line in material_batches(raw_ids) if (raw := inbound_line_material(line)) and str(raw.pk) in raw_ids]
    available = inbound_batch_available_quantities(all_batches)
    effective_inputs = [row for row in line_inputs if row.get("inbound_line_id")]
    reserved = defaultdict(Decimal)
    for row in effective_inputs:
        snapshot = ready_snapshot(by_id[row["material_item_id"]])
        entered = quantity(row["requested_quantity"])
        reserved[row["inbound_line_id"]] += Decimal(pipe_amount(entered, snapshot)["bar_count"]) if snapshot["kind"] == "PIPE" else entered
    locked_batches = {str(key): line for key, line in batches.items()}
    for row in line_inputs:
        if not row.get("zone_id"):
            continue
        item = by_id[row["material_item_id"]]
        snapshot = ready_snapshot(item)
        entered = quantity(row["requested_quantity"])
        needed = Decimal(pipe_amount(entered, snapshot)["bar_count"]) if snapshot["kind"] == "PIPE" else entered
        remaining = needed
        for candidate in batch_candidates(snapshot, all_batches, available):
            if candidate["zone_id"] != str(row["zone_id"]):
                continue
            line = locked_batches.get(candidate["inbound_line_id"])
            if line is None:
                raise Conflict("库区库存已变化，请刷新后重试。")
            take = min(max(available.get(line.pk, Decimal("0")) - reserved[line.pk], Decimal("0")), remaining)
            if take <= 0:
                continue
            source = {**row, "inbound_line_id": line.pk,
                "requested_quantity": take * Decimal(snapshot["pieces_per_bar"]) if snapshot["kind"] == "PIPE" else take}
            source.pop("zone_id", None)
            effective_inputs.append(source)
            reserved[line.pk] += take
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            raise Conflict(f"库区 {zones[row['zone_id']].zone_name} 可用库存不足，请刷新后重试。")
    by_batch, by_item, by_requirement = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    prepared, pairs = [], set()
    for row in effective_inputs:
        item = by_id[row["material_item_id"]]
        line = batches[row["inbound_line_id"]]
        pair = (item.pk, line.pk)
        if pair in pairs:
            raise ValidationError({"lines": "同一材料的批次重复。"})
        pairs.add(pair)
        snapshot = ready_snapshot(item)
        raw = inbound_line_material(line)
        requirement = requirements.get(item.bom_material_line_id)
        if (raw is None or str(raw.pk) != snapshot["raw_material_id"] or requirement is None
                or requirement.raw_material_id != raw.pk):
            raise ValidationError({"lines": "所选批次原料与订单部位来源不符。"})
        if (line.zone.status != "ACTIVE" or line.zone.warehouse.status != "ACTIVE" or line.zone.warehouse.warehouse_type != "MATERIAL"
                or (line.location_id and line.location.status != "ACTIVE")):
            raise ValidationError({"lines": "批次库区或库位已停用。"})
        entered = quantity(row["requested_quantity"])
        balance = None
        if snapshot["kind"] == "PIPE":
            amount = pipe_amount(entered, snapshot)
            actual = Decimal(amount["bar_count"])
            balance = balance_by_batch.get(line.pk)
            if (balance is None or balance.zone_id != line.zone_id or balance.raw_material_id != raw.pk
                    or balance.unit_id != raw.unit_id or balance.raw_bar_length_m != Decimal(snapshot["raw_bar_length_m"])
                    or line.raw_bar_length_m != balance.raw_bar_length_m):
                raise ValidationError({"lines": "管材批次单根长度或根制库存身份不符。"})
        else:
            if line.measurement_kind != "OTHER" or line.source_unit_text_snapshot not in {raw.unit.unit_name, raw.unit.unit_code}:
                raise ValidationError({"lines": "非管材原料按库存原单位发料，不允许任意换算比例。"})
            actual = entered
        by_batch[line.pk] += actual
        by_item[item.pk] += actual
        by_requirement[requirement.pk] += entered
        prepared.append((item, line, raw, requirement, entered, actual, balance))
    for batch_id, actual in by_batch.items():
        if actual > available.get(batch_id, Decimal("0")):
            raise Conflict(f"批次 {batches[batch_id].inbound.inbound_number} 可用库存不足。")
    for item in selected_items:
        if by_item[item.pk] > item.planned_issue_quantity:
            raise ValidationError({"lines": "每项材料的库区发料合计不能超过计划发料数量。"})
    unique_requirements = {r.pk: r for r in requirements.values()}
    from apps.material_issues.services import pending_issue_quantities
    pending, _ = pending_issue_quantities(requirement_ids=unique_requirements)
    for key, amount in by_requirement.items():
        requirement = unique_requirements[key]
        if amount > requirement.required_quantity - requirement.internal_issued_quantity - requirement.outsourcing_issued_quantity - pending.get(key, Decimal("0")):
            raise Conflict("外发与厂内领料合计超过订单该部位剩余额度。")
    before = order_audit_snapshot(order)
    dispatch = OutsourcingDispatch.objects.create(order=order, dispatch_number=f"FL-{timezone.localdate():%Y%m%d}-{uuid4().hex[:8].upper()}",
        client_request_id=request_id, request_payload_hash=digest, remark=remark,
        confirmed_by_employee=actor_employee, confirmed_at=timezone.now())
    for item, line, raw, requirement, entered, actual, balance in prepared:
        snapshot = {**item.conversion_snapshot, "inbound_line_id": str(line.pk), "inbound_number": line.inbound.inbound_number,
                    "warehouse": line.zone.warehouse.warehouse_name, "zone": line.zone.zone_name,
                    "location": line.location.location_number if line.location else "",
                    "factory": item.allocation.factory_snapshot.get("name", ""), "requested_quantity": str(entered)}
        record = OutsourcingDispatchLine.objects.create(dispatch=dispatch, material_item=item, requirement=requirement,
            raw_material=raw, unit=raw.unit, inbound_line=line, zone=line.zone, location=line.location,
            source_quantity=actual, material_quantity=actual, conversion_factor=1, source_unit_snapshot=item.unit_text,
            source_snapshot=snapshot, issued_quantity=actual, snapshot=snapshot, stock_balance=balance,
            issued_piece_count=int(entered) if balance else None,
            issued_meters=actual * balance.raw_bar_length_m if balance else None)
        if balance:
            change_pipe_balance(balance, actual, direction="OUT", source_type="OUTSOURCING_DISPATCH", source_id=dispatch.pk,
                source_line_id=record.pk, task=task, actor=actor_employee, snapshot=snapshot)
        else:
            movement = debit_material_stock(raw_material=raw, unit=raw.unit, quantity=actual, source_type="OUTSOURCING_DISPATCH",
                source_id=dispatch.pk, source_line_id=record.pk, actor_employee=actor_employee,
                production_task=task, snapshot=snapshot, zone=line.zone)
    for key, amount in by_requirement.items():
        requirement = unique_requirements[key]
        requirement.outsourcing_issued_quantity += amount
        requirement.save(update_fields=["outsourcing_issued_quantity", "updated_at"])
    order.status = "PROCESSING"
    order.version += 1
    order.updated_by_employee = actor_employee
    order.save(update_fields=["status", "version", "updated_by_employee", "updated_at"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action="DISPATCH_CONFIRMED", actor_employee=actor_employee,
        before_data=before, after_data=order_audit_snapshot(order), context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)
    return order
