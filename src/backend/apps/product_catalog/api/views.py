from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee

from .. import selectors, services
from ..models import ProductCatalog, ProductCatalogName
from .serializers import (
    CatalogErrorResponseSerializer, CatalogOptionsResponseSerializer, ColorCreateSerializer,
    NameCreateSerializer, NameDetailResponseSerializer, NameDetailSerializer, NameListQuerySerializer,
    NameListResponseSerializer, NamePatchSerializer, ProductCreateSerializer, ProductDetailResponseSerializer,
    ProductListQuerySerializer, ProductListResponseSerializer, ProductPatchSerializer, ProductSummarySerializer,
)


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True, description="资源详情返回的当前 ETag；成功写入后使用新版本。")
ETAG = OpenApiParameter("ETag", str, OpenApiParameter.HEADER, response=[200, 201], required=True, description="本次完整详情的版本。")
ERRORS = {code: CatalogErrorResponseSerializer for code in (400, 401, 403, 404, 412, 428)}
VIEW = "product_catalog.view_productcatalog"
ADD = "product_catalog.add_productcatalog"
CHANGE = "product_catalog.change_productcatalog"


class ProductCatalogPagination(StandardPageNumberPagination):
    page_size = 50


class CatalogViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]

    def get_permissions(self):
        if self.action is None:
            return [IsAuthenticated(), HasActiveEmployee()]
        return super().get_permissions()

    def validated(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @staticmethod
    def detail_response(result, response_status=status.HTTP_200_OK):
        data, etag = result
        response = Response({"data": data}, status=response_status)
        response["ETag"] = etag
        return response


class ProductCatalogNameViewSet(CatalogViewSet):
    serializer_class = NameDetailSerializer
    queryset = ProductCatalogName.objects.none()
    pagination_class = None
    action_permission_map = {"list": VIEW, "retrieve": VIEW, "create": ADD, "partial_update": CHANGE, "metadata": VIEW}

    @extend_schema(parameters=[NameListQuerySerializer], responses={200: NameListResponseSerializer, **ERRORS})
    def list(self, request):
        query = NameListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response({"data": [selectors.name_detail(name) for name in selectors.name_list(**query.validated_data)]})

    @extend_schema(request=NameCreateSerializer, parameters=[ETAG], responses={201: NameDetailResponseSerializer, **ERRORS})
    def create(self, request):
        return self.detail_response(services.create_name(data=self.validated(NameCreateSerializer), request=request), status.HTTP_201_CREATED)

    @extend_schema(parameters=[ETAG], responses={200: NameDetailResponseSerializer, **ERRORS})
    def retrieve(self, request, pk=None):
        with transaction.atomic():
            name = get_object_or_404(ProductCatalogName.objects.select_for_update(of=("self",)).select_related("category"), pk=pk, archived_at__isnull=True, category__archived_at__isnull=True)
            return self.detail_response((selectors.name_detail(name), etag_for_instance(name)))

    @extend_schema(request=NamePatchSerializer, parameters=[IF_MATCH, ETAG], responses={200: NameDetailResponseSerializer, **ERRORS})
    def partial_update(self, request, pk=None):
        return self.detail_response(services.rename_name(name_id=pk, value=self.validated(NamePatchSerializer)["name"], request=request))


class ProductCatalogViewSet(CatalogViewSet):
    serializer_class = ProductSummarySerializer
    queryset = ProductCatalog.objects.none()
    pagination_class = ProductCatalogPagination
    action_permission_map = {"list": VIEW, "retrieve": VIEW, "options_list": VIEW, "metadata": VIEW,
                             "create": ADD, "partial_update": CHANGE, "add_color": CHANGE, "remove_color": CHANGE}

    @extend_schema(responses={200: CatalogOptionsResponseSerializer, **ERRORS})
    def options_list(self, request):
        return Response({"data": selectors.catalog_options()})

    @extend_schema(parameters=[ProductListQuerySerializer,
        OpenApiParameter("page", int, OpenApiParameter.QUERY, description="页码，从 1 开始。"),
        OpenApiParameter("page_size", int, OpenApiParameter.QUERY, description="每页条数，默认 50，最多 100。")],
        responses={200: ProductListResponseSerializer, **ERRORS})
    def list(self, request):
        query = ProductListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = self.paginate_queryset(selectors.product_list(**query.validated_data))
        return self.get_paginated_response([selectors.product_summary(product) for product in page])

    @extend_schema(request=ProductCreateSerializer, parameters=[ETAG], responses={201: ProductDetailResponseSerializer, **ERRORS})
    def create(self, request):
        return self.detail_response(services.create_product(data=self.validated(ProductCreateSerializer), request=request), status.HTTP_201_CREATED)

    @extend_schema(parameters=[ETAG], responses={200: ProductDetailResponseSerializer, **ERRORS})
    def retrieve(self, request, pk=None):
        with transaction.atomic():
            product = get_object_or_404(ProductCatalog.objects.select_for_update(of=("self",)),
                                       pk=pk, archived_at__isnull=True, name__archived_at__isnull=True, name__category__archived_at__isnull=True)
            return self.detail_response((selectors.product_detail(product), etag_for_instance(product)))

    @extend_schema(request=ProductPatchSerializer, parameters=[IF_MATCH, ETAG], responses={200: ProductDetailResponseSerializer, **ERRORS})
    def partial_update(self, request, pk=None):
        return self.detail_response(services.update_product(product_id=pk, data=self.validated(ProductPatchSerializer), request=request))

    @extend_schema(request=ColorCreateSerializer, parameters=[IF_MATCH, ETAG], responses={200: ProductDetailResponseSerializer, **ERRORS})
    def add_color(self, request, pk=None):
        return self.detail_response(services.add_color(product_id=pk, value=self.validated(ColorCreateSerializer)["value"], request=request))

    @extend_schema(parameters=[IF_MATCH, ETAG], responses={200: ProductDetailResponseSerializer, **ERRORS})
    def remove_color(self, request, pk=None, color_id=None):
        return self.detail_response(services.remove_color(product_id=pk, color_id=color_id, request=request))
