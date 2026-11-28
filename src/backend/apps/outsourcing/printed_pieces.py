"""裁片丝印总单的原裁片、回货身份及后续车缝实际可用量。"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.component_parts import required_component_quantity
from apps.boms.component_sources import component_source_materials
from apps.boms.models import Bom, BomLine
from apps.inventory.part_flow_quantities import first_output_available
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.reference_data.models import ProductionUnit

from .models import TubeOutsourcingInput, TubeOutsourcingLine
from .services import _json_hash
from .tube_services import _json


def planned_print_lines(product_line_id):
    return TubeOutsourcingLine.objects.filter(
        order__is_plan=True, order__product_line_id=product_line_id, order__source_snapshot__screen_print_pieces=True,
    ).exclude(order__status='CANCELLED')


def processor_transfer_quantities(print_order_ids):
    return dict(TubeOutsourcingInput.objects.filter(
        print_order_line__order_id__in=print_order_ids, order__status__in=['PROCESSING', 'COMPLETED'],
    ).values('print_order_line_id').annotate(total=Sum('quantity')).values_list('print_order_line_id', 'total'))


def _reported_cut_pieces(product_line_id):
    from apps.workshop_reporting.models import WageSchemeLine, WorkReportLine
    today = timezone.localdate()
    lines = list(WageSchemeLine.objects.filter(scheme__product_line_id=product_line_id,
        scheme__scope_craft__plan_category='CUTTING', scheme__status__in=['APPROVED', 'SUPERSEDED'],
        status='ACTIVE').select_related('work_item', 'scheme'))
    groups = {}
    if any(line.counting_mode == 'GROUP' for line in lines):
        # 单裁片报工的旧版本没有组明细表，也不会保存 GROUP 记录。
        from apps.workshop_reporting.models import WageSchemeLineCuttingGroup
        groups = dict(WageSchemeLineCuttingGroup.objects.filter(line__in=lines).values_list('line_id', 'components'))
    reports = dict(WorkReportLine.objects.filter(scheme_line_id__in=[row.pk for row in lines],
        report__production_date__lte=today).values('scheme_line_id').annotate(total=Sum('quantity'))
        .values_list('scheme_line_id', 'total'))
    totals = defaultdict(lambda: defaultdict(Decimal))
    for line in lines:
        if line.pk not in reports and (line.scheme.status != 'APPROVED' or
                line.scheme.effective_from > today or (line.scheme.effective_to and line.scheme.effective_to < today)):
            continue
        if line.counting_mode == 'GROUP':
            components = [(entry['component_identity'], entry['quantity_per_group']) for entry in groups.get(line.pk, [])]
        elif line.bom_component_kind_snapshot == 'CUT_PIECE' and line.counting_mode == 'PIECE':
            components = [(str(line.bom_component_identity_snapshot), 1)]
        else:
            continue
        for key, per_count in components:
            totals[key][line.work_item.operation_id] += reports.get(line.pk, 0) * Decimal(per_count)
    # 同一片经过多个裁剪工序时不能重复计数；逐道工序都完成的数量才能直发。
    return {key: int(min(quantities.values())) for key, quantities in totals.items()}


def cut_print_direct_available(product_line_id, line, order_quantity, *, reported=None):
    if reported is None:
        reported = _reported_cut_pieces(product_line_id)
    required = required_component_quantity(line, order_quantity)
    remaining = first_output_available(product_line_id, line, order_quantity)
    used = required - remaining
    return max(0, min(required, reported.get(str(line.component_identity), 0)) - used)


def printed_pieces_for_sewing(product_line_id):
    lines = list(planned_print_lines(product_line_id).values('component_identity', 'snapshot', 'pk'))
    if not lines:
        return {}
    from .models import TubePlanReceiptLine
    received = dict(TubePlanReceiptLine.objects.filter(order_line_id__in=[line['pk'] for line in lines],
        receipt__voided_at__isnull=True).values('order_line_id').annotate(total=Sum('received_quantity'))
        .values_list('order_line_id', 'total'))
    sent = dict(TubeOutsourcingInput.objects.filter(order__product_line_id=product_line_id,
        order__status__in=['PROCESSING', 'COMPLETED'], source_kind='PUBLIC_PIECE', snapshot__screen_print_required=True)
        .values('component_identity').annotate(total=Sum('quantity')).values_list('component_identity', 'total'))
    return {str(line['component_identity']): (
        line['snapshot']['public_output_identity'], max(received.get(line['pk'], 0) - sent.get(line['component_identity'], 0), 0)
    ) for line in lines}


def processor_sources(product_line_id, request):
    from .models import TubeOutsourcingOrder
    from .plan_selectors import plan_quantities
    from .tube_selectors import DISPATCH_PERMISSION, saved_orders_for_permission
    allowed = saved_orders_for_permission(request, DISPATCH_PERMISSION)
    plans = TubeOutsourcingOrder.objects.filter(pk__in=allowed.values('pk'),
        product_line_id=product_line_id, is_plan=True, source_snapshot__screen_print_pieces=True,
    ).exclude(status='CANCELLED').prefetch_related('lines__factory')
    quantities = plan_quantities(plans)
    sources = {}
    for plan in plans:
        for line in plan.lines.all():
            sources[str(line.component_identity)] = {'order_id': str(plan.pk), 'order_number': plan.order_number,
                'order_line_id': str(line.pk), 'factory_id': str(line.factory_id),
                'factory_name': line.snapshot['factory_name'],
                'available_quantity': quantities[str(plan.pk)]['lines'][str(line.pk)]['receivable_quantity']}
    return sources


def processor_transfer_records(order):
    rows = TubeOutsourcingInput.objects.filter(print_order_line__order=order, source_kind='PROCESSOR',
        order__status__in=['PROCESSING', 'COMPLETED']).select_related('order__plan').prefetch_related(
        'order__actions__actor_employee').order_by('-order__created_at', 'order_id', 'pk')
    records = {}
    for row in rows:
        batch = row.order
        if batch.pk not in records:
            dispatch = next(action for action in batch.actions.all() if action.kind == 'DISPATCH')
            records[batch.pk] = {'id': str(batch.pk), 'order_number': batch.order_number,
                'actual_dispatch_date': str(dispatch.actual_dispatch_date), 'actor_name': dispatch.actor_employee.display_name,
                'sewing_plan_id': str(batch.plan_id), 'sewing_plan_number': batch.plan.order_number, 'lines': []}
        source = row.snapshot['processor_source']
        records[batch.pk]['lines'].append({'component_identity': str(row.component_identity),
            'part_name': row.snapshot['part_name'], 'unit': row.snapshot['unit'], 'quantity': str(row.quantity),
            'source_factory_id': source['factory_id'], 'source_factory_name': source['factory_name'],
            'factory_id': str(row.factory_id), 'factory_name': row.snapshot['factory_name']})
    return list(records.values())


def screen_print_context(*, product_line, source_kind, zone, craft, for_plan):
    from .part_flow_sources import _part_stock_by_zone
    bom = Bom.objects.filter(product_line=product_line, archived_at__isnull=True).order_by('-version_number', '-pk').first()
    blockers = []
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product_line.quantity:
        blockers.append('请先确认与订单数量一致的最新 BOM。')
    rows = []
    pieces = BomLine.objects.filter(section__bom=bom, component_kind='CUT_PIECE').select_related(
        'section__bom', 'parent_part', 'fabric_source_line__section').order_by('line_number', 'pk') if bom else []
    units = {unit.unit_name: unit for unit in ProductionUnit.objects.filter(status='ACTIVE', archived_at__isnull=True)}
    reported = _reported_cut_pieces(product_line.pk) if source_kind == 'CUTTING' and not for_plan else {}
    for piece in pieces:
        parent = piece.parent_part
        row = {'component_identity': str(piece.component_identity), 'bom_line_id': str(piece.pk),
            'parent_component_identity': str(parent.component_identity) if parent else None,
            'parent_name': parent.part_name if parent else '',
            'part_name': piece.part_name, 'specification': piece.specification, 'unit': piece.unit, 'material': '',
            'order_required': '0', 'max_quantity': '0', 'stock_quantity': None, 'blockers': list(blockers),
            'component_source_materials': [], 'component_material_selection_snapshot': piece.material_selection_snapshot or {},
            'input_identity': {}, 'snapshot': {}}
        rows.append(row)
        if row['blockers']:
            continue
        if piece.unit not in units:
            row['blockers'].append('裁片缺少启用的计数单位。')
            continue
        try:
            quantity = required_component_quantity(piece, bom.order_quantity)
            row['order_required'] = str(quantity)
            row['component_source_materials'] = component_source_materials(piece)
            row['input_identity'] = build_semi_finished_identity(bom_line=piece,
                completed_craft=component_stock_craft('CUTTING'), unit=units[piece.unit])
            printed = build_semi_finished_identity(bom_line=piece, completed_craft=craft, unit=units[piece.unit])
            row['snapshot'] = {'public_output_identity': printed, 'part_flow': True, 'screen_print_pieces': True,
                'component_kind': 'CUT_PIECE', 'parent_name': row['parent_name'], 'unit': piece.unit,
                'component_material_selection_snapshot': row['component_material_selection_snapshot'],
                'component_source_materials': row['component_source_materials']}
        except ValidationError as error:
            row['blockers'].append(str(error.detail))
            continue
        if for_plan:
            row['max_quantity'] = str(quantity)
        elif source_kind == 'CUTTING':
            row['max_quantity'] = str(cut_print_direct_available(product_line.pk, piece,
                bom.order_quantity, reported=reported))
    if zone and not for_plan:
        for row, by_zone in _part_stock_by_zone(product_line, [row for row in rows if not row['blockers']]):
            total, free = by_zone.get(zone.pk, (0, 0))
            row['stock_quantity'], row['max_quantity'] = str(total), str(free)
    context = {'part_flow': True, 'screen_print_pieces': True, 'sewing_inputs': False, 'fees_deferred': False,
        'billing_basis': 'PART_RECEIPT', 'rows': rows, 'inputs': [], 'blockers': blockers,
        'ready': not blockers and any(not row['blockers'] for row in rows), 'bom_id': str(bom.pk) if bom else None,
        'source_kind': source_kind, 'craft_id': str(craft.pk)}
    context['source_revision'] = _json_hash(_json(context))
    return context
