"""委外总单的累计口径；实际收发记录是权威来源，计划数量不占库存。"""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.access_control import module_policy
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import WarehouseZone

from .models import TubeOutsourcingLine, TubePlanReceiptLine
from .tube_kinds import CUTTING_SOURCES
from .tube_selectors import (CANCEL_PERMISSION, DISPATCH_PERMISSION, RETURN_PERMISSION,
                            require_saved_order_access, source_factories)


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
    result = {}
    for order in orders:
        rows, target, planned, dispatched, returned, covered = {}, 0, 0, 0, 0, 0
        for line in order.lines.all():
            bom = int(Decimal(str(line.snapshot['order_required'])))
            outgoing = sent.get((str(order.pk), str(line.component_identity)), 0)
            incoming = received.get(str(line.pk), 0)
            rows[str(line.pk)] = {'bom_quantity': str(bom), 'dispatched_quantity': str(outgoing),
                'received_quantity': str(incoming), 'receivable_quantity': str(max(outgoing-incoming, 0))}
            target += bom
            planned += line.quantity
            dispatched += outgoing
            returned += incoming
            covered += min(bom, incoming)
        result[str(order.pk)] = {'lines': rows, 'summary': {'bom_quantity': str(target),
            'planned_quantity': str(planned), 'dispatched_quantity': str(dispatched),
            'received_quantity': str(returned), 'dispatch_progress': float(Decimal(dispatched)*100/target) if target else 0,
            'receipt_progress': float(Decimal(covered)*100/target) if target else 0}}
    return result


def plan_purchase_references(order):
    from .plan_purchase_reference import add_plan_purchase_reference
    context = {'source_kind': order.source_kind, 'rows': [
        {'id': str(line.pk), 'bom_line_id': str(line.bom_line_id)} for line in order.lines.all()]}
    add_plan_purchase_reference(context, order.schedule_product)
    return {row['id']: row['purchase_reference'] for row in context['rows']}


def plan_detail_data(order, data, request):
    quantities = plan_quantities([order])[str(order.pk)]
    purchases = plan_purchase_references(order)
    data.update(is_plan=True, plan_summary=quantities['summary'])
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
                permissions[field] = field != 'can_cancel' or not order.dispatch_batches.exists()
    permissions.update(can_correct_dispatch=permissions['can_dispatch'], can_correct_receive=permissions['can_receive'])
    data['permissions'] = permissions
    from .tube_materials import material_data
    batches = order.dispatch_batches.filter(status__in=['PROCESSING', 'COMPLETED'], actions__kind='DISPATCH').select_related('zone').prefetch_related('lines', 'materials__order_line', 'actions__actor_employee')
    data['dispatch_records'] = []
    for batch in batches:
        dispatch = next(record for record in batch.actions.all() if record.kind == 'DISPATCH')
        data['dispatch_records'].append({'id': str(batch.pk), 'order_number': batch.order_number,
            'client_request_id': str(batch.client_request_id), 'actual_dispatch_date': str(dispatch.actual_dispatch_date),
            'created_at': dispatch.created_at.isoformat(), 'actor_name': dispatch.actor_employee.display_name,
            'source_kind': batch.source_kind, 'zone_name': batch.zone.zone_name if batch.zone else '',
            'total_quantity': str(sum(line.quantity for line in batch.lines.all())),
            'materials': [material_data(value) for value in batch.materials.all()],
            'lines': [{'component_identity': str(line.component_identity), 'quantity': str(line.quantity),
                'factory_id': str(line.factory_id), 'factory_name': line.snapshot.get('factory_name', ''),
                'unit_price': str(line.unit_price) if line.unit_price is not None else None} for line in batch.lines.all()]})
    data['receipt_records'] = []
    for receipt in order.plan_receipts.filter(voided_at__isnull=True).select_related('warehouse', 'actor_employee').prefetch_related('lines__order_line', 'lines__zone'):
        data['receipt_records'].append({'id': str(receipt.pk), 'receipt_number': receipt.receipt_number,
            'client_request_id': str(receipt.client_request_id), 'receipt_date': str(receipt.receipt_date),
            'created_at': receipt.created_at.isoformat(), 'actor_name': receipt.actor_employee.display_name, 'remark': receipt.remark,
            'warehouse_id': str(receipt.warehouse_id), 'warehouse_name': receipt.warehouse.warehouse_name,
            'total_received_quantity': str(sum(line.received_quantity for line in receipt.lines.all())),
            'lines': [{'order_line_id': str(line.order_line_id), 'component_identity': str(line.order_line.component_identity),
                'received_quantity': str(line.received_quantity), 'zone_id': str(line.zone_id), 'zone_name': line.zone.zone_name} for line in receipt.lines.all()]})
    if request is not None:
        from .tube_selectors import SOURCE_LABELS
        zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE').select_related('warehouse')
        kinds = ['PUBLIC_CUTTING', 'SEWING'] if order.source_kind in CUTTING_SOURCES else ['RAW_PIPE', 'PUBLIC_SEMI', 'METAL']
        data['plan_options'] = {'source_kinds': [{'value': value, 'label': SOURCE_LABELS[value]} for value in kinds],
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
    can_receive = data['permissions']['can_receive'] and any(int(line['receivable_quantity']) > 0 for line in data['lines'])
    return {'order': data, 'etag': etag_for_instance(order), 'can_receive': can_receive,
        'blockers': [] if can_receive else ['当前没有可入库数量或无回货确认权限。'],
        'actor_name': request.employee.display_name, 'today': str(timezone.localdate()),
        'warehouses': list(warehouses.values()), 'zones': [{'id': str(zone.pk), 'warehouse_id': str(zone.warehouse_id),
            'warehouse': zone.warehouse.warehouse_name, 'name': zone.zone_name} for zone in zones], 'receipt': None}
