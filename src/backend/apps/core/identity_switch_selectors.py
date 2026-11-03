from django.conf import settings
from django.db.models import F, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from apps.organizations.models import (
    Employee, EmployeeStatus, EmployeeOrganizationAssignment, EmployeeRoleAssignment,
)


def is_switch_admin(user):
    """确认策略启用后，真正超级管理员共享身份切换能力。"""
    confirmed_policy = getattr(settings, 'CONFIRMED_ROLE_POLICY_ENABLED', False)
    if user and user.is_authenticated:
        from apps.access_control.superuser_services import sync_role_superuser
        sync_role_superuser(user)
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_superuser
        and (confirmed_policy or user.username == "admin")
    )


def switch_targets(query=""):
    """Return eligible employees; the view applies the 100-result limit."""
    employees = (
        Employee.objects.filter(
            user__isnull=False,
            user__is_active=True,
            user__is_superuser=False,
            user__is_staff=False,
            status=EmployeeStatus.ACTIVE,
            archived_at__isnull=True,
        )
        .exclude(user__username="admin")
        .select_related("user")
        .order_by("employee_code", "id")
    )
    query = query.strip()
    if query:
        employees = employees.filter(
            Q(employee_code__icontains=query)
            | Q(display_name__icontains=query)
            | Q(user__username__icontains=query)
        )
    return employees


def switch_target_list(query="", department_id=None, role_id=None):
    """Filter before limiting; show all current affiliations, including secondary posts."""
    now = timezone.now()
    current = Q(effective_to__isnull=True) | Q(effective_to__gt=now)
    departments = EmployeeOrganizationAssignment.objects.filter(
        current, effective_from__lte=now, organization_unit__status="ACTIVE",
        organization_unit__archived_at__isnull=True,
    )
    roles = EmployeeRoleAssignment.objects.filter(
        current, effective_from__lte=now, role_profile__archived_at__isnull=True,
    )
    eligible = switch_targets()
    # Choices use the complete eligible population, not the first 100 search results.
    department_choices = departments.filter(employee__in=eligible).order_by(
        "organization_unit__unit_name", "organization_unit_id",
    ).values_list("organization_unit_id", "organization_unit__unit_name").distinct()
    role_choices = roles.filter(employee__in=eligible).order_by(
        "role_profile__display_name", "role_profile_id",
    ).values_list("role_profile_id", "role_profile__display_name").distinct()
    candidates = switch_targets(query)
    if department_id:
        candidates = candidates.filter(pk__in=departments.filter(
            organization_unit_id=department_id,
        ).values("employee_id"))
    if role_id:
        candidates = candidates.filter(pk__in=roles.filter(
            role_profile_id=role_id,
        ).values("employee_id"))
    # 多部门/角色按当前展示的首项排序；先排序再截取，空归属排后，同组内顺序稳定。
    candidates = candidates.alias(
        switch_department_name=Subquery(departments.filter(employee_id=OuterRef("pk")).order_by(
            "organization_unit__unit_name", "organization_unit_id",
        ).values("organization_unit__unit_name")[:1]),
        switch_role_name=Subquery(roles.filter(employee_id=OuterRef("pk")).order_by(
            "role_profile__display_name", "role_profile_id",
        ).values("role_profile__display_name")[:1]),
    ).order_by(
        F("switch_department_name").asc(nulls_last=True),
        F("switch_role_name").asc(nulls_last=True), "display_name", "employee_code", "id",
    )
    candidates = list(candidates.prefetch_related(
        Prefetch("organization_assignments", queryset=departments.select_related(
            "organization_unit",
        ).order_by("organization_unit__unit_name", "organization_unit_id"), to_attr="switch_departments"),
        Prefetch("role_assignments", queryset=roles.select_related(
            "role_profile",
        ).order_by("role_profile__display_name", "role_profile_id"), to_attr="switch_roles"),
    )[:101])

    def choices(pairs):
        return [{"id": key, "name": name} for key, name in dict(pairs).items()]

    return {
        "results": [{
            "employee_id": employee.pk, "user_id": employee.user_id,
            "username": employee.user.get_username(), "employee_code": employee.employee_code,
            "display_name": employee.display_name,
            "departments": choices((item.organization_unit_id, item.organization_unit.unit_name)
                                   for item in employee.switch_departments),
            "roles": choices((item.role_profile_id, item.role_profile.display_name)
                             for item in employee.switch_roles),
        } for employee in candidates[:100]],
        "departments": choices(department_choices), "roles": choices(role_choices),
        "has_more": len(candidates) > 100,
    }
