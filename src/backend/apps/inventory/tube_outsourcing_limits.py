"""管材新建外发：只读来源、共享额度以及事务内真实预留校验。"""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed
from apps.material_issues.material_flow import allocation_plan, pipe_specs
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement, MetalProcessingSource
from apps.material_issues.public_issue_services import public_issue_quantity_context, _pool, _lock_public_issue_stock
from apps.products.material_identity import lock_bom_line_material_identities
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft
from .models import WarehouseZone
from .public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity, profile_spray_color
from .stock_services import InventoryStockValidationError
from .tube_processing_quantities import whole_pieces, TubeQuantityError
from .tube_processing_services import lock_tube_product_scope, metal_component_limits, assert_tube_quantity_available

ZERO = Decimal(0)


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _digest(value):
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fail(detail):
    raise ValidationError({'detail': detail})


def _zone(zone, source_kind):
    if source_kind == 'METAL':
        if zone is not None:
            _fail('未入库半成品不选择库存库区。')
        return None
    if zone is None:
        _fail('请选择发出库区。')
    zone_id = getattr(zone, 'pk', zone)
    value = WarehouseZone.objects.select_related('warehouse').filter(pk=zone_id).first()
    warehouse_type = 'MATERIAL' if source_kind == 'RAW_PIPE' else 'SEMI_FINISHED'
    if (not value or value.status != 'ACTIVE' or value.warehouse.status != 'ACTIVE'
            or value.warehouse.warehouse_type != warehouse_type):
        _fail('库区已停用或仓库类型不符合本次来源。')
    return value


def _new_pending(product_id, *, exclude_order_id=None):
    from apps.outsourcing.models import TubeOutsourcingLine
    rows = TubeOutsourcingLine.objects.filter(order__product_line_id=product_id, order__status='PENDING_DISPATCH')
    if exclude_order_id:
        rows = rows.exclude(order_id=exclude_order_id)
    return {str(row['component_identity']): Decimal(row['quantity']) for row in
        rows.values('component_identity').annotate(quantity=Sum('quantity'))}


def _build_context(*, schedule_product, source_kind, zone=None, exclude_order_id=None):
    if source_kind not in {'RAW_PIPE', 'PUBLIC_SEMI', 'METAL'}:
        _fail('请选择有效的管材来源。')
    plan = ProductionScheduleProduct.objects.select_related('schedule__production_task', 'product_line').get(pk=schedule_product.pk)
    product, task = plan.product_line, plan.schedule.production_task
    if (plan.removed_at or plan.schedule.record_status != 'ACTIVE' or task.status not in {'READY', 'IN_PRODUCTION'}
            or product.production_task_id != task.pk):
        _fail('排产或生产任务已失效，请重新选择。')
    craft_links = list(plan.crafts.filter(removed_at__isnull=True).select_related('craft'))
    spray = [row.craft for row in craft_links if row.craft_type_snapshot == 'EXTERNAL'
             and row.craft.outsourcing_code == 'POWDER_COATING' and row.craft.status == 'ACTIVE']
    if len(spray) != 1:
        _fail('当前排产产品须有唯一有效的外发喷塑工艺。')
    zone = _zone(zone, source_kind)
    bom = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('-version_number', '-pk').first()
    blockers = []
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
        blockers.append('请先确认与当前订单数量一致的最新BOM。')
    lines = list(BomLine.objects.filter(section__bom=bom, section__section_type='PROFILE')
                 .select_related('section__bom').order_by('section__line_number', 'line_number', 'id')) if bom else []
    counts = Counter(str(line.component_identity) for line in lines)
    if not lines:
        blockers.append('当前BOM没有可外发的管材部位。')
    if any(value != 1 for value in counts.values()):
        blockers.append('BOM存在重复部位编号，请先修正。')
    specs, spec_errors = pipe_specs(task.pk, product.pk) if not blockers else ([], [])
    specs_by_line = {str(spec['line'].pk): spec for spec in specs}
    errors_by_line = {row['bom_line_id']: row['detail'] for row in spec_errors}
    existing_requirements = list(OrderMaterialRequirement.objects.filter(product_line=product, measurement_kind='PIPE'))
    current = {row.pk: row for row in existing_requirements}
    requirements_by_component = defaultdict(list)
    for row in existing_requirements:
        requirements_by_component[str(row.component_identity)].append(row)
    metal = metal_component_limits(product, exclude_tube_order_id=exclude_order_id) if source_kind == 'METAL' else None
    piece_unit = ProductionUnit.objects.filter(unit_name='支', status='ACTIVE', archived_at__isnull=True).first()
    metal_crafts = [row.craft for row in craft_links if row.craft_type_snapshot == 'INTERNAL'
                    and row.plan_category == 'METAL' and row.craft.status == 'ACTIVE']
    if not metal_crafts:
        metal_crafts = list(Craft.objects.filter(craft_type='INTERNAL', plan_category='METAL', status='ACTIVE'))
    issue = MaterialIssue(production_task=task, product_line=product, stock_mode='PUBLIC_V2')
    stock_lines, rows = [], []
    all_pending = _new_pending(product.pk, exclude_order_id=exclude_order_id)
    from apps.outsourcing.models import TubeOutsourcingLine
    new_dispatched = TubeOutsourcingLine.objects.filter(order__product_line_id=product.pk,
        order__status__in=['PROCESSING', 'COMPLETED'], order__source_kind__in=['METAL', 'PUBLIC_SEMI'])
    if exclude_order_id:
        new_dispatched = new_dispatched.exclude(order_id=exclude_order_id)
    new_dispatched = {str(row['component_identity']): Decimal(row['quantity']) for row in
        new_dispatched.values('component_identity').annotate(quantity=Sum('quantity'))}
    metal_dispatched = {str(row['issue_line__requirement__component_identity']): row['quantity'] or ZERO
        for row in MetalProcessingSource.objects.filter(issue_line__issue__product_line=product)
        .values('issue_line__requirement__component_identity').annotate(quantity=Sum('dispatched_pieces'))}
    for line in lines:
        key = str(line.component_identity)
        values = line.raw_values or {}
        spec = specs_by_line.get(str(line.pk))
        row_errors = []
        row = dict(component_identity=key, bom_line_id=str(line.pk), part_name=line.part_name,
            material=line.material, specification=line.specification,
            thickness=values.get('tube_thickness') or values.get('G') or '',
            cutting_length_mm=str(line.cutting_length_mm or ''), raw_color='',
            spray_color=profile_spray_color(values), order_required='0',
            stock_quantity=None, stock_unit=None, max_quantity='0', pieces_per_bar=None,
            raw_bar_length_m=None, blockers=row_errors, input_identity={}, snapshot={})
        rows.append(row)
        try:
            row['order_required'] = str(whole_pieces(product.quantity * line.pieces_per_product, '部位净需求'))
            if not spec:
                _fail(errors_by_line.get(str(line.pk), '管材原料或BOM换算依据不完整。'))
            previous = requirements_by_component[key]
            if len(previous) > 1 or (previous and previous[0].pk != spec['id']):
                _fail('该部位历史管材需求编号不一致，请核对后再外发，不能另建额度。')
            raw, snapshot = spec['raw_material'], dict(spec['snapshot'])
            row['raw_color'] = raw.color.color_name if raw.color_id else raw.color_snapshot
            if not piece_unit:
                _fail('缺少有效的支单位。')
            # 即使发原料也冻结回来后的实物属性；不能凭空补颜色或规格。
            output_identity = build_semi_finished_identity(bom_line=line, completed_craft=spray[0], unit=piece_unit)
            snapshot.update(requirement_id=str(spec['id']), public_output_identity=_json(output_identity))
            requirement = current.get(spec['id']) or OrderMaterialRequirement(id=spec['id'],
                production_task=task, product_line=product, component_identity=line.component_identity,
                raw_material=raw, unit=piece_unit, measurement_kind='PIPE')
            requirement.required_quantity = Decimal(snapshot['allowance_pieces'])
            if source_kind == 'METAL':
                basis = metal['components'].get(key)
                if not basis or not basis['basis_ready']:
                    _fail('；'.join(basis['blockers']) if basis else '部位缺少有效的金工报工依据。')
                row['max_quantity'] = str(basis['allowance']['remaining'])
                row['operations'] = basis['operations']
                row['allowance'] = basis['allowance']
                snapshot.update(metal_basis_revision=metal['revision'], operations=basis['operations'], allowance=basis['allowance'])
            else:
                if source_kind == 'RAW_PIPE':
                    identity = build_pipe_stock_identity(raw_material=raw,
                        raw_bar_length_m=Decimal(snapshot['raw_bar_length_m']), unit=raw.unit)
                    row.update(pieces_per_bar=str(snapshot['pieces_per_bar']), raw_bar_length_m=str(snapshot['raw_bar_length_m']), stock_unit='根')
                    requested = Decimal(snapshot['pieces_per_bar'])
                else:
                    if len(metal_crafts) != 1:
                        _fail('未喷塑库存缺少唯一有效的金工完成工艺。')
                    identity = build_semi_finished_identity(bom_line=line, completed_craft=metal_crafts[0], unit=piece_unit)
                    row['stock_unit'] = '支'
                    requested = Decimal(1)
                row['input_identity'] = _json(identity)
                stock_line = MaterialIssueLine(issue=issue, requirement=requirement, raw_material=raw,
                    unit=piece_unit, requested_quantity=requested,
                    conversion_snapshot={**snapshot, 'kind': 'PIPE' if source_kind == 'RAW_PIPE' else 'TUBE_SEMI',
                                         'public_identity': _json(identity)})
                stock_lines.append(stock_line)
                row['_line'] = stock_line
            row['snapshot'] = _json(snapshot)
            row['_external_used'] = (requirement.outsourcing_issued_quantity + metal_dispatched.get(key, ZERO)
                                     + new_dispatched.get(key, ZERO))
            shared_cap = Decimal(snapshot['allowance_pieces']) if source_kind == 'RAW_PIPE' else Decimal(row['order_required'])
            shared_remaining = max(shared_cap - row['_external_used'] - all_pending.get(key, ZERO), ZERO)
            row['snapshot'].update(shared_remaining=str(shared_remaining),
                pending_all_sources=str(all_pending.get(key, ZERO)), external_used=str(row['_external_used']))
            if source_kind == 'METAL':
                row['max_quantity'] = str(min(Decimal(row['max_quantity']), shared_remaining))
        except (ValidationError, InventoryStockValidationError, TubeQuantityError, TypeError) as error:
            row_errors.append(str(getattr(error, 'detail', error)))
    stock_context = public_issue_quantity_context(issue, lines=stock_lines,
        exclude_tube_order_id=exclude_order_id) if stock_lines else None
    for row in rows:
        stock_line = row.pop('_line', None)
        external_used = row.pop('_external_used', ZERO)
        if stock_line is None:
            continue
        pool = _pool(stock_line)
        all_stock = stock_context['stock'][pool]
        total_pending = stock_context['pending_stock'][pool]
        zone_stock = sum((value.quantity for value in stock_context['balances'][pool] if value.zone_id == zone.pk), ZERO)
        zone_pending = stock_context['tube_reserved_by_zone'].get((pool, str(zone.pk)), ZERO)
        available = max(min(zone_stock - zone_pending, all_stock - total_pending), ZERO)
        row['stock_quantity'] = str(zone_stock)
        row['snapshot'].update(pool_available=str(available), zone_quantity=str(zone_stock),
            pool_pending=str(total_pending), zone_pending=str(zone_pending))
        if source_kind == 'RAW_PIPE':
            req = stock_line.requirement
            pending = stock_context['pending_raw'].get(req.pk, ZERO)
            remaining = max(req.required_quantity - req.internal_issued_quantity - req.outsourcing_issued_quantity - pending, ZERO)
            factor = Decimal(row['pieces_per_bar'])
            maximum = min(remaining, available * factor, Decimal(row['snapshot']['shared_remaining']))
            # 显示可申请的整根支数，不向上抹掉订单/库存边界。
            maximum = (maximum // factor) * factor
            row['snapshot'].update(order_remaining=str(remaining), internal_issued=str(req.internal_issued_quantity),
                outsourcing_issued=str(req.outsourcing_issued_quantity), pending_order=str(pending))
        else:
            remaining = Decimal(row['snapshot']['shared_remaining'])
            maximum = min(remaining, available)
            row['snapshot'].update(order_remaining=str(remaining), external_used=str(external_used),
                pending_order=str(all_pending.get(row['component_identity'], ZERO)))
        row['max_quantity'] = str(maximum.to_integral_value()) if not row['blockers'] else '0'
    # 空需求创建前后数据库补齐小数位，不应把同一数量误判成来源变化。
    quantity_fields = {'pool_available', 'zone_quantity', 'pool_pending', 'zone_pending',
        'order_remaining', 'internal_issued', 'outsourcing_issued', 'pending_order',
        'shared_remaining', 'pending_all_sources', 'external_used'}
    for row in rows:
        row['max_quantity'] = str(int(Decimal(row['max_quantity'])))
        if row['stock_quantity'] is not None:
            row['stock_quantity'] = str(int(Decimal(row['stock_quantity'])))
        for field in quantity_fields & row['snapshot'].keys():
            row['snapshot'][field] = str(int(Decimal(row['snapshot'][field])))
    context = dict(source_kind=source_kind, schedule_product_id=str(plan.pk), product_line_id=str(product.pk),
        zone_id=str(zone.pk) if zone else None, ready=not blockers and any(not row['blockers'] for row in rows),
        blockers=blockers, rows=rows, bom_id=str(bom.pk) if bom else None,
        metal_basis_revision=metal['revision'] if metal else None)
    context['source_revision'] = _digest({'context': context, 'schedule_revision': plan.source_revision_hash,
        'schedule_version': plan.schedule.version, 'product_quantity': product.quantity,
        'bom_version': bom.version_number if bom else None, 'craft_ids': [str(row.pk) for row in spray]})
    return context, issue, stock_lines


def tube_source_context(*, schedule_product, source_kind, zone=None):
    return _build_context(schedule_product=schedule_product, source_kind=source_kind, zone=zone)[0]


def prepare_tube_source(*, schedule_product, source_kind, zone, requested, expected_revision,
                        exclude_order_id=None, require_revision=True):
    if not connection.in_atomic_block:
        raise RuntimeError('外发预留必须在同一数据库事务内保存。')
    product = lock_tube_product_scope(schedule_product.product_line_id)
    boms = list(Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('pk').select_for_update(of=('self',)))
    lines = list(BomLine.objects.filter(section__bom__in=boms).order_by('pk').select_for_update(of=('self',)))
    lock_bom_line_material_identities(lines)
    list(OrderMaterialRequirement.objects.filter(product_line=product).order_by('pk').select_for_update(of=('self',)))
    context, issue, stock_lines = _build_context(schedule_product=schedule_product, source_kind=source_kind,
                                               zone=zone, exclude_order_id=exclude_order_id)
    if source_kind == 'RAW_PIPE' and isinstance(requested, dict):
        from apps.material_issues.pipe_requirements import sync_pipe_requirement
        selected = {str(key) for key in requested}
        for row in context['rows']:
            if row['component_identity'] in selected and not row['blockers']:
                sync_pipe_requirement(row['bom_line_id'])
        context, issue, stock_lines = _build_context(schedule_product=schedule_product, source_kind=source_kind,
                                                   zone=zone, exclude_order_id=exclude_order_id)
    if stock_lines:
        _lock_public_issue_stock(issue, stock_lines)
        # 等锁期间库存或其他订单预留可能已改变，必须重新读取。
        context, _, stock_lines = _build_context(schedule_product=schedule_product, source_kind=source_kind,
                                                zone=zone, exclude_order_id=exclude_order_id)
    if require_revision and (not expected_revision or context['source_revision'] != expected_revision):
        raise PreconditionFailed('BOM、报工、库存或预留已变化，请刷新后重新确认。')
    if not context['ready']:
        _fail('；'.join(context['blockers']) or '当前来源尚不具备外发条件。')
    if not isinstance(requested, dict) or not requested:
        _fail('至少填写一个大于0的管材数量。')
    by_component = {row['component_identity']: row for row in context['rows']}
    stock_totals, pool_available = defaultdict(Decimal), {}
    normalized = {}
    for component, value in requested.items():
        key = str(component)
        try:
            quantity = whole_pieces(value, '本次外发')
        except TubeQuantityError as error:
            _fail(str(error))
        row = by_component.get(key)
        if quantity <= 0 or key in normalized or not row or row['blockers']:
            _fail('外发明细须为当前BOM中不重复且依据完整的部位，数量须大于0。')
        if quantity > Decimal(row['max_quantity']):
            _fail(f'“{row["part_name"]}”最多可外发{row["max_quantity"]}支。')
        normalized[key] = quantity
        row.update(quantity=quantity, stock_quantity=None, meters='0.00')
        if source_kind != 'METAL':
            identity = row['input_identity']
            pool = (identity['stock_kind'], identity['identity_key'], str(identity['unit_id']))
            if source_kind == 'RAW_PIPE':
                conversion = allocation_plan(Decimal(quantity), row['snapshot'])
                row['stock_quantity'] = int(conversion['bar_count'])
                row['meters'] = str(conversion['meters'])
            else:
                row['stock_quantity'] = quantity
            stock_totals[pool] += row['stock_quantity']
            pool_available[pool] = Decimal(row['snapshot']['pool_available'])
    for pool, quantity in stock_totals.items():
        if quantity > pool_available[pool]:
            _fail('本单多个部位使用同一种公共库存，合计数量超过可用库存。')
    if source_kind == 'METAL':
        assert_tube_quantity_available(product_line_id=product.pk, requested=normalized,
            expected_revision=context['metal_basis_revision'], exclude_tube_order_id=exclude_order_id)
    return context
