import django_filters

from ..models import SampleRequest
from ..procurement_status import PROCUREMENT_IN_PROGRESS, ordered_sample_ids


class SampleRequestFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=[*SampleRequest._meta.get_field('status').choices, (PROCUREMENT_IN_PROGRESS, '采购中')],
        method='filter_status',
    )

    def filter_status(self, queryset, name, value):
        if value == PROCUREMENT_IN_PROGRESS:
            return queryset.filter(status='PROCUREMENT_PENDING', pk__in=ordered_sample_ids())
        if value == 'PROCUREMENT_PENDING':
            return queryset.filter(status=value).exclude(pk__in=ordered_sample_ids())
        return queryset.filter(status=value)

    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    owner_employee_id = django_filters.UUIDFilter(field_name="owner_employee_id")
    source_inquiry_id = django_filters.UUIDFilter(field_name="source_inquiry_id")
    source_quotation_version_id = django_filters.UUIDFilter(field_name="source_quotation_version_id")
    requested_from = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="gte")
    requested_to = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="lte")
    tracking_number = django_filters.CharFilter(field_name="shipments__tracking_number", lookup_expr="icontains")

    class Meta:
        model = SampleRequest
        fields = [
            "status",
            "sample_type",
            "customer_id",
            "owner_employee_id",
            "source_inquiry_id",
            "source_quotation_version_id",
        ]
