from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncMonth

from apps.audit.models import AuditLog
from apps.production_scheduling.models import ProductionScheduleProduct
from .models import PurchaseOrderLine, SupplierCategory
from .purchase_scope import standard_order_lines
from .tracking_rules import BEIJING
from .tracking_selectors import VALID_PURCHASE_STATUSES, arrival_rows, coverage_rows


COVERAGE_CATEGORIES = ('unstarted', 'shortage', 'bom_changed')
ARRIVAL_CATEGORIES = ('near_due', 'due_today', 'overdue', 'late_for_use', 'missing_due')


def coverage_queues(task_ids):
    queues = {key: [] for key in COVERAGE_CATEGORIES}
    by_task = defaultdict(list)
    unknown_requirements = 0
    for row in coverage_rows(task_ids=task_ids):
        by_task[row['production_task_id']].append(row)
        if row['group_status'] == '人工完成需求':
            continue
        if row['required_quantity'] is None:
            unknown_requirements += 1
        if row['source_reliable'] and row['remaining_quantity'] and Decimal(row['remaining_quantity']) > 0:
            queues['shortage'].append(row)
        if any(risk['code'] == 'DEMAND_CHANGED' for risk in row['risks']):
            queues['bom_changed'].append(row)
    for task_rows in by_task.values():
        if all(row['group_status'] != '人工完成需求' and row['source_reliable']
               and row['required_quantity'] and Decimal(row['required_quantity']) > 0
               and Decimal(row['purchased_quantity']) == 0 for row in task_rows):
            queues['unstarted'].append({**task_rows[0], 'material_count': len(task_rows)})
    return queues, unknown_requirements


def arrival_queues(task_ids, today):
    queues = {key: [] for key in ARRIVAL_CATEGORIES}
    rows = [row for row in arrival_rows(task_ids=task_ids, today=today)
            if not row['is_history'] and row['unreceived_quantity'] and Decimal(row['unreceived_quantity']) > 0]
    product_ids = {pk for row in rows for pk in row['source_product_ids']}
    schedules = {str(pk): value for pk, value in ProductionScheduleProduct.objects.filter(
        product_line_id__in=product_ids, schedule__production_task_id__in=task_ids,
        schedule__record_status='ACTIVE', removed_at__isnull=True).values_list('product_line_id', 'material_inbound_date')}
    missing_use_dates = 0
    comparable = 0
    risk_keys = {'NEAR_DUE': 'near_due', 'DUE_TODAY': 'due_today', 'OVERDUE': 'overdue',
                 'DELIVERY_UNKNOWN': 'missing_due'}
    for row in rows:
        for risk in row['risks']:
            if key := risk_keys.get(risk['code']):
                queues[key].append(row)
        dates = [schedules.get(pk) for pk in row['source_product_ids']]
        known_dates = [value for value in dates if value]
        first_use = min(known_dates).isoformat() if known_dates else None
        row['material_inbound_date'] = first_use
        if row['delivery_date']:
            # 任一关联产品已知赶不上，就能确定这批料有风险。
            if first_use and row['delivery_date'] > first_use:
                queues['late_for_use'].append(row)
                comparable += 1
            elif not dates or None in dates:
                missing_use_dates += 1
            else:
                comparable += 1
    return queues, missing_use_dates, comparable


def period_start(period, anchor):
    if period == 'year':
        return date(anchor.year, 1, 1)
    first_month = anchor.month if period == 'month' else 1 + 3 * ((anchor.month - 1) // 3)
    return date(anchor.year, first_month, 1)


def purchase_spend(task_ids, period, anchor):
    start = period_start(period, anchor)
    first_confirmation = AuditLog.objects.filter(object_type='PURCHASE_ORDER', action='CONFIRMED',
        object_id=OuterRef('purchase_order_id')).order_by('occurred_at').values('occurred_at')[:1]
    lines = standard_order_lines(PurchaseOrderLine.objects.filter(purchase_order__production_task_id__in=task_ids,
        purchase_order__source_type='PRODUCTION', purchase_order__archived_at__isnull=True,
        purchase_order__status__in=VALID_PURCHASE_STATUSES, actual_purchase_quantity__gt=0)
        ).annotate(confirmed_at=Subquery(first_confirmation))
    unknown_dates = lines.filter(confirmed_at__isnull=True).count()
    # 先按批次和供应商聚合，避免将整批金额重复计入多个供应商。
    next_day = datetime.combine(anchor + timedelta(days=1), time.min, tzinfo=BEIJING)
    yearly = lines.filter(confirmed_at__gte=datetime(anchor.year, 1, 1, tzinfo=BEIJING),
        confirmed_at__lt=next_day).annotate(month=TruncMonth('confirmed_at', tzinfo=BEIJING)
        ).values('month', 'purchase_order__currency_code_snapshot', 'purchase_order_id', 'purchase_order__purchase_group_id',
                 'purchase_order__batch_number', 'supplier_id',
                 'supplier_name_snapshot', 'supplier_categories_snapshot').annotate(
            amount_total=Sum('amount'), line_count=Count('id'), unpriced_count=Count('id', filter=Q(amount__isnull=True))
        ).order_by('month', 'purchase_order_id', 'supplier_id')
    currencies = {}
    for row in yearly.iterator():
        code = row['purchase_order__currency_code_snapshot']
        if code not in currencies:
            currencies[code] = {'currency': code, 'amount': Decimal(0), 'unpriced_count': 0, 'line_count': 0,
                'orders': set(), 'suppliers': {}, 'trend': [{'month': i, 'amount': Decimal(0), 'line_count': 0, 'unpriced_count': 0}
                                                          for i in range(1, 13)]}
        bucket = currencies[code]
        month = row['month'].month
        amount = row['amount_total'] or Decimal(0)
        trend = bucket['trend'][month - 1]
        trend['amount'] += amount
        trend['line_count'] += row['line_count']
        trend['unpriced_count'] += row['unpriced_count']
        if month < start.month:
            continue
        supplier = bucket['suppliers'].setdefault(row['supplier_id'], {
            'supplier_id': row['supplier_id'], 'supplier_name': row['supplier_name_snapshot'],
            'supplier_category': '', 'amount': Decimal(0), 'unpriced_count': 0, 'line_count': 0, 'orders': set()})
        supplier['supplier_category'] = '、'.join(str(SupplierCategory(key).label) for key in row['supplier_categories_snapshot']
                                                if key in SupplierCategory.values)
        # 同一需求的同一批可按供应商拆成多张采购单。
        batch_key = ((row['purchase_order__purchase_group_id'], row['purchase_order__batch_number'])
                     if row['purchase_order__purchase_group_id'] and row['purchase_order__batch_number'] is not None
                     else row['purchase_order_id'])
        for group in (bucket, supplier):
            group['orders'].add(batch_key)
            group['line_count'] += row['line_count']
            group['unpriced_count'] += row['unpriced_count']
            group['amount'] += amount
    for bucket in currencies.values():
        suppliers = bucket['suppliers'].values()
        bucket['supplier_count'] = sum(row['supplier_id'] is not None for row in suppliers)
        bucket['suppliers'] = sorted(suppliers, key=lambda row: (-row['amount'], row['supplier_name'], str(row['supplier_id'])))
        for row in (bucket, *bucket['suppliers']):
            row['order_count'] = len(row.pop('orders'))
            row['amount'] = format(row['amount'], 'f')
        for row in bucket['trend']:
            row['amount'] = format(row['amount'], 'f')
    return {'period': period, 'start_date': start.isoformat(), 'end_date': anchor.isoformat(), 'year': anchor.year,
            'currencies': [currencies[key] for key in sorted(currencies)], 'unknown_date_count': unknown_dates}
