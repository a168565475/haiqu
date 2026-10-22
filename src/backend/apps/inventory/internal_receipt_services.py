"""确认厂内产出；金工核对领用投入，车缝按实际套数及订单剩余办理。"""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
import uuid

from django.db import connection, models
from django.db.models.deletion import ProtectedError
from django.db.models import Prefetch, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.auth import active_employee_for
from apps.core.numbering import next_business_number
from apps.material_issues.models import (MaterialIssue, MaterialIssueLine, MaterialIssueAuditEvent,
    MaterialIssuePublicStockAllocation, MetalProcessingSource, RequirementContribution)
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct
from apps.production_scheduling.selectors import schedule_items_for_category
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.material_identity import resolve_bom_line_raw_material, resolve_cutting_fabric_material
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft
from .internal_receipt_quantities import (ComponentDemand, InputPool, ReceivedOutput, ReceiptQuantityError,
    calculate_receipt, validate_receipt, net_component_demand)
from .models import (InternalReceiptStatus, InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine,
                     WarehouseZone, PublicStockMovement)
from .public_stock_cutover import stock_write_transaction
from .public_stock_identity import build_semi_finished_identity
from .public_stock_services import credit_public_stock
from .public_stock_mode import public_flow_enabled
from .stock_services import InventoryStockValidationError
from .receipt_permissions import can_delete_pending_receipt, receipt_plans_for_category


def require_operator(request, *, write=False, permission=None):
    from apps.access_control.module_policy import has_permission
    actor = active_employee_for(request.user)
    required_permission = permission or ('add_internalsemifinishedreceipt' if write else 'view_internalsemifinishedreceipt')
    if actor is None or not has_permission(request, f'inventory.{required_permission}'):
        raise PermissionDenied('没有厂内半成品入库权限。')
    request.employee = actor
    return actor


def _fail(message):
    raise ValidationError({'detail': message})


def _key(product, component, category):
    return f'{product}:{component}:{category}'


def _json(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def load_receipt_context(request, schedule_product_id, category, *, lock=False, exclude_receipt_id=None,
                         confirmation=False):
    if category == 'METAL':
        from .tube_receipt_services import uses_tube_receipt, load_tube_receipt_context
        if uses_tube_receipt(schedule_product_id=schedule_product_id):
            return load_tube_receipt_context(request, schedule_product_id, lock=lock,
                                             exclude_receipt_id=exclude_receipt_id, confirmation=confirmation)
    require_operator(request)
    if not public_flow_enabled():
        _fail('公共库存流程尚未启用，不能在旧库存流程登记厂内半成品。')
    if category not in {'METAL', 'SEWING'}:
        _fail('只有金工、车缝计划可以登记厂内半成品入库；裁剪直接交车缝。')
    plan = get_object_or_404(receipt_plans_for_category(request, category, confirmation=confirmation), pk=schedule_product_id)
    locked_issue_ids = None
    if lock:
        if category == 'METAL':
            from .tube_processing_services import lock_tube_product_scope
            lock_tube_product_scope(plan.product_line_id)
            if uses_tube_receipt(schedule_product_id=schedule_product_id):
                return load_tube_receipt_context(request, schedule_product_id, lock=True,
                                                 exclude_receipt_id=exclude_receipt_id, confirmation=confirmation)
        else:
            from .sewing_processing_services import lock_sewing_product_scope
            lock_sewing_product_scope(plan.product_line_id)
        # 既有加工/原单回货先锁领料再锁订单；保持同序，不能拿着订单锁等待领料锁。
        locked_issue_ids = list(MaterialIssue.objects.filter(production_task_id=plan.schedule.production_task_id,
            product_line_id=plan.product_line_id, status='ISSUED').order_by('id').select_for_update().values_list('id',flat=True))
        list(MetalProcessingSource.objects.filter(issue_line__issue_id__in=locked_issue_ids).order_by('id').select_for_update().values_list('id',flat=True))
        ProductionSchedule.objects.select_for_update().get(pk=plan.schedule_id)
        ProductionTask.objects.select_for_update().get(pk=plan.schedule.production_task_id)
        ProductionScheduleProduct.objects.select_for_update().get(pk=plan.pk)
        ProductionTaskProduct.objects.select_for_update().get(pk=plan.product_line_id)
        plan = get_object_or_404(receipt_plans_for_category(request, category, confirmation=confirmation), pk=plan.pk)
        current_issue_ids = list(MaterialIssue.objects.filter(production_task_id=plan.schedule.production_task_id,
            product_line_id=plan.product_line_id,status='ISSUED').order_by('id').values_list('id',flat=True))
        if current_issue_ids != locked_issue_ids:
            raise PreconditionFailed('有新的领料完成出库，请刷新后确认。')
    task, product = plan.schedule.production_task, plan.product_line
    if task.status != 'IN_PRODUCTION':
        _fail('生产订单必须处于生产中。')
    boms = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('-version_number', '-id')
    if lock:
        boms = boms.select_for_update()
    bom = boms.first()
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
        _fail('请先确认与当前订单数量一致的最新 BOM。')
    links = list(plan.crafts.filter(removed_at__isnull=True).select_related('craft'))
    craft = next((item.craft for item in links if item.plan_category == category and item.craft_type_snapshot == 'INTERNAL'), None)
    if not craft or craft.status != 'ACTIVE':
        _fail('内部工序不存在或已停用。')
    powder = any(item.craft.outsourcing_code == 'POWDER_COATING' for item in links)
    # 外发/厂内车缝使用同一个完成阶段身份，实际来源仍由入库原单单独记录。
    stock_craft = craft
    if category == 'SEWING':
        stock_craft = Craft.objects.filter(craft_type='EXTERNAL', outsourcing_code='SEWING').first()
        if stock_craft is None:
            _fail('缺少既有车缝完成工艺，无法与外发车缝公共库存对应。')
    unit_name = '支' if category == 'METAL' else '套'
    unit = ProductionUnit.objects.filter(unit_name=unit_name, status='ACTIVE', archived_at__isnull=True).first()
    if not unit:
        _fail(f'缺少有效的{unit_name}单位。')
    lines = list(BomLine.objects.filter(section__bom=bom).select_related('section', 'fabric_source_line__section').order_by('id'))
    lines = [line for line in lines if (line.section.section_type == 'PROFILE' if category == 'METAL'
                                      else line.section.section_type == 'FABRIC' and line.section.title == '裁剪明细')]
    excluded = []
    if category == 'METAL' and powder:
        excluded = [line.part_name for line in lines]
        lines = []
    contributions = list(RequirementContribution.objects.filter(bom=bom, is_current=True,
        product_line=product).select_related('requirement__unit', 'requirement__raw_material'))
    by_line = defaultdict(list)
    for contribution in contributions:
        by_line[contribution.bom_line_id].append(contribution.requirement)
    demands, facts, requirement_ids, seen = [], {}, set(), set()
    scope = str(task.pk)
    external_received = {row['bom_line__component_identity']: row['total'] for row in PublicStockMovement.objects.filter(
        production_task=task, product_line=product, direction='IN', balance__quality='AVAILABLE',
        source_type__in=['OUTSOURCING_RETURN','METAL_P4_EXTERNAL_RETURN'],
        balance__identity_snapshot__completed_craft__code=category).values('bom_line__component_identity').annotate(total=Sum('quantity'))}
    direct_usage = {}
    if category == 'SEWING':
        from .sewing_processing_services import sewing_output_usage
        direct_usage = sewing_output_usage(product.pk)
    for line in lines:
        if line.component_identity in seen:
            _fail('BOM 部位编号重复，请先修正。')
        seen.add(line.component_identity)
        requirements = by_line[line.pk if category == 'METAL' else line.fabric_source_line_id]
        requirements = {row.pk: row for row in requirements if row.line_type == 'RAW'}
        if len(requirements) != 1:
            _fail(f'{line.part_name}尚无唯一有效的领料需求，请先完成对应原料领料。')
        requirement = next(iter(requirements.values()))
        material, _ = resolve_bom_line_raw_material(line) if category == 'METAL' else resolve_cutting_fabric_material(line)
        if material is None or requirement.raw_material_id != material.pk:
            _fail(f'{line.part_name}的已领原料与当前 BOM 关联原料不一致。')
        input_unit = '支' if category == 'METAL' else '米'
        if requirement.unit.unit_name != input_unit:
            _fail(f'{line.part_name}的投入单位应为{input_unit}。')
        if category == 'METAL' and (requirement.measurement_kind != 'PIPE'
                or requirement.component_identity != line.component_identity or requirement.product_line_id != product.pk):
            _fail('管材投入与当前部位不一致。')
        usage = line.pieces_per_product if category == 'METAL' else line.cutting_sets_per_product
        required = net_component_demand(product.quantity, usage)
        input_per_output = Decimal(1) if category == 'METAL' else None
        component_key = _key(product.pk, line.component_identity, category)
        source_key = f'{product.pk}:{requirement.pk}'
        try:
            identity = build_semi_finished_identity(bom_line=line, completed_craft=stock_craft, unit=unit)
        except InventoryStockValidationError as error:
            field = error.error_meta['field']
            label = {'specification':'规格', 'material':'材质', 'category':'类别', 'part_name':'部位名称',
                'fabric_source_line':'来源面料', 'fabric.material':'来源面料材质',
                'fabric.specification':'来源面料规格', 'fabric.color':'来源面料颜色或色号',
                'cutting_color':'裁片颜色', 'cutting_pieces_per_set':'每套裁片数',
                'completed_craft':'完成工艺', 'unit':'单位'}.get(field, '库存属性')
            raise InventoryStockValidationError(
                {'detail':f'部位“{line.part_name}”的{label}：{error.detail[field]}', **error.detail},
                code=error.api_error_code, meta=error.error_meta) from error
        demands.append(ComponentDemand(scope, component_key, source_key, input_unit, unit_name, required, input_per_output,
                                       external_received.get(line.component_identity, Decimal(0)),
                                       sum(direct_usage.get(str(line.component_identity), {}).get(name, 0)
                                           for name in ('dispatched', 'reserved'))))
        facts[component_key] = dict(line=line, requirement=requirement, identity=identity, usage=usage)
        requirement_ids.add(requirement.pk)
    issued_query = MaterialIssueLine.objects.filter(issue__production_task=task, issue__product_line=product,
        issue__status='ISSUED', line_type='RAW', requirement_id__in=requirement_ids).select_related(
        'issue__product_line', 'issue__production_task', 'requirement').prefetch_related(
        Prefetch('issue__audit_events', queryset=MaterialIssueAuditEvent.objects.filter(action='CREATED')),
        Prefetch('public_stock_allocations', queryset=MaterialIssuePublicStockAllocation.objects.select_related('movement', 'balance'))).order_by('issue_id','id')
    issued_lines = list(issued_query) if category == 'METAL' else []
    sources_query = MetalProcessingSource.objects.filter(issue_line_id__in=[line.pk for line in issued_lines]).order_by('id')
    if lock:
        sources_query = sources_query.select_for_update()
    sources = {row.issue_line_id: row for row in sources_query}
    issued, committed, source_facts = defaultdict(Decimal), defaultdict(Decimal), []
    for line in issued_lines:
        origin = next(iter(line.issue.audit_events.all()), None)
        origin_category = (origin.snapshot.get('plan_source', {}) if origin else {}).get('plan_category')
        if origin_category not in ({'METAL'} if category == 'METAL' else {'CUTTING','SEWING'}):
            continue
        if line.issue.stock_mode != 'PUBLIC_V2':
            _fail('旧库存口径领料不在本期厂内入库范围，请先核对来源。')
        if line.issued_quantity is None or line.issued_quantity <= 0:
            _fail('实际领料数量不完整，请核对原领料单。')
        source_key = f'{product.pk}:{line.requirement_id}'
        issued[source_key] += line.issued_quantity
        source = sources.get(line.pk)
        if category == 'METAL':
            if line.issue.stock_mode != 'PUBLIC_V2':
                _fail('旧批次管材不在本期厂内入库范围。')
            snapshot = frozen_source(line)
            fact = next(item for item in facts.values() if item['requirement'].pk == line.requirement_id)
            current_line = fact['line']
            frozen = line.conversion_snapshot
            if (Decimal(str(frozen.get('cutting_length_mm',0))) != current_line.cutting_length_mm
                    or Decimal(str(frozen.get('pieces_per_bar',0))) != current_line.pieces_per_bar
                    or Decimal(str(frozen.get('raw_bar_length_m',0))) != current_line.raw_bar_length_m):
                raise Conflict('BOM 切割参数与实际已领管材不一致，不能按修改后的部位入库。')
            if source and source.source_hash != digest(snapshot):
                raise Conflict('已领管材冻结资料有变化，请核对来源。')
            consumed = source.reserved_pieces + source.dispatched_pieces if source else 0
            if source and source.status == 'CLOSED':
                consumed = source.issued_pieces - source.internal_received_pieces
            committed[source_key] += consumed
            source_facts.append((line, source, snapshot))
    history_query = InternalSemiFinishedReceiptLine.objects.filter(
        receipt__schedule_product__product_line=product)
    if exclude_receipt_id is not None:
        history_query = history_query.exclude(receipt_id=exclude_receipt_id)
    history_lines = list(history_query.select_related('receipt', 'unit').order_by('id'))
    history = []
    for row in history_lines:
        if row.receipt.plan_category != category:
            continue
        component_key = _key(product.pk, row.component_identity, category)
        history.append(ReceivedOutput(scope, component_key, f'{product.pk}:{row.input_requirement_id}',
            row.input_unit_name, row.unit.unit_name, row.quantity, row.input_quantity))
        fact = facts.get(component_key)
        if not fact or fact['identity']['identity_snapshot'] != row.attribute_snapshot:
            raise Conflict('已入库部位的实物属性或工序发生变化，请先核对原单。')
    tube_basis = None
    if category == 'SEWING':
        known_components = {str(fact['line'].component_identity) for fact in facts.values()}
        if any((row['dispatched'] or row['reserved']) and key not in known_components
               for key, row in direct_usage.items()):
            raise Conflict('已有直发或预留的裁片部位不在当前 BOM，不能丢弃历史占用。')
    if category == 'METAL':
        from apps.outsourcing.models import TubeOutsourcingLine
        pending = {str(row['component_identity']): Decimal(row['quantity']) for row in
            TubeOutsourcingLine.objects.filter(order__product_line=product,
                order__source_kind='METAL', order__status__in=['PENDING_DISPATCH', 'PROCESSING', 'COMPLETED'])
                .values('component_identity').annotate(quantity=Sum('quantity'))}
        if pending:
            from .tube_processing_services import metal_component_limits
            tube_basis = metal_component_limits(product, exclude_receipt_id=exclude_receipt_id)
            for fact in facts.values():
                committed[f'{product.pk}:{fact["requirement"].pk}'] += pending.get(str(fact['line'].component_identity), Decimal(0))
    pools = [InputPool(scope, f'{product.pk}:{identifier}', '支',
                      issued[f'{product.pk}:{identifier}'], committed[f'{product.pk}:{identifier}'])
             for identifier in sorted(requirement_ids, key=str)] if category == 'METAL' else []
    args = dict(scope_key=scope, demands=demands, inputs=pools, history=history, check_inputs=category == 'METAL')
    calculation = calculate_receipt(**args) if demands else None
    revision = digest({'plan': str(plan.pk), 'plan_revision': plan.source_revision_hash, 'bom':str(bom.pk),
        'category':category, 'demands':[asdict(item) for item in demands], 'pools':[asdict(item) for item in pools],
        'history':[asdict(item) for item in history], 'identities':[fact['identity'] for fact in facts.values()],
        'sources':[(str(line.pk), source.version if source else 0) for line, source, _ in source_facts],
        'tube_basis_revision': tube_basis['revision'] if tube_basis else None,
        **({'quantity_basis':'ORDER_REMAINING'} if category == 'SEWING' else {})})
    return dict(plan=plan, task=task, product=product, bom=bom, craft=craft, unit=unit, category=category,
                facts=facts, args=args, calculation=calculation, revision=revision, sources=source_facts, excluded=excluded,
                tube_basis=tube_basis)


def preview_data(context, actor):
    if context.get('tube_new'):
        from .tube_receipt_services import tube_preview_data
        return tube_preview_data(context, actor)
    rows = []
    for key, fact in context['facts'].items():
        identity = fact['identity']['identity_snapshot']
        row = dict(bom_line_id=str(fact['line'].pk), component_key=key, usage=str(fact['usage']), attributes=identity,
                   stage='金工完成' if context['category']=='METAL' else '车缝完成')
        row.update(_json(asdict(context['calculation'].components[key])))
        if context.get('tube_basis'):
            basis = context['tube_basis']['components'].get(str(fact['line'].component_identity))
            remaining = basis['allowance']['remaining'] if basis and basis['basis_ready'] else 0
            row['can_receive'] = str(min(Decimal(row['can_receive']), Decimal(remaining)))
        rows.append(row)
    zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type='SEMI_FINISHED').select_related('warehouse').order_by('warehouse__warehouse_name','zone_name')
    return dict(schedule_product_id=str(context['plan'].pk), plan_category=context['category'],
        etag=f'"{context["revision"]}"', production_order=context['task'].task_number,
        product=context['product'].product_name_snapshot, order_quantity=str(context['product'].quantity),
        actor=actor.display_name, receipt_date=str(timezone.localdate()), lines=rows, excluded=context['excluded'],
        zones=[dict(id=str(zone.pk), warehouse=zone.warehouse.warehouse_name, name=zone.zone_name) for zone in zones])


@stock_write_transaction
def submit_receipt(request, data):
    """车间提交厂内产出；这里只登记待确认原单，不产生库存流水。"""
    if data['plan_category'] == 'METAL':
        from .tube_receipt_services import uses_tube_receipt, submit_tube_receipt
        if uses_tube_receipt(schedule_product_id=data['schedule_product_id'], request_id=data['request_id']):
            return submit_tube_receipt(request, data)
    actor = require_operator(request, write=True)
    payload_hash = digest({'actor':str(actor.pk),'data':data})
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int.from_bytes(bytes.fromhex(digest(str(data['request_id'])))[:8], signed=True)])
    existing = InternalSemiFinishedReceipt.objects.filter(request_id=data['request_id']).first()
    if existing:
        get_object_or_404(schedule_items_for_category(request, existing.plan_category), pk=existing.schedule_product_id)
        if existing.request_payload_hash != payload_hash:
            raise Conflict('相同请求编号不能用于不同入库内容或操作人。')
        return existing, True
    context = load_receipt_context(request, data['schedule_product_id'], data['plan_category'], lock=True)
    if context.get('tube_new'):
        # 等待统一产品锁期间可能出现首笔新口径记录，继续使用新口径办理。
        from .tube_receipt_services import submit_tube_receipt
        data = {**data, 'lines': sorted([{'bom_line_id': row['bom_line_id'], 'quantity': int(row['quantity'])}
            for row in data['lines']], key=lambda row: str(row['bom_line_id']))}
        return submit_tube_receipt(request, data)
    expected = request.headers.get('If-Match')
    if not expected:
        raise PreconditionRequired()
    if expected != f'"{context["revision"]}"':
        raise PreconditionFailed('领料、外发占用或累计入库已变化，请刷新可入数量后重试。')
    by_id = {str(fact['line'].pk):key for key,fact in context['facts'].items()}
    requested = {}
    for item in data['lines']:
        key = by_id.get(str(item['bom_line_id']))
        if not key or key in requested:
            _fail('入库明细不属于本计划、需走喷塑外发，或部位重复。')
        requested[key] = item['quantity']
    calculation = validate_receipt(**context['args'], requested=requested)
    if context.get('tube_basis'):
        from .tube_processing_services import assert_tube_quantity_available
        assert_tube_quantity_available(product_line_id=context['product'].pk,
            requested={str(context['facts'][key]['line'].component_identity): quantity for key, quantity in requested.items()},
            expected_revision=context['tube_basis']['revision'])
    zone = get_object_or_404(WarehouseZone, pk=data['zone_id'], status='ACTIVE',
                            warehouse__status='ACTIVE', warehouse__warehouse_type='SEMI_FINISHED')
    now = timezone.now()
    header = InternalSemiFinishedReceipt.objects.create(receipt_number=next_business_number('INTERNAL_SEMI_RECEIPT'),
        request_id=data['request_id'], request_payload_hash=payload_hash, schedule_product=context['plan'],
        completed_craft=context['craft'], plan_category=context['category'], receipt_date=data['receipt_date'],
        zone=zone, actor_employee=actor, status=InternalReceiptStatus.PENDING,
        submitted_by_employee=actor, submitted_at=now, source_revision_hash=context['revision'], remark=data.get('remark',''),
        source_snapshot={'production_order':context['task'].task_number,'product':context['product'].product_name_snapshot,
                         'order_quantity':str(context['product'].quantity),'bom_id':str(context['bom'].pk),
                         'plan_category':context['category'],'schedule_id':str(context['plan'].schedule_id),
                         **({'quantity_basis':'ORDER_REMAINING'} if context['category'] == 'SEWING' else {})})
    for key, quantity in requested.items():
        fact = context['facts'][key]
        allowance = calculation.components[key]
        row_id = uuid.uuid4()
        demand = next(item for item in context['args']['demands'] if item.component_key == key)
        InternalSemiFinishedReceiptLine.objects.create(id=row_id,receipt=header,bom_line=fact['line'],
            component_identity=fact['line'].component_identity,unit=context['unit'],input_requirement=fact['requirement'],
            input_unit_name=demand.input_unit,quantity=quantity,input_per_output=demand.input_per_output,
            input_quantity=allowance.consumes_input,required_quantity_snapshot=allowance.required,
            received_before=allowance.received,received_after=allowance.received_after,stock_movement=None,
            attribute_snapshot=fact['identity']['identity_snapshot'],input_snapshot=_json(asdict(allowance)))
    from .notification_events import internal_receipt_submitted
    internal_receipt_submitted(header, actor)
    return header, False


def _receipt_requested(receipt):
    return {str(line.bom_line_id): line.quantity for line in receipt.lines.select_related('bom_line').all()}


@stock_write_transaction
def confirm_receipt(request, receipt_id):
    """仓库确认待入库原单；成功后才写公共库存和通知。"""
    actor = require_operator(request, permission='confirm_internalsemifinishedreceipt')
    receipt = get_object_or_404(InternalSemiFinishedReceipt.objects.select_related('schedule_product'), pk=receipt_id)
    from .tube_processing_services import lock_tube_product_scope
    lock_tube_product_scope(receipt.schedule_product.product_line_id)
    receipt = get_object_or_404(InternalSemiFinishedReceipt.objects.select_for_update(of=('self',)).select_related(
        'schedule_product', 'zone', 'completed_craft'), pk=receipt_id)
    get_object_or_404(receipt_plans_for_category(request, receipt.plan_category, confirmation=True), pk=receipt.schedule_product_id)
    if receipt.status == InternalReceiptStatus.CONFIRMED:
        return receipt, True
    if receipt.status != InternalReceiptStatus.PENDING:
        raise Conflict('该入库原单状态不允许确认。')
    if receipt.source_snapshot.get('quantity_basis') == 'WORK_REPORT_MINIMUM':
        from .tube_receipt_services import confirm_tube_receipt
        return confirm_tube_receipt(request, receipt)
    context = load_receipt_context(request, receipt.schedule_product_id, receipt.plan_category,
                                   lock=True, exclude_receipt_id=receipt.pk, confirmation=True)
    expected = request.headers.get('If-Match')
    if not expected:
        raise PreconditionRequired()
    if expected != f'"{receipt.source_revision_hash}"':
        raise PreconditionFailed('待入库原单版本已变化，请刷新后重试。')
    if (receipt.source_snapshot.get('bom_id') != str(context['bom'].pk)
            or receipt.completed_craft_id != context['craft'].pk):
        raise Conflict('BOM或完成工序已变化，请删除待入库原单后重新提交。')
    by_id = {str(fact['line'].pk): key for key, fact in context['facts'].items()}
    requested, pending_lines = {}, {}
    for item in receipt.lines.select_related('bom_line').all():
        key = by_id.get(str(item.bom_line_id))
        if not key or key in requested:
            _fail('待确认明细不属于当前计划或部位重复。')
        fact = context['facts'][key]
        demand = next(row for row in context['args']['demands'] if row.component_key == key)
        if (item.component_identity != fact['line'].component_identity
                or item.attribute_snapshot != fact['identity']['identity_snapshot']
                or item.unit_id != context['unit'].pk or item.input_requirement_id != fact['requirement'].pk
                or item.input_unit_name != demand.input_unit or item.input_per_output != demand.input_per_output):
            raise Conflict('部位实物属性或投入依据已变化，请删除待入库原单后重新提交。')
        requested[key] = item.quantity
        pending_lines[key] = item
    calculation = validate_receipt(**context['args'], requested=requested)
    if context.get('tube_basis'):
        from .tube_processing_services import assert_tube_quantity_available
        assert_tube_quantity_available(product_line_id=context['product'].pk,
            requested={str(context['facts'][key]['line'].component_identity): quantity
                       for key, quantity in requested.items()},
            expected_revision=context['tube_basis']['revision'], exclude_receipt_id=receipt.pk)
    for key, quantity in requested.items():
        fact = context['facts'][key]
        allowance = calculation.components[key]
        if context['category'] == 'METAL':
            remaining = int(quantity)
            for issue_line, source, snapshot in context['sources']:
                if issue_line.requirement_id != fact['requirement'].pk or (source and source.status == 'CLOSED'):
                    continue
                if source is None:
                    source = MetalProcessingSource.objects.create(issue_line=issue_line, source_snapshot=snapshot,
                        source_hash=digest(snapshot), issued_pieces=snapshot['issued_pieces'])
                available = source.issued_pieces-source.internal_received_pieces-source.reserved_pieces-source.dispatched_pieces
                take = min(remaining, available)
                source.internal_received_pieces += take
                source.completed_pieces = max(source.completed_pieces,
                    source.internal_received_pieces+source.reserved_pieces+source.dispatched_pieces)
                source.version += 1
                source.save(update_fields=['internal_received_pieces','completed_pieces','version','updated_at'])
                remaining -= take
                if remaining == 0:
                    break
            if remaining:
                raise Conflict('实际已领投入不足，本次入库已全部回滚。')
        line = pending_lines[key]
        movement = credit_public_stock(identity=fact['identity'], zone=receipt.zone, quantity=quantity,
            source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk, source_line_id=line.pk,
            actor_employee=actor, production_task=context['task'], product_line=context['product'], bom_line=fact['line'],
            snapshot={**receipt.source_snapshot, 'receipt_number':receipt.receipt_number,
                      'receipt_date':str(receipt.receipt_date), 'actor_name':actor.display_name,
                      'source':'厂内入库', 'remark':receipt.remark})
        line.stock_movement = movement
        line.save(update_fields=['stock_movement','updated_at'])
    receipt.status = InternalReceiptStatus.CONFIRMED
    receipt.confirmed_by_employee = actor
    receipt.confirmed_at = timezone.now()
    receipt.save(update_fields=['status','confirmed_by_employee','confirmed_at','updated_at'])
    from .notification_events import internal_receipt_confirmed
    internal_receipt_confirmed(receipt, actor)
    return receipt, False


@stock_write_transaction
def delete_pending_receipt(request, receipt_id):
    require_operator(request, permission='delete_internalsemifinishedreceipt')
    receipt = get_object_or_404(InternalSemiFinishedReceipt.objects.select_related('schedule_product'), pk=receipt_id)
    from .tube_processing_services import lock_tube_product_scope
    # 与提交、确认共用产品额度锁；原单删除与额度释放一起提交。
    lock_tube_product_scope(receipt.schedule_product.product_line_id)
    receipt = get_object_or_404(InternalSemiFinishedReceipt.objects.select_for_update(of=('self',)), pk=receipt_id)
    if receipt.status != InternalReceiptStatus.PENDING:
        raise Conflict('已入库记录不能删除。')
    if not can_delete_pending_receipt(request, receipt, receipt.plan_category):
        raise PermissionDenied('只能删除本人提交的待入库记录。')
    expected = request.headers.get('If-Match')
    if not expected:
        raise PreconditionRequired()
    if expected != f'"{receipt.source_revision_hash}"':
        raise PreconditionFailed()
    if (receipt.confirmed_at is not None or receipt.lines.filter(stock_movement__isnull=False).exists()
            or PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk).exists()):
        raise Conflict('入库记录已有库存流水，不能删除。')
    try:
        # 仅本服务在行锁和状态核验后绕过禁止历史删除的模型保护。
        from apps.core.audit import write_audit_log
        write_audit_log(object_type='INTERNAL_SEMI_RECEIPT', object_id=receipt.pk, action='DELETED',
            actor_employee=request.employee, context_type='PRODUCTION_SCHEDULE',
            context_id=receipt.schedule_product.schedule_id, request=request,
            before_data={'receipt_number': receipt.receipt_number,
                         'product_line_id': str(receipt.schedule_product.product_line_id),
                         'submitted_at': receipt.submitted_at or receipt.created_at,
                         'submitted_by_name': (receipt.submitted_by_employee or receipt.actor_employee).display_name,
                         'status': receipt.status})
        models.QuerySet.delete(receipt.lines.all())
        models.Model.delete(receipt)
    except ProtectedError as error:
        raise Conflict('入库记录已有业务引用，不能删除。') from error
