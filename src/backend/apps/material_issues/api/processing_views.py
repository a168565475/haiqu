from apps.access_control.resource_scopes import can_order, filter_crafts, enabled, require_order_craft
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.organizations.selectors import active_department_employees
from apps.core.api.permissions import HasActiveEmployee
from apps.outsourcing.warehouse_access import (
    WarehouseActionReadPermission, warehouse_stage, warehouse_original_handoffs,
    warehouse_rework_orders, warehouse_crafts, warehouse_original_dispatch_orders,
    ORIGINAL_HANDOFF_PERMISSION, REWORK_HANDOFF_PERMISSION,
)

from ..processing_selectors import processing_lines, readable_processing_lines, source_data
from ..processing_services import record_processing
from .processing_serializers import (
    ProcessingClosureWriteSerializer, ProcessingCompletionWriteSerializer,
    ProcessingSourceFilterSerializer, ProcessingSourceReadSerializer, ProcessingSourceResponseSerializer,
    ProcessingErrorResponseSerializer, ProcessingSourceListResponseSerializer,
)
from .p4_serializers import P4OriginalHandoffWriteSerializer, P4SourceResponseSerializer
from ..p4_services import _source_result, create_original_handoff, p4_schema_ready


ETAG_PARAMETER = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True,
                                  description="来源详情返回的 ETag；同请求重试携带原值。")
WRITE_RESPONSES = {200: ProcessingSourceResponseSerializer, **{
    code: ProcessingErrorResponseSerializer for code in (400, 401, 403, 404, 409, 412, 428)
}}


class MetalProcessingSourceViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, WarehouseActionReadPermission]
    warehouse_read_actions = ('list', 'retrieve', 'options')
    warehouse_read_permissions = ('outsourcing.confirm_return_outsourcingorder', 'material_issues.confirm_metalprocessingexternalreturn',
                                  ORIGINAL_HANDOFF_PERMISSION, REWORK_HANDOFF_PERMISSION)
    serializer_class = ProcessingSourceReadSerializer
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    action_permission_map = {
        "list": "material_issues.view_metalprocessingsource",
        "retrieve": "material_issues.view_metalprocessingsource",
        "options": "material_issues.view_metalprocessingsource",
        "closure_preview": "material_issues.view_metalprocessingsource",
        "completions": "material_issues.register_metalprocessingcompletion",
        "close": "material_issues.close_metalprocessingsource",
        "handoffs": "material_issues.create_metalprocessingoriginalhandoff",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            from ..models import MaterialIssueLine
            return MaterialIssueLine.objects.none()
        if self.action in {'list', 'retrieve', 'closure_preview'}:
            if self.action in self.warehouse_read_actions and warehouse_stage(self.request):
                from ..models import MaterialIssueLine
                return MaterialIssueLine.objects.filter(
                    Q(pk__in=warehouse_original_handoffs(self.request).values('source__issue_line_id'))
                    | Q(pk__in=warehouse_rework_orders(self.request).values('source__issue_line_id')),
                ).select_related('issue__product_line', 'issue__production_task', 'requirement', 'processing_source').order_by('-issue__issued_at', 'issue_id', 'line_number', 'id')
            return readable_processing_lines(self.request)
        return processing_lines(self.request, scoped=self.action not in {'completions', 'close'},
            permission=self.action_permission_map.get(self.action))

    def get_line(self, pk):
        from rest_framework import serializers
        line_id = serializers.UUIDField().run_validation(pk)
        return get_object_or_404(self.get_queryset(), pk=line_id)

    @extend_schema(parameters=[ProcessingSourceFilterSerializer], responses=ProcessingSourceListResponseSerializer)
    def list(self, request):
        filters = ProcessingSourceFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        queryset = self.get_queryset()
        for key, value in filters.validated_data.items():
            if key == "status":
                queryset = queryset.filter(processing_source__status="CLOSED") if value == "CLOSED" else queryset.filter(
                    Q(processing_source__isnull=True) | Q(processing_source__status="OPEN"))
            elif key == "component_identity":
                queryset = queryset.filter(conversion_snapshot__component_identity=str(value))
            elif key == "original_order_id":
                if warehouse_stage(request):
                    queryset = queryset.filter(pk__in=warehouse_original_handoffs(request).filter(original_order_id=value).values('source__issue_line_id'))
                else:
                    require_order_craft(request, 'material_issues.view_metalprocessingsource', value)
                queryset = queryset.filter(processing_source__original_handoffs__original_order_id=value).distinct()
            elif key == "source_id":
                queryset = queryset.filter(processing_source__id=value)
            else:
                queryset = queryset.filter(**{f"issue__{key}" if key != "issue_id" else key: value})
        page = self.paginate_queryset(queryset)
        handoff_ids = set(processing_lines(request, permission=ORIGINAL_HANDOFF_PERMISSION).filter(
            pk__in=[line.pk for line in page]).values_list('pk', flat=True)) if request.user.has_perm(ORIGINAL_HANDOFF_PERMISSION) else set()
        from ..models import MetalProcessingOriginalHandoff
        from apps.outsourcing.selectors import accessible_outsourcing_orders
        related_orders = {}
        for source_line_id, order_id in MetalProcessingOriginalHandoff.objects.filter(
            source__issue_line_id__in=handoff_ids,
            original_order__in=accessible_outsourcing_orders(request, permission=ORIGINAL_HANDOFF_PERMISSION),
        ).values_list('source__issue_line_id', 'original_order_id').distinct():
            related_orders.setdefault(source_line_id, []).append(str(order_id))
        rows = []
        for line in page:
            data = source_data(line)
            data['can_handoff'] = bool(line.pk in handoff_ids and data.get('status') == 'OPEN' and data.get('available_pieces', 0) > 0)
            data['original_handoff_order_ids'] = related_orders.get(line.pk, [])
            rows.append(data)
        return self.get_paginated_response(rows)

    @staticmethod
    def response(data):
        response = Response({"data": data})
        if data.get("etag"):
            response["ETag"] = data["etag"]
        return response

    @extend_schema(responses=ProcessingSourceResponseSerializer)
    def retrieve(self, request, pk=None):
        line = self.get_line(pk)
        source = getattr(line, "processing_source", None)
        return self.response(_source_result(source, line, request) if source and p4_schema_ready() else source_data(line, detail=True))

    @extend_schema(responses=P4SourceResponseSerializer)
    @action(detail=False, methods=["get"])
    def options(self, request):
        from apps.inventory.models import WarehouseType, WarehouseZone
        from apps.organizations.models import Employee
        from apps.outsourcing.models import OutsourcingFactory
        from apps.outsourcing.selectors import accessible_outsourcing_orders, factories_with_context
        from apps.workshop_config.models import Craft

        crafts = Craft.objects.filter(craft_type="EXTERNAL", outsourcing_code="POWDER_COATING", status="ACTIVE")
        crafts = warehouse_crafts(request, crafts) if warehouse_stage(request) else filter_crafts(crafts, request, "material_issues.view_metalprocessingsource", "pk")
        visible_craft_ids = set(crafts.values_list("pk", flat=True))
        factories = factories_with_context(OutsourcingFactory.objects.filter(
            status="ACTIVE", craft_links__craft__in=crafts,
        ).distinct())
        zones = WarehouseZone.objects.filter(status="ACTIVE", warehouse__status="ACTIVE",
            warehouse__warehouse_type=WarehouseType.SEMI_FINISHED).select_related("warehouse")
        receivers = active_department_employees("DEPT_WAREHOUSE")
        orders = accessible_outsourcing_orders(request).filter(craft__in=crafts).exclude(status="CANCELLED")
        if warehouse_stage(request):
            # 仓库只办理已保存交接关系的原单，不提供首次选择来源的候选。
            orders = warehouse_original_dispatch_orders(request).filter(craft__in=crafts).exclude(status__in=['CLOSED', 'COMPLETED', 'CANCELLED'])
        from ..models import MetalProcessingOriginalHandoff
        orders = orders.annotate(has_handoffs=Exists(MetalProcessingOriginalHandoff.objects.filter(original_order_id=OuterRef('pk'))))
        return Response({"data": {
            "crafts": [{"id": str(row.pk), "name": row.name, "outsourcing_code": row.outsourcing_code} for row in crafts],
            "factories": [{"id": str(row.pk), "name": row.name, "crafts": [
                {"id": str(link.craft_id), "name": link.craft_name_snapshot} for link in row.prefetched_craft_links if not enabled() or link.craft_id in visible_craft_ids
            ]} for row in factories],
            "semi_finished_zones": [{"id": str(row.pk), "name": f"{row.warehouse.warehouse_name} / {row.zone_name}"} for row in zones],
            "receivers": [{"id": str(row.pk), "name": row.display_name, "employee_code": row.employee_code} for row in receivers],
            "original_orders": [{"id": str(row.pk), "order_number": row.order_number, "has_handoffs": row.has_handoffs,
                "can_handoff": bool(can_order(request, ORIGINAL_HANDOFF_PERMISSION, row)
                    and row.status in {'PENDING_DISPATCH', 'PROCESSING', 'PARTIAL_RETURN'})} for row in orders.order_by("-created_at", "id")],
            "statuses": [], "defective_zones": [], "bom_confirmation_rule": "LATEST_VERIFIED",
            "material_overage_rule": "SHARED_CONFIRMED_ALLOWANCE",
        }})

    @extend_schema(request=ProcessingCompletionWriteSerializer, responses=WRITE_RESPONSES,
                   parameters=[ETAG_PARAMETER])
    @action(detail=True, methods=["post"])
    def completions(self, request, pk=None):
        return self.write(request, pk, ProcessingCompletionWriteSerializer, "completion")

    @extend_schema(responses=ProcessingSourceResponseSerializer)
    @action(detail=True, methods=["get"], url_path="closure-preview")
    def closure_preview(self, request, pk=None):
        return self.response(source_data(self.get_line(pk), detail=True))

    @extend_schema(request=ProcessingClosureWriteSerializer, responses=WRITE_RESPONSES,
                   parameters=[ETAG_PARAMETER])
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self.write(request, pk, ProcessingClosureWriteSerializer, "close")

    @extend_schema(request=P4OriginalHandoffWriteSerializer, responses=P4SourceResponseSerializer,
                   parameters=[ETAG_PARAMETER])
    @action(detail=True, methods=["post"])
    def handoffs(self, request, pk=None):
        line = self.get_line(pk)
        serializer = P4OriginalHandoffWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.response(create_original_handoff(request=request, issue_line_id=line.pk, **serializer.validated_data))

    def write(self, request, pk, serializer_class, operation):
        line = self.get_line(pk)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.response(record_processing(request=request, issue_line_id=line.pk,
                                                data=serializer.validated_data, operation=operation))
