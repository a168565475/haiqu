import django_filters

from ..models import CustomerCommunication


class CommunicationFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    created_by_id = django_filters.UUIDFilter(field_name="created_by_employee_id")
    occurred_from = django_filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="gte")
    occurred_to = django_filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="lte")

    class Meta:
        model = CustomerCommunication
        fields = ["customer_id", "created_by_id", "communication_type", "direction"]

