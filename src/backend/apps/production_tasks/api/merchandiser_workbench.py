from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.access_control.module_policy import has_permission
from apps.access_control.sales_policy import access_for
from apps.core.api.permissions import HasActiveEmployee
from .. import merchandiser_workbench as workbench
from ..models import ProductionTask


class MerchandiserPermission(BasePermission):
    message = '当前岗位没有跟单工作台查看权限。'

    def has_permission(self, request, view):
        if not has_permission(request, workbench.TASK_PERMISSION):
            return False
        access = access_for(request)
        return access['is_superuser'] or any(role['code'] == 'MERCHANDISER' for role in access['roles'])


class WorkbenchQuery(serializers.Serializer):
    def to_internal_value(self, data):
        for key in data:
            if key not in self.fields or (hasattr(data, 'getlist') and len(data.getlist(key)) > 1):
                raise serializers.ValidationError({key: '筛选项不支持或被重复指定。'})
        return super().to_internal_value(data)


PERIODS = ('month', 'quarter', 'year')
PERIOD_ITEMS = ('period_tasks', 'period_purchases', 'supplier')


class ActivityQuery(WorkbenchQuery):
    period = serializers.ChoiceField(choices=PERIODS, default='month')


class ItemsQuery(WorkbenchQuery):
    category = serializers.ChoiceField(choices=['need', 'soon', 'late', 'returns', 'ordinary',
                                               *workbench.PRINT_CATEGORIES, *workbench.TASK_CATEGORIES,
                                               'period_purchases', 'supplier'])
    date = serializers.DateField(required=False)
    period = serializers.ChoiceField(choices=PERIODS, required=False)
    supplier_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, max_value=2147483647, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)

    def validate(self, attrs):
        key = attrs['category']
        if (key == 'day') != ('date' in attrs):
            raise serializers.ValidationError({'date': '按交期查看时需要选择日期。'})
        if key == 'day' and not self.context['today'] <= attrs['date'] <= self.context['today'] + timedelta(days=6):
            raise serializers.ValidationError({'date': '请选择含今天在内的七天之一。'})
        if (key == 'supplier') != ('supplier_id' in attrs):
            raise serializers.ValidationError({'supplier_id': '仅供应商采购明细需要选择供应商。'})
        if key not in PERIOD_ITEMS and 'period' in attrs:
            raise serializers.ValidationError({'period': '日常待办按当前状态查看。'})
        return attrs


class DayCount(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()


class MerchandiserOverview(serializers.Serializer):
    as_of = serializers.DateField()
    counts = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    upcoming = DayCount(many=True)


class Amount(serializers.Serializer):
    currency = serializers.CharField()
    amount = serializers.CharField()


class Supplier(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    order_count = serializers.IntegerField()
    amounts = Amount(many=True)
    unpriced_count = serializers.IntegerField()


class MerchandiserActivity(serializers.Serializer):
    as_of = serializers.DateField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    task_count = serializers.IntegerField()
    purchase_order_count = serializers.IntegerField(allow_null=True)
    supplier_count = serializers.IntegerField(allow_null=True)
    amounts = Amount(many=True)
    suppliers = Supplier(many=True)
    unpriced_count = serializers.IntegerField()
    undated_count = serializers.IntegerField()
    unknown_supplier_count = serializers.IntegerField()


class WorkbenchColumn(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class WorkbenchRow(serializers.Serializer):
    task_id = serializers.UUIDField()
    task_number = serializers.CharField()
    cells = serializers.DictField(child=serializers.CharField())


class WorkbenchTable(serializers.Serializer):
    columns = WorkbenchColumn(many=True)
    rows = WorkbenchRow(many=True)


@extend_schema_serializer(many=False)
class MerchandiserOverviewResponse(serializers.Serializer):
    data = MerchandiserOverview()


class MerchandiserActivityResponse(serializers.Serializer):
    data = MerchandiserActivity()


class MerchandiserItemsResponse(serializers.Serializer):
    data = WorkbenchTable()
    meta = serializers.DictField(child=serializers.IntegerField())


class MerchandiserWorkbenchViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, MerchandiserPermission]
    queryset = ProductionTask.objects.none()
    pagination_class = None
    serializer_class = MerchandiserOverviewResponse

    def filters(self, cls, today):
        query = cls(data=self.request.query_params, context={'today': today})
        query.is_valid(raise_exception=True)
        return query.validated_data

    @extend_schema(responses=MerchandiserOverviewResponse)
    def list(self, request):
        today = timezone.localdate()
        self.filters(WorkbenchQuery, today)
        return Response({'data': workbench.overview(request, today)})

    @extend_schema(parameters=[ActivityQuery], responses=MerchandiserActivityResponse)
    @action(detail=False, methods=['get'])
    def activity(self, request):
        today = timezone.localdate()
        query = self.filters(ActivityQuery, today)
        return Response({'data': workbench.activity(request, today, query['period'])})

    @extend_schema(parameters=[ItemsQuery], responses=MerchandiserItemsResponse)
    @action(detail=False, methods=['get'])
    def items(self, request):
        today = timezone.localdate()
        return Response(workbench.items(request, today, self.filters(ItemsQuery, today)))
