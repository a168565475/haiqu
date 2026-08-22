import django_filters
from django.db.models import Q
from django.utils import timezone

from ..models import CustomerAccount


class CustomerFilter(django_filters.FilterSet):
    country_code = django_filters.CharFilter(field_name="primary_country_code")
    owner_id = django_filters.UUIDFilter(method="filter_owner")
    organization_id = django_filters.UUIDFilter(method="filter_organization")
    attention_level = django_filters.CharFilter(method="filter_attention")
    updated_from = django_filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="gte")
    updated_to = django_filters.IsoDateTimeFilter(field_name="updated_at", lookup_expr="lte")

    class Meta:
        model = CustomerAccount
        fields = [
            "lifecycle_stage",
            "country_code",
            "owner_id",
            "organization_id",
            "attention_level",
        ]

    def filter_owner(self, queryset, name, value):
        now = timezone.now()
        return queryset.filter(
            assignments__employee_id=value,
            assignments__effective_from__lte=now,
        ).filter(
            Q(assignments__effective_to__isnull=True) | Q(assignments__effective_to__gt=now)
        ).distinct()

    def filter_attention(self, queryset, name, value):
        now = timezone.now()
        return queryset.filter(
            attention_reviews__attention_level_item__item_code=value,
            attention_reviews__effective_from__lte=now,
        ).filter(
            Q(attention_reviews__effective_to__isnull=True)
            | Q(attention_reviews__effective_to__gt=now)
        ).distinct()

    def filter_organization(self, queryset, name, value):
        now = timezone.now()
        return queryset.filter(
            assignments__effective_from__lte=now,
            assignments__employee__organization_assignments__organization_unit_id=value,
            assignments__employee__organization_assignments__effective_from__lte=now,
        ).filter(
            Q(assignments__effective_to__isnull=True) | Q(assignments__effective_to__gt=now),
            Q(assignments__employee__organization_assignments__effective_to__isnull=True)
            | Q(assignments__employee__organization_assignments__effective_to__gt=now),
        ).distinct()
