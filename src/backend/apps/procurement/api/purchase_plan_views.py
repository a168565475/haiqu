from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.access_control.module_policy import has_permission
from apps.boms.models import BomLine
from apps.core.api.delivery_reminders import DeliveryReminderSerializer, ReminderFilter
from apps.core.api.permissions import HasActiveEmployee
from ..purchase_plan_selectors import purchase_plan
from ..tracking_permissions import VIEW_PERMISSION, accessible_tracking_task_ids


class CanViewPurchasePlan(BasePermission):
    message = "当前账号没有普通采购查看权限。"

    def has_permission(self, request, view):
        return has_permission(request, VIEW_PERMISSION)


class PurchasePlanFilter(ReminderFilter):
    category = serializers.ChoiceField(choices=("TUBE", "FABRIC"), default="TUBE")
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    q = serializers.CharField(max_length=200, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class PurchasePlanDetailFilter(serializers.Serializer):
    category = serializers.ChoiceField(choices=("TUBE", "FABRIC"))
    task_id = serializers.UUIDField()


class PurchasePlanAmount(serializers.Serializer):
    quantity = serializers.CharField()
    unit = serializers.CharField()


class PurchasePlanRow(serializers.Serializer):
    id = serializers.UUIDField()
    task_id = serializers.UUIDField()
    task_number = serializers.CharField()
    product_name = serializers.CharField()
    task_quantity = serializers.IntegerField()
    bom_number = serializers.CharField()
    name = serializers.CharField()
    material = serializers.CharField()
    specification = serializers.CharField()
    thickness = serializers.CharField()
    cutting_length = serializers.CharField()
    raw_length = serializers.CharField()
    hardness = serializers.CharField()
    coating = serializers.CharField()
    fabric_width = serializers.CharField()
    fabric_color = serializers.CharField()
    required = PurchasePlanAmount(allow_null=True)
    ordered = PurchasePlanAmount(many=True)
    received = PurchasePlanAmount(many=True)
    progress = serializers.CharField()
    note = serializers.CharField()
    reminder = DeliveryReminderSerializer(allow_null=True)


class PurchasePlanMovement(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    amount = PurchasePlanAmount(allow_null=True)
    status = serializers.CharField()
    days = serializers.IntegerField(allow_null=True)
    equivalents = PurchasePlanAmount(many=True)


class PurchasePlanBatch(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    batch_number = serializers.IntegerField(allow_null=True)
    supplier = serializers.CharField()
    sheet_numbers = serializers.ListField(child=serializers.CharField())
    ordered_on = serializers.DateField(allow_null=True)
    expected_on = serializers.DateField(allow_null=True)
    complete_on = serializers.DateField(allow_null=True)
    ordered = PurchasePlanAmount(allow_null=True)
    ordered_equivalents = PurchasePlanAmount(many=True)
    received = PurchasePlanAmount(allow_null=True)
    remaining = PurchasePlanAmount(allow_null=True)
    progress = serializers.CharField()
    unit_price = PurchasePlanAmount(allow_null=True)
    currency = serializers.CharField()
    shared = serializers.BooleanField()
    products = serializers.ListField(child=serializers.CharField())
    bom_numbers = serializers.ListField(child=serializers.CharField())
    arrivals = PurchasePlanMovement(many=True)
    returns = PurchasePlanMovement(many=True)
    reminder = DeliveryReminderSerializer(allow_null=True)


class PurchasePlanSourceVersion(serializers.Serializer):
    bom_number = serializers.CharField()
    required = PurchasePlanAmount(allow_null=True)


class PurchasePlanDetail(PurchasePlanRow):
    batches = PurchasePlanBatch(many=True)
    source_versions = PurchasePlanSourceVersion(many=True)
    purchase_reminders = DeliveryReminderSerializer(many=True)


class PurchasePlanListResponse(serializers.Serializer):
    data = PurchasePlanRow(many=True)
    total = serializers.IntegerField()


class PurchasePlanDetailResponse(serializers.Serializer):
    data = PurchasePlanDetail()


class PurchasePlanViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated, HasActiveEmployee, CanViewPurchasePlan)
    serializer_class = PurchasePlanRow
    queryset = BomLine.objects.none()
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    @extend_schema(parameters=[PurchasePlanFilter], responses=PurchasePlanListResponse)
    def list(self, request):
        query = PurchasePlanFilter(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, total = purchase_plan(task_ids=accessible_tracking_task_ids(request), **query.validated_data)
        return Response({"data": PurchasePlanRow(rows, many=True).data, "total": total})

    @extend_schema(parameters=[PurchasePlanDetailFilter], responses=PurchasePlanDetailResponse)
    def retrieve(self, request, pk=None):
        query = PurchasePlanDetailFilter(data=request.query_params)
        query.is_valid(raise_exception=True)
        identifier = serializers.UUIDField().run_validation(pk)
        tasks = accessible_tracking_task_ids(request).filter(pk=query.validated_data["task_id"])
        rows, _ = purchase_plan(task_ids=tasks, category=query.validated_data["category"], line_id=identifier)
        if not rows:
            raise NotFound("未找到该采购需求。")
        return Response({"data": PurchasePlanDetail(rows[0]).data})
