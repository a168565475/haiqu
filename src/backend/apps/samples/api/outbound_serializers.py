from rest_framework import serializers

from ..models import (
    SampleInventoryLine,
    SampleInventoryOutbound,
    SampleInventoryOutboundLine,
    SampleOutboundMethod,
)


class SampleInventoryOutboundLineSerializer(serializers.ModelSerializer):
    outbound_id = serializers.UUIDField(read_only=True)
    outbound_number = serializers.CharField(source="outbound.outbound_number", read_only=True)
    operator_name = serializers.CharField(source="outbound.operated_by_employee.display_name", read_only=True)
    operated_at = serializers.DateTimeField(source="outbound.operated_at", read_only=True)
    sample_request_id = serializers.UUIDField(
        source="inventory_line.sample_item.sample_request_id",
        read_only=True,
    )
    sample_request_number = serializers.CharField(
        source="inventory_line.sample_item.sample_request.request_number",
        read_only=True,
    )
    product_category = serializers.CharField(
        source="inventory_line.category_name_snapshot",
        read_only=True,
    )
    product_name = serializers.CharField(source="inventory_line.product_name_snapshot", read_only=True)
    specification = serializers.CharField(
        source="inventory_line.specification_snapshot",
        read_only=True,
    )
    color = serializers.CharField(source="inventory_line.color_name_snapshot", read_only=True)
    outbound_method_display = serializers.CharField(source="get_outbound_method_display", read_only=True)

    class Meta:
        model = SampleInventoryOutboundLine
        fields = [
            "id",
            "outbound_id",
            "outbound_number",
            "operator_name",
            "operated_at",
            "sample_request_id",
            "sample_request_number",
            "product_category",
            "product_name",
            "specification",
            "color",
            "outbound_quantity",
            "outbound_method",
            "outbound_method_display",
            "courier_company",
            "tracking_number",
            "remark",
        ]


class SampleOutboundSummarySerializer(serializers.Serializer):
    outbound_today = serializers.IntegerField()
    outbound_this_month = serializers.IntegerField()
    mailed = serializers.IntegerField()
    salesperson_carried = serializers.IntegerField()


class SampleOutboundMethodOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class SampleOutboundOptionsSerializer(serializers.Serializer):
    outbound_methods = SampleOutboundMethodOptionSerializer(many=True)
    product_categories = serializers.ListField(child=serializers.CharField())


class SampleOutboundSummaryEnvelopeSerializer(serializers.Serializer):
    data = SampleOutboundSummarySerializer()


class SampleOutboundOptionsEnvelopeSerializer(serializers.Serializer):
    data = SampleOutboundOptionsSerializer()


class SampleOutboundEligibleInventoryLineSerializer(serializers.ModelSerializer):
    inventory_line_id = serializers.UUIDField(source="id", read_only=True)
    receipt_number = serializers.CharField(source="receipt.receipt_number", read_only=True)
    sample_request_number = serializers.CharField(
        source="sample_item.sample_request.request_number",
        read_only=True,
    )
    product_category = serializers.CharField(source="category_name_snapshot", read_only=True)
    product_name = serializers.CharField(source="product_name_snapshot", read_only=True)
    specification = serializers.CharField(source="specification_snapshot", read_only=True)
    color = serializers.CharField(source="color_name_snapshot", read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = SampleInventoryLine
        fields = [
            "inventory_line_id",
            "receipt_number",
            "sample_request_number",
            "product_category",
            "product_name",
            "specification",
            "color",
            "available_quantity",
            "location",
        ]


class SampleOutboundCreateLineSerializer(serializers.Serializer):
    inventory_line_id = serializers.UUIDField()
    outbound_quantity = serializers.IntegerField(min_value=1)
    outbound_method = serializers.ChoiceField(choices=SampleOutboundMethod.choices)
    courier_company = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=150,
    )
    tracking_number = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=150,
    )
    remark = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=500,
    )
    expected_available_quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        method = attrs["outbound_method"]
        courier_company = attrs.get("courier_company", "").strip()
        tracking_number = attrs.get("tracking_number", "").strip()
        remark = attrs.get("remark", "").strip()

        if method == SampleOutboundMethod.MERCHANDISER_MAIL:
            errors = {}
            if not courier_company:
                errors["courier_company"] = "跟单员邮寄时必须填写快递公司。"
            if not tracking_number:
                errors["tracking_number"] = "跟单员邮寄时必须填写快递单号。"
            if errors:
                raise serializers.ValidationError(errors)
            remark = ""
        elif method == SampleOutboundMethod.SALESPERSON_CARRY:
            courier_company = ""
            tracking_number = ""
            remark = ""
        else:
            if not remark:
                raise serializers.ValidationError({"remark": "出库方式为其他时必须填写备注。"})
            courier_company = ""
            tracking_number = ""

        attrs.update(
            courier_company=courier_company,
            tracking_number=tracking_number,
            remark=remark,
        )
        return attrs


class SampleOutboundCreateSerializer(serializers.Serializer):
    items = SampleOutboundCreateLineSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        inventory_line_ids = [item["inventory_line_id"] for item in items]
        if len(inventory_line_ids) != len(set(inventory_line_ids)):
            raise serializers.ValidationError("同一入库批次明细不能重复提交。")
        return items


class SampleOutboundCreatedSerializer(serializers.Serializer):
    outbound_id = serializers.UUIDField()
    outbound_number = serializers.CharField()
    operated_by = serializers.CharField()
    operated_at = serializers.DateTimeField()
    line_count = serializers.IntegerField()


class SampleOutboundDetailLineSerializer(serializers.ModelSerializer):
    inventory_line_id = serializers.UUIDField(read_only=True)
    receipt_id = serializers.UUIDField(source="inventory_line.receipt_id", read_only=True)
    receipt_number = serializers.CharField(
        source="inventory_line.receipt.receipt_number",
        read_only=True,
    )
    sample_request_id = serializers.UUIDField(
        source="inventory_line.sample_item.sample_request_id",
        read_only=True,
    )
    sample_request_number = serializers.CharField(
        source="inventory_line.sample_item.sample_request.request_number",
        read_only=True,
    )
    product_name = serializers.CharField(
        source="inventory_line.product_name_snapshot",
        read_only=True,
    )
    specification = serializers.CharField(
        source="inventory_line.specification_snapshot",
        read_only=True,
    )
    color = serializers.CharField(
        source="inventory_line.color_name_snapshot",
        read_only=True,
    )
    outbound_method_display = serializers.CharField(
        source="get_outbound_method_display",
        read_only=True,
    )

    class Meta:
        model = SampleInventoryOutboundLine
        fields = [
            "id",
            "inventory_line_id",
            "receipt_id",
            "receipt_number",
            "sample_request_id",
            "sample_request_number",
            "product_name",
            "specification",
            "color",
            "outbound_quantity",
            "outbound_method",
            "outbound_method_display",
            "courier_company",
            "tracking_number",
            "remark",
        ]


class SampleOutboundDetailSerializer(serializers.ModelSerializer):
    outbound_id = serializers.UUIDField(source="id", read_only=True)
    document_type = serializers.SerializerMethodField()
    submitted_by = serializers.CharField(source="operated_by_employee.display_name", read_only=True)
    submitted_at = serializers.DateTimeField(source="operated_at", read_only=True)
    operation_source = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    lines = SampleOutboundDetailLineSerializer(source="detail_lines", many=True, read_only=True)

    def get_document_type(self, instance) -> str:
        return "样品出库"

    def get_operation_source(self, instance) -> str:
        return "样品库"

    def get_status(self, instance) -> str:
        return "COMPLETED"

    def get_status_display(self, instance) -> str:
        return "已完成"

    def get_line_count(self, instance) -> int:
        return len(instance.detail_lines)

    class Meta:
        model = SampleInventoryOutbound
        fields = [
            "outbound_id",
            "outbound_number",
            "document_type",
            "submitted_by",
            "submitted_at",
            "operation_source",
            "status",
            "status_display",
            "line_count",
            "lines",
        ]


class SampleOutboundEligibleEnvelopeSerializer(serializers.Serializer):
    data = SampleOutboundEligibleInventoryLineSerializer(many=True)
    meta = serializers.DictField()


class SampleOutboundCreatedEnvelopeSerializer(serializers.Serializer):
    data = SampleOutboundCreatedSerializer()


class SampleOutboundDetailEnvelopeSerializer(serializers.Serializer):
    data = SampleOutboundDetailSerializer()
