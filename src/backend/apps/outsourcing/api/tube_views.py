from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from apps.access_control import module_policy
from apps.core.api.permissions import HasActiveEmployee

from ..models import TubeOutsourcingAction, TubeOutsourcingOrder
from ..tube_selectors import (CANCEL_PERMISSION, CREATE_PERMISSION, DISPATCH_PERMISSION, RETURN_PERMISSION, VIEW_PERMISSION,
    product_summary, require_saved_order_access, require_tube_feature, saved_order_data, source_factories,
    source_product, source_zone, tube_options, tube_order_queryset)
from ..tube_services import create_tube_order
from ..tube_action_services import confirm_tube_action
from ..tube_receipt_services import confirm_tube_final_receipt
from ..tube_receipt_selectors import (receipt_candidates, receipt_data, receipt_preview,
                                     receipt_queryset, require_receipt_read_access)
from .tube_serializers import (TubeCancelWriteSerializer, TubeDispatchWriteSerializer,
    TubeOrderWriteSerializer, TubeSourceQuerySerializer, TubeReceiptCandidatesQuerySerializer,
    TubeReceiptWriteSerializer, TubeReceiptResponseSerializer, TubeReceiptPreviewResponseSerializer,
    TubeReceiptCandidatesResponseSerializer)


class TubeActionPermission(BasePermission):
    message = '当前账号没有执行管材外发操作的权限。'

    def has_permission(self, request, view):
        permission = view.action_permission_map.get(view.action)
        permissions = permission if isinstance(permission, tuple) else (permission,)
        return any(value and module_policy.has_permission(request, value) for value in permissions)


class TubeOutsourcingOrderViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, TubeActionPermission]
    action_permission_map = {'options': VIEW_PERMISSION, 'source_context': VIEW_PERMISSION,
                             'create': CREATE_PERMISSION, 'by_request': VIEW_PERMISSION,
                             'retrieve': VIEW_PERMISSION, 'confirm_dispatch': DISPATCH_PERMISSION,
                             'cancel': CANCEL_PERMISSION, 'action_by_request': VIEW_PERMISSION,
                             'receipt_candidates': RETURN_PERMISSION, 'receipt_preview': (VIEW_PERMISSION, RETURN_PERMISSION),
                             'confirm_receipt': RETURN_PERMISSION, 'receipt_by_request': RETURN_PERMISSION,
                             'receipt': (VIEW_PERMISSION, RETURN_PERMISSION)}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_tube_feature()

    @action(detail=False, methods=['get'])
    def options(self, request):
        return Response({'data': tube_options(request)})

    @action(detail=False, methods=['get'], url_path='source-context')
    def source_context(self, request):
        serializer = TubeSourceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product, craft = source_product(request, data['schedule_product_id'])
        zone = source_zone(data['source_kind'], data.get('zone_id'))
        from apps.inventory.tube_outsourcing_limits import tube_source_context
        context = tube_source_context(schedule_product=product, source_kind=data['source_kind'], zone=zone)
        options = tube_options(request)
        context = {**context, **product_summary(product), **options, 'craft_name': craft.name,
                   'source_kind': data['source_kind'], 'zone_id': str(zone.pk) if zone else None,
                   'factories': [{'id': str(factory.pk), 'name': factory.name} for factory in source_factories(request, craft)]}
        # 库存身份和冻结凭证仅供保存服务使用，页面按可显示字段读取。
        context['rows'] = [{key: value for key, value in row.items() if key not in {'input_identity', 'snapshot'}}
                           for row in context.get('rows', [])]
        return Response({'data': context})

    def create(self, request):
        serializer = TubeOrderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, created = create_tube_order(data=serializer.validated_data, request=request)
        order = tube_order_queryset().get(pk=order.pk)
        data = saved_order_data(order, created=created, request=request)
        response = Response({'data': data}, status=201 if created else 200)
        response['ETag'] = data['etag']
        return response

    @action(detail=False, methods=['get'], url_path=r'by-request/(?P<request_id>[^/.]+)')
    def by_request(self, request, request_id=None):
        request_id = serializers.UUIDField().run_validation(request_id)
        order = get_object_or_404(tube_order_queryset(), client_request_id=request_id)
        require_saved_order_access(request, order)
        data = saved_order_data(order, request=request)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    def retrieve(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        require_saved_order_access(request, order)
        return self._detail_response(order, request)

    def _detail_response(self, order, request, *, action_record=None, created=False):
        data = saved_order_data(order, request=request, action_record=action_record, created=created)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    @action(detail=True, methods=['post'], url_path='dispatch')
    def confirm_dispatch(self, request, pk=None):
        return self._confirm_action(request, pk, 'DISPATCH', TubeDispatchWriteSerializer)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._confirm_action(request, pk, 'CANCEL', TubeCancelWriteSerializer)

    def _confirm_action(self, request, pk, kind, serializer_class):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, record, created = confirm_tube_action(order_id=pk, kind=kind,
            data=serializer.validated_data, request=request)
        order = tube_order_queryset().get(pk=order.pk)
        return self._detail_response(order, request, action_record=record, created=created)

    @action(detail=True, methods=['get'], url_path=r'action-by-request/(?P<request_id>[^/.]+)')
    def action_by_request(self, request, pk=None, request_id=None):
        pk = serializers.UUIDField().run_validation(pk)
        request_id = serializers.UUIDField().run_validation(request_id)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        require_saved_order_access(request, order)
        record = get_object_or_404(TubeOutsourcingAction.objects.select_related('actor_employee'),
                                   order_id=order.pk, client_request_id=request_id)
        return self._detail_response(order, request, action_record=record)

    @extend_schema(parameters=[TubeReceiptCandidatesQuerySerializer], responses=TubeReceiptCandidatesResponseSerializer)
    @action(detail=False, methods=['get'], url_path='receipt-candidates')
    def receipt_candidates(self, request):
        serializer = TubeReceiptCandidatesQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response({'data': receipt_candidates(request, serializer.validated_data)})

    @extend_schema(responses=TubeReceiptPreviewResponseSerializer,
        parameters=[OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path='receipt-preview')
    def receipt_preview(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        order = get_object_or_404(tube_order_queryset(), pk=pk)
        data = receipt_preview(order, request)
        response = Response({'data': data})
        response['ETag'] = data['etag']
        return response

    @extend_schema(request=TubeReceiptWriteSerializer, responses={200: TubeReceiptResponseSerializer,
        201: TubeReceiptResponseSerializer}, parameters=[OpenApiParameter('If-Match', str,
        location=OpenApiParameter.HEADER, required=True),
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['post'], url_path='confirm-receipt')
    def confirm_receipt(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        serializer = TubeReceiptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, created = confirm_tube_final_receipt(order_id=pk, data=serializer.validated_data, request=request)
        return self._receipt_response(receipt_queryset().get(pk=record.pk), created=created)

    def _receipt_response(self, record, *, created=False):
        data = receipt_data(record, created=created)
        response = Response({'data': data}, status=201 if created else 200)
        response['ETag'] = data['etag']
        return response

    @extend_schema(responses=TubeReceiptResponseSerializer, parameters=[
        OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter('request_id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path=r'receipt-by-request/(?P<request_id>[^/.]+)')
    def receipt_by_request(self, request, pk=None, request_id=None):
        pk = serializers.UUIDField().run_validation(pk)
        request_id = serializers.UUIDField().run_validation(request_id)
        record = get_object_or_404(receipt_queryset(), order_id=pk, client_request_id=request_id)
        require_saved_order_access(request, record.order, RETURN_PERMISSION)
        return self._receipt_response(record)

    @extend_schema(responses=TubeReceiptResponseSerializer,
        parameters=[OpenApiParameter('id', OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    @action(detail=True, methods=['get'], url_path='receipt')
    def receipt(self, request, pk=None):
        pk = serializers.UUIDField().run_validation(pk)
        record = get_object_or_404(receipt_queryset(), order_id=pk)
        require_receipt_read_access(request, record.order)
        return self._receipt_response(record)
