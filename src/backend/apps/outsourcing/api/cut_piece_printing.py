"""跟单丝印只注册经任务归属过滤的读接口和建总单入口。"""
from django.urls import path
from drf_spectacular.utils import extend_schema, OpenApiTypes

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from ..tube_selectors import saved_orders_for_permission
from ..unified_selectors import UnifiedOrderFilters, _tube_candidates, unified_order_rows
from .tube_views import TubeOutsourcingOrderViewSet


class CutPiecePrintingViewSet(TubeOutsourcingOrderViewSet):
    printing = True

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
    path('cut-piece-printing-orders/by-request/<uuid:request_id>/', printing({'get': 'by_request'}), name='cut-piece-printing-by-request'),
    path('cut-piece-printing-orders/<uuid:pk>/', printing({'get': 'retrieve'}), name='cut-piece-printing-detail'),
]
