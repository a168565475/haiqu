"""显式启用后，将两个全权角色映射到真实Django超级用户，并保存撤销依据。"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import EmployeeRoleAssignment
from .models import RoleSuperuserState


SUPERUSER_ROLE_CODES = frozenset({
    'GENERAL_MANAGER', settings.CONFIRMED_ADMIN_ROLE_CODE,
})


def configured():
    return bool(getattr(settings, 'CONFIRMED_ROLE_POLICY_ENABLED', False))


def eligible_for_superuser_role(user, now=None):
    if not user.is_active:
        return False
    now = now or timezone.now()
    return EmployeeRoleAssignment.objects.filter(
        employee__user_id=user.pk, employee__status='ACTIVE', employee__archived_at__isnull=True,
        role_profile__role_code__in=SUPERUSER_ROLE_CODES, role_profile__archived_at__isnull=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).exists()


def clear_user_permission_cache(user, request=None):
    for key in ('_perm_cache', '_group_perm_cache', '_user_perm_cache', '_erp_role_perm_cache'):
        user.__dict__.pop(key, None)
    if request is not None:
        request.__dict__.pop('_sales_access_snapshot', None)


def sync_role_superuser(user, *, request=None):
    """应在认证后、权限判断前调用；角色到期/归档/停用即时恢复原生标志。

    关闭开关也撤回已托管的提升。首次尚未迁移且关闭开关时不访问新表。
    原生admin始终独立，不被角色生命周期托管。
    """
    if not user or not user.is_authenticated or not user.pk or user.get_username() == 'admin':
        return user
    if not configured():
        if not user.is_superuser and not user.is_staff:
            return user
        if RoleSuperuserState._meta.db_table not in connection.introspection.table_names():
            return user
    with transaction.atomic():
        stored = get_user_model().objects.select_for_update().get(pk=user.pk)
        state = RoleSuperuserState.objects.select_for_update().filter(user_id=user.pk).first()
        eligible = configured() and eligible_for_superuser_role(stored)
        if eligible and state is None:
            state = RoleSuperuserState.objects.create(user=stored,
                original_is_superuser=stored.is_superuser, original_is_staff=stored.is_staff)
        before = {'is_superuser': stored.is_superuser, 'is_staff': stored.is_staff}
        if eligible:
            stored.is_superuser = stored.is_staff = True
        elif state is not None:
            stored.is_superuser = state.original_is_superuser
            stored.is_staff = state.original_is_staff
            state.delete()
        after = {'is_superuser': stored.is_superuser, 'is_staff': stored.is_staff}
        if before != after:
            stored.save(update_fields=['is_superuser', 'is_staff'])
            from apps.core.audit import write_audit_log
            employee = getattr(stored, 'employee_profile', None)
            if employee is not None:
                from apps.core.auth import active_employee_for
                actor = active_employee_for(request.user) if request is not None else None
                write_audit_log(object_type='ACCESS_EMPLOYEE', object_id=employee.pk,
                    action='ROLE_SUPERUSER_SYNC', actor_employee=actor,
                    before_data=before, after_data=after, request=request)
        user.is_superuser, user.is_staff = stored.is_superuser, stored.is_staff
        if request is not None and getattr(request, 'user', None) is not None and request.user.pk == user.pk:
            request.user.is_superuser, request.user.is_staff = stored.is_superuser, stored.is_staff
            clear_user_permission_cache(request.user, request)
    clear_user_permission_cache(user, request)
    return user


def sync_role_members(role, *, request=None):
    if role.role_code not in SUPERUSER_ROLE_CODES:
        return
    users = get_user_model().objects.filter(employee_profile__role_assignments__role_profile=role).distinct()
    for user in users:
        sync_role_superuser(user, request=request)


def superuser_plan():
    """预览启用后的身份变化；不写标志、不访问密码或会话字段。"""
    has_state_table = RoleSuperuserState._meta.db_table in connection.introspection.table_names()
    states = {state.user_id: state for state in RoleSuperuserState.objects.all()} if has_state_table else {}
    accounts = get_user_model().objects.filter(
        Q(employee_profile__role_assignments__role_profile__role_code__in=SUPERUSER_ROLE_CODES)
        | Q(pk__in=states),
    ).exclude(username='admin').only('pk', 'is_active', 'is_superuser', 'is_staff').distinct().order_by('pk')
    result = []
    for user in accounts:
        state = states.get(user.pk)
        eligible = eligible_for_superuser_role(user)
        before = {'is_superuser': user.is_superuser, 'is_staff': user.is_staff}
        after = ({'is_superuser': True, 'is_staff': True} if eligible else
                 {'is_superuser': state.original_is_superuser, 'is_staff': state.original_is_staff} if state else before)
        if before != after:
            result.append({'user_id': user.pk, 'before': before, 'after': after})
    return result
