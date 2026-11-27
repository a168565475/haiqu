"""跟单本人负责的任务中，包材办理和普通采购到货跟进。"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, OuterRef, Q, Subquery, Sum

from apps.access_control.module_policy import has_permission
from apps.audit.models import AuditLog
from .models import PurchaseOrderLine, PurchaseReturnLine, PurchaseReturnStatus, PurchaseScope
from .purchase_scope import PACKAGING_PERMISSION, packaging_order_filter
from .source_access import packaging_purchase_tasks
from .tracking_permissions import VIEW_PERMISSION, accessible_tracking_task_ids
from .tracking_rules import BEIJING
from .tracking_selectors import VALID_PURCHASE_STATUSES, arrival_rows, coverage_rows


_ARRIVAL = [('order', '采购单号'), ('supplier', '供应商'), ('material', '物料'), ('due', '预计交期'),
            ('ordered', '已采购'), ('received', '已到'), ('remaining', '未到'), ('unit', '单位')]
_SPEND = [('order', '包材采购单号'), ('supplier', '供应商'), ('material', '包材'), ('date', '确认日期'),
          ('quantity', '数量'), ('unit', '单位'), ('currency', '币种'), ('price', '单价'), ('amount', '金额')]
PURCHASE_COLUMNS = {
    'need': [('material', '包材'), ('required', '总需求'), ('ordered', '已订购'), ('remaining', '待订购'), ('unit', '单位')],
    'soon': _ARRIVAL, 'late': _ARRIVAL, 'ordinary': _ARRIVAL,
    'returns': [('order', '包材采购单号'), ('return_number', '退货单号'), ('supplier', '供应商'), ('material', '包材'),
                ('quantity', '退货数量'), ('unit', '单位'), ('reason', '质检备注'), ('status', '退货进度')],
    'period_purchases': _SPEND, 'supplier': _SPEND,
}
QUEUE_KEYS = ('need', 'soon', 'late', 'returns', 'ordinary')


def detail_row(task_id, task_number, **cells):
    return {'task_id': str(task_id), 'task_number': task_number,
            'cells': {key: str(value) if value is not None else '—' for key, value in cells.items()}}


def packaging_ids(request, own_tasks):
    return own_tasks.filter(pk__in=packaging_purchase_tasks(request).values('pk')).order_by().values('pk')


def shortages(task_ids, today):
    rows = coverage_rows(task_ids=task_ids, today=today, purchase_scope=PurchaseScope.PACKAGING)
    rows.sort(key=lambda r: (r['task_number'], r['material_name'], r['row_key']))
    return [detail_row(r['production_task_id'], r['task_number'], material=r['material_name'], unit=r['unit'],
                required=r['required_quantity'], ordered=r['purchased_quantity'], remaining=r['remaining_quantity'])
            for r in rows if r['group_status'] != '人工完成需求' and r['remaining_quantity'] is not None
            and Decimal(r['remaining_quantity']) > 0]


def pending_returns(task_ids):
    lines = PurchaseReturnLine.objects.filter(packaging_order_filter('return_order__purchase_order__'),
        return_order__purchase_order__production_task_id__in=task_ids, return_order__purchase_order__archived_at__isnull=True
        ).exclude(return_order__status=PurchaseReturnStatus.COMPLETED).select_related(
            'inbound_line', 'return_order__purchase_order__production_task').order_by('return_order__created_at', 'pk')
    rows = []
    for line in lines:
        record, source = line.return_order, line.inbound_line
        order = record.purchase_order
        rows.append(detail_row(order.production_task_id, order.production_task.task_number, order=order.order_number,
            return_number=record.return_number, supplier=record.supplier_name_snapshot,
            material=source.part_name_snapshot or source.material_snapshot, quantity=line.quantity,
            unit=source.source_unit_text_snapshot, reason=source.quality_remark, status=record.get_status_display()))
    return rows


def due_arrivals(task_ids, today, scope, queues):
    rows = arrival_rows(task_ids=task_ids, today=today, purchase_scope=scope)
    for row in sorted(rows, key=lambda r: (r['delivery_date'] or '', r['task_number'], r['row_key'])):
        risks = {item['code'] for item in row['risks']}
        if 'OVERDUE' in risks:
            key = 'late' if scope == PurchaseScope.PACKAGING else 'ordinary'
        elif scope == PurchaseScope.PACKAGING and risks & {'DUE_TODAY', 'NEAR_DUE'}:
            key = 'soon'
        else:
            continue
        if key in queues:
            queues[key].append(detail_row(row['production_task_id'], row['task_number'], order=row['purchase_order_no'],
                supplier=row['supplier_name'], material=row['material_name'], due=row['delivery_date'],
                ordered=row['ordered_quantity'], received=row['received_quantity'], remaining=row['unreceived_quantity'], unit=row['unit']))


def purchase_queues(request, own_tasks, today, categories=None):
    keys = set(QUEUE_KEYS) if categories is None else set(categories) & set(QUEUE_KEYS)
    queues = dict.fromkeys(keys)
    if keys - {'ordinary'} and has_permission(request, PACKAGING_PERMISSION):
        task_ids = packaging_ids(request, own_tasks)
        if 'need' in keys:
            queues['need'] = shortages(task_ids, today)
        if 'returns' in keys:
            queues['returns'] = pending_returns(task_ids)
        if keys & {'soon', 'late'}:
            arrivals = {key: [] for key in keys & {'soon', 'late'}}
            due_arrivals(task_ids, today, PurchaseScope.PACKAGING, arrivals)
            queues.update(arrivals)
    if 'ordinary' in keys and has_permission(request, VIEW_PERMISSION):
        queues['ordinary'] = []
        task_ids = own_tasks.filter(pk__in=accessible_tracking_task_ids(request)).order_by().values('pk')
        due_arrivals(task_ids, today, PurchaseScope.STANDARD, queues)
    return queues


def confirmed_lines(task_ids):
    confirmation = AuditLog.objects.filter(object_type='PURCHASE_ORDER', action='CONFIRMED',
        object_id=OuterRef('purchase_order_id')).order_by('occurred_at').values('occurred_at')[:1]
    return PurchaseOrderLine.objects.filter(packaging_order_filter('purchase_order__'),
        purchase_order__production_task_id__in=task_ids, purchase_order__source_type='PRODUCTION',
        purchase_order__archived_at__isnull=True, purchase_order__status__in=VALID_PURCHASE_STATUSES,
        actual_purchase_quantity__gt=0).annotate(confirmed_at=Subquery(confirmation))


def in_period(lines, start, today):
    return lines.filter(confirmed_at__gte=datetime.combine(start, time.min, tzinfo=BEIJING),
                        confirmed_at__lt=datetime.combine(today + timedelta(days=1), time.min, tzinfo=BEIJING))


def currency_amounts(totals):
    return [{'currency': code, 'amount': format(value, 'f')} for code, value in sorted(totals.items())]


def purchase_activity(request, own_tasks, start, today):
    result = {'purchase_order_count': None, 'supplier_count': None, 'amounts': [], 'suppliers': [],
              'unpriced_count': 0, 'undated_count': 0, 'unknown_supplier_count': 0}
    if not has_permission(request, PACKAGING_PERMISSION):
        return result
    lines = confirmed_lines(packaging_ids(request, own_tasks))
    result['undated_count'] = lines.filter(confirmed_at__isnull=True).count()
    groups = in_period(lines, start, today).values('purchase_order_id', 'supplier_id', 'supplier_name_snapshot',
        'purchase_order__currency_code_snapshot').annotate(amount_total=Sum('amount'),
        unpriced=Count('id', filter=Q(amount__isnull=True)), line_count=Count('id')).order_by('supplier_name_snapshot', 'purchase_order_id')
    orders, totals, suppliers = set(), defaultdict(Decimal), {}
    for group in groups:
        pk, supplier_id = group['purchase_order_id'], group['supplier_id']
        orders.add(pk)
        code, amount = group['purchase_order__currency_code_snapshot'], group['amount_total']
        result['unpriced_count'] += group['unpriced']
        if amount is not None:
            totals[code] += amount
        if supplier_id is None:
            result['unknown_supplier_count'] += group['line_count']
            continue
        supplier = suppliers.setdefault(supplier_id, {'id': str(supplier_id), 'name': group['supplier_name_snapshot'],
                                            'orders': set(), 'totals': defaultdict(Decimal), 'unpriced_count': 0})
        supplier['orders'].add(pk)
        supplier['unpriced_count'] += group['unpriced']
        if amount is not None:
            supplier['totals'][code] += amount
    ranked = [{'id': s['id'], 'name': s['name'], 'order_count': len(s['orders']),
               'amounts': currency_amounts(s['totals']), 'unpriced_count': s['unpriced_count']} for s in suppliers.values()]
    return {**result, 'purchase_order_count': len(orders), 'supplier_count': len(ranked),
            'amounts': currency_amounts(totals), 'suppliers': ranked}


def purchase_activity_rows(request, own_tasks, start, today, supplier_id=None):
    if not has_permission(request, PACKAGING_PERMISSION):
        return None
    lines = in_period(confirmed_lines(packaging_ids(request, own_tasks)), start, today)
    if supplier_id is not None:
        lines = lines.filter(supplier_id=supplier_id)
    rows = []
    for line in lines.select_related('purchase_order__production_task').order_by('-confirmed_at', 'purchase_order__order_number', 'pk'):
        order = line.purchase_order
        rows.append(detail_row(order.production_task_id, order.production_task.task_number, order=order.order_number,
            supplier=line.supplier_name_snapshot, material=line.part_name_snapshot or line.material_snapshot,
            date=line.confirmed_at.astimezone(BEIJING).date(), quantity=line.actual_purchase_quantity, unit=line.source_unit_text,
            currency=order.currency_code_snapshot, price=line.unit_price, amount=line.amount))
    return rows
