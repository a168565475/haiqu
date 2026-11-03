"""样品消费保存材料身份；原管按实际批次根数扣账、逐批折米。"""
from decimal import Decimal
from uuid import UUID, uuid5

from apps.core.api.exceptions import Conflict
from apps.inventory.models import PublicStockMovement
from apps.inventory.public_stock_services import debit_public_stock

from .models import SampleMaterialArrival
from .warehouse_stock import stock_rows, validate_allocations


def plan_catalog_issue(record, row, selections, warehouse_quantity, arrived_quantity, *, planned, lock=False):
    pipe = row.get('category') == 'tube'
    _, rows = stock_rows(row, lock=lock)
    by_id = {str(balance.pk): (balance, free) for balance, free in rows}
    selected = validate_allocations(row, selections or [], warehouse_quantity, planned=planned, lock=lock)
    allocations = {entry['balanceId']: {'balance': by_id[entry['balanceId']][0], 'quantity': Decimal(entry['quantity'])} for entry in selected}
    arrivals = list(SampleMaterialArrival.objects.filter(
        procurement_request__material_request=record, line_key=row['key'], inbound_line__inbound__status='CONFIRMED',
    ).select_related('inbound_line').order_by('inbound_line_id'))
    if sum((arrival.accepted_quantity for arrival in arrivals), Decimal('0')) != arrived_quantity:
        raise Conflict('样品到货数量已变化，请重新核对。')
    for arrival in arrivals:
        movements = list(PublicStockMovement.objects.filter(source_type='MATERIAL_INBOUND',
            source_line_id=arrival.inbound_line_id, direction='IN').order_by('id'))
        if pipe:
            line = arrival.inbound_line
            if (line.measurement_kind != 'PIPE' or not line.raw_bar_length_m
                    or line.material_catalog_id != UUID(str(row['material_catalog_id']))
                    or line.material_selection_snapshot != row['material_selection_snapshot']
                    or line.accepted_bar_count is None
                    or line.accepted_quantity != line.accepted_bar_count * line.raw_bar_length_m
                    or arrival.accepted_quantity != line.accepted_quantity
                    or sum((movement.quantity for movement in movements), Decimal('0')) != line.accepted_bar_count
                    or any(movement.meter_quantity != movement.quantity * line.raw_bar_length_m for movement in movements)):
                raise Conflict('本次样品管材到货的实际根米与入账流水不一致。')
        if sum(((movement.meter_quantity if pipe else movement.quantity) for movement in movements), Decimal('0')) != arrival.accepted_quantity:
            raise Conflict('本次样品到货缺少一致的库存入账流水，不能改领其他库存。')
        for movement in movements:
            key = str(movement.balance_id)
            if key not in by_id:
                raise Conflict('本次样品到货所在库区无相同材料可用库存。')
            balance, free = by_id[key]
            if pipe and balance.raw_bar_length_m != arrival.inbound_line.raw_bar_length_m:
                raise Conflict('本次样品到货的实际单根长度与库存批次不一致。')
            identity = ('PUBLIC_V2', key)
            total = planned.get(identity, Decimal('0')) + movement.quantity
            if total > free:
                raise Conflict('本次安排的材料库存不足，不能挪扣其他库区。')
            planned[identity] = total
            entry = allocations.setdefault(key, {'balance': balance, 'quantity': Decimal('0')})
            entry['quantity'] += movement.quantity
    entries = list(allocations.values())
    if pipe:
        for entry in entries:
            entry['bars'] = entry['quantity']
        if sum((entry['bars'] * entry['balance'].raw_bar_length_m for entry in entries), Decimal('0')) != warehouse_quantity + arrived_quantity:
            raise Conflict('样品已安排和实际到货的根米合计不一致。')
    return {'kind': 'CATALOG', 'allocations': entries}


def debit_catalog_plan(plan, *, issue, line, actor_employee):
    for entry in plan['allocations']:
        balance = entry['balance']
        debit_public_stock(balance_id=balance.pk, quantity=entry['quantity'],
            source_type='SAMPLE_MATERIAL_ISSUE', source_id=issue.pk,
            source_line_id=uuid5(UUID(str(line.pk)), str(balance.pk)), actor_employee=actor_employee,
            snapshot={'sample_issue_id': str(issue.pk), 'sample_issue_line_id': str(line.pk),
                'material_catalog_id': str(line.material_catalog_id),
                'raw_bar_length_m': str(balance.raw_bar_length_m) if balance.raw_bar_length_m else None,
                'material_selection_snapshot': line.material_selection_snapshot})
