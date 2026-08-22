from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import BasePermission


class HasActiveEmployee(BasePermission):
    message = "当前账号没有有效员工档案，无法使用业务接口。"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            request.employee = None
            return True

        try:
            employee = user.employee_profile
        except ObjectDoesNotExist:
            return False

        if employee.status != "ACTIVE" or employee.archived_at is not None:
            return False

        request.employee = employee
        return True


class BusinessActionPermission(BasePermission):
    message = "当前账号没有执行此操作的权限。"

    def has_permission(self, request, view):
        permission_map = getattr(view, "action_permission_map", {})
        action = getattr(view, "action", None)
        permission = permission_map.get(f"{action}.{request.method}") or permission_map.get(action)
        if not permission:
            return False
        return request.user.has_perm(permission)
