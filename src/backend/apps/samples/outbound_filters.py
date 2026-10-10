from datetime import timedelta

import django_filters
from django.utils import timezone

from .models import SampleInventoryOutboundLine, SampleOutboundMethod


class SampleInventoryOutboundLineFilter(django_filters.FilterSet):
    outbound_method = django_filters.ChoiceFilter(choices=SampleOutboundMethod.choices)
    category_name = django_filters.CharFilter(
        field_name="inventory_line__category_name_snapshot",
        lookup_expr="iexact",
    )
    operated_period = django_filters.ChoiceFilter(
        choices=[
            ("TODAY", "今日"),
            ("THIS_MONTH", "本月"),
            ("LAST_30_DAYS", "近30天"),
        ],
        method="filter_operated_period",
    )

    class Meta:
        model = SampleInventoryOutboundLine
        fields = ["outbound_method", "category_name", "operated_period"]

    def filter_operated_period(self, queryset, name, value):
        today = timezone.localdate()
        if value == "TODAY":
            return queryset.filter(outbound__operated_at__date=today)
        if value == "THIS_MONTH":
            return queryset.filter(outbound__operated_at__date__gte=today.replace(day=1))
        if value == "LAST_30_DAYS":
            return queryset.filter(outbound__operated_at__date__gte=today - timedelta(days=29))
        return queryset
