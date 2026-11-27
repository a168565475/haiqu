"""仓库工作台：交仓入库、采购收货、生产发料。只读取业务原单。"""
from django.contrib.postgres.aggregates import StringAgg
from django.db.models import Count, Min, Prefetch
from django.db.models.functions import Coalesce, TruncDate
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.access_control.module_policy import has_permission
from apps.material_issues.selectors import accessible_material_issues

from .hardware_receipts import is_hardware_weight
from .internal_receipt_models import InternalSemiFinishedReceipt
from .models import FinishedGoodsReceipt
from .pipe_receipt_basis import is_root_receipt
from .purchase_receipt_records import purchase_receipt_scope
from .selectors import can_read_inventory_overview, scoped_inventory_records, scoped_finished_receipts
from .warehouse_workbench_internal_purchase import RECEIVE, names, purchase_source, quantities, waiting_purchases


SEMI = 'inventory.view_internalsemifinishedreceipt'
FINISHED = 'inventory.view_finishedgoodsreceipt'
ISSUE = 'material_issues.view_materialissue'
REVIEW = 'material_issues.review_materialissue'
CONFIRM = {'semi': 'inventory.confirm_internalsemifinishedreceipt', 'finished': 'inventory.confirm_finishedgoodsreceipt'}


def _receipt_kinds(request):
    return [kind for kind, read in [('semi', SEMI), ('finished', FINISHED)]
            if has_permission(request, read) and has_permission(request, CONFIRM[kind])]


def available(request, key):
    if key == 'inbound':
        return bool(_receipt_kinds(request))
    if key == 'issue':
        return has_permission(request, ISSUE) and has_permission(request, REVIEW)
    return has_permission(request, RECEIVE)


def receipt_queryset(request, kind, status):
    if kind == 'semi':
        scope = dict(task_lookup='schedule_product__schedule__production_task', workshop_lookup='completed_craft__workshop_id')
        qs = scoped_inventory_records(InternalSemiFinishedReceipt.objects.all(), request, SEMI, **scope)
        qs = scoped_inventory_records(qs, request, CONFIRM[kind], **scope).select_related(
            'completed_craft__workshop', 'schedule_product__schedule__production_task', 'schedule_product__product_line')
        business_date = 'receipt_date'
    else:
        qs = scoped_finished_receipts(FinishedGoodsReceipt.objects.filter(assembly_source__isnull=False), request)
        qs = scoped_finished_receipts(qs, request, CONFIRM[kind]).select_related('unit', 'assembly_source')
        business_date = 'assembly_source__receipt_date'
    qs = qs.filter(status=status)
    if status == 'PENDING':
        return qs.annotate(board_date=TruncDate('submitted_at'))
    return qs.annotate(board_date=Coalesce(TruncDate('confirmed_at'), business_date))


def receipt_row(r, kind):
    if kind == 'semi':
        plan = r.schedule_product
        task = r.source_snapshot.get('production_order') or plan.schedule.production_task.task_number
        product = r.source_snapshot.get('product') or plan.product_line.product_name_snapshot
        party = r.completed_craft.workshop.name if r.completed_craft.workshop_id else r.get_plan_category_display()
    else:
        task, product, party = r.task_number_snapshot, r.product_name_snapshot, '装配车间'
    return dict(id=str(r.pk), kind=kind, task_number=task, product=product, number=r.receipt_number, party=party,
                date=r.board_date.isoformat() if r.board_date else None, status='待仓库确认' if r.status == 'PENDING' else '已入库')


def receipt_page(request, status, offset, limit, period=None):
    counts, rows = {}, []
    for kind in _receipt_kinds(request):
        qs = receipt_queryset(request, kind, status)
        if period:
            qs = qs.filter(board_date__range=period)
        counts[kind] = qs.count()
        if limit:
            order = ('-board_date', '-id') if period else ('board_date', 'id')
            rows.extend(receipt_row(r, kind) for r in qs.order_by(*order)[:offset + limit])
    rows.sort(key=lambda row: (row['date'] or '9999', row['id'], row['kind']), reverse=bool(period))
    return counts, rows[offset:offset + limit]


def issue_queryset(request, status):
    qs = accessible_material_issues(request, ISSUE).filter(
        pk__in=accessible_material_issues(request, REVIEW).order_by().values('pk'), status=status)
    if status == 'PENDING_REVIEW':
        return qs.filter(production_task_id__isnull=False).annotate(board_date=TruncDate('submitted_at'))
    return qs.annotate(board_date=TruncDate(Coalesce('issued_at', 'issue_at')))


def issue_group_page(qs, offset, limit):
    groups = qs.order_by().values('production_task_id', 'production_task__task_number').annotate(
        document_count=Count('id', distinct=True), first_date=Min('board_date'),
        products=StringAgg('product_line__product_name_snapshot', delimiter='、', distinct=True,
                           order_by='product_line__product_name_snapshot'),
        shops=StringAgg('workshop__name', delimiter='、', distinct=True, order_by='workshop__name'),
    ).order_by('first_date', 'production_task__task_number', 'production_task_id')
    return groups.count(), [dict(id=str(task['production_task_id']), kind='task',
        task_number=task['production_task__task_number'], product=task['products'] or '', number='', party=task['shops'] or '',
        date=task['first_date'].isoformat() if task['first_date'] else None, status='待仓库审核',
        document_count=task['document_count']) for task in groups[offset:offset + limit]]


def issue_row(issue):
    return dict(id=str(issue.pk), kind='issue',
                task_number=issue.production_task.task_number if issue.production_task_id else '',
                product=issue.product_line.product_name_snapshot if issue.product_line_id else '',
                number=issue.issue_number, party=issue.workshop.name if issue.workshop_id else '',
                date=issue.board_date.isoformat() if issue.board_date else None, status=issue.get_status_display())


def overview(request, key, today):
    if not available(request, key):
        return dict(available=False, count=None, breakdown={}, preview=None, priority=[])
    priority = []
    if key == 'inbound':
        breakdown, rows = receipt_page(request, 'PENDING', 0, 1)
        count = sum(breakdown.values())
    elif key == 'issue':
        qs = issue_queryset(request, 'PENDING_REVIEW')
        count, rows = issue_group_page(qs, 0, 1)
        breakdown = {'documents': qs.count()}
    else:
        rows = [row for row, _ in waiting_purchases(request)]
        count = len(rows)
        breakdown = {'partial': sum(row['status'] == '部分收货' for row in rows)}
        priority = [row for row in rows if row['date'] and row['date'] <= today.isoformat()][:4]
    return dict(available=True, count=count, breakdown=breakdown, preview=rows[0] if rows else None, priority=priority)


def items(request, key, params):
    if not available(request, key):
        raise PermissionDenied('无权查看这项仓库待办。')
    size = params['page_size']
    offset = (params['page'] - 1) * size
    if key == 'inbound':
        counts, rows = receipt_page(request, 'PENDING', offset, size)
        return sum(counts.values()), rows
    if key == 'purchase':
        rows = waiting_purchases(request)
        return len(rows), [row for row, _ in rows[offset:offset + size]]
    issues = issue_queryset(request, 'PENDING_REVIEW')
    if not params.get('task_id'):
        return issue_group_page(issues, offset, size)
    issues = issues.filter(production_task_id=params['task_id']).select_related(
        'production_task', 'product_line', 'workshop').order_by('board_date', 'id')
    total = issues.count()
    if not total:
        raise NotFound('该任务当前没有可查看的待发料单。')
    return total, [issue_row(i) for i in issues[offset:offset + size]]


def _receipt_lines(receipt, kind):
    confirmed = receipt.status == 'CONFIRMED'
    if kind == 'finished':
        return [quantities(names([receipt.product_name_snapshot, receipt.specification_snapshot, receipt.actual_color]),
                           receipt.unit.unit_name, receipt.received_quantity, receipt.received_quantity if confirmed else 0)]
    return [quantities(line.attribute_snapshot.get('part_name') or line.bom_line.part_name,
                       line.unit.unit_name, line.quantity, line.quantity if confirmed else 0)
            for line in receipt.lines.select_related('unit', 'bom_line').order_by('created_at', 'id')]


def _purchase_receipts(request):
    # 工作台汇总仓管自身的收货职责；兼任品质不会扩大可见材料分区。
    if not can_read_inventory_overview(request, RECEIVE):
        raise PermissionDenied('当前权限仅可在关联任务中读取入库记录。')
    records, lines, _ = purchase_receipt_scope(request, {RECEIVE})
    return records.select_related('purchase_order__production_task').prefetch_related(
        Prefetch('lines', queryset=lines.order_by('id'), to_attr='board_lines'))


def _purchase_receipt_row(r):
    task, product = purchase_source(r.purchase_order, (line.product_name_snapshot for line in r.board_lines))
    return dict(id=str(r.pk), kind='purchase_receipt', task_number=task, product=product,
        number=r.inbound_number, party=names(l.supplier_name_snapshot for l in r.board_lines),
        date=r.inbound_date.isoformat(), status=r.get_status_display())


def _physical_receipt_line(line):
    if is_root_receipt(line) or (line.measurement_kind == 'PIPE' and line.received_bar_count is not None):
        done, unit = line.received_bar_count, '根'
    elif is_hardware_weight(line):
        done, unit = line.received_weight_kg, 'kg'
    elif line.measurement_kind == 'PIPE':
        done, unit = line.received_quantity, '米'
    else:
        done, unit = line.received_quantity, line.source_unit_text_snapshot
    return quantities(names([line.part_name_snapshot, line.specification_snapshot]), unit, None, done)


def detail(request, key, kind, id):
    if not available(request, key) or (key == 'inbound' and kind in CONFIRM and kind not in _receipt_kinds(request)):
        raise PermissionDenied('无权查看此类仓库单据。')
    if key == 'purchase' and kind == 'purchase':
        candidates = waiting_purchases(request, id)
        if not candidates:
            raise NotFound('未找到可查看的待收采购单。')
        row, lines = candidates[0]
    elif key == 'purchase' and kind == 'purchase_receipt':
        receipt = _purchase_receipts(request).filter(pk=id).first()
        if receipt is None:
            raise NotFound('未找到可查看的收货记录。')
        row, lines = _purchase_receipt_row(receipt), [_physical_receipt_line(line) for line in receipt.board_lines]
    elif key == 'inbound' and kind in CONFIRM:
        for status in ('PENDING', 'CONFIRMED'):
            receipt = receipt_queryset(request, kind, status).filter(pk=id).first()
            if receipt:
                break
        if not receipt:
            raise NotFound('未找到可查看的车间入库单。')
        row, lines = receipt_row(receipt, kind), _receipt_lines(receipt, kind)
    elif key == 'issue' and kind == 'issue':
        for status in ('PENDING_REVIEW', 'ISSUED'):
            issue = issue_queryset(request, status).filter(pk=id).select_related('production_task', 'product_line', 'workshop').first()
            if issue:
                break
        if not issue:
            raise NotFound('未找到可查看的领料单。')
        row = issue_row(issue)
        lines = [quantities(names([l.material_name_snapshot, l.specification_snapshot, l.color_snapshot]), l.unit_snapshot,
                            l.requested_quantity, l.issued_quantity if status == 'ISSUED' else 0)
                 for l in issue.lines.order_by('line_number')]
    else:
        raise NotFound('未找到对应类型的仓库单据。')
    return dict(row=row, lines=lines, movements=[], related=None)


def activity(request, key, start, end, limit, offset):
    if not available(request, key) or (key == 'purchase' and not can_read_inventory_overview(request, RECEIVE)):
        return None, []
    if key == 'inbound':
        counts, rows = receipt_page(request, 'CONFIRMED', offset, limit, (start, end))
        total = sum(counts.values())
    elif key == 'issue':
        qs = issue_queryset(request, 'ISSUED').filter(board_date__range=(start, end)).order_by('-board_date', '-id')
        total = qs.count()
        rows = [issue_row(i) for i in qs.select_related('production_task', 'product_line', 'workshop')[offset:offset + limit]]
    else:
        qs = _purchase_receipts(request).filter(inbound_date__range=(start, end)).order_by('-inbound_date', '-id')
        total = qs.count()
        rows = [_purchase_receipt_row(r) for r in qs[offset:offset + limit]]
    return total, [dict(id=r['id'], kind=r['kind'], task_number=r['task_number'], number=r['number'],
                        party=r['party'], date=r['date'], description=r['product']) for r in rows]
