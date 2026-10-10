"""D1金工入库：按报工首次产出额度记入公共未喷塑库存。"""
from decimal import Decimal
import uuid

from django.db import connection
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.material_issues.models import OrderMaterialRequirement
from apps.material_issues.processing_selectors import digest
from apps.production_scheduling.selectors import schedule_items_for_category, accessible_production_schedules
from apps.products.material_identity import lock_bom_line_material_identities
from apps.reference_data.models import ProductionUnit
from apps.workshop_reporting.models import WageScheme
from .models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, WarehouseZone
from .public_stock_identity import build_semi_finished_identity
from .public_stock_mode import public_flow_enabled
from .public_stock_services import credit_public_stock
from .tube_processing_quantities import whole_pieces, TubeQuantityError
from .tube_processing_services import (
    lock_tube_product_scope, metal_component_limits, _basis_dates, assert_tube_quantity_available,
)

QUANTITY_BASIS = 'WORK_REPORT_MINIMUM'


def uses_tube_receipt(*, schedule_product_id=None, request_id=None):
    """开关仅控制新接入；已存在的新口径业务不随开关退回手工完成规则。"""
    def identifier(value):
        try:
            return uuid.UUID(str(value)) if value else None
        except (ValueError, TypeError, AttributeError):
            return None
    request_id, plan_id = identifier(request_id), identifier(schedule_product_id)
    if request_id:
        existing = InternalSemiFinishedReceipt.objects.filter(request_id=request_id).values('source_snapshot').first()
        if existing is not None:
            return existing['source_snapshot'].get('quantity_basis') == QUANTITY_BASIS
    if getattr(settings, 'TUBE_OUTSOURCING_ENABLED', False):
        return True
    records = InternalSemiFinishedReceipt.objects.filter(source_snapshot__quantity_basis=QUANTITY_BASIS)
    if plan_id:
        from apps.production_scheduling.models import ProductionScheduleProduct
        from apps.outsourcing.models import TubeOutsourcingOrder
        product_id = ProductionScheduleProduct.objects.filter(pk=plan_id).values_list('product_line_id', flat=True).first()
        if product_id and (records.filter(schedule_product__product_line_id=product_id).exists()
                or TubeOutsourcingOrder.objects.filter(product_line_id=product_id, source_kind='METAL',
                    status__in=['PENDING_DISPATCH', 'PROCESSING', 'COMPLETED']).exists()):
            return True
    return False


def _fail(message):
    raise ValidationError({'detail': message})


def _integer(value):
    return str(whole_pieces(value))


def _schemes(basis):
    identifiers = {operation['scheme_id'] for row in basis['components'].values() for operation in row['operations']}
    return {str(row.pk): {'id': str(row.pk), 'scheme_number': row.scheme_number, 'version': row.version,
        'status': row.status, 'effective_from': str(row.effective_from),
        'effective_to': str(row.effective_to) if row.effective_to else None}
        for row in WageScheme.objects.filter(pk__in=identifiers).order_by('scheme_number', 'pk')}


def load_tube_receipt_context(request, schedule_product_id, *, lock=False):
    from .internal_receipt_services import require_operator
    require_operator(request)
    if not public_flow_enabled():
        _fail('公共库存流程尚未启用，不能登记厂内半成品。')
    plan = get_object_or_404(schedule_items_for_category(request, 'METAL'), pk=schedule_product_id)
    if lock:
        lock_tube_product_scope(plan.product_line_id)
        plan = get_object_or_404(schedule_items_for_category(request, 'METAL'), pk=plan.pk)
    task, product = plan.schedule.production_task, plan.product_line
    if task.status != 'IN_PRODUCTION' or task.archived_at is not None:
        _fail('生产任务必须处于生产中。')
    boms = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('-version_number', '-pk')
    if lock:
        boms = boms.select_for_update(of=('self',))
    bom = boms.first()
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
        _fail('请先确认与当前订单数量一致的最新BOM。')
    links = list(plan.crafts.filter(removed_at__isnull=True, craft_type_snapshot='INTERNAL',
        plan_category='METAL').select_related('craft'))
    if len(links) != 1 or links[0].craft.status != 'ACTIVE':
        _fail('内部金工工艺不存在、已停用或不能唯一确定。')
    craft = links[0].craft
    unit = ProductionUnit.objects.filter(unit_name='支', status='ACTIVE', archived_at__isnull=True).first()
    if not unit:
        _fail('缺少有效的支单位。')
    lines_query = BomLine.objects.filter(section__bom=bom, section__section_type='PROFILE').select_related('section__bom')
    if lock:
        lines_query = lines_query.select_for_update(of=('self',))
    lines = list(lines_query.order_by('section__line_number', 'line_number', 'pk'))
    if lock:
        lock_bom_line_material_identities(lines)
        list(OrderMaterialRequirement.objects.filter(product_line=product).order_by('pk').select_for_update(of=('self',)))
    basis = metal_component_limits(product)
    future = [metal_component_limits(product, as_of=day) for day in _basis_dates(product.pk)
              if str(day) != basis['as_of']]
    schemes = _schemes(basis)
    requirements = {}
    for requirement in OrderMaterialRequirement.objects.filter(product_line=product, measurement_kind='PIPE'):
        requirements.setdefault(str(requirement.component_identity), []).append(requirement)
    history = {}
    for row in InternalSemiFinishedReceiptLine.objects.filter(receipt__schedule_product__product_line=product,
            receipt__plan_category='METAL').order_by('pk'):
        history.setdefault(str(row.component_identity), []).append(row)
    facts, rows, global_blockers = {}, [], []
    current_components = {str(line.component_identity) for line in lines}
    if set(history) - current_components:
        global_blockers.append('已有首次入库部位不在当前BOM，请先核对历史资料。')
    for line in lines:
        key = str(line.component_identity)
        value = basis['components'][key]
        blockers = list(value['blockers'])
        identity = None
        try:
            identity = build_semi_finished_identity(bom_line=line, completed_craft=craft, unit=unit)
        except ValidationError as error:
            blockers.append(str(error.detail))
        if identity and any(row.attribute_snapshot != identity['identity_snapshot'] for row in history.get(key, [])):
            blockers.append('已入库部位的实物属性或完成工艺发生变化，请先核对原单。')
        matching = requirements.get(key, [])
        requirement = matching[0] if len(matching) == 1 else None
        if len(matching) > 1 or (value['issued'] and requirement is None):
            blockers.append('无法唯一关联该部位的有效领料需求，请核对原领料单。')
        allowance = value['allowance']
        ready = bool(value['basis_ready'] and identity and not blockers)
        current = allowance['remaining'] if ready else 0
        available, future_blockers = current, []
        for future_basis in future:
            future_row = future_basis['components'].get(key)
            if not future_row or not future_row['basis_ready']:
                permitted = 0
            else:
                amounts = future_row['allowance']
                permitted = max(0, amounts['reported_minimum'] - amounts['report_protected_usage'])
            if permitted < current:
                future_blockers.append(f'{future_basis["as_of"]}生效的已批准工价依据最多支持本次新增{permitted}支，请核对工价方案和报工。')
            available = min(available, permitted)
        operations = value['operations']
        selected_schemes = sorted({item['scheme_id'] for item in operations})
        metadata = {'basis_ready': ready, 'blockers': list(dict.fromkeys(blockers)), 'as_of': basis['as_of'],
            'issued': _integer(value['issued']), 'reported_minimum': _integer(allowance['reported_minimum']) if ready else None,
            'dispatched': _integer(value['usage']['dispatched']), 'reserved': _integer(value['usage']['reserved']),
            'first_output_limit': _integer(min(allowance['required'], allowance['issued'], allowance['reported_minimum'])) if ready else None,
            'current_remaining': _integer(current), 'can_receive': _integer(available), 'operations': operations,
            'schemes': [schemes[identifier] for identifier in selected_schemes], 'future_blockers': future_blockers}
        attributes = identity['identity_snapshot'] if identity else {'part_name': line.part_name, 'material': line.material,
            'tube_thickness': (line.raw_values or {}).get('tube_thickness', ''),
            'cutting_length_mm': str(line.cutting_length_mm or ''), 'color': '', 'unit_name': '支'}
        required = _integer(value['required']) if value['required'] is not None else None
        received = _integer(value['usage']['received'])
        row = {'bom_line_id': str(line.pk), 'component_identity': key,
            'component_key': f'{product.pk}:{key}:METAL', 'usage': str(line.pieces_per_product or ''),
            'specification': line.specification, 'attributes': attributes, 'stage': '金工完成',
            'required': required, 'received': received, 'can_receive': _integer(available), 'metal_processing': metadata}
        rows.append(row)
        facts[str(line.pk)] = {'line': line, 'requirement': requirement, 'identity': identity, 'row': row}
    revision = digest({'quantity_basis': QUANTITY_BASIS, 'plan': str(plan.pk), 'plan_revision': plan.source_revision_hash,
        'schedule_version': plan.schedule.version, 'bom': str(bom.pk), 'basis_revision': basis['revision'],
        'future_revisions': [value['revision'] for value in future], 'rows': rows, 'blockers': global_blockers})
    return {'tube_new': True, 'plan': plan, 'task': task, 'product': product, 'bom': bom,
        'craft': craft, 'unit': unit, 'category': 'METAL', 'facts': facts, 'rows': rows, 'tube_basis': basis,
        'revision': revision, 'blockers': global_blockers}


def tube_preview_data(context, actor):
    plan, task, product = context['plan'], context['task'], context['product']
    zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type='SEMI_FINISHED').select_related('warehouse').order_by('warehouse__warehouse_name', 'zone_name', 'pk')
    future_blockers = list(dict.fromkeys(message for row in context['rows']
        for message in row['metal_processing']['future_blockers']))
    if any(int(row['can_receive']) > 0 for row in context['rows']):
        future_blockers = []
    return {'schedule_product_id': str(plan.pk), 'plan_category': 'METAL', 'etag': f'"{context["revision"]}"',
        'production_order': task.task_number, 'order_number': task.order_number, 'schedule_number': plan.schedule.schedule_number,
        'product': product.product_name_snapshot, 'product_number': product.product_number_snapshot,
        'item_number': product.item_number_snapshot, 'product_unit': product.unit.unit_name,
        'product_color': product.color_name_snapshot, 'order_quantity': str(product.quantity),
        'actor': actor.display_name, 'receipt_date': str(timezone.localdate()), 'processing_state': '未喷塑',
        'lines': context['rows'], 'excluded': [], 'zones': [{'id': str(zone.pk), 'warehouse_id': str(zone.warehouse_id),
            'warehouse': zone.warehouse.warehouse_name, 'name': zone.zone_name} for zone in zones],
        'metal_processing': {'as_of': context['tube_basis']['as_of'], 'blockers': context['blockers'],
            'future_blockers': future_blockers}}


def require_receipt_recovery_access(request, receipt):
    from .internal_receipt_services import require_operator
    actor = require_operator(request)
    if receipt.actor_employee_id != actor.pk:
        raise PermissionDenied('只能核对本人提交的入库结果。')
    get_object_or_404(accessible_production_schedules(request), pk=receipt.schedule_product.schedule_id)


def receipt_result(receipt, *, replayed=True):
    return {'receipt_id': str(receipt.pk), 'receipt_number': receipt.receipt_number, 'replayed': replayed,
            'record_ids': [str(value) for value in receipt.lines.values_list('stock_movement_id', flat=True)]}


def confirm_tube_receipt(request, data):
    # 调用者已经通过stock_write_transaction进入原子事务并取得公共库存切换锁。
    from .internal_receipt_services import require_operator
    actor = require_operator(request, write=True)
    payload_hash = digest({'actor': str(actor.pk), 'data': data})
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int.from_bytes(bytes.fromhex(digest(str(data['request_id'])))[:8], signed=True)])
    existing = InternalSemiFinishedReceipt.objects.select_related('schedule_product').filter(request_id=data['request_id']).first()
    if existing:
        require_receipt_recovery_access(request, existing)
        if existing.request_payload_hash != payload_hash:
            raise Conflict('相同请求编号不能用于不同入库内容或操作人。')
        return existing, True
    context = load_tube_receipt_context(request, data['schedule_product_id'], lock=True)
    expected = request.headers.get('If-Match')
    if not expected:
        raise PreconditionRequired()
    if expected != f'"{context["revision"]}"':
        raise PreconditionFailed('报工、工价、BOM、领料或已用额度发生变化，请刷新后重新核对。')
    if context['blockers']:
        _fail('；'.join(context['blockers']))
    requested, facts = {}, context['facts']
    for entered in data['lines']:
        fact = facts.get(str(entered['bom_line_id']))
        if not fact:
            _fail('入库明细不属于当前金工计划。')
        key = str(fact['line'].component_identity)
        try:
            quantity = whole_pieces(entered['quantity'], '本次入库')
        except TubeQuantityError as error:
            _fail(str(error))
        if key in requested or quantity <= 0:
            _fail('入库部位不能重复，办理数量须大于0。')
        row = fact['row']
        if not row['metal_processing']['basis_ready']:
            _fail('；'.join(row['metal_processing']['blockers']) or '部位入库依据不完整。')
        if quantity > int(row['can_receive']):
            _fail('；'.join(row['metal_processing']['future_blockers']) or f'“{fact["line"].part_name}”本次最多可入{row["can_receive"]}支。')
        if fact['requirement'] is None:
            _fail('该部位尚无有效领料需求，请先领料。')
        requested[key] = quantity
    assert_tube_quantity_available(product_line_id=context['product'].pk, requested=requested,
                                  expected_revision=context['tube_basis']['revision'])
    zone = get_object_or_404(WarehouseZone, pk=data['zone_id'], status='ACTIVE',
        warehouse__status='ACTIVE', warehouse__warehouse_type='SEMI_FINISHED')
    header = InternalSemiFinishedReceipt.objects.create(
        receipt_number='BNRK' + timezone.localtime().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:10].upper(),
        request_id=data['request_id'], request_payload_hash=payload_hash, schedule_product=context['plan'],
        completed_craft=context['craft'], plan_category='METAL', receipt_date=data['receipt_date'], zone=zone,
        actor_employee=actor, source_revision_hash=context['revision'], remark=data.get('remark', ''),
        source_snapshot={'quantity_basis': QUANTITY_BASIS, 'production_order': context['task'].task_number,
            'product': context['product'].product_name_snapshot, 'order_quantity': str(context['product'].quantity),
            'bom_id': str(context['bom'].pk), 'plan_category': 'METAL', 'schedule_id': str(context['plan'].schedule_id),
            'tube_basis_revision': context['tube_basis']['revision']})
    for entered in data['lines']:
        fact = facts[str(entered['bom_line_id'])]
        key = str(fact['line'].component_identity)
        quantity, row_id, row = requested[key], uuid.uuid4(), fact['row']
        movement = credit_public_stock(identity=fact['identity'], zone=zone, quantity=quantity,
            source_type='INTERNAL_SEMI_RECEIPT', source_id=header.pk, source_line_id=row_id, actor_employee=actor,
            production_task=context['task'], product_line=context['product'], bom_line=fact['line'],
            snapshot={**header.source_snapshot, 'receipt_number': header.receipt_number,
                'receipt_date': str(header.receipt_date), 'actor_name': actor.display_name, 'source': '厂内入库', 'remark': header.remark})
        InternalSemiFinishedReceiptLine.objects.create(id=row_id, receipt=header, bom_line=fact['line'],
            component_identity=fact['line'].component_identity, unit=context['unit'], input_requirement=fact['requirement'],
            input_unit_name='支', quantity=quantity, input_per_output=1, input_quantity=quantity,
            required_quantity_snapshot=row['required'], received_before=row['received'],
            received_after=int(row['received']) + quantity, stock_movement=movement,
            attribute_snapshot=fact['identity']['identity_snapshot'], input_snapshot=row['metal_processing'])
    return header, False
