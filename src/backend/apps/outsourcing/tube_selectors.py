"""D2来源和保存结果；只使用外发操作本身的数据权限。"""
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError

from apps.access_control.resource_scopes import filter_crafts, require_craft
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.inventory.models import WarehouseZone
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Craft

from .models import OutsourcingFactory, TubeSourceKind
from .selectors import outsourcing_source_schedules


VIEW_PERMISSION = 'outsourcing.view_outsourcingorder'
CREATE_PERMISSION = 'outsourcing.add_outsourcingorder'
DISPATCH_PERMISSION = 'outsourcing.confirm_dispatch_outsourcingorder'
CANCEL_PERMISSION = 'outsourcing.cancel_outsourcingorder'
RETURN_PERMISSION = 'outsourcing.confirm_return_outsourcingorder'
SOURCE_LABELS = {'RAW_PIPE': '原材料', 'PUBLIC_SEMI': '未喷塑半成品', 'METAL': '未入库半成品'}


def require_tube_feature():
    if not getattr(settings, 'TUBE_OUTSOURCING_ENABLED', False):
        raise NotFound('管材外发保存入口尚未启用。')
    if not public_flow_enabled():
        raise Conflict('管材外发保存须使用已启用的公共库存模式。')


def powder_crafts(request, permission=VIEW_PERMISSION):
    return filter_crafts(Craft.objects.filter(craft_type='EXTERNAL', status='ACTIVE',
        outsourcing_code='POWDER_COATING'), request, permission, 'pk')


def visible_products(request, permission=VIEW_PERMISSION):
    crafts = powder_crafts(request, permission)
    links = ProductionScheduleProductCraft.objects.filter(craft__in=crafts, craft_type_snapshot='EXTERNAL',
                                                          removed_at__isnull=True)
    schedules = outsourcing_source_schedules(request, permission=permission).filter(record_status='ACTIVE')
    return ProductionScheduleProduct.objects.filter(schedule__in=schedules, removed_at__isnull=True,
        pk__in=links.values('schedule_product_id'), product_line__production_task__archived_at__isnull=True
    ).select_related('schedule__production_task', 'product_line__unit', 'unit').order_by('schedule_id', 'line_number', 'pk')


def source_product(request, schedule_product_id, permission=VIEW_PERMISSION):
    product = get_object_or_404(visible_products(request, permission), pk=schedule_product_id)
    active_count = ProductionScheduleProduct.objects.filter(product_line_id=product.product_line_id,
        removed_at__isnull=True, schedule__record_status='ACTIVE').count()
    if active_count != 1:
        raise ValidationError({'schedule_product_id': '同一产品存在多个有效排产，请先整理为唯一有效计划。'})
    if product.schedule.production_task.status not in {'READY', 'IN_PRODUCTION'}:
        raise ValidationError({'schedule_product_id': '当前生产任务状态不能新建外发单。'})
    links = list(product.crafts.filter(removed_at__isnull=True, craft_type_snapshot='EXTERNAL',
        craft__in=powder_crafts(request, permission)).select_related('craft'))
    if len(links) != 1:
        raise ValidationError({'schedule_product_id': '未找到唯一有效喷塑工艺，请先完善计划。'})
    require_craft(request, permission, links[0].craft_id)
    return product, links[0].craft


def source_zone(source_kind, zone_id):
    if source_kind == TubeSourceKind.METAL:
        if zone_id:
            raise ValidationError({'zone_id': '未入库半成品不从仓库库存选择库区。'})
        return None
    if not zone_id:
        raise ValidationError({'zone_id': '请选择来源仓库和库区。'})
    warehouse_type = 'MATERIAL' if source_kind == TubeSourceKind.RAW_PIPE else 'SEMI_FINISHED'
    zone = WarehouseZone.objects.select_related('warehouse').filter(pk=zone_id, status='ACTIVE',
        warehouse__status='ACTIVE', warehouse__warehouse_type=warehouse_type).first()
    if zone is None:
        raise ValidationError({'zone_id': '来源库区已停用或与所选材料来源不符。'})
    return zone


def source_factories(request, craft=None, permission=VIEW_PERMISSION):
    crafts = powder_crafts(request, permission)
    if craft is not None:
        crafts = crafts.filter(pk=craft.pk)
    return OutsourcingFactory.objects.filter(status='ACTIVE', craft_links__craft__in=crafts).distinct().order_by('name', 'pk')


def product_summary(product):
    task = product.schedule.production_task
    line = product.product_line
    return {'schedule_product_id': str(product.pk), 'product_line_id': str(line.pk),
        'task_id': str(task.pk), 'task_number': task.task_number, 'order_number': task.order_number,
        'schedule_number': product.schedule.schedule_number, 'product_number': line.product_number_snapshot,
        'item_number': line.item_number_snapshot, 'product_name': line.product_name_snapshot,
        'quantity': str(line.quantity), 'unit': line.unit.unit_name, 'color': line.color_name_snapshot}


def tube_options(request):
    tasks = {}
    seen_products = set()
    for product in visible_products(request):
        if product.schedule.production_task.status not in {'READY', 'IN_PRODUCTION'}:
            continue
        if product.product_line_id in seen_products:
            continue
        seen_products.add(product.product_line_id)
        row = product_summary(product)
        task = tasks.setdefault(row['task_id'], {'id': row['task_id'], 'task_number': row['task_number'],
                                                'order_number': row['order_number'], 'products': []})
        task['products'].append({'id': row['product_line_id'], **{key: row[key] for key in (
            'schedule_product_id', 'schedule_number', 'product_number', 'item_number', 'product_name',
            'quantity', 'unit', 'color')}})
    zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type__in=['MATERIAL', 'SEMI_FINISHED']).select_related('warehouse').order_by('warehouse_id', 'zone_name', 'pk')
    return {'tasks': list(tasks.values()), 'factories': [{'id': str(factory.pk), 'name': factory.name}
        for factory in source_factories(request)], 'zones': [{'id': str(zone.pk), 'name': zone.zone_name,
        'warehouse_id': str(zone.warehouse_id), 'warehouse_name': zone.warehouse.warehouse_name,
        'warehouse_type': zone.warehouse.warehouse_type} for zone in zones],
        'source_kinds': [{'value': value, 'label': label} for value, label in (
            (TubeSourceKind.RAW_PIPE, '原材料'),
            (TubeSourceKind.PUBLIC_SEMI, '未喷塑半成品'),
            (TubeSourceKind.METAL, '未入库半成品'),
        )]}


def saved_orders_for_permission(request, permission=VIEW_PERMISSION):
    from apps.access_control.resource_scopes import craft_access_union, has_resource_grant
    from apps.production_scheduling.selectors import accessible_production_schedules
    from .models import TubeOutsourcingOrder
    # 已保存单按自身冻结工艺鉴权，不能因当前计划移除工艺/产品而失去取消或回查入口。
    # 与既有外发单相同：新工艺范围只授权对应原单，旧权限仍受旧任务可见范围约束。
    queryset = TubeOutsourcingOrder.objects.all()
    legacy = queryset.filter(schedule_product__schedule_id__in=accessible_production_schedules(request).values('id'))
    return (craft_access_union(queryset, legacy, request, permission)
               if has_resource_grant(request, permission, 'CRAFT') else filter_crafts(legacy, request, permission))


def require_saved_order_access(request, order, permission=VIEW_PERMISSION):
    require_craft(request, permission, order.craft_id)
    get_object_or_404(saved_orders_for_permission(request, permission), pk=order.pk)


def saved_order_data(order, *, created=False, request=None, action_record=None, include_metal_basis=True):
    from decimal import Decimal, InvalidOperation
    from apps.access_control import module_policy
    from rest_framework.exceptions import APIException
    from apps.inventory.tube_processing_services import metal_component_limits
    basis = metal_component_limits(order.product_line) if order.source_kind == 'METAL' and include_metal_basis and order.status != 'COMPLETED' else None
    actions = {row.kind: row for row in order.actions.all()}
    dispatch, cancel = actions.get('DISPATCH'), actions.get('CANCEL')
    permissions = {'can_dispatch': False, 'can_cancel': False}
    if request is not None and order.status == 'PENDING_DISPATCH':
        for field, permission in [('can_dispatch', DISPATCH_PERMISSION), ('can_cancel', CANCEL_PERMISSION)]:
            if module_policy.has_permission(request, permission):
                try:
                    require_saved_order_access(request, order, permission)
                except APIException:
                    continue
                permissions[field] = True
    lines, total_quantity, total_stock, total_meters = [], 0, 0, Decimal('0')
    for line in order.lines.all():
        snapshot = line.snapshot if isinstance(line.snapshot, dict) else {}
        meters = snapshot.get('meters')
        component = basis['components'].get(str(line.component_identity)) if basis else None
        lines.append({'id': str(line.pk), 'component_identity': str(line.component_identity),
            'part_name': snapshot.get('part_name', ''), 'factory_id': str(line.factory_id),
            'factory_name': snapshot.get('factory_name', ''), 'quantity': str(line.quantity),
            'stock_quantity': str(line.stock_quantity) if line.stock_quantity is not None else None,
            'meters': str(meters) if meters is not None else None,
            **{key: snapshot.get(key) for key in ('material', 'specification', 'thickness',
                'cutting_length_mm', 'raw_color', 'spray_color', 'order_required', 'pieces_per_bar', 'raw_bar_length_m')},
            'current_reported_minimum': str(component['allowance']['reported_minimum'])
                if component and component['basis_ready'] else None,
            'report_as_of': basis['as_of'] if basis else None,
            'operations': component['operations'] if component else [],
            'basis_blockers': component['blockers'] if component else (['当前BOM已不包含该部位。'] if basis else [])})
        total_quantity += line.quantity
        total_stock += line.stock_quantity or 0
        try:
            meter_value = Decimal(str(meters or 0))
            if meter_value.is_finite():
                total_meters += meter_value
        except (InvalidOperation, TypeError, ValueError, ArithmeticError):
            pass  # 只读详情保留原值；动作门禁会阻断不完整换算凭证。
    summary = product_summary(order.schedule_product)
    task_order_number = summary.pop('order_number')
    result = {**summary, 'task_order_number': task_order_number,
        'id': str(order.pk), 'order_number': order.order_number, 'status': order.status,
        'version': order.version, 'etag': etag_for_instance(order), 'created': created,
        'client_request_id': str(order.client_request_id), 'source_kind': order.source_kind,
        'source_label': SOURCE_LABELS[order.source_kind], 'zone_id': str(order.zone_id) if order.zone_id else None,
        'zone_name': order.zone.zone_name if order.zone_id else '',
        'warehouse_name': order.zone.warehouse.warehouse_name if order.zone_id else '',
        'craft_name': order.craft.name, 'remark': order.remark,
        'created_at': order.created_at.isoformat(), 'created_by_name': order.created_by_employee.display_name,
        'actual_dispatch_date': str(dispatch.actual_dispatch_date) if dispatch else None,
        'dispatched_at': dispatch.created_at.isoformat() if dispatch else None,
        'dispatched_by_name': dispatch.actor_employee.display_name if dispatch else '',
        'cancelled_at': cancel.created_at.isoformat() if cancel else None,
        'cancelled_by_name': cancel.actor_employee.display_name if cancel else '',
        'cancel_remark': cancel.remark if cancel else '', 'permissions': permissions,
        'schedule_product_id': str(order.schedule_product_id), 'product_line_id': str(order.product_line_id),
        'planned_dispatch_date': str(order.planned_dispatch_date), 'expected_return_date': str(order.expected_return_date),
        'total_quantity': str(total_quantity), 'total_stock_quantity': None if order.source_kind == 'METAL' else str(total_stock),
        'total_meters': format(total_meters, '.2f') if order.source_kind == 'RAW_PIPE' else None, 'lines': lines}
    if action_record:
        result['action'] = {'id': str(action_record.pk), 'kind': action_record.kind,
            'client_request_id': str(action_record.client_request_id),
            'confirmed_at': action_record.created_at.isoformat(), 'actor_name': action_record.actor_employee.display_name}
    return result


def tube_order_queryset():
    from .models import TubeOutsourcingOrder
    from django.db.models import Prefetch
    from .models import TubeOutsourcingAction
    return TubeOutsourcingOrder.objects.select_related('schedule_product__schedule__production_task',
        'schedule_product__product_line__unit', 'product_line', 'craft', 'zone__warehouse', 'created_by_employee')\
        .prefetch_related('lines', Prefetch('actions', queryset=TubeOutsourcingAction.objects.select_related('actor_employee')))
