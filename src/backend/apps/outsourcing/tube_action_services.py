"""D4整单实际发出与待发取消；原数量不编辑，任何失败全单回滚。"""
from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.models import PublicStockBalance
from apps.inventory.public_stock_cutover import stock_write_transaction
from apps.inventory.public_stock_services import _lock_source, debit_public_stock
from apps.inventory.tube_outsourcing_limits import prepare_tube_source
from apps.inventory.tube_processing_services import lock_tube_product_scope, assert_tube_reports_cover_usage
from apps.material_issues.models import OrderMaterialRequirement

from .material_flow import lock_request
from .models import OutsourcingFactory, TubeOutsourcingAction, TubeOutsourcingOrder
from .services import _json_hash
from .tube_selectors import (CANCEL_PERMISSION, DISPATCH_PERMISSION, require_saved_order_access,
                            require_tube_feature, source_factories, source_product, source_zone)
from .tube_services import _json, _stock_amount


MOVEMENT_SOURCE = 'TUBE_OUTSOURCING_DISPATCH'


def _fail(detail):
    raise ValidationError({'detail': detail})


def _matching_frozen_line(line, current, source_kind):
    """只接受原单冻结实物和换算；库存/报工数量变化不等同于身份变化。"""
    snapshot = line.snapshot
    output = snapshot.get('public_output_identity')
    latest = current.get('snapshot', {})
    if not output or _json_hash(output) != _json_hash(latest.get('public_output_identity')):
        raise Conflict('当前BOM的管材实物属性或喷塑颜色与原单不一致，请取消后重新创建。')
    # 已加工来源以实物身份为准，不新增原料长度/每根切割支数的限制。
    for field in ('raw_material_id', 'cutting_length_mm', 'pieces_per_bar', 'raw_bar_length_m') if source_kind == 'RAW_PIPE' else ():
        try:
            if field == 'raw_material_id':
                equal = str(snapshot.get(field)) == str(latest.get(field)) and bool(snapshot.get(field))
            else:
                a, b = Decimal(str(snapshot[field])), Decimal(str(latest[field]))
                equal = a.is_finite() and b.is_finite() and a == b and a > 0
        except (KeyError, ValueError, TypeError, ArithmeticError):
            equal = False
        if not equal:
            raise Conflict('当前BOM的原料或切割换算与原单不一致，请取消后重新创建。')
    if source_kind != 'METAL' and _json_hash(line.input_identity) != _json_hash(current.get('input_identity')):
        raise Conflict('来源公共库存的实物身份与原单不一致，请取消后重新创建。')
    stock_quantity, meters = _stock_amount(source_kind, line.quantity, current)
    try:
        matching_meters = source_kind != 'RAW_PIPE' or Decimal(str(snapshot.get('meters'))) == Decimal(meters)
    except (ValueError, TypeError, ArithmeticError):
        matching_meters = False
    if stock_quantity != line.stock_quantity or not matching_meters:
        raise Conflict('原单支、根、米换算凭证不一致，不能发出。')
    return stock_quantity, meters


@stock_write_transaction
def confirm_tube_action(*, order_id, kind, data, request):
    require_tube_feature()
    if kind not in {'DISPATCH', 'CANCEL'}:
        _fail('不支持该管材外发操作。')
    permission = DISPATCH_PERMISSION if kind == 'DISPATCH' else CANCEL_PERMISSION
    if not request.headers.get('If-Match'):
        raise PreconditionRequired()
    lock_request('tube-action', data['client_request_id'])
    payload_hash = _json_hash({'order_id': str(order_id), 'kind': kind,
                               'actor_id': str(request.employee.pk), 'data': data})
    existing = TubeOutsourcingAction.objects.select_related('order__schedule_product').filter(
        client_request_id=data['client_request_id']).first()
    if existing:
        require_saved_order_access(request, existing.order, permission)
        if existing.request_payload_hash != payload_hash:
            raise Conflict('相同提交标识已用于不同外发动作、内容或操作人。')
        return existing.order, existing, False
    initial = get_object_or_404(TubeOutsourcingOrder.objects.select_related('schedule_product'), pk=order_id)
    require_saved_order_access(request, initial, permission)
    # 先共同产品锁，后本单锁；与D1入库、D2保存和旧直接交接保持同一顺序。
    lock_tube_product_scope(initial.product_line_id)
    order = TubeOutsourcingOrder.objects.select_for_update(of=('self',)).select_related(
        'schedule_product', 'product_line', 'zone__warehouse', 'craft').get(pk=order_id)
    require_saved_order_access(request, order, permission)
    require_matching_etag(request, order)
    if order.status != 'PENDING_DISPATCH':
        raise Conflict('只有待外发原单可以发出或取消，请刷新查看当前状态。')
    lines = list(order.lines.select_for_update(of=('self',)).order_by('pk'))
    if not lines:
        _fail('原单没有可办理明细，不能提交。')
    before = {'status': order.status, 'version': order.version}
    movements = []
    context = None
    if kind == 'DISPATCH':
        product, craft = source_product(request, order.schedule_product_id, permission)
        if craft.pk != order.craft_id:
            raise Conflict('当前喷塑工艺与原单不一致，请取消后重新创建。')
        zone = source_zone(order.source_kind, order.zone_id)
        # 同一事件在库存余额前锁定，且不引入采购批次查询。
        if order.source_kind != 'METAL':
            for line in lines:
                _lock_source({'source_type': MOVEMENT_SOURCE, 'source_line_id': line.pk}, 'OUT')
        context = prepare_tube_source(schedule_product=product, source_kind=order.source_kind, zone=zone,
            requested={str(line.component_identity): line.quantity for line in lines}, expected_revision=None,
            exclude_order_id=order.pk, require_revision=False)
        # 在可能的锁等待后重新检查当前计划、工艺权限和库区。
        product, craft = source_product(request, order.schedule_product_id, permission)
        if craft.pk != order.craft_id:
            raise Conflict('当前喷塑工艺已变化，请取消后重新创建。')
        source_zone(order.source_kind, order.zone_id)
        factories = {line.factory_id for line in lines}
        locked_factories = list(OutsourcingFactory.objects.select_for_update(of=('self',))
                                .filter(pk__in=factories).order_by('pk'))
        visible = set(source_factories(request, craft, permission).filter(pk__in=factories).values_list('pk', flat=True))
        if {factory.pk for factory in locked_factories} != factories or visible != factories:
            _fail('加工厂不存在、已停用或不再获授权办理本单喷塑工艺，请取消后重建。')
        by_component = {row['component_identity']: row for row in context['rows']}
        for line in lines:
            current = by_component.get(str(line.component_identity))
            if current is None:
                raise Conflict('当前BOM不再包含原单部位，请取消后重新创建。')
            _matching_frozen_line(line, current, order.source_kind)
    # 解除本单预留后，底层扣库仍保护所有其他待发单。失败会回滚此状态及整单流水。
    order.status = 'PROCESSING' if kind == 'DISPATCH' else 'CANCELLED'
    order.version += 1
    order.updated_by_employee = request.employee
    order.save(update_fields=['status', 'version', 'updated_by_employee', 'updated_at'])
    if kind == 'DISPATCH':
        by_component = {row['component_identity']: row for row in context['rows']}
        for line in lines:
            row = by_component[str(line.component_identity)]
            if order.source_kind == 'METAL':
                continue
            identity = line.input_identity
            balance = PublicStockBalance.objects.filter(stock_kind=identity['stock_kind'],
                identity_key=identity['identity_key'], unit_id=identity['unit_id'], zone_id=order.zone_id,
                quality='AVAILABLE').first()
            if not balance:
                raise Conflict('原单来源库区公共库存已不足，请刷新后重新复核。')
            snapshot = _json({'order_number': order.order_number, 'source_kind': order.source_kind,
                'actual_dispatch_date': str(data['actual_dispatch_date']), 'actor_name': request.employee.display_name,
                'factory_id': str(line.factory_id), 'factory_name': line.snapshot.get('factory_name', ''),
                'quantity': str(line.quantity), 'stock_quantity': str(line.stock_quantity),
                'meters': line.snapshot.get('meters'), 'public_identity': line.input_identity,
                'saved_bom_line_id': str(line.bom_line_id), 'current_bom_line_id': row['bom_line_id'],
                'source_revision': context['source_revision'], 'client_request_id': str(data['client_request_id'])})
            movement = debit_public_stock(balance_id=balance.pk, quantity=line.stock_quantity,
                source_type=MOVEMENT_SOURCE, source_id=order.pk, source_line_id=line.pk,
                actor_employee=request.employee, production_task=product.schedule.production_task_id,
                product_line=order.product_line_id, bom_line=row['bom_line_id'], snapshot=snapshot)
            movements.append({'line_id': str(line.pk), 'movement_id': str(movement.pk),
                'before_quantity': str(movement.before_quantity), 'after_quantity': str(movement.after_quantity),
                'meter_quantity': str(movement.meter_quantity) if movement.meter_quantity is not None else None})
            if order.source_kind == 'RAW_PIPE':
                requirement = get_object_or_404(OrderMaterialRequirement,
                    pk=row['snapshot']['requirement_id'], product_line_id=order.product_line_id,
                    component_identity=line.component_identity)
                requirement.outsourcing_issued_quantity += line.quantity
                requirement.save(update_fields=['outsourcing_issued_quantity', 'updated_at'])
        if order.source_kind == 'METAL':
            assert_tube_reports_cover_usage(order.product_line_id)
    record = TubeOutsourcingAction.objects.create(order=order, kind=kind,
        client_request_id=data['client_request_id'], request_payload_hash=payload_hash,
        actual_dispatch_date=data.get('actual_dispatch_date'), remark=data.get('remark', ''),
        actor_employee=request.employee, snapshot=_json({'quantity': sum(line.quantity for line in lines),
            'source_revision': context['source_revision'] if context else None, 'movements': movements}))
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk,
        action='DISPATCH_CONFIRMED' if kind == 'DISPATCH' else 'CANCELLED', actor_employee=request.employee,
        before_data=before, after_data={'order_number': order.order_number, 'status': order.status,
            'version': order.version, 'source_kind': order.source_kind, 'action_id': str(record.pk),
            'client_request_id': str(record.client_request_id), 'actual_dispatch_date': str(record.actual_dispatch_date)
            if record.actual_dispatch_date else None, 'remark': record.remark, **record.snapshot},
        context_type='PRODUCTION_SCHEDULE', context_id=order.schedule_product.schedule_id, request=request)
    return order, record, True
