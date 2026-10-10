from django.db.models import Q
from django.utils import timezone
import django_filters

from ..models import Quotation


class QuotationFilter(django_filters.FilterSet):
    customer_id = django_filters.UUIDFilter(field_name="customer_account_id")
    transaction_entity_id = django_filters.UUIDFilter(field_name="transaction_entity_id")
    source_inquiry_id = django_filters.UUIDFilter(field_name="source_inquiry_id")
    owner_employee_id = django_filters.UUIDFilter(field_name="owner_employee_id")
    created_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    currency_code = django_filters.CharFilter(field_name="latest_version_currency", lookup_expr="iexact")
    valid_from = django_filters.DateFilter(field_name="latest_version_valid_until", lookup_expr="gte")
    valid_to = django_filters.DateFilter(field_name="latest_version_valid_until", lookup_expr="lte")
    display_status = django_filters.CharFilter(method="filter_display_status")

    def filter_display_status(self, queryset, _name, value):
        today = timezone.localdate()
        version_status = {
            "DRAFT": "DRAFT",
            "LOCKED": "LOCKED",
            "READY_TO_SEND": "ISSUED",
            "SENT": "SENT",
            "SUPERSEDED": "SUPERSEDED",
        }
        if value == "ACCEPTED":
            return queryset.filter(outcome_status="WON")
        if value == "REJECTED":
            return queryset.filter(outcome_status="LOST")
        if value == "WITHDRAWN":
            return queryset.filter(Q(outcome_status="CANCELLED") | Q(latest_version_status="VOID"))
        if value == "EXPIRED":
            return queryset.filter(
                outcome_status="OPEN",
                latest_version_valid_until__lt=today,
            ).exclude(latest_version_status="VOID")
        if value in version_status:
            return queryset.filter(outcome_status="OPEN", latest_version_status=version_status[value])
        return queryset.none()

    class Meta:
        model = Quotation
        fields = [
            "outcome_status",
            "customer_id",
            "transaction_entity_id",
            "source_inquiry_id",
            "owner_employee_id",
            "currency_code",
            "valid_from",
            "valid_to",
            "display_status",
        ]
