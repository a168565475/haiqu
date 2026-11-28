from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView

from apps.access_control import module_policy
from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.core.api.delivery_reminders import DeliveryReminderSerializer, ReminderFilter
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import HasActiveEmployee
from ..sewing_tracking import TRACKED_CRAFTS, attach_tracking_details, sewing_tracking_rows
from ..tube_selectors import require_tube_feature
from ..unified_selectors import workshop_regular_access
from .sewing_workbench import SewingQuery


class SewingTrackingPermission(BasePermission):
    message = "当前岗位没有布面跟踪单的查看权限。"

    def has_permission(self, request, view):
        return workshop_regular_access(request) or module_policy.has_permission(request, CUT_PIECE_PRINTING)


class SewingTrackingQuery(SewingQuery, ReminderFilter):
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=100)


class TrackingQuantity(serializers.Serializer):
    unit = serializers.CharField()
    quantity = serializers.CharField(allow_null=True)


class TrackingUnitPrice(serializers.Serializer):
    amount = serializers.CharField()
    unit = serializers.CharField()


class SewingTrackingRow(serializers.Serializer):
    id = serializers.CharField()
    task_number = serializers.CharField()
    process = serializers.ChoiceField(choices=TRACKED_CRAFTS)
    product_name = serializers.CharField()
    part_name = serializers.CharField()
    product_image_url = serializers.CharField()
    color = serializers.CharField()
    factory_name = serializers.CharField()
    factory_phone = serializers.CharField()
    unit_prices = TrackingUnitPrice(many=True)
    planned_dispatch_dates = serializers.ListField(child=serializers.DateField())
    dispatch_dates = serializers.ListField(child=serializers.DateField())
    expected_return_dates = serializers.ListField(child=serializers.DateField())
    last_receipt_date = serializers.DateField(allow_null=True)
    sent = TrackingQuantity(many=True)
    received = TrackingQuantity(many=True)
    transferred = TrackingQuantity(many=True)
    factory_remaining = TrackingQuantity(many=True)
    not_sent = TrackingQuantity(many=True)
    reminder = DeliveryReminderSerializer(allow_null=True)


class SewingTrackingResponse(serializers.Serializer):
    data = SewingTrackingRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class SewingTrackingView(APIView):
    permission_classes = [HasActiveEmployee, SewingTrackingPermission]

    @extend_schema(operation_id="v1_sewing_tracking_list", parameters=[SewingTrackingQuery], responses=SewingTrackingResponse)
    def get(self, request):
        require_tube_feature()
        query = SewingTrackingQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        rows = sewing_tracking_rows(request, filters["task_number"], follow_up=filters["follow_up"], owner=filters["owner"])
        paginator = StandardPageNumberPagination()
        page = paginator.paginate_queryset(rows, request)
        attach_tracking_details(request, page)
        return paginator.get_paginated_response(SewingTrackingRow(page, many=True).data)
