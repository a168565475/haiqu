from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee

from .. import editing, selectors, services
from ..models import MaterialCatalog
from .serializers import (
    AllowedUnitCreateSerializer, AllowedUnitPatchSerializer, AttributeValueCreateSerializer,
    AttributeValuePatchSerializer, CatalogCreateSerializer,
    CatalogDetailResponseSerializer, CatalogErrorResponseSerializer, CatalogListQuerySerializer,
    CatalogListResponseSerializer, CatalogOptionsResponseSerializer, CatalogPatchSerializer, CatalogSaveSerializer,
    CatalogSummarySerializer,
)


IF_MATCH = OpenApiParameter(
    "If-Match", str, OpenApiParameter.HEADER, required=True,
    description="当前主档详情返回的 ETag；每次成功写入后使用新版本。",
)
ETAG = OpenApiParameter(
    "ETag", str, OpenApiParameter.HEADER, response=[200, 201], required=True,
    description="本次完整详情的版本；后续写入通过 If-Match 提交。",
)
WRITE_RESPONSES = {200: CatalogDetailResponseSerializer, **{
    code: CatalogErrorResponseSerializer for code in (400, 401, 403, 404, 412, 428)
}}
CATALOG_PATCH_SCHEMA = {
    "type": "object", "properties": {
        "spray_enabled": {"type": "boolean"},
        "base_warehouse_id": {"type": "string", "format": "uuid", "nullable": True},
        "semi_warehouse_id": {"type": "string", "format": "uuid", "nullable": True},
    }, "minProperties": 1, "additionalProperties": False,
}
UNIT_PATCH_SCHEMA = {
    "type": "object", "properties": {
        "unit_id": {"type": "string", "format": "uuid"},
        "unit_name": {"type": "string", "minLength": 1, "maxLength": 80},
    }, "oneOf": [{"required": ["unit_id"]}, {"required": ["unit_name"]}], "additionalProperties": False,
}
UNIT_CREATE_SCHEMA = {
    **UNIT_PATCH_SCHEMA,
    "properties": {**UNIT_PATCH_SCHEMA["properties"], "scope": {"type": "string", "enum": ["BASE", "SPRAY"]}},
    "required": ["scope"],
}


class MaterialCatalogActionPermission(BusinessActionPermission):
    def has_permission(self, request, view):
        if super().has_permission(request, view):
            return True
        # 兼容旧原料维护入口，仅放行本页已明确的维护操作。
        if view.action not in {
            "create", "save", "destroy", "partial_update", "add_value", "update_value", "remove_value",
            "add_unit", "update_unit", "remove_unit",
        }:
            return False
        if (view.action == "partial_update" and (
                not isinstance(request.data, dict) or not request.data
                or not set(request.data).issubset({"base_warehouse_id", "semi_warehouse_id", "spray_enabled"}))):
            return False
        from apps.access_control.sales_policy import enabled, has_permission
        return all(
            has_permission(request, code) if enabled() else request.user.has_perm(code)
            for code in ("material_catalog.view_materialcatalog", "products.add_rawmaterialinformation")
        )


class MaterialCatalogViewSet(viewsets.GenericViewSet):
    serializer_class = CatalogSummarySerializer
    queryset = MaterialCatalog.objects.none()
    permission_classes = [IsAuthenticated, HasActiveEmployee, MaterialCatalogActionPermission]
    action_permission_map = {
        "list": "material_catalog.view_materialcatalog",
        "retrieve": "material_catalog.view_materialcatalog",
        "options_list": "material_catalog.view_materialcatalog",
        "metadata": "material_catalog.view_materialcatalog",
        "create": "material_catalog.add_materialcatalog",
        "save": "material_catalog.change_materialcatalog",
        "destroy": "material_catalog.change_materialcatalog",
        "partial_update": "material_catalog.change_materialcatalog",
        "add_value": "material_catalog.change_materialcatalog",
        "update_value": "material_catalog.change_materialcatalog",
        "remove_value": "material_catalog.change_materialcatalog",
        "add_unit": "material_catalog.change_materialcatalog",
        "update_unit": "material_catalog.change_materialcatalog",
        "remove_unit": "material_catalog.change_materialcatalog",
    }

    def get_permissions(self):
        if self.action is None:
            # 不支持的方法交给 DRF 返回 405；仍先要求登录和有效员工。
            return [IsAuthenticated(), HasActiveEmployee()]
        return super().get_permissions()

    def _validated(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @staticmethod
    def _detail_response(result, response_status=status.HTTP_200_OK):
        data, etag = result
        response = Response({"data": data}, status=response_status)
        response["ETag"] = etag
        return response

    @extend_schema(responses={200: CatalogOptionsResponseSerializer, **{
        code: CatalogErrorResponseSerializer for code in (401, 403)
    }})
    def options_list(self, request):
        return Response({"data": selectors.catalog_options()})

    @extend_schema(parameters=[
        CatalogListQuerySerializer,
        OpenApiParameter("page", int, OpenApiParameter.QUERY, description="页码，从 1 开始。"),
        OpenApiParameter("page_size", int, OpenApiParameter.QUERY, description="每页条数，默认 20，最多 100。"),
    ], responses={200: CatalogListResponseSerializer, **{
        code: CatalogErrorResponseSerializer for code in (400, 401, 403, 404)
    }})
    def list(self, request):
        query = CatalogListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        queryset = selectors.catalog_list(
            category=query.validated_data.get("category", ""), query=query.validated_data.get("q", "")
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response([selectors.catalog_summary(catalog) for catalog in page])

    @extend_schema(request=CatalogCreateSerializer, parameters=[ETAG], responses={201: CatalogDetailResponseSerializer, **{
        code: CatalogErrorResponseSerializer for code in (400, 401, 403)
    }})
    def create(self, request):
        return self._detail_response(
            services.create_catalog(data=self._validated(CatalogCreateSerializer), request=request), status.HTTP_201_CREATED
        )

    @extend_schema(parameters=[ETAG], responses={200: CatalogDetailResponseSerializer, **{
        code: CatalogErrorResponseSerializer for code in (401, 403, 404)
    }})
    def retrieve(self, request, pk=None):
        # 短暂锁住主档，使属性集合与返回的 ETag 来自同一版本。
        with transaction.atomic():
            catalog = get_object_or_404(MaterialCatalog.objects.select_for_update(), pk=pk, archived_at__isnull=True)
            return self._detail_response((selectors.catalog_detail(catalog), etag_for_instance(catalog)))

    @extend_schema(request={"application/json": CATALOG_PATCH_SCHEMA}, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def partial_update(self, request, pk=None):
        data = self._validated(CatalogPatchSerializer)
        return self._detail_response(services.update_catalog(catalog_id=pk, data=data, request=request))

    @extend_schema(request=CatalogSaveSerializer, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def save(self, request, pk=None):
        return self._detail_response(editing.save_catalog(
            catalog_id=pk, data=self._validated(CatalogSaveSerializer), request=request,
        ))

    @extend_schema(request=None, parameters=[IF_MATCH], responses={204: None, **{
        code: CatalogErrorResponseSerializer for code in (401, 403, 404, 412, 428)
    }})
    def destroy(self, request, pk=None):
        editing.archive_catalog(catalog_id=pk, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=AttributeValueCreateSerializer, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def add_value(self, request, pk=None):
        return self._detail_response(services.add_value(catalog_id=pk, data=self._validated(AttributeValueCreateSerializer), request=request))

    @extend_schema(request=AttributeValuePatchSerializer, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def update_value(self, request, pk=None, value_id=None):
        data = self._validated(AttributeValuePatchSerializer)
        return self._detail_response(services.update_value(catalog_id=pk, value_id=value_id, value=data["value"], color=data, request=request))

    @extend_schema(responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def remove_value(self, request, pk=None, value_id=None):
        return self._detail_response(services.remove_value(catalog_id=pk, value_id=value_id, request=request))

    @extend_schema(request={"application/json": UNIT_CREATE_SCHEMA}, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def add_unit(self, request, pk=None):
        return self._detail_response(services.add_unit(catalog_id=pk, data=self._validated(AllowedUnitCreateSerializer), request=request))

    @extend_schema(request={"application/json": UNIT_PATCH_SCHEMA}, responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def update_unit(self, request, pk=None, option_id=None):
        data = self._validated(AllowedUnitPatchSerializer)
        return self._detail_response(services.update_unit(catalog_id=pk, option_id=option_id, data=data, request=request))

    @extend_schema(responses=WRITE_RESPONSES, parameters=[IF_MATCH, ETAG])
    def remove_unit(self, request, pk=None, option_id=None):
        return self._detail_response(services.remove_unit(catalog_id=pk, option_id=option_id, request=request))
