from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.api.permissions import HasActiveEmployee
from apps.production_scheduling.models import ProductionScheduleProductCraft
from ..director_workbench import CATEGORY_GROUPS, DirectorWorkbench, page_of
from .merchandiser_workbench import DayCount, PERIODS, WorkbenchQuery


class WorkshopQuery(WorkbenchQuery):
    workshop = serializers.ChoiceField(choices=list(CATEGORY_GROUPS), required=False)


class PageQuery(WorkshopQuery):
    page = serializers.IntegerField(min_value=1, max_value=2147483647, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class DirectorItemsQuery(PageQuery):
    category = serializers.ChoiceField(choices=("working", "late", "today", "planned", "day", "week"))
    date = serializers.DateField(required=False)

    def validate(self, attrs):
        if (attrs["category"] == "day") != ("date" in attrs):
            raise serializers.ValidationError({"date": "仅按日查看时需要指定日期。"})
        today = self.context["today"]
        if "date" in attrs and not today <= attrs["date"] <= today + timedelta(days=6):
            raise serializers.ValidationError({"date": "请选择含今天在内的七天之一。"})
        return attrs


class DirectorDetailQuery(WorkshopQuery):
    id = serializers.UUIDField()


class DirectorActivityQuery(PageQuery):
    period = serializers.ChoiceField(choices=PERIODS, default="month")


class DirectorQuantity(serializers.Serializer):
    target = serializers.CharField(allow_null=True)
    done = serializers.CharField(allow_null=True)
    remaining = serializers.CharField(allow_null=True)
    unit = serializers.CharField()
    reason = serializers.CharField()


class DirectorOperation(DirectorQuantity):
    name = serializers.CharField()


class DirectorJob(serializers.Serializer):
    id = serializers.UUIDField()
    task_id = serializers.UUIDField()
    task_number = serializers.CharField()
    schedule_number = serializers.CharField()
    product_name = serializers.CharField()
    craft_name = serializers.CharField()
    category = serializers.CharField()
    stage = serializers.ChoiceField(choices=("working", "planned", "completed", "unknown"))
    due_date = serializers.DateField()
    days_remaining = serializers.IntegerField()
    latest_date = serializers.DateField(allow_null=True)
    latest_operation = serializers.CharField()
    quantity = DirectorQuantity()


class DirectorRecord(serializers.Serializer):
    id = serializers.UUIDField()
    date = serializers.DateField()
    number = serializers.CharField()
    task_number = serializers.CharField()
    product_name = serializers.CharField()
    name = serializers.CharField()
    quantity = serializers.CharField()
    unit = serializers.CharField()
    job_id = serializers.UUIDField(allow_null=True)


class DirectorOverview(serializers.Serializer):
    as_of = serializers.DateField()
    workshop = serializers.CharField()
    workshops = serializers.ListField(child=serializers.CharField())
    counts = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    upcoming = DayCount(many=True)
    jobs = DirectorJob(many=True)


class DirectorDetail(serializers.Serializer):
    job = DirectorJob()
    operations = DirectorOperation(many=True)
    reports = DirectorRecord(many=True, allow_null=True)
    receipts = DirectorRecord(many=True, allow_null=True)


class DirectorUnitTotal(serializers.Serializer):
    unit = serializers.CharField()
    quantity = serializers.CharField()


class DirectorActivity(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    task_count = serializers.IntegerField()
    record_count = serializers.IntegerField()
    day_count = serializers.IntegerField()
    quantities = DirectorUnitTotal(many=True)
    records = DirectorRecord(many=True)
    available = serializers.BooleanField()


@extend_schema_serializer(many=False)
class DirectorOverviewResponse(serializers.Serializer):
    data = DirectorOverview()


class DirectorItemsResponse(serializers.Serializer):
    data = DirectorJob(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class DirectorDetailResponse(serializers.Serializer):
    data = DirectorDetail()


class DirectorActivityResponse(serializers.Serializer):
    data = DirectorActivity()
    meta = serializers.DictField(child=serializers.IntegerField())


class WorkshopDirectorWorkbenchViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee]
    pagination_class = None
    serializer_class = DirectorOverviewResponse
    queryset = ProductionScheduleProductCraft.objects.none()

    def workbench(self, serializer):
        today = timezone.localdate()
        query = serializer(data=self.request.query_params, context={"today": today})
        query.is_valid(raise_exception=True)
        params = query.validated_data
        return DirectorWorkbench(self.request, params.get("workshop"), today), params

    @extend_schema(parameters=[WorkshopQuery], responses=DirectorOverviewResponse)
    def list(self, request):
        board, _ = self.workbench(WorkshopQuery)
        return Response({"data": board.overview()})

    @extend_schema(parameters=[DirectorItemsQuery], responses=DirectorItemsResponse)
    @action(detail=False, methods=["get"])
    def items(self, request):
        board, params = self.workbench(DirectorItemsQuery)
        items, meta = page_of(board.select_items(params["category"], params.get("date")), params)
        return Response({"data": board.jobs(items), "meta": meta})

    @extend_schema(parameters=[DirectorDetailQuery], responses=DirectorDetailResponse)
    @action(detail=False, methods=["get"], url_path="detail")
    def plan_detail(self, request):
        board, params = self.workbench(DirectorDetailQuery)
        rows = board.jobs(board.plans().filter(pk=params["id"]), detail=True)
        if not rows:
            raise NotFound("未找到可查看的本车间计划。")
        return Response({"data": rows[0]})

    @extend_schema(parameters=[DirectorActivityQuery], responses=DirectorActivityResponse)
    @action(detail=False, methods=["get"])
    def activity(self, request):
        board, params = self.workbench(DirectorActivityQuery)
        return Response(board.activity(params))
