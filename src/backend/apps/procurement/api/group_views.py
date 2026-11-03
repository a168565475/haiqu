from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.production_tasks.selectors import accessible_production_tasks

from ..group_selectors import purchase_groups_with_context
from ..group_services import complete_purchase_group, create_purchase_batch, create_purchase_group
from ..models import PurchaseGroup
from .group_serializers import (
    PurchaseBatchCreateSerializer, PurchaseGroupCreateSerializer, PurchaseGroupFilterOptionsSerializer,
    PurchaseGroupCompleteSerializer, PurchaseGroupSerializer,
)
from .serializers import PurchaseOrderDetailSerializer


class PurchaseGroupViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "procurement.view_purchaseorder", "retrieve": "procurement.view_purchaseorder",
        "filter_options": "procurement.view_purchaseorder",
        "create": "procurement.add_purchaseorder", "batches": "procurement.add_purchaseorder",
        "complete": "procurement.submit_purchaseorder",
    }
    serializer_class = PurchaseGroupSerializer

    def _task_ids(self):
        return accessible_production_tasks(self.request).filter(archived_at__isnull=True).order_by().values_list("id", flat=True)

    def _accessible_groups(self):
        return PurchaseGroup.objects.filter(production_task_id__in=self._task_ids(), archived_at__isnull=True)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PurchaseGroup.objects.none()
        queryset = self._accessible_groups()
        task_id = self.request.query_params.get("production_task_id")
        if task_id:
            try:
                task_id = UUID(task_id)
            except (ValueError, TypeError) as exc:
                raise ValidationError({"production_task_id": "生产任务参数必须为UUID。"}) from exc
            queryset = queryset.filter(production_task_id=task_id)
        return purchase_groups_with_context(queryset)

    @extend_schema(responses=inline_serializer(
        name="PurchaseGroupFilterOptionsResponse", fields={"data": PurchaseGroupFilterOptionsSerializer()},
    ))
    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        # 选项来自全部可见总单，不依赖当前页、子批次或最新 BOM 是否仍有效。
        groups = self._accessible_groups().order_by("production_task_id", "-created_at", "-id").distinct("production_task_id")
        data = {"production_tasks": [{
            "id": group.production_task_id,
            "task_number": group.production_task_number_snapshot,
            "order_number": group.sales_order_number_snapshot,
        } for group in groups.only("production_task_id", "production_task_number_snapshot", "sales_order_number_snapshot")]}
        return Response({"data": PurchaseGroupFilterOptionsSerializer(data).data})

    def retrieve(self, request, *args, **kwargs):
        group = self.get_object()
        response = Response({"data": PurchaseGroupSerializer(group).data})
        response["ETag"] = etag_for_instance(group)
        return response

    @extend_schema(request=PurchaseGroupCompleteSerializer, responses=inline_serializer(
        name="PurchaseGroupCompleteResponse", fields={"data": PurchaseGroupSerializer()},
    ))
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        group = self.get_object()
        serializer = PurchaseGroupCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = complete_purchase_group(
            group_id=group.pk, remark=serializer.validated_data["remark"], allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request,
        )
        response = Response({"data": PurchaseGroupSerializer(group).data})
        response["ETag"] = etag_for_instance(group)
        return response

    @extend_schema(request=PurchaseGroupCreateSerializer, responses={201: PurchaseGroupSerializer})
    def create(self, request, *args, **kwargs):
        serializer = PurchaseGroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = create_purchase_group(validated_data=serializer.validated_data, allowed_task_ids=self._task_ids(),
                                      actor_employee=request.employee, request=request)
        group = purchase_groups_with_context().get(pk=group.pk)
        response = Response({"data": PurchaseGroupSerializer(group).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(group)
        return response

    @extend_schema(request=PurchaseBatchCreateSerializer, responses={200: PurchaseOrderDetailSerializer, 201: PurchaseOrderDetailSerializer})
    @action(detail=True, methods=["post"])
    def batches(self, request, pk=None):
        group = self.get_object()
        serializer = PurchaseBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, created = create_purchase_batch(group_id=group.pk, validated_data=serializer.validated_data,
            allowed_task_ids=self._task_ids(), actor_employee=request.employee, request=request)
        response = Response({"data": PurchaseOrderDetailSerializer(order).data}, status=201 if created else 200)
        response["ETag"] = etag_for_instance(order)
        return response
