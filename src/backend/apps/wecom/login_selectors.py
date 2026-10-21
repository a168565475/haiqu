"""企微登录与绑定列表共用的授权资格；具体操作和数据范围仍由业务权限校验。"""
from collections import defaultdict

from django.contrib.auth.models import Permission
from django.db.models import CharField, Exists, ExpressionWrapper, OuterRef, Q

from apps.access_control.catalog import IMPLIED, PERMISSION_CODES, scopes_for
from apps.access_control.management_permissions import MANAGEMENT_OPERATIONS
from apps.access_control.models import RoleActionGrant
from apps.access_control.module_operations import LEGACY_ALIASES
from apps.access_control.resource_scopes import scope_kind
from apps.access_control.sales_operations import LEGACY_ACTION_PERMISSIONS
from apps.access_control.selectors import current_assignments
from .models import WeComBinding


ACTIVE_BINDING = Q(employee__status="ACTIVE", employee__archived_at__isnull=True,
                   employee__user__is_active=True)
MANAGEMENT_CODES = {"organizations.manage_organization"} | {
    f"access_control.{code}" for code, _, _ in MANAGEMENT_OPERATIONS
}
LEGACY_CODES = (set(PERMISSION_CODES) | {code for children in IMPLIED.values() for code in children}
                | set(LEGACY_ALIASES.values()) | set(LEGACY_ACTION_PERMISSIONS.values())) - MANAGEMENT_CODES


def permission_filter(codes, prefix="permission__"):
    by_app = defaultdict(list)
    for code in codes:
        app, codename = code.split(".", 1)
        by_app[app].append(codename)
    result = Q(pk__in=[])
    for app, codenames in by_app.items():
        result |= Q(**{prefix + "content_type__app_label": app, prefix + "codename__in": codenames})
    return result


def role_action_filter():
    by_scopes = defaultdict(list)
    for code in PERMISSION_CODES:
        scopes = set(scopes_for(code))
        # 资源开关回退不会撤销已有动作；空资源仍由原业务选择器返回空范围。
        resource_scope = scope_kind(code)
        if resource_scope:
            scopes.add(resource_scope)
            if code.startswith("outsourcing.") and "outsourcingorder" in code:
                scopes.update(("WORKSHOP", "STOCK"))
        by_scopes[tuple(sorted(scopes))].append(code)
    result = Q(pk__in=[])
    for scopes, codes in by_scopes.items():
        result |= (permission_filter(codes, "role_profile__action_grants__permission__")
                   & Q(role_profile__action_grants__scope__in=scopes))
    return result


def bindings_with_login_permission():
    assignments = current_assignments(OuterRef("employee_id"))
    role_actions = assignments.filter(role_action_filter())
    legacy_permissions = Permission.objects.filter(permission_filter(LEGACY_CODES, ""))
    direct = legacy_permissions.filter(user=OuterRef("employee__user_id"))
    groups = legacy_permissions.filter(group__user=OuterRef("employee__user_id"))

    # 同一角色已投影的权限（包括隐含权限）不是独立历史授权，非法范围不能借此绕过。
    legacy_role = assignments.filter(permission_filter(LEGACY_CODES, "role_profile__auth_group__permissions__"))
    projected = RoleActionGrant.objects.filter(role_id=OuterRef("role_profile_id")).alias(
        legacy_app=ExpressionWrapper(OuterRef("role_profile__auth_group__permissions__content_type__app_label"),
                                     output_field=CharField()),
        legacy_code=ExpressionWrapper(OuterRef("role_profile__auth_group__permissions__codename"),
                                      output_field=CharField()),
    )
    projection = Q(permission_id=OuterRef("role_profile__auth_group__permissions__pk"))
    for parent, children in IMPLIED.items():
        for child in children:
            app, codename = child.split(".", 1)
            projection |= permission_filter((parent,)) & Q(legacy_app=app, legacy_code=codename)
    legacy_role = legacy_role.alias(projected_permission=Exists(projected.filter(projection))).filter(
        projected_permission=False)
    return WeComBinding.objects.select_related("employee__user").annotate(
        has_login_permission=(Q(employee__user__is_superuser=True) | Exists(role_actions)
                              | Exists(direct) | Exists(groups) | Exists(legacy_role)),
    )
