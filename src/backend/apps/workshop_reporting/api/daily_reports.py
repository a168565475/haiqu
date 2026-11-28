from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView

from apps.access_control.module_policy import has_permission
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import HasActiveEmployee

from ..daily_reports import (
    METAL_PERMISSION, REPORT_PERMISSION, assembly_rows, metal_rows, sewing_detail_rows, sewing_order_rows,
)


REPORTS = {
    "metal": (METAL_PERMISSION, metal_rows),
    "sewing-detail": (REPORT_PERMISSION, sewing_detail_rows),
    "sewing-orders": (REPORT_PERMISSION, sewing_order_rows),
    "assembly": (REPORT_PERMISSION, assembly_rows),
}


class DailyReportQuery(serializers.Serializer):
    report = serializers.ChoiceField(choices=tuple(REPORTS), default="metal")
    date = serializers.DateField(default=timezone.localdate)
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class DailyReportRow(serializers.Serializer):
    id = serializers.CharField()
    task_number = serializers.CharField()
    product_name = serializers.CharField()
    part_name = serializers.CharField(required=False)
    specification = serializers.CharField(required=False)
    color = serializers.CharField(required=False)
    employee = serializers.CharField(required=False)
    operation = serializers.CharField(required=False)
    unit = serializers.CharField(required=False)
    order_unit = serializers.CharField(required=False)
    order_quantity = serializers.CharField(required=False, allow_null=True)
    today = serializers.DecimalField(max_digits=28, decimal_places=4, normalize_output=True, required=False)
    cumulative = serializers.CharField(required=False)
    remaining = serializers.CharField(required=False, allow_null=True)


class DailyReportPage(serializers.Serializer):
    data = DailyReportRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class DailyReportView(GenericAPIView):
    permission_classes = [HasActiveEmployee]
    pagination_class = StandardPageNumberPagination
    serializer_class = DailyReportRow

    @extend_schema(parameters=[DailyReportQuery], responses=DailyReportPage)
    def get(self, request):
        query = DailyReportQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        permission, read_rows = REPORTS[filters["report"]]
        if not has_permission(request, permission):
            raise PermissionDenied("当前岗位没有这张日报的查看权限。")
        page = self.paginate_queryset(read_rows(request, filters["date"], filters["task_number"]))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)
