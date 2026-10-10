import hashlib
import json

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from .catalog import catalog, permission_code
from .models import RoleActionGrant


def business_scope_enforcement():
    sales = bool(getattr(settings, 'SALES_ACCESS_ENABLED', False))
    modules = bool(getattr(settings, 'MODULE_ACCESS_ENABLED', False))
    return 'ENABLED' if sales and modules else 'PARTIAL' if sales or modules else 'DISABLED'


def current_assignments(employee, now=None):
    now = now or timezone.now()
    return EmployeeRoleAssignment.objects.filter(
        employee=employee, role_profile__archived_at__isnull=True, effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))


def role_grants(role):
    queryset = RoleActionGrant.objects.filter(role=role).select_related("permission__content_type").order_by(
        "permission__content_type__app_label", "permission__codename", "scope",
    )
    from .resource_scopes import configured
    return queryset.prefetch_related('resource_selections') if configured() else queryset


def grant_rows(role):
    from .resource_scopes import selected_ids
    return [{"permission": permission_code(g.permission), "scope": g.scope,
             **({'resource_ids': selected_ids(g)} if g.scope in {'WORKSHOP', 'CRAFT'} else {})} for g in role_grants(role)]


def role_snapshot(role):
    return {
        "id": str(role.pk), "role_code": role.role_code, "display_name": role.display_name,
        "description": role.description, "archived": role.archived_at is not None,
        "grants": grant_rows(role),
    }


def effective_access(user):
    """Per-action union. Legacy permissions are explicit, never guessed into scopes.

    These results do not replace business selectors until stages 4/5 integrate them.
    Queries intentionally use fresh rows; no session or cross-request grants cache.
    """
    employee = Employee.objects.filter(user_id=user.pk, status="ACTIVE", archived_at__isnull=True).first()
    active = bool(user.is_active and employee)
    actions = {}
    legacy = []
    roles = []
    if active and user.is_superuser:
        actions = {item["code"]: {"scopes": ["ALL"] if "ALL" in item["scopes"] else ["MODULE"],
                                   "sources": [{"type": "SUPERUSER"}]} for item in catalog() if item["available"]}
    elif active:
        assignments = current_assignments(employee).select_related("role_profile").order_by("role_profile__role_code")
        role_ids = []
        for assignment in assignments:
            role = assignment.role_profile
            role_ids.append(role.pk)
            roles.append({"id": str(role.pk), "code": role.role_code, "name": role.display_name})
        from .resource_scopes import configured, selected_ids
        grants = RoleActionGrant.objects.filter(role_id__in=role_ids).select_related("permission__content_type", "role")
        if configured():
            grants = grants.prefetch_related('resource_selections')
        for grant in grants:
            code = permission_code(grant.permission)
            entry = actions.setdefault(code, {"scopes": [], "sources": []})
            if grant.scope not in entry["scopes"]:
                entry["scopes"].append(grant.scope)
            entry["sources"].append({"type": "ROLE", "role_id": str(grant.role_id), "scope": grant.scope,
                                     **({'resource_ids': selected_ids(grant)} if grant.scope in {'WORKSHOP', 'CRAFT'} else {})})
        for permission in user.user_permissions.select_related("content_type").order_by("id"):
            legacy.append({"type": "DIRECT", "permission": permission_code(permission)})
        for group in user.groups.order_by("id"):
            for permission in group.permissions.select_related("content_type").order_by("id"):
                legacy.append({"type": "GROUP", "group_id": group.pk, "name": group.name, "permission": permission_code(permission)})
        # Non-projected permissions on historical role groups remain visible.
        from .catalog import projected_permission_ids
        for role in RoleProfile.objects.filter(pk__in=role_ids).select_related("auth_group"):
            projected = projected_permission_ids([(g.permission, g.scope) for g in role_grants(role)])
            for p in role.auth_group.permissions.exclude(pk__in=projected).select_related("content_type").order_by("id"):
                legacy.append({"type": "LEGACY_ROLE", "role_id": str(role.pk), "permission": permission_code(p)})
    for value in actions.values():
        value["scopes"].sort()
        value["sources"].sort(key=lambda x: json.dumps(x, sort_keys=True))
    legacy.sort(key=lambda x: json.dumps(x, sort_keys=True))
    payload = {"active": active, "is_superuser": bool(active and user.is_superuser), "roles": roles,
               "actions": actions, "legacy_sources": legacy,
               "business_scope_enforcement": business_scope_enforcement()}
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def scopes_for_user(user, permission):
    return frozenset(effective_access(user)["actions"].get(permission, {}).get("scopes", []))
