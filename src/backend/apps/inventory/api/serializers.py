from decimal import Decimal

from rest_framework import serializers
from django.utils import timezone

from apps.procurement.models import Supplier, SupplierType

from ..models import (
    FinishedGoodsOutbound,
    FinishedGoodsOutboundLine,
    FinishedGoodsReceipt,
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    RecordStatus,
    Warehouse,
    WarehouseLocation,
    WarehouseType,
    WarehouseZone,
)


class WarehouseSerializer(serializers.ModelSerializer):
    warehouse_type_display = serializers.CharField(source="get_warehouse_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    zone_count = serializers.IntegerField(read_only=True, default=0)
    location_count = serializers.IntegerField(read_only=True, default=0)
    capacity_box_slots_total = serializers.IntegerField(read_only=True, allow_null=True)
    occupied_box_slots = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Warehouse
        fields = [
            "id", "warehouse_number", "warehouse_name", "warehouse_type", "warehouse_type_display",
            "address", "status", "status_display", "responsible_person_name", "contact_phone",
            "zone_count", "location_count", "capacity_box_slots_total", "occupied_box_slots",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_warehouse_number(self, value):
        return value.strip().upper()

    def validate_warehouse_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请输入仓库名称。")
        return value


class WarehouseZoneSerializer(serializers.ModelSerializer):
    warehouse_number = serializers.CharField(source="warehouse.warehouse_number", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.warehouse_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    location_count = serializers.IntegerField(read_only=True, default=0)
    capacity_box_slots_total = serializers.IntegerField(read_only=True, allow_null=True)
    occupied_box_slots = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = WarehouseZone
        fields = [
            "id", "warehouse", "warehouse_number", "warehouse_name", "zone_name", "status", "status_display",
            "location_count", "capacity_box_slots_total", "occupied_box_slots", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_zone_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请输入库区名称。")
        return value


class WarehouseLocationSerializer(serializers.ModelSerializer):
    warehouse_id = serializers.UUIDField(source="zone.warehouse_id", read_only=True)
    warehouse_number = serializers.CharField(source="zone.warehouse.warehouse_number", read_only=True)
    warehouse_name = serializers.CharField(source="zone.warehouse.warehouse_name", read_only=True)
    zone_name = serializers.CharField(source="zone.zone_name", read_only=True)
    warehouse_type = serializers.CharField(source="zone.warehouse.warehouse_type", read_only=True)
    warehouse_type_display = serializers.CharField(source="zone.warehouse.get_warehouse_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    unique_key = serializers.CharField(read_only=True)
    occupied_box_slots = serializers.IntegerField(read_only=True, default=0)
    remaining_box_slots = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseLocation
        fields = [
            "id", "zone", "warehouse_id", "warehouse_number", "warehouse_name", "zone_name", "location_number",
            "capacity_box_slots", "unique_key", "warehouse_type", "warehouse_type_display", "status", "status_display",
            "occupied_box_slots", "remaining_box_slots", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_location_number(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError("请输入库位号。")
        if value == "-":
            raise serializers.ValidationError("“-”只代表库区记录，不能作为实际库位号。")
        return value

    def get_remaining_box_slots(self, instance) -> int | None:
        if instance.capacity_box_slots is None:
            return None
        return max(instance.capacity_box_slots - int(instance.occupied_box_slots or 0), 0)


class FinishedGoodsInventoryScopeSerializer(serializers.Serializer):
    exclude_sample = serializers.BooleanField(default=False)
    production_task_id = serializers.UUIDField(required=False, allow_null=True)


class FinishedGoodsReceiptInputSerializer(serializers.Serializer):
    production_task_product_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.filter(is_disabled=False, supplier_type=SupplierType.FINISHED, archived_at__isnull=True),
        required=False,
        allow_null=True,
        default=None,
    )
    expected_received_total = serializers.IntegerField(min_value=0)
    received_quantity = serializers.IntegerField(min_value=1)
    quantity_per_box = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    unit_id = serializers.UUIDField()
    actual_color = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True, default="")
    remark = serializers.CharField(max_length=3000, required=False, allow_blank=True, trim_whitespace=True, default="")


class FinishedGoodsReceiptBatchInputSerializer(serializers.Serializer):
    items = FinishedGoodsReceiptInputSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        line_ids = [item["production_task_product_id"] for item in items]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("同一生产订单产品不能重复入库，请合并数量后提交。")
        return items


class FinishedGoodsReceiptSerializer(serializers.ModelSerializer):
    material_snapshot = serializers.SerializerMethodField()

    def get_material_snapshot(self, instance) -> str:
        return instance.material_snapshot or (instance.production_task_product.material_snapshot if instance.production_task_product_id else "")

    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    supplier_name = serializers.CharField(source="supplier.supplier_name", allow_null=True, read_only=True)
    unit_code = serializers.CharField(source="unit.unit_code", read_only=True)
    unit_name = serializers.CharField(source="unit.unit_name", read_only=True)
    warehouse_id = serializers.UUIDField(source="location.zone.warehouse_id", read_only=True)
    warehouse_number = serializers.CharField(source="location.zone.warehouse.warehouse_number", read_only=True)
    warehouse_name = serializers.CharField(source="location.zone.warehouse.warehouse_name", read_only=True)
    zone_id = serializers.UUIDField(source="location.zone_id", read_only=True)
    zone_name = serializers.CharField(source="location.zone.zone_name", read_only=True)
    location_number = serializers.CharField(source="location.location_number", read_only=True)
    received_by_name = serializers.CharField(source="received_by_employee.display_name", read_only=True)

    class Meta:
        model = FinishedGoodsReceipt
        fields = [
            "id", "receipt_number", "production_task_product_id", "source_type", "source_type_display",
            "source_document_number", "task_number_snapshot", "order_number_snapshot",
            "category_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot",
            "item_number_snapshot", "specification_snapshot", "material_snapshot", "actual_color", "supplier_id", "supplier_name",
            "unit_id", "unit_code", "unit_name", "warehouse_id", "warehouse_number", "warehouse_name", "zone_id",
            "zone_name", "location_id", "location_number", "received_quantity", "remaining_quantity",
            "quantity_per_box", "box_count", "tail_quantity", "occupied_box_slots", "remaining_box_slots", "remark",
            "received_by_name", "received_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class FinishedGoodsOutboundLineInputSerializer(serializers.Serializer):
    receipt_id = serializers.UUIDField()
    expected_remaining_quantity = serializers.IntegerField(min_value=1)
    outbound_quantity = serializers.IntegerField(min_value=1)
    quantity_per_box = serializers.IntegerField(min_value=1)


class FinishedGoodsOutboundInputSerializer(serializers.Serializer):
    receiver_name = serializers.CharField(max_length=150, required=False, allow_blank=True, trim_whitespace=True, default="")
    used_for_order_number = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True, default="")
    remark = serializers.CharField(max_length=3000, required=False, allow_blank=True, trim_whitespace=True, default="")
    responsible_employee_id = serializers.UUIDField()
    shipment_date = serializers.DateField()
    loading_fee = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)
    other_fee = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)
    loading_images = serializers.ListField(child=serializers.FileField(), required=False, max_length=20, write_only=True)
    items = FinishedGoodsOutboundLineInputSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        ids = [item["receipt_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("同一入库批次不能重复出库。")
        return items

    def validate(self, data):
        if "attachment_ids" in self.initial_data:
            raise serializers.ValidationError({"loading_images": "请直接上传本次出库的装卸图片。"})
        return data


class FinishedGoodsOutboundLineSerializer(serializers.ModelSerializer):
    receipt_number = serializers.CharField(source="receipt.receipt_number", read_only=True)
    task_number_snapshot = serializers.CharField(source="receipt.task_number_snapshot", read_only=True)
    product_code_snapshot = serializers.CharField(source="receipt.product_code_snapshot", read_only=True)
    product_number_snapshot = serializers.CharField(source="receipt.product_number_snapshot", read_only=True)
    product_name_snapshot = serializers.CharField(source="receipt.product_name_snapshot", read_only=True)
    item_number_snapshot = serializers.CharField(source="receipt.item_number_snapshot", read_only=True)
    specification_snapshot = serializers.CharField(source="receipt.specification_snapshot", read_only=True)
    actual_color = serializers.CharField(source="receipt.actual_color", read_only=True)
    material_snapshot = serializers.CharField(source="receipt.material_snapshot", read_only=True)
    unit_code = serializers.CharField(source="receipt.unit.unit_code", read_only=True)
    unit_name = serializers.CharField(source="receipt.unit.unit_name", read_only=True)
    order_quantity = serializers.IntegerField(source="receipt.production_task_product.quantity", read_only=True, allow_null=True)
    received_quantity = serializers.IntegerField(source="receipt.received_quantity", read_only=True)
    warehouse_id = serializers.UUIDField(source="receipt.location.zone.warehouse_id", read_only=True)
    warehouse_name = serializers.CharField(source="receipt.location.zone.warehouse.warehouse_name", read_only=True)
    location_number = serializers.CharField(source="receipt.location.location_number", read_only=True)

    class Meta:
        model = FinishedGoodsOutboundLine
        fields = [
            "id", "receipt_id", "receipt_number", "task_number_snapshot", "product_code_snapshot", "product_number_snapshot", "product_name_snapshot",
            "item_number_snapshot", "specification_snapshot", "actual_color", "material_snapshot", "unit_code", "unit_name", "warehouse_name", "location_number",
            "order_quantity", "received_quantity", "warehouse_id", "outbound_quantity", "quantity_per_box", "box_count",
            "tail_quantity", "before_quantity", "after_quantity",
        ]
        read_only_fields = fields


class FinishedGoodsOutboundSerializer(serializers.ModelSerializer):
    outbound_by_name = serializers.CharField(source="outbound_by_employee.display_name", read_only=True)
    responsible_employee_name = serializers.CharField(source="responsible_employee.display_name", read_only=True, allow_null=True)
    lines = FinishedGoodsOutboundLineSerializer(many=True, read_only=True)
    attachments = serializers.SerializerMethodField()
    loading_images = serializers.SerializerMethodField()

    def get_attachments(self, instance) -> list[dict]:
        return [{"id": str(item.business_file_id), "name": item.business_file.original_name,
                 "url": f"/api/v1/finished-goods-inventory/outbounds/{instance.pk}/attachments/{item.business_file_id}/",
                 "content_type": item.business_file.content_type, "size_bytes": item.business_file.size_bytes,
                 "scan_status": item.business_file.scan_status} for item in instance.attachments.all()]

    def get_loading_images(self, instance) -> list[dict]:
        return self.get_attachments(instance)

    class Meta:
        model = FinishedGoodsOutbound
        fields = [
            "id", "outbound_number", "receiver_name", "used_for_order_number", "remark", "responsible_employee_id",
            "responsible_name_snapshot", "responsible_employee_name", "shipment_date", "loading_fee", "other_fee",
            "outbound_by_name", "outbound_at", "lines", "attachments", "loading_images",
        ]
        read_only_fields = fields


class FinishedGoodsOutboundResponseSerializer(serializers.Serializer):
    data = FinishedGoodsOutboundSerializer()


class FinishedGoodsOutboundListDataSerializer(serializers.Serializer):
    items = FinishedGoodsOutboundSerializer(many=True)
    total = serializers.IntegerField()


class FinishedGoodsOutboundListResponseSerializer(serializers.Serializer):
    data = FinishedGoodsOutboundListDataSerializer()


class MaterialInboundLineInputSerializer(serializers.Serializer):
    purchase_order_line_id = serializers.UUIDField()
    received_bar_count = serializers.IntegerField(min_value=1, max_value=99999999999999, required=False)
    raw_bar_length_m = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal('0.01'), required=False)
    zone_id = serializers.UUIDField()
    location_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    expected_remaining_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0"),
    )
    received_quantity = serializers.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    remark = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )


class MaterialInboundInputSerializer(serializers.Serializer):
    inbound_date = serializers.DateField(default=timezone.localdate)
    remark = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )
    items = MaterialInboundLineInputSerializer(many=True, allow_empty=False, max_length=100)


class SampleMaterialInboundLineInputSerializer(serializers.Serializer):
    purchase_order_line_id = serializers.UUIDField()
    zone_id = serializers.UUIDField()
    location_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    remark = serializers.CharField(max_length=3000, required=False, allow_blank=True, default='')

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({'non_field_errors': ['样品全部入库只提交采购明细及库区，不填写数量或长度。']})
        return super().to_internal_value(data)


class SampleMaterialInboundInputSerializer(serializers.Serializer):
    purchase_order_id = serializers.UUIDField()
    client_request_id = serializers.UUIDField()
    inbound_date = serializers.DateField(default=timezone.localdate)
    remark = serializers.CharField(max_length=3000, required=False, allow_blank=True, default='')
    items = SampleMaterialInboundLineInputSerializer(many=True, allow_empty=False, max_length=100)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({'non_field_errors': ['样品全部入库不接受额外的数量或品质参数。']})
        return super().to_internal_value(data)


class ManualMaterialInboundLineInputSerializer(serializers.Serializer):
    raw_material_id = serializers.UUIDField()
    received_bar_count = serializers.IntegerField(min_value=1, max_value=99999999999999, required=False)
    raw_bar_length_m = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal('0.01'), required=False)
    zone_id = serializers.UUIDField()
    location_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    received_quantity = serializers.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    remark = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )


class ManualMaterialInboundInputSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField()
    inbound_date = serializers.DateField()
    remark = serializers.CharField(
        max_length=3000,
        allow_blank=False,
        trim_whitespace=True,
    )
    items = ManualMaterialInboundLineInputSerializer(many=True, allow_empty=False, max_length=100)


class MaterialInboundLineSerializer(serializers.ModelSerializer):
    warehouse_id = serializers.UUIDField(source="zone.warehouse_id", read_only=True)
    warehouse_number = serializers.CharField(source="zone.warehouse.warehouse_number", read_only=True)
    warehouse_name = serializers.CharField(source="zone.warehouse.warehouse_name", read_only=True)
    zone_name = serializers.CharField(source="zone.zone_name", read_only=True)
    location_number = serializers.CharField(source="location.location_number", read_only=True, allow_null=True)

    class Meta:
        model = MaterialInboundLine
        fields = [
            "measurement_kind", "raw_bar_length_m", "received_bar_count", "accepted_bar_count", "return_bar_count", "calculation_snapshot",
            "id", "purchase_order_line_id", "raw_material_information_id", "zone_id", "location_id", "received_quantity",
            "return_quantity", "accepted_quantity", "remark", "quality_remark",
            "purchase_order_number_snapshot", "production_task_number_snapshot", "sales_order_number_snapshot",
            "supplier_number_snapshot", "supplier_name_snapshot", "bom_number_snapshot", "product_name_snapshot",
            "section_type_snapshot", "section_title_snapshot", "category_snapshot", "material_snapshot",
            "part_name_snapshot", "specification_snapshot", "raw_material_snapshot", "source_unit_text_snapshot",
            "material_attributes_snapshot",
            "purchased_quantity_snapshot", "warehouse_id", "warehouse_number", "warehouse_name", "zone_id",
            "zone_name", "location_number", "created_at", "updated_at",
        ]
        read_only_fields = fields


class ProcurementInboundProductSerializer(serializers.Serializer):
    product_line_id = serializers.UUIDField()
    product_name = serializers.CharField(allow_blank=True)
    item_number = serializers.CharField(allow_blank=True)
    specification = serializers.CharField(allow_blank=True)
    color_name = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)


class ProcurementInboundSupplierSerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField(allow_null=True)
    supplier_name = serializers.CharField(allow_blank=True)
    total_amount = serializers.CharField(allow_null=True)


class ProcurementInboundOrderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    source_type = serializers.ChoiceField(choices=["PRODUCTION", "SAMPLE"])
    source_number = serializers.CharField(allow_blank=True)
    sales_order_number = serializers.CharField(allow_blank=True)
    product_summary = ProcurementInboundProductSerializer(many=True)
    supplier_summary = ProcurementInboundSupplierSerializer(many=True)
    currency_code = serializers.CharField(allow_blank=True)
    supplier_names = serializers.ListField(child=serializers.CharField())
    line_count = serializers.IntegerField()
    remaining_line_count = serializers.IntegerField()
    pending_quality_count = serializers.IntegerField()
    confirmed_batch_count = serializers.IntegerField()
    received_quantity = serializers.CharField()
    return_quantity = serializers.CharField()
    return_status = serializers.CharField()
    workflow_status = serializers.CharField()
    workflow_status_display = serializers.CharField()
    updated_at = serializers.DateTimeField()


class ProcurementInboundOrderListResponseSerializer(serializers.Serializer):
    data = ProcurementInboundOrderSerializer(many=True)


class MaterialInboundSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by_employee.display_name", read_only=True)
    quality_confirmed_by_name = serializers.CharField(
        source="quality_confirmed_by_employee.display_name",
        read_only=True,
        allow_null=True,
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    purchase_order_number = serializers.CharField(source="purchase_order.order_number", read_only=True, allow_null=True)
    total_received_quantity = serializers.SerializerMethodField()
    total_return_quantity = serializers.SerializerMethodField()
    total_accepted_quantity = serializers.SerializerMethodField()
    source_type = serializers.SerializerMethodField()
    source_type_display = serializers.SerializerMethodField()
    lines = MaterialInboundLineSerializer(many=True, read_only=True)

    class Meta:
        model = MaterialInbound
        fields = [
            "id", "inbound_number", "source_type", "source_type_display", "purchase_order_id", "purchase_order_number", "inbound_date",
            "status", "status_display", "remark", "received_by_name", "quality_confirmed_by_name",
            "quality_confirmed_at", "total_received_quantity", "total_return_quantity",
            "total_accepted_quantity", "created_at", "updated_at", "lines",
        ]
        read_only_fields = fields

    @staticmethod
    def _sum(instance, field):
        return sum((getattr(line, field) for line in instance.lines.all()), Decimal("0"))

    def get_total_received_quantity(self, instance):
        return f"{self._sum(instance, 'received_quantity'):.4f}"

    def get_total_return_quantity(self, instance):
        return f"{self._sum(instance, 'return_quantity'):.4f}"

    def get_total_accepted_quantity(self, instance):
        return f"{self._sum(instance, 'accepted_quantity'):.4f}"

    @staticmethod
    def get_source_type(instance):
        return "PURCHASE" if instance.purchase_order_id else "MANUAL"

    @staticmethod
    def get_source_type_display(instance):
        return "采购入库" if instance.purchase_order_id else "额外入库"


class SampleMaterialInboundResponseSerializer(serializers.Serializer):
    data = MaterialInboundSerializer()


class MaterialQualityLineInputSerializer(serializers.Serializer):
    line_id = serializers.UUIDField()
    expected_received_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    return_bar_count = serializers.IntegerField(min_value=0, max_value=99999999999999, required=False)
    return_quantity = serializers.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0"),
    )
    quality_remark = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )


class MaterialQualityConfirmationInputSerializer(serializers.Serializer):
    items = MaterialQualityLineInputSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        ids = [item["line_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("同一待检明细不能重复提交。")
        return items
