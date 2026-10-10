from uuid import UUID

from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.permissions import HasActiveEmployee
from apps.boms.models import Bom, BomStatus
from apps.production_tasks.models import ProductionTaskStatus
from apps.production_tasks.selectors import accessible_production_tasks

from ..models import (
    PurchaseAllocationStatus,
    PurchaseContractTemplate,
    PurchaseContractTemplateStatus,
    PurchaseRequest,
    PurchaseRequestAllocation,
    PurchaseRequestLine,
    PurchaseRequestStatus,
    SupplierPurchaseSheet,
    Supplier,
)
from ..purchase_sheet_services import generate_supplier_purchase_sheet_from_request
from ..purchase_request_services import (
    allocate_purchase_request_line,
    cancel_purchase_allocation,
    create_purchase_request,
    purchase_requests_with_context,
    submit_purchase_request,
    update_purchase_request,
)
from .purchase_request_serializers import (
    PurchaseAllocationCancelSerializer,
    PurchaseAllocationCreateSerializer,
    PurchaseRequestAllocationSerializer,
    PurchaseRequestCreateSerializer,
    PurchaseRequestSerializer,
    PurchaseRequestUpdateSerializer,
    SupplierOrderGenerateSerializer,
)
from .serializers import SupplierPurchaseSheetSerializer


class PurchaseRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasActiveEmployee]

    def get_permissions(self):
        from apps.access_control import module_policy
        from apps.core.api.permissions import BusinessActionPermission
        permissions = super().get_permissions()
        if module_policy.enabled():
            permissions.append(BusinessActionPermission())
        return permissions
    serializer_class = PurchaseRequestSerializer

    def get_serializer_class(self):
        return {
            "create": PurchaseRequestCreateSerializer,
            "partial_update": PurchaseRequestUpdateSerializer,
            "allocate": PurchaseAllocationCreateSerializer,
            "cancel_allocation": PurchaseAllocationCancelSerializer,
            "generate_supplier_order": SupplierOrderGenerateSerializer,
        }.get(self.action, PurchaseRequestSerializer)

    def get_queryset(self):
        task_ids = accessible_production_tasks(self.request).values("id")
        queryset = PurchaseRequest.objects.filter(
            production_task_id__in=task_ids,
            archived_at__isnull=True,
        )
        requested_status = self.request.query_params.get("status", "").strip().upper()
        if requested_status:
            if requested_status not in PurchaseRequestStatus.values:
                raise ValidationError({"status": "采购申请状态参数不正确。"})
            queryset = queryset.filter(status=requested_status)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(request_number__icontains=keyword)
                | Q(production_task__task_number__icontains=keyword)
                | Q(production_task__order_number__icontains=keyword)
                | Q(lines__material_snapshot__icontains=keyword)
            ).distinct()
        return purchase_requests_with_context(queryset)

    def _response(self, purchase_request, response_status=status.HTTP_200_OK):
        current = purchase_requests_with_context(self.get_queryset().filter(pk=purchase_request.pk)).get()
        response = Response({"data": PurchaseRequestSerializer(current).data}, status=response_status)
        response["ETag"] = etag_for_instance(current)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = PurchaseRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bom = serializer.validated_data["bom"]
        if not accessible_production_tasks(request).filter(pk=bom.production_task_id).exists():
            raise NotFound("BOM 不存在或当前账号不可访问。")
        purchase_request = create_purchase_request(
            bom=bom,
            actor_employee=request.employee,
            request=request,
        )
        return self._response(purchase_request, status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def options(self, request, *args, **kwargs):
        task_ids = accessible_production_tasks(request).values_list("id", flat=True)
        eligible_boms = Bom.objects.filter(
            production_task_id__in=task_ids,
            production_task__status__in=[
                ProductionTaskStatus.READY,
                ProductionTaskStatus.IN_PRODUCTION,
                ProductionTaskStatus.PAUSED,
                ProductionTaskStatus.COMPLETED,
            ],
            status=BomStatus.VERIFIED,
            archived_at__isnull=True,
            purchase_request__isnull=True,
        ).select_related("production_task", "product_line").order_by("-updated_at", "-id")[:500]
        suppliers = Supplier.objects.filter(archived_at__isnull=True, is_disabled=False).order_by(
            "supplier_number", "id"
        )[:1000]
        return Response({"data": {
            "statuses": [{"value": value, "label": label} for value, label in PurchaseRequestStatus.choices],
            "eligible_boms": [{
                "id": str(item.pk),
                "bom_number": item.bom_number,
                "production_task_id": str(item.production_task_id),
                "production_task_number": item.production_task.task_number,
                "product_name": item.product_line.product_name_snapshot,
            } for item in eligible_boms],
            "suppliers": [{
                "id": str(item.pk),
                "supplier_number": item.supplier_number,
                "supplier_name": item.supplier_name,
            } for item in suppliers],
        }})

    def partial_update(self, request, *args, **kwargs):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = PurchaseRequestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase_request = update_purchase_request(
            purchase_request=current,
            line_values=serializer.validated_data["lines"],
            actor_employee=request.employee,
            request=request,
        )
        return self._response(purchase_request)

    @action(detail=True, methods=["post"])
    def submit(self, request, *args, **kwargs):
        purchase_request = submit_purchase_request(
            purchase_request=self.get_object(),
            actor_employee=request.employee,
            request=request,
        )
        return self._response(purchase_request)

    @action(detail=True, methods=["post"])
    def allocate(self, request, *args, **kwargs):
        current = self.get_object()
        serializer = PurchaseAllocationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = serializer.validated_data.pop("purchase_request_line")
        if line.purchase_request_id != current.pk:
            raise ValidationError({"purchase_request_line_id": "申请行不属于当前采购申请。"})
        allocation, purchase_request = allocate_purchase_request_line(
            line=line,
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        response = Response({"data": PurchaseRequestAllocationSerializer(allocation).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(purchase_request)
        return response

    @action(detail=True, methods=["post"], url_path="cancel-allocation")
    def cancel_allocation(self, request, *args, **kwargs):
        current = self.get_object()
        serializer = PurchaseAllocationCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocation = serializer.validated_data["allocation"]
        if allocation.purchase_request_line.purchase_request_id != current.pk:
            raise ValidationError({"allocation_id": "分配记录不属于当前采购申请。"})
        allocation, purchase_request = cancel_purchase_allocation(
            allocation=allocation,
            reason=serializer.validated_data["reason"],
            actor_employee=request.employee,
            request=request,
        )
        response = Response({"data": PurchaseRequestAllocationSerializer(allocation).data})
        response["ETag"] = etag_for_instance(purchase_request)
        return response

    @action(detail=True, methods=["get"], url_path="supplier-order-options")
    def supplier_order_options(self, request, *args, **kwargs):
        current = self.get_object()
        groups = {}
        allocations = PurchaseRequestAllocation.objects.filter(
            purchase_request_line__purchase_request=current,
            status=PurchaseAllocationStatus.DRAFT,
            supplier_purchase_sheet__isnull=True,
        ).select_related("supplier", "purchase_request_line")
        for item in allocations:
            key = (item.supplier_id, item.procurement_batch_number)
            group = groups.setdefault(
                key,
                {
                    "supplier_id": str(item.supplier_id),
                    "supplier_number": item.supplier.supplier_number,
                    "supplier_name": item.supplier.supplier_name,
                    "procurement_batch_number": item.procurement_batch_number,
                    "line_count": 0,
                    "total_quantity": 0,
                },
            )
            group["line_count"] += 1
            group["total_quantity"] += item.quantity
        templates = []
        for template in PurchaseContractTemplate.objects.filter(
            status=PurchaseContractTemplateStatus.ACTIVE,
            archived_at__isnull=True,
        ).prefetch_related("versions").order_by("template_code", "id"):
            version = next(
                (value for value in template.versions.all() if value.version_number == template.current_version_number),
                None,
            )
            if version:
                templates.append({
                    "template_id": str(template.pk),
                    "template_code": template.template_code,
                    "template_name": template.template_name,
                    "template_version_id": str(version.pk),
                    "template_version_number": version.version_number,
                })
        rows = list(groups.values())
        for row in rows:
            row["total_quantity"] = format(row["total_quantity"], "f")
        return Response({"data": {"groups": rows, "templates": templates}})

    @action(detail=True, methods=["post"], url_path="generate-supplier-order")
    def generate_supplier_order(self, request, *args, **kwargs):
        current = self.get_object()
        serializer = SupplierOrderGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sheet = generate_supplier_purchase_sheet_from_request(
            purchase_request=current,
            supplier=serializer.validated_data["supplier"],
            procurement_batch_number=serializer.validated_data["procurement_batch_number"],
            template_version=serializer.validated_data["template_version"],
            allowed_task_ids=accessible_production_tasks(request).values_list("id", flat=True),
            actor_employee=request.employee,
            request=request,
        )
        sheet = SupplierPurchaseSheet.objects.select_related(
            "purchase_request__production_task__sales_order",
            "supplier",
            "template_version__template",
            "updated_by_employee",
            "created_by_employee",
        ).prefetch_related("line_images__image_file").get(pk=sheet.pk)
        response = Response({"data": SupplierPurchaseSheetSerializer(sheet).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(sheet)
        return response
