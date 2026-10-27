"""D3最终回货的候选、冻结凭证和只读结果。"""
from decimal import Decimal, InvalidOperation

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.access_control import module_policy
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import PublicStockMovement, WarehouseZone
from apps.inventory.public_stock_identity import validate_public_identity

from .models import TubeOutsourcingAction, TubeOutsourcingReceipt
from .tube_prices import line_price_data, planned_amount
from .tube_kinds import CUTTING_SOURCES, CUTTING_CRAFT_CODES, CUTTING_FIELDS, DIRECT_SOURCES, output_unit, source_category
from .tube_selectors import (RETURN_PERMISSION, SOURCE_LABELS, VIEW_PERMISSION, product_summary,
    require_saved_order_access, saved_order_data, saved_orders_for_permission, tube_order_queryset)


def require_receipt_read_access(request, order):
    from django.shortcuts import get_object_or_404
    from .warehouse_access import warehouse_stage, warehouse_tube_orders
    if warehouse_stage(request):
        get_object_or_404(warehouse_tube_orders(request), pk=order.pk)
        return
    # 每个动作单独检查自己的原单工艺范围，不能拼接两种权限的范围。
    for permission in (VIEW_PERMISSION, RETURN_PERMISSION):
        if not module_policy.has_permission(request, permission):
            continue
        try:
            require_saved_order_access(request, order, permission)
            return
        except APIException:
            continue
    raise PermissionDenied('当前账号没有查看该外发单最终回货凭证的工艺权限。')


def dispatch_evidence_blockers(order):
    """已发出必须有真实原单动作；状态字段本身不能证明曾发料。"""
    lines = list(order.lines.all())
    actions = {row.kind: row for row in order.actions.all()}
    dispatch = actions.get('DISPATCH')
    if not lines or dispatch is None or actions.get('CANCEL') is not None:
        return ['原单缺少有效的整单实际发出凭证，不能登记回货。']
    if not isinstance(dispatch.snapshot, dict) or dispatch.snapshot.get('quantity') != sum(line.quantity for line in lines):
        return ['原单实际发出数量与保存明细不一致，请核对原凭证。']
    from .tube_materials import material_dispatch_blockers
    material_blockers = material_dispatch_blockers(order, dispatch)
    if material_blockers:
        return material_blockers
    for line in lines:
        try:
            identity = validate_public_identity(line.snapshot.get('public_output_identity') if isinstance(line.snapshot, dict) else None)
            codes = CUTTING_CRAFT_CODES if order.source_kind in CUTTING_SOURCES else {'POWDER_COATING'}
            if (identity['stock_kind'] != 'SEMI' or identity['identity_snapshot']['unit_name'] != output_unit(order.source_kind)
                    or identity['identity_snapshot']['completed_craft']['code'] not in codes
                    or identity['identity_snapshot']['completed_craft']['id'] != str(order.craft_id)):
                raise ValueError('加工身份不匹配')
        except (ValueError, TypeError, KeyError, APIException):
            return ['原单缺少完整的冻结加工半成品身份，请核对原凭证。']
    if order.source_kind in DIRECT_SOURCES:
        return [] if not dispatch.snapshot.get('movements') else ['未入库半成品原单存在异常扣库凭证。']
    movements = list(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH',
        source_id=order.pk, direction='OUT').select_related('balance'))
    by_line = {row.source_line_id: row for row in movements}
    saved_rows = dispatch.snapshot.get('movements')
    if not isinstance(saved_rows, list) or any(not isinstance(row, dict) for row in saved_rows):
        return ['原单实际发出扣库流水快照不完整，请核对原凭证。']
    saved = {row.get('line_id'): row.get('movement_id') for row in saved_rows}
    if len(movements) != len(lines) or len(saved) != len(lines):
        return ['原单实际发出扣库流水不完整，请核对原凭证。']
    for line in lines:
        movement = by_line.get(line.pk)
        if (movement is None or saved.get(str(line.pk)) != str(movement.pk)
                or movement.quantity != line.stock_quantity or movement.balance.zone_id != order.zone_id
                or not isinstance(line.input_identity, dict)
                or movement.balance.identity_key != line.input_identity.get('identity_key')):
            return ['原单实际发出扣库流水与冻结明细不一致，请核对原凭证。']
        if order.source_kind == 'RAW_PIPE':
            try:
                meters = Decimal(str(line.snapshot.get('meters')))
                matches = meters.is_finite() and meters > 0 and movement.meter_quantity == meters
            except (InvalidOperation, TypeError, ValueError, ArithmeticError):
                matches = False
            if not matches:
                return ['原单实际发出米数与冻结凭证不一致，请核对原凭证。']
    return []


def receipt_queryset():
    return TubeOutsourcingReceipt.objects.select_related('order', 'warehouse', 'actor_employee').prefetch_related(
        'lines__order_line', 'lines__zone')


def receipt_data(receipt, *, created=False):
    header = receipt.snapshot
    rows = []
    for row in sorted(receipt.lines.all(), key=lambda value: str(value.order_line_id)):
        saved = row.snapshot
        rows.append({'id': str(row.pk), 'order_line_id': str(row.order_line_id),
            **line_price_data(row.order_line),
            **{key: saved.get(key) for key in CUTTING_FIELDS},
            'component_identity': str(row.order_line.component_identity),
            **{key: saved.get(key) for key in ('part_name', 'material', 'specification', 'thickness',
                                              'cutting_length_mm', 'raw_color', 'spray_color', 'factory_name')},
            'factory_id': str(row.order_line.factory_id), 'dispatched_quantity': str(row.dispatched_quantity),
            'received_quantity': str(row.received_quantity), 'shortage_quantity': str(row.shortage_quantity),
            'shortage_reason': row.shortage_reason, 'zone_id': str(row.zone_id) if row.zone_id else None,
            'zone_name': saved.get('zone_name', ''),
            'stock_movement_id': str(row.stock_movement_id) if row.stock_movement_id else None})
    return {'id': str(receipt.pk), 'receipt_number': receipt.receipt_number, 'order_id': str(receipt.order_id),
        'order_number': header.get('order_number', receipt.order.order_number), 'status': 'COMPLETED',
        'source_kind': receipt.order.source_kind, 'source_label': SOURCE_LABELS[receipt.order.source_kind],
        'category': source_category(receipt.order.source_kind), 'output_unit': output_unit(receipt.order.source_kind),
        'craft_id': str(receipt.order.craft_id), 'craft_name': receipt.order.craft.name,
        'client_request_id': str(receipt.client_request_id), 'receipt_date': str(receipt.receipt_date),
        'warehouse_id': str(receipt.warehouse_id) if receipt.warehouse_id else None,
        'warehouse_name': header.get('warehouse_name', ''), 'confirmed_at': receipt.created_at.isoformat(),
        'actor_name': header.get('actor_name', receipt.actor_employee.display_name), 'remark': receipt.remark,
        'total_dispatched_quantity': str(sum(row.dispatched_quantity for row in receipt.lines.all())),
        'total_received_quantity': str(sum(row.received_quantity for row in receipt.lines.all())),
        'total_shortage_quantity': str(sum(row.shortage_quantity for row in receipt.lines.all())),
        'planned_amount': planned_amount(row.order_line for row in receipt.lines.all()),
        'etag': etag_for_instance(receipt.order), 'created': created, 'lines': rows}


def receipt_preview(order, request):
    from .warehouse_access import warehouse_stage
    warehouse = warehouse_stage(request)
    if warehouse or order.status == 'COMPLETED':
        require_receipt_read_access(request, order)
    else:
        require_saved_order_access(request, order, RETURN_PERMISSION)
    receipt = receipt_queryset().filter(order=order).first()
    blockers = []
    if warehouse and not (module_policy.has_permission(request, RETURN_PERMISSION)
            and saved_orders_for_permission(request, RETURN_PERMISSION).filter(pk=order.pk).exists()):
        blockers.append('当前账号没有该外发单的回货确认权限。')
    if order.status != 'PROCESSING':
        blockers.append({'PENDING_DISPATCH': '原单尚未实际发出。', 'CANCELLED': '原单已取消。',
                         'COMPLETED': '原单已一次性结束，不能追加回货。'}.get(order.status, '原单状态不能登记回货。'))
    elif receipt is not None:
        blockers.append('原单已有最终回货凭证，不能重复登记。')
    else:
        blockers.extend(dispatch_evidence_blockers(order))
    zones = list(WarehouseZone.objects.filter(status='ACTIVE', warehouse__status='ACTIVE',
        warehouse__warehouse_type='SEMI_FINISHED').select_related('warehouse').order_by('warehouse_id', 'zone_name', 'pk'))
    warehouses = {str(zone.warehouse_id): {'id': str(zone.warehouse_id), 'name': zone.warehouse.warehouse_name}
                  for zone in zones}
    return {'order': saved_order_data(order, request=request, include_metal_basis=False),
        'etag': etag_for_instance(order), 'can_receive': not blockers, 'blockers': blockers,
        'actor_name': request.employee.display_name, 'today': str(timezone.localdate()),
        'warehouses': list(warehouses.values()), 'zones': [{'id': str(zone.pk), 'warehouse_id': str(zone.warehouse_id),
            'warehouse': zone.warehouse.warehouse_name, 'name': zone.zone_name} for zone in zones],
        'receipt': receipt_data(receipt) if receipt else None}


def receipt_candidates(request, data):
    eligible = saved_orders_for_permission(request, RETURN_PERMISSION).filter(status='PROCESSING').annotate(
        has_dispatch=Exists(TubeOutsourcingAction.objects.filter(order_id=OuterRef('pk'), kind='DISPATCH')),
        has_cancel=Exists(TubeOutsourcingAction.objects.filter(order_id=OuterRef('pk'), kind='CANCEL')),
        has_receipt=Exists(TubeOutsourcingReceipt.objects.filter(order_id=OuterRef('pk'))),
    ).filter(has_dispatch=True, has_cancel=False, has_receipt=False)
    if data.get('category', 'tube') == 'cutting':
        eligible = eligible.filter(source_kind__in=CUTTING_SOURCES)
    else:
        eligible = eligible.exclude(source_kind__in=CUTTING_SOURCES)
    if data.get('source_kind'):
        eligible = eligible.filter(source_kind=data['source_kind'])
    search = data.get('search', '').strip()
    if search:
        eligible = eligible.filter(Q(order_number__icontains=search)
            | Q(product_line__product_number_snapshot__icontains=search)
            | Q(product_line__item_number_snapshot__icontains=search)
            | Q(product_line__product_name_snapshot__icontains=search)
            | Q(lines__snapshot__factory_name__icontains=search)
            | Q(materials__snapshot__factory_name__icontains=search)
            | Q(schedule_product__schedule__production_task__task_number__icontains=search)
            | Q(schedule_product__schedule__production_task__order_number__icontains=search)).distinct()
    total = eligible.count()
    offset = (data['page'] - 1) * data['page_size']
    page = list(tube_order_queryset().filter(pk__in=eligible.values('pk')).order_by('-created_at', '-pk')[
        offset:offset + data['page_size']])
    rows = []
    for order in page:
        summary = product_summary(order.schedule_product)
        dispatch = next(row for row in order.actions.all() if row.kind == 'DISPATCH')
        rows.append({'id': str(order.pk), 'order_number': order.order_number,
            'task_order_number': summary['order_number'], **{key: summary[key] for key in (
                'task_number', 'product_number', 'item_number', 'product_name', 'color')},
            'source_kind': order.source_kind, 'source_label': SOURCE_LABELS[order.source_kind],
            'category': source_category(order.source_kind), 'output_unit': output_unit(order.source_kind),
            'craft_id': str(order.craft_id), 'craft_name': order.craft.name,
            'actual_dispatch_date': str(dispatch.actual_dispatch_date),
            'expected_return_date': str(order.expected_return_date),
            'total_quantity': str(sum(line.quantity for line in order.lines.all())),
            'factory_names': sorted({line.snapshot.get('factory_name', '')
                                     for line in [*order.lines.all(), *order.materials.all()]})})
    return {'items': rows, 'total': total, 'page': data['page'], 'page_size': data['page_size']}
