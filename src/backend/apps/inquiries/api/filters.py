import django_filters

from ..models import Inquiry


class InquiryFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    transaction_entity_id = django_filters.UUIDFilter(field_name="transaction_entity_id")
    customer_contact_id = django_filters.UUIDFilter(field_name="customer_contact_id")
    owner_employee_id = django_filters.UUIDFilter(field_name="owner_employee_id")
    received_from = django_filters.IsoDateTimeFilter(field_name="received_at", lookup_expr="gte")
    received_to = django_filters.IsoDateTimeFilter(field_name="received_at", lookup_expr="lte")
    due_from = django_filters.IsoDateTimeFilter(field_name="requested_due_at", lookup_expr="gte")
    due_to = django_filters.IsoDateTimeFilter(field_name="requested_due_at", lookup_expr="lte")

    class Meta:
        model = Inquiry
        fields = ["status", "customer_id", "transaction_entity_id", "customer_contact_id", "owner_employee_id"]
