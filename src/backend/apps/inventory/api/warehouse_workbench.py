from heapq import merge
from itertools import islice

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from apps.access_control.sales_policy import access_for
from apps.core.api.permissions import HasActiveEmployee
from apps.procurement.workbench import period_start
from apps.production_tasks.api.merchandiser_workbench import PERIODS, WorkbenchQuery
from .. import warehouse_workbench_internal as internal
from .. import warehouse_workbench_external as external
from ..models import Warehouse


SOURCES = {
    'inbound': internal, 'purchase': internal, 'issue': internal,
    'dispatch': external, 'returns': external,
}


class WarehouseWorkbenchAccess(BasePermission):
    message = '当前岗位没有仓库工作台查看权限。'

    def has_permission(self, request, view):
        access = access_for(request)
        return access['is_superuser'] or any(role['code'] == 'WAREHOUSE_KEEPER' for role in access['roles'])


class PageQuery(WorkbenchQuery):
    page = serializers.IntegerField(min_value=1, max_value=2147483647, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class WarehouseItemsQuery(PageQuery):
    queue = serializers.ChoiceField(choices=list(SOURCES))
    task_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if 'task_id' in attrs and attrs['queue'] != 'issue':
            raise serializers.ValidationError({'task_id': '仅生产任务待发料支持按任务展开。'})
        return attrs


class WarehouseDetailQuery(WorkbenchQuery):
    queue = serializers.ChoiceField(choices=list(SOURCES))
    kind = serializers.CharField(max_length=40)
    id = serializers.UUIDField()


class WarehouseActivityQuery(PageQuery):
    period = serializers.ChoiceField(choices=PERIODS, default='month')
    queue = serializers.ChoiceField(choices=['all', *SOURCES], default='all')
    summary = serializers.BooleanField(default=False)


class WarehouseQueueRow(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    task_number = serializers.CharField()
    product = serializers.CharField()
    number = serializers.CharField()
    party = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    status = serializers.CharField()
    document_count = serializers.IntegerField(required=False)


class WarehousePriorityRow(WarehouseQueueRow):
    queue = serializers.ChoiceField(choices=list(SOURCES))


class WarehouseCard(serializers.Serializer):
    available = serializers.BooleanField()
    count = serializers.IntegerField(allow_null=True)
    breakdown = serializers.DictField(child=serializers.IntegerField())
    preview = WarehouseQueueRow(allow_null=True)


class WarehouseOverview(serializers.Serializer):
    as_of = serializers.DateField()
    queues = serializers.DictField(child=WarehouseCard())
    priority = WarehousePriorityRow(many=True)


class WarehouseLine(serializers.Serializer):
    name = serializers.CharField()
    unit = serializers.CharField()
    party = serializers.CharField(required=False)
    date = serializers.DateField(required=False, allow_null=True)
    basis_label = serializers.CharField(required=False)
    required = serializers.CharField(allow_null=True)
    done = serializers.CharField(allow_null=True)
    remaining = serializers.CharField(allow_null=True)


class WarehouseMovement(serializers.Serializer):
    date = serializers.DateField(allow_null=True)
    action = serializers.CharField()
    number = serializers.CharField()
    description = serializers.CharField()


class WarehouseDocument(serializers.Serializer):
    row = WarehouseQueueRow()
    lines = WarehouseLine(many=True)
    movements = WarehouseMovement(many=True)
    related = WarehouseDetailQuery(allow_null=True)


class WarehouseActivityRow(serializers.Serializer):
    queue = serializers.ChoiceField(choices=list(SOURCES))
    id = serializers.CharField()
    kind = serializers.CharField()
    task_number = serializers.CharField()
    number = serializers.CharField()
    party = serializers.CharField()
    date = serializers.DateField()
    description = serializers.CharField()


class WarehouseActivity(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    counts = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    records = WarehouseActivityRow(many=True)


@extend_schema_serializer(many=False)
class WarehouseOverviewResponse(serializers.Serializer):
    data = WarehouseOverview()


class WarehousePageMeta(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class WarehouseItemsResponse(serializers.Serializer):
    data = WarehouseQueueRow(many=True)
    meta = WarehousePageMeta()


class WarehouseDetailResponse(serializers.Serializer):
    data = WarehouseDocument()


class WarehouseActivityResponse(serializers.Serializer):
    data = WarehouseActivity()
    meta = WarehousePageMeta()


def page_meta(total, params):
    size = params['page_size']
    return {'total': total, 'page': params['page'], 'page_size': size, 'total_pages': (total + size - 1) // size}


def activity_batches(request, key, start, end, total, size):
    for offset in range(0, total, size):
        _, rows = SOURCES[key].activity(request, key, start, end, size, offset)
        for row in rows:
            yield {'queue': key, **row}
        if len(rows) < size:
            break


class WarehouseWorkbenchViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, WarehouseWorkbenchAccess]
    serializer_class = WarehouseOverviewResponse
    queryset = Warehouse.objects.none()
    pagination_class = None

    def params(self, serializer):
        query = serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data

    @extend_schema(responses=WarehouseOverviewResponse)
    def list(self, request):
        self.params(WorkbenchQuery)
        today = timezone.localdate()
        cards, priority = {}, []
        for key, source in SOURCES.items():
            card = source.overview(request, key, today)
            priority.extend({'queue': key, **row} for row in card.pop('priority') if row['date'])
            cards[key] = card
        priority.sort(key=lambda row: (str(row['date']), row['number'], row['queue'], str(row['id'])))
        return Response({'data': {'as_of': today, 'queues': cards, 'priority': priority[:4]}})

    @extend_schema(parameters=[WarehouseItemsQuery], responses=WarehouseItemsResponse)
    @action(detail=False, methods=['get'])
    def items(self, request):
        params = self.params(WarehouseItemsQuery)
        key = params['queue']
        total, rows = SOURCES[key].items(request, key, params)
        return Response({'data': rows, 'meta': page_meta(total, params)})

    @extend_schema(parameters=[WarehouseDetailQuery], responses=WarehouseDetailResponse)
    @action(detail=False, methods=['get'], url_path='detail')
    def document(self, request):
        params = self.params(WarehouseDetailQuery)
        key = params['queue']
        return Response({'data': SOURCES[key].detail(request, key, params['kind'], params['id'])})

    @extend_schema(parameters=[WarehouseActivityQuery], responses=WarehouseActivityResponse)
    @action(detail=False, methods=['get'])
    def activity(self, request):
        params = self.params(WarehouseActivityQuery)
        end = timezone.localdate()
        start = period_start(params['period'], end)
        key, size = params['queue'], params['page_size']
        offset = (params['page'] - 1) * size
        counts = {k: source.activity(request, k, start, end, 0, 0)[0] for k, source in SOURCES.items()}
        if key != 'all' and counts[key] is None:
            raise PermissionDenied('当前账号无权查看该类仓库收发记录。')
        total = sum(n for n in counts.values() if n is not None) if key == 'all' else counts[key]
        rows = []
        if not params['summary'] and offset < total:
            if key == 'all':
                streams = (activity_batches(request, k, start, end, n, size) for k, n in counts.items() if n)
                merged = merge(*streams, key=lambda row: str(row['date']), reverse=True)
                rows = list(islice(merged, offset, offset + size))
            else:
                _, entries = SOURCES[key].activity(request, key, start, end, size, offset)
                rows = [{'queue': key, **entry} for entry in entries]
        data = {'counts': counts, 'start_date': start, 'end_date': end, 'records': rows}
        return Response({'data': data, 'meta': page_meta(total, params)})
