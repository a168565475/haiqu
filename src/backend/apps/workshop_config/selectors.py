from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import resource_ids
from apps.access_control.sales_policy import access_for
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment
from apps.organizations.selectors import active_department_employees

from .models import RecordStatus, Workshop


# 员工角色中的车间名称是岗位归属来源；“缝纫车间”是历史角色名，对应固定的“车缝车间”。
ROLE_WORKSHOP_NAMES = {
    "金工车间": "金工车间",
    "缝纫车间": "车缝车间",
    "装配车间": "装配车间",
}


def employee_workshop_ids(request, permission):
    """None 表示全模块；空集合表示没有当前动作的员工配置权限。"""
    if request is None or not access_for(request)["active"] or not has_permission(request, permission):
        return set()
    return resource_ids(request, permission, "WORKSHOP")


def accessible_workshop_employees(request, permission="workshop_config.view_workshopemployee"):
    queryset = active_department_employees("DEPT_PRODUCTION")
    ids = employee_workshop_ids(request, permission)
    return queryset if ids is None else queryset.filter(workshop_id__in=ids)


def accessible_role_workshop_employees(request, permission="workshop_config.view_workshopemployee", workshop_ids=None):
    """返回角色能明确对应到授权车间的生产部员工，包括尚未写入车间的员工。"""
    queryset = active_department_employees("DEPT_PRODUCTION")
    allowed_ids = employee_workshop_ids(request, permission)
    target_workshops = Workshop.objects.filter(name__in=ROLE_WORKSHOP_NAMES.values())
    if allowed_ids is not None:
        target_workshops = target_workshops.filter(pk__in=allowed_ids)
    if workshop_ids:
        target_workshops = target_workshops.filter(pk__in=workshop_ids)
    targets = dict(target_workshops.values_list("name", "pk"))
    now = timezone.now()
    mapped_roles = EmployeeRoleAssignment.objects.filter(
        role_profile__display_name__in=ROLE_WORKSHOP_NAMES.keys(),
        role_profile__archived_at__isnull=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    # 先独立检查全部有效映射，避免授权或车间筛选把另一个冲突角色隐藏。
    unique_role_employees = mapped_roles.values("employee_id").annotate(
        workshop_count=Count("role_profile__display_name", distinct=True),
    ).filter(workshop_count=1).values("employee_id")
    role_query = Q()
    for role_name, workshop_name in ROLE_WORKSHOP_NAMES.items():
        workshop_id = targets.get(workshop_name)
        if not workshop_id:
            continue
        role_employees = mapped_roles.filter(role_profile__display_name=role_name).values("employee_id")
        role_query |= Q(pk__in=role_employees) & (Q(workshop__isnull=True) | Q(workshop_id=workshop_id))
    if not role_query:
        return queryset.none()
    return queryset.filter(pk__in=unique_role_employees).filter(role_query)


def employee_role_workshop_name(employee):
    """只依据当前有效角色返回唯一车间名称，不猜测未知角色。"""
    rows = getattr(employee, "_workshop_roles", None)
    if rows is None:
        now = timezone.now()
        role_names = set(EmployeeRoleAssignment.objects.filter(
            employee=employee,
            effective_from__lte=now,
            role_profile__archived_at__isnull=True,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).values_list(
            "role_profile__display_name", flat=True,
        ))
    else:
        role_names = {row.role_profile.display_name for row in rows}
    workshop_names = {ROLE_WORKSHOP_NAMES[name] for name in role_names if name in ROLE_WORKSHOP_NAMES}
    return next(iter(workshop_names)) if len(workshop_names) == 1 else None


def employee_role_workshop(employee):
    """返回员工唯一明确的角色车间；多车间或无对应角色时返回 None。"""
    name = employee_role_workshop_name(employee)
    return Workshop.objects.filter(name=name).first() if name else None


def workshops_with_statistics(queryset):
    eligible = active_department_employees("DEPT_PRODUCTION").values("pk")
    return queryset.annotate(
        employee_count=Count("production_employees", filter=Q(production_employees__in=eligible), distinct=True),
        active_employee_count=Count("production_employees", filter=Q(
            production_employees__in=eligible, production_employees__workshop_status="ACTIVE"), distinct=True),
        active_supervisor_count=Count("production_employees", filter=Q(
            production_employees__in=eligible, production_employees__workshop_status="ACTIVE",
            production_employees__workshop_is_supervisor=True), distinct=True),
        craft_count=Count("crafts", distinct=True),
        active_craft_count=Count("crafts", filter=Q(crafts__status=RecordStatus.ACTIVE), distinct=True),
        operation_count=Count("crafts__operations", distinct=True),
    )


def employees_with_context(queryset):
    now = timezone.now()
    departments = EmployeeOrganizationAssignment.objects.filter(
        effective_from__lte=now,
        organization_unit__archived_at__isnull=True,
        organization_unit__status="ACTIVE",
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).select_related("organization_unit").order_by(
        "-is_primary", "organization_unit__unit_name", "id",
    )
    roles = EmployeeRoleAssignment.objects.filter(
        effective_from__lte=now,
        role_profile__archived_at__isnull=True,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).select_related("role_profile").order_by(
        "role_profile__display_name", "id",
    )
    return queryset.select_related("workshop").prefetch_related(
        Prefetch("organization_assignments", queryset=departments, to_attr="_workshop_departments"),
        Prefetch("role_assignments", queryset=roles, to_attr="_workshop_roles"),
    )


def active_employees(queryset):
    return queryset.filter(
        pk__in=active_department_employees("DEPT_PRODUCTION").values("pk"),
        workshop_status="ACTIVE", workshop__status=RecordStatus.ACTIVE,
    ).exclude(workshop_position="")


def locked_active_employees(queryset):
    """锁定统一员工，再复查部门、车间和任职状态。"""
    rows = list(queryset.select_related(None).order_by("pk").select_for_update(of=("self",)))
    eligible_ids = set(active_employees(Employee.objects.filter(pk__in=[row.pk for row in rows])).values_list("pk", flat=True))
    return [row for row in rows if row.pk in eligible_ids]


def crafts_with_context(queryset):
    return queryset.select_related("workshop", "created_by_employee", "updated_by_employee").annotate(
        operation_count=Count("operations", distinct=True),
        active_operation_count=Count(
            "operations",
            filter=Q(operations__status=RecordStatus.ACTIVE),
            distinct=True,
        ),
    )


def operations_with_context(queryset):
    return queryset.select_related(
        "craft",
        "craft__workshop",
        "reporting_unit",
        "created_by_employee",
        "updated_by_employee",
    )
