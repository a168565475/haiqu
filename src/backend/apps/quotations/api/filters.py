import django_filters

from ..models import Quotation


class QuotationFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    transaction_entity_id = django_filters.UUIDFilter(field_name="transaction_entity_id")
    source_inquiry_id = django_filters.UUIDFilter(field_name="source_inquiry_id")
    owner_employee_id = django_filters.UUIDFilter(field_name="owner_employee_id")
    created_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Quotation
        fields = [
            "outcome_status",
            "customer_id",
            "transaction_entity_id",
            "source_inquiry_id",
            "owner_employee_id",
        ]
