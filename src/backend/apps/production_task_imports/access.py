from types import SimpleNamespace

from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied

from apps.access_control import module_policy
from apps.core.auth import active_employee_for


IMPORT_PERMISSION = 'production_task_imports.import_production_task'


def require_actor(request):
    user = get_user_model().objects.filter(pk=request.user.pk).first()
    actor = active_employee_for(user)
    fresh = SimpleNamespace(user=user, employee=actor)
    if actor is None or not all(module_policy.has_permission(fresh, code) for code in
                                (IMPORT_PERMISSION, 'production_tasks.add_productiontask')):
        raise PermissionDenied('需要有效员工身份、生产任务新增及导入权限。')
    return actor


def worker_allowed(actor):
    if not actor.user_id:
        return False
    try:
        require_actor(SimpleNamespace(user=actor.user))
    except PermissionDenied:
        return False
    return True
