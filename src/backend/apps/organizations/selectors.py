from django.db.models import Q
from django.db.models.functions import Now

from .models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment


def active_department_employees(department_code):
    """按当前有效归属查询部门员工，兼岗员工也包含在内。"""
    now = Now()
    assignments = EmployeeOrganizationAssignment.objects.filter(
        organization_unit__unit_code=department_code,
        organization_unit__status="ACTIVE",
        organization_unit__archived_at__isnull=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    return Employee.objects.filter(
        status="ACTIVE", archived_at__isnull=True,
        pk__in=assignments.values("employee_id"),
    )


def active_role_employees(role_code):
    """只返回当前持有指定有效角色的在职员工，不按姓名或部门推断角色。"""
    assignments = EmployeeRoleAssignment.objects.filter(
        role_profile__role_code=role_code, role_profile__archived_at__isnull=True,
        effective_from__lte=Now(),
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=Now()))
    return Employee.objects.filter(status="ACTIVE", archived_at__isnull=True,
                                   pk__in=assignments.values("employee_id"))


def employee_filter_choices(candidates, historical_ids):
    """列表筛选保留可见单据的历史人员，不扩大新增/转交时的候选范围。"""
    return Employee.objects.filter(Q(pk__in=candidates.values("pk")) | Q(pk__in=historical_ids)).order_by("employee_code", "pk")
