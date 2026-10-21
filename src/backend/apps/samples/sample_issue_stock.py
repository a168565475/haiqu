"""样品整单管材领料：采购按真实根米，核库可供按既有库存顺序整根分配。"""

from decimal import Decimal
from math import gcd
from uuid import UUID, uuid5

from django.db import transaction

from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_cutover import require_business_stock_write
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.inventory.public_stock_services import debit_public_stock, lock_public_stock_locations
from apps.inventory.tube_outsourcing_reservations import reserved_quantity_for_balance
from apps.products.models import RawMaterialInformation

from .models import SampleMaterialArrival


def pipe_arrivals(record, line_key):
    return list(SampleMaterialArrival.objects.filter(
        procurement_request__material_request=record, line_key=line_key,
        inbound_line__inbound__status="CONFIRMED",
    ).select_related("inbound_line").order_by("inbound_line_id"))


def pipe_arrival_reservations(arrivals):
    model = PublicStockMovement if public_flow_enabled() else MaterialStockMovement
    quantities = {row.inbound_line_id: Decimal(row.inbound_line.accepted_bar_count or 0) for row in arrivals}
    reserved = {}
    for movement in model.objects.filter(source_type="MATERIAL_INBOUND", source_line_id__in=quantities, direction="IN"):
        reserved[movement.balance_id] = reserved.get(movement.balance_id, Decimal("0")) + quantities[movement.source_line_id]
    return reserved


def _whole_bar_quantities(groups, meters):
    """按单根长度合并后找精确整根组合；不把可供米数向上或向下取整。"""
    if meters == 0:
        return {}
    cents = meters * 100
    if cents != cents.to_integral_value():
        raise Conflict("核库可供米数无法对应整根管材，请核对单根长度。")
    target = int(cents)
    lengths = list(groups)
    values = [int(length * 100) for length in lengths]
    limits = [int(groups[length]) for length in lengths]
    for length, value, limit in zip(lengths, values, limits):
        if target % value == 0 and target // value <= limit:
            return {length: target // value}
    suffix_total, suffix_gcd = [0] * (len(values) + 1), [0] * (len(values) + 1)
    for index in range(len(values) - 1, -1, -1):
        suffix_total[index] = suffix_total[index + 1] + values[index] * limits[index]
        suffix_gcd[index] = gcd(suffix_gcd[index + 1], values[index])
    failed, attempts = set(), 0

    def find(index, remaining):
        nonlocal attempts
        if remaining == 0:
            return [0] * (len(values) - index)
        if (index == len(values) or remaining > suffix_total[index]
                or remaining % suffix_gcd[index] or (index, remaining) in failed):
            return None
        value = values[index]
        maximum = min(limits[index], remaining // value)
        minimum = max(0, (remaining - suffix_total[index + 1] + value - 1) // value)
        if index == len(values) - 1:
            return [remaining // value] if remaining % value == 0 and remaining // value <= maximum else None
        common = gcd(value, suffix_gcd[index + 1])
        if remaining % common:
            return None
        step = suffix_gcd[index + 1] // common
        residue = ((remaining // common) * pow(value // common, -1, step)) % step if step > 1 else 0
        first = maximum - (maximum - residue) % step
        for bars in range(first, minimum - 1, -step):
            attempts += 1
            if attempts > 10000:
                raise Conflict("管材长度组合过多，暂无法自动确定整根分配，请先核对本次可供材料。")
            rest = find(index + 1, remaining - bars * value)
            if rest is not None:
                return [bars, *rest]
        failed.add((index, remaining))
        return None

    chosen = find(0, target)
    if chosen is None:
        raise Conflict("核库可供米数无法按当前库存整根领足，请核对可供米数和单根长度；本次未扣库存。")
    return dict(zip(lengths, chosen))


def plan_pipe_issue(*, raw_material, warehouse_quantity, arrivals=(), lock=False, planned=None, pending_arrivals=None):
    """只分配本单到货根数及核库数量；不把同料号的全部库存当作本单材料。"""
    public = public_flow_enabled()
    model = PublicStockBalance if public else MaterialStockBalance
    filters = {"stock_kind": "RAW_PIPE"} if public else {"measurement_kind": "PIPE"}
    balances = model.objects.filter(
        **filters, raw_material=raw_material, unit=raw_material.unit, quality="AVAILABLE",
        quantity__gt=0, zone__status="ACTIVE", zone__warehouse__status="ACTIVE",
        zone__warehouse__warehouse_type="MATERIAL",
    ).select_related("zone", "zone__warehouse").order_by("zone_id", "id")
    if lock:
        RawMaterialInformation.objects.select_for_update().get(pk=raw_material.pk)
        if public:
            lock_public_stock_locations(list(balances.values_list("zone_id", flat=True)))
        balances = balances.select_for_update(of=("self",))
    balances = list(balances)
    by_id = {row.pk: row for row in balances}
    used = planned if planned is not None else {}
    protected = dict(pending_arrivals or {})
    free = {}
    for balance in balances:
        if not balance.raw_bar_length_m or balance.meter_quantity != balance.quantity * balance.raw_bar_length_m:
            raise Conflict("管材库存根数与米数不一致，请先核对库存。")
        reserved = reserved_quantity_for_balance(balance) if public else Decimal("0")
        free[balance.pk] = max(balance.quantity - reserved - used.get(balance.pk, Decimal("0")), Decimal("0"))
    allocations = {}

    def allocate(balance, bars, inbound_line_id=None):
        if free.get(balance.pk, Decimal("0")) < bars:
            raise Conflict("本次打样安排的管材库存不足或已被预留，请刷新后核对库存。")
        free[balance.pk] -= bars
        entry = allocations.setdefault(balance.pk, {"balance": balance, "bars": Decimal("0"), "inbound_line_ids": []})
        entry["bars"] += bars
        if inbound_line_id:
            entry["inbound_line_ids"].append(str(inbound_line_id))

    movement_model = PublicStockMovement if public else MaterialStockMovement
    inbound_ids = [arrival.inbound_line_id for arrival in arrivals]
    movements = {row.source_line_id: row for row in movement_model.objects.filter(
        source_type="MATERIAL_INBOUND", source_line_id__in=inbound_ids, direction="IN",
    )}
    for arrival in arrivals:
        line = arrival.inbound_line
        movement = movements.get(line.pk)
        balance = by_id.get(movement.balance_id) if movement else None
        if (not balance or line.measurement_kind != "PIPE" or not line.accepted_bar_count
                or line.raw_material_information_id != raw_material.pk
                or line.raw_bar_length_m != balance.raw_bar_length_m
                or movement.quantity != line.accepted_bar_count
                or line.accepted_quantity != line.accepted_bar_count * line.raw_bar_length_m):
            raise Conflict("本次打样管材到货与当前库存来源不一致，请先核对入库记录。")
        allocate(balance, Decimal(line.accepted_bar_count), line.pk)
        protected[balance.pk] = max(protected.get(balance.pk, Decimal("0")) - line.accepted_bar_count, Decimal("0"))

    groups = {}
    for balance in balances:
        available = max(free[balance.pk] - protected.get(balance.pk, Decimal("0")), Decimal("0"))
        groups[balance.raw_bar_length_m] = groups.get(balance.raw_bar_length_m, Decimal("0")) + available
    quantities = _whole_bar_quantities(groups, warehouse_quantity)
    for balance in balances:
        available = max(free[balance.pk] - protected.get(balance.pk, Decimal("0")), Decimal("0"))
        bars = min(quantities.get(balance.raw_bar_length_m, 0), available)
        if bars > 0:
            allocate(balance, bars)
            quantities[balance.raw_bar_length_m] -= bars
    result = list(allocations.values())
    for entry in result:
        balance = entry["balance"]
        used[balance.pk] = used.get(balance.pk, Decimal("0")) + entry["bars"]
    if pending_arrivals is not None:
        pending_arrivals.clear()
        pending_arrivals.update(protected)
    return {"public": public, "allocations": result}


def pipe_plan_payload(plan):
    return [{
        "balanceId": str(row["balance"].pk),
        "warehouseName": row["balance"].zone.warehouse.warehouse_name,
        "zoneName": row["balance"].zone.zone_name,
        "rawBarLengthM": str(row["balance"].raw_bar_length_m),
        "barCount": int(row["bars"]),
        "meterQuantity": str(row["bars"] * row["balance"].raw_bar_length_m),
    } for row in plan["allocations"]]


def issued_pipe_payload(issue, line):
    batches = []
    for model in (PublicStockMovement, MaterialStockMovement):
        movements = model.objects.filter(
            source_type="SAMPLE_MATERIAL_ISSUE", source_id=issue.pk, direction="OUT",
            snapshot__sample_issue_line_id=str(line.pk),
        ).select_related("balance__zone__warehouse").order_by("balance__zone_id", "balance_id")
        for movement in movements:
            batches.append({
                "balanceId": str(movement.balance_id),
                "warehouseName": movement.balance.zone.warehouse.warehouse_name,
                "zoneName": movement.balance.zone.zone_name,
                "rawBarLengthM": str(movement.balance.raw_bar_length_m),
                "barCount": int(movement.quantity),
                "meterQuantity": str(movement.meter_quantity),
            })
    return batches


@transaction.atomic
def debit_pipe_plan(*, plan, source_id, source_line_id, actor_employee, snapshot):
    require_business_stock_write(source_type="SAMPLE_MATERIAL_ISSUE", direction="OUT")
    movements = []
    for allocation in plan["allocations"]:
        balance, bars = allocation["balance"], allocation["bars"]
        meters = bars * balance.raw_bar_length_m
        # 一条领料明细可跨库区；每个余额用稳定子来源编号满足流水幂等约束。
        movement_line_id = uuid5(UUID(str(source_line_id)), str(balance.pk))
        movement_snapshot = {
            **snapshot, "sample_issue_line_id": str(source_line_id), "zone_id": str(balance.zone_id),
            "raw_bar_length_m": str(balance.raw_bar_length_m), "issued_meters": str(meters),
            "issued_bar_count": int(bars), "inbound_line_ids": allocation["inbound_line_ids"],
        }
        if plan["public"]:
            movements.append(debit_public_stock(
                balance_id=balance.pk, quantity=bars, source_type="SAMPLE_MATERIAL_ISSUE",
                source_id=source_id, source_line_id=movement_line_id, actor_employee=actor_employee,
                snapshot=movement_snapshot,
            ))
            continue
        existing = MaterialStockMovement.objects.filter(
            source_type="SAMPLE_MATERIAL_ISSUE", source_line_id=movement_line_id, direction="OUT",
        ).first()
        if existing:
            if existing.balance_id != balance.pk or existing.quantity != bars or existing.snapshot != movement_snapshot:
                raise Conflict("该管材领料来源已使用不同数量记账。")
            movements.append(existing)
            continue
        balance = MaterialStockBalance.objects.select_for_update().get(pk=balance.pk)
        before, before_meters = balance.quantity, balance.meter_quantity
        if before < bars:
            raise Conflict("管材库存已变化，本次未扣库存，请刷新后重试。")
        balance.quantity -= bars
        balance.meter_quantity -= meters
        balance.version += 1
        balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
        movements.append(MaterialStockMovement.objects.create(
            balance=balance, direction="OUT", quantity=bars, meter_quantity=meters,
            before_quantity=before, after_quantity=balance.quantity,
            before_meter_quantity=before_meters, after_meter_quantity=balance.meter_quantity,
            source_type="SAMPLE_MATERIAL_ISSUE", source_id=source_id, source_line_id=movement_line_id,
            actor_employee=actor_employee, snapshot=movement_snapshot,
        ))
    return movements
