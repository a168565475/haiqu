"""D2真实保存：先校验并锁定共同额度，再一次性保存单据及预留。"""
from decimal import Decimal, InvalidOperation
import json
from uuid import UUID, uuid4

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.inventory.public_stock_cutover import stock_write_transaction

from .material_flow import lock_request
from .models import OutsourcingFactory, TubeOutsourcingLine, TubeOutsourcingOrder
from .services import _json_hash
from .tube_selectors import (CREATE_PERMISSION, require_saved_order_access, require_tube_feature,
                             source_factories, source_product, source_zone)


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _stock_amount(source_kind, quantity, row):
    if source_kind == 'METAL':
        return None, None
    if source_kind == 'PUBLIC_SEMI':
        return quantity, None
    try:
        pieces = Decimal(str(row['pieces_per_bar']))
        length = Decimal(str(row['raw_bar_length_m']))
        if not pieces.is_finite() or not length.is_finite() or pieces <= 0 or pieces != pieces.to_integral_value() or length <= 0:
            raise ValueError()
        if quantity % int(pieces):
            raise ValidationError({'lines': f'“{row.get("part_name", "管材")}”须填写每根切割支数{pieces}的整数倍。'})
        bars = quantity // int(pieces)
        return bars, format(Decimal(bars) * length, '.2f')
    except (KeyError, ValueError, InvalidOperation, TypeError) as exc:
        raise ValidationError({'lines': '原管材冻结换算依据不完整，请刷新并核对BOM。'}) from exc


@stock_write_transaction
def create_tube_order(*, data, request):
    require_tube_feature()
    lock_request('tube-create', data['client_request_id'])
    payload_hash = _json_hash(data)
    # 已成功请求先回查，不因保存后额度降低或来源版本变化而重复预留。
    existing = TubeOutsourcingOrder.objects.select_related('schedule_product').filter(
        client_request_id=data['client_request_id']).first()
    if existing:
        require_saved_order_access(request, existing, CREATE_PERMISSION)
        if existing.request_payload_hash != payload_hash:
            raise Conflict('相同提交标识已用于不同的管材外发内容。')
        return existing, False

    product, craft = source_product(request, data['schedule_product_id'], CREATE_PERMISSION)
    zone = source_zone(data['source_kind'], data.get('zone_id'))
    requested = {str(row['component_identity']): row['quantity'] for row in data['lines']}
    from apps.inventory.tube_outsourcing_limits import prepare_tube_source
    context = prepare_tube_source(schedule_product=product, source_kind=data['source_kind'], zone=zone,
                                  requested=requested, expected_revision=data['source_revision'])
    # prepare已先取得S2统一锁，再检查当前可见范围和有效计划，避免等待期间来源变更。
    product, craft = source_product(request, product.pk, CREATE_PERMISSION)
    zone = source_zone(data['source_kind'], data.get('zone_id'))
    requested_factories = {row['factory_id'] for row in data['lines']}
    visible_ids = set(source_factories(request, craft, CREATE_PERMISSION).filter(pk__in=requested_factories)
                      .values_list('pk', flat=True))
    if visible_ids != requested_factories:
        raise ValidationError({'lines': '加工厂不存在、已停用或未获授权办理当前喷塑工艺。'})
    factories = {row.pk: row for row in OutsourcingFactory.objects.select_for_update(of=('self',))
                 .filter(pk__in=visible_ids, status='ACTIVE').order_by('pk')}
    if set(factories) != requested_factories or set(source_factories(request, craft, CREATE_PERMISSION)
            .filter(pk__in=requested_factories).values_list('pk', flat=True)) != requested_factories:
        raise Conflict('加工厂资料已变化，请刷新后重新核对。')
    bom = Bom.objects.filter(product_line=product.product_line, archived_at__isnull=True)
    bom = bom.order_by('-version_number', '-updated_at', '-pk').first()
    if bom is None or bom.status != 'VERIFIED':
        raise ValidationError({'lines': '请先确认当前产品的最新BOM。'})
    prepared = {str(row['component_identity']): row for row in context['rows']}
    lines = []
    for entered in data['lines']:
        key = str(entered['component_identity'])
        row = prepared.get(key)
        if row is None:
            raise Conflict('当前BOM已不包含所选部位，请刷新后重试。')
        try:
            bom_line = BomLine.objects.get(pk=UUID(str(row['bom_line_id'])), section__bom=bom,
                                          component_identity=entered['component_identity'], section__section_type='PROFILE')
        except (KeyError, ValueError, BomLine.DoesNotExist) as exc:
            raise Conflict('管材部位身份已变化，请刷新后重试。') from exc
        stock_quantity, meters = _stock_amount(data['source_kind'], entered['quantity'], row)
        if row.get('quantity') != entered['quantity'] or row.get('stock_quantity') != stock_quantity:
            raise Conflict('管材数量换算依据已变化，请刷新后重新核对。')
        if data['source_kind'] == 'RAW_PIPE' and Decimal(str(row.get('meters'))) != Decimal(meters):
            raise Conflict('原管材米数依据已变化，请刷新后重新核对。')
        input_identity = row.get('input_identity') or {}
        if data['source_kind'] != 'METAL' and not input_identity:
            raise Conflict('公共库存身份未就绪，不能保存预留。')
        snapshot = {**row.get('snapshot', {}), **{key: row.get(key) for key in (
            'part_name', 'material', 'specification', 'thickness', 'cutting_length_mm', 'raw_color', 'spray_color',
            'order_required', 'pieces_per_bar', 'raw_bar_length_m')},
            'factory_name': factories[entered['factory_id']].name, 'meters': meters}
        lines.append(TubeOutsourcingLine(bom_line=bom_line, component_identity=entered['component_identity'],
            factory=factories[entered['factory_id']], quantity=entered['quantity'], stock_quantity=stock_quantity,
            input_identity=_json(input_identity), snapshot=_json(snapshot)))
    order = TubeOutsourcingOrder.objects.create(
        order_number=f'WF-{timezone.localdate():%Y%m%d}-{uuid4().hex[:12].upper()}',
        schedule_product=product, product_line=product.product_line, bom=bom, craft=craft,
        source_kind=data['source_kind'], zone=zone, planned_dispatch_date=data['planned_dispatch_date'],
        expected_return_date=data['expected_return_date'], remark=data.get('remark', ''),
        client_request_id=data['client_request_id'], request_payload_hash=payload_hash,
        source_revision_hash=data['source_revision'], source_snapshot=_json(context),
        created_by_employee=request.employee, updated_by_employee=request.employee,
    )
    for line in lines:
        line.order = order
    TubeOutsourcingLine.objects.bulk_create(lines)
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=order.pk, action='CREATED',
        actor_employee=request.employee, after_data={'order_number': order.order_number,
            'source_kind': order.source_kind, 'product_line_id': str(order.product_line_id),
            'quantity': sum(line.quantity for line in lines), 'source_revision': order.source_revision_hash,
            'lines': [{'component_identity': str(line.component_identity), 'quantity': line.quantity,
                       'factory_id': str(line.factory_id), 'stock_quantity': line.stock_quantity} for line in lines]},
        context_type='PRODUCTION_SCHEDULE', context_id=product.schedule_id, request=request)
    return order, True
