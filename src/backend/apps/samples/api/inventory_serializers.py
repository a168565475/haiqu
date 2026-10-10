from rest_framework import serializers

from ..models import SampleInventoryLine, SampleInventoryReceipt, SampleItem, SampleRequestStatus


class SampleInventoryLineSerializer(serializers.ModelSerializer):
    receipt_id = serializers.UUIDField(read_only=True)
    receipt_number = serializers.CharField(source="receipt.receipt_number", read_only=True)
    inbound_time = serializers.DateTimeField(source="receipt.submitted_at", read_only=True)
    operator_name = serializers.CharField(source="receipt.submitted_by_employee.display_name", read_only=True)
    sample_request_id = serializers.UUIDField(source="sample_item.sample_request_id", read_only=True)
    sample_request_number = serializers.CharField(source="sample_item.sample_request.request_number", read_only=True)
    product_category = serializers.CharField(source="category_name_snapshot", read_only=True)
    product_name = serializers.CharField(source="product_name_snapshot", read_only=True)
    specification = serializers.CharField(source="specification_snapshot", read_only=True)
    color = serializers.CharField(source="color_name_snapshot", read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = SampleInventoryLine
        fields = [
            "id",
            "receipt_id",
            "receipt_number",
            "inbound_time",
            "operator_name",
            "sample_request_id",
            "sample_request_number",
            "product_category",
            "product_name",
            "specification",
            "color",
            "sampling_quantity",
            "received_quantity",
            "outbound_quantity",
            "loaned_quantity",
            "available_quantity",
            "location",
        ]


class SampleInventorySummarySerializer(serializers.Serializer):
    current_available = serializers.IntegerField()
    borrowed = serializers.IntegerField()
    inbound_today = serializers.IntegerField()
    outbound_today = serializers.IntegerField()


class SampleInventoryOptionsSerializer(serializers.Serializer):
    product_categories = serializers.ListField(child=serializers.CharField())
    locations = serializers.ListField(child=serializers.CharField())


class SampleInventorySummaryEnvelopeSerializer(serializers.Serializer):
    data = SampleInventorySummarySerializer()


class SampleInventoryOptionsEnvelopeSerializer(serializers.Serializer):
    data = SampleInventoryOptionsSerializer()


class SampleInventoryEligibleItemSerializer(serializers.ModelSerializer):
    sample_item_id = serializers.UUIDField(source="id", read_only=True)
    sample_request_number = serializers.CharField(source="sample_request.request_number", read_only=True)
    flow_condition = serializers.SerializerMethodField()
    product_category = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()
    specification = serializers.SerializerMethodField()
    color = serializers.CharField(source="color_name_snapshot", read_only=True)
    sampling_quantity = serializers.IntegerField(source="sample_quantity", read_only=True)
    cumulative_received = serializers.IntegerField(read_only=True)
    remaining_quantity = serializers.IntegerField(read_only=True)

    def get_flow_condition(self, instance) -> str:
        if instance.sample_request.application_payload_hash:
            return "材料齐备✓ 参数齐全✓ 金工✓ 裁剪✓"
        return "PMC✓ 金工✓ 裁剪✓"

    def get_product_category(self, instance) -> str:
        return instance.sample_product.category_name_snapshot if instance.sample_product else ""

    def get_product_name(self, instance) -> str:
        return instance.sample_product.product_name if instance.sample_product else instance.product_description_snapshot

    def get_specification(self, instance) -> str:
        if instance.specification_snapshot:
            return instance.specification_snapshot
        return instance.sample_product.specification if instance.sample_product else ""

    class Meta:
        model = SampleItem
        fields = [
            "sample_item_id",
            "sample_request_number",
            "flow_condition",
            "product_category",
            "product_name",
            "specification",
            "color",
            "sampling_quantity",
            "cumulative_received",
            "remaining_quantity",
        ]


class SampleInventoryReceiptLineInputSerializer(serializers.Serializer):
    sample_item_id = serializers.UUIDField()
    received_quantity = serializers.IntegerField(min_value=1)
    location = serializers.CharField(max_length=150, allow_blank=False, trim_whitespace=True)
    expected_cumulative_received = serializers.IntegerField(min_value=0)


class SampleFinishedGoodsDestinationSerializer(serializers.Serializer):
    warehouse_id = serializers.UUIDField()
    zone_id = serializers.UUIDField()
    location_id = serializers.UUIDField()


class SampleInventoryReceiptCreateSerializer(serializers.Serializer):
    items = SampleInventoryReceiptLineInputSerializer(many=True, allow_empty=False, max_length=100)
    finished_goods_destination = SampleFinishedGoodsDestinationSerializer()

    def validate_items(self, items):
        item_ids = [item["sample_item_id"] for item in items]
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError("同一条样品明细不能重复提交。")
        return items


class SampleInventoryReceiptCreatedSerializer(serializers.Serializer):
    receipt_id = serializers.UUIDField()
    receipt_number = serializers.CharField()
    submitted_by = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    line_count = serializers.IntegerField()


class SampleInventoryReceiptDetailLineSerializer(serializers.ModelSerializer):
    sample_item_id = serializers.UUIDField(read_only=True)
    sample_request_id = serializers.UUIDField(source="sample_item.sample_request_id", read_only=True)
    sample_request_number = serializers.CharField(
        source="sample_item.sample_request.request_number",
        read_only=True,
    )
    product_category = serializers.CharField(source="category_name_snapshot", read_only=True)
    product_name = serializers.CharField(source="product_name_snapshot", read_only=True)
    specification = serializers.CharField(source="specification_snapshot", read_only=True)
    color = serializers.CharField(source="color_name_snapshot", read_only=True)
    cumulative_received = serializers.IntegerField(read_only=True)
    flow_condition = serializers.SerializerMethodField()
    source_status = serializers.SerializerMethodField()
    finished_goods_receipt_number = serializers.SerializerMethodField()
    finished_goods_warehouse = serializers.SerializerMethodField()
    finished_goods_zone = serializers.SerializerMethodField()
    finished_goods_location = serializers.SerializerMethodField()

    def get_flow_condition(self, instance) -> str:
        if instance.sample_item.sample_request.application_payload_hash:
            return "新版打样：参数及生产完成后入库"
        pmc = "PMC✓" if instance.has_pmc_approval else "PMC—"
        metalwork = "金工✓" if instance.sample_item.metalwork_completed else "金工—"
        cutting = "裁剪✓" if instance.sample_item.cutting_completed else "裁剪—"
        return f"{pmc} {metalwork} {cutting}"

    def get_source_status(self, instance) -> str:
        is_finished = (
            instance.sample_item.sample_request.status == SampleRequestStatus.FINISHED
            and instance.has_finished_workflow
        )
        return "流程已结束" if is_finished else "流程未结束"

    def _finished_receipt(self, instance):
        return getattr(instance, "finished_goods_receipt", None)

    def get_finished_goods_receipt_number(self, instance) -> str:
        receipt = self._finished_receipt(instance)
        return receipt.receipt_number if receipt else ""

    def get_finished_goods_warehouse(self, instance) -> str:
        receipt = self._finished_receipt(instance)
        return receipt.location.zone.warehouse.warehouse_name if receipt else ""

    def get_finished_goods_zone(self, instance) -> str:
        receipt = self._finished_receipt(instance)
        return receipt.location.zone.zone_name if receipt else ""

    def get_finished_goods_location(self, instance) -> str:
        receipt = self._finished_receipt(instance)
        return receipt.location.location_number if receipt else ""

    class Meta:
        model = SampleInventoryLine
        fields = [
            "id",
            "sample_item_id",
            "sample_request_id",
            "sample_request_number",
            "product_category",
            "product_name",
            "specification",
            "color",
            "sampling_quantity",
            "received_quantity",
            "cumulative_received",
            "location",
            "flow_condition",
            "source_status",
            "finished_goods_receipt_number",
            "finished_goods_warehouse",
            "finished_goods_zone",
            "finished_goods_location",
        ]


class SampleInventoryReceiptDetailSerializer(serializers.ModelSerializer):
    receipt_id = serializers.UUIDField(source="id", read_only=True)
    document_type = serializers.SerializerMethodField()
    submitted_by = serializers.CharField(source="submitted_by_employee.display_name", read_only=True)
    operation_source = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    lines = SampleInventoryReceiptDetailLineSerializer(source="detail_lines", many=True, read_only=True)

    def get_document_type(self, instance) -> str:
        return "样品入库"

    def get_operation_source(self, instance) -> str:
        return "样品库"

    def get_status(self, instance) -> str:
        return "COMPLETED"

    def get_status_display(self, instance) -> str:
        return "已完成"

    def get_line_count(self, instance) -> int:
        return len(instance.detail_lines)

    class Meta:
        model = SampleInventoryReceipt
        fields = [
            "receipt_id",
            "receipt_number",
            "document_type",
            "submitted_by",
            "submitted_at",
            "operation_source",
            "status",
            "status_display",
            "line_count",
            "lines",
        ]


class SampleInventoryEligibleEnvelopeSerializer(serializers.Serializer):
    data = SampleInventoryEligibleItemSerializer(many=True)
    meta = serializers.DictField()


class SampleInventoryReceiptCreatedEnvelopeSerializer(serializers.Serializer):
    data = SampleInventoryReceiptCreatedSerializer()


class SampleInventoryReceiptDetailEnvelopeSerializer(serializers.Serializer):
    data = SampleInventoryReceiptDetailSerializer()
