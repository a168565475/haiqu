"""已确认岗位的对象范围与计划字段边界，不把关联读取升级为模块权限。"""
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.auth import active_employee_for
from .sales_policy import access_for


PLAN_EDIT_PERMISSION = 'access_control.edit_productionplan'
PLAN_UPDATE_FIELDS = ('planned_start_date', 'planned_end_date', 'production_priority', 'follower_ids')

# FOLLOWED只允许有生产任务归属的读取动作；写动作不能选择这个范围。
FOLLOWED_PERMISSIONS = frozenset({
    'production_tasks.view_productiontask', 'production_tasks.view_productiontaskcost',
    'boms.view_bom', 'production_scheduling.view_productionschedule',
    'procurement.view_purchaseorder', 'procurement.view_supplierpurchasesheet',
    'material_issues.view_materialissue', 'material_issues.view_metalprocessingsource',
    'workshop_reporting.view_workreport', 'outsourcing.view_outsourcingorder',
    'inventory.view_material_receipt', 'inventory.view_materialinbound',
    'inventory.view_internalsemifinishedreceipt', 'inventory.view_finishedgoodsreceipt',
    'inventory.view_finishedgoodsoutbound',
})
STATEMENT_OWN_PERMISSIONS = frozenset({'finance.view_receivablestatement', 'finance.view_receipt'})


def role_scopes(request, permission):
    access = access_for(request)
    if not access['active']:
        return frozenset()
    return frozenset(source['scope'] for source in access['actions'].get(permission, {}).get('sources', [])
                     if source['type'] == 'ROLE' and source.get('scope'))


def has_role_scope(request, permission, scope):
    return scope in role_scopes(request, permission)


def filter_task_scope(request, queryset, permission, task_lookup='production_task'):
    """只返回该动作的新角色授权；调用方另并入该动作的车间/旧授权范围。

    task_lookup=''用于ProductionTask本身；关联对象使用production_task等ORM路径。
    """
    access = access_for(request)
    if not access['active']:
        return queryset.none()
    scopes = role_scopes(request, permission)
    if access['is_superuser'] or scopes & {'MODULE', 'ALL'}:
        return queryset
    employee = active_employee_for(request.user)
    if permission in FOLLOWED_PERMISSIONS and 'FOLLOWED' in scopes and employee:
        prefix = f'{task_lookup}__' if task_lookup else ''
        return queryset.filter(**{f'{prefix}followers': employee}).distinct()
    return queryset.none()


def filter_statement_scope(request, queryset, permission, statement_lookup=''):
    """OWN只使用对账单保存的业务员，绝不回读当前生产任务业务员。"""
    access = access_for(request)
    if not access['active']:
        return queryset.none()
    scopes = role_scopes(request, permission)
    if access['is_superuser'] or scopes & {'MODULE', 'ALL'}:
        return queryset
    employee = active_employee_for(request.user)
    if permission in STATEMENT_OWN_PERMISSIONS and 'OWN' in scopes and employee:
        prefix = f'{statement_lookup}__' if statement_lookup else ''
        return queryset.filter(**{f'{prefix}salesperson_id': employee.pk}).distinct()
    return queryset.none()


def allowed_task_update_fields(request):
    """None=完整编辑授权；空元组=不可编辑；否则为准许的输入字段。"""
    from .module_policy import has_permission
    if has_permission(request, 'production_tasks.change_productiontask'):
        return None
    if has_permission(request, PLAN_EDIT_PERMISSION):
        return PLAN_UPDATE_FIELDS
    return ()


def require_task_edit_fields(request, fields):
    allowed = allowed_task_update_fields(request)
    if allowed is None:
        return
    if not allowed:
        raise PermissionDenied('没有修改生产任务的权限。')
    forbidden = set(fields) - (set(allowed) | {'followers'})
    if forbidden:
        raise ValidationError({field: '当前权限只能修改计划日期、优先级和跟单员。'
                               for field in sorted(forbidden)})
