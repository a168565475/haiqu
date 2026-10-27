from ..p4_access import scoped_records
from apps.access_control.resource_scopes import current_permission, filter_crafts
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.outsourcing.models import OutsourcingOrder
from apps.outsourcing.warehouse_access import (
    REWORK_RETURN_PERMISSION, RETURN_PERMISSION, WarehouseActionReadPermission,
    warehouse_original_handoffs, warehouse_rework_orders, warehouse_stage,
)

from ..models import (
    MetalProcessingExternalOrder, MetalProcessingOriginalHandoff,
    MetalProcessingRework, MetalProcessingUnsprayedReturn,
)
from ..p4_services import (
    _handoff_return_state, _order_result, available_p4_semi_identity, close_external_order,
    confirm_external_good_return, confirm_external_handoff, create_external_order,
    create_rework, create_unsprayed_return, rework_result, unsprayed_return_result,
    confirm_original_good_return, original_good_return_context,
    adjust_external_allocation,
)
from .p4_serializers import (
    P4ClosureWriteSerializer, P4ExternalHandoffWriteSerializer,
    P4ExternalOrderWriteSerializer, P4GoodReturnWriteSerializer,
    P4RecordResponseSerializer, P4ReworkWriteSerializer,
    P4UnsprayedReturnWriteSerializer, P4OrderResponseSerializer,
    P4AllocationWriteSerializer,
    P4CancelPendingWriteSerializer,
)
from ..processing_selectors import processing_lines
from ..original_order_services import original_closure_data, original_order_context, original_order_for_request, write_original_order_closure


class MetalProcessingOriginalHandoffViewSet(viewsets.GenericViewSet):
    serializer_class = P4RecordResponseSerializer
    permission_classes = [HasActiveEmployee, WarehouseActionReadPermission]
    warehouse_read_actions = {'retrieve'}
    warehouse_read_permissions = (RETURN_PERMISSION,)
    action_permission_map = {
        "retrieve": "material_issues.view_metalprocessingsource",
        "returns": "material_issues.register_metalprocessingunsprayedreturn",
        "good_returns": "outsourcing.confirm_return_outsourcingorder",
    }
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MetalProcessingOriginalHandoff.objects.none()
        if self.action in self.warehouse_read_actions and warehouse_stage(self.request):
            return warehouse_original_handoffs(self.request).select_related('source', 'original_order', 'factory').prefetch_related(
                'unsprayed_returns', 'unsprayed_returns__reworks')
        queryset = MetalProcessingOriginalHandoff.objects.filter(
            source__issue_line__in=processing_lines(self.request),
            original_order__in=accessible_outsourcing_orders(self.request),
        ).select_related("source", "original_order", "factory").prefetch_related(
            "unsprayed_returns", "unsprayed_returns__reworks",
        )
        return scoped_records(queryset, self.request, current_permission(self.request, "material_issues.view_metalprocessingsource"), "original_order__craft_id")

    def retrieve(self, request, pk=None):
        handoff = get_object_or_404(self.get_queryset(), pk=pk)
        from ..processing_selectors import frozen_source, source_etag
        permission = RETURN_PERMISSION if warehouse_stage(request) else None
        line = get_object_or_404(processing_lines(request, permission=permission), pk=handoff.source.issue_line_id)
        return Response({"data": {
            "id": str(handoff.pk), "source_id": str(handoff.source_id),
            "original_order_id": str(handoff.original_order_id), "original_order_number": handoff.original_order.order_number,
            "original_order_status": handoff.original_order.status,
            "original_order_closure": original_closure_data(handoff.original_order),
            "source_etag": source_etag(line, handoff.source, frozen_source(line)),
            "factory_id": str(handoff.factory_id), "factory_name": handoff.factory.name,
            "handoff_pieces": handoff.handoff_pieces, "handoff_date": handoff.handoff_date.isoformat(),
            **_handoff_return_state(handoff),
            "good_return_context": original_good_return_context(handoff, request),
            "unsprayed_returns": [
                unsprayed_return_result(row) | {
                    "completed_rework_pieces": sum(rework.completed_pieces for rework in row.reworks.all()),
                    "remaining_rework_pieces": row.returned_pieces - sum(rework.completed_pieces for rework in row.reworks.all()),
                    "reworks": [rework_result(rework, request) for rework in row.reworks.all()],
                }
                for row in handoff.unsprayed_returns.all()
            ],
        }})

    @extend_schema(request=P4GoodReturnWriteSerializer, responses=P4RecordResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"], url_path="good-returns")
    def good_returns(self, request, pk=None):
        handoff = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4GoodReturnWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = confirm_original_good_return(request=request, handoff_id=handoff.pk, **serializer.validated_data)
        response = Response({"data": result})
        response["ETag"] = result["etag"]
        return response

    @extend_schema(request=P4UnsprayedReturnWriteSerializer, responses=P4RecordResponseSerializer)
    @action(detail=True, methods=["post"])
    def returns(self, request, pk=None):
        handoff = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4UnsprayedReturnWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": create_unsprayed_return(request=request, handoff_id=handoff.pk, **serializer.validated_data)})


class MetalProcessingOriginalOrderViewSet(viewsets.GenericViewSet):
    serializer_class = P4RecordResponseSerializer
    queryset = OutsourcingOrder.objects.none()
    permission_classes = [HasActiveEmployee, WarehouseActionReadPermission]
    warehouse_read_actions = {'retrieve'}
    warehouse_read_permissions = (RETURN_PERMISSION,)
    action_permission_map = {
        "retrieve": "material_issues.view_metalprocessingsource",
        "close": "outsourcing.complete_outsourcingorder",
        "cancel_pending": "outsourcing.change_outsourcingorder",
    }
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def retrieve(self, request, pk=None):
        result = original_order_context(original_order_for_request(request, pk), request)
        response = Response({"data": result})
        response["ETag"] = result["etag"]
        return response

    @extend_schema(request=P4ClosureWriteSerializer, responses=P4RecordResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        serializer = P4ClosureWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = write_original_order_closure(request=request, order_id=pk, **serializer.validated_data)
        response = Response({"data": result})
        response["ETag"] = result["etag"]
        return response

    @extend_schema(request=P4CancelPendingWriteSerializer, responses=P4RecordResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"], url_path="cancel-pending")
    def cancel_pending(self, request, pk=None):
        serializer = P4CancelPendingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = write_original_order_closure(request=request, order_id=pk, **serializer.validated_data)
        response = Response({"data": result})
        response["ETag"] = result["etag"]
        return response


class MetalProcessingUnsprayedReturnViewSet(viewsets.GenericViewSet):
    serializer_class = P4RecordResponseSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "retrieve": "material_issues.view_metalprocessingsource",
        "rework": "material_issues.register_metalprocessingrework",
    }
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MetalProcessingUnsprayedReturn.objects.none()
        queryset = MetalProcessingUnsprayedReturn.objects.filter(
            original_handoff__source__issue_line__in=processing_lines(self.request),
        ).select_related("original_handoff__source", "original_handoff__original_order", "received_by_employee").prefetch_related("reworks")
        return scoped_records(queryset, self.request, current_permission(self.request, "material_issues.view_metalprocessingsource"), "original_handoff__original_order__craft_id", "original_handoff__source__issue_line")

    def retrieve(self, request, pk=None):
        record = get_object_or_404(self.get_queryset(), pk=pk)
        completed = sum(row.completed_pieces for row in record.reworks.all())
        return Response({"data": unsprayed_return_result(record) | {
            "completed_rework_pieces": completed,
            "remaining_rework_pieces": record.returned_pieces - completed,
        }})

    @extend_schema(request=P4ReworkWriteSerializer, responses=P4RecordResponseSerializer)
    @action(detail=True, methods=["post"])
    def rework(self, request, pk=None):
        record = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4ReworkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": create_rework(request=request, unsprayed_return_id=record.pk, **serializer.validated_data)})


class MetalProcessingReworkViewSet(viewsets.GenericViewSet):
    serializer_class = P4RecordResponseSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "retrieve": "material_issues.view_metalprocessingsource",
        "orders": "material_issues.create_metalprocessingexternalorder",
    }
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MetalProcessingRework.objects.none()
        queryset = MetalProcessingRework.objects.filter(
            source__issue_line__in=processing_lines(self.request),
        ).select_related("source", "unsprayed_return")
        return scoped_records(queryset, self.request, current_permission(self.request, "material_issues.view_metalprocessingsource"), "unsprayed_return__original_handoff__original_order__craft_id")

    def retrieve(self, request, pk=None):
        record = get_object_or_404(self.get_queryset(), pk=pk)
        from ..p4_services import rework_result
        return Response({"data": rework_result(record, request)})

    @extend_schema(request=P4ExternalOrderWriteSerializer, responses=P4OrderResponseSerializer)
    @action(detail=True, methods=["post"])
    def orders(self, request, pk=None):
        record = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4ExternalOrderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": create_external_order(request=request, rework_id=record.pk, **serializer.validated_data)}, status=201)


class MetalProcessingExternalOrderViewSet(viewsets.GenericViewSet):
    serializer_class = P4OrderResponseSerializer
    permission_classes = [HasActiveEmployee, WarehouseActionReadPermission]
    warehouse_read_actions = {'retrieve', 'semi_stock'}
    warehouse_read_permissions = (REWORK_RETURN_PERMISSION,)
    action_permission_map = {
        "list": "material_issues.view_metalprocessingsource",
        "retrieve": "material_issues.view_metalprocessingsource",
        "handoff": "material_issues.confirm_metalprocessingexternalhandoff",
        "allocation": "material_issues.change_metalprocessingexternalorder",
        "returns": "material_issues.confirm_metalprocessingexternalreturn",
        "close": "material_issues.close_metalprocessingexternalorder",
        "semi_stock": "material_issues.view_metalprocessingsource",
    }
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MetalProcessingExternalOrder.objects.none()
        if self.action in self.warehouse_read_actions and warehouse_stage(self.request):
            return warehouse_rework_orders(self.request).select_related('source', 'factory', 'craft', 'rework', 'original_return').prefetch_related(
                'handoff', 'good_returns', 'closure')
        queryset = MetalProcessingExternalOrder.objects.filter(
            source__issue_line__in=processing_lines(self.request),
        ).select_related("source", "factory", "craft", "rework", "original_return").prefetch_related("handoff", "good_returns", "closure")
        return scoped_records(queryset, self.request, current_permission(self.request, "material_issues.view_metalprocessingsource"), "craft_id")

    def list(self, request):
        rows = [_order_result(row, request) for row in self.get_queryset().order_by("-created_at", "-id")]
        return Response({"data": rows, "meta": {"total": len(rows)}})

    def retrieve(self, request, pk=None):
        return Response({"data": _order_result(get_object_or_404(self.get_queryset(), pk=pk), request)})

    @extend_schema(request=P4AllocationWriteSerializer, responses=P4OrderResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def allocation(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4AllocationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = adjust_external_allocation(request=request, order_id=pk, **serializer.validated_data)
        response = Response({"data": result})
        response["ETag"] = result["etag"]
        return response

    @extend_schema(request=P4ExternalHandoffWriteSerializer, responses=P4OrderResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def handoff(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4ExternalHandoffWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": confirm_external_handoff(request=request, order_id=pk, **serializer.validated_data)})

    @extend_schema(request=P4GoodReturnWriteSerializer, responses=P4OrderResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def returns(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4GoodReturnWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": confirm_external_good_return(request=request, order_id=pk, **serializer.validated_data)})

    @extend_schema(request=P4ClosureWriteSerializer, responses=P4OrderResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = P4ClosureWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"data": close_external_order(request=request, order_id=pk, **serializer.validated_data)})

    @extend_schema(responses=P4RecordResponseSerializer)
    @action(detail=True, methods=["get"], url_path="semi-stock")
    def semi_stock(self, request, pk=None):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        return Response({"data": available_p4_semi_identity(order)})
