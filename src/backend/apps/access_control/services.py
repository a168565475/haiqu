from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from .catalog import projected_permission_ids, validate_grants
from .models import RoleActionGrant
from .permissions import CanManageAccess
from .selectors import grant_rows, role_grants, role_snapshot


def require_manager(request, code='access_control.manage_access'):
    permission = CanManageAccess()
    permission.code = code
    if not permission.has_permission(request, None):
        raise PermissionDenied(permission.message)
    employee = active_employee_for(request.user)
    if employee is None:
        raise PermissionDenied("需要有效员工档案记录授权操作者。")
    return employee


def audit(request, instance, action, before, after, object_type="ACCESS_ROLE"):
    employee = active_employee_for(request.user)
    if employee is None:
        raise PermissionDenied("需要有效员工档案记录管理操作者。")
    write_audit_log(object_type=object_type, object_id=instance.pk, action=action,
                    actor_employee=employee, before_data=before, after_data=after, request=request)


def assert_managed_projection(role):
    # Never overwrite historical direct/group permissions while adopting a role.
    expected = projected_permission_ids([(g.permission, g.scope) for g in role_grants(role)])
    if set(role.auth_group.permissions.values_list("pk", flat=True)) != expected:
        raise Conflict("此角色含历史授权或投影差异，请先审阅旧授权，不能直接覆盖。")
    if role.auth_group.user_set.exists():
        raise Conflict("此角色组仍有原生账号成员，请先审阅成员来源，不能直接修改或复制。")


def locked_role(pk, request):
    role = get_object_or_404(RoleProfile.objects.select_for_update(), pk=pk)
    require_matching_etag(request, role)
    assert_managed_projection(role)
    return role


def _create_role(data):
    if RoleProfile.objects.filter(display_name=data["display_name"]).exists():
        raise ValidationError({"display_name": "角色名称已存在。"})
    try:
        with transaction.atomic():
            group = Group.objects.create(name=f"ERP_ROLE:{data['role_code']}")
            return RoleProfile.objects.create(auth_group=group, **data)
    except IntegrityError as exc:
        raise Conflict("角色编码或对应权限组已存在。") from exc


@transaction.atomic
def create_role(request, data):
    require_manager(request)
    role = _create_role(data)
    audit(request, role, "ROLE_CREATE", {}, role_snapshot(role))
    return role


@transaction.atomic
def update_role(request, pk, data):
    actor = require_manager(request)
    role = locked_role(pk, request)
    before = role_snapshot(role)
    if "display_name" in data and RoleProfile.objects.exclude(pk=pk).filter(display_name=data["display_name"]).exists():
        raise ValidationError({"display_name": "角色名称已存在。"})
    for field in ("display_name", "description"):
        if field in data:
            setattr(role, field, data[field])
    if "archived" in data:
        role.archived_at = timezone.now() if data["archived"] else None
        role.archived_by_employee = actor if data["archived"] else None
        role.archive_reason = "管理员停用角色" if data["archived"] else ""
    role.save()
    audit(request, role, "ROLE_UPDATE", before, role_snapshot(role))
    return role


@transaction.atomic
def replace_grants(request, pk, rows):
    require_manager(request)
    role = locked_role(pk, request)
    if role.archived_at:
        raise Conflict("请先启用角色，再修改授权。")
    grants = validate_grants(rows)
    from .resource_scopes import validate_resources, save_resources
    selections = validate_resources(rows)
    before = role_snapshot(role)
    permission_ids = projected_permission_ids(grants)
    from .resource_scopes import configured
    if configured():
        from .models import RoleGrantResource
        RoleGrantResource.objects.filter(grant__role=role).delete()
    RoleActionGrant.objects.filter(role=role).delete()
    RoleActionGrant.objects.bulk_create([RoleActionGrant(role=role, permission=p, scope=s) for p, s in grants])
    save_resources(role, selections)
    role.auth_group.permissions.set(permission_ids)
    role.save(update_fields=["updated_at"])
    audit(request, role, "ROLE_GRANTS_REPLACE", before, role_snapshot(role))
    return role


@transaction.atomic
def add_module_grant(request, pk, permission_code):
    """单项追加MODULE授权，保留既有授权及资源记录；已有同项时不重复审计。"""
    require_manager(request)
    role = locked_role(pk, request)
    if role.archived_at:
        raise Conflict("请先启用角色，再修改授权。")
    permission, scope = validate_grants([{"permission": permission_code, "scope": "MODULE"}])[0]
    existing = list(RoleActionGrant.objects.filter(role=role, permission=permission))
    if existing:
        if len(existing) == 1 and existing[0].scope == scope:
            return role, False
        raise Conflict("该动作已有其他范围授权，请先审阅，不能直接扩大范围。")
    before = role_snapshot(role)
    grant = RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
    role.auth_group.permissions.add(*projected_permission_ids([(permission, scope)]))
    role.save(update_fields=["updated_at"])
    audit(request, role, "ROLE_GRANT_ADD", before, {
        **role_snapshot(role), "added_grant": {"permission": permission_code, "scope": scope,
            "resource_ids": [], "grant_id": str(grant.pk)},
    })
    assert_managed_projection(role)
    return role, True


@transaction.atomic
def copy_role(request, pk, data):
    require_manager(request)
    source = locked_role(pk, request)
    if source.archived_at:
        raise Conflict("不能复制已停用角色。")
    rows = grant_rows(source)
    grants = validate_grants(rows)
    from .resource_scopes import validate_resources, save_resources
    selections = validate_resources(rows)
    role = _create_role(data)
    RoleActionGrant.objects.bulk_create([RoleActionGrant(role=role, permission=p, scope=s) for p, s in grants])
    role.auth_group.permissions.set(projected_permission_ids(grants))
    save_resources(role, selections)
    after = role_snapshot(role)
    after["copied_from_role_id"] = str(source.pk)
    audit(request, role, "ROLE_COPY", {}, after)
    return role


@transaction.atomic
def replace_employee_roles(request, pk, role_ids):
    actor = require_manager(request)
    # Audit actor FKs can take KEY SHARE concurrently without a lock-order cycle.
    employee = get_object_or_404(Employee.objects.select_for_update(no_key=True), pk=pk)
    require_matching_etag(request, employee)
    if employee.archived_at or employee.status != "ACTIVE":
        raise Conflict("只能为有效员工分配角色。")
    if len(set(role_ids)) != len(role_ids):
        raise ValidationError({"role_ids": "角色不可重复。"})
    # Deterministic locks serialize grant/role edits and prevent lock-order cycles.
    roles = list(RoleProfile.objects.select_for_update().filter(pk__in=role_ids).order_by("id"))
    if len(roles) != len(role_ids) or any(r.archived_at for r in roles):
        raise ValidationError({"role_ids": "包含不存在或已停用的角色。"})
    for role in roles:
        assert_managed_projection(role)
    now = timezone.now()
    if EmployeeRoleAssignment.objects.filter(employee=employee, effective_from__gt=now).exists():
        raise Conflict("存在未来生效的历史角色分配，请先审阅，不能静默覆盖。")
    # Include inactive roles so a later restore cannot resurrect a removed grant.
    existing = list(EmployeeRoleAssignment.objects.filter(employee=employee, effective_from__lte=now)
                    .filter(transaction_range_open(now)).select_for_update())
    before = {"role_ids": sorted(str(a.role_profile_id) for a in existing)}
    wanted = set(role_ids)
    current = {a.role_profile_id for a in existing}
    for assignment in existing:
        if assignment.role_profile_id not in wanted:
            assignment.effective_to = now
            assignment.save(update_fields=["effective_to", "updated_at"])
    for role in roles:
        if role.pk not in current:
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=now, assigned_by_employee=actor)
    employee.save(update_fields=["updated_at"])
    audit(request, employee, "EMPLOYEE_ROLES_REPLACE", before, {"role_ids": sorted(str(pk) for pk in wanted)}, "ACCESS_EMPLOYEE")
    return employee


def transaction_range_open(now):
    from django.db.models import Q
    return Q(effective_to__isnull=True) | Q(effective_to__gt=now)
