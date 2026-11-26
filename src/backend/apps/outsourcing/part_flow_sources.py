"""部位总单与裁片投入；实物数量保持各自单位，不推算齐套产量。"""
from decimal import Decimal
from copy import deepcopy

from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.boms.component_parts import required_component_quantity
from apps.boms.component_sources import component_source_materials
from apps.inventory.part_flow_quantities import first_output_available
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.material_issues.models import MaterialIssue, MaterialIssueLine
from apps.material_issues.public_issue_services import public_issue_quantity_context, _pool
from apps.reference_data.models import ProductionUnit

from .services import _json_hash
from .tube_services import _json


def uses_part_flow(product_id, source_kind):
    return source_kind in {'CUTTING', 'PUBLIC_PIECE', 'PUBLIC_PART', 'PROCESSOR'} or (
        source_kind == 'SEWING' and BomLine.objects.filter(section__bom__product_line_id=product_id,
            section__bom__archived_at__isnull=True, component_kind='SEWN_PART').exists())


def _part_stock_by_zone(product_line, rows):
    if not rows:
        return
    issue = MaterialIssue(production_task_id=product_line.production_task_id,
        product_line_id=product_line.pk, stock_mode='PUBLIC_V2')
    lines = [MaterialIssueLine(id=row['bom_line_id'], issue=issue, line_type='SEMI',
        unit_id=row['input_identity']['unit_id'], requested_quantity=1,
        conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': row['input_identity']}) for row in rows]
    quantities = public_issue_quantity_context(issue, lines=lines)
    for row, line in zip(rows, lines):
        pool = _pool(line)
        pool_free = quantities['stock'][pool] - quantities['pending_stock'][pool]
        by_zone = {}
        for balance in quantities['balances'][pool]:
            reserved = quantities['tube_reserved_by_zone'].get((pool, str(balance.zone_id)), Decimal(0))
            available = max(min(balance.quantity - reserved, pool_free), Decimal(0))
            by_zone[balance.zone_id] = (balance.quantity, available)
        yield row, by_zone


def add_cut_piece_stock_zones(schedule_product, plan, inputs):
    targets = {piece['component_identity']: quantity * piece['pieces_per_part']
        for quantity, snapshot in plan.lines.values_list('quantity', 'snapshot') for piece in snapshot.get('pieces', [])}
    short_rows = [row for row in inputs if not row['blockers']
        and Decimal(row['max_quantity']) < targets.get(row['component_identity'], 0)]
    for row, by_zone in _part_stock_by_zone(schedule_product.product_line, short_rows):
        if row.get('screen_print_required'):
            limit = Decimal(row['printed_available_quantity'])
            by_zone = {key: (total, min(free, limit)) for key, (total, free) in by_zone.items()}
        row['stock_zones'] = [{'zone_id': str(zone_id), 'available_quantity': str(available)}
            for zone_id, (_, available) in by_zone.items() if available > 0]


def part_source_context(*, schedule_product, source_kind, zone, craft, for_plan=False, request=None):
    sewing = craft.outsourcing_code == 'SEWING'
    if craft.outsourcing_code == 'SCREEN_PRINTING' and source_kind in {'CUTTING', 'PUBLIC_PIECE'}:
        from .printed_pieces import screen_print_context
        return screen_print_context(product_line=schedule_product.product_line, source_kind=source_kind,
            zone=zone, craft=craft, for_plan=for_plan)
    if source_kind == 'PROCESSOR' and (for_plan or request is None):
        raise ValidationError({'source_kind': '加工点发出仅用于仓库登记车缝总单的实际交接。'})
    if (sewing and source_kind not in {'CUTTING', 'PUBLIC_PIECE', 'PROCESSOR'}) or (
            not sewing and (craft.outsourcing_code not in {'SCREEN_PRINTING', 'EMBROIDERY'}
                           or source_kind not in {'SEWING', 'PUBLIC_PART'})):
        raise ValidationError({'source_kind': '车缝请选择裁片来源；丝印、刺绣请选择车缝部位来源。'})
    bom = Bom.objects.filter(product_line_id=schedule_product.product_line_id, archived_at__isnull=True).order_by('-version_number', '-pk').first()
    blockers = []
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != schedule_product.product_line.quantity:
        blockers.append('请先确认与当前订单数量一致的最新 BOM。')
    parents = list(BomLine.objects.filter(section__bom=bom, component_kind='SEWN_PART')
        .select_related('section__bom', 'fabric_source_line__section').prefetch_related('cut_pieces__fabric_source_line__section')) if bom else []
    rows, inputs = [], []
    for parent in parents:
        row = {'component_identity': str(parent.component_identity), 'bom_line_id': str(parent.pk),
            'part_name': parent.part_name, 'unit': parent.unit,
            'material': '',
            'specification': parent.specification,
            'component_source_materials': [],
            'component_material_selection_snapshot': deepcopy(parent.material_selection_snapshot or {}),
            'order_required': str(required_component_quantity(parent, bom.order_quantity)),
            'stock_quantity': None, 'max_quantity': '0', 'blockers': list(blockers), 'input_identity': {}, 'snapshot': {}}
        rows.append(row)
        try:
            row['component_source_materials'] = component_source_materials(parent)
            unit = ProductionUnit.objects.get(unit_name=parent.unit, status='ACTIVE', archived_at__isnull=True)
            output = build_semi_finished_identity(bom_line=parent, completed_craft=craft, unit=unit)
            row['snapshot'] = {'public_output_identity': output, 'part_flow': True, 'unit': parent.unit,
                'component_material_selection_snapshot': row['component_material_selection_snapshot'],
                'component_source_materials': row['component_source_materials'],
                'component_kind': 'SEWN_PART', 'pieces': []}
            if sewing:
                for piece in parent.cut_pieces.all():
                    piece_unit = ProductionUnit.objects.get(unit_name=piece.unit, status='ACTIVE', archived_at__isnull=True)
                    identity = build_semi_finished_identity(bom_line=piece,
                        completed_craft=component_stock_craft('CUTTING'), unit=piece_unit)
                    frozen = {'component_identity': str(piece.component_identity), 'bom_line_id': str(piece.pk),
                        'parent_component_identity': str(parent.component_identity), 'parent_name': parent.part_name,
                        'part_name': piece.part_name, 'specification': piece.specification, 'unit': piece.unit,
                        'component_material_selection_snapshot': deepcopy(piece.material_selection_snapshot or {}),
                        'component_source_materials': component_source_materials(piece),
                        'pieces_per_part': piece.pieces_per_part, 'input_identity': identity}
                    row['snapshot']['pieces'].append(frozen)
                    inputs.append({**frozen, 'order_required': str(required_component_quantity(piece, bom.order_quantity)),
                        'max_quantity': '0', 'stock_quantity': None, 'blockers': [], '_line': piece})
            else:
                row['input_identity'] = build_semi_finished_identity(bom_line=parent,
                    completed_craft=component_stock_craft('SEWING'), unit=unit)
            row['max_quantity'] = row['order_required']
        except (ValidationError, ProductionUnit.DoesNotExist) as error:
            row['blockers'].append(str(getattr(error, 'detail', error)))
    candidates = inputs if sewing else rows
    from .printed_pieces import printed_pieces_for_sewing, processor_sources
    printed = printed_pieces_for_sewing(schedule_product.product_line_id) if sewing and not for_plan else {}
    at_processor = processor_sources(schedule_product.product_line_id, request) if source_kind == 'PROCESSOR' else {}
    by_id = {str(row.pk): row for row in parents}
    stock_rows = []
    for row in candidates:
        line = row.pop('_line', None) or by_id[row['bom_line_id']]
        if row['blockers']:
            continue
        if row['component_identity'] in printed:
            identity, free = printed[row['component_identity']]
            row.update(input_identity=identity, screen_print_required=True, printed_available_quantity=str(free))
            if source_kind == 'PROCESSOR':
                source = at_processor.get(row['component_identity'])
                if source:
                    row.update(processor_source=source, max_quantity=source['available_quantity'])
            elif zone:
                stock_rows.append(row)
            continue
        if source_kind == 'PROCESSOR':
            continue
        if source_kind in {'CUTTING', 'SEWING'}:
            row['max_quantity'] = str(first_output_available(schedule_product.product_line_id, line, bom.order_quantity))
        elif row['input_identity']:
            stock_rows.append(row)
    for row, by_zone in _part_stock_by_zone(schedule_product.product_line, stock_rows):
        amount, available = by_zone.get(zone.pk, (Decimal(0), Decimal(0)))
        if row.get('screen_print_required'):
            available = min(available, Decimal(row['printed_available_quantity']))
        row['stock_quantity'] = str(amount)
        row['max_quantity'] = str(available)
    if for_plan:
        for row in rows:
            row['max_quantity'] = row['order_required'] if not row['blockers'] else '0'
    context = {'part_flow': True, 'sewing_inputs': sewing, 'fees_deferred': False,
        'billing_basis': 'PART_RECEIPT', 'rows': rows,
        'inputs': inputs, 'blockers': blockers, 'ready': not blockers and any(not row['blockers'] for row in rows),
        'bom_id': str(bom.pk) if bom else None, 'source_kind': source_kind, 'craft_id': str(craft.pk)}
    context['source_revision'] = _json_hash(_json(context))
    return context


def input_dispatched(plan):
    from .models import TubeOutsourcingInput
    return {str(row['component_identity']): row['total'] for row in TubeOutsourcingInput.objects.filter(
        order__plan=plan, order__status__in=['PROCESSING', 'COMPLETED'])
        .values('component_identity').annotate(total=Sum('quantity'))}
