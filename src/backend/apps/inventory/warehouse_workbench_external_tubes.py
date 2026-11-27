"""现行委外。总单以实际批次、有效回货凭证核对，独立老单只认最终回货。"""
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db.models import Exists, OuterRef, Prefetch, Q, Sum

from apps.outsourcing.models import (
    TubeOutsourcingAction, TubeOutsourcingInput, TubeOutsourcingLine, TubeOutsourcingMaterial,
    TubeOutsourcingOrder, TubeOutsourcingReceipt, TubePlanReceipt,
)
from apps.outsourcing.plan_selectors import plan_quantities
from apps.outsourcing.source_access import STOCK_SOURCES
from apps.outsourcing.tube_kinds import output_unit
from apps.outsourcing.warehouse_access import DISPATCH_PERMISSION, RETURN_PERMISSION, warehouse_tube_orders
from .warehouse_workbench_external_common import document, event, number, quantity


def _visible(request, key):
    if not getattr(settings, 'TUBE_OUTSOURCING_ENABLED', False):
        return TubeOutsourcingOrder.objects.none()
    permission = DISPATCH_PERMISSION if key == 'dispatch' else RETURN_PERMISSION
    return warehouse_tube_orders(request, permission)


def _batch_sums(model, plans):
    quantities = model.objects.filter(order__plan__in=plans,
        order__status__in=['PROCESSING', 'COMPLETED'], order__actions__kind='DISPATCH')
    grouped = quantities.order_by().values('order__plan_id', 'component_identity').annotate(
        total=Sum('quantity'), direct=Sum('quantity', filter=~Q(order__source_kind__in=STOCK_SOURCES)))
    return {(root, part): (total, direct or 0) for root, part, total, direct in
            grouped.values_list('order__plan_id', 'component_identity', 'total', 'direct')}


def _dispatched_line(name, unit, required, sent, direct, factory):
    if direct:
        name += f'（另有直发 {number(direct)} {unit}）'
    return quantity(name, unit, max(required - direct, 0), sent - direct, factory=factory)


def tube_documents(request, key, pk=None):
    roots = _visible(request, key).filter(plan__isnull=True, status__in=['PENDING_DISPATCH', 'PROCESSING'])
    if key == 'dispatch':
        # 已指定车间/加工点直发的单不计作仓库待发。裁片丝印总单由裁片选入，来源在分批发出时选。
        roots = roots.filter(
            Q(source_kind__in=STOCK_SOURCES) | Q(is_plan=True, source_snapshot__contains={'screen_print_pieces': True}) |
            Q(source_snapshot__planned_materials__0__isnull=False) |
            Exists(TubeOutsourcingMaterial.objects.filter(order_id=OuterRef('pk')))
        )
    if pk is not None:
        roots = roots.filter(pk=pk)
    orders = list(roots.annotate(sent_once=Exists(TubeOutsourcingAction.objects.filter(
        Q(order_id=OuterRef('pk')) | Q(order__plan_id=OuterRef('pk')), kind='DISPATCH',
        order__status__in=['PROCESSING', 'COMPLETED'])),
        finalised=Exists(TubeOutsourcingReceipt.objects.filter(order_id=OuterRef('pk'))))
        .select_related('product_line__production_task')
        .prefetch_related(Prefetch('lines', queryset=TubeOutsourcingLine.objects.select_related('factory')),
                          Prefetch('materials', queryset=TubeOutsourcingMaterial.objects.select_related('unit','factory'))))
    plans = [o for o in orders if o.is_plan]
    progress = plan_quantities(plans) if key == 'returns' else {}
    pieces = _batch_sums(TubeOutsourcingInput, [o for o in plans if o.source_snapshot.get('sewing_inputs')])
    main_batches = {}
    if key == 'dispatch':
        main_batches = _batch_sums(TubeOutsourcingLine, [o for o in plans if not o.source_snapshot.get('sewing_inputs')])
    planned_ids = [o.pk for o in plans if key == 'dispatch' and o.source_snapshot.get('planned_materials')]
    sent_aux = {(root, str(bom), str(factory)): total for root, bom, factory, total in
        TubeOutsourcingMaterial.objects.filter(order__plan_id__in=planned_ids,
            order__status__in=['PROCESSING', 'COMPLETED'], order__actions__kind='DISPATCH').order_by()
        .values('order__plan_id', 'bom_line_id', 'factory_id').annotate(n=Sum('quantity'))
        .values_list('order__plan_id', 'bom_line_id', 'factory_id', 'n')}
    for order in orders:
        if key == 'returns' and (not order.sent_once or order.finalised):
            continue
        if key == 'dispatch' and not order.is_plan and order.status != 'PENDING_DISPATCH':
            continue
        lines, factories = [], set()
        main_stock = order.source_kind in STOCK_SOURCES or order.source_snapshot.get('screen_print_pieces')
        sewing = order.is_plan and order.source_snapshot.get('sewing_inputs')
        for line in order.lines.all():
            if key == 'dispatch' and not main_stock:
                continue
            s = line.snapshot
            factory = s.get('factory_name') or line.factory.name
            factories.add(factory)
            counts = progress[str(order.pk)]['lines'][str(line.pk)] if key == 'returns' and order.is_plan else {}
            name = s.get('part_name') or s.get('name') or s.get('specification') or '加工件'
            unit = s.get('unit') or output_unit(order.source_kind)
            if sewing:
                sent = 0
                for piece in s.get('pieces', []):
                    done, direct = pieces.get((order.pk, UUID(str(piece['component_identity']))), (0, 0))
                    sent += done
                    if key == 'dispatch':
                        lines.append(_dispatched_line(piece['part_name'], piece.get('unit') or '片',
                                     line.quantity * piece['pieces_per_part'], done, direct, factory))
                if key == 'dispatch':
                    continue
            elif key == 'dispatch':
                sent, direct = main_batches.get((order.pk, line.component_identity), (0, 0))
                lines.append(_dispatched_line(name, unit, line.quantity, sent, direct, factory))
                continue
            else:
                sent = int(counts['dispatched_quantity']) if order.is_plan else line.quantity
            done = int(counts.get('received_quantity', 0))
            if not sent and not done:
                continue
            forwarded = int(counts.get('transferred_quantity', 0))
            target = int(counts['bom_quantity']) if sewing else max(sent - forwarded, 0)
            if forwarded:
                name += f'（已直交下道加工 {forwarded} {unit}）'
            lines.append({**quantity(name, unit, target, done, factory=factory),
                          'basis_label': '整单部位需求' if sewing else '已发应回仓'})
        if key == 'dispatch':
            for m in order.source_snapshot.get('planned_materials', []) if order.is_plan else ():
                factory = m.get('factory_name', '')
                factories.add(factory)
                lines.append(quantity(m.get('name') or m.get('part_name') or '辅料', m.get('unit', ''),
                    Decimal(str(m['quantity'])), sent_aux.get((order.pk, str(m['bom_line_id']), str(m['factory_id'])), 0),
                    factory=factory))
            for m in order.materials.all() if not order.is_plan else ():
                factories.add(m.factory.name)
                lines.append(quantity(m.snapshot.get('name') or '辅料', m.unit.unit_name, m.quantity, 0, factory=m.factory.name))
        if any(Decimal(line['remaining']) > 0 for line in lines):
            partial = any(Decimal(line['done']) > 0 for line in lines)
            yield document(order, 'tube', key, order.product_line.production_task.task_number,
                order.product_line.product_name_snapshot, factories,
                order.planned_dispatch_date if key == 'dispatch' else order.expected_return_date, partial, lines)


def _description(lines, attr, unit):
    descriptions = []
    for line in lines:
        snapshot = line.snapshot
        name = snapshot.get('part_name') or snapshot.get('name') or '加工件'
        if isinstance(line, TubeOutsourcingMaterial):
            line_unit = line.unit.unit_name
        elif attr == 'received_quantity':
            line_unit = snapshot.get('unit') or line.order_line.snapshot.get('unit')
        else:
            line_unit = snapshot.get('unit')
        descriptions.append(f"{name} {number(getattr(line, attr))} {line_unit or unit}")
    return '、'.join(descriptions)


def tube_events(request, key, period, maximum, pk):
    scoped = _visible(request, key)
    roots = scoped.filter(plan__isnull=True)
    if pk:
        roots = roots.filter(pk=pk)
    roots = roots.values('pk')
    if key == 'dispatch':
        batches = scoped.filter(Q(pk__in=roots) | Q(plan_id__in=roots)).filter(
            status__in=['PROCESSING', 'COMPLETED']).filter(Q(source_kind__in=STOCK_SOURCES) |
            Q(materials__isnull=False)).order_by().values('pk')
        qs = TubeOutsourcingAction.objects.filter(order_id__in=batches, kind='DISPATCH')
        if period:
            qs = qs.filter(actual_dispatch_date__range=period)
        count = qs.count()
        rows = []
        if maximum != 0:
            for a in qs.select_related('order__plan','order__product_line__production_task').prefetch_related(
                    'order__inputs__factory', 'order__lines__factory', 'order__materials__factory',
                    'order__materials__unit').order_by(
                    '-actual_dispatch_date', '-pk')[:maximum]:
                order = a.order
                lines = list(order.inputs.all() if order.source_snapshot.get('sewing_inputs') else order.lines.all()
                             ) if order.source_kind in STOCK_SOURCES else []
                lines += list(order.materials.all())
                root = order.plan or order
                rows.append(event(a, 'tube', root.order_number, order.product_line.production_task.task_number,
                    a.actual_dispatch_date, order.order_number, '、'.join(sorted({l.factory.name for l in lines})),
                    _description(lines, 'quantity', output_unit(order.source_kind))))
        return count, rows
    total, rows = 0, []
    for model in (TubePlanReceipt, TubeOutsourcingReceipt):
        qs = model.objects.filter(order_id__in=roots, lines__received_quantity__gt=0).distinct()
        if model is TubePlanReceipt:
            qs = qs.filter(voided_at__isnull=True)
        if period:
            qs = qs.filter(receipt_date__range=period)
        total += qs.count()
        if maximum != 0:
            for r in qs.select_related('order__product_line__production_task').prefetch_related(
                    'lines__order_line__factory').order_by('-receipt_date', '-pk')[:maximum]:
                lines = [l for l in r.lines.all() if l.received_quantity]
                rows.append(event(r, 'tube', r.order.order_number, r.order.product_line.production_task.task_number,
                    r.receipt_date, r.receipt_number, '、'.join(sorted({l.order_line.factory.name for l in lines})),
                    _description(lines, 'received_quantity', output_unit(r.order.source_kind))))
    return total, rows
