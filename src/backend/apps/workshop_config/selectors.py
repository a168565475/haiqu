from django.db.models import Count, Q

from apps.organizations.models import Employee
from apps.organizations.selectors import active_department_employees

from .models import RecordStatus


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
    return queryset.select_related("workshop")


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
