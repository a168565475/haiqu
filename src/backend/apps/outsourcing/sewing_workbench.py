"""车缝外协工作台，以总单或历史独立车缝单为一个跟进对象。"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Prefetch, Q
from django.db.models.functions import Coalesce

from apps.access_control.resource_scopes import filter_crafts
from .models import (TubeOutsourcingInput, TubeOutsourcingLine, TubeOutsourcingReceiptLine,
                     TubePlanReceiptLine)
from .tube_selectors import VIEW_PERMISSION, saved_orders_for_permission


SEND = ('send', 'late_send', 'today_send', 'partial')
RETURN = ('working', 'soon', 'today', 'overdue', 'upcoming')


def visible_sewing_orders(request):
    visible = saved_orders_for_permission(request, VIEW_PERMISSION)
    # 与详情页 require_saved_order_access 同时检查原单和工艺范围。
    return filter_crafts(visible, request, VIEW_PERMISSION).filter(
        plan__isnull=True, craft__outsourcing_code='SEWING').exclude(status='CANCELLED')


def shipment_rows(order_ids, period=None):
    # 新车缝总单发的是裁片；旧批次/独立单发的是原加工明细。
    active = {'order__actions__kind': 'DISPATCH', 'order__status__in': ('PROCESSING', 'COMPLETED')}
    if period:
        active['order__actions__actual_dispatch_date__range'] = period
    for model in (TubeOutsourcingInput, TubeOutsourcingLine):
        yield model.objects.filter(Q(order__plan_id__in=order_ids) | Q(order_id__in=order_ids, order__is_plan=False),
            **active).annotate(root=Coalesce('order__plan_id', 'order_id')).order_by()


def receipt_lines(order_ids, period=None):
    filters = {'receipt__order_id__in': order_ids, 'received_quantity__gt': 0}
    if period:
        filters['receipt__receipt_date__range'] = period
    for rows in (TubePlanReceiptLine.objects.filter(receipt__voided_at__isnull=True, **filters),
                 TubeOutsourcingReceiptLine.objects.filter(**filters)):
        yield from rows.order_by().values_list('receipt__order_id', 'order_line_id', 'order_line__factory_id',
            'order_line__factory__name', 'order_line__snapshot__unit', 'received_quantity',
            'receipt_id', 'receipt__receipt_date').iterator()


def quantity_row(name, factory, unit, target, actual):
    return {'name': name, 'factory_name': factory, 'unit': unit, 'target': str(target),
            'actual': str(actual), 'remaining': str(max(target - actual, 0))}


def open_orders(request, today, *, for_dispatch=False):
    lines = TubeOutsourcingLine.objects.select_related('factory').only(
        'order_id', 'component_identity', 'quantity', 'snapshot', 'factory__name')
    orders = list(visible_sewing_orders(request).exclude(status='COMPLETED')
        .select_related('product_line__production_task').prefetch_related(Prefetch('lines', queryset=lines))
        .annotate(piece_inputs=F('source_snapshot__sewing_inputs')).only(
            'order_number', 'is_plan', 'planned_dispatch_date', 'expected_return_date',
            'product_line__product_name_snapshot', 'product_line__production_task__task_number'))
    ids = [order.pk for order in orders]
    sent, received = Counter(), Counter()
    last_send, last_return = {}, {}
    for shipments in shipment_rows(ids):
        for root, factory, component, quantity, day in shipments.values_list(
                'root', 'factory_id', 'component_identity', 'quantity', 'order__actions__actual_dispatch_date').iterator():
            sent[root, factory, str(component)] += quantity
            last_send[root] = max(day, last_send.get(root, day))
    for root, line_id, _, _, _, quantity, _, day in receipt_lines(ids):
        received[line_id] += quantity
        last_return[root] = max(day, last_return.get(root, day))

    for order in orders:
        materials, parts = [], []
        for line in order.lines.all():
            snapshot = line.snapshot
            factory = snapshot.get('factory_name') or line.factory.name
            unit = snapshot.get('unit') or '套'  # 历史裁片整套外发流程。
            name = snapshot.get('part_name') or ''
            sent_to_part = 0
            if order.piece_inputs:
                for piece in snapshot.get('pieces', []):
                    actual = sent[order.pk, line.factory_id, piece['component_identity']]
                    target = line.quantity * piece['pieces_per_part']
                    if target > actual:
                        materials.append(quantity_row(piece['part_name'], factory, piece.get('unit') or '片', target, actual))
                    sent_to_part += actual
            else:
                sent_to_part = sent[order.pk, line.factory_id, str(line.component_identity)]
                if line.quantity > sent_to_part:
                    materials.append(quantity_row(name, factory, unit, line.quantity, sent_to_part))
            # 部位应回沿用总单完工口径。新总单可以分次发裁片，不能用裁片数减部位实收数。
            expected = int(Decimal(snapshot['order_required'])) if order.is_plan else line.quantity
            if (sent_to_part or received[line.pk]) and received[line.pk] < expected:
                parts.append(quantity_row(name, factory, unit, expected, received[line.pk]))

        flags = set()
        if materials:
            flags.add('send')
            if order.planned_dispatch_date < today:
                flags.add('late_send')
            elif order.planned_dispatch_date == today:
                flags.add('today_send')
            if order.pk in last_send:
                flags.add('partial')
        if parts:
            flags.add('working')
            days = (order.expected_return_date - today).days
            if days < 0:
                flags.add('overdue')
            elif days == 0:
                flags.add('today')
            elif days <= 3:
                flags.add('soon')
            if 0 <= days < 7:
                flags.add('upcoming')
        if flags:
            yield flags, {'id': order.pk, 'order_number': order.order_number, 'is_plan': order.is_plan,
                'task_number': order.product_line.production_task.task_number,
                'product_name': order.product_line.product_name_snapshot,
                'planned_dispatch_date': order.planned_dispatch_date, 'expected_return_date': order.expected_return_date,
                'last_dispatch_date': last_send.get(order.pk), 'last_receipt_date': last_return.get(order.pk),
                'factories': sorted({row['factory_name'] for row in (materials if for_dispatch else parts)}),
                'materials': materials, 'parts': parts}


def overview(request, today):
    counts = dict.fromkeys([*SEND, *RETURN[:-1]], 0)
    upcoming = Counter()
    for flags, order in open_orders(request, today):
        for key in flags:
            if key == 'upcoming':
                upcoming[order['expected_return_date']] += 1
            else:
                counts[key] += 1
    return {'as_of': today, 'counts': counts, 'upcoming': [
        {'date': day, 'count': upcoming[day]} for day in (today + timedelta(days=i) for i in range(7))]}


def workbench_items(request, today, category, day):
    sending = category in SEND
    rows = [row for flags, row in open_orders(request, today, for_dispatch=sending)
            if category in flags and (day is None or row['expected_return_date'] == day)]
    due = 'planned_dispatch_date' if sending else 'expected_return_date'
    return sorted(rows, key=lambda row: (row[due], row['task_number'], row['order_number']))


def quantity_totals(totals):
    return [{'unit': unit, 'quantity': str(value)} for unit, value in sorted(totals.items())]


def activity(request, today, period):
    start_month = {'month': today.month, 'quarter': (today.month - 1) // 3 * 3 + 1, 'year': 1}[period]
    start = today.replace(month=start_month, day=1)
    ids = visible_sewing_orders(request).order_by().values('pk')
    sent_orders, sent_factories = set(), set()
    for shipments in shipment_rows(ids, (start, today)):
        for root, factory in shipments.values_list('root', 'factory_id').distinct().iterator():
            sent_orders.add(root)
            sent_factories.add(factory)
    factories, returns, events = {}, set(), set()
    totals = Counter()
    for root, _, factory, name, unit, quantity, event, _ in receipt_lines(ids, (start, today)):
        returns.add(root)
        events.add(event)
        group = factories.setdefault(factory, {'id': factory, 'name': name, 'orders': set(), 'totals': Counter()})
        group['orders'].add(root)
        group['totals'][unit or '套'] += quantity
        totals[unit or '套'] += quantity
    ranked = [{'id': f['id'], 'name': f['name'], 'order_count': len(f['orders']), 'quantities': quantity_totals(f['totals'])}
              for f in factories.values()]
    # 有多个单位时不把件、套相加排名，改按有回货的单数排序。
    ranked.sort(key=lambda f: (-(int(f['quantities'][0]['quantity']) if len(totals) == 1 else f['order_count']), f['name'], str(f['id'])))
    return {'start_date': start, 'end_date': today, 'dispatch_orders': len(sent_orders),
            'dispatch_factories': len(sent_factories), 'receipt_orders': len(returns),
            'receipt_factories': len(ranked), 'receipt_events': len(events), 'factories': ranked, 'quantities': quantity_totals(totals)}
