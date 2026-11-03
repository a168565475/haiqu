"""仅更正新委外总单的既有收发记录，保留原单号及所有库存事件。"""
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control import module_policy
from apps.core.api.concurrency import PreconditionRequired
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.models import MaterialStockMovement, PublicStockMovement
from apps.inventory.public_stock_cutover import stock_write_transaction
from apps.material_issues.models import OrderMaterialRequirement

from .material_flow import lock_request
from .models import TubeOutsourcingOrder, TubePlanReceipt, TubePlanRecordCorrection
from .plan_correction_stock import (DISPATCH_SOURCE, RECEIPT_SOURCE, MATERIAL_SOURCE,
    apply_stock_events, effective_stock_quantity, stock_event)
from .plan_selectors import plan_quantities
from .plan_services import _lock_plan, _update_plan
from .services import _json_hash
from .tube_kinds import DIRECT_SOURCES, output_unit
from .tube_selectors import DISPATCH_PERMISSION, RETURN_PERMISSION, require_saved_order_access, require_tube_feature
from .tube_services import _json, _stock_amount
from .tube_materials import material_dispatch_blockers


class CorrectionRequestConflict(Conflict):
    api_error_code = 'IDEMPOTENCY_CONFLICT'


def correction_data(record):
    return {'id': str(record.pk), 'client_request_id': str(record.client_request_id),
        'record_kind': record.record_kind, 'record_id': str(record.record_id),
        'operation': record.operation, 'created_at': record.created_at.isoformat()}


def _permission(request, order, kind):
    permission = DISPATCH_PERMISSION if kind == 'DISPATCH' else RETURN_PERMISSION
    if not module_policy.has_permission(request, permission):
        raise PermissionDenied('当前账号没有更正此类收发记录的权限。')
    require_saved_order_access(request, order, permission)
    return permission


def find_record_correction(*, order_id, request_id, request):
    require_tube_feature()
    record = get_object_or_404(TubePlanRecordCorrection.objects.select_related('order'),
                              order_id=order_id, client_request_id=request_id, order__is_plan=True)
    _permission(request, record.order, record.record_kind)
    return record


def _quantities(data, components):
    if data['operation'] == 'DELETE':
        return {str(key): 0 for key in components}
    entered = {str(row['component_identity']): row['quantity'] for row in data['lines']}
    if len(entered) != len(data['lines']) or set(entered) != {str(key) for key in components}:
        raise ValidationError({'lines': '须完整提交原部件集合，不得添加、遗漏或重复部件。'})
    if any(type(value) is not int or value <= 0 or value > 99999999999999 for value in entered.values()):
        raise ValidationError({'lines': '已有部件数量必须为有效正整数。'})
    return entered


def _original_movement(model, source, record_id, line_id):
    movement = model.objects.filter(source_type=source, source_id=record_id, source_line_id=line_id,
        direction='OUT').select_related('balance__zone__warehouse', 'balance__unit', 'balance__raw_material').first()
    if movement is None:
        raise Conflict('原外发库存凭证缺失，不能自动更正。')
    return movement


def _requirement_deltas(deltas, order):
    if not deltas:
        return
    rows = {str(row.pk): row for row in OrderMaterialRequirement.objects.filter(pk__in=deltas)
            .order_by('pk').select_for_update(of=('self',))}
    if set(rows) != set(deltas):
        raise Conflict('原材料需求副账缺失，不能自动更正。')
    for key, (delta, expected_raw, expected_catalog, expected_unit, component) in deltas.items():
        row = rows[key]
        if (row.production_task_id != order.product_line.production_task_id
                or row.product_line_id not in {None, order.product_line_id}
                or str(row.raw_material_id) != str(expected_raw)
                or str(row.material_catalog_id) != str(expected_catalog)
                or str(row.unit_id) != str(expected_unit)
                or (component is not None and row.component_identity != component)):
            raise Conflict('原材料需求副账身份已变化，不能自动更正。')
        if row.outsourcing_issued_quantity + delta < 0:
            raise Conflict('原材料需求已外发数量不足，不能重复恢复。')
        row.outsourcing_issued_quantity += delta
        row.save(update_fields=['outsourcing_issued_quantity', 'updated_at'])


def _add_requirement(deltas, requirement, delta, *, raw_id, catalog_id, unit_id, component=None):
    key = str(requirement.pk)
    expected = (raw_id, catalog_id, unit_id, component)
    if key in deltas and tuple(str(value) for value in deltas[key][1:]) != tuple(str(value) for value in expected):
        raise Conflict('同一材料需求副账对应不同保存身份，不能自动更正。')
    previous = deltas.get(key, (Decimal(0), None, None, None))[0]
    deltas[key] = (previous + delta, raw_id, catalog_id, unit_id, component)


def _dispatch(order, correction, data, request):
    batch = get_object_or_404(TubeOutsourcingOrder.objects.select_for_update(of=('self',)).select_related('zone'),
                             pk=data['record_id'], plan=order, is_plan=False)
    _permission(request, batch, 'DISPATCH')
    if batch.status not in {'PROCESSING', 'COMPLETED'}:
        raise Conflict('只有有效已发出的总单记录可以更正。')
    action = batch.actions.select_for_update().filter(kind='DISPATCH').first()
    if action is None:
        raise Conflict('原外发确认凭证缺失，不能自动更正。')
    lines = list(batch.lines.select_for_update(of=('self',)).order_by('pk'))
    materials = list(batch.materials.select_for_update(of=('self',)).select_related(
        'requirement', 'zone', 'unit', 'raw_material').order_by('pk'))
    entered = _quantities(data, [line.component_identity for line in lines])
    values = plan_quantities([order])[str(order.pk)]['lines']
    parent = {str(line.component_identity): line for line in order.lines.all()}
    history = list(order.record_corrections.filter(record_kind='DISPATCH', record_id=batch.pk))
    before = {'number': batch.order_number, 'business_date': str(action.actual_dispatch_date),
        'remark': batch.remark, 'status': batch.status,
        'lines': [{'id': str(line.pk), 'component_identity': str(line.component_identity),
            'quantity': line.quantity, 'stock_quantity': line.stock_quantity, 'snapshot': line.snapshot} for line in lines],
        'materials': [{'id': str(line.pk), 'quantity': str(line.quantity), 'snapshot': line.snapshot} for line in materials]}
    correction.before_data = _json(before)
    correction.after_data = _json({**before, 'operation': data['operation'],
        **({'business_date': data['business_date']} if data['operation'] == 'UPDATE' else {})})
    events, requirements = [], {}
    new_values = {}
    original_ids = {row.get('line_id'): row.get('movement_id') for row in action.snapshot.get('movements', [])}
    for line in lines:
        key = str(line.component_identity)
        target = parent.get(key)
        if target is None:
            raise Conflict('外发部件与总单保存部件不一致。')
        quantity = entered[key]
        value = values[str(target.pk)]
        dispatched_quantity = int(value['dispatched_quantity']) - line.quantity + quantity
        if dispatched_quantity < int(value['received_quantity']):
            raise ValidationError({'lines': f'“{line.snapshot.get("part_name", "部件")}”更正后的累计实发不能少于累计实收。'})
        if quantity > line.quantity and dispatched_quantity > target.quantity:
            raise ValidationError({'lines': f'“{line.snapshot.get("part_name", "部件")}”更正后的累计实发不能超过委外总单填写的{target.quantity}{output_unit(order.source_kind)}。'})
        current_stock, current_meters = _stock_amount(batch.source_kind, line.quantity, line.snapshot)
        if current_stock != line.stock_quantity or (batch.source_kind == 'RAW_PIPE'
                and Decimal(str(line.snapshot.get('meters', 'NaN'))) != Decimal(current_meters)):
            raise Conflict('原外发数量与保存的库存换算不一致，不能自动更正。')
        stock, meters = _stock_amount(batch.source_kind, quantity, line.snapshot)
        new_values[line.pk] = (quantity, stock, meters)
        if batch.source_kind in DIRECT_SOURCES:
            continue
        original = _original_movement(PublicStockMovement, 'TUBE_OUTSOURCING_DISPATCH', batch.pk, line.pk)
        if (original_ids.get(str(line.pk)) != str(original.pk) or original.balance.zone_id != batch.zone_id
                or original.snapshot.get('public_identity') != line.input_identity
                or effective_stock_quantity(original, history, line_id=line.pk, source_type=DISPATCH_SOURCE) != line.stock_quantity):
            raise Conflict('原外发数量与库存凭证不一致，不能自动更正。')
        events.append(stock_event(correction, original, Decimal(line.stock_quantity) - stock,
                                  line_id=line.pk, source_type=DISPATCH_SOURCE))
        if batch.source_kind == 'RAW_PIPE':
            requirement = OrderMaterialRequirement.objects.filter(pk=line.snapshot.get('requirement_id')).first()
            if requirement is None or requirement.component_identity != line.component_identity:
                raise Conflict('原管材需求副账缺失或部件不一致。')
            _add_requirement(requirements, requirement, quantity - line.quantity,
                raw_id=line.input_identity.get('raw_material_id'), catalog_id=line.input_material_catalog_id,
                unit_id=line.snapshot['public_output_identity']['unit_id'], component=line.component_identity)
    if data['operation'] == 'DELETE':
        blockers = material_dispatch_blockers(batch, action)
        if blockers:
            raise Conflict('；'.join(blockers))
        saved_materials = {row.get('material_id'): row.get('movement_id')
                           for row in action.snapshot.get('material_movements', [])}
        for material in materials:
            model = PublicStockMovement if material.material_catalog_id else MaterialStockMovement
            original = _original_movement(model, 'TUBE_OUTSOURCING_MATERIAL_DISPATCH', batch.pk, material.pk)
            if (saved_materials.get(str(material.pk)) != str(original.pk) or original.quantity != material.quantity
                    or original.balance.zone_id != material.zone_id or original.balance.unit_id != material.unit_id
                    or original.balance.raw_material_id != material.raw_material_id):
                raise Conflict('附带材料原出库凭证与保存资料不一致，不能自动退回。')
            events.append(stock_event(correction, original, material.quantity, line_id=material.pk, source_type=MATERIAL_SOURCE))
            _add_requirement(requirements, material.requirement, -material.quantity,
                raw_id=material.raw_material_id, catalog_id=material.material_catalog_id, unit_id=material.unit_id)
    _requirement_deltas(requirements, order)
    movements = apply_stock_events(order, correction, events, request)
    if data['operation'] == 'DELETE':
        batch.status = 'CANCELLED'
    else:
        action.actual_dispatch_date = data['business_date']
        action.save(update_fields=['actual_dispatch_date', 'updated_at'])
        for line in lines:
            line.quantity, line.stock_quantity, meters = new_values[line.pk]
            if batch.source_kind == 'RAW_PIPE':
                line.snapshot = {**line.snapshot, 'meters': meters}
            line.save(update_fields=['quantity', 'stock_quantity', 'snapshot', 'updated_at'])
    batch.version += 1
    batch.updated_by_employee = request.employee
    batch.save(update_fields=['status', 'version', 'updated_by_employee', 'updated_at'])
    correction.after_data.update(status=batch.status, lines=[{'id': str(line.pk),
        'component_identity': str(line.component_identity), 'quantity': entered[str(line.component_identity)],
        'stock_quantity': new_values[line.pk][1], 'meters': new_values[line.pk][2]} for line in lines])
    return movements


def _receipt(order, correction, data, request):
    receipt = get_object_or_404(TubePlanReceipt.objects.select_for_update(of=('self',)), pk=data['record_id'], order=order)
    if receipt.voided_at is not None:
        raise Conflict('该次入库已删除，不能再次更正。')
    lines = list(receipt.lines.select_for_update(of=('self',)).select_related('order_line',
        'stock_movement__balance__zone__warehouse', 'stock_movement__balance__unit').order_by('pk'))
    entered = _quantities(data, [line.order_line.component_identity for line in lines])
    values = plan_quantities([order])[str(order.pk)]['lines']
    history = list(order.record_corrections.filter(record_kind='RECEIPT', record_id=receipt.pk))
    before = {'number': receipt.receipt_number, 'business_date': str(receipt.receipt_date),
        'remark': receipt.remark, 'voided_at': None, 'lines': [{'id': str(line.pk),
            'component_identity': str(line.order_line.component_identity), 'quantity': line.received_quantity,
            'zone_id': str(line.zone_id), 'snapshot': line.snapshot} for line in lines]}
    correction.before_data = _json(before)
    correction.after_data = _json({**before, 'operation': data['operation'],
        **({'business_date': data['business_date']} if data['operation'] == 'UPDATE' else {})})
    events = []
    for line in lines:
        quantity = entered[str(line.order_line.component_identity)]
        value = values[str(line.order_line_id)]
        if int(value['received_quantity']) - line.received_quantity + quantity > int(value['dispatched_quantity']):
            raise ValidationError({'lines': f'“{line.snapshot.get("part_name", "部件")}”累计实收不能超过累计实发。'})
        original = line.stock_movement
        if (original.direction != 'IN' or original.source_type != 'TUBE_OUTSOURCING_RETURN'
                or original.source_id != receipt.pk or original.source_line_id != line.pk
                or original.balance.zone_id != line.zone_id
                or original.snapshot.get('public_identity') != line.snapshot.get('public_output_identity')
                or effective_stock_quantity(original, history, line_id=line.pk, source_type=RECEIPT_SOURCE) != line.received_quantity):
            raise Conflict('原入库数量与库存凭证不一致，不能自动更正。')
        events.append(stock_event(correction, original, quantity - line.received_quantity,
                                  line_id=line.pk, source_type=RECEIPT_SOURCE))
    movements = apply_stock_events(order, correction, events, request)
    if data['operation'] == 'DELETE':
        receipt.voided_at = timezone.now()
    else:
        receipt.receipt_date = data['business_date']
        for line in lines:
            line.received_quantity = entered[str(line.order_line.component_identity)]
            line.save(update_fields=['received_quantity', 'updated_at'])
    receipt.save(update_fields=['receipt_date', 'voided_at', 'updated_at'])
    correction.after_data.update(voided_at=receipt.voided_at.isoformat() if receipt.voided_at else None,
        lines=[{'id': str(line.pk), 'component_identity': str(line.order_line.component_identity),
                'quantity': entered[str(line.order_line.component_identity)]} for line in lines])
    return movements


@stock_write_transaction
def correct_plan_record(*, order_id, data, request):
    require_tube_feature()
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    lock_request('plan-record-correction', data['client_request_id'])
    digest = _json_hash({'order_id': str(order_id), 'actor': str(request.employee.pk), 'data': data})
    previous = TubePlanRecordCorrection.objects.select_related('order').filter(
        client_request_id=data['client_request_id']).first()
    if previous:
        _permission(request, previous.order, previous.record_kind)
        if previous.order_id != order_id or previous.request_payload_hash != digest:
            raise CorrectionRequestConflict('相同提交标识已用于不同的更正内容或操作人。')
        return previous.order, previous, False
    initial = get_object_or_404(TubeOutsourcingOrder, pk=order_id, is_plan=True)
    permission = _permission(request, initial, data['record_kind'])
    order = _lock_plan(order_id, request, permission)
    correction = TubePlanRecordCorrection(order=order, client_request_id=data['client_request_id'],
        request_payload_hash=digest, record_kind=data['record_kind'], record_id=data['record_id'],
        operation=data['operation'], actor_employee=request.employee)
    correction.stock_movements = (_dispatch if data['record_kind'] == 'DISPATCH' else _receipt)(order, correction, data, request)
    correction.save(force_insert=True)
    _update_plan(order, request)
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='PLAN_RECORD_CORRECTED',
        actor_employee=request.employee, before_data=correction.before_data,
        after_data={**correction.after_data, 'record_correction': correction_data(correction),
                    'stock_movements': correction.stock_movements, 'version': order.version},
        context_type='PRODUCTION_SCHEDULE', context_id=order.schedule_product.schedule_id, request=request)
    return order, correction, True
