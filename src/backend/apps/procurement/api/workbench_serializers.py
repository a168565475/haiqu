from datetime import date

from drf_spectacular.utils import PolymorphicProxySerializer, inline_serializer
from rest_framework import serializers

from ..tracking_rules import beijing_today
from ..workbench import ARRIVAL_CATEGORIES, COVERAGE_CATEGORIES
from .tracking_serializers import (
    ArrivalTrackingRowSerializer, CoverageTrackingRowSerializer, TrackingPaginationSerializer,
)


class WorkbenchFilterSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        for key in data:
            if key not in self.fields or hasattr(data, 'getlist') and len(data.getlist(key)) > 1:
                raise serializers.ValidationError({key: '不支持或重复的筛选参数。'})
        return super().to_internal_value(data)


class WorkbenchItemFilterSerializer(WorkbenchFilterSerializer):
    category = serializers.ChoiceField(choices=[*COVERAGE_CATEGORIES, *ARRIVAL_CATEGORIES])
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class WorkbenchSpendFilterSerializer(WorkbenchFilterSerializer):
    period = serializers.ChoiceField(choices=['month', 'quarter', 'year'], default='month')
    date = serializers.DateField(default=beijing_today)

    def validate_date(self, value):
        if value == date.max:
            raise serializers.ValidationError('超出可统计日期范围。')
        return value


class WorkbenchCoverageItemSerializer(CoverageTrackingRowSerializer):
    material_count = serializers.IntegerField(required=False)


class WorkbenchArrivalItemSerializer(ArrivalTrackingRowSerializer):
    material_inbound_date = serializers.DateField(allow_null=True)


class WorkbenchOverviewSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    availability_reasons = serializers.DictField(child=serializers.CharField())
    missing_use_date_count = serializers.IntegerField()
    as_of = serializers.DateField()


class WorkbenchSpendGroupSerializer(serializers.Serializer):
    amount = serializers.CharField()
    order_count = serializers.IntegerField()
    line_count = serializers.IntegerField()
    unpriced_count = serializers.IntegerField()


class WorkbenchSupplierSerializer(WorkbenchSpendGroupSerializer):
    supplier_id = serializers.UUIDField(allow_null=True)
    supplier_name = serializers.CharField()
    supplier_category = serializers.CharField()


class WorkbenchTrendSerializer(serializers.Serializer):
    month = serializers.IntegerField()
    amount = serializers.CharField()
    line_count = serializers.IntegerField()
    unpriced_count = serializers.IntegerField()


class WorkbenchCurrencySerializer(WorkbenchSpendGroupSerializer):
    currency = serializers.CharField(allow_blank=True)
    supplier_count = serializers.IntegerField()
    suppliers = WorkbenchSupplierSerializer(many=True)
    trend = WorkbenchTrendSerializer(many=True)


class WorkbenchSpendSerializer(serializers.Serializer):
    period = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    year = serializers.IntegerField()
    currencies = WorkbenchCurrencySerializer(many=True)
    unknown_date_count = serializers.IntegerField()


overview_response = inline_serializer('PurchaseWorkbenchOverview', {'data': WorkbenchOverviewSerializer()})
spend_response = inline_serializer('PurchaseWorkbenchSpend', {'data': WorkbenchSpendSerializer()})
items_response = inline_serializer('PurchaseWorkbenchItems', {
    'data': PolymorphicProxySerializer(component_name='PurchaseWorkbenchItem', resource_type_field_name=None,
        serializers=[WorkbenchCoverageItemSerializer, WorkbenchArrivalItemSerializer], many=True),
    'meta': TrackingPaginationSerializer(),
})
