from django.db.models import F
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_control.module_policy import has_permission
from apps.boms.image_files import safe_storage_path
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import HasActiveEmployee

from ..material_tracking import PLAN_PERMISSION, STAGES, bom_source_files, readable_boms, tracking_data, visible_products


class TrackingQuery(serializers.Serializer):
    task_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class Milestone(serializers.Serializer):
    date = serializers.DateField(allow_null=True)
    batch_count = serializers.IntegerField()
    note = serializers.CharField()


class Quantity(serializers.Serializer):
    quantity = serializers.CharField()
    unit = serializers.CharField()


class BomLink(serializers.Serializer):
    id = serializers.UUIDField()
    file_name = serializers.CharField()


class TrackingRow(serializers.Serializer):
    id = serializers.UUIDField()
    task_number = serializers.CharField()
    product_name = serializers.CharField()
    order_quantity = serializers.CharField()
    order_unit = serializers.CharField()
    color = serializers.CharField()
    stages = serializers.DictField(child=Milestone())
    coating_factories = serializers.ListField(child=serializers.CharField())
    assembly_lines = serializers.ListField(child=serializers.IntegerField())
    finished_quantities = Quantity(many=True)
    bom = BomLink(allow_null=True)
    has_packaging_requirements = serializers.BooleanField()


class TrackingListResponse(serializers.Serializer):
    data = TrackingRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class TrackingBatch(serializers.Serializer):
    kind = serializers.ChoiceField(choices=STAGES)
    date = serializers.DateField(allow_null=True)
    number = serializers.CharField()
    party = serializers.CharField()
    material = serializers.CharField()
    quantity = serializers.CharField(allow_null=True)
    unit = serializers.CharField()
    note = serializers.CharField()


class FabricArrival(serializers.Serializer):
    material = serializers.CharField()
    required = serializers.CharField()
    unit = serializers.CharField()
    arrived_on = serializers.DateField(allow_null=True)
    total_received = serializers.CharField()


class TrackingDetail(serializers.Serializer):
    batches = TrackingBatch(many=True)
    fabrics = FabricArrival(many=True)
    packaging_requirements = serializers.CharField()


class TrackingDetailResponse(serializers.Serializer):
    data = TrackingDetail()


class CanViewMaterialTracking(BasePermission):
    message = "当前岗位没有查看材料跟踪的权限。"

    def has_permission(self, request, view):
        return has_permission(request, PLAN_PERMISSION)


TRACKING_PERMISSIONS = [HasActiveEmployee, CanViewMaterialTracking]


class MaterialTrackingView(APIView):
    permission_classes = TRACKING_PERMISSIONS

    @extend_schema(operation_id="v1_material_tracking_list", parameters=[TrackingQuery], responses=TrackingListResponse)
    def get(self, request):
        query = TrackingQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        products = visible_products(request).filter(
            production_task__task_number__icontains=query.validated_data["task_number"],
        ).select_related("production_task", "unit").order_by(
            "-production_task__created_at", "production_task_id", "line_number", "pk",
        )
        paginator = StandardPageNumberPagination()
        rows = paginator.paginate_queryset(products, request)
        return paginator.get_paginated_response(TrackingRow(tracking_data(request, rows), many=True).data)


class MaterialTrackingDetailView(APIView):
    permission_classes = TRACKING_PERMISSIONS

    @extend_schema(operation_id="v1_material_tracking_detail", responses=TrackingDetailResponse)
    def get(self, request, product_id):
        product = get_object_or_404(visible_products(request), pk=product_id)
        detail = tracking_data(request, [product], detail=True)[0]
        return Response({"data": TrackingDetail(detail).data})


class MaterialTrackingBomFileView(APIView):
    permission_classes = TRACKING_PERMISSIONS

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request, product_id, bom_id):
        bom = get_object_or_404(bom_source_files(readable_boms(request)).filter(
            product_line_id__in=visible_products(request).filter(pk=product_id).values("pk"),
            production_task_id=F("product_line__production_task_id"),
        ).select_related("source_file"), pk=bom_id)
        file = bom.source_file
        path = safe_storage_path(file.storage_key)
        if path is None or not path.is_file():
            raise NotFound("BOM 源文件不可用。")
        return FileResponse(
            path.open("rb"), as_attachment=True, filename=file.original_name, content_type="application/octet-stream",
        )
