import django_filters

from ..models import SampleRequest


class SampleRequestFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    owner_employee_id = django_filters.UUIDFilter(field_name="owner_employee_id")
    source_inquiry_id = django_filters.UUIDFilter(field_name="source_inquiry_id")
    source_quotation_version_id = django_filters.UUIDFilter(field_name="source_quotation_version_id")
    requested_from = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="gte")
    requested_to = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="lte")

    class Meta:
        model = SampleRequest
        fields = [
            "status",
            "customer_id",
            "owner_employee_id",
            "source_inquiry_id",
            "source_quotation_version_id",
        ]
