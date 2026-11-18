"""一般入库使用的原料选料只读入口。"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.material_catalog import selectors
from apps.material_catalog.api.public import (
    PublicOptionsQuerySerializer, PublicOptionsResponseSerializer,
)
from apps.material_catalog.api.serializers import (
    CatalogDetailResponseSerializer, CatalogListQuerySerializer, CatalogListResponseSerializer,
    CatalogOptionsResponseSerializer, CatalogSummarySerializer,
)
from apps.material_catalog.definitions import CATEGORIES, CATEGORY_TEMPLATES
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.public_configuration import public_options


class MaterialInboundSourceViewSet(viewsets.GenericViewSet):
    """仓管可选择入库原料，但不能借此访问目录维护写入口。"""

    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = CatalogSummarySerializer
    queryset = MaterialCatalog.objects.none()
    http_method_names = ["get", "head", "options"]
    allowed_categories = frozenset(CATEGORY_TEMPLATES) - {"FABRIC_SEMI"}
    action_permission_map = {
        name: "inventory.receive_material"
        for name in ("list", "retrieve", "options_list", "public_options")
    }

    @extend_schema(parameters=[CatalogListQuerySerializer], responses=CatalogListResponseSerializer)
    def list(self, request):
        query = CatalogListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        category = query.validated_data.get("category", "")
        if category and category not in self.allowed_categories:
            raise ValidationError({"category": "一般入库仅支持基础原料类别。"})
        rows = selectors.catalog_list(
            category=category, query=query.validated_data.get("q", ""),
        ).filter(category_key__in=self.allowed_categories)
        page = self.paginate_queryset(rows)
        return self.get_paginated_response([selectors.catalog_summary(row) for row in page])

    @extend_schema(responses=CatalogDetailResponseSerializer)
    def retrieve(self, request, pk=None):
        catalog_id = serializers.UUIDField().run_validation(pk)
        catalog = MaterialCatalog.objects.filter(
            pk=catalog_id, archived_at__isnull=True, category_key__in=self.allowed_categories,
        ).first()
        if catalog is None:
            raise NotFound("原料品名不存在或不属于一般入库范围。")
        data = selectors.catalog_detail(catalog)
        # 保留已配置仓库的身份，即使它已停用或类型不符；页面须提示修正，不能静默换仓。
        data["base_warehouse_id"] = str(catalog.base_warehouse_id) if catalog.base_warehouse_id else None
        data["semi_warehouse_id"] = None
        return Response({"data": data})

    @extend_schema(responses=CatalogOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="options")
    def options_list(self, request):
        categories = [row for row in CATEGORIES if row["key"] in self.allowed_categories]
        return Response({"data": {"categories": categories, "spray_fields": [], "units": [], "warehouses": []}})

    @extend_schema(parameters=[PublicOptionsQuerySerializer], responses=PublicOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="public-options")
    def public_options(self, request):
        query = PublicOptionsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        if values["category_key"] not in self.allowed_categories:
            raise ValidationError({"category_key": "一般入库仅支持基础原料类别。"})
        if values["scope"] != "BASE":
            raise ValidationError({"scope": "一般入库仅可选择基础属性。"})
        return Response({"data": public_options(**values)})
