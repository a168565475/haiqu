from django.conf import settings
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission


class AccessManagementUnavailable(APIException):
    status_code = 503
    default_detail = "权限管理尚未启用，请先完成迁移与分阶段验收。"
    default_code = "access_management_unavailable"


class CanManageAccess(BasePermission):
    message = "当前仅 admin 超级管理员可以管理授权。"

    def has_permission(self, request, view):
        # Identity is checked before the rollout switch or any new-table reads.
        if not (request.user.is_active and request.user.is_superuser and request.user.get_username() == "admin"):
            return False
        if not settings.ACCESS_MANAGEMENT_ENABLED:
            raise AccessManagementUnavailable()
        return True
