from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response
from .material_serializers import MaterialSaveSerializer, WarehouseSaveSerializer, MaterialResponseSerializer
from ..material_services import material_response, warehouse_response, save_materials, save_warehouse
from apps.reference_data.models import ProductionUnit
from .material_serializers import MaterialCandidateQuerySerializer
from ..material_reference_selectors import material_reference_options, material_candidates, color_label


class SampleMaterialActionsMixin:
    @extend_schema(responses=MaterialResponseSerializer)
    @action(detail=True, methods=['get'], url_path='procurement-material-context')
    def procurement_material_context(self, request, pk=None):
        """采购只读用料页上下文，不能借缺料读取权获取整份样品详情。"""
        from rest_framework.exceptions import NotFound
        from ..material_services import _record
        from ..procurement_status import sample_status_display
        sample = self.get_object()
        record = _record(sample)
        procurement = getattr(record, 'procurement_request', None) if record else None
        if sample.archived_at or sample.customer_account.archived_at or not procurement or not record.reviewed_at:
            raise NotFound('当前没有可读取的已核定打样缺料需求。')
        products = list(sample.products.order_by('line_number'))
        items = list(sample.items.order_by('line_number'))
        colors = [' / '.join(value for value in [item.color_name_snapshot, item.color_card_snapshot, item.color_code_snapshot] if value) for item in items]
        quantity = sum(item.sample_quantity for item in items) if items and all(item.sample_quantity is not None for item in items) else None
        return Response({'data': {'sample': {
            'id': str(sample.pk), 'request_number': sample.request_number, 'status': sample.status,
            'status_display': sample_status_display(sample), 'customer_name': sample.customer_account.account_name,
            'requested_at': sample.requested_at, 'product_name': '、'.join(product.product_name for product in products),
            'specification': '；'.join(product.specification for product in products),
            'color': '；'.join(color for color in colors if color), 'quantity_label': f'{quantity} PCS' if quantity is not None else '',
        }, 'materials': material_response(sample, request)}})

    @extend_schema(request=None, responses=MaterialResponseSerializer)
    @action(detail=True, methods=['post'], url_path='no-materials')
    def no_materials(self, request, pk=None):
        from ..material_services import confirm_no_materials
        sample = confirm_no_materials(sample_id=self.get_object().pk, request=request)
        result = material_response(sample, request)
        return Response({'data': result}, headers={'ETag': result['etag']})

    @action(detail=True, methods=['post'], url_path='production-report')
    def production_report(self, request, pk=None):
        from .material_serializers import ProductionReportSerializer
        from .serializers import SampleRequestDetailSerializer
        from ..production_services import report_production
        from ..selectors import sample_requests_with_context
        from ..models import SampleRequest
        serializer = ProductionReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = report_production(sample_id=self.get_object().pk, data=serializer.validated_data, request=request)
        sample = sample_requests_with_context(SampleRequest.objects.filter(pk=sample.pk)).get()
        return self.response_with_etag({'data': SampleRequestDetailSerializer(sample, context=self.get_serializer_context()).data}, sample)

    @extend_schema(responses=MaterialResponseSerializer)
    @action(detail=False, methods=['get'], url_path='material-reference-options')
    def material_reference_options(self, request):
        return Response({'data': material_reference_options()})

    @extend_schema(parameters=[MaterialCandidateQuerySerializer], responses=MaterialResponseSerializer)
    @action(detail=False, methods=['get'], url_path='material-candidates')
    def material_candidates(self, request):
        query = MaterialCandidateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = self.paginate_queryset(material_candidates(query.validated_data['category'], query.validated_data['q'], query.validated_data['name']))
        return self.get_paginated_response([{'id': str(row.pk), 'number': row.material_number, 'name': row.material_name,
                                            'specification': row.specification, 'material': row.material,
                                            'color': color_label(row.color) if row.color_id else row.color_snapshot,
                                            'unitId': str(row.unit_id), 'unitLabel': row.unit.unit_name} for row in rows])

    @extend_schema(responses=MaterialResponseSerializer)
    @action(detail=False, methods=['get'], url_path='material-units')
    def material_units(self, request):
        units = ProductionUnit.objects.filter(status='ACTIVE', archived_at__isnull=True)
        return Response({'data': [{'id': str(unit.pk), 'label': unit.unit_name, 'decimalPlaces': 4} for unit in units]})

    @extend_schema(request=MaterialSaveSerializer, responses=MaterialResponseSerializer)
    @action(detail=True, methods=['get', 'put'], url_path='materials')
    def materials(self, request, pk=None):
        sample = self.get_object()
        if request.method == 'PUT':
            serializer = MaterialSaveSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            sample = save_materials(sample_id=sample.pk, data=serializer.validated_data, request=request)
        result = material_response(sample, request)
        return Response({'data': result}, headers={'ETag': result.get('etag', '')})

    @extend_schema(request=WarehouseSaveSerializer, responses=MaterialResponseSerializer)
    @action(detail=True, methods=['get', 'put'], url_path='warehouse-review')
    def warehouse_review(self, request, pk=None):
        sample = self.get_object()
        if request.method == 'PUT':
            serializer = WarehouseSaveSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            sample = save_warehouse(sample_id=sample.pk, data=serializer.validated_data, request=request)
        result = warehouse_response(sample, request)
        return Response({'data': result}, headers={'ETag': result.get('etag', '')})

    @extend_schema(responses=MaterialResponseSerializer)
    @action(detail=True, methods=['get'], url_path='warehouse-inventory')
    def warehouse_inventory(self, request, pk=None):
        from rest_framework.exceptions import PermissionDenied
        from apps.access_control.module_policy import can_sample
        from apps.core.api.exceptions import Conflict
        from ..models import SampleMaterialRequest
        from ..warehouse_stock import inventory_candidates
        sample = self.get_object()
        if not can_sample(request, sample, 'samples.review_sample_materials'):
            raise PermissionDenied('当前账号没有此样品的仓库核对权限。')
        record = SampleMaterialRequest.objects.filter(sample_request=sample).first()
        if not record or not record.submitted_at or record.no_materials:
            raise Conflict('没有已提交的用料需求可查询库存。')
        return Response({'data': inventory_candidates(record)})
