"""只在本人当前跟单任务内查询，兼任其他岗位也使用同一任务集合。"""
from calendar import monthrange
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, OuterRef, Subquery
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.access_control.module_policy import has_permission
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.outsourcing.plan_selectors import plan_quantities
from apps.outsourcing.tube_selectors import saved_orders_for_permission
from apps.procurement import merchandiser_workbench as purchases
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.workshop_reporting.selectors import accessible_work_reports

from .dashboard import TASK_STATUSES
from .selectors import accessible_production_tasks


TASK_PERMISSION = 'production_tasks.view_productiontask'
PRINT_CATEGORIES = ('owing', 'unsent')
TASK_CATEGORIES = ('past', 'day', 'period_tasks')
REPORT_PERMISSION = 'workshop_reporting.view_workreport'


def followed_tasks(request):
    return accessible_production_tasks(request, TASK_PERMISSION).filter(
        followers=request.employee, archived_at__isnull=True, status__in=TASK_STATUSES).order_by().distinct()


def period_bounds(today, period):
    month = {'month': today.month, 'quarter': 1 + 3 * ((today.month - 1) // 3), 'year': 1}[period]
    last = month + {'month': 0, 'quarter': 2, 'year': 11}[period]
    return today.replace(month=month, day=1), today.replace(month=last, day=monthrange(today.year, last)[1])


def print_groups(request, tasks):
    if not (has_permission(request, CUT_PIECE_PRINTING) and settings.TUBE_OUTSOURCING_ENABLED and public_flow_enabled()):
        return None
    plans = list(saved_orders_for_permission(request, CUT_PIECE_PRINTING).filter(
        is_plan=True, product_line__production_task__in=tasks,
    ).exclude(status__in=['CANCELLED', 'COMPLETED']).select_related(
        'product_line__production_task').prefetch_related('lines__factory')
        .order_by('expected_return_date', 'order_number', 'pk'))
    quantities = plan_quantities(plans)
    groups = {key: [] for key in PRINT_CATEGORIES}
    for plan in plans:
        task = plan.product_line.production_task
        lines = {key: [] for key in PRINT_CATEGORIES}
        for line in plan.lines.all():
            amounts = quantities[str(plan.pk)]['lines'][str(line.pk)]
            sent = int(amounts['dispatched_quantity'])
            unit = line.snapshot.get('unit') or '片'
            pending = {'owing': int(amounts['receivable_quantity']), 'unsent': max(line.quantity - sent, 0)}
            for key, remaining in pending.items():
                if remaining == 0:
                    continue
                cells = {
                    'order': plan.order_number, 'factory': line.factory.name,
                    'piece': line.snapshot.get('part_name') or '—',
                    'date': str(plan.expected_return_date if key == 'owing' else plan.planned_dispatch_date),
                    'planned': f'{line.quantity} {unit}', 'sent': f'{sent} {unit}',
                    'returned': f"{amounts['received_quantity']} {unit}",
                    'direct': f"{amounts['transferred_quantity']} {unit}", 'remaining': f'{remaining} {unit}',
                }
                lines[key].append({'task_id': str(task.pk), 'task_number': task.task_number, 'cells': cells})
        for key in PRINT_CATEGORIES:
            if lines[key]:
                groups[key].append(lines[key])
    return groups


def task_rows(request, queryset, window):
    columns = [('products', '产品'), ('delivery_date', '任务交期'), ('status', '任务状态')]
    if has_permission(request, 'production_scheduling.view_productionschedule'):
        schedules = accessible_production_schedules(request).filter(production_task_id=OuterRef('pk'), record_status='ACTIVE')
        queryset = queryset.annotate(schedule_number=Subquery(schedules.values('schedule_number')[:1]))
        columns.append(('schedule', '有效排产单'))
    if has_permission(request, REPORT_PERMISSION):
        reports = accessible_work_reports(request, REPORT_PERMISSION).filter(
            product_line__production_task_id=OuterRef('pk')).order_by('-production_date', '-created_at', '-pk')
        queryset = queryset.annotate(report_date=Subquery(reports.values('production_date')[:1]),
                                     report_workshop=Subquery(reports.values('workshop__name')[:1]))
        columns.append(('report', '最近车间报工'))
    rows = []
    for task in queryset.order_by('delivery_date', 'task_number', 'pk').prefetch_related('products')[window]:
        cells = {'products': '、'.join(p.product_name_snapshot for p in task.products.all()),
                 'delivery_date': task.delivery_date.isoformat(), 'status': task.get_status_display()}
        if hasattr(task, 'schedule_number'):
            cells['schedule'] = task.schedule_number or '暂无记录'
        if hasattr(task, 'report_date'):
            cells['report'] = f'{task.report_date} {task.report_workshop}' if task.report_date else '暂无记录'
        rows.append({'task_id': str(task.pk), 'task_number': task.task_number, 'cells': cells})
    return columns, rows


def overview(request, today):
    tasks = followed_tasks(request)
    open_tasks = tasks.exclude(status='COMPLETED')
    week = [today + timedelta(days=i) for i in range(7)]
    calendar = dict(open_tasks.filter(delivery_date__range=(today, week[-1])).order_by()
                    .values_list('delivery_date').annotate(n=Count('pk', distinct=True)))
    queues = purchases.purchase_queues(request, tasks, today)
    counts = {key: len(rows) if rows is not None else None for key, rows in queues.items()}
    groups = print_groups(request, tasks)
    counts.update({key: len(groups[key]) if groups is not None else None for key in PRINT_CATEGORIES})
    counts['past'] = open_tasks.filter(delivery_date__lt=today).count()
    return {'as_of': today, 'counts': counts, 'upcoming': [{'date': d, 'count': calendar.get(d, 0)} for d in week]}


def activity(request, today, period):
    tasks = followed_tasks(request)
    start, end = period_bounds(today, period)
    return {'as_of': today, 'start_date': start, 'end_date': end,
            'task_count': tasks.filter(delivery_date__range=(start, end)).count(),
            **purchases.purchase_activity(request, tasks, start, today)}


def items(request, today, filters):
    tasks = followed_tasks(request)
    key = filters['category']
    page, size = filters['page'], filters['page_size']
    window = slice((page - 1) * size, page * size)
    start, end = period_bounds(today, filters.get('period', 'month'))
    if key in TASK_CATEGORIES:
        if key == 'period_tasks':
            selected = tasks.filter(delivery_date__range=(start, end))
        elif key == 'past':
            selected = tasks.exclude(status='COMPLETED').filter(delivery_date__lt=today)
        else:
            selected = tasks.exclude(status='COMPLETED').filter(delivery_date=filters['date'])
        total = selected.count()
        columns, page_rows = task_rows(request, selected, window)
    elif key in PRINT_CATEGORIES:
        groups = print_groups(request, tasks)
        if groups is None:
            raise PermissionDenied('当前账号未开放裁片丝印外发。')
        total = len(groups[key])
        page_rows = [row for group in groups[key][window] for row in group]
        columns = [('order', '丝印外发单号'), ('factory', '丝印厂'), ('piece', '裁片'),
                   ('date', '预计回货日' if key == 'owing' else '计划发料日'),
                   ('planned', '计划外发'), ('sent', '实际已发')]
        if key == 'owing':
            columns += [('returned', '回仓'), ('direct', '直送车缝厂')]
        columns.append(('remaining', '丝印厂待交' if key == 'owing' else '待发数量'))
    else:
        if key in ('supplier', 'period_purchases'):
            rows = purchases.purchase_activity_rows(request, tasks, start, today, filters.get('supplier_id'))
        else:
            rows = purchases.purchase_queues(request, tasks, today, categories=[key])[key]
        if rows is None:
            raise PermissionDenied('当前岗位没有查看这类采购明细的权限。')
        total, page_rows = len(rows), rows[window]
        columns = purchases.PURCHASE_COLUMNS[key]
    return {'data': {'columns': [{'key': k, 'label': name} for k, name in columns], 'rows': page_rows},
            'meta': {'page': page, 'page_size': size, 'total': total, 'total_pages': (total + size - 1) // size}}
