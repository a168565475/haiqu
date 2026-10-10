from decimal import Decimal

from rest_framework import serializers

from apps.boms.models import Bom

from ..models import (
    PurchaseAllocationStatus,
    PurchaseRequest,
    PurchaseRequestAllocation,
    PurchaseRequestLine,
    PurchaseRequestStatus,
    Supplier,
    PurchaseContractTemplateVersion,
)


class PurchaseRequestAllocationSerializer(serializers.ModelSerializer):
    supplier_number = serializers.CharField(source="supplier.supplier_number", read_only=True)
    supplier_name = serializers.CharField(source="supplier.supplier_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PurchaseRequestAllocation
        fields = [
            "id",
            "supplier_id",
            "supplier_number",
            "supplier_name",
            "procurement_batch_number",
            "quantity",
            "expected_arrival_date",
            "status",
            "status_display",
            "supplier_purchase_sheet_id",
            "created_at",
        ]


class PurchaseRequestLineSerializer(serializers.ModelSerializer):
    suggested_supplier_number = serializers.CharField(source="suggested_supplier.supplier_number", read_only=True, allow_null=True)
    suggested_supplier_name = serializers.CharField(source="suggested_supplier.supplier_name", read_only=True, allow_null=True)
    allocated_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    allocations = PurchaseRequestAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequestLine
        fields = [
            "id",
            "line_number",
            "bom_line_id",
            "material_snapshot",
            "specification_snapshot",
            "unit_snapshot",
            "gross_requirement_quantity",
            "actual_request_quantity",
            "difference_reason",
            "required_date",
            "suggested_supplier_id",
            "suggested_supplier_number",
            "suggested_supplier_name",
            "allocated_quantity",
            "remaining_quantity",
            "allocations",
        ]

    def get_allocated_quantity(self, instance):
        return format(Decimal(instance.allocated_quantity), "f")

    def get_remaining_quantity(self, instance):
        return format(Decimal(instance.remaining_quantity), "f")


class PurchaseRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    production_task_number = serializers.CharField(source="production_task.task_number", read_only=True)
    sales_order_number = serializers.CharField(source="production_task.sales_order.order_number", read_only=True, allow_null=True)
    delivery_batch_number = serializers.CharField(source="sales_order_delivery_batch.batch_number", read_only=True, allow_null=True)
    bom_number = serializers.CharField(source="bom.bom_number", read_only=True)
    requested_by_name = serializers.CharField(source="requested_by_employee.display_name", read_only=True, allow_null=True)
    lines = PurchaseRequestLineSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequest
        fields = [
            "id",
            "request_number",
            "production_task_id",
            "production_task_number",
            "sales_order_delivery_batch_id",
            "sales_order_number",
            "delivery_batch_number",
            "bom_id",
            "bom_number",
            "status",
            "status_display",
            "gross_requirement_notice",
            "requested_by_name",
            "submitted_at",
            "lines",
            "created_at",
            "updated_at",
        ]


class PurchaseRequestCreateSerializer(serializers.Serializer):
    bom_id = serializers.PrimaryKeyRelatedField(
        source="bom",
        queryset=Bom.objects.filter(archived_at__isnull=True),
    )


class PurchaseRequestLineUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    actual_request_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    difference_reason = serializers.CharField(required=False, allow_blank=True)
    required_date = serializers.DateField()
    suggested_supplier_id = serializers.PrimaryKeyRelatedField(
        source="suggested_supplier",
        queryset=Supplier.objects.filter(archived_at__isnull=True, is_disabled=False),
        required=False,
        allow_null=True,
    )


class PurchaseRequestUpdateSerializer(serializers.Serializer):
    lines = PurchaseRequestLineUpdateSerializer(many=True, allow_empty=False)


class PurchaseAllocationCreateSerializer(serializers.Serializer):
    purchase_request_line_id = serializers.PrimaryKeyRelatedField(
        source="purchase_request_line",
        queryset=PurchaseRequestLine.objects.all(),
    )
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.filter(archived_at__isnull=True, is_disabled=False),
    )
    procurement_batch_number = serializers.CharField(max_length=100)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    expected_arrival_date = serializers.DateField()


class PurchaseAllocationCancelSerializer(serializers.Serializer):
    allocation_id = serializers.PrimaryKeyRelatedField(
        source="allocation",
        queryset=PurchaseRequestAllocation.objects.all(),
    )
    reason = serializers.CharField(max_length=500)


class SupplierOrderGenerateSerializer(serializers.Serializer):
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.filter(archived_at__isnull=True, is_disabled=False),
    )
    procurement_batch_number = serializers.CharField(max_length=100)
    template_version_id = serializers.PrimaryKeyRelatedField(
        source="template_version",
        queryset=PurchaseContractTemplateVersion.objects.filter(
            template__archived_at__isnull=True,
            template__status="ACTIVE",
        ),
    )
