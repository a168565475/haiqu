"""D2来源和保存结果；只使用外发操作本身的数据权限。"""
from types import SimpleNamespace

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.exceptions import NotFound, ValidationError

from apps.access_control.resource_scopes import filter_crafts, require_craft
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.inventory.models import WarehouseZone
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_tasks.selectors import production_task_product_image
from apps.sales_orders.presentation import specification_display
from apps.workshop_config.models import Craft

from .models import OutsourcingFactory, TubeSourceKind
from .selectors import outsourcing_source_schedules
from .tube_prices import line_price_data, planned_amount
from .tube_kinds import CUTTING_SOURCES, CUTTING_CRAFT_CODES, CUTTING_FIELDS, DIRECT_SOURCES, output_unit, source_category, display_operations


VIEW_PERMISSION = 'outsourcing.view_outsourcingorder'
CREATE_PERMISSION = 'outsourcing.add_outsourcingorder'
DISPATCH_PERMISSION = 'outsourcing.confirm_dispatch_outsourcingorder'
CANCEL_PERMISSION = 'outsourcing.cancel_outsourcingorder'
RETURN_PERMISSION = 'outsourcing.confirm_return_outsourcingorder'
SOURCE_LABELS = {'RAW_PIPE': '原材料', 'PUBLIC_SEMI': '未喷塑半成品', 'METAL': '未入库半成品',
                 'PUBLIC_CUTTING': '已入库裁片半成品', 'SEWING': '未入库车缝完成件'}


def require_tube_feature():
    if not getattr(settings, 'TUBE_OUTSOURCING_ENABLED', False):
        raise NotFound('外发单保存入口尚未启用。')
    if not public_flow_enabled():
        raise Conflict('外发单保存须使用已启用的公共库存模式。')


def powder_crafts(request, permission=VIEW_PERMISSION, *, category='tube'):
    codes = CUTTING_CRAFT_CODES if category == 'cutting' else {'POWDER_COATING'}
    if category == 'all':
        codes = codes | CUTTING_CRAFT_CODES
    return filter_crafts(Craft.objects.filter(craft_type='EXTERNAL', status='ACTIVE',
        outsourcing_code__in=codes), request, permission, 'pk')


def visible_products(request, permission=VIEW_PERMISSION, *, category='tube'):
    crafts = powder_crafts(request, permission, category=category)
    links = ProductionScheduleProductCraft.objects.filter(craft__in=crafts, craft_type_snapshot='EXTERNAL',
                                                          removed_at__isnull=True)
    schedules = outsourcing_source_schedules(request, permission=permission).filter(record_status='ACTIVE')
    queryset = ProductionScheduleProduct.objects.filter(schedule__in=schedules, removed_at__isnull=True,
        pk__in=links.values('schedule_product_id'), product_line__production_task__archived_at__isnull=True
    ).select_related('schedule__production_task', 'product_line__unit', 'unit',
        'product_line__production_task', 'product_line__image_file',
        'product_line__sales_order_delivery_batch_line__sales_order_line__product_image'
    ).prefetch_related('product_line__images__image_file').order_by('schedule_id', 'line_number', 'pk')
    from .source_access import filter_source_products
    return filter_source_products(queryset, request, permission)


def source_product(request, schedule_product_id, permission=VIEW_PERMISSION, *, source_kind='RAW_PIPE', craft_id=None):
    from .source_access import require_source
    require_source(request, permission, source_kind)
    category = source_category(source_kind)
    product = get_object_or_404(visible_products(request, permission, category=category), pk=schedule_product_id)
    from .source_access import require_source_product
    require_source_product(request, permission, source_kind, product)
    active_count = ProductionScheduleProduct.objects.filter(product_line_id=product.product_line_id,
        removed_at__isnull=True, schedule__record_status='ACTIVE').count()
    if active_count != 1:
        raise ValidationError({'schedule_product_id': '同一产品存在多个有效排产，请先整理为唯一有效计划。'})
    if product.schedule.production_task.status not in {'READY', 'IN_PRODUCTION'}:
        raise ValidationError({'schedule_product_id': '当前生产任务状态不能新建外发单。'})
    links_query = product.crafts.filter(removed_at__isnull=True, craft_type_snapshot='EXTERNAL',
        craft__in=powder_crafts(request, permission, category=category))
    if category == 'cutting' and not craft_id:
        raise ValidationError({'craft_id': '裁片外发请选择刺绣、丝印、裁剪或车缝工艺。'})
    if craft_id:
        links_query = links_query.filter(craft_id=craft_id)
    links = list(links_query.select_related('craft'))
    if len(links) != 1:
        raise ValidationError({'schedule_product_id': '未找到所选有效外发工艺，请先完善计划。'})
    require_craft(request, permission, links[0].craft_id)
    return product, links[0].craft


def source_zone(source_kind, zone_id):
    if source_kind in DIRECT_SOURCES:
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


def source_factories(request, craft=None, permission=VIEW_PERMISSION, *, category='tube'):
    if craft is not None and craft.outsourcing_code in CUTTING_CRAFT_CODES:
        category = 'cutting'
    crafts = powder_crafts(request, permission, category=category)
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


def product_display(product):
    line = product.product_line
    image = production_task_product_image(line)
    if image is not None and not image.content_type.startswith('image/'):
        image = None
    return {'specification': line.specification_snapshot,
        'specification_display': specification_display(SimpleNamespace(
            specification_snapshot=line.specification_snapshot,
            customer_specification_snapshot=line.customer_specification_snapshot,
            color_snapshot=line.color_name_snapshot, customer_color_snapshot=line.customer_color_snapshot,
            material_snapshot=line.material_snapshot)),
        'material': line.material_snapshot, 'image_file_id': str(image.pk) if image else None,
        'image_url': reverse('tube-outsourcing-order-product-image', kwargs={
            'schedule_product_id': product.pk, 'file_id': image.pk}) if image else ''}


def tube_options(request, *, category='tube'):
    if category not in {'tube', 'cutting'}:
        raise ValidationError({'category': '外发类别只能是管材或裁片。'})
    tasks = {}
    seen_products = set()
    crafts = powder_crafts(request, category=category)
    for product in visible_products(request, category=category):
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
            'quantity', 'unit', 'color')}, **product_display(product),
            'craft_ids': [str(value) for value in product.crafts.filter(removed_at__isnull=True,
                craft_type_snapshot='EXTERNAL', craft__in=crafts).values_list('craft_id', flat=True)]})
    zones = WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type__in=['MATERIAL', 'SEMI_FINISHED']).select_related('warehouse').order_by('warehouse_id', 'zone_name', 'pk')
    kinds = ([TubeSourceKind.PUBLIC_CUTTING, TubeSourceKind.SEWING] if category == 'cutting' else
             [TubeSourceKind.RAW_PIPE, TubeSourceKind.PUBLIC_SEMI, TubeSourceKind.METAL])
    from .source_access import allowed_source_kinds
    kinds = [kind for kind in kinds if kind in allowed_source_kinds(request, VIEW_PERMISSION)]
    return {'category': category, 'crafts': [{'id': str(craft.pk), 'name': craft.name,
        'outsourcing_code': craft.outsourcing_code} for craft in crafts],
        'tasks': list(tasks.values()), 'factories': [{'id': str(factory.pk), 'name': factory.name}
        for factory in source_factories(request, category=category)], 'zones': [{'id': str(zone.pk), 'name': zone.zone_name,
        'warehouse_id': str(zone.warehouse_id), 'warehouse_name': zone.warehouse.warehouse_name,
        'warehouse_type': zone.warehouse.warehouse_type} for zone in zones],
        'source_kinds': [{'value': value, 'label': SOURCE_LABELS[value]} for value in kinds]}


def saved_orders_for_permission(request, permission=VIEW_PERMISSION):
    from apps.access_control.resource_scopes import craft_access_union, has_resource_grant
    from apps.production_scheduling.selectors import accessible_production_schedules
    from .models import TubeOutsourcingOrder
    # 已保存单按自身冻结工艺鉴权，不能因当前计划移除工艺/产品而失去取消或回查入口。
    # 与既有外发单相同：新工艺范围只授权对应原单，旧权限仍受旧任务可见范围约束。
    queryset = TubeOutsourcingOrder.objects.all()
    legacy = queryset.filter(schedule_product__schedule_id__in=accessible_production_schedules(request).values('id'))
    from apps.access_control.resource_scopes import enforcing
    from .source_access import scoped_tube_orders
    if enforcing(request, permission):
        return scoped_tube_orders(queryset, request, permission, legacy)
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
    if order.source_kind == 'SEWING' and include_metal_basis and order.status != 'COMPLETED':
        from apps.inventory.sewing_processing_services import sewing_component_limits
        basis = sewing_component_limits(order.product_line)
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
        output_identity = snapshot.get('public_output_identity')
        output_snapshot = output_identity.get('identity_snapshot') if isinstance(output_identity, dict) else None
        tube_diameter = output_snapshot.get('tube_diameter') if isinstance(output_snapshot, dict) else None
        pieces_per_product = snapshot.get('pieces_per_product')
        meters = snapshot.get('meters')
        component = basis['components'].get(str(line.component_identity)) if basis else None
        lines.append({'id': str(line.pk), 'component_identity': str(line.component_identity),
            **line_price_data(line),
            **{key: snapshot.get(key) for key in CUTTING_FIELDS},
            'part_name': snapshot.get('part_name', ''), 'factory_id': str(line.factory_id),
            'factory_name': snapshot.get('factory_name', ''), 'quantity': str(line.quantity),
            'stock_quantity': str(line.stock_quantity) if line.stock_quantity is not None else None,
            'meters': str(meters) if meters is not None else None,
            **{key: snapshot.get(key) for key in ('material', 'specification', 'thickness',
                'cutting_length_mm', 'raw_color', 'spray_color', 'order_required', 'pieces_per_bar', 'raw_bar_length_m')},
            'pieces_per_product': str(pieces_per_product) if pieces_per_product is not None else None,
            'tube_diameter': str(tube_diameter) if tube_diameter is not None else None,
            'current_reported_minimum': str(component['allowance']['reported_minimum'])
                if component and component['basis_ready'] else None,
            'report_as_of': basis['as_of'] if basis else None,
            'operations': display_operations(order.source_kind, component['operations']) if component else [],
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
    from .tube_materials import material_data
    result = {**summary, 'task_order_number': task_order_number,
        'id': str(order.pk), 'order_number': order.order_number, 'status': order.status,
        'version': order.version, 'etag': etag_for_instance(order), 'created': created,
        'client_request_id': str(order.client_request_id), 'source_kind': order.source_kind,
        'source_label': SOURCE_LABELS[order.source_kind], 'zone_id': str(order.zone_id) if order.zone_id else None,
        'zone_name': order.zone.zone_name if order.zone_id else '',
        'warehouse_name': order.zone.warehouse.warehouse_name if order.zone_id else '',
        'craft_name': order.craft.name, 'craft_id': str(order.craft_id), 'remark': order.remark,
        'category': source_category(order.source_kind), 'output_unit': output_unit(order.source_kind),
        'material_category': '辅料' if order.source_kind in CUTTING_SOURCES else '五金',
        'created_at': order.created_at.isoformat(), 'created_by_name': order.created_by_employee.display_name,
        'updated_at': order.updated_at.isoformat(),
        'planned_quantity': str(order.schedule_product.planned_quantity),
        'specification': order.product_line.specification_snapshot, 'material': order.product_line.material_snapshot,
        'actual_dispatch_date': str(dispatch.actual_dispatch_date) if dispatch else None,
        'dispatched_at': dispatch.created_at.isoformat() if dispatch else None,
        'dispatched_by_name': dispatch.actor_employee.display_name if dispatch else '',
        'cancelled_at': cancel.created_at.isoformat() if cancel else None,
        'cancelled_by_name': cancel.actor_employee.display_name if cancel else '',
        'cancel_remark': cancel.remark if cancel else '', 'permissions': permissions,
        'schedule_product_id': str(order.schedule_product_id), 'product_line_id': str(order.product_line_id),
        'planned_dispatch_date': str(order.planned_dispatch_date), 'expected_return_date': str(order.expected_return_date),
        'total_quantity': str(total_quantity), 'total_stock_quantity': None if order.source_kind in DIRECT_SOURCES else str(total_stock),
        'total_meters': format(total_meters, '.2f') if order.source_kind == 'RAW_PIPE' else None, 'lines': lines,
        'planned_amount': planned_amount(order.lines.all()),
        'materials': [{**material_data(value), 'unit_consumption': None} for value in order.materials.all()]}
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
        .prefetch_related('lines', 'materials__order_line',
            Prefetch('actions', queryset=TubeOutsourcingAction.objects.select_related('actor_employee')))
