from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.material_catalog import selectors
from apps.material_catalog.api.public import PublicMetadataResponseSerializer, PublicOptionsQuerySerializer, PublicOptionsResponseSerializer
from apps.material_catalog.api.serializers import CatalogDetailResponseSerializer, CatalogListQuerySerializer, CatalogListResponseSerializer, CatalogOptionsResponseSerializer, CatalogSummarySerializer
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.public_configuration import public_options

from ..material_source_selectors import source_crafts, source_detail, source_options


class SampleMaterialSourceViewSet(viewsets.GenericViewSet):
    """打样用料选择入口。角色拥有填料权即可选择，不获得主档页面或写入权。"""

    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = CatalogSummarySerializer
    queryset = MaterialCatalog.objects.none()
    http_method_names = ["get", "head", "options"]
    action_permission_map = {
        name: "samples.edit_sample_materials"
        for name in ("list", "retrieve", "options_list", "public_options", "crafts", "metadata")
    }

    @extend_schema(parameters=[CatalogListQuerySerializer], responses=CatalogListResponseSerializer)
    def list(self, request):
        query = CatalogListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = selectors.catalog_list(category=query.validated_data.get("category", ""), query=query.validated_data.get("q", ""))
        return self.get_paginated_response([selectors.catalog_summary(row) for row in self.paginate_queryset(rows)])

    @extend_schema(responses=CatalogDetailResponseSerializer)
    def retrieve(self, request, pk=None):
        catalog_id = serializers.UUIDField().run_validation(pk)
        catalog = get_object_or_404(MaterialCatalog, pk=catalog_id, archived_at__isnull=True)
        return Response({"data": source_detail(catalog)})

    @extend_schema(responses=CatalogOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="options")
    def options_list(self, request):
        return Response({"data": source_options()})

    @extend_schema(parameters=[PublicOptionsQuerySerializer], responses=PublicOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="public-options")
    def public_options(self, request):
        query = PublicOptionsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response({"data": public_options(**query.validated_data)})

    @extend_schema(responses=PublicMetadataResponseSerializer)
    @action(detail=False, methods=["get"])
    def crafts(self, request):
        return Response({"data": source_crafts()})
