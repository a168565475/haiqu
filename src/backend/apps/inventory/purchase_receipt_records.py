from collections import defaultdict

from django.db.models import Case, CharField, Count, DateTimeField, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, NullIf
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_policy import has_permission
from apps.procurement.source_access import purchase_order_access
from apps.production_tasks.selectors import accessible_production_tasks

from .models import MaterialInbound, MaterialInboundLine, MaterialTransfer, MaterialTransferLine, PURCHASE_INBOUND_SECTION_NAMES
from .purchase_receiving_sections import SECTION_CATEGORIES, assigned_receiving_sections, receiving_lines_in_scope
from .selectors import can_read_inventory_overview, inbound_product_summaries


RECEIPT_PERMISSIONS = ('inventory.receive_material', 'inventory.quality_confirm_material', 'inventory.view_material_receipt')
RECEIPT_STATUSES = {'PENDING_QUALITY': '待质检', 'CONFIRMED': '已入库', 'RETURNED': '全部退货'}
RECEIPT_SOURCES = {'PURCHASE': '采购收货', 'TRANSFER': '材料收发'}
UNASSIGNED_SECTION = 'UNASSIGNED'
SUMMARY_FIELDS = ('id', 'source', 'production_task_number', 'inbound_number', 'purchase_order_number', 'material_section', 'batch_number', 'inbound_date',
                  'received_by_name', 'quality_confirmed_by_name', 'quality_confirmed_at', 'line_count', 'record_status',
                  'can_quality_confirm', 'created_at')


def purchase_receipts_for(request, permission, allowed):
    records = MaterialInbound.objects.filter(purchase_order__isnull=False)
    if not allowed:
        return records.none()
    task_ids = accessible_production_tasks(request, permission=permission).order_by().values('id')
    return records.filter(purchase_order_access(task_ids, request, 'purchase_order__', permission=permission))


def receipt_record_permissions(request):
    allowed = {permission for permission in RECEIPT_PERMISSIONS
               if has_permission(request, permission) and can_read_inventory_overview(request, permission)}
    if not allowed:
        raise PermissionDenied('当前权限仅可在关联任务中读取入库记录。')
    return allowed


def purchase_receipt_scope(request, allowed):
    receive, confirm, read = RECEIPT_PERMISSIONS
    quality_records = purchase_receipts_for(request, confirm, confirm in allowed)
    receiving_records = purchase_receipts_for(request, receive, receive in allowed)
    confirmed_records = purchase_receipts_for(request, read, read in allowed).filter(status='CONFIRMED')
    categories = assigned_receiving_sections(request)
    lines = MaterialInboundLine.objects.all()
    scoped_lines = receiving_lines_in_scope(lines, categories, order_field='inbound__purchase_order')
    if categories is not None:
        scoped_lines = lines.filter(Q(pk__in=scoped_lines.values('pk')) | Q(inbound_id__in=quality_records.values('pk')))

    known = Q(pk__in=receiving_records.values('pk')) | Q(pk__in=quality_records.values('pk')) | Q(pk__in=confirmed_records.values('pk'))
    records = MaterialInbound.objects.filter(known)
    if categories is not None:
        records = records.filter(Exists(scoped_lines.filter(inbound_id=OuterRef('pk'))))

    current_lines = lines.filter(inbound_id=OuterRef('pk'))
    accepted = current_lines.filter(Q(accepted_quantity__gt=0) | Q(accepted_weight_kg__gt=0))
    returned = current_lines.filter(Q(return_quantity__gt=0) | Q(return_weight_kg__gt=0))
    visible_count = scoped_lines.filter(inbound_id=OuterRef('pk')).order_by().values('inbound_id').annotate(count=Count('pk')).values('count')
    records = records.select_related('purchase_order', 'received_by_employee', 'quality_confirmed_by_employee').annotate(
        record_status=Case(
            When(status='PENDING_QUALITY', then=Value('PENDING_QUALITY')),
            When(~Exists(accepted) & Exists(returned), then=Value('RETURNED')),
            default=Value('CONFIRMED'), output_field=CharField(),
        ),
        can_quality_confirm=Exists(quality_records.filter(pk=OuterRef('pk'), status='PENDING_QUALITY')),
        visible_line_count=Coalesce(Subquery(visible_count), 0),
    )
    sections = [
        {'id': code, 'name': name} for code, name in PURCHASE_INBOUND_SECTION_NAMES.items()
        if categories is None or confirm in allowed or categories & SECTION_CATEGORIES[code]
    ]
    return records, scoped_lines, sections


def transfer_receipt_scope(request, allowed):
    receive, _, read = RECEIPT_PERMISSIONS
    records = MaterialTransfer.objects.filter(direction='IN')
    lines = MaterialTransferLine.objects.all()
    if read not in allowed:
        records = records.filter(operated_by_employee=request.employee) if receive in allowed else records.none()
    categories = assigned_receiving_sections(request)
    visible = lines
    if categories is not None:
        visible = lines.filter(material_selection_snapshot__category_key__in=categories)
        records = records.filter(Exists(visible.filter(transfer_id=OuterRef('pk'))))

    current = lines.filter(transfer_id=OuterRef('pk'))
    # A historical transfer with material from more than one group belongs once in 未登记.
    sections = []
    for section, category_keys in SECTION_CATEGORIES.items():
        matching = lines.filter(material_selection_snapshot__category_key__in=category_keys)
        sections.append(When(
            Exists(current.filter(pk__in=matching.values('pk'))) & ~Exists(current.exclude(pk__in=matching.values('pk'))),
            then=Value(section),
        ))
    visible_count = visible.filter(transfer_id=OuterRef('pk')).order_by().values('transfer_id').annotate(count=Count('pk')).values('count')
    return records.select_related('operated_by_employee').annotate(
        material_section=Case(*sections, default=Value(''), output_field=CharField()),
        visible_line_count=Coalesce(Subquery(visible_count), 0),
    ), visible


def receipt_record_page(purchases, transfers, purchase_lines, *, section, status, keyword, page, page_size):
    if section is not None:
        purchases = purchases.filter(material_section=section)
        transfers = transfers.filter(material_section=section)
    purchases = purchases.annotate(production_task_number=Coalesce(
        NullIf('purchase_order__production_task_number_snapshot', Value('')),
        'purchase_order__production_task__task_number', Value(''), output_field=CharField(),
    ))
    if status:
        purchases = purchases.filter(record_status=status)
        if status != 'CONFIRMED':
            transfers = transfers.none()
    if keyword:
        named_lines = purchase_lines.filter(inbound_id=OuterRef('pk')).filter(
            Q(supplier_name_snapshot__icontains=keyword) | Q(product_name_snapshot__icontains=keyword),
        )
        purchases = purchases.filter(Q(inbound_number__icontains=keyword) | Q(purchase_order__order_number__icontains=keyword)
                                     | Q(production_task_number__icontains=keyword) | Exists(named_lines))
        transfers = transfers.filter(transfer_number__icontains=keyword)

    purchase_rows = purchases.order_by().annotate(
        source=Value('PURCHASE'), purchase_order_number=F('purchase_order__order_number'),
        batch_number=F('purchase_order__batch_number'), received_by_name=F('received_by_employee__display_name'),
        quality_confirmed_by_name=Coalesce('quality_confirmed_by_employee__display_name', Value('')),
        line_count=F('visible_line_count'),
    ).values(*SUMMARY_FIELDS)
    transfer_rows = transfers.order_by().annotate(
        source=Value('TRANSFER'), production_task_number=Value(''), inbound_number=F('transfer_number'), purchase_order_number=Value(''),
        batch_number=Value(None, output_field=IntegerField()), inbound_date=F('transfer_date'),
        received_by_name=F('operated_by_employee__display_name'), quality_confirmed_by_name=Value(''),
        quality_confirmed_at=Value(None, output_field=DateTimeField()),
        line_count=F('visible_line_count'), record_status=Value('CONFIRMED'), can_quality_confirm=Value(False),
    ).values(*SUMMARY_FIELDS)
    combined = purchase_rows.union(transfer_rows, all=True).order_by('-inbound_date', '-created_at', '-id', 'source')
    offset = (page - 1) * page_size
    rows = list(combined[offset:offset + page_size])
    include_receipt_check_fields(rows, purchase_lines)
    return rows, combined.count()


def include_receipt_check_fields(rows, visible_lines):
    receipt_ids = [row['id'] for row in rows if row['source'] == 'PURCHASE']
    orders_by_receipt = {}
    purchase_lines = defaultdict(list)
    supplier_names = defaultdict(dict)
    unlinked_names = defaultdict(dict)
    for line in visible_lines.filter(inbound_id__in=receipt_ids).select_related(
        'inbound__purchase_order', 'purchase_order_line',
    ).order_by('inbound_id', 'purchase_order_line__line_number', 'id'):
        receipt_id = line.inbound_id
        orders_by_receipt[receipt_id] = line.inbound.purchase_order
        if line.purchase_order_line and line.purchase_order_line.purchase_order_id == line.inbound.purchase_order_id:
            purchase_lines[receipt_id].append(line.purchase_order_line)
        if line.supplier_name_snapshot.strip():
            supplier_names[receipt_id][line.supplier_name_snapshot.strip()] = None
        if line.product_name_snapshot.strip():
            unlinked_names[receipt_id][line.product_name_snapshot.strip()] = None
    products = inbound_product_summaries(orders_by_receipt, purchase_lines, include_unlinked=True)
    for row in rows:
        if row['source'] == 'TRANSFER':
            row['supplier_names'] = []
            row['product_summary'] = []
            continue
        receipt_id = row['id']
        row['supplier_names'] = list(supplier_names.get(receipt_id, {}))
        row['product_summary'] = products.get(receipt_id) or [
            {'product_line_id': None, 'product_name': name, 'item_number': '', 'specification': '', 'color_name': '', 'material': ''}
            for name in unlinked_names.get(receipt_id, {})
        ]
