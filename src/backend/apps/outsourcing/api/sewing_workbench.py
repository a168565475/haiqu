from math import ceil

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_serializer, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import has_legacy_permission
from apps.access_control.sales_policy import access_for
from apps.core.api.permissions import HasActiveEmployee
from .. import sewing_workbench as workbench
from ..models import TubeOutsourcingOrder
from ..tube_selectors import VIEW_PERMISSION, require_tube_feature


class SewingWorkbenchPermission(BasePermission):
    message = '当前岗位没有车缝外协工作台的查看权限。'

    def has_permission(self, request, view):
        if not has_permission(request, VIEW_PERMISSION):
            return False
        access = access_for(request)
        scopes = access['actions'].get(VIEW_PERMISSION, {}).get('scopes', [])
        return (access['is_superuser'] or set(scopes) != {'FOLLOWED'}
                or has_legacy_permission(request, VIEW_PERMISSION))


class SewingQuery(serializers.Serializer):
    def to_internal_value(self, data):
        for key in data:
            if key not in self.fields or (hasattr(data, 'getlist') and len(data.getlist(key)) > 1):
                raise serializers.ValidationError({key: '筛选项不支持或被重复指定。'})
        return super().to_internal_value(data)


class SewingItemsQuery(SewingQuery):
    category = serializers.ChoiceField(choices=[*workbench.SEND, *workbench.RETURN])
    date = serializers.DateField(required=False)
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=100)

    def validate(self, attrs):
        if 'date' in attrs and attrs['category'] != 'upcoming':
            raise serializers.ValidationError({'date': '仅未来七天应回明细支持按天筛选。'})
        return attrs


class SewingActivityQuery(SewingQuery):
    period = serializers.ChoiceField(choices=['month', 'quarter', 'year'], default='month')


class SewingDayCount(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()


class SewingOverview(serializers.Serializer):
    as_of = serializers.DateField()
    counts = serializers.DictField(child=serializers.IntegerField())
    upcoming = SewingDayCount(many=True)


@extend_schema_serializer(many=False)
class SewingWorkbenchOverviewResponse(serializers.Serializer):
    data = SewingOverview()


class SewingWorkItem(serializers.Serializer):
    name = serializers.CharField()
    factory_name = serializers.CharField()
    unit = serializers.CharField()
    target = serializers.CharField()
    actual = serializers.CharField()
    remaining = serializers.CharField()


class SewingOrderItem(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    task_number = serializers.CharField()
    product_name = serializers.CharField()
    is_plan = serializers.BooleanField()
    planned_dispatch_date = serializers.DateField()
    expected_return_date = serializers.DateField()
    last_dispatch_date = serializers.DateField(allow_null=True)
    last_receipt_date = serializers.DateField(allow_null=True)
    factories = serializers.ListField(child=serializers.CharField())
    materials = SewingWorkItem(many=True)
    parts = SewingWorkItem(many=True)


class SewingQuantity(serializers.Serializer):
    unit = serializers.CharField()
    quantity = serializers.CharField()


class SewingFactoryActivity(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    order_count = serializers.IntegerField()
    quantities = SewingQuantity(many=True)


class SewingActivity(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    dispatch_orders = serializers.IntegerField()
    dispatch_factories = serializers.IntegerField()
    receipt_orders = serializers.IntegerField()
    receipt_factories = serializers.IntegerField()
    receipt_events = serializers.IntegerField()
    quantities = SewingQuantity(many=True)
    factories = SewingFactoryActivity(many=True)


class SewingWorkbenchViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, SewingWorkbenchPermission]
    queryset = TubeOutsourcingOrder.objects.none()
    pagination_class = None
    serializer_class = SewingOverview

    def filters(self, serializer_class):
        require_tube_feature()
        serializer = serializer_class(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @extend_schema(responses=SewingWorkbenchOverviewResponse)
    def list(self, request):
        self.filters(SewingQuery)
        return Response({'data': workbench.overview(request, timezone.localdate())})

    @extend_schema(parameters=[SewingItemsQuery],
        responses=inline_serializer('SewingWorkbenchItemsResponse', {'data': SewingOrderItem(many=True),
            'meta': serializers.DictField(child=serializers.IntegerField())}))
    @action(detail=False, methods=['get'])
    def items(self, request):
        filters = self.filters(SewingItemsQuery)
        rows = workbench.workbench_items(request, timezone.localdate(), filters['category'], filters.get('date'))
        page, size = filters['page'], filters['page_size']
        return Response({'data': SewingOrderItem(rows[(page-1)*size:page*size], many=True).data,
                         'meta': {'total': len(rows), 'page': page, 'page_size': size, 'total_pages': ceil(len(rows)/size)}})

    @extend_schema(parameters=[SewingActivityQuery],
        responses=inline_serializer('SewingWorkbenchActivityResponse', {'data': SewingActivity()}))
    @action(detail=False, methods=['get'])
    def activity(self, request):
        filters = self.filters(SewingActivityQuery)
        return Response({'data': workbench.activity(request, timezone.localdate(), filters['period'])})
