"""仓库委外读取按实际操作授权取并集，不借查看权限扩大操作范围。"""
from django.db.models import Exists, OuterRef, Q
from rest_framework import serializers

from apps.access_control import module_policy
from apps.access_control.resource_scopes import filter_crafts
from apps.core.api.permissions import BusinessActionPermission
from apps.material_issues.models import MetalProcessingExternalOrder, MetalProcessingOriginalHandoff
from apps.material_issues.p4_access import scoped_records

from .models import OutsourcingOrder, TubeOutsourcingOrder
from .selectors import accessible_outsourcing_orders
from .tube_selectors import DISPATCH_PERMISSION, RETURN_PERMISSION, saved_orders_for_permission


RAW_RETURN_PERMISSION = 'outsourcing.return_raw_outsourcingorder'
REWORK_RETURN_PERMISSION = 'material_issues.confirm_metalprocessingexternalreturn'
ORIGINAL_HANDOFF_PERMISSION = 'material_issues.create_metalprocessingoriginalhandoff'
REWORK_HANDOFF_PERMISSION = 'material_issues.confirm_metalprocessingexternalhandoff'
WAREHOUSE_PERMISSIONS = (DISPATCH_PERMISSION, RETURN_PERMISSION, RAW_RETURN_PERMISSION,
                         ORIGINAL_HANDOFF_PERMISSION, REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION)


def warehouse_stage(request):
    value = getattr(request, 'query_params', {}).get('warehouse_stage')
    if value is None:
        return None
    return serializers.ChoiceField(choices=['all']).run_validation(value)


def warehouse_read_permission(request, view):
    if view.action not in getattr(view, 'warehouse_read_actions', ()) or not warehouse_stage(request):
        return None
    permissions = getattr(view, 'warehouse_read_permissions', WAREHOUSE_PERMISSIONS)
    return any(module_policy.has_permission(request, permission) for permission in permissions)


class WarehouseActionReadPermission(BusinessActionPermission):
    def has_permission(self, request, view):
        allowed = warehouse_read_permission(request, view)
        return super().has_permission(request, view) if allowed is None else allowed


def warehouse_regular_orders(request, permission=None):
    permissions = (permission,) if permission else (DISPATCH_PERMISSION, RETURN_PERMISSION, RAW_RETURN_PERMISSION)
    allowed = Q(pk__in=[])
    for code in permissions:
        if module_policy.has_permission(request, code):
            # 旧金工直接交接使用独立来源投影和回货接口。
            scoped = accessible_outsourcing_orders(request, permission=code).filter(metal_processing_original_handoffs__isnull=True)
            allowed |= Q(pk__in=scoped.values('pk'))
    return OutsourcingOrder.objects.filter(allowed)


def warehouse_original_handoffs(request):
    queryset = MetalProcessingOriginalHandoff.objects.all()
    allowed = Q(pk__in=[])
    for permission in (ORIGINAL_HANDOFF_PERMISSION, RETURN_PERMISSION):
        if module_policy.has_permission(request, permission):
            scoped = scoped_records(queryset, request, permission, 'original_order__craft_id')
            allowed |= Q(pk__in=scoped.values('pk'))
    return queryset.filter(allowed)


def warehouse_original_dispatch_orders(request):
    """只使用已保存的原单交接关系；首次选择来源仍由车间建立。"""
    if not module_policy.has_permission(request, ORIGINAL_HANDOFF_PERMISSION):
        return OutsourcingOrder.objects.none()
    handoffs = scoped_records(MetalProcessingOriginalHandoff.objects.all(), request,
                             ORIGINAL_HANDOFF_PERMISSION, 'original_order__craft_id')
    outside_scope = MetalProcessingOriginalHandoff.objects.filter(original_order_id=OuterRef('pk')).exclude(
        pk__in=warehouse_original_handoffs(request).values('pk'))
    # 列表操作和原单详情使用同一整单读取边界，不能只看到一条来源就给整单交接入口。
    return OutsourcingOrder.objects.filter(pk__in=handoffs.values('original_order_id')).filter(~Exists(outside_scope))


def warehouse_rework_orders(request, permission=None):
    queryset = MetalProcessingExternalOrder.objects.all()
    allowed = Q(pk__in=[])
    for code in (permission,) if permission else (REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION):
        if module_policy.has_permission(request, code):
            allowed |= Q(pk__in=scoped_records(queryset, request, code).values('pk'))
    return queryset.filter(allowed)


def warehouse_tube_orders(request, permission=None):
    permissions = (permission,) if permission else (DISPATCH_PERMISSION, RETURN_PERMISSION)
    allowed = Q(pk__in=[])
    for code in permissions:
        if module_policy.has_permission(request, code):
            scoped = saved_orders_for_permission(request, code)
            allowed |= Q(pk__in=scoped.values('pk'))
    return TubeOutsourcingOrder.objects.filter(allowed)


def warehouse_crafts(request, crafts):
    allowed = Q(pk__in=[])
    for code in WAREHOUSE_PERMISSIONS:
        if module_policy.has_permission(request, code):
            scoped = filter_crafts(crafts, request, code, 'pk')
            if code in (ORIGINAL_HANDOFF_PERMISSION, REWORK_HANDOFF_PERMISSION, REWORK_RETURN_PERMISSION):
                scoped = scoped.filter(outsourcing_code='POWDER_COATING')
            allowed |= Q(pk__in=scoped.values('pk'))
    return crafts.filter(allowed)
