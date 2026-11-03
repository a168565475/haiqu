"""总单更正的冻结凭证和差额记账；不读取当前 BOM 构造库存身份。"""
import hashlib
from collections import defaultdict
from decimal import Decimal
from uuid import uuid5

from django.db import connection
from django.db.models import Q

from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_identity import validate_public_identity
from apps.inventory.public_stock_services import _lock_source, credit_public_stock, debit_public_stock, lock_public_stock_locations
from apps.inventory.stock_services import credit_material_stock
from apps.material_issues.models import MaterialIssue, MaterialIssueLine
from apps.material_issues.public_issue_services import public_issue_quantity_context
from apps.products.models import RawMaterialInformation

from .tube_services import _json


DISPATCH_SOURCE = 'TUBE_PLAN_DISPATCH_CORRECTION'
RECEIPT_SOURCE = 'TUBE_PLAN_RECEIPT_CORRECTION'
MATERIAL_SOURCE = 'TUBE_PLAN_MATERIAL_CORRECTION'
CORRECTION_SOURCES = (DISPATCH_SOURCE, RECEIPT_SOURCE, MATERIAL_SOURCE)


def frozen_identity(movement):
    identity = validate_public_identity(movement.snapshot.get('public_identity'))
    balance = movement.balance
    if (identity['stock_kind'] != balance.stock_kind or identity['identity_key'] != balance.identity_key
            or str(identity['unit_id']) != str(balance.unit_id) or balance.quality != 'AVAILABLE'):
        raise Conflict('原库存流水与冻结实物身份不一致，不能自动更正。')
    return identity


def effective_stock_quantity(original, corrections, *, line_id, source_type):
    """原事件加已确认差额必须与当前凭证一致，防止凭据缺损时再次退库。"""
    total = original.quantity
    model = type(original)
    expected_ids = set()
    for correction in corrections:
        for saved in correction.stock_movements:
            if saved.get('original_line_id') != str(line_id) or saved.get('source_type') != source_type:
                continue
            movement = model.objects.filter(pk=saved.get('id'), source_id=correction.pk,
                source_type=source_type, balance_id=original.balance_id).first()
            if (movement is None or movement.quantity != Decimal(saved.get('quantity', 'NaN'))
                    or movement.direction != saved.get('direction')
                    or movement.snapshot.get('original_movement_id') != str(original.pk)):
                raise Conflict('历史更正流水与操作回执不一致，请先核对。')
            expected_ids.add(movement.pk)
            total += movement.quantity if movement.direction == original.direction else -movement.quantity
    actual_ids = set(model.objects.filter(source_type=source_type,
        snapshot__original_movement_id=str(original.pk)).values_list('pk', flat=True))
    if actual_ids != expected_ids:
        raise Conflict('历史更正流水缺少对应回执，请先核对。')
    return total


def stock_event(correction, original, delta, *, line_id, source_type):
    return {'original': original, 'delta': Decimal(delta), 'line_id': line_id, 'source_type': source_type,
        'event_id': uuid5(correction.pk, f'{source_type}:{line_id}'),
        'identity': frozen_identity(original) if isinstance(original, PublicStockMovement) else None}


def apply_stock_events(order, correction, events, request):
    events = [event for event in events if event['delta']]
    if not events:
        return []
    public = [event for event in events if event['identity'] is not None]
    ordinary = [event for event in events if event['identity'] is None]
    pools = {}
    for event in public:
        identity = event['identity']
        pool = (identity['stock_kind'], identity['identity_key'], str(identity['unit_id']))
        event['pool'] = pool
        pools[pool] = identity
    ordinary_pools = {('OTHER', str(event['original'].balance.raw_material_id),
                       str(event['original'].balance.unit_id)) for event in ordinary}
    for pool in sorted(set(pools) | ordinary_pools):
        key = int.from_bytes(hashlib.sha256(('public-issue-pool:' + ':'.join(pool)).encode()).digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [key])
    for event in sorted(public, key=lambda value: str(value['event_id'])):
        _lock_source({'source_type': event['source_type'], 'source_line_id': event['event_id']},
                     'IN' if event['delta'] > 0 else 'OUT')
    # 旧辅料入账会锁原料父对象，先于库区/余额统一取齐，不能在逐行记账时倒序锁。
    list(RawMaterialInformation.objects.filter(pk__in={event['original'].balance.raw_material_id
        for event in ordinary}).order_by('pk').select_for_update())
    predicate = Q(pk__in=[])
    for kind, key, unit in pools:
        predicate |= Q(stock_kind=kind, identity_key=key, unit_id=unit, quality='AVAILABLE')
    balances = PublicStockBalance.objects.filter(predicate)
    ordinary_balances = MaterialStockBalance.objects.filter(pk__in=[event['original'].balance_id for event in ordinary])
    zones = lock_public_stock_locations(set(balances.values_list('zone_id', flat=True))
        | {event['original'].balance.zone_id for event in events})
    list(ordinary_balances.order_by('raw_material_id', 'unit_id', 'zone_id', 'pk').select_for_update())
    list(balances.order_by('pk').select_for_update(of=('self',)))
    for event in events:
        zone = zones[event['original'].balance.zone_id]
        if zone.status != 'ACTIVE' or zone.warehouse.status != 'ACTIVE':
            raise Conflict('原库存库区或仓库已停用，不能自动更正。')
    if public:
        issue = MaterialIssue(production_task_id=order.product_line.production_task_id,
                              product_line_id=order.product_line_id, stock_mode='PUBLIC_V2')
        lines = [MaterialIssueLine(issue=issue, unit_id=identity['unit_id'], line_type='SEMI',
            requested_quantity=1, conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': _json(identity)})
            for identity in pools.values()]
        context = public_issue_quantity_context(issue, lines=lines)
        by_zone, by_pool = defaultdict(Decimal), defaultdict(Decimal)
        for event in public:
            by_zone[(event['pool'], event['original'].balance.zone_id)] += event['delta']
            by_pool[event['pool']] += event['delta']
        # 多部件可以共用同一实物池：一次校验本操作合计，兼顾同区及跨区普通领料预占。
        for (pool, zone_id), delta in by_zone.items():
            available = sum((balance.quantity for balance in context['balances'][pool]
                             if balance.zone_id == zone_id), Decimal(0))
            reserved = context['tube_reserved_by_zone'].get((pool, str(zone_id)), Decimal(0))
            if delta < 0 and -delta > max(available - reserved, Decimal(0)):
                raise Conflict('原库区同种材料未占用库存不足，不能更正或删除该记录。')
        for pool, delta in by_pool.items():
            if delta < 0 and -delta > max(context['stock'][pool] - context['pending_stock'][pool], Decimal(0)):
                raise Conflict('同种材料库存已被待审领料或待发委外占用，不能更正或删除该记录。')
    result = []
    # 先增加后扣减，避免同池本次净变化合法却被中间余额误阻断；全程持有池锁。
    for event in sorted(events, key=lambda value: (value['delta'] < 0, str(value['event_id']))):
        original, delta = event['original'], event['delta']
        zone = zones[original.balance.zone_id]
        snapshot = _json({'order_id': order.pk, 'order_number': order.order_number,
            'record_id': correction.record_id, 'record_kind': correction.record_kind,
            'operation': correction.operation, 'correction_id': correction.pk,
            'original_movement_id': original.pk, 'original_line_id': event['line_id'],
            'business_number': correction.before_data['number'],
            'business_date': correction.after_data.get('business_date', correction.before_data['business_date']),
            'quantity': abs(delta), 'public_identity': event['identity']})
        kwargs = dict(quantity=abs(delta), source_type=event['source_type'], source_id=correction.pk,
            source_line_id=event['event_id'], actor_employee=request.employee,
            production_task=original.production_task_id, snapshot=snapshot)
        if event['identity'] is not None:
            kwargs.update(product_line=original.product_line_id, bom_line=original.bom_line_id)
            movement = (credit_public_stock(identity=event['identity'], zone=zone, **kwargs) if delta > 0
                        else debit_public_stock(balance_id=original.balance_id, **kwargs))
        else:
            if delta <= 0 or zone.warehouse.warehouse_type != 'MATERIAL':
                raise Conflict('附带材料只支持按原库区退回，不能修改辅料数量。')
            kwargs['production_task'] = order.product_line.production_task
            movement = credit_material_stock(raw_material=original.balance.raw_material,
                unit=original.balance.unit, zone=zone, **kwargs)
        result.append({'id': str(movement.pk), 'source_type': event['source_type'],
            'original_line_id': str(event['line_id']), 'quantity': str(movement.quantity), 'direction': movement.direction})
    return result
