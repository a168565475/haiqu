from django.db.models import Count, Q

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
    return queryset.select_related("workshop", "created_by_employee", "updated_by_employee")


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
