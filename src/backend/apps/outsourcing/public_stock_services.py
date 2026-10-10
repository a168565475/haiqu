"""委外公共库存路径：订单额度保留，仓库只按物料身份和库区记账。"""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4, uuid5

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.boms.material_attributes import bom_attribute_fields
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.models import MaterialStockBalance, PublicStockBalance, WarehouseZone
from apps.inventory.public_stock_identity import build_pipe_stock_identity, validate_public_identity
from apps.inventory.public_stock_services import _lock_source, credit_public_stock, debit_public_stock, lock_public_stock_locations
from apps.inventory.stock_services import credit_material_stock, debit_material_stock
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
from apps.material_issues.material_flow import pipe_specs
from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities
from apps.material_issues.requirements import build_requirement_specs, sync_order_requirements
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.production_scheduling.models import ProductionSchedule
from apps.products.models import RawMaterialInformation

from .material_flow import pipe_amount, quantity
from .models import (OutsourcingDispatch, OutsourcingDispatchLine, OutsourcingRawReturn,
                     OutsourcingRawReturnLine)


PUBLIC_MODE = "PUBLIC_V2"


def json_snapshot(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def public_output_identity(processing, order):
    identity = validate_public_identity(processing.component_snapshot.get("public_output_identity"))
    if (identity["stock_kind"] != "SEMI" or str(identity["unit_id"]) != str(processing.unit_id)
            or identity["identity_snapshot"]["completed_craft"]["id"] != str(order.craft_id)):
        raise Conflict("加工产出的冻结身份、单位或实际完成工艺不一致。")
    return identity


def lock_order_sources(order, items=None):
    """在取库区／余额锁前锁齐来源父对象，避免流水外键检查反序。"""
    # 建单、原料退回及投入登记均先锁排产，再锁生产任务。
    ProductionSchedule.objects.select_for_update(of=("self",)).get(pk=order.schedule_id)
    task_id = order.schedule.production_task_id
    ProductionTask.objects.select_for_update(of=("self",)).get(pk=task_id)
    products = list(order.products.values_list("schedule_product__product_line_id", flat=True))
    list(ProductionTaskProduct.objects.select_for_update(of=("self",)).filter(pk__in=products).order_by("id"))
    list(Bom.objects.select_for_update(of=("self",)).filter(pk__in=order.products.values_list("bom_id", flat=True)).order_by("id"))
    line_ids = set(order.products.values_list("processing_items__bom_line_id", flat=True))
    line_ids.update(order.products.values_list("processing_items__allocations__material_items__bom_material_line_id", flat=True))
    list(BomLine.objects.select_for_update(of=("self",)).filter(pk__in=line_ids).order_by("id"))


def _raws(items):
    ids = {item.conversion_snapshot["raw_material_id"] for item in items}
    rows = RawMaterialInformation.objects.select_related("unit", "category").filter(pk__in=ids)
    result = {str(row.pk): row for row in rows}
    if len(result) != len(ids):
        raise Conflict("委外材料的冻结原料已不存在。")
    for row in result.values():
        if (row.archived_at or row.item_type != "MATERIAL" or row.category.status != "ACTIVE"
                or row.category.archived_at or row.unit.status != "ACTIVE" or row.unit.archived_at):
            raise Conflict("委外原料、品类或单位已停用，请核对。")
    return result


def _requirements(order, items, *, lock=False):
    task_id = order.schedule.production_task_id
    by_line = {}
    ordinary_items = [item for item in items if item.conversion_snapshot["kind"] != "PIPE"]
    if ordinary_items:
        if lock:
            _, rows, blockers, _ = sync_order_requirements(task_id)
            targets = {str(item.bom_material_line_id) for item in ordinary_items}
            products = {str(item.allocation.processing_item.order_product.schedule_product.product_line_id) for item in ordinary_items}
            relevant = [b for b in blockers if b.get("bom_line_id") in targets
                        or (not b.get("bom_line_id") and b.get("product_line_id") in products)]
            if relevant:
                raise ValidationError({"materials": "订单原料来源尚未就绪。", "blockers": relevant})
            for row in rows:
                for contribution in row.contributions.filter(is_current=True):
                    by_line[contribution.bom_line_id] = row
        else:
            _, specs, _, _ = build_requirement_specs(task_id)
            existing = {r.pk: r for r in OrderMaterialRequirement.objects.filter(pk__in=[s["id"] for s in specs])}
            for spec in specs:
                row = existing.get(spec["id"]) or OrderMaterialRequirement(id=spec["id"],
                    production_task_id=task_id, raw_material=spec["raw_material"], unit=spec["unit"])
                row.required_quantity = spec["required_quantity"]
                for contribution in spec["contributions"]:
                    by_line[contribution["bom_line"].pk] = row
    pipe_items = [item for item in items if item.conversion_snapshot["kind"] == "PIPE"]
    if lock:
        for line_id in sorted({item.bom_material_line_id for item in pipe_items}, key=str):
            by_line[line_id] = sync_pipe_requirement(line_id)
    else:
        product_ids = {item.allocation.processing_item.order_product.schedule_product.product_line_id for item in pipe_items}
        for product_id in product_ids:
            specs, _ = pipe_specs(task_id, product_id)
            existing = {r.pk: r for r in OrderMaterialRequirement.objects.filter(pk__in=[s["id"] for s in specs])}
            for spec in specs:
                row = existing.get(spec["id"]) or OrderMaterialRequirement(id=spec["id"],
                    production_task_id=task_id, product_line_id=product_id,
                    raw_material=spec["raw_material"], unit=spec["unit"])
                row.required_quantity = Decimal(spec["snapshot"]["allowance_pieces"])
                by_line[spec["line"].pk] = row
    return by_line


def _lines(order, items, requirements, raws):
    issue = MaterialIssue(production_task_id=order.schedule.production_task_id, stock_mode=PUBLIC_MODE)
    result = {}
    for item in items:
        requirement = requirements.get(item.bom_material_line_id)
        if requirement is None:
            raise Conflict("当前材料没有有效订单额度，请先核对已确认 BOM。")
        raw = raws[item.conversion_snapshot["raw_material_id"]]
        snapshot = dict(item.conversion_snapshot)
        if snapshot["kind"] == "PIPE":
            frozen = snapshot.get("public_identity")
            identity = validate_public_identity(frozen) if frozen else build_pipe_stock_identity(
                raw_material=raw, raw_bar_length_m=Decimal(snapshot["raw_bar_length_m"]), unit=raw.unit)
            if (str(identity["raw_material_id"]) != str(raw.pk) or str(identity["unit_id"]) != str(raw.unit_id)
                    or identity["raw_bar_length_m"] != Decimal(snapshot["raw_bar_length_m"])):
                raise Conflict("冻结的公共管材身份与发料换算不一致。")
            snapshot["public_identity"] = json_snapshot(identity)
        result[item.pk] = MaterialIssueLine(issue=issue, requirement=requirement, raw_material=raw,
            unit=requirement.unit, requested_quantity=Decimal(item.planned_piece_count if snapshot["kind"] == "PIPE"
                else item.planned_issue_quantity), conversion_snapshot=snapshot)
    return issue, result


def _pool(line):
    identity = line.conversion_snapshot.get("public_identity")
    return (identity["stock_kind"], identity["identity_key"], str(identity["unit_id"])) if identity else (
        "OTHER", str(line.raw_material_id), str(line.raw_material.unit_id))


def _ordinary_balances(lines):
    filters = Q(pk__in=[])
    for line in lines:
        if _pool(line)[0] == "OTHER":
            filters |= Q(raw_material_id=line.raw_material_id, unit_id=line.raw_material.unit_id)
    return MaterialStockBalance.objects.filter(filters, measurement_kind="OTHER", quality="AVAILABLE",
        zone__status="ACTIVE", zone__warehouse__status="ACTIVE", zone__warehouse__warehouse_type="MATERIAL"
    ).select_related("zone__warehouse", "unit").order_by("raw_material_id", "unit_id", "zone_id", "id")


def _stock_rows(context, lines):
    result = defaultdict(list)
    for pool, balances in context["balances"].items():
        result[pool].extend(balances)
    for balance in _ordinary_balances(lines):
        result[("OTHER", str(balance.raw_material_id), str(balance.unit_id))].append(balance)
    return result


def public_dispatch_context(order):
    from .dispatch_services import material_items, ready_snapshot
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    items = material_items(order)
    for item in items:
        ready_snapshot(item)
    raws, requirements = _raws(items), _requirements(order, items)
    issue, lines = _lines(order, items, requirements, raws)
    context = public_issue_quantity_context(issue, lines=list(lines.values()))
    stock_rows = _stock_rows(context, lines.values())
    result = []
    for item in items:
        line = lines[item.pk]
        snapshot, pool = line.conversion_snapshot, _pool(line)
        is_pipe = snapshot["kind"] == "PIPE"
        factor = Decimal(snapshot["pieces_per_bar"]) if is_pipe else Decimal(1)
        zones = [{"zone_id": str(b.zone_id), "warehouse_name": b.zone.warehouse.warehouse_name,
            "zone_name": b.zone.zone_name, "available_quantity": str(b.quantity),
            "available_input_quantity": str(b.quantity * factor),
            "available_meters": str(b.meter_quantity) if is_pipe else None} for b in stock_rows[pool]]
        values = public_line_quantities(line, context=context)
        values["max_issue_quantity"] = str(min(line.requested_quantity, Decimal(values["max_issue_quantity"])))
        result.append({"material_item_id": str(item.pk), "factory_name": item.allocation.factory_snapshot.get("name", ""),
            "material_number": item.material_snapshot.get("material_number", ""), "material_name": item.material_snapshot.get("name", ""),
            "specification": item.material_snapshot.get("specification", ""), "color": item.material_snapshot.get("color", ""),
             "bom_attributes": item.material_snapshot.get("bom_attributes") or bom_attribute_fields(item.bom_material_line),
            "planned_issue_quantity": str(line.requested_quantity), "unit": "支" if is_pipe else item.unit_text,
            "procurement_required_quantity": str(item.planned_issue_quantity), "procurement_unit": item.unit_text,
            "procurement_conversion": False, "suggested_conversion_factor": "1", "conversion_evidence": "",
            "identity_resolved": True, "planned_batches": [], "batch_selection": False,
            "conversion_snapshot": snapshot, "candidates": [], "zones": zones, "quota_error": "", **values})
    return {"order_id": str(order.pk), "order_number": order.order_number, "stock_mode": PUBLIC_MODE, "materials": result}


def _lock_pools(lines):
    for pool in sorted({_pool(line) for line in lines}):
        value = int.from_bytes(hashlib.sha256(("public-issue-pool:" + ":".join(pool)).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [value])


def confirm_public_dispatch(order, *, request_id, digest, line_inputs, remark, actor_employee, request):
    """调用方持有请求锁、单据锁和事务；同一公共池先累计整单，再扣减。"""
    from .dispatch_services import material_items, ready_snapshot
    from .services import _assert_order_source_unchanged, order_audit_snapshot
    lock_order_sources(order)
    _assert_order_source_unchanged(order)
    items = material_items(order)
    by_id = {item.pk: item for item in items}
    for item in items:
        ready_snapshot(item)
    if not line_inputs or any(row["material_item_id"] not in by_id for row in line_inputs):
        raise ValidationError({"lines": "请填写属于本单的材料、库区和数量。"})
    if any(row.get("inbound_line_id") or not row.get("zone_id") for row in line_inputs):
        raise ValidationError({"lines": "公共库存只按库区发料，不接受采购批次。"})
    pairs = [(row["material_item_id"], row["zone_id"]) for row in line_inputs]
    if len(pairs) != len(set(pairs)):
        raise ValidationError({"lines": "同一材料不能重复选择同一库区。"})
    requirements, raws = _requirements(order, items, lock=True), _raws(items)
    issue, lines = _lines(order, items, requirements, raws)
    _lock_pools(lines.values())
    prepared, by_item, by_quota, by_pool, by_zone = [], defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    for row in line_inputs:
        item, line = by_id[row["material_item_id"]], lines[row["material_item_id"]]
        if Decimal(row.get("conversion_factor", 1)) != 1:
            raise ValidationError({"conversion_factor": "公共库存使用冻结 BOM 换算，不接受手工比例。"})
        entered = quantity(row["requested_quantity"])
        actual = Decimal(pipe_amount(entered, line.conversion_snapshot)["bar_count"]) if _pool(line)[0] == "RAW_PIPE" else entered
        event_id = uuid5(UUID(str(request_id)), f"dispatch:{item.pk}:{row['zone_id']}")
        prepared.append((item, line, row["zone_id"], entered, actual, event_id))
        by_item[item.pk] += entered
        by_quota[line.requirement_id] += entered
        by_pool[_pool(line)] += actual
        by_zone[(_pool(line), str(row["zone_id"]))] += actual
    for _, line, _, _, _, event_id in sorted(prepared, key=lambda entry: str(entry[-1])):
        if _pool(line)[0] == "RAW_PIPE":
            _lock_source({"source_type": "OUTSOURCING_DISPATCH", "source_line_id": event_id}, "OUT")
    context = public_issue_quantity_context(issue, lines=list(lines.values()))
    stock_rows = _stock_rows(context, lines.values())
    all_balances = [b for rows in stock_rows.values() for b in rows]
    zone_ids = {row["zone_id"] for row in line_inputs} | {b.zone_id for b in all_balances}
    zones = lock_public_stock_locations(zone_ids)
    list(_ordinary_balances(lines.values()).select_for_update(of=("self",)))
    public_ids = [b.pk for rows in context["balances"].values() for b in rows]
    list(PublicStockBalance.objects.select_for_update(of=("self",)).filter(pk__in=public_ids).order_by("id"))
    # 等锁期间入库、退料可能变化，余额和待审量必须重新读取。
    context = public_issue_quantity_context(issue, lines=list(lines.values()))
    stock_rows = _stock_rows(context, lines.values())
    balances = {(pool, str(b.zone_id)): b for pool, rows in stock_rows.items() for b in rows}
    for item in items:
        line = lines[item.pk]
        values = public_line_quantities(line, context=context)
        if item.pk not in by_item and Decimal(values["max_issue_quantity"]) > 0:
            raise ValidationError({"lines": "本次可领大于 0 的材料必须填写发料数量。"})
        if by_item[item.pk] > line.requested_quantity:
            raise ValidationError({"lines": "材料的库区发料合计不能超过计划数量。"})
        if by_quota[line.requirement_id] > Decimal(values["order_remaining"]):
            raise Conflict("外发与厂内已领、待审核领料合计超过订单剩余额度。")
    for pool, amount in by_pool.items():
        if amount > max(context["stock"][pool] - context["pending_stock"][pool], Decimal(0)):
            raise Conflict("公共库存不足，已扣除其他订单待审核领料占用。")
    for key, amount in by_zone.items():
        balance = balances.get(key)
        if balance is None or amount > balance.quantity:
            raise Conflict("所选库区公共库存不足。")
    before = order_audit_snapshot(order)
    dispatch = OutsourcingDispatch.objects.create(order=order,
        dispatch_number=f"FL-{timezone.localdate():%Y%m%d}-{uuid4().hex[:8].upper()}",
        client_request_id=request_id, request_payload_hash=digest, remark=remark,
        confirmed_by_employee=actor_employee, confirmed_at=timezone.now())
    for item, line, zone_id, entered, actual, event_id in prepared:
        balance = balances[(_pool(line), str(zone_id))]
        raw, is_pipe = line.raw_material, _pool(line)[0] == "RAW_PIPE"
        zone = zones[zone_id]
        snapshot = {**line.conversion_snapshot, "stock_mode": PUBLIC_MODE,
            "warehouse": zone.warehouse.warehouse_name, "zone": zone.zone_name, "location": "",
            "zone_id": str(zone.pk), "factory": item.allocation.factory_snapshot.get("name", ""),
            "requested_quantity": str(entered), "stock_quantity": str(actual), "stock_unit": raw.unit.unit_name,
            "stock_before": str(balance.quantity), "stock_after": str(balance.quantity - actual)}
        meters = actual * balance.raw_bar_length_m if is_pipe else None
        record = OutsourcingDispatchLine.objects.create(id=event_id, dispatch=dispatch, material_item=item,
            requirement=line.requirement, raw_material=raw, unit=raw.unit, zone=zone,
            source_quantity=actual, material_quantity=actual, conversion_factor=1, source_unit_snapshot=item.unit_text,
            source_snapshot=snapshot, issued_quantity=actual, snapshot=snapshot,
            public_stock_balance=balance if is_pipe else None,
            issued_piece_count=int(entered) if is_pipe else None, issued_meters=meters)
        if is_pipe:
            movement = debit_public_stock(balance_id=balance.pk, quantity=actual, source_type="OUTSOURCING_DISPATCH",
                source_id=dispatch.pk, source_line_id=record.pk, actor_employee=actor_employee,
                production_task=order.schedule.production_task_id,
                product_line=item.allocation.processing_item.order_product.schedule_product.product_line_id,
                bom_line=item.bom_material_line_id, snapshot=snapshot)
            record.public_stock_movement = movement
            record.save(update_fields=["public_stock_movement", "updated_at"])
        else:
            debit_material_stock(raw_material=raw, unit=raw.unit, quantity=actual,
                source_type="OUTSOURCING_DISPATCH", source_id=dispatch.pk, source_line_id=record.pk,
                actor_employee=actor_employee, production_task=order.schedule.production_task, zone=zone, snapshot=snapshot)
        balance.quantity -= actual
    for requirement in {r.pk: r for r in requirements.values()}.values():
        if by_quota[requirement.pk]:
            requirement.outsourcing_issued_quantity += by_quota[requirement.pk]
            requirement.save(update_fields=["outsourcing_issued_quantity", "updated_at"])
    order.status = "PROCESSING"
    order.version += 1
    order.updated_by_employee = actor_employee
    order.save(update_fields=["status", "version", "updated_by_employee", "updated_at"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action="DISPATCH_CONFIRMED",
        actor_employee=actor_employee, before_data=before, after_data=order_audit_snapshot(order),
        context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)
    return order


def reversible_public_source(source):
    value = (lambda key: source.get(key)) if isinstance(source, dict) else (lambda key: getattr(source, key, None))
    snapshot = value("snapshot") or {}
    if snapshot.get("stock_mode") != PUBLIC_MODE or snapshot.get("schema_version") != 2 or not value("zone_id"):
        return False
    if value("inbound_line_id") or value("stock_balance_id"):
        return False
    if snapshot.get("kind") == "PIPE":
        try:
            identity = validate_public_identity(snapshot.get("public_identity"))
            return bool(value("public_stock_balance_id") and value("public_stock_movement_id")
                and identity["stock_kind"] == "RAW_PIPE"
                and identity["raw_bar_length_m"] == Decimal(snapshot["raw_bar_length_m"])
                and Decimal(str(value("issued_piece_count"))) == Decimal(str(value("issued_quantity"))) * Decimal(snapshot["pieces_per_bar"]))
        except (ValueError, TypeError, KeyError, ArithmeticError, ValidationError):
            return False
    return snapshot.get("kind") in {"FABRIC", "OTHER"}


def restore_public_sources(order, source_amounts, *, record, actor_employee, revocation_request_id=None):
    """退回原公共身份和库区；订单归属只用于恢复原单额度，不成为库存身份。"""
    lock_order_sources(order)
    source_ids = [source.pk for source, _ in source_amounts]
    sources = {s.pk: s for s in OutsourcingDispatchLine.objects.select_for_update(of=("self",)).filter(pk__in=source_ids)
        .select_related("raw_material__unit", "unit", "zone__warehouse", "public_stock_movement__balance",
                        "material_item__allocation__processing_item__order_product__schedule_product").order_by("id")}
    list(RawMaterialInformation.objects.select_for_update(of=("self",)).filter(
        pk__in={s.raw_material_id for s in sources.values()}).order_by("id"))
    requirements = {r.pk: r for r in OrderMaterialRequirement.objects.select_for_update(of=("self",)).filter(
        pk__in={s.requirement_id for s in sources.values()}).order_by("id")}
    prepared = []
    for original, entered in source_amounts:
        source = sources[original.pk]
        if not reversible_public_source(source):
            raise Conflict("公共发料的冻结身份或实际出库凭据缺失，不能自动退回。")
        is_pipe = source.snapshot["kind"] == "PIPE"
        amount = quantity(entered, integer=is_pipe)
        event_id = uuid5(record.pk, str(source.pk))
        if is_pipe:
            _lock_source({"source_type": "OUTSOURCING_RAW_RETURN", "source_line_id": event_id}, "IN")
        prepared.append((source, amount, event_id))
    # 撤销可能按加工厂分组调用；从首组起按顺序锁齐整单库区，避免 B→A 反序。
    all_zone_ids = OutsourcingDispatchLine.objects.filter(dispatch__order=order).values_list("zone_id", flat=True)
    locked_zones = lock_public_stock_locations(all_zone_ids)
    for source, amount, event_id in prepared:
        source.zone = locked_zones[source.zone_id]
        is_pipe = source.snapshot["kind"] == "PIPE"
        equivalent = int(amount) * int(source.snapshot["pieces_per_bar"]) if is_pipe else None
        meters = amount * Decimal(source.snapshot["raw_bar_length_m"]) if is_pipe else (
            amount if source.snapshot["kind"] == "FABRIC" else None)
        snapshot = {**source.snapshot, "dispatch_line_id": str(source.pk)}
        if revocation_request_id:
            snapshot["revocation_request_id"] = str(revocation_request_id)
        returned = OutsourcingRawReturnLine.objects.create(id=event_id, record=record, dispatch_line=source,
            quantity=amount, meter_quantity=meters, piece_quantity_equivalent=equivalent, snapshot=snapshot)
        if is_pipe:
            original = source.public_stock_movement
            identity = validate_public_identity(source.snapshot["public_identity"])
            if (original.direction != "OUT" or original.source_type != "OUTSOURCING_DISPATCH"
                    or original.source_id != source.dispatch_id or original.source_line_id != source.pk
                    or original.balance_id != source.public_stock_balance_id or original.quantity != source.issued_quantity
                    or original.balance.zone_id != source.zone_id or original.balance.identity_key != identity["identity_key"]
                    or original.snapshot != source.snapshot):
                raise Conflict("原公共出库事件与冻结身份不一致。")
            movement = credit_public_stock(identity=identity, zone=source.zone, quantity=amount,
                source_type="OUTSOURCING_RAW_RETURN", source_id=record.pk, source_line_id=returned.pk,
                actor_employee=actor_employee, production_task=order.schedule.production_task_id,
                product_line=source.material_item.allocation.processing_item.order_product.schedule_product.product_line_id,
                bom_line=source.material_item.bom_material_line_id, snapshot=snapshot)
            returned.snapshot = {**snapshot, "public_stock_movement_id": str(movement.pk)}
            returned.save(update_fields=["snapshot", "updated_at"])
        else:
            if (source.zone.status != "ACTIVE" or source.zone.warehouse.status != "ACTIVE"
                    or source.zone.warehouse.warehouse_type != "MATERIAL"):
                raise Conflict("原发料库区不可用，请先核对。")
            credit_material_stock(raw_material=source.raw_material, unit=source.unit, zone=source.zone, quantity=amount,
                source_type="OUTSOURCING_RAW_RETURN", source_id=record.pk, source_line_id=returned.pk,
                production_task=order.schedule.production_task, actor_employee=actor_employee, snapshot=snapshot)
        requirement = requirements[source.requirement_id]
        delta = Decimal(equivalent) if is_pipe else amount
        if delta > requirement.outsourcing_issued_quantity:
            raise Conflict("原单净外发额度不足，不能重复恢复。")
        requirement.outsourcing_issued_quantity -= delta
        requirement.save(update_fields=["outsourcing_issued_quantity", "updated_at"])


def confirm_public_raw_return(order, *, request_id, factory_id, lines, reason, actor_employee, request, digest):
    from .reconciliation_services import reconciliation, bump
    sources = {s.pk: s for s in OutsourcingDispatchLine.objects.filter(dispatch__order=order,
        material_item__allocation__factory_id=factory_id)}
    if not reason.strip() or not lines or len({row["dispatch_line_id"] for row in lines}) != len(lines):
        raise ValidationError({"lines": "请填写退料原因和不重复的发料明细。"})
    remaining = {row["dispatch_line_id"]: Decimal(row["remaining"]) for row in reconciliation(order)["raw_materials"]}
    amounts = []
    for row in lines:
        source = sources.get(row["dispatch_line_id"])
        if source is None:
            raise ValidationError({"lines": "退料明细必须属于当前外发单及加工厂。"})
        amount = quantity(row["quantity"], integer=source.snapshot.get("kind") == "PIPE")
        if amount > remaining[str(source.pk)]:
            raise Conflict("退料超过尚未投入、未处理、未退回的原料。")
        amounts.append((source, amount))
    record = OutsourcingRawReturn.objects.create(order=order, factory_id=factory_id, request_id=request_id,
        payload_hash=digest, reason=reason, actor=actor_employee)
    restore_public_sources(order, amounts, record=record, actor_employee=actor_employee)
    bump(order, actor_employee, "RAW_RETURN_CONFIRMED", request)
    return order


def revoke_public_dispatch(order, *, request_id, reason, digest, actor_employee, request):
    from .services import _json_hash, order_audit_snapshot
    sources = list(OutsourcingDispatchLine.objects.filter(dispatch__order=order).select_related("material_item__allocation"))
    returned = {r["dispatch_line_id"]: r["total"] for r in OutsourcingRawReturnLine.objects.filter(dispatch_line__in=sources)
        .values("dispatch_line_id").annotate(total=Sum("quantity"))}
    by_factory = defaultdict(list)
    for source in sources:
        amount = source.issued_quantity - returned.get(source.pk, Decimal(0))
        if amount < 0:
            raise Conflict("累计退料大于实际发料，不能撤销。")
        if amount:
            by_factory[source.material_item.allocation.factory_id].append((source, amount))
    before = order_audit_snapshot(order)
    lock_order_sources(order)
    # 整次撤销先锁齐所有材料与额度，避免跨厂逐组恢复时反向取锁。
    list(RawMaterialInformation.objects.select_for_update(of=("self",)).filter(
        pk__in={s.raw_material_id for s in sources}).order_by("id"))
    list(OrderMaterialRequirement.objects.select_for_update(of=("self",)).filter(
        pk__in={s.requirement_id for s in sources}).order_by("id"))
    for factory_id, amounts in sorted(by_factory.items(), key=lambda pair: str(pair[0])):
        record = OutsourcingRawReturn.objects.create(order=order, factory_id=factory_id,
            request_id=uuid5(UUID(str(request_id)), f"raw-return:{factory_id}"),
            payload_hash=_json_hash({"request_id": str(request_id), "factory_id": str(factory_id)}),
            reason=f"撤销外发单：{reason}", actor=actor_employee)
        restore_public_sources(order, amounts, record=record, actor_employee=actor_employee, revocation_request_id=request_id)
    order.status = "CANCELLED"
    order.cancel_reason = reason
    order.cancelled_at = timezone.now()
    order.cancelled_by_employee = actor_employee
    order.updated_by_employee = actor_employee
    order.version += 1
    order.save(update_fields=["status", "cancel_reason", "cancelled_at", "cancelled_by_employee", "updated_by_employee", "version", "updated_at"])
    write_audit_log(object_type="OUTSOURCING_ORDER", object_id=order.pk, action="DISPATCH_REVOKED", actor_employee=actor_employee,
        before_data=before, after_data={**order_audit_snapshot(order), "reason": reason,
            "revocation_request_id": str(request_id), "payload_hash": digest},
        context_type="PRODUCTION_SCHEDULE", context_id=order.schedule_id, request=request)
    return order
