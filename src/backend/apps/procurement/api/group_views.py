from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control import module_policy, sales_policy
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.production_tasks.selectors import accessible_production_tasks

from ..group_selectors import purchase_groups_with_context
from ..group_services import (
    complete_purchase_group, confirm_purchase_batch_page, create_purchase_batch, create_purchase_group,
    delete_purchase_group, submit_supplier_purchase_batch,
)
from ..models import PurchaseGroup, PurchaseScope
from .group_serializers import (
    PurchaseBatchCreateSerializer, PurchaseBatchPageConfirmSerializer, PurchaseGroupCreateSerializer, PurchaseGroupFilterOptionsSerializer,
    PurchaseGroupBatchPageQuerySerializer, PurchaseGroupCompleteSerializer, PurchaseGroupSerializer,
    PurchaseSupplierBatchSubmitSerializer,
)
from .serializers import PurchaseOrderDetailSerializer


supplier_batch_response = inline_serializer(name="PurchaseSupplierBatchSubmitResponse", fields={
    "data": inline_serializer(name="SubmittedPurchaseSupplierBatch", fields={
        "order_id": serializers.UUIDField(),
        "batch_number": serializers.IntegerField(),
        "group": PurchaseGroupSerializer(),
    }),
})


class PurchaseGroupRecordViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    purchase_scope = PurchaseScope.STANDARD
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = PurchaseGroupSerializer

    def _task_ids(self):
        return accessible_production_tasks(self.request).filter(archived_at__isnull=True).order_by().values_list("id", flat=True)

    def _accessible_groups(self):
        return PurchaseGroup.objects.filter(
            production_task_id__in=self._task_ids(), archived_at__isnull=True, purchase_scope=self.purchase_scope,
        )

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
        if self.action in {"submit_supplier_batch", "confirm_batch_page"}:
            return queryset.only("id")
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

    @extend_schema(parameters=[PurchaseGroupBatchPageQuerySerializer])
    def retrieve(self, request, *args, **kwargs):
        group = self.get_object()
        query = PurchaseGroupBatchPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        response = Response({"data": PurchaseGroupSerializer(group, context=query.validated_data).data})
        response["ETag"] = etag_for_instance(group)
        return response

    @extend_schema(
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
        responses={
            204: None,
            403: OpenApiResponse(description="无删除权限、员工无效或 CSRF 校验失败。"),
            404: OpenApiResponse(description="采购需求不存在或不在当前账号的数据范围内。"),
            409: OpenApiResponse(description="已有确认采购或后续业务记录，不能删除。"),
            412: OpenApiResponse(description="采购需求版本已变化，请重新读取并确认。"),
            428: OpenApiResponse(description="缺少 If-Match 版本标识。"),
        },
    )
    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        delete_purchase_group(
            group_id=group.pk, allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

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

class PurchaseGroupViewSet(PurchaseGroupRecordViewSet):
    action_permission_map = {
        "list": "procurement.view_purchaseorder", "retrieve": "procurement.view_purchaseorder",
        "filter_options": "procurement.view_purchaseorder",
        "create": "procurement.add_purchaseorder", "batches": "procurement.add_purchaseorder",
        "submit_supplier_batch": "procurement.submit_purchaseorder",
        "confirm_batch_page": "procurement.submit_purchaseorder",
        "complete": "procurement.submit_purchaseorder",
        "destroy": "procurement.delete_purchaseorder",
    }

    @extend_schema(request=PurchaseGroupCreateSerializer, responses={201: PurchaseGroupSerializer})
    def create(self, request, *args, **kwargs):
        serializer = PurchaseGroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = create_purchase_group(
            validated_data=serializer.validated_data, allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request, purchase_scope=self.purchase_scope,
        )
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

    @extend_schema(
        request=PurchaseSupplierBatchSubmitSerializer,
        parameters=[
            OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True),
            OpenApiParameter("ETag", str, OpenApiParameter.HEADER, response=[200, 201], description="采购需求当前版本"),
        ],
        responses={
            200: supplier_batch_response, 201: supplier_batch_response,
            400: OpenApiResponse(description="采购明细或默认采购模板无效。"),
            403: OpenApiResponse(description="缺少采购权限、员工无效或 CSRF 校验失败。"),
            409: OpenApiResponse(description="采购来源、当前状态或请求编号冲突。"),
            412: OpenApiResponse(description="采购需求版本已变化。"),
            428: OpenApiResponse(description="缺少 If-Match 版本标识。"),
        },
    )
    @action(detail=True, methods=["post"], url_path="submit-supplier-batch")
    def submit_supplier_batch(self, request, pk=None):
        self._require_supplier_submit_permissions(request)
        group = self.get_object()
        serializer = PurchaseSupplierBatchSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, group, created = submit_supplier_purchase_batch(
            group_id=group.pk, validated_data=serializer.validated_data, allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request,
        )
        context = {"batch_session_id": order.batch_session_id} if serializer.validated_data.get("save_as_draft") else {}
        response = Response({"data": {
            "order_id": order.pk, "batch_number": order.batch_number, "group": PurchaseGroupSerializer(group, context=context).data,
        }}, status=201 if created else 200)
        response["ETag"] = etag_for_instance(group)
        return response

    @extend_schema(
        request=PurchaseBatchPageConfirmSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
        responses={200: inline_serializer(name="ConfirmedPurchaseBatchPage", fields={"data": PurchaseGroupSerializer()})},
    )
    @action(detail=True, methods=["post"], url_path="confirm-batch-page")
    def confirm_batch_page(self, request, pk=None):
        self._require_supplier_submit_permissions(request)
        group = self.get_object()
        serializer = PurchaseBatchPageConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = confirm_purchase_batch_page(
            group_id=group.pk, validated_data=serializer.validated_data, allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request,
        )
        response = Response({"data": PurchaseGroupSerializer(group, context=serializer.validated_data).data})
        response["ETag"] = etag_for_instance(group)
        return response

    @staticmethod
    def _require_supplier_submit_permissions(request):
        permissions = ["procurement.add_purchaseorder", "procurement.view_purchaseorder"]
        has_permission = sales_policy.has_permission
        if module_policy.enabled():
            has_permission = module_policy.has_permission
            permissions.append("access_control.generate_purchasesheets")
        if not all(has_permission(request, code) for code in permissions):
            raise PermissionDenied("当前账号缺少按供应商提交采购所需的权限。")
