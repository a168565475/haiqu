"""采购来源的数据范围，供采购、采购表和仓库共同使用。"""
from django.db.models import Q

from apps.samples.models import SampleRequest
from apps.samples.selectors import accessible_sample_requests


def current_operations(request, default):
    from apps.access_control import module_policy
    view = (getattr(request, 'parser_context', None) or {}).get('view')
    permission = module_policy.action_permission(request, view) if view is not None else None
    permissions = permission if isinstance(permission, (tuple, list)) else (permission or default,)
    return tuple(code for code in permissions if module_policy.has_permission(request, code))


def accessible_purchase_samples(request, permission=None):
    if not request or not getattr(request, "employee", None):
        return SampleRequest.objects.none()
    from apps.access_control import module_policy
    from apps.access_control.role_policy import role_scopes
    from apps.access_control.resource_scopes import has_legacy_permission
    operations = (permission,) if permission else current_operations(request, 'procurement.view_purchaseorder')
    if module_policy.enabled():
        if request.user.is_superuser or any(role_scopes(request, code) & {'MODULE', 'ALL'} for code in operations):
            return SampleRequest.objects.filter(archived_at__isnull=True, customer_account__archived_at__isnull=True)
        if not any(has_legacy_permission(request, code) for code in operations):
            # FOLLOWED只有生产任务关系，不能由其它岗位的模块授权附赠样品范围。
            return SampleRequest.objects.none()
    user = request.user
    if user.is_superuser or user.has_perm("samples.view_sample_procurement"):
        permission = "view_sample_procurement"
    elif user.has_perm("samples.review_sample_materials"):
        permission = "review_sample_materials"
    elif any(user.has_perm("inventory." + code) for code in ("quality_confirm_material", "receive_material", "view_materialinbound", "view_material_receipt")):
        # 库存操作权限不授予全体样品可见性，仍按客户和申请归属计算范围。
        permission = "view_samplerequest"
    else:
        return SampleRequest.objects.none()
    return accessible_sample_requests(request, permission).filter(
        archived_at__isnull=True, customer_account__archived_at__isnull=True,
    )


def purchase_order_access(allowed_task_ids, request, prefix="", *, permission=None):
    return Q(**{prefix + "production_task_id__in": allowed_task_ids}) | Q(**{
        prefix + "sample_procurement_request__material_request__sample_request__in": accessible_purchase_samples(request, permission),
    })
