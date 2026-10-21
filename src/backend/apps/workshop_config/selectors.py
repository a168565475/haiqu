from django.db.models import Count, Q

from apps.organizations.models import Employee

from .models import RecordStatus, WorkshopEmployeeStatus


def workshops_with_statistics(queryset):
    return queryset.annotate(
        employee_count=Count("employees", distinct=True),
        active_employee_count=Count(
            "employees",
            filter=Q(employees__status=WorkshopEmployeeStatus.ACTIVE),
            distinct=True,
        ),
        active_supervisor_count=Count(
            "employees",
            filter=Q(
                employees__status=WorkshopEmployeeStatus.ACTIVE,
                employees__is_supervisor=True,
            ),
            distinct=True,
        ),
        craft_count=Count("crafts", distinct=True),
        active_craft_count=Count(
            "crafts",
            filter=Q(crafts__status=RecordStatus.ACTIVE),
            distinct=True,
        ),
        operation_count=Count("crafts__operations", distinct=True),
    )


def employees_with_context(queryset):
    return queryset.select_related("workshop", "employee", "created_by_employee", "updated_by_employee")


def active_employees(queryset):
    return queryset.filter(status=WorkshopEmployeeStatus.ACTIVE).filter(
        Q(employee__isnull=True) | Q(employee__status="ACTIVE", employee__archived_at__isnull=True),
    )


def locked_active_employees(queryset):
    """仅在事务内调用；按车间记录、统一员工顺序锁定并复查可参与生产的人员。"""
    rows = list(queryset.select_related(None).order_by("pk").select_for_update(of=("self",)))
    employees = {employee.pk: employee for employee in Employee.objects.select_for_update(no_key=True).filter(
        pk__in={row.employee_id for row in rows if row.employee_id},
    ).order_by("pk")}
    active = []
    for row in rows:
        if row.status != WorkshopEmployeeStatus.ACTIVE:
            continue
        if row.employee_id:
            employee = employees.get(row.employee_id)
            if employee is None or employee.status != "ACTIVE" or employee.archived_at is not None:
                continue
            row.employee = employee
        active.append(row)
    return active


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
