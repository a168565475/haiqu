from rest_framework.permissions import BasePermission

from apps.core.auth import active_employee_for


class HasActiveEmployee(BasePermission):
    message = "当前账号没有有效员工档案，无法使用业务接口。"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        employee = active_employee_for(user)
        if employee is None:
            return False

        request.employee = employee
        return True


class BusinessActionPermission(BasePermission):
    message = "当前账号没有执行此操作的权限。"

    def has_permission(self, request, view):
        from apps.access_control.sales_policy import action_permission, enabled, has_permission
        from apps.access_control import module_policy
        if module_policy.enabled() and type(view).__name__ in module_policy.ACTION_OVERRIDES:
            permission = module_policy.action_permission(request, view)
            if isinstance(permission, (list, tuple, set)):
                return any(module_policy.has_permission(request, item) for item in permission)
            return bool(permission and module_policy.has_permission(request, permission))
        permission = action_permission(request, view)
        if not permission:
            return False
        if isinstance(permission, (list, tuple, set)):
            return any(has_permission(request, item) for item in permission) if enabled() else any(request.user.has_perm(item) for item in permission)
        return has_permission(request, permission) if enabled() else request.user.has_perm(permission)
