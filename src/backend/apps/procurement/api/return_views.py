from uuid import UUID

from django.db.models import Count, Prefetch, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.production_tasks.selectors import accessible_production_tasks

from ..completion_services import advance_purchase_return
from ..source_access import purchase_order_access
from ..models import PurchaseReturn, PurchaseReturnLine, PurchaseReturnStatus


class PurchaseReturnLineSerializer(serializers.ModelSerializer):
    return_bar_count = serializers.IntegerField(source='inbound_line.return_bar_count', read_only=True, allow_null=True)
    raw_bar_length_m = serializers.DecimalField(source='inbound_line.raw_bar_length_m', max_digits=18, decimal_places=2, read_only=True, allow_null=True)
    purchase_order_line_id = serializers.UUIDField(source="inbound_line.purchase_order_line_id", read_only=True)
    product_name = serializers.CharField(source="inbound_line.product_name_snapshot", read_only=True)
    material = serializers.CharField(source="inbound_line.material_snapshot", read_only=True)
    part_name = serializers.CharField(source="inbound_line.part_name_snapshot", read_only=True)
    specification = serializers.CharField(source="inbound_line.specification_snapshot", read_only=True)
    material_attributes_snapshot = serializers.JSONField(source="inbound_line.material_attributes_snapshot", read_only=True)
    color = serializers.SerializerMethodField()
    unit = serializers.CharField(source="inbound_line.source_unit_text_snapshot", read_only=True)
    quality_remark = serializers.CharField(source="inbound_line.quality_remark", read_only=True)

    class Meta:
        model = PurchaseReturnLine
        fields = ["id", "inbound_line_id", "purchase_order_line_id", "product_name", "material", "part_name", "specification", "material_attributes_snapshot", "color", "unit", "quantity", "quality_remark", "return_bar_count", "raw_bar_length_m"]
        read_only_fields = fields

    def get_color(self, obj):
        purchase_order_line = obj.inbound_line.purchase_order_line
        return purchase_order_line.color_snapshot if purchase_order_line else ""


class PurchaseReturnSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="purchase_order.order_number", read_only=True)
    production_task_number = serializers.CharField(source="purchase_order.production_task_number_snapshot", read_only=True)
    inbound_number = serializers.CharField(source="inbound.inbound_number", read_only=True)
    supplier_number = serializers.CharField(source="supplier_number_snapshot", read_only=True)
    supplier_name = serializers.CharField(source="supplier_name_snapshot", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    generated_by_name = serializers.CharField(source="generated_by_employee.display_name", read_only=True)
    confirmed_by_name = serializers.CharField(source="confirmed_by_employee.display_name", read_only=True, default="")
    completed_by_name = serializers.CharField(source="completed_by_employee.display_name", read_only=True, default="")
    lines = PurchaseReturnLineSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseReturn
        fields = ["id", "return_number", "purchase_order_id", "order_number", "production_task_number", "inbound_id", "inbound_number", "supplier_id", "supplier_number", "supplier_name", "status", "status_display", "generated_by_name", "confirmed_by_name", "completed_by_name", "created_at", "confirmed_at", "completed_at", "updated_at", "lines"]
        read_only_fields = fields


class PurchaseReturnViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    return_read_permissions = (
        "procurement.view_purchaseorder",
        "inventory.receive_material",
        "inventory.quality_confirm_material",
    )
    action_permission_map = {
        "list": return_read_permissions, "retrieve": return_read_permissions,
        "stats": return_read_permissions, "filter_options": return_read_permissions,
        "confirm": "procurement.submit_purchaseorder", "complete": "procurement.submit_purchaseorder",
    }
    serializer_class = PurchaseReturnSerializer

    def _task_ids(self):
        return accessible_production_tasks(self.request).filter(archived_at__isnull=True).order_by().values_list("id", flat=True)

    def get_queryset(self):
        queryset = PurchaseReturn.objects.filter(
            purchase_order_access(self._task_ids(), self.request, "purchase_order__"), purchase_order__archived_at__isnull=True,
        )
        if self.action in {"list", "retrieve"}:
            queryset = queryset.select_related("purchase_order", "inbound", "generated_by_employee", "confirmed_by_employee", "completed_by_employee").prefetch_related(
                Prefetch("lines", queryset=PurchaseReturnLine.objects.select_related("inbound_line", "inbound_line__purchase_order_line")),
            )
        elif self.action not in {"stats", "filter_options"}:
            # 写操作沿用原查询；读取优化不改变推进状态时的对象和校验。
            queryset = queryset.select_related("purchase_order", "inbound", "generated_by_employee", "confirmed_by_employee", "completed_by_employee").prefetch_related("lines__inbound_line")
        if self.action not in {"list", "stats"}:
            return queryset
        status = self.request.query_params.get("status", "").strip()
        if status:
            if status not in PurchaseReturnStatus.values:
                raise ValidationError({"status": "退货状态不正确。"})
            if self.action == "list":
                queryset = queryset.filter(status=status)
        for field in ["purchase_order_id", "supplier_id"]:
            value = self.request.query_params.get(field, "").strip()
            if value:
                try:
                    value = UUID(value)
                except ValueError as exc:
                    raise ValidationError({field: "编号格式不正确。"}) from exc
                queryset = queryset.filter(**{field: value})
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(Q(return_number__icontains=keyword) | Q(purchase_order__order_number__icontains=keyword) | Q(supplier_name_snapshot__icontains=keyword))
        ordering = self.request.query_params.get("ordering", "-updated_at")
        if ordering not in {"updated_at", "-updated_at"}:
            raise ValidationError({"ordering": "仅支持按更新时间排序。"})
        return queryset.order_by(ordering, "id")

    @action(detail=False, methods=["get"])
    def stats(self, request):
        # 页签统计不受当前页码和状态限制，仍应用关键词、供应商和数据权限。
        counts = self.get_queryset().aggregate(
            total=Count("id"),
            QUALITY_GENERATED=Count("id", filter=Q(status=PurchaseReturnStatus.QUALITY_GENERATED)),
            PROCUREMENT_CONFIRMED=Count("id", filter=Q(status=PurchaseReturnStatus.PROCUREMENT_CONFIRMED)),
            COMPLETED=Count("id", filter=Q(status=PurchaseReturnStatus.COMPLETED)),
        )
        return Response({"data": counts})

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        # 每家供应商只取可见退货单中最新的名称快照，避免泄露其他业务范围的供应商。
        records = self.get_queryset().order_by("supplier_id", "-updated_at", "id").distinct("supplier_id").values(
            "supplier_id", "supplier_number_snapshot", "supplier_name_snapshot",
        )
        suppliers = [{"id": row["supplier_id"], "supplier_number": row["supplier_number_snapshot"],
                      "supplier_name": row["supplier_name_snapshot"]} for row in records]
        return Response({"data": {"suppliers": suppliers}})

    def retrieve(self, request, *args, **kwargs):
        record = self.get_object()
        response = Response({"data": self.get_serializer(record).data})
        response["ETag"] = etag_for_instance(record)
        return response

    def _advance(self, request, target_status):
        record = self.get_object()
        advance_purchase_return(
            return_id=record.pk, target_status=target_status, allowed_task_ids=self._task_ids(),
            actor_employee=request.employee, request=request,
        )
        return self.retrieve(request)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._advance(request, PurchaseReturnStatus.PROCUREMENT_CONFIRMED)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._advance(request, PurchaseReturnStatus.COMPLETED)
