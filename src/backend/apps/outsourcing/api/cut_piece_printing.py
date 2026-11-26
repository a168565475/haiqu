"""跟单丝印只注册经任务归属过滤的读接口和建总单入口。"""
from django.urls import path
from drf_spectacular.utils import extend_schema, OpenApiTypes
from rest_framework import serializers
from rest_framework.response import Response

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from ..plan_services import plan_source_context
from ..tube_selectors import (printing_source, product_display, product_summary, saved_orders_for_permission,
                              source_factories, tube_options)
from ..unified_selectors import UnifiedOrderFilters, _tube_candidates, unified_order_rows
from .tube_serializers import TubeOrderWriteSerializer
from .tube_views import TubeOutsourcingOrderViewSet


def require_print_product(attrs):
    if not attrs.get('product_line_id') and not attrs.get('schedule_product_id'):
        raise serializers.ValidationError({'product_line_id': '请选择生产任务中的产品。'})
    if not attrs.get('is_plan'):
        raise serializers.ValidationError('跟单入口仅支持裁片丝印总单。')
    return attrs


class CutPiecePrintingSourceSerializer(serializers.Serializer):
    product_line_id = serializers.UUIDField(required=False)
    schedule_product_id = serializers.UUIDField(required=False, allow_null=True)
    craft_id = serializers.UUIDField()
    source_kind = serializers.ChoiceField(choices=['CUTTING'], default='CUTTING')
    is_plan = serializers.BooleanField(default=True)
    category = serializers.ChoiceField(choices=['screen_printing'], required=False)

    def validate(self, attrs):
        if 'plan_id' in self.initial_data or 'zone_id' in self.initial_data:
            raise serializers.ValidationError('裁片丝印建单不选择库存来源。')
        return require_print_product(attrs)


class CutPiecePrintingWriteSerializer(TubeOrderWriteSerializer):
    product_line_id = serializers.UUIDField(required=False)
    schedule_product_id = serializers.UUIDField(required=False, allow_null=True)
    source_kind = serializers.ChoiceField(choices=['CUTTING'])

    def validate(self, attrs):
        return require_print_product(super().validate(attrs))


class CutPiecePrintingViewSet(TubeOutsourcingOrderViewSet):
    printing = True
    write_serializer = CutPiecePrintingWriteSerializer

    @extend_schema(parameters=[CutPiecePrintingSourceSerializer], responses=OpenApiTypes.OBJECT)
    def source_context(self, request):
        serializer = CutPiecePrintingSourceSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        line, product, craft = printing_source(request, serializer.validated_data)
        context = plan_source_context(schedule_product=product, printing_line=line, source_kind='CUTTING',
                                      zone=None, craft=craft, for_plan=True)
        context['rows'] = [{key: value for key, value in row.items() if key not in {'input_identity', 'snapshot'}}
                           for row in context['rows']]
        units = {row['unit'] for row in context['rows']}
        return Response({'data': {**tube_options(request, category='screen_printing', permission=CUT_PIECE_PRINTING),
            **context, **product_summary(product, product_line=line), **product_display(product, printing=True, product_line=line),
            'craft_name': craft.name, 'output_unit': units.pop() if len(units) == 1 else '',
            'material_rows': [], 'material_category': '辅料', 'zone_id': None,
            'factories': [{'id': str(row.pk), 'name': row.name} for row in source_factories(request, craft, CUT_PIECE_PRINTING)]}})

    @extend_schema(request=CutPiecePrintingWriteSerializer, responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT})
    def create(self, request):
        return super().create(request)

    @extend_schema(parameters=[UnifiedOrderFilters], responses=OpenApiTypes.OBJECT)
    def list(self, request):
        serializer = UnifiedOrderFilters(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        filters.pop('warehouse_stage', None)
        orders = saved_orders_for_permission(request, CUT_PIECE_PRINTING)
        candidates = _tube_candidates(request, filters, queryset=orders).order_by('-updated_at', '-id')
        page = list(self.paginate_queryset(candidates.values('id', 'record_type', 'unified_source', 'unified_access')))
        return self.get_paginated_response(unified_order_rows(request, page, filters))


printing = CutPiecePrintingViewSet.as_view
urlpatterns = [
    path('cut-piece-printing-orders/', printing({'get': 'list', 'post': 'create'}), name='cut-piece-printing-list'),
    path('cut-piece-printing-orders/options/', printing({'get': 'options'}), name='cut-piece-printing-options'),
    path('cut-piece-printing-orders/source-context/', printing({'get': 'source_context'}), name='cut-piece-printing-source-context'),
    path('cut-piece-printing-orders/product-images/<uuid:schedule_product_id>/<uuid:file_id>/', printing({'get': 'product_image'}), name='cut-piece-printing-product-image'),
    path('cut-piece-printing-orders/product-lines/<uuid:product_line_id>/images/<uuid:file_id>/', printing({'get': 'product_image'}), name='cut-piece-printing-line-image'),
    path('cut-piece-printing-orders/by-request/<uuid:request_id>/', printing({'get': 'by_request'}), name='cut-piece-printing-by-request'),
    path('cut-piece-printing-orders/<uuid:pk>/', printing({'get': 'retrieve'}), name='cut-piece-printing-detail'),
]
