"""委外总单、实际外发与独立入库；共同产品锁后锁总单，数量在同一事务累加。"""
from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.inventory.public_stock_cutover import stock_write_transaction
from apps.inventory.public_stock_identity import validate_public_identity
from apps.inventory.public_stock_services import credit_public_stock

from .material_flow import lock_request
from .models import OutsourcingFactory, TubeOutsourcingOrder, TubeOutsourcingLine, TubePlanReceipt, TubePlanReceiptLine
from .plan_selectors import plan_quantities
from .services import _json_hash
from .processing_materials import processing_line_fields, require_saved_processing_materials
from apps.inventory.processing_material_snapshots import KILOGRAM_TUBE_PROCESSING_MESSAGE
from .tube_kinds import CUTTING_FIELDS, CUTTING_SOURCES, lock_source_product, output_unit, source_category
from .tube_selectors import (CREATE_PERMISSION, DISPATCH_PERMISSION, RETURN_PERMISSION,
    require_saved_order_access, require_tube_feature, source_factories, source_product, source_zone)
from .tube_services import _json


def plan_source_context(*, schedule_product, source_kind, zone, craft, for_plan=False):
    if source_kind in CUTTING_SOURCES:
        from .cutting_sources import cutting_source_context
        context = cutting_source_context(schedule_product=schedule_product, source_kind=source_kind,
            zone=zone, craft=craft, plan_mode=True)
    else:
        from apps.inventory.tube_outsourcing_limits import tube_source_context
        context = tube_source_context(schedule_product=schedule_product, source_kind=source_kind, zone=zone, plan_mode=True)
    if for_plan:
        # 计划的版本只依赖BOM和实物身份，不让暂时库存/报工变化限制预先建单。
        for row in context['rows']:
            row['max_quantity'] = row['order_required'] if not row['blockers'] else '0'
        context['source_revision'] = _json_hash(_json({'bom_id': context['bom_id'],
            'source_kind': source_kind, 'craft_id': craft.pk,
            'rows': [{'component_identity': row['component_identity'], 'bom_line_id': row['bom_line_id'],
                'order_required': row['order_required'], 'output': row['snapshot'].get('public_output_identity'),
                'blockers': row['blockers']} for row in context['rows']]}))
    return context


@stock_write_transaction
def create_plan(*, data, request):
    require_tube_feature()
    lock_request('tube-create', data['client_request_id'])
    payload_hash = _json_hash(data)
    existing = TubeOutsourcingOrder.objects.filter(client_request_id=data['client_request_id']).first()
    if existing:
        require_saved_order_access(request, existing, CREATE_PERMISSION)
        if not existing.is_plan or existing.request_payload_hash != payload_hash:
            raise Conflict('相同提交标识已用于不同委外内容。')
        return existing, False
    product, craft = source_product(request, data['schedule_product_id'], CREATE_PERMISSION,
        source_kind=data['source_kind'], craft_id=data.get('craft_id'))
    lock_source_product(product.product_line_id, data['source_kind'])
    boms = list(Bom.objects.filter(product_line_id=product.product_line_id, archived_at__isnull=True)
        .order_by('pk').select_for_update(of=('self',)))
    bom_lines = {str(line.pk): line for line in BomLine.objects.filter(section__bom__in=boms)
        .select_related('section').order_by('pk').select_for_update(of=('self',))}
    product, craft = source_product(request, data['schedule_product_id'], CREATE_PERMISSION,
        source_kind=data['source_kind'], craft_id=data.get('craft_id'))
    zone = source_zone(data['source_kind'], data.get('zone_id'))
    context = plan_source_context(schedule_product=product, source_kind=data['source_kind'], zone=zone, craft=craft, for_plan=True)
    selected_components = {str(row['component_identity']) for row in data['lines']}
    if any(row['component_identity'] in selected_components and KILOGRAM_TUBE_PROCESSING_MESSAGE in row['blockers']
           for row in context['rows']):
        raise ValidationError({'lines': KILOGRAM_TUBE_PROCESSING_MESSAGE})
    if not context['ready']:
        raise ValidationError({'lines': '；'.join(context['blockers']) or '当前BOM部件或实物身份不完整。'})
    if data['source_revision'] != context['source_revision']:
        raise Conflict('BOM或加工身份已变化，请刷新后重新保存。')
    if TubeOutsourcingOrder.objects.filter(is_plan=True, product_line=product.product_line, craft=craft).exclude(status='CANCELLED').exists():
        raise ValidationError({'detail': '该产品与工艺已有有效委外总单，请在原总单登记发货或补料。'})
    requested_materials = data.get('materials', [])
    if requested_materials and data['source_kind'] not in CUTTING_SOURCES:
        raise ValidationError({'materials': '管材委外总单不再选择附带五金。'})
    factory_ids = source_factories(request, craft, CREATE_PERMISSION).values('pk')
    factories = {value.pk: value for value in OutsourcingFactory.objects.filter(pk__in=factory_ids).select_for_update(of=('self',))}
    if any(row['factory_id'] not in factories for row in [*data['lines'], *requested_materials]):
        raise ValidationError({'lines': '加工厂不存在、已停用或无对应工艺权限。'})
    planned_materials = []
    if requested_materials:
        from .tube_materials import tube_material_context
        material_context = tube_material_context(product, source_kind=data['source_kind'], plan_mode=True, for_plan=True)
        available = {row['bom_line_id']: row for row in material_context['material_rows']}
        for entered in requested_materials:
            material = available.get(str(entered['bom_line_id']))
            if not material or material['blockers'] or not any(str(zone['zone_id']) == str(entered['zone_id']) for zone in material['zones']):
                raise ValidationError({'materials': '辅料或来源库区不属于当前产品的有效材料。'})
            planned_materials.append({**_json(entered), 'name': material['name'], 'unit': material['unit'],
                'material_catalog_id': material.get('material_catalog_id'),
                'material_selection_snapshot': material.get('material_selection_snapshot', {}),
                'factory_name': factories[entered['factory_id']].name})
    rows = {row['component_identity']: row for row in context['rows']}
    lines = []
    for entered in data['lines']:
        row = rows.get(str(entered['component_identity']))
        if not row or row['blockers'] or Decimal(row['order_required']) <= 0:
            raise ValidationError({'lines': '所选部件不属于有效BOM或加工身份不完整。'})
        validate_public_identity(row['snapshot']['public_output_identity'])
        snapshot = {**row['snapshot'], **{key: row.get(key) for key in (
            'part_name', 'material', 'specification', 'thickness', 'cutting_length_mm', 'raw_color',
            'spray_color', 'order_required', 'pieces_per_bar', 'raw_bar_length_m', *CUTTING_FIELDS)},
            'factory_name': factories[entered['factory_id']].name}
        lines.append(TubeOutsourcingLine(bom_line_id=row['bom_line_id'], component_identity=entered['component_identity'],
            **processing_line_fields(bom_line=bom_lines[row['bom_line_id']], row=row, craft=craft),
            factory_id=entered['factory_id'], quantity=entered['quantity'], unit_price=entered['unit_price'],
            stock_quantity=None, input_identity=_json(row['input_identity']), snapshot=_json(snapshot)))
    order = TubeOutsourcingOrder.objects.create(is_plan=True, order_number=next_business_number('OUTSOURCING_ORDER'),
        schedule_product=product, product_line=product.product_line, bom_id=context['bom_id'], craft=craft,
        source_kind=data['source_kind'], zone=zone, planned_dispatch_date=data['planned_dispatch_date'],
        expected_return_date=data['expected_return_date'], remark=data.get('remark', ''),
        client_request_id=data['client_request_id'], request_payload_hash=payload_hash,
        source_revision_hash=context['source_revision'], source_snapshot=_json({**context, 'planned_materials': planned_materials}),
        created_by_employee=request.employee, updated_by_employee=request.employee)
    for line in lines:
        line.order = order
    TubeOutsourcingLine.objects.bulk_create(lines)
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='PLAN_CREATED',
        actor_employee=request.employee, after_data={'order_number': order.order_number,
            'planned_quantity': sum(line.quantity for line in lines), 'is_plan': True},
        context_type='PRODUCTION_SCHEDULE', context_id=product.schedule_id, request=request)
    from apps.wecom.workshop_notifications import outsourcing_created
    outsourcing_created(order, request.employee, tube=True)
    return order, True


def _lock_plan(order_id, request, permission):
    require_tube_feature()
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    initial = get_object_or_404(TubeOutsourcingOrder, pk=order_id, is_plan=True)
    require_saved_order_access(request, initial, permission)
    lock_source_product(initial.product_line_id, initial.source_kind)
    order = TubeOutsourcingOrder.objects.select_for_update(of=('self',)).select_related('schedule_product__schedule', 'craft').get(pk=order_id)
    require_saved_order_access(request, order, permission)
    require_matching_etag(request, order)
    if order.status == 'CANCELLED':
        raise Conflict('已取消的委外总单不能再办理。')
    return order


def _update_plan(order, request):
    quantities = plan_quantities([order])[str(order.pk)]['summary']
    order.status = ('PENDING_DISPATCH' if not int(quantities['dispatched_quantity']) and not int(quantities['received_quantity'])
                    else 'COMPLETED' if quantities['receipt_progress'] >= 100 else 'PROCESSING')
    order.version += 1
    order.updated_by_employee = request.employee
    order.save(update_fields=['status', 'version', 'updated_by_employee', 'updated_at'])


@stock_write_transaction
def update_plan_quantity(*, order_id, data, request):
    order = _lock_plan(order_id, request, 'outsourcing.change_outsourcingorder')
    lines = list(order.lines.select_for_update(of=('self',)).order_by('pk'))
    entered = {str(row['order_line_id']): row['quantity'] for row in data['lines']}
    if len(entered) != len(data['lines']) or set(entered) != {str(line.pk) for line in lines}:
        raise ValidationError({'lines': '须完整提交原委外总单部件，不能增加、删除或重复部件。'})
    changed = [line for line in lines if entered[str(line.pk)] != line.quantity]
    if not changed:
        return order
    quantities = plan_quantities([order])[str(order.pk)]['lines']
    before, after = [], []
    for line in changed:
        key = str(line.pk)
        quantity = entered[key]
        name = line.snapshot.get('part_name', '部件')
        if quantity <= 0 or quantity < int(quantities[key]['dispatched_quantity']):
            raise ValidationError({'lines': f'“{name}”计划数量须为正整数，且不能少于累计已外发数量。'})
        before.append({'order_line_id': key, 'quantity': line.quantity})
        after.append({'order_line_id': key, 'quantity': quantity})
    for line in changed:
        line.quantity = entered[str(line.pk)]
        line.save(update_fields=['quantity', 'updated_at'])
    order.version += 1
    order.updated_by_employee = request.employee
    order.save(update_fields=['version', 'updated_by_employee', 'updated_at'])
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='PLAN_QUANTITY_UPDATED',
        actor_employee=request.employee, before_data={'lines': before},
        after_data={'lines': after, 'version': order.version},
        context_type='PRODUCTION_SCHEDULE', context_id=order.schedule_product.schedule_id, request=request)
    return order


@stock_write_transaction
def dispatch_plan(*, order_id, data, request):
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    lock_request('plan-dispatch', data['client_request_id'])
    payload_hash = _json_hash({'order_id': str(order_id), 'actor': str(request.employee.pk), 'data': data})
    existing = TubeOutsourcingOrder.objects.select_related('plan').filter(client_request_id=data['client_request_id']).first()
    if existing:
        if existing.plan_id != order_id or existing.source_snapshot.get('plan_dispatch_payload_hash') != payload_hash:
            raise Conflict('相同提交标识已用于不同的委外发货。')
        require_saved_order_access(request, existing.plan, DISPATCH_PERMISSION)
        return existing.plan, False
    order = _lock_plan(order_id, request, DISPATCH_PERMISSION)
    if source_category(order.source_kind) != source_category(data['source_kind']):
        raise ValidationError({'source_kind': '实际发货来源与总单加工类别不一致。'})
    expected = {str(line.component_identity): line for line in order.lines.all()}
    if any(str(line['component_identity']) not in expected for line in data['lines']):
        raise ValidationError({'lines': '只能发出本委外总单包含的部件。'})
    quantities = plan_quantities([order])[str(order.pk)]['lines']
    for entered in data['lines']:
        target = expected[str(entered['component_identity'])]
        remaining = max(target.quantity - int(quantities[str(target.pk)]['dispatched_quantity']), 0)
        if entered['quantity'] > remaining:
            raise ValidationError({'lines': f'“{target.snapshot.get("part_name", "部件")}”本次最多可发{remaining}{output_unit(order.source_kind)}，累计实发不能超过委外总单填写数量。'})
    from .tube_services import create_tube_order
    from .tube_action_services import confirm_tube_action
    batch_data = {**data, 'is_plan': False, 'schedule_product_id': order.schedule_product_id,
        'craft_id': order.craft_id, 'source_revision': '', 'planned_dispatch_date': data['actual_dispatch_date'],
        'expected_return_date': max(order.expected_return_date, data['actual_dispatch_date'])}
    batch, _ = create_tube_order(data=batch_data, request=request, plan=order)
    planned_materials = {row['bom_line_id']: row for row in order.source_snapshot.get('planned_materials', [])}
    for material in batch.materials.all():
        planned = planned_materials.get(str(material.bom_line_id))
        if planned and planned.get('material_catalog_id') and (
                str(material.material_catalog_id) != planned['material_catalog_id']
                or material.material_selection_snapshot != planned['material_selection_snapshot']):
            raise Conflict('实际发出附带料与总单保存的材料不一致，请核对BOM。')
    for line in batch.lines.all():
        target = expected[str(line.component_identity)]
        if _json_hash(line.snapshot.get('public_output_identity')) != _json_hash(target.snapshot.get('public_output_identity')):
            raise Conflict('实际发货的加工产物与总单冻结身份不一致，请核对BOM。')
    batch.source_snapshot['plan_dispatch_payload_hash'] = payload_hash
    batch.save(update_fields=['source_snapshot'])
    confirm_tube_action(order_id=batch.pk, kind='DISPATCH', data={'client_request_id': data['client_request_id'],
        'actual_dispatch_date': data['actual_dispatch_date'], 'remark': data.get('remark', '')}, request=request, plan_dispatch=True)
    _update_plan(order, request)
    return order, True


@stock_write_transaction
def receive_plan(*, order_id, data, request):
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    lock_request('plan-receipt', data['client_request_id'])
    payload_hash = _json_hash({'order_id': str(order_id), 'actor': str(request.employee.pk), 'data': data})
    existing = TubePlanReceipt.objects.select_related('order').filter(client_request_id=data['client_request_id']).first()
    if existing:
        if existing.order_id != order_id or existing.request_payload_hash != payload_hash:
            raise Conflict('相同提交标识已用于不同的委外入库。')
        require_saved_order_access(request, existing.order, RETURN_PERMISSION)
        return existing.order, False
    order = _lock_plan(order_id, request, RETURN_PERMISSION)
    lines = {line.pk: line for line in order.lines.select_for_update(of=('self',)).order_by('pk')}
    quantities = plan_quantities([order])[str(order.pk)]['lines']
    pending = []
    for entered in data['lines']:
        line = lines.get(entered['order_line_id'])
        if line is None:
            raise ValidationError({'lines': '入库部件不属于该委外总单。'})
        quantity = entered['received_quantity']
        if quantity > int(quantities[str(line.pk)]['receivable_quantity']):
            raise ValidationError({'lines': f'“{line.snapshot.get("part_name", "部件")}”累计入库不能超过累计实际外发。'})
        if not quantity:
            continue
        require_saved_processing_materials(line)
        identity = validate_public_identity(line.snapshot['public_output_identity'])
        if identity['identity_snapshot']['completed_craft']['id'] != str(order.craft_id):
            raise Conflict('总单冻结加工身份不匹配。')
        row = TubePlanReceiptLine(order_line=line, received_quantity=quantity, zone_id=entered['zone_id'], snapshot=line.snapshot)
        pending.append((row, entered, identity))
    if not pending:
        raise ValidationError({'lines': '本次至少填写一个大于0的入库数量。'})
    from .tube_receipt_services import _lock_receipt_stock
    locations = _lock_receipt_stock(pending)
    for row, entered, _ in pending:
        zone = locations[entered['zone_id']]
        if zone.warehouse_id != data['warehouse_id'] or zone.status != 'ACTIVE' or zone.warehouse.status != 'ACTIVE' or zone.warehouse.warehouse_type != 'SEMI_FINISHED':
            raise ValidationError({'warehouse_id': '入库库区必须属于所选的有效半成品仓。'})
        row.zone = zone
    receipt = TubePlanReceipt.objects.create(order=order, receipt_number=next_business_number('TUBE_OUTSOURCING_RECEIPT'),
        client_request_id=data['client_request_id'], request_payload_hash=payload_hash, receipt_date=data['receipt_date'],
        warehouse_id=data['warehouse_id'], actor_employee=request.employee, remark=data.get('remark', ''))
    for row, _, identity in pending:
        row.receipt = receipt
        row.stock_movement = credit_public_stock(identity=identity, zone=row.zone, quantity=row.received_quantity,
            source_type='TUBE_OUTSOURCING_RETURN', source_id=receipt.pk, source_line_id=row.pk, actor_employee=request.employee,
            production_task=order.schedule_product.schedule.production_task_id, product_line=order.product_line_id,
            bom_line=row.order_line.bom_line_id, snapshot=_json({'order_id': order.pk, 'order_number': order.order_number,
                'receipt_number': receipt.receipt_number, 'receipt_date': receipt.receipt_date, 'is_plan': True,
                'source_kind': order.source_kind,
                'input_material_selection_snapshot': row.order_line.input_material_selection_snapshot,
                'output_material_selection_snapshot': row.order_line.output_material_selection_snapshot,
                'raw_color': row.order_line.snapshot.get('raw_color', ''),
                'spray_color': row.order_line.snapshot.get('spray_color', ''),
                'quantity': row.received_quantity, 'public_identity': identity, 'remark': receipt.remark}))
        row.save(force_insert=True)
    previous_status = order.status
    _update_plan(order, request)
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='PLAN_RECEIVED',
        actor_employee=request.employee, after_data={'receipt_id': str(receipt.pk), 'receipt_number': receipt.receipt_number,
            'quantity': sum(row.received_quantity for row, _, _ in pending), 'version': order.version,
            'previous_status': previous_status},
        context_type='PRODUCTION_SCHEDULE', context_id=order.schedule_product.schedule_id, request=request)
    return order, True
