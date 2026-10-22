"""仓库核对保存具体库存来源；不预留，领料时重新校验。"""
from decimal import Decimal
from uuid import UUID, uuid5

from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialStockBalance, PublicStockBalance
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.inventory.stock_services import debit_material_stock
from apps.inventory.tube_outsourcing_reservations import reserved_quantity_for_balance, tube_material_reserved_quantities


def stock_rows(demand, *, lock=False):
    pipe = demand.get('category') == 'tube'
    public = pipe and public_flow_enabled()
    model = PublicStockBalance if public else MaterialStockBalance
    filters = {'stock_kind': 'RAW_PIPE'} if public else {'measurement_kind': 'PIPE' if pipe else 'OTHER'}
    rows = model.objects.filter(
        **filters, raw_material_id=demand.get('rawMaterialId'), quality='AVAILABLE', quantity__gt=0,
        raw_material__archived_at__isnull=True, raw_material__item_type='MATERIAL',
        unit__status='ACTIVE', unit__archived_at__isnull=True,
        zone__status='ACTIVE', zone__warehouse__status='ACTIVE', zone__warehouse__warehouse_type='MATERIAL',
    ).select_related('raw_material', 'unit', 'zone__warehouse').order_by('zone_id', 'id')
    if lock:
        rows = rows.select_for_update(of=('self',))
    _, reserved = tube_material_reserved_quantities(raw_material_ids=[demand.get('rawMaterialId')]) if not pipe else ({}, {})
    result = []
    for balance in rows:
        if balance.unit_id != balance.raw_material.unit_id:
            continue
        if not pipe and str(balance.unit_id) != demand.get('unitId'):
            continue
        if pipe and (not balance.raw_bar_length_m or balance.raw_bar_length_m <= 0
                     or balance.quantity != balance.quantity.to_integral_value()
                     or balance.meter_quantity != balance.quantity * balance.raw_bar_length_m):
            continue
        occupied = reserved_quantity_for_balance(balance) if public else reserved.get(
            (str(balance.raw_material_id), str(balance.unit_id), str(balance.zone_id)), Decimal('0'))
        available = max(balance.quantity - occupied, Decimal('0'))
        if available > 0:
            result.append((balance, available))
    return ('PUBLIC_V2' if public else 'LEGACY'), result


def candidate_payload(balance, available, stock_mode):
    return {
        'balanceId': str(balance.pk), 'stockMode': stock_mode,
        'materialNumber': balance.raw_material.material_number,
        'warehouseName': balance.zone.warehouse.warehouse_name, 'zoneName': balance.zone.zone_name,
        'unitLabel': balance.unit.unit_name, 'availableQuantity': str(available),
        'rawBarLengthM': str(balance.raw_bar_length_m) if balance.raw_bar_length_m else None,
        'meterQuantity': str(available * balance.raw_bar_length_m) if balance.raw_bar_length_m else None,
    }


def inventory_candidates(record):
    result = []
    for demand in record.draft.get('lines', []):
        mode, rows = stock_rows(demand)
        result.append({'lineKey': demand['key'], 'candidates': [candidate_payload(row, free, mode) for row, free in rows]})
    return {'lines': result}


def validate_allocations(demand, allocations, supply, *, planned=None, lock=False):
    """不能靠同名/同规格代替料号；整单重复使用同一库存也须累计校验。"""
    from .material_services import quantity_value
    mode, rows = stock_rows(demand, lock=lock)
    by_id = {str(row.pk): (row, free) for row, free in rows}
    used = planned if planned is not None else {}
    seen, normalized, total = set(), [], Decimal('0')
    for selected in allocations:
        key = str(selected['balanceId'])
        if key in seen:
            raise ValidationError('同一材料不能重复勾选同一库存。')
        seen.add(key)
        if selected['stockMode'] != mode or key not in by_id:
            raise Conflict(f"{demand['name']}：关联库存已失效或不属于此需求原材料，请重新查询。")
        balance, free = by_id[key]
        quantity = quantity_value(selected['quantity'], positive=True)
        if demand['category'] == 'tube' and quantity != quantity.to_integral_value():
            raise ValidationError('管材供料根数必须为正整数。')
        identity = (mode, key)
        if used.get(identity, Decimal('0')) + quantity > free:
            raise Conflict(f"{demand['name']}：{balance.zone.zone_name}的可用库存不足，请重新查询。")
        used[identity] = used.get(identity, Decimal('0')) + quantity
        amount = quantity * balance.raw_bar_length_m if demand['category'] == 'tube' else quantity
        total += amount
        normalized.append({**candidate_payload(balance, free, mode),
                           'quantity': str(int(quantity)) if demand['category'] == 'tube' else str(quantity)})
    if total != (supply or Decimal('0')):
        raise ValidationError('勾选库存的供料合计与本次可供数量不一致，请重新应用库存关联。')
    if demand['category'] == 'tube' and allocations and demand.get('unitLabel') != '米':
        raise ValidationError('旧支数口径需求不能直接关联根制库存，请先核对需求米数。')
    return normalized


def plan_other_issue(demand, selections, warehouse_quantity, arrived_quantity, *, planned, lock=False):
    mode, rows = stock_rows(demand, lock=lock)
    by_id = {str(row.pk): (row, free) for row, free in rows}
    selected = validate_allocations(demand, selections, warehouse_quantity, planned=planned, lock=lock)
    allocations = {entry['balanceId']: {'balance': by_id[entry['balanceId']][0], 'quantity': Decimal(entry['quantity'])} for entry in selected}
    remaining = arrived_quantity
    # 到货数量继续沿用原有库区顺序分配；已关联的仓库供料绝不另找库存替代。
    for balance, free in rows:
        key, identity = str(balance.pk), (mode, str(balance.pk))
        quantity = min(max(free - planned.get(identity, Decimal('0')), Decimal('0')), remaining)
        if quantity <= 0:
            continue
        entry = allocations.setdefault(key, {'balance': balance, 'quantity': Decimal('0')})
        entry['quantity'] += quantity
        planned[identity] = planned.get(identity, Decimal('0')) + quantity
        remaining -= quantity
    if remaining:
        raise Conflict(f"{demand['name']}：当前可用库存不足，本次未扣库存。")
    return {'kind': 'OTHER', 'allocations': list(allocations.values())}


def debit_other_plan(*, plan, source_id, source_line_id, actor_employee, snapshot):
    for entry in plan['allocations']:
        balance = entry['balance']
        debit_material_stock(
            raw_material=balance.raw_material, unit=balance.unit, quantity=entry['quantity'], zone=balance.zone,
            source_type='SAMPLE_MATERIAL_ISSUE', source_id=source_id,
            source_line_id=uuid5(UUID(str(source_line_id)), str(balance.pk)),
            actor_employee=actor_employee, production_task=None,
            snapshot={**snapshot, 'warehouse_linked_balance_id': str(balance.pk)},
        )
