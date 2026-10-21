from django.conf import settings
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission


class AccessManagementUnavailable(APIException):
    status_code = 503
    default_detail = "权限管理尚未启用，请先完成迁移与分阶段验收。"
    default_code = "access_management_unavailable"


class CanManageAccess(BasePermission):
    message = "需要角色与授权管理权限。"
    code = 'access_control.manage_access'

    def has_permission(self, request, view):
        from .management_permissions import can_manage
        if not can_manage(request.user, self.code):
            return False
        if not settings.ACCESS_MANAGEMENT_ENABLED:
            raise AccessManagementUnavailable()
        return True


class CanManageAccounts(CanManageAccess):
    message = "需要员工账号管理权限。"
    code = 'access_control.manage_accounts'


class CanManageWeCom(CanManageAccess):
    message = "需要企业微信管理权限。"
    code = 'access_control.manage_wecom'


class CanManageNotifications(CanManageAccess):
    message = "需要业务通知规则管理权限。"
    code = 'access_control.manage_notifications'


class CanReadAccessDirectory(CanManageAccess):
    message = "需要组织、账号、授权或企业微信管理权限。"

    def has_permission(self, request, view):
        from .management_permissions import can_manage
        if not any(can_manage(request.user, code) for code in (
            'organizations.manage_organization', 'access_control.manage_access',
            'access_control.manage_accounts', 'access_control.manage_wecom',
        )):
            return False
        if not settings.ACCESS_MANAGEMENT_ENABLED:
            raise AccessManagementUnavailable()
        return True


class CanManageOrganization(BasePermission):
    message = "需要部门与组织管理权限。"

    def has_permission(self, request, view):
        from apps.core.auth import active_employee_for
        from .selectors import effective_access
        if active_employee_for(request.user) is None:
            return False
        admin = request.user.is_superuser and request.user.get_username() == "admin"
        if not admin:
            access = effective_access(request.user)
            sources = access["actions"].get("organizations.manage_organization", {}).get("sources", [])
            if not any(s["type"] == "ROLE" and s.get("scope") == "MODULE" for s in sources):
                return False
        if not settings.ACCESS_MANAGEMENT_ENABLED:
            raise AccessManagementUnavailable()
        return True
