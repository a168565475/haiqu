from collections import defaultdict
from decimal import Decimal

from django.db.models import Exists, F, OuterRef, Prefetch, Sum, TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast

from apps.access_control.module_policy import has_permission
from apps.material_issues.models import MetalProcessingExternalGoodReturn, MetalProcessingExternalHandoff, MetalProcessingOriginalHandoff
from apps.material_issues.p4_access import scoped_records
from apps.outsourcing.models import (
    OutsourcingDispatch, OutsourcingFactoryAllocation, OutsourcingMaterialItem, OutsourcingOrderProduct,
    OutsourcingReconciliationEntry, OutsourcingReturn, OutsourcingReturnLine,
)
from apps.outsourcing.warehouse_access import (
    DISPATCH_PERMISSION, RETURN_PERMISSION, REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION,
    warehouse_regular_orders, warehouse_rework_orders,
)
from .warehouse_workbench_external_common import document, event, number, quantity


def _regular(request, key):
    return warehouse_regular_orders(request, DISPATCH_PERMISSION if key == 'dispatch' else RETURN_PERMISSION)


def regular_documents(request, key, pk):
    orders = _regular(request, key)
    if pk:
        orders = orders.filter(pk=pk)
    if key == 'dispatch':
        orders = orders.filter(status='PENDING_DISPATCH', dispatch_record__isnull=True)
    else:
        orders = orders.filter(status__in=['PROCESSING', 'PARTIAL_RETURN'], dispatch_record__isnull=False)
    orders = list(orders.select_related('schedule__production_task'))
    ids = [o.pk for o in orders]
    lines, factories, products = defaultdict(list), defaultdict(set), defaultdict(list)
    for order_id, name in OutsourcingOrderProduct.objects.filter(order_id__in=ids).values_list('order_id','product_snapshot__product_name'):
        if name and name not in products[order_id]:
            products[order_id].append(name)
    allocations = OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order_id__in=ids)
    if key == 'dispatch':
        for m in OutsourcingMaterialItem.objects.filter(allocation__in=allocations).select_related(
                'allocation__processing_item__order_product', 'allocation__factory'):
            oid = m.allocation.processing_item.order_product.order_id
            factory = m.allocation.factory_snapshot.get('name') or m.allocation.factory.name
            factories[oid].add(factory)
            material = m.material_snapshot
            name = material.get('material_name') or material.get('name') or material.get('part_name') or '外发材料'
            required, unit = (m.planned_piece_count, '支') if m.planned_piece_count is not None else (m.planned_issue_quantity, m.unit_text)
            lines[oid].append(quantity(name, unit, required, 0, factory=factory))
    else:
        returned = dict(OutsourcingReturnLine.objects.filter(allocation__in=allocations).order_by()
                        .values('allocation_id').annotate(n=Sum('returned_quantity')).values_list('allocation_id','n'))
        scrap = dict(OutsourcingReconciliationEntry.objects.filter(allocation__in=allocations, kind='OUTPUT_SCRAP')
                    .order_by().values('allocation_id').annotate(n=Sum('quantity')).values_list('allocation_id','n'))
        for a in allocations.select_related('processing_item__order_product','factory'):
            item = a.processing_item
            oid = item.order_product.order_id
            name = item.component_snapshot.get('part_name') or '加工件'
            factory = a.factory_snapshot.get('name') or a.factory.name
            factories[oid].add(factory)
            if scrap.get(a.pk):
                name += f'（已报废 {number(scrap[a.pk])} {item.unit_snapshot}）'
            done = returned.get(a.pk, 0)
            expected = max(a.allocated_quantity - scrap.get(a.pk, 0), 0)
            lines[oid].append(quantity(name, item.unit_snapshot, expected, done, factory=factory))
    for o in orders:
        rows = lines[o.pk]
        if any(Decimal(r['remaining']) > 0 for r in rows):
            yield document(o, 'outsourcing', key, o.schedule.production_task.task_number, '、'.join(products[o.pk]),
                factories[o.pk], o.delivery_date if key=='returns' else None, any(Decimal(r['done']) for r in rows), rows)


def _reworks(request,key):
    return warehouse_rework_orders(request, REWORK_HANDOFF_PERMISSION if key=='dispatch' else REWORK_RETURN_PERMISSION)


def rework_documents(request,key,pk):
    orders = _reworks(request,key)
    if pk:
        orders = orders.filter(pk=pk)
    if key=='dispatch':
        orders = orders.filter(status='PENDING_HANDOFF', handoff__isnull=True)
    else:
        orders = orders.filter(status__in=('PROCESSING', 'CLOSED'), handoff__isnull=False,
                               handoff_pieces__gt=F('returned_good_pieces'))
    for o in orders.select_related('source__issue_line__issue__production_task','source__issue_line__issue__product_line','factory'):
        issue = o.source.issue_line.issue
        want,done = (o.allocated_pieces,o.handoff_pieces) if key=='dispatch' else (o.handoff_pieces,o.returned_good_pieces)
        line = quantity(o.source.source_snapshot.get('part_name') or '金工重加工件', '支', want, done)
        yield document(o, 'rework', key, issue.production_task.task_number, issue.product_line.product_name_snapshot,
                       [o.factory.name], None, done>0, [line])


def _handoffs(request):
    if not has_permission(request,RETURN_PERMISSION):
        return MetalProcessingOriginalHandoff.objects.none()
    return scoped_records(MetalProcessingOriginalHandoff.objects.all(), request, RETURN_PERMISSION, 'original_order__craft_id')


def _metal_receipts(handoffs):
    linked = handoffs.annotate(source_key=Cast('source_id', TextField())).filter(
        original_order_id=OuterRef('return_record__order_id'), factory_id=OuterRef('allocation__factory_id'),
        source_key=OuterRef('visible_source_key'))
    return OutsourcingReturnLine.objects.annotate(visible_source_key=KT('snapshot__source_id')).filter(
        Exists(linked), quality='AVAILABLE')


def original_documents(request,key,pk):
    if key!='returns':
        return
    handoffs = _handoffs(request).filter(original_order__status__in=['PENDING_DISPATCH','PROCESSING','PARTIAL_RETURN','CLOSED'])
    if pk:
        handoffs = handoffs.filter(original_order_id=pk)
    totals, summary = defaultdict(lambda: [0, 0, 0]), {}
    for h in handoffs.select_related('original_order__schedule__production_task','source__issue_line__issue__product_line','factory').prefetch_related('unsprayed_returns'):
        # 同一部位与工厂的多次交接共用回货上限，不能按某次回货选择的来源重复算欠数。
        snapshot = h.source.source_snapshot
        index = (h.original_order_id, h.factory_id, snapshot['product_line_id'], snapshot['conversion_snapshot']['bom_line_id'])
        totals[index][0] += h.handoff_pieces
        totals[index][2] += sum(u.returned_pieces for u in h.unsprayed_returns.all())
        summary[index] = h
    fields = ('return_record__order_id', 'allocation__factory_id',
              'allocation__processing_item__order_product__schedule_product__product_line_id',
              'allocation__processing_item__bom_line_id')
    receipts = _metal_receipts(handoffs).order_by().values(*fields).annotate(total=Sum('returned_quantity'))
    for order_id, factory_id, product_id, bom_id, received in receipts.values_list(*fields, 'total'):
        index = (order_id, factory_id, str(product_id), str(bom_id))
        if index in totals:
            totals[index][1] = received
    grouped, parties, products, orders = defaultdict(list), defaultdict(set), defaultdict(set), {}
    for index,(sent,good,unprocessed) in totals.items():
        h = summary[index]
        oid = h.original_order_id
        orders[oid] = h.original_order
        parties[oid].add(h.factory.name)
        products[oid].add(h.source.issue_line.issue.product_line.product_name_snapshot)
        name = h.source.source_snapshot.get('part_name') or '金工加工件'
        if unprocessed:
            name += f'（未加工退回 {unprocessed} 支）'
        grouped[oid].append(quantity(name, '支', max(sent - unprocessed, 0), good, factory=h.factory.name))
    for oid,lines in grouped.items():
        o = orders[oid]
        if any(Decimal(r['remaining'])>0 for r in lines):
            yield document(o,'metal_original',key,o.schedule.production_task.task_number,'、'.join(sorted(products[oid])),
                           parties[oid],o.delivery_date,any(Decimal(r['done'])>0 for r in lines),lines)


def legacy_events(request, key, period, maximum, kind, pk):
    total, records = 0, []

    def selected(queryset, date_field):
        nonlocal total
        if period:
            queryset = queryset.filter(**{date_field + '__range': period})
        total += queryset.count()
        return queryset.order_by('-' + date_field, '-pk')[:maximum] if maximum != 0 else ()

    if kind in (None, 'outsourcing', 'metal_original'):
        orders = _regular(request, key)
        handoffs = _handoffs(request)
        if pk:
            orders = orders.filter(pk=pk)
            handoffs = handoffs.filter(original_order_id=pk)
        if key == 'dispatch' and kind != 'metal_original':
            dispatches = OutsourcingDispatch.objects.filter(order__in=orders).select_related(
                'order__schedule__production_task').prefetch_related('lines__unit', 'lines__material_item__allocation__factory')
            for dispatch in selected(dispatches, 'dispatch_date'):
                lines = list(dispatch.lines.all())
                factories = {line.material_item.allocation.factory.name for line in lines}
                parts = []
                for line in lines:
                    material = line.material_item.material_snapshot
                    name = material.get('material_name') or material.get('name') or '材料'
                    if line.issued_piece_count is not None:
                        amount, unit = line.issued_piece_count, '支'
                    else:
                        amount = line.material_quantity if line.material_quantity is not None else line.issued_quantity
                        unit = line.unit.unit_name
                    parts.append(f'{name} {number(amount)} {unit}')
                records.append(event(dispatch, 'outsourcing', dispatch.order.order_number,
                                     dispatch.order.schedule.production_task.task_number, dispatch.dispatch_date,
                                     dispatch.dispatch_number, '、'.join(sorted(factories)), '、'.join(parts)))
        elif key == 'returns':
            # 金工直接交接只读取可归属到授权来源的回货行。
            scopes = []
            if kind != 'metal_original':
                scopes.append(('outsourcing', OutsourcingReturnLine.objects.filter(return_record__order__in=orders)))
            if kind != 'outsourcing':
                scopes.append(('metal_original', _metal_receipts(handoffs)))
            for label, scoped_lines in scopes:
                receipts = OutsourcingReturn.objects.filter(pk__in=scoped_lines.values('return_record_id')).select_related(
                    'order__schedule__production_task', 'factory').prefetch_related(Prefetch(
                        'lines', queryset=scoped_lines.select_related('allocation__processing_item'), to_attr='visible_lines'))
                for receipt in selected(receipts, 'return_date'):
                    parts = []
                    for line in receipt.visible_lines:
                        item = line.allocation.processing_item
                        name = item.component_snapshot.get('part_name') or '加工件'
                        parts.append(f'{name} {number(line.returned_quantity)} {item.unit_snapshot}')
                    factory = receipt.factory_snapshot.get('name') or (receipt.factory.name if receipt.factory_id else '')
                    records.append(event(receipt, label, receipt.order.order_number,
                                         receipt.order.schedule.production_task.task_number, receipt.return_date,
                                         receipt.return_number, factory, '、'.join(parts)))
    if kind in (None, 'rework'):
        reworks = _reworks(request, key)
        if pk:
            reworks = reworks.filter(pk=pk)
        send = key == 'dispatch'
        model = MetalProcessingExternalHandoff if send else MetalProcessingExternalGoodReturn
        date_field = 'handoff_date' if send else 'return_date'
        movements = model.objects.filter(order__in=reworks).select_related(
            'order__source__issue_line__issue__production_task', 'order__factory')
        for movement in selected(movements, date_field):
            order = movement.order
            name = order.source.source_snapshot.get('part_name') or '重加工件'
            pieces = movement.handoff_pieces if send else movement.good_pieces
            voucher = order.order_number if send else movement.return_number
            records.append(event(movement, 'rework', order.order_number, order.source.issue_line.issue.production_task.task_number,
                                 getattr(movement, date_field), voucher, order.factory.name, f'{name} {pieces} 支'))
    return total, records
