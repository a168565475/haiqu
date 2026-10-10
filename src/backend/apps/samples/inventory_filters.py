import django_filters

from .models import SampleInventoryLine

SAMPLE_INVENTORY_STATUS_CHOICES = (
    ("AVAILABLE", "有库存（>0）"),
    ("DEPLETED", "无库存（=0）"),
)


class SampleInventoryLineFilter(django_filters.FilterSet):
    category_name = django_filters.CharFilter(field_name="category_name_snapshot", lookup_expr="iexact")
    location = django_filters.CharFilter(field_name="location", lookup_expr="iexact")
    inventory_status = django_filters.ChoiceFilter(
        choices=SAMPLE_INVENTORY_STATUS_CHOICES,
        method="filter_inventory_status",
    )

    def filter_inventory_status(self, queryset, name, value):
        if value == "DEPLETED":
            return queryset.filter(available_quantity=0)
        return queryset.filter(available_quantity__gt=0)

    class Meta:
        model = SampleInventoryLine
        fields = ["category_name", "location"]
