"""裁片来源适配；保存、发出、取消及回货继续共用现有外发单据。"""
from collections import Counter, defaultdict
from decimal import Decimal
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.stock_services import InventoryStockValidationError
from apps.inventory.tube_processing_quantities import whole_pieces, TubeQuantityError
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
from apps.material_issues.public_issue_services import public_issue_quantity_context, _lock_public_issue_stock, _pool
from apps.products.material_identity import lock_bom_line_material_identities
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft

from .models import TubeOutsourcingLine, OutsourcingProcessingItem
from .services import _json_hash
from .tube_kinds import CUTTING_CRAFT_CODES, CUTTING_SOURCES, lock_source_product, display_operations


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _build_context(*, schedule_product, source_kind, craft, zone=None, exclude_order_id=None):
    from apps.inventory.sewing_processing_services import sewing_component_limits
    # 锁等待期间订单或计划可能已变更，不沿用调用方预先加载的关联对象。
    schedule_product = ProductionScheduleProduct.objects.select_related('product_line', 'schedule').get(pk=schedule_product.pk)
    product = schedule_product.product_line
    blockers = []
    if source_kind not in CUTTING_SOURCES or craft.outsourcing_code not in CUTTING_CRAFT_CODES:
        raise ValidationError({'source_kind': '裁片来源与加工工艺不匹配。'})
    bom = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('-version_number', '-updated_at', '-pk').first()
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
        blockers.append('请先确认与当前订单数量一致的最新BOM。')
    unit = ProductionUnit.objects.filter(unit_name='套', status='ACTIVE', archived_at__isnull=True).first()
    sewing = Craft.objects.filter(craft_type='EXTERNAL', outsourcing_code='SEWING', status='ACTIVE').first()
    if not unit or not sewing:
        blockers.append('缺少有效套单位或车缝完成工艺。')
    lines = list(BomLine.objects.filter(section__bom=bom, section__section_type='FABRIC',
        section__title='裁剪明细').select_related('section__bom', 'fabric_source_line__section')) if bom else []
    if any(count != 1 for count in Counter(line.component_identity for line in lines).values()):
        blockers.append('BOM裁片部位编号重复，请先修正。')
    basis = sewing_component_limits(product, exclude_tube_order_id=exclude_order_id) if source_kind == 'SEWING' else None
    allocations = TubeOutsourcingLine.objects.filter(order__product_line=product,
        order__source_kind__in=CUTTING_SOURCES).exclude(order__status='CANCELLED')
    allocated = {str(row['component_identity']): row['total'] for row in
        allocations.values('component_identity').annotate(total=Sum('quantity'))}
    own_allocated = {str(row['component_identity']): row['total'] for row in
        allocations.filter(order_id=exclude_order_id).values('component_identity').annotate(total=Sum('quantity'))
    } if exclude_order_id else {}
    # 旧刺绣/丝印单继续占后加工额度；旧裁剪/车缝属于首次产出，不能重复计入。
    legacy = OutsourcingProcessingItem.objects.filter(order_product__schedule_product__product_line=product,
        order_product__order__craft__outsourcing_code__in={'SCREEN_PRINTING', 'EMBROIDERY'}).exclude(order_product__order__status='CANCELLED')
    for value in legacy.values('bom_line__component_identity').annotate(total=Sum('quantity')):
        key = str(value['bom_line__component_identity'])
        allocated[key] = allocated.get(key, 0) + value['total']
    issue = MaterialIssue(production_task_id=product.production_task_id, product_line=product, stock_mode='PUBLIC_V2')
    rows, stock_lines = [], []
    for line in lines:
        key = str(line.component_identity)
        row = {'component_identity': key, 'bom_line_id': str(line.pk), 'part_name': line.part_name,
            'material': line.material, 'specification': line.specification, 'thickness': '', 'cutting_length_mm': '',
            'raw_color': '', 'spray_color': '', 'order_required': '0', 'stock_quantity': None, 'stock_unit': '套',
            'unit': '套', 'max_quantity': '0', 'pieces_per_bar': None, 'raw_bar_length_m': None,
            'blockers': list(blockers), 'input_identity': {}, 'snapshot': {}}
        rows.append(row)
        if row['blockers']:
            continue
        try:
            required = whole_pieces(product.quantity * line.cutting_sets_per_product, '裁片订单需求套数')
            input_identity = build_semi_finished_identity(bom_line=line, completed_craft=sewing, unit=unit)
            output_identity = build_semi_finished_identity(bom_line=line, completed_craft=craft, unit=unit)
            attributes = input_identity['identity_snapshot']
            total_allocated = allocated.get(key, 0)
            # 历史冲突包含当前待发单；只有本次可用量扣减时才排除本单预留。
            if total_allocated > required:
                row['blockers'].append(f'历史裁片加工占用{total_allocated}套超过订单需求{required}套，请核对历史占用。')
            remaining = max(Decimal(required) - total_allocated + own_allocated.get(key, 0), Decimal(0))
            row.update(order_required=str(required), pieces_per_set=attributes['pieces_per_set'],
                material=attributes['material'], raw_color=attributes['color'],
                fabric_material=attributes['fabric']['material'], fabric_specification=attributes['fabric']['specification'],
                fabric_color=attributes['color'], completed_craft_name=sewing.name,
                snapshot={'public_output_identity': _json(output_identity), 'shared_remaining': str(remaining)})
            if source_kind == 'SEWING':
                component = basis['components'].get(key)
                if not component or not component['basis_ready']:
                    row['blockers'].extend(component['blockers'] if component else ['缺少该部位有效车缝报工依据。'])
                    continue
                row.update(operations=display_operations(source_kind, component['operations']), allowance=component['allowance'],
                    current_reported_minimum=str(component['allowance']['reported_minimum']),
                    max_quantity=str(min(Decimal(component['allowance']['remaining']), remaining)))
                row['snapshot'].update(sewing_basis_revision=basis['revision'], operations=component['operations'],
                                       allowance=component['allowance'])
            else:
                if zone is None:
                    raise ValidationError('请选择裁片来源半成品库区。')
                row['input_identity'] = _json(input_identity)
                stock_lines.append(MaterialIssueLine(id=line.pk, issue=issue, line_type='SEMI', unit=unit,
                    requested_quantity=1, conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': _json(input_identity)}))
        except (InventoryStockValidationError, ValidationError, TubeQuantityError, TypeError) as error:
            row['blockers'].append(str(getattr(error, 'detail', error)))
    if stock_lines:
        stock = public_issue_quantity_context(issue, lines=stock_lines, exclude_tube_order_id=exclude_order_id)
        all_reservations = public_issue_quantity_context(issue, lines=stock_lines) if exclude_order_id else stock
        by_line = {str(line.pk): line for line in stock_lines}
        for row in rows:
            stock_line = by_line.get(row['bom_line_id'])
            if stock_line is None:
                continue
            pool = _pool(stock_line)
            zone_quantity = sum((value.quantity for value in stock['balances'][pool] if value.zone_id == zone.pk), Decimal(0))
            zone_pending = stock['tube_reserved_by_zone'].get((pool, str(zone.pk)), Decimal(0))
            all_zone_pending = all_reservations['tube_reserved_by_zone'].get((pool, str(zone.pk)), Decimal(0))
            if all_zone_pending > zone_quantity:
                row['blockers'].append(f'历史待发预留{all_zone_pending}套超过来源库区现存{zone_quantity}套，请核对库存及预留。')
            if all_reservations['pending_stock'][pool] > stock['stock'][pool]:
                row['blockers'].append(f'历史待领及待发预留{all_reservations["pending_stock"][pool]}套超过同类裁片现存'
                    f'{stock["stock"][pool]}套，请核对库存及预留。')
            available = max(min(zone_quantity - zone_pending, stock['stock'][pool] - stock['pending_stock'][pool]), Decimal(0))
            row['stock_quantity'] = str(int(zone_quantity))
            row['max_quantity'] = str(int(min(available, Decimal(row['snapshot']['shared_remaining']))))
            row['snapshot']['pool_available'] = str(int(available))
    for row in rows:
        if row['blockers']:
            row['max_quantity'] = '0'
    context = {'source_kind': source_kind, 'rows': rows, 'blockers': blockers,
        'ready': not blockers and any(not row['blockers'] for row in rows), 'bom_id': str(bom.pk) if bom else None,
        'schedule_product_id': str(schedule_product.pk), 'product_line_id': str(product.pk),
        'zone_id': str(zone.pk) if zone else None, 'craft_id': str(craft.pk),
        'sewing_basis_revision': basis['revision'] if basis else None}
    context['source_revision'] = _json_hash(_json({'context': context, 'plan_revision': schedule_product.source_revision_hash,
        'plan_version': schedule_product.schedule.version, 'bom_version': bom.version_number if bom else None}))
    return context, issue, stock_lines


def cutting_source_context(**kwargs):
    return _build_context(**kwargs)[0]


def prepare_cutting_source(*, schedule_product, source_kind, craft, zone, requested, expected_revision,
                           exclude_order_id=None, require_revision=True, additional_stock_lines=()):
    if not connection.in_atomic_block:
        raise RuntimeError('裁片预留必须在同一事务内保存。')
    product = lock_source_product(schedule_product.product_line_id, source_kind)
    boms = list(Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('pk').select_for_update(of=('self',)))
    lines = list(BomLine.objects.filter(section__bom__in=boms).order_by('pk').select_for_update(of=('self',)))
    lock_bom_line_material_identities(lines)
    list(OrderMaterialRequirement.objects.filter(production_task_id=product.production_task_id)
        .order_by('pk').select_for_update(of=('self',)))
    args = dict(schedule_product=schedule_product, source_kind=source_kind, craft=craft, zone=zone, exclude_order_id=exclude_order_id)
    context, issue, stock_lines = _build_context(**args)
    if stock_lines or additional_stock_lines:
        _lock_public_issue_stock(issue, [*stock_lines, *additional_stock_lines])
        context, _, _ = _build_context(**args)
    selected_blockers = []
    if isinstance(requested, dict):
        selected_blockers = [message for row in context['rows'] if row['component_identity'] in requested
                             for message in row['blockers']]
    blocker_message = '；'.join(dict.fromkeys(selected_blockers))
    if require_revision and (not expected_revision or context['source_revision'] != expected_revision):
        raise PreconditionFailed(blocker_message or 'BOM、车缝报工、库存或预留已变化，请刷新后重新确认。')
    if blocker_message:
        raise ValidationError({'lines': blocker_message})
    if not context['ready'] or not isinstance(requested, dict) or not requested:
        raise ValidationError({'lines': '；'.join(context['blockers']) or '至少填写一个依据完整的裁片部位。'})
    by_component = {row['component_identity']: row for row in context['rows']}
    totals, available = defaultdict(Decimal), {}
    normalized = {}
    for key, value in requested.items():
        try:
            quantity = whole_pieces(value, '裁片外发套数')
        except TubeQuantityError as error:
            raise ValidationError({'lines': str(error)}) from error
        row = by_component.get(str(key))
        if not row or row['blockers'] or quantity <= 0 or quantity > Decimal(row['max_quantity']):
            raise ValidationError({'lines': '裁片部位依据不完整，或本次数量超过可外发套数。'})
        row.update(quantity=quantity, stock_quantity=quantity if source_kind == 'PUBLIC_CUTTING' else None, meters=None)
        normalized[str(key)] = quantity
        if source_kind == 'PUBLIC_CUTTING':
            identity = row['input_identity']
            pool = (identity['identity_key'], str(identity['unit_id']))
            totals[pool] += quantity
            available[pool] = Decimal(row['snapshot']['pool_available'])
    if any(quantity > available[pool] for pool, quantity in totals.items()):
        raise ValidationError({'lines': '多个部位共用同一种裁片库存，合计外发套数超过可用库存。'})
    if source_kind == 'SEWING':
        from apps.inventory.sewing_processing_services import assert_sewing_quantity_available
        assert_sewing_quantity_available(product_line_id=product.pk, requested=normalized,
            expected_revision=context['sewing_basis_revision'], exclude_tube_order_id=exclude_order_id)
    return context
