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
    return source_kind in {'CUTTING', 'PUBLIC_PIECE', 'PUBLIC_PART'} or (
        source_kind == 'SEWING' and BomLine.objects.filter(section__bom__product_line_id=product_id,
            section__bom__archived_at__isnull=True, component_kind='SEWN_PART').exists())


def part_source_context(*, schedule_product, source_kind, zone, craft, for_plan=False):
    sewing = craft.outsourcing_code == 'SEWING'
    if (sewing and source_kind not in {'CUTTING', 'PUBLIC_PIECE'}) or (
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
    by_id = {str(row.pk): row for row in parents}
    issue = MaterialIssue(production_task_id=schedule_product.schedule.production_task_id,
        product_line_id=schedule_product.product_line_id, stock_mode='PUBLIC_V2')
    stock_lines = []
    for row in candidates:
        line = row.pop('_line', None) or by_id[row['bom_line_id']]
        if row['blockers']:
            continue
        if source_kind in {'CUTTING', 'SEWING'}:
            row['max_quantity'] = str(first_output_available(schedule_product.product_line_id, line, bom.order_quantity))
        elif row['input_identity']:
            stock_lines.append(MaterialIssueLine(id=line.pk, issue=issue, line_type='SEMI',
                unit_id=row['input_identity']['unit_id'], requested_quantity=1,
                conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': row['input_identity']}))
    if stock_lines:
        quantities = public_issue_quantity_context(issue, lines=stock_lines)
        by_line = {str(line.pk): line for line in stock_lines}
        for row in candidates:
            if row['bom_line_id'] not in by_line:
                continue
            pool = _pool(by_line[row['bom_line_id']])
            amount = sum((value.quantity for value in quantities['balances'][pool] if value.zone_id == zone.pk), Decimal(0))
            reserved = quantities['tube_reserved_by_zone'].get((pool, str(zone.pk)), Decimal(0))
            row['stock_quantity'] = str(amount)
            row['max_quantity'] = str(max(min(amount-reserved, quantities['stock'][pool]-quantities['pending_stock'][pool]), Decimal(0)))
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
