from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.core.api.delivery_reminders import DeliveryReminderSerializer, ReminderFilter
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import HasActiveEmployee
from apps.core.delivery_reminders import PRIORITY

from ..powder_coating import METAL_PERMISSION, powder_coating_reminders, powder_coating_rows
from ..tube_selectors import VIEW_PERMISSION
from ..unified_selectors import workshop_list_access


class PowderCoatingQuery(ReminderFilter):
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    direction = serializers.ChoiceField(choices=("dispatch", "receipt"), default="dispatch")
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)
    order_id = serializers.UUIDField(required=False)


class PowderCoatingStatus(serializers.Serializer):
    status = serializers.ChoiceField(choices=tuple(PRIORITY))
    label = serializers.CharField()


class PowderCoatingRow(serializers.Serializer):
    id = serializers.CharField()
    task_number = serializers.CharField()
    business_date = serializers.DateField()
    factory_name = serializers.CharField()
    part_name = serializers.CharField()
    specification = serializers.CharField()
    spray_color = serializers.CharField()
    quantity = serializers.CharField()
    unit = serializers.CharField()
    order_id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=("TUBE", "REGULAR", "METAL", "REWORK"))
    voucher_number = serializers.CharField()
    expected_return_date = serializers.DateField(source="_deadline", allow_null=True)
    reminder = PowderCoatingStatus(allow_null=True)


class PowderCoatingPage(serializers.Serializer):
    data = PowderCoatingRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class PowderCoatingReminderQuery(ReminderFilter):
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class PowderCoatingReminderRow(serializers.Serializer):
    id = serializers.CharField()
    task_number = serializers.CharField()
    factory_name = serializers.CharField()
    part_name = serializers.CharField()
    specification = serializers.CharField()
    spray_color = serializers.CharField()
    order_id = serializers.UUIDField()
    reminder = DeliveryReminderSerializer()


class PowderCoatingReminderPage(serializers.Serializer):
    data = PowderCoatingReminderRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


def _read_scope(request):
    regular = workshop_list_access(request, VIEW_PERMISSION)
    metal = workshop_list_access(request, METAL_PERMISSION)
    if not (regular or metal):
        raise PermissionDenied("当前账号没有喷塑收发的查看权限。")
    return {"regular": regular, "metal": metal}


class PowderCoatingView(APIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(parameters=[PowderCoatingQuery], responses=PowderCoatingPage)
    def get(self, request):
        scope = _read_scope(request)
        query = PowderCoatingQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        query_data = query.validated_data
        rows = powder_coating_rows(request, query_data["task_number"], query_data["direction"],
                                   follow_up=query_data["follow_up"], owner=query_data["owner"],
                                   order_id=query_data.get("order_id"), **scope)
        paginator = StandardPageNumberPagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(PowderCoatingRow(page, many=True).data)


class PowderCoatingRemindersView(APIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(parameters=[PowderCoatingReminderQuery], responses=PowderCoatingReminderPage)
    def get(self, request):
        scope = _read_scope(request)
        query = PowderCoatingReminderQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        query_data = query.validated_data
        rows = powder_coating_reminders(request, query_data["task_number"], follow_up=query_data["follow_up"],
                                        owner=query_data["owner"], **scope)
        paginator = StandardPageNumberPagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(PowderCoatingReminderRow(page, many=True).data)
