"""采购待收货按原单冻结单位和当前仓管可收的材料分区计算。"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Exists, OuterRef, Q

from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseReturnLine
from apps.procurement.selectors import purchase_line_products
from apps.procurement.source_access import purchase_order_access
from apps.production_tasks.selectors import accessible_production_tasks

from .pipe_receipt_basis import root_receipt_line_ids
from .purchase_receiving_sections import assigned_receiving_sections, receiving_lines_in_scope
from .selectors import eligible_material_purchase_orders, material_received_totals


RECEIVE = 'inventory.receive_material'


def names(values):
    return '、'.join(dict.fromkeys(value for value in values if value))


def purchase_source(order, product_names):
    product = names(product_names)
    if order.source_type == 'SAMPLE':
        return '', names(['打样采购', order.sample_number_snapshot, product])
    task = order.production_task_number_snapshot or (order.production_task.task_number if order.production_task_id else '')
    return task, product


def quantities(name, unit, required, done):
    remaining = max(required - done, 0) if required is not None and done is not None else None
    return {'name': name, 'unit': unit, 'required': str(required) if required is not None else None,
            'done': str(done) if done is not None else None,
            'remaining': str(remaining) if remaining is not None else None}


def waiting_purchases(request, order_id=None):
    task_ids = accessible_production_tasks(request, permission=RECEIVE).order_by().values('id')
    allowed = PurchaseOrder.objects.filter(purchase_order_access(task_ids, request, permission=RECEIVE))
    if order_id:
        allowed = allowed.filter(pk=order_id)
    # 完成单只允许补收已完成退货的原行；仍有未办结退货时原入库入口不允许收货。
    orders = eligible_material_purchase_orders(allowed).order_by().values('id')
    returned = PurchaseReturnLine.objects.filter(inbound_line__purchase_order_line_id=OuterRef('pk'),
                                                return_order__status='COMPLETED')
    lines = receiving_lines_in_scope(PurchaseOrderLine.objects.all(), assigned_receiving_sections(request)).filter(
        purchase_order_id__in=orders, actual_purchase_quantity__isnull=False,
    ).filter(~Q(purchase_order__status='COMPLETED') | Exists(returned)).select_related('purchase_order')
    lines = list(lines.only(
        'id', 'purchase_order_id', 'line_number', 'part_name_snapshot', 'product_name_snapshot',
        'product_specification_snapshot', 'product_line_id_snapshot', 'bom_id', 'calculation_snapshot',
        'specification_snapshot', 'color_snapshot', 'source_unit_text', 'supplier_name_snapshot',
        'actual_bar_count', 'actual_purchase_quantity', 'delivery_date', 'purchase_order__order_number',
        'purchase_order__source_type', 'purchase_order__sample_number_snapshot',
        'purchase_order__production_task_number_snapshot', 'purchase_order__production_task__task_number',
    ).select_related('purchase_order__production_task').order_by('purchase_order_id', 'line_number', 'id'))
    totals = material_received_totals([line.pk for line in lines])
    roots = root_receipt_line_ids(lines)
    grouped = defaultdict(list)
    partial = set()
    detail_lines = []
    for line in lines:
        ordered = line.actual_bar_count if line.pk in roots else line.actual_purchase_quantity
        done = totals.get(line.pk, Decimal('0'))
        if order_id:
            item = quantities(names([line.part_name_snapshot, line.specification_snapshot, line.color_snapshot]),
                              '根' if line.pk in roots else line.source_unit_text, ordered, done)
            item.update(party=line.supplier_name_snapshot, date=line.delivery_date.isoformat() if line.delivery_date else None)
            detail_lines.append(item)
        if done > 0:
            partial.add(line.purchase_order_id)
        if ordered > done:
            grouped[line.purchase_order_id].append((line, ordered, done))
    documents = []
    for pk, pending in grouped.items():
        order = pending[0][0].purchase_order
        due = min((line.delivery_date for line, _, _ in pending if line.delivery_date), default=None)
        task, product = purchase_source(order, (p[2] for line, _, _ in pending for p in purchase_line_products(line)))
        row = dict(id=str(pk), kind='purchase', task_number=task, product=product,
                   number=order.order_number, party=names(line.supplier_name_snapshot for line, _, _ in pending),
                   date=due.isoformat() if due else None, status='部分收货' if pk in partial else '待收货')
        documents.append((row, detail_lines))
    return sorted(documents, key=lambda pair: (pair[0]['date'] or '9999', pair[0]['number'], pair[0]['id']))
