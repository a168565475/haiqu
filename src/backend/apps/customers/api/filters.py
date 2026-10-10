import django_filters
from django.db.models import Q
from django.utils import timezone

from ..models import CustomerAccount


class CustomerFilter(django_filters.FilterSet):
    country_code = django_filters.CharFilter(field_name="primary_country_code")
    owner_id = django_filters.UUIDFilter(method="filter_owner")
    organization_id = django_filters.UUIDFilter(method="filter_organization")
    attention_level = django_filters.CharFilter(method="filter_attention")
    customer_grade = django_filters.CharFilter(method="filter_grade")
    customer_source = django_filters.CharFilter(method="filter_source")
    customer_type = django_filters.CharFilter(method="filter_customer_type")
    customer_tag = django_filters.CharFilter(method="filter_customer_tag")
    activity_status = django_filters.CharFilter(method="filter_activity")
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
            "customer_grade",
            "customer_source",
            "customer_type",
            "customer_tag",
            "activity_status",
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

    def filter_grade(self, queryset, name, value):
        return self._filter_effective_dictionary_relation(
            queryset,
            relation="grade_reviews",
            item_field="grade_item",
            value=value,
        )

    def filter_source(self, queryset, name, value):
        return self._filter_effective_dictionary_relation(
            queryset,
            relation="source_attributions",
            item_field="source_item",
            value=value,
        )

    def filter_customer_type(self, queryset, name, value):
        return self._filter_effective_dictionary_relation(
            queryset,
            relation="type_assignments",
            item_field="type_item",
            value=value,
        )

    def filter_customer_tag(self, queryset, name, value):
        now = timezone.now()
        return queryset.filter(
            tag_assignments__customer_tag__tag_code=value,
            tag_assignments__effective_from__lte=now,
        ).filter(
            Q(tag_assignments__effective_to__isnull=True) | Q(tag_assignments__effective_to__gt=now)
        ).distinct()

    def filter_activity(self, queryset, name, value):
        now = timezone.now()
        return queryset.filter(
            activity_reviews__activity_status=value,
            activity_reviews__effective_from__lte=now,
        ).filter(
            Q(activity_reviews__effective_to__isnull=True) | Q(activity_reviews__effective_to__gt=now)
        ).distinct()

    @staticmethod
    def _filter_effective_dictionary_relation(queryset, *, relation, item_field, value):
        now = timezone.now()
        filters = {
            f"{relation}__{item_field}__item_code": value,
            f"{relation}__effective_from__lte": now,
        }
        return queryset.filter(**filters).filter(
            Q(**{f"{relation}__effective_to__isnull": True})
            | Q(**{f"{relation}__effective_to__gt": now})
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
