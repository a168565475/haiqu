import django_filters
from django.utils import timezone

from ..models import BusinessTask


class TaskFilter(django_filters.FilterSet):
    assignee_id = django_filters.UUIDFilter(field_name="assignee_employee_id")
    due_from = django_filters.IsoDateTimeFilter(field_name="due_at", lookup_expr="gte")
    due_to = django_filters.IsoDateTimeFilter(field_name="due_at", lookup_expr="lte")
    overdue = django_filters.BooleanFilter(method="filter_overdue")

    class Meta:
        model = BusinessTask
        fields = ["status", "priority", "assignee_id", "overdue"]

    def filter_overdue(self, queryset, name, value):
        if value:
            return queryset.filter(
                status__in=["PENDING", "IN_PROGRESS"],
                due_at__lt=timezone.now(),
            )
        return queryset

