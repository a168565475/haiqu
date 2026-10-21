from apps.access_control.resource_scopes import require_craft, require_order_craft
"""外发原料去向和加工产出分别对账，确认记录只追加。"""
from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.models import (MaterialInbound, MaterialInboundLine, MaterialInboundStatus,
                                   MaterialStockBalance, MaterialStockQuality, Warehouse, WarehouseZone)
from apps.inventory.stock_services import credit_material_stock, inbound_line_material
from apps.material_issues.models import OrderMaterialRequirement
from apps.production_scheduling.models import ProductionSchedule
from apps.production_tasks.models import ProductionTask
from apps.products.models import RawMaterialInformation

from .dispatch_services import change_pipe_balance
from .material_flow import quantity, lock_request
from .models import (OutsourcingOrder, OutsourcingDispatch, OutsourcingDispatchLine, OutsourcingFactoryAllocation,
                     OutsourcingReturn, OutsourcingReturnLine,
                     OutsourcingRawReturn, OutsourcingRawReturnLine, OutsourcingReconciliation, OutsourcingReconciliationEntry)


def reconciliation(order):
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    relations = ["material_item__allocation__processing_item", "raw_material", "unit", "zone"]
    if order.stock_mode != "PUBLIC_V2":
        relations.append("inbound_line__inbound")
    dispatches = list(OutsourcingDispatchLine.objects.filter(dispatch__order=order).select_related(*relations))
    entries = list(OutsourcingReconciliationEntry.objects.filter(record__order=order))
    raw_totals = defaultdict(lambda: defaultdict(Decimal))
    scrap = defaultdict(Decimal)
    for entry in entries:
        if entry.kind == "OUTPUT_SCRAP":
            scrap[entry.allocation_id] += entry.quantity
        else:
            raw_totals[entry.dispatch_line_id][entry.kind] += entry.quantity
    for line in OutsourcingRawReturnLine.objects.filter(record__order=order):
        raw_totals[line.dispatch_line_id]["RETURN"] += line.quantity
    capacity = defaultdict(Decimal)
    fabric_inputs = defaultdict(Decimal)
    fabric_consumptions = {}
    raws = []
    blockers = []
    for line in dispatches:
        snapshot = line.snapshot
        if snapshot.get("schema_version") != 2:
            blockers.append("旧口径发料记录不可进入新流程结清。")
        totals = raw_totals[line.pk]
        allocation = line.material_item.allocation
        raw_input = totals["RAW_INPUT"]
        if snapshot.get("kind") == "PIPE":
            capacity[allocation.pk] += raw_input * Decimal(snapshot["pieces_per_bar"])
        elif snapshot.get("kind") == "FABRIC" and snapshot.get("quantity_basis") != "OUTPUT_SETS":
            fabric_inputs[allocation.pk] += raw_input
            fabric_consumptions[allocation.pk] = Decimal(snapshot["fabric_meters_per_set"])
        remaining = line.issued_quantity - totals["RETURN"] - raw_input - totals["RAW_LOSS"]
        if remaining:
            blockers.append(f"{line.raw_material.material_name} 尚有 {remaining} {line.unit.unit_name} 原料未处理。")
        raws.append({"dispatch_line_id": str(line.pk), "allocation_id": str(allocation.pk), "factory_id": str(allocation.factory_id),
            "factory_name": allocation.factory_snapshot.get("name", ""), "material_name": line.raw_material.material_name,
            "component": allocation.processing_item.component_snapshot.get("part_name", ""),
            "bom_attributes": line.material_item.material_snapshot.get("bom_attributes", []),
            "inbound_number": line.inbound_line.inbound.inbound_number if line.inbound_line_id else "",
            "zone_name": line.zone.zone_name if line.zone_id else "", "unit": line.unit.unit_name,
            "dispatched": str(line.issued_quantity), "returned": str(totals["RETURN"]), "input": str(raw_input),
            "loss": str(totals["RAW_LOSS"]), "remaining": str(remaining), "conversion_snapshot": snapshot})
    returned = defaultdict(lambda: defaultdict(Decimal))
    returned_colors = defaultdict(list)
    # 先加总同一加工分配的投入米数，再做除法，避免跨批次 1/3 累加误差。
    for allocation_id, meters in fabric_inputs.items():
        capacity[allocation_id] = meters / fabric_consumptions[allocation_id]
    for line in OutsourcingReturnLine.objects.filter(return_record__order=order):
        returned[line.allocation_id][line.quality] += line.returned_quantity
        actual_color = str((line.snapshot or {}).get("color") or "").strip()
        if actual_color and actual_color not in returned_colors[line.allocation_id]:
            returned_colors[line.allocation_id].append(actual_color)
    outputs = []
    for allocation in OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order=order).select_related("processing_item"):
        if allocation.conversion_snapshot.get("quantity_basis") == "OUTPUT_SETS":
            capacity[allocation.pk] = allocation.allocated_quantity
        good, bad = returned[allocation.pk]["AVAILABLE"], returned[allocation.pk]["DEFECTIVE"]
        remaining = capacity[allocation.pk] - good - bad - scrap[allocation.pk]
        if remaining:
            blockers.append(f"{allocation.processing_item.component_snapshot.get('part_name', '')} 尚有 {remaining} {allocation.processing_item.unit_snapshot} 产出未处理。")
        if capacity[allocation.pk] != capacity[allocation.pk].to_integral_value():
            blockers.append("面料投入必须能解释整数套产出，余米请退回或登记原料损失。")
        outputs.append({"allocation_id": str(allocation.pk), "factory_id": str(allocation.factory_id),
            "factory_name": allocation.factory_snapshot.get("name", ""),
            "component": allocation.processing_item.component_snapshot.get("part_name", ""),
            "specification": allocation.processing_item.component_snapshot.get("specification", ""),
            "color": "、".join(returned_colors[allocation.pk]) or allocation.processing_item.component_snapshot.get("color", ""),
            "bom_attributes": allocation.processing_item.component_snapshot.get("bom_attributes", []),
            "unit": allocation.processing_item.unit_snapshot, "planned": str(allocation.allocated_quantity),
            "capacity": str(capacity[allocation.pk]), "good": str(good), "defective": str(bad),
            "scrap": str(scrap[allocation.pk]), "remaining": str(remaining)})
    if not dispatches:
        blockers.append("尚未确认发料。")
    return {"raw_materials": raws, "outputs": outputs, "blockers": blockers,
            "can_complete": bool(dispatches) and not blockers and order.status in {"PROCESSING", "PARTIAL_RETURN"},
            "records": [{"id": str(entry.pk), "kind": entry.kind, "allocation_id": str(entry.allocation_id),
                "dispatch_line_id": str(entry.dispatch_line_id) if entry.dispatch_line_id else None,
                "quantity": str(entry.quantity), "unit": entry.unit_snapshot, "reason": entry.reason,
                "confirmed_at": entry.record.confirmed_at, "actor": entry.record.actor.display_name}
                for entry in OutsourcingReconciliationEntry.objects.filter(record__order=order).select_related("record__actor").order_by("created_at", "id")],
            "raw_returns": [{"id": str(line.pk), "dispatch_line_id": str(line.dispatch_line_id), "quantity": str(line.quantity),
                "unit": line.dispatch_line.unit.unit_name,
                "component": line.dispatch_line.material_item.allocation.processing_item.component_snapshot.get("part_name", ""),
                "factory_name": line.record.factory.name,
                "meters": str(line.meter_quantity) if line.meter_quantity is not None else None, "reason": line.record.reason,
                "actor": line.record.actor.display_name, "confirmed_at": line.record.confirmed_at}
                for line in OutsourcingRawReturnLine.objects.filter(record__order=order).select_related("record__actor", "record__factory", "dispatch_line__unit", "dispatch_line__material_item__allocation__processing_item").order_by("created_at", "id")]}


def lock_task(order):
    ProductionSchedule.objects.select_for_update().get(pk=order.schedule_id)
    return ProductionTask.objects.select_for_update().get(pk=order.schedule.production_task_id)


def active(order):
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    if order.status not in {"PROCESSING", "PARTIAL_RETURN"}:
        raise Conflict("只有已发料且未结清的外发单可以处理原料和产出。")


def bump(order, actor, action, request=None, before=None):
    from .services import order_audit_snapshot
    before = before if before is not None else order_audit_snapshot(order)
    order.version += 1
    order.updated_by_employee = actor
    order.save(update_fields=["status", "version", "updated_by_employee", "updated_at", "completed_at", "completion_request_id", "completion_payload_hash"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action=action, actor_employee=actor,
        before_data=before, after_data=order_audit_snapshot(order), context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)


def record_entries(order, request_id, inputs, actor):
    from .services import _json_hash
    digest = _json_hash({"order_id": str(order.pk), "entries": inputs})
    old = OutsourcingReconciliation.objects.filter(request_id=request_id).first()
    if old:
        if old.order_id != order.pk or old.payload_hash != digest:
            raise Conflict("相同登记请求已用于不同内容。")
        return False
    if not inputs:
        raise ValidationError({"entries": "请至少填写一条投入或损耗记录。"})
    allocations = {str(a.pk): a for a in OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order=order).select_related("processing_item")}
    sources = {str(line.pk): line for line in OutsourcingDispatchLine.objects.filter(dispatch__order=order).select_related("material_item", "unit")}
    record = OutsourcingReconciliation.objects.create(order=order, request_id=request_id, payload_hash=digest, actor=actor)
    for row in inputs:
        allocation = allocations.get(str(row["allocation_id"]))
        if allocation is None:
            raise ValidationError({"allocation_id": "加工分配不属于本外发单。"})
        kind = row["kind"]
        if kind not in {"RAW_INPUT", "RAW_LOSS", "OUTPUT_SCRAP"} or not row.get("reason", "").strip():
            raise ValidationError({"entries": "请选择登记类型并填写原因。"})
        source = sources.get(str(row.get("dispatch_line_id")))
        if kind == "OUTPUT_SCRAP":
            if row.get("dispatch_line_id"):
                raise ValidationError({"dispatch_line_id": "加工报废按产出登记，不另扣一份原料。"})
            amount = quantity(row["quantity"], integer=True)
            unit = allocation.processing_item.unit_snapshot
            snapshot = allocation.conversion_snapshot
        else:
            if source is None or source.material_item.allocation_id != allocation.pk or source.snapshot.get("schema_version") != 2:
                raise ValidationError({"dispatch_line_id": "原料来源必须是本厂、本部位的已发批次。"})
            amount = quantity(row["quantity"], integer=source.snapshot.get("kind") == "PIPE")
            unit, snapshot = source.unit.unit_name, source.snapshot
        OutsourcingReconciliationEntry.objects.create(record=record, allocation=allocation, dispatch_line=source if kind != "OUTPUT_SCRAP" else None,
            kind=kind, quantity=amount, unit_snapshot=unit, reason=row["reason"].strip(), snapshot=snapshot)
    state = reconciliation(order)
    if any(Decimal(row["remaining"]) < 0 for row in state["raw_materials"] + state["outputs"]):
        raise Conflict("登记超出未处理原料或加工产出余量，已回库不良不能重复报废。")
    if any(Decimal(row["capacity"]) != Decimal(row["capacity"]).to_integral_value() for row in state["outputs"]):
        raise ValidationError({"entries": "本次面料投入合计必须对应整数套数，余米单独处理。"})
    from apps.wecom.workshop_change_notifications import reconciliation_losses
    reconciliation_losses(record, actor)
    return True


def prepare_return_inputs(order, request_id, inputs, returns, actor):
    lock_task(order)
    for row in inputs:
        if row["kind"] != "RAW_INPUT" or row["allocation_id"] not in {item["allocation_id"] for item in returns}:
            raise ValidationError({"raw_inputs": "回货只能同时登记本次回货部位的实际投入。"})
    if inputs:
        record_entries(order, uuid5(UUID(str(request_id)), "return-raw-input"), inputs, actor)


def assert_return_capacity(allocation, received):
    state = reconciliation(allocation.processing_item.order_product.order)
    row = next(row for row in state["outputs"] if row["allocation_id"] == str(allocation.pk))
    if received > Decimal(row["remaining"]):
        if allocation.conversion_snapshot.get("quantity_basis") == "OUTPUT_SETS":
            raise Conflict("回货套数超过本厂本部位的剩余加工套数，请核对累计回货及报废。")
        raise Conflict("实际投入不足或产出已处理，请核对投入、累计回货及报废。")


@transaction.atomic
def confirm_reconciliation(*, order_id, request_id, entries, actor_employee, request):
    require_order_craft(request, "outsourcing.reconcile_outsourcingorder", order_id)
    from .services import _json_hash
    lock_request("reconciliation", request_id)
    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related("schedule").get(pk=order_id)
    old = OutsourcingReconciliation.objects.filter(request_id=request_id).first()
    if old:
        if old.order_id != order.pk or old.payload_hash != _json_hash({"order_id": str(order.pk), "entries": entries}):
            raise Conflict("相同登记请求已用于不同内容。")
        return order
    require_matching_etag(request, order)
    active(order)
    lock_task(order)
    record_entries(order, request_id, entries, actor_employee)
    bump(order, actor_employee, "RECONCILIATION_CONFIRMED", request)
    return order


@transaction.atomic
def confirm_raw_return(*, order_id, request_id, factory_id, lines, reason, actor_employee, request):
    require_order_craft(request, "outsourcing.return_raw_outsourcingorder", order_id)
    from .services import _json_hash
    lock_request("raw-return", request_id)
    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related("schedule").get(pk=order_id)
    digest = _json_hash({"order_id": str(order.pk), "factory_id": str(factory_id), "lines": lines, "reason": reason})
    old = OutsourcingRawReturn.objects.filter(request_id=request_id).first()
    if old:
        if old.order_id != order.pk or old.payload_hash != digest:
            raise Conflict("相同退料请求已用于不同内容。")
        return order
    require_matching_etag(request, order)
    active(order)
    task = lock_task(order)
    from apps.inventory.public_stock_mode import require_document_stock_mode
    if require_document_stock_mode(order):
        from .public_stock_services import confirm_public_raw_return
        return confirm_public_raw_return(order, request_id=request_id, factory_id=factory_id, lines=lines,
            reason=reason, actor_employee=actor_employee, request=request, digest=digest)
    if not reason.strip() or not lines or len({row["dispatch_line_id"] for row in lines}) != len(lines):
        raise ValidationError({"lines": "请填写退料原因和不重复的来源明细。"})
    sources = {line.pk: line for line in OutsourcingDispatchLine.objects.filter(dispatch__order=order,
        material_item__allocation__factory_id=factory_id).select_related("material_item__allocation", "raw_material", "unit", "zone__warehouse", "inbound_line")}
    remaining = {row["dispatch_line_id"]: Decimal(row["remaining"]) for row in reconciliation(order)["raw_materials"]}
    list(RawMaterialInformation.objects.select_for_update().filter(pk__in={line.raw_material_id for line in sources.values()}).order_by("pk"))
    requirement_map = {r.pk: r for r in OrderMaterialRequirement.objects.select_for_update().filter(pk__in={line.requirement_id for line in sources.values()}).order_by("pk")}
    list(WarehouseZone.objects.select_for_update().filter(pk__in={line.zone_id for line in sources.values()}).order_by("id"))
    balances = {b.pk: b for b in MaterialStockBalance.objects.select_for_update().filter(pk__in={line.stock_balance_id for line in sources.values() if line.stock_balance_id}).order_by("raw_material_id", "unit_id", "zone_id", "id")}
    record = OutsourcingRawReturn.objects.create(order=order, factory_id=factory_id, request_id=request_id, payload_hash=digest, reason=reason, actor=actor_employee)
    for row in lines:
        source = sources.get(row["dispatch_line_id"])
        if source is None or source.snapshot.get("schema_version") != 2:
            raise ValidationError({"lines": "退料必须对应本单、本厂的新口径发料批次。"})
        is_pipe = source.snapshot.get("kind") == "PIPE"
        amount = quantity(row["quantity"], integer=is_pipe)
        if amount > remaining[str(source.pk)]:
            raise Conflict("退料超过原批次尚未投入、未损耗、未退回的数量。")
        if source.zone.status != "ACTIVE" or source.zone.warehouse.status != "ACTIVE" or source.zone.warehouse.warehouse_type != "MATERIAL":
            raise Conflict("原发料库区不可用，请先恢复有效库区。")
        equivalent = int(amount) * source.snapshot["pieces_per_bar"] if is_pipe else None
        meters = amount * Decimal(source.snapshot["raw_bar_length_m"]) if is_pipe else (amount if source.snapshot.get("kind") == "FABRIC" else None)
        returned = OutsourcingRawReturnLine.objects.create(record=record, dispatch_line=source, quantity=amount,
            meter_quantity=meters, piece_quantity_equivalent=equivalent, snapshot=source.snapshot)
        snapshot = {**source.snapshot, "dispatch_line_id": str(source.pk), "inbound_line_id": str(source.inbound_line_id)}
        if is_pipe:
            balance = balances.get(source.stock_balance_id)
            if balance is None or balance.inbound_line_id != source.inbound_line_id or balance.zone_id != source.zone_id:
                raise Conflict("原管材批次库存身份已变化。")
            change_pipe_balance(balance, amount, direction="IN", source_type="OUTSOURCING_RAW_RETURN", source_id=record.pk,
                source_line_id=returned.pk, task=task, actor=actor_employee, snapshot=snapshot)
        else:
            credit_material_stock(raw_material=source.raw_material, unit=source.unit, zone=source.zone, quantity=amount,
                source_type="OUTSOURCING_RAW_RETURN", source_id=record.pk, source_line_id=returned.pk,
                production_task=task, actor_employee=actor_employee, snapshot=snapshot)
        requirement = requirement_map[source.requirement_id]
        delta = Decimal(equivalent) if is_pipe else amount
        if delta > requirement.outsourcing_issued_quantity:
            raise Conflict("来源净外发额度不足，不能重复恢复。")
        requirement.outsourcing_issued_quantity -= delta
        requirement.save(update_fields=["outsourcing_issued_quantity", "updated_at"])
    bump(order, actor_employee, "RAW_RETURN_CONFIRMED", request)
    return order


def _reversible_source_snapshot(source):
    value = (lambda key: source[key]) if isinstance(source, dict) else (lambda key: getattr(source, key))
    snapshot = value("snapshot") or {}
    if snapshot.get("stock_mode") == "PUBLIC_V2":
        from .public_stock_services import reversible_public_source
        return reversible_public_source(source)
    if (snapshot.get("schema_version") != 2 or snapshot.get("kind") not in {"PIPE", "FABRIC", "OTHER"}
            or not value("inbound_line_id") or not value("zone_id")
            or (snapshot.get("kind") == "PIPE" and not value("stock_balance_id"))):
        return False
    if snapshot.get("kind") == "PIPE":
        try:
            pieces = Decimal(str(snapshot["pieces_per_bar"]))
            length = Decimal(str(snapshot["raw_bar_length_m"]))
            return (pieces.is_finite() and pieces > 0 and pieces == pieces.to_integral_value()
                    and length.is_finite() and length > 0
                    and Decimal(str(value("issued_piece_count"))) == Decimal(str(value("issued_quantity"))) * pieces)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False
    return True


def dispatched_revocation_blocker(order):
    """列表与详情共用的只读前置检查；写入时还会在行锁内重新检查。"""
    from apps.material_issues.p4_services import has_original_direct_handoff

    if has_original_direct_handoff(order):
        return "金工直接交接原单不能按原料发料撤销。"
    if order.status != "PROCESSING":
        return "只有已发料且尚未回货的普通外发单可以撤销。"
    if not OutsourcingDispatch.objects.filter(order=order).exists():
        return "外发单没有发料记录。"
    if OutsourcingReturn.objects.filter(order=order).exists():
        return "外发单已有回货记录，不能撤销发料。"
    if OutsourcingReconciliation.objects.filter(order=order).exists():
        return "外发单已有投入、损耗或报废记录，不能撤销发料。"
    sources = list(OutsourcingDispatchLine.objects.filter(dispatch__order=order).only(
        "id", "inbound_line_id", "zone_id", "stock_balance_id", "issued_quantity", "issued_piece_count", "snapshot",
        "public_stock_balance_id", "public_stock_movement_id",
    ))
    if not sources:
        return "外发单没有发料明细。"
    for source in sources:
        if not _reversible_source_snapshot(source):
            return "旧口径或缺少原批次的发料记录不能自动退回。"
    return None


def order_action_candidates(orders):
    """列表批量计算候选操作，P4 范围和权限仍由序列化器逐行检查。"""
    pending_ids = {order.pk for order in orders if order.status == "PENDING_DISPATCH"}
    processing_ids = {order.pk for order in orders if order.status == "PROCESSING"}
    ids = pending_ids | processing_ids
    if not ids:
        return {"delete": set(), "revoke_dispatched": set()}
    dispatch_ids = set(OutsourcingDispatch.objects.filter(order_id__in=ids).values_list("order_id", flat=True))
    returned_ids = set(OutsourcingReturn.objects.filter(order_id__in=ids).values_list("order_id", flat=True))
    reconciled_ids = set(OutsourcingReconciliation.objects.filter(order_id__in=ids).values_list("order_id", flat=True))
    reversible_ids = processing_ids & dispatch_ids - returned_ids - reconciled_ids
    seen_ids = set()
    invalid_ids = set()
    for source in OutsourcingDispatchLine.objects.filter(dispatch__order_id__in=reversible_ids).values(
        "dispatch__order_id", "inbound_line_id", "zone_id", "stock_balance_id",
        "issued_quantity", "issued_piece_count", "snapshot", "public_stock_balance_id", "public_stock_movement_id",
    ):
        order_id = source["dispatch__order_id"]
        seen_ids.add(order_id)
        if not _reversible_source_snapshot(source):
            invalid_ids.add(order_id)
    return {
        "delete": pending_ids - dispatch_ids - returned_ids,
        "revoke_dispatched": reversible_ids & seen_ids - invalid_ids,
    }


@transaction.atomic
def revoke_dispatched_order(*, order_id, request_id, reason, actor_employee, request):
    require_order_craft(request, "outsourcing.cancel_outsourcingorder", order_id)
    require_order_craft(request, "outsourcing.return_raw_outsourcingorder", order_id)
    """未投入也未回货时，将仍在厂外的原料按原批次退回并留存外发单。"""
    from .services import _json_hash, order_audit_snapshot

    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "请填写撤销原因。"})
    digest = _json_hash({"kind": "DISPATCH_REVOCATION", "order_id": str(order_id), "reason": reason})
    lock_request("revoke-dispatched", request_id)
    existing = AuditLog.objects.filter(
        object_type="OUTSOURCING_ORDER", action="DISPATCH_REVOKED",
        after_data__revocation_request_id=str(request_id),
    ).first()
    if existing:
        if (existing.object_id != order_id or existing.after_data.get("payload_hash") != digest
                or not OutsourcingOrder.objects.filter(pk=order_id, status="CANCELLED").exists()):
            raise Conflict("相同撤销请求标识已用于不同外发单或原因。")
        return OutsourcingOrder.objects.get(pk=order_id)

    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related("schedule").get(pk=order_id)
    require_matching_etag(request, order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    blocker = dispatched_revocation_blocker(order)
    if blocker:
        raise Conflict(blocker)
    from apps.inventory.public_stock_mode import require_document_stock_mode
    if require_document_stock_mode(order):
        from .public_stock_services import revoke_public_dispatch
        return revoke_public_dispatch(order, request_id=request_id, reason=reason, digest=digest,
            actor_employee=actor_employee, request=request)

    task = lock_task(order)
    sources = list(OutsourcingDispatchLine.objects.select_for_update(of=("self",)).filter(dispatch__order=order)
        .select_related("material_item__allocation", "raw_material", "unit", "zone__warehouse", "inbound_line__inbound")
        .order_by("id"))
    returned = {
        row["dispatch_line_id"]: row["total"]
        for row in OutsourcingRawReturnLine.objects.filter(dispatch_line__in=sources)
        .values("dispatch_line_id").annotate(total=Sum("quantity"))
    }
    remaining_by_factory = defaultdict(list)
    for source in sources:
        remaining = source.issued_quantity - returned.get(source.pk, Decimal("0"))
        if remaining < 0:
            raise Conflict("历史退料数量超过原发料数量，请先核对。")
        if remaining:
            remaining_by_factory[source.material_item.allocation.factory_id].append((source, remaining))

    list(RawMaterialInformation.objects.select_for_update().filter(
        pk__in={source.raw_material_id for source in sources}).order_by("pk"))
    requirements = {
        row.pk: row for row in OrderMaterialRequirement.objects.select_for_update().filter(
            pk__in={source.requirement_id for source in sources}).order_by("pk")
    }
    source_inbound_ids = {source.inbound_line_id for source in sources}
    parent_ids = set(MaterialInboundLine.objects.filter(pk__in=source_inbound_ids).values_list("inbound_id", flat=True))
    inbound_records = {
        row.pk: row for row in MaterialInbound.objects.select_for_update(of=("self",)).filter(
            pk__in=parent_ids).order_by("pk")
    }
    inbound_lines = {
        row.pk: row for row in MaterialInboundLine.objects.select_for_update(of=("self",)).filter(
            pk__in=source_inbound_ids).order_by("pk")
    }
    zone_ids = {source.zone_id for source in sources}
    warehouse_ids = set(WarehouseZone.objects.filter(pk__in=zone_ids).values_list("warehouse_id", flat=True))
    warehouses = {
        row.pk: row for row in Warehouse.objects.select_for_update(of=("self",)).filter(
            pk__in=warehouse_ids).order_by("pk")
    }
    zones = {
        row.pk: row for row in WarehouseZone.objects.select_for_update(of=("self",)).filter(
            pk__in=zone_ids).order_by("pk")
    }
    balances = {
        row.pk: row for row in MaterialStockBalance.objects.select_for_update().filter(
            pk__in={source.stock_balance_id for source in sources if source.stock_balance_id}
        ).order_by("raw_material_id", "unit_id", "zone_id", "id")
    }
    if len(requirements) != len({source.requirement_id for source in sources}):
        raise Conflict("原订单用料额度记录缺失，不能撤销发料。")
    if len(inbound_lines) != len({source.inbound_line_id for source in sources}):
        raise Conflict("原发料批次已缺失，不能自动退回。")
    if any(line.inbound_id not in inbound_records for line in inbound_lines.values()):
        raise Conflict("原发料入库单发生变化，不能自动退回。")
    if len(zones) != len(zone_ids) or any(zone.warehouse_id not in warehouses for zone in zones.values()):
        raise Conflict("原发料库区发生变化，不能自动退回。")

    before = order_audit_snapshot(order)
    restored = []
    for factory_id, factory_sources in sorted(remaining_by_factory.items(), key=lambda item: str(item[0])):
        return_request_id = uuid5(UUID(str(request_id)), f"raw-return:{factory_id}")
        if OutsourcingRawReturn.objects.filter(request_id=return_request_id).exists():
            raise Conflict("撤销退料请求标识已被使用，请刷新后重试。")
        record = OutsourcingRawReturn.objects.create(
            order=order, factory_id=factory_id, request_id=return_request_id,
            payload_hash=_json_hash({"order_id": str(order.pk),
                "factory_id": str(factory_id), "request_id": str(request_id), "reason": reason}),
            reason=f"撤销外发单：{reason}", actor=actor_employee,
        )
        for source, amount in factory_sources:
            inbound_line = inbound_lines[source.inbound_line_id]
            inbound = inbound_records.get(inbound_line.inbound_id)
            inbound_material = inbound_line_material(inbound_line)
            zone = zones[source.zone_id]
            warehouse = warehouses[zone.warehouse_id]
            is_pipe = source.snapshot["kind"] == "PIPE"
            if (zone.status != "ACTIVE" or warehouse.status != "ACTIVE"
                    or warehouse.warehouse_type != "MATERIAL"
                    or inbound_line.zone_id != source.zone_id
                    or inbound is None or inbound.status != MaterialInboundStatus.CONFIRMED
                    or inbound_line.accepted_quantity <= 0
                    or inbound_material is None or inbound_material.pk != source.raw_material_id
                    or inbound_material.unit_id != source.unit_id
                    or inbound_line.measurement_kind != ("PIPE" if is_pipe else "OTHER")
                    or (not is_pipe and inbound_line.source_unit_text_snapshot not in
                        {source.unit.unit_name, source.unit.unit_code})
                    or (is_pipe and inbound_line.raw_bar_length_m != Decimal(source.snapshot["raw_bar_length_m"]))):
                raise Conflict("原发料批次或库区已变更、停用，不能自动原路退回。")
            if is_pipe and amount != amount.to_integral_value():
                raise Conflict("管材剩余根数不是整数，不能自动退回。")
            equivalent = int(amount) * int(source.snapshot["pieces_per_bar"]) if is_pipe else None
            meters = amount * Decimal(source.snapshot["raw_bar_length_m"]) if is_pipe else (
                amount if source.snapshot["kind"] == "FABRIC" else None
            )
            return_line = OutsourcingRawReturnLine.objects.create(
                record=record, dispatch_line=source, quantity=amount,
                meter_quantity=meters, piece_quantity_equivalent=equivalent, snapshot=source.snapshot,
            )
            snapshot = {**source.snapshot, "dispatch_line_id": str(source.pk),
                        "inbound_line_id": str(source.inbound_line_id), "revocation_request_id": str(request_id)}
            if is_pipe:
                balance = balances.get(source.stock_balance_id)
                if (balance is None or balance.inbound_line_id != source.inbound_line_id
                        or balance.zone_id != source.zone_id or balance.raw_material_id != source.raw_material_id
                        or balance.unit_id != source.unit_id
                        or balance.measurement_kind != "PIPE" or balance.quality != MaterialStockQuality.AVAILABLE
                        or balance.raw_bar_length_m != Decimal(source.snapshot["raw_bar_length_m"])):
                    raise Conflict("原管材批次库存身份已变化，不能自动退回。")
                change_pipe_balance(balance, amount, direction="IN", source_type="OUTSOURCING_RAW_RETURN",
                    source_id=record.pk, source_line_id=return_line.pk, task=task, actor=actor_employee,
                    snapshot=snapshot)
            else:
                credit_material_stock(raw_material=source.raw_material, unit=source.unit, zone=zone,
                    quantity=amount, source_type="OUTSOURCING_RAW_RETURN", source_id=record.pk,
                    source_line_id=return_line.pk, production_task=task, actor_employee=actor_employee,
                    snapshot=snapshot)
            requirement = requirements[source.requirement_id]
            delta = Decimal(equivalent) if is_pipe else amount
            if delta > requirement.outsourcing_issued_quantity:
                raise Conflict("来源净外发额度不足，不能重复恢复。")
            requirement.outsourcing_issued_quantity -= delta
            requirement.save(update_fields=["outsourcing_issued_quantity", "updated_at"])
            restored.append({"dispatch_line_id": str(source.pk), "inbound_line_id": str(source.inbound_line_id),
                             "zone_id": str(source.zone_id), "quantity": str(amount), "unit": source.unit.unit_name})

    order.status = "CANCELLED"
    order.cancel_reason = reason
    order.cancelled_at = timezone.now()
    order.cancelled_by_employee = actor_employee
    order.updated_by_employee = actor_employee
    order.version += 1
    order.save(update_fields=["status", "cancel_reason", "cancelled_at", "cancelled_by_employee",
                              "updated_by_employee", "version", "updated_at"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action="DISPATCH_REVOKED",
        actor_employee=actor_employee, before_data=before,
        after_data={**order_audit_snapshot(order), "reason": reason,
                    "revocation_request_id": str(request_id), "payload_hash": digest,
                    "restored_lines": restored},
        context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)
    return order


@transaction.atomic
def complete_order(*, order_id, request_id, actor_employee, request):
    require_order_craft(request, "outsourcing.complete_outsourcingorder", order_id)
    from .services import order_audit_snapshot, _json_hash
    lock_request("complete", request_id)
    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related("schedule").get(pk=order_id)
    if order.completion_request_id == request_id:
        return order
    if OutsourcingOrder.objects.filter(completion_request_id=request_id).exists():
        raise Conflict("同一结清请求已用于其他外发单。")
    require_matching_etag(request, order)
    active(order)
    lock_task(order)
    state = reconciliation(order)
    if not state["can_complete"]:
        raise ValidationError({"code": "RECONCILIATION_UNBALANCED", "blockers": state["blockers"]})
    before = order_audit_snapshot(order)
    order.status = "COMPLETED"
    order.completed_at = timezone.now()
    order.completion_request_id = request_id
    order.completion_payload_hash = _json_hash({"order_id": str(order_id)})
    bump(order, actor_employee, "COMPLETED", request, before=before)
    return order
