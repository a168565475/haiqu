from rest_framework import serializers

from ..models import SampleInventoryLine, SampleInventoryLoan, SampleInventoryLoanLine


class SampleInventoryLoanLineSerializer(serializers.ModelSerializer):
    loan_id = serializers.UUIDField(read_only=True)
    loan_number = serializers.CharField(source="loan.loan_number", read_only=True)
    operator_name = serializers.CharField(source="loan.operated_by_employee.display_name", read_only=True)
    operated_at = serializers.DateTimeField(source="loan.operated_at", read_only=True)
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
    specification = serializers.CharField(source="inventory_line.specification_snapshot", read_only=True)
    color = serializers.CharField(source="inventory_line.color_name_snapshot", read_only=True)

    class Meta:
        model = SampleInventoryLoanLine
        fields = [
            "id",
            "loan_id",
            "loan_number",
            "operator_name",
            "operated_at",
            "sample_request_id",
            "sample_request_number",
            "product_category",
            "product_name",
            "specification",
            "color",
            "loan_quantity",
            "borrower_name",
            "purpose_note",
        ]


class SampleLoanSummarySerializer(serializers.Serializer):
    active_documents = serializers.IntegerField()
    cumulative_borrowed = serializers.IntegerField()
    customer_confirmation = serializers.IntegerField()
    showroom_or_photo = serializers.IntegerField()


class SampleLoanOptionsSerializer(serializers.Serializer):
    borrower_names = serializers.ListField(child=serializers.CharField())
    product_categories = serializers.ListField(child=serializers.CharField())


class SampleLoanSummaryEnvelopeSerializer(serializers.Serializer):
    data = SampleLoanSummarySerializer()


class SampleLoanOptionsEnvelopeSerializer(serializers.Serializer):
    data = SampleLoanOptionsSerializer()


class SampleLoanEligibleInventoryLineSerializer(serializers.ModelSerializer):
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


class SampleLoanCreateLineSerializer(serializers.Serializer):
    inventory_line_id = serializers.UUIDField()
    loan_quantity = serializers.IntegerField(min_value=1)
    borrower_name = serializers.CharField(max_length=150, allow_blank=False, trim_whitespace=True)
    purpose_note = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)
    expected_available_quantity = serializers.IntegerField(min_value=1)


class SampleLoanCreateSerializer(serializers.Serializer):
    items = SampleLoanCreateLineSerializer(many=True, allow_empty=False, max_length=100)

    def validate_items(self, items):
        inventory_line_ids = [item["inventory_line_id"] for item in items]
        if len(inventory_line_ids) != len(set(inventory_line_ids)):
            raise serializers.ValidationError("同一入库批次明细不能重复提交。")
        return items


class SampleLoanCreatedSerializer(serializers.Serializer):
    loan_id = serializers.UUIDField()
    loan_number = serializers.CharField()
    operated_by = serializers.CharField()
    operated_at = serializers.DateTimeField()
    line_count = serializers.IntegerField()


class SampleLoanDetailLineSerializer(serializers.ModelSerializer):
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
    inventory_impact = serializers.SerializerMethodField()

    def get_inventory_impact(self, instance) -> str:
        return f"可用库存 -{instance.loan_quantity}"

    class Meta:
        model = SampleInventoryLoanLine
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
            "loan_quantity",
            "borrower_name",
            "purpose_note",
            "inventory_impact",
        ]


class SampleLoanDetailSerializer(serializers.ModelSerializer):
    loan_id = serializers.UUIDField(source="id", read_only=True)
    document_type = serializers.SerializerMethodField()
    submitted_by = serializers.CharField(source="operated_by_employee.display_name", read_only=True)
    submitted_at = serializers.DateTimeField(source="operated_at", read_only=True)
    operation_source = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    inventory_status_display = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    lines = SampleLoanDetailLineSerializer(source="detail_lines", many=True, read_only=True)

    def get_document_type(self, instance) -> str:
        return "样品借出"

    def get_operation_source(self, instance) -> str:
        return "样品库"

    def get_status(self, instance) -> str:
        return "ACTIVE"

    def get_status_display(self, instance) -> str:
        return "借出中"

    def get_inventory_status_display(self, instance) -> str:
        return "库存占用中"

    def get_line_count(self, instance) -> int:
        return len(instance.detail_lines)

    class Meta:
        model = SampleInventoryLoan
        fields = [
            "loan_id",
            "loan_number",
            "document_type",
            "submitted_by",
            "submitted_at",
            "operation_source",
            "status",
            "status_display",
            "inventory_status_display",
            "line_count",
            "lines",
        ]


class SampleLoanEligibleEnvelopeSerializer(serializers.Serializer):
    data = SampleLoanEligibleInventoryLineSerializer(many=True)
    meta = serializers.DictField()


class SampleLoanCreatedEnvelopeSerializer(serializers.Serializer):
    data = SampleLoanCreatedSerializer()


class SampleLoanDetailEnvelopeSerializer(serializers.Serializer):
    data = SampleLoanDetailSerializer()
