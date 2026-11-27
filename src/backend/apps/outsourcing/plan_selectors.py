"""委外总单的累计口径；实际收发记录是权威来源，计划数量不占库存。"""
from decimal import Decimal

from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.access_control import module_policy
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import WarehouseZone

from .models import TubeOutsourcingLine, TubeOutsourcingInput, TubePlanReceiptLine
from .tube_kinds import CUTTING_SOURCES
from .tube_prices import line_area_data, line_price_data
from .part_flow_prices import receipt_price_data, receipt_amount_summary
from .sewing_assignments import internal_sewing_assignment_in_use
from .component_source_snapshots import frozen_component_source_materials
from .tube_selectors import (CANCEL_PERMISSION, DISPATCH_PERMISSION, RETURN_PERMISSION,
                            require_saved_order_access, source_factories)
from .warehouse_access import warehouse_stage


def plan_quantities(orders):
    """一次读取一组已授权总单的收发量；部件超收不能抵消其他部件欠量。"""
    orders = list(orders)
    ids = [order.pk for order in orders]
    sent = {(str(row['order__plan_id']), str(row['component_identity'])): row['total']
            for row in TubeOutsourcingLine.objects.filter(order__plan_id__in=ids,
                order__is_plan=False, order__status__in=['PROCESSING', 'COMPLETED'],
                order__actions__kind='DISPATCH').values('order__plan_id', 'component_identity').annotate(total=Sum('quantity'))}
    received = {str(row['order_line_id']): row['total'] for row in TubePlanReceiptLine.objects.filter(
        receipt__order_id__in=ids, receipt__voided_at__isnull=True).values('order_line_id').annotate(total=Sum('received_quantity'))}
    print_ids = [order.pk for order in orders if order.source_snapshot.get('screen_print_pieces')]
    transferred = dict(TubeOutsourcingInput.objects.filter(print_order_line__order_id__in=print_ids,
        order__status__in=['PROCESSING', 'COMPLETED']).values('print_order_line_id')
        .annotate(total=Sum('quantity')).values_list('print_order_line_id', 'total')) if print_ids else {}
    input_plan_ids = [order.pk for order in orders if order.source_snapshot.get('sewing_inputs')]
    input_totals = {}
    if input_plan_ids:
        for row in (TubeOutsourcingInput.objects.filter(
                order__plan_id__in=input_plan_ids, order__status__in=['PROCESSING', 'COMPLETED'])
                .values('order__plan_id', 'snapshot__unit').annotate(total=Sum('quantity'))):
            totals = input_totals.setdefault(str(row['order__plan_id']), {})
            unit = row['snapshot__unit'] or '片'  # 旧裁片投入记录的缺省单位。
            totals[unit] = totals.get(unit, 0) + row['total']
    result = {}
    for order in orders:
        rows, target, planned, dispatched, returned, covered = {}, 0, 0, 0, 0, 0
        quantity_totals = {}
        for line in order.lines.all():
            bom = int(Decimal(str(line.snapshot['order_required'])))
            outgoing = sent.get((str(order.pk), str(line.component_identity)), 0)
            incoming = received.get(str(line.pk), 0)
            passed_on = transferred.get(line.pk, 0)
            outstanding = max(outgoing - incoming - passed_on, 0)
            rows[str(line.pk)] = {'bom_quantity': str(bom), 'dispatched_quantity': str(outgoing),
                'received_quantity': str(incoming), 'receivable_quantity': str(outstanding)}
            if order.pk in print_ids:
                rows[str(line.pk)]['transferred_quantity'] = str(passed_on)
            target += bom
            planned += line.quantity
            dispatched += outgoing
            returned += incoming
            covered += min(bom, incoming + passed_on)
            unit = line.snapshot.get('unit') or ('套' if order.source_kind in CUTTING_SOURCES else '支')
            totals = quantity_totals.setdefault(unit, {'unit': unit, 'bom_quantity': 0, 'planned_quantity': 0,
                'dispatched_quantity': 0, 'received_quantity': 0})
            for field, value in [('bom_quantity', bom), ('planned_quantity', line.quantity),
                                 ('dispatched_quantity', outgoing), ('received_quantity', incoming)]:
                totals[field] += value
            if order.pk in print_ids:
                totals['transferred_quantity'] = totals.get('transferred_quantity', 0) + passed_on
                totals['receivable_quantity'] = totals.get('receivable_quantity', 0) + outstanding
        input_units = input_totals.get(str(order.pk), {})
        if order.source_snapshot.get('sewing_inputs'):
            for line in order.lines.all():
                for piece in line.snapshot.get('pieces', []):
                    input_units.setdefault(piece.get('unit') or '片', 0)
            # 异单位投入没有可比较的总数；逐单位汇总才是展示及状态判断依据。
            dispatched = next(iter(input_units.values()), 0) if len(input_units) <= 1 else None
        result[str(order.pk)] = {'lines': rows, 'summary': {'bom_quantity': str(target),
            'planned_quantity': str(planned), 'dispatched_quantity': str(dispatched) if dispatched is not None else None,
            'received_quantity': str(returned), 'dispatch_progress': None if order.source_snapshot.get('sewing_inputs') else (float(Decimal(dispatched)*100/target) if target else 0),
            'input_totals': [{'unit': unit, 'dispatched_quantity': str(quantity)} for unit, quantity in input_units.items()],
            'receipt_progress': float(Decimal(covered)*100/target) if target else 0,
            'quantity_totals': [{key: str(value) if key != 'unit' else value for key, value in row.items()}
                                for row in quantity_totals.values()]}}
        if order.pk in print_ids:
            result[str(order.pk)]['summary'].update({
                field: str(sum(row[field] for row in quantity_totals.values()))
                for field in ('transferred_quantity', 'receivable_quantity')})
    return result


def plan_purchase_references(order):
    from .plan_purchase_reference import add_plan_purchase_reference
    context = {'source_kind': order.source_kind, 'rows': [
        {'id': str(line.pk), 'bom_line_id': str(line.bom_line_id)} for line in order.lines.all()]}
    add_plan_purchase_reference(context, order.product_line)
    return {row['id']: row['purchase_reference'] for row in context['rows']}


def _can_view_sewing_assignment(order, request):
    permission = 'outsourcing.view_outsourcingorder'
    if request is None or warehouse_stage(request) or not module_policy.has_permission(request, permission):
        return False
    try:
        require_saved_order_access(request, order, permission)
    except (PermissionDenied, Http404):
        return False
    return True


def _internal_sewing_details(source_snapshot, parts):
    rows = {row['component_identity']: row for row in source_snapshot.get('rows', [])}
    details = []
    for part in parts:
        row = rows.get(part['component_identity'], {})
        snapshot = {**row.get('snapshot', {}), **row}
        details.append({**part, 'specification': snapshot.get('specification') or '',
            'component_material_selection_snapshot': snapshot.get('component_material_selection_snapshot', {}),
            'component_source_materials': frozen_component_source_materials(snapshot),
            # 本厂承接整个部位，保存时已校验计划量等于该部位的 BOM 需求。
            'bom_quantity': str(part['quantity'])})
    return details


def plan_detail_data(order, data, request):
    quantities = plan_quantities([order])[str(order.pk)]
    purchases = plan_purchase_references(order)
    data.update(is_plan=True, plan_summary=quantities['summary'],
        part_flow=bool(order.source_snapshot.get('part_flow')),
        screen_print_pieces=bool(order.source_snapshot.get('screen_print_pieces')),
        sewing_inputs=bool(order.source_snapshot.get('sewing_inputs')),
        fees_deferred=bool(order.source_snapshot.get('fees_deferred')),
        billing_basis=order.source_snapshot.get('billing_basis'))
    data['inputs'] = []
    assignment = order.source_snapshot.get('sewing_part_assignments')
    if assignment is not None and _can_view_sewing_assignment(order, request):
        data['internal_sewing_parts'] = _internal_sewing_details(order.source_snapshot, assignment['internal'])
    if data['sewing_inputs']:
        from .part_flow_sources import input_dispatched
        from .printed_pieces import printed_pieces_for_sewing
        sent = input_dispatched(order)
        printed = printed_pieces_for_sewing(order.product_line_id)
        for line in order.lines.all():
            for piece in line.snapshot.get('pieces', []):
                data['inputs'].append({key: value for key, value in piece.items() if key != 'input_identity'} | {
                    **({'screen_print_required': True, 'printed_available_quantity': str(printed[piece['component_identity']][1])}
                       if piece['component_identity'] in printed else {}),
                    'component_source_materials': frozen_component_source_materials(piece),
                    'target_quantity': str(line.quantity * piece['pieces_per_part']),
                    'dispatched_quantity': str(sent.get(piece['component_identity'], 0)),
                    'factory_id': str(line.factory_id), 'factory_name': line.snapshot.get('factory_name', '')})
    for line in data['lines']:
        line.update(quantities['lines'][line['id']])
        line['purchase_reference'] = purchases[line['id']]
    permissions = {'can_dispatch': False, 'can_receive': False, 'can_cancel': False, 'can_edit_quantity': False}
    if request is not None and order.status != 'CANCELLED':
        for field, permission in [('can_dispatch', DISPATCH_PERMISSION), ('can_receive', RETURN_PERMISSION), ('can_cancel', CANCEL_PERMISSION),
                                  ('can_edit_quantity', 'outsourcing.change_outsourcingorder')]:
            if module_policy.has_permission(request, permission):
                try:
                    require_saved_order_access(request, order, permission)
                except APIException:
                    continue
                permissions[field] = field != 'can_cancel' or (not order.dispatch_batches.exists()
                    and (assignment is None or (order.status == 'PENDING_DISPATCH' and not internal_sewing_assignment_in_use(order))))
    if assignment is not None and not assignment['has_external']:
        permissions.update(can_dispatch=False, can_receive=False, can_edit_quantity=False)
    permissions.update(can_correct_dispatch=permissions['can_dispatch'], can_correct_receive=permissions['can_receive'])
    data['permissions'] = permissions
    from .tube_materials import material_data
    batches = order.dispatch_batches.filter(status__in=['PROCESSING', 'COMPLETED'], actions__kind='DISPATCH').select_related('zone').prefetch_related('lines', 'materials__order_line', 'actions__actor_employee')
    data['dispatch_records'] = []
    for batch in batches:
        dispatch = next(record for record in batch.actions.all() if record.kind == 'DISPATCH')
        batch_lines = list(batch.inputs.all() if batch.source_snapshot.get('sewing_inputs') else batch.lines.all())
        data['dispatch_records'].append({'id': str(batch.pk), 'order_number': batch.order_number,
            'client_request_id': str(batch.client_request_id), 'actual_dispatch_date': str(dispatch.actual_dispatch_date),
            'created_at': dispatch.created_at.isoformat(), 'actor_name': dispatch.actor_employee.display_name,
            'source_kind': batch.source_kind, 'zone_name': batch.zone.zone_name if batch.zone else '',
            'total_quantity': str(sum(line.quantity for line in batch_lines)),
            'materials': [material_data(value) for value in batch.materials.all()],
            'lines': [{'component_identity': str(line.component_identity), 'quantity': str(line.quantity),
                'factory_id': str(line.factory_id), 'factory_name': line.snapshot.get('factory_name', ''),
                **({'processor_source': line.snapshot['processor_source']} if batch.source_kind == 'PROCESSOR' else {}),
                'part_name': line.snapshot.get('part_name', ''), 'unit': line.snapshot.get('unit'),
                'specification': line.snapshot.get('specification', ''),
                'component_material_selection_snapshot': line.snapshot.get('component_material_selection_snapshot', {}),
                'component_source_materials': frozen_component_source_materials(line.snapshot, line.input_identity),
                **({ 'unit_price': None, 'planned_amount': None } if batch.source_snapshot.get('sewing_inputs')
                   else {**line_area_data(line), **line_price_data(line)})} for line in batch_lines]})
    data['receipt_records'] = []
    all_receipt_lines = []
    for receipt in order.plan_receipts.filter(voided_at__isnull=True).select_related('warehouse', 'actor_employee').prefetch_related('lines__order_line', 'lines__zone'):
        receipt_lines = list(receipt.lines.all())
        all_receipt_lines.extend(receipt_lines)
        data['receipt_records'].append({'id': str(receipt.pk), 'receipt_number': receipt.receipt_number,
            'client_request_id': str(receipt.client_request_id), 'receipt_date': str(receipt.receipt_date),
            'created_at': receipt.created_at.isoformat(), 'actor_name': receipt.actor_employee.display_name, 'remark': receipt.remark,
            'warehouse_id': str(receipt.warehouse_id), 'warehouse_name': receipt.warehouse.warehouse_name,
            'total_received_quantity': str(sum(line.received_quantity for line in receipt.lines.all())),
            **(receipt_amount_summary(receipt_lines) if data['part_flow'] else {}),
            'lines': [{'order_line_id': str(line.order_line_id), 'component_identity': str(line.order_line.component_identity),
                'unit': line.snapshot.get('unit'),
                'part_name': line.snapshot.get('part_name'), 'specification': line.snapshot.get('specification'),
                'component_material_selection_snapshot': line.snapshot.get('component_material_selection_snapshot', {}),
                'component_source_materials': frozen_component_source_materials(line.snapshot),
                **(receipt_price_data(line) if data['part_flow'] else {}),
                'received_quantity': str(line.received_quantity), 'zone_id': str(line.zone_id), 'zone_name': line.zone.zone_name} for line in receipt_lines]})
    if data['part_flow']:
        data['plan_summary'].update(receipt_amount_summary(all_receipt_lines))
        for line in data['lines']:
            line.update(receipt_amount_summary(row for row in all_receipt_lines if str(row.order_line_id) == line['id']))
    if data['screen_print_pieces']:
        from .printed_pieces import processor_transfer_records
        data['transferred_records'] = processor_transfer_records(order)
    if request is not None:
        from .source_access import allowed_source_kinds
        from .tube_selectors import SOURCE_LABELS
        allowed = allowed_source_kinds(request, DISPATCH_PERMISSION)
        zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE').select_related('warehouse')
        kinds = ['PUBLIC_CUTTING', 'SEWING'] if order.source_kind in CUTTING_SOURCES else ['METAL', 'PUBLIC_SEMI']
        if data['part_flow']:
            kinds = ['CUTTING', 'PUBLIC_PIECE'] if data['sewing_inputs'] or data['screen_print_pieces'] else ['PUBLIC_PART', 'SEWING']
            if data['sewing_inputs'] and permissions['can_dispatch'] and 'PROCESSOR' in allowed:
                from .printed_pieces import processor_sources
                sources = processor_sources(order.product_line_id, request)
                if any(int(sources[row['component_identity']]['available_quantity']) > 0
                       for row in data['inputs'] if row['component_identity'] in sources):
                    kinds.append('PROCESSOR')
        data['plan_options'] = {'per_line_sources': True,
            'source_kinds': [{'value': value, 'label': SOURCE_LABELS[value]} for value in kinds if value in allowed],
            'factories': [{'id': str(value.pk), 'name': value.name} for value in source_factories(request, order.craft, DISPATCH_PERMISSION)],
            'zones': [{'id': str(zone.pk), 'name': zone.zone_name, 'warehouse_id': str(zone.warehouse_id),
                'warehouse_name': zone.warehouse.warehouse_name, 'warehouse_type': zone.warehouse.warehouse_type} for zone in zones]}
    data['planned_materials'] = order.source_snapshot.get('planned_materials', [])
    return data


def plan_receipt_preview(order, request):
    from .tube_selectors import saved_order_data
    from .tube_receipt_selectors import require_receipt_read_access
    require_receipt_read_access(request, order)
    data = saved_order_data(order, request=request, include_metal_basis=False)
    zones = list(WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type='SEMI_FINISHED').select_related('warehouse').order_by('warehouse_id', 'zone_name', 'pk'))
    warehouses = {str(zone.warehouse_id): {'id': str(zone.warehouse_id), 'name': zone.warehouse.warehouse_name} for zone in zones}
    can_receive = data['permissions']['can_receive'] and bool(data['lines'])
    return {'order': data, 'etag': etag_for_instance(order), 'can_receive': can_receive,
        'blockers': [] if can_receive else ['当前总单没有入库部件或无回货确认权限。'],
        'actor_name': request.employee.display_name, 'today': str(timezone.localdate()),
        'warehouses': list(warehouses.values()), 'zones': [{'id': str(zone.pk), 'warehouse_id': str(zone.warehouse_id),
            'warehouse': zone.warehouse.warehouse_name, 'name': zone.zone_name} for zone in zones], 'receipt': None}
