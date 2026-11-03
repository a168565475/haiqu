"""生产任务页面使用的对象动作提示；实际写入仍由服务再次校验。"""
from rest_framework.exceptions import PermissionDenied

from apps.access_control import module_policy
from apps.access_control.catalog import module_for
from apps.access_control.role_policy import role_scopes
from apps.access_control.resource_scopes import has_legacy_permission
from apps.access_control.sales_policy import access_for

from .models import ProductionTaskStatus


def task_allowed_permissions(request, task):
    access = access_for(request)
    if not access['active']:
        return []
    codes = set(access['actions']) | {row['permission'] for row in access['legacy_sources']}
    result = {code for code in codes if module_for(code) == 'production_tasks'
              and module_policy.has_permission(request, code)}
    if not module_policy.enabled() and request.user.has_perm('production_tasks.change_productiontask'):
        result.update({'access_control.cancel_productiontask', 'access_control.finish_productiontask'})
    followed = None
    for code in tuple(result):
        scopes = role_scopes(request, code)
        if 'FOLLOWED' in scopes and not scopes & {'MODULE', 'ALL'} and not access['is_superuser']:
            if followed is None:
                employee_id = getattr(getattr(request, 'employee', None), 'pk', None)
                followed = any(employee.pk == employee_id for employee in task.followers.all())
            from .selectors import legacy_accessible_production_tasks
            legacy_visible = (has_legacy_permission(request, code)
                              and legacy_accessible_production_tasks(request).filter(pk=task.pk).exists())
            if not followed and not legacy_visible:
                result.discard(code)
    if task.status != ProductionTaskStatus.PENDING_VALIDATION:
        result.discard('production_tasks.confirm_productiontask')
    elif 'production_tasks.confirm_productiontask' in result:
        from apps.access_control.production_approval import check_production_approval
        try:
            check_production_approval(request.employee, task)
        except PermissionDenied:
            result.discard('production_tasks.confirm_productiontask')
    if task.status != ProductionTaskStatus.DRAFT:
        result.discard('production_tasks.submit_productiontask')
    if task.status != ProductionTaskStatus.READY:
        result.discard('production_tasks.start_productiontask')
    if task.status not in {ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION}:
        result.discard('access_control.pause_productiontask')
    if task.status != ProductionTaskStatus.PAUSED:
        result.discard('access_control.resume_productiontask')
    if task.status in {ProductionTaskStatus.COMPLETED, ProductionTaskStatus.CANCELLED}:
        result -= {'production_tasks.change_productiontask', 'access_control.edit_productionplan',
                   'access_control.cancel_productiontask', 'access_control.finish_productiontask'}
    if task.status != ProductionTaskStatus.CANCELLED:
        result.discard('production_tasks.delete_productiontask')
    return sorted(result)
