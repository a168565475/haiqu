from decimal import Decimal

from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import MaterialInboundStatus
from apps.inventory.pipe_receipt_basis import is_root_receipt
from .purchase_payable_models import PurchasePayable, PurchasePayableLine, PurchasePayableStatus


class PurchasePayableQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=PurchasePayableStatus.choices, required=False)
    supplier_id = serializers.UUIDField(required=False)
    inbound_date_from = serializers.DateField(required=False)
    inbound_date_to = serializers.DateField(required=False)
    inbound_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)

    def validate(self, attrs):
        start = attrs.get("inbound_date_from")
        end = attrs.get("inbound_date_to")
        if start and end and start > end:
            raise serializers.ValidationError({"inbound_date_to": "入库日期范围的结束日期不能早于开始日期。"})
        return attrs


class PurchasePayablePriceLineSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    line_id = serializers.UUIDField(required=False)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    price_unit = serializers.CharField(max_length=50, required=False, allow_blank=True)
    price_unit_text = serializers.CharField(max_length=50, required=False, allow_blank=True)
    price_source = serializers.CharField(max_length=100, required=False, allow_blank=True)
    price_confirmation_remark = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    price_remark = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    tax_mode = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)
    freight_mode = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)


class PurchasePayablePricingSerializer(serializers.Serializer):
    lines = PurchasePayablePriceLineSerializer(many=True, allow_empty=False)
    tax_mode = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)
    freight_mode = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)

    def validate_lines(self, lines):
        for item in lines:
            if not item.get("id") and not item.get("line_id"):
                raise serializers.ValidationError("每条价格明细必须提供 id。")
            if item.get("id") and item.get("line_id") and item["id"] != item["line_id"]:
                raise serializers.ValidationError("同一明细的 id 与 line_id 不能不一致。")
            if not (item.get("price_unit") or item.get("price_unit_text")):
                raise serializers.ValidationError("每条价格明细必须提供计价单位。")
        line_ids = [item.get("id") or item.get("line_id") for item in lines]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("同一应付明细不能重复提交。")
        return lines


class PurchasePayableVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, allow_blank=False)


class PurchasePayableLineSerializer(serializers.ModelSerializer):
    line_id = serializers.UUIDField(source="id", read_only=True)
    id = serializers.UUIDField(read_only=True)
    inbound_line_id = serializers.UUIDField(source="material_inbound_line_id", read_only=True)
    material_inbound_line_id = serializers.UUIDField(read_only=True)
    purchase_order_line_id = serializers.UUIDField(read_only=True)
    purchase_order_number = serializers.CharField(source="payable.purchase_order_number_snapshot", read_only=True)
    inbound_number = serializers.CharField(source="payable.inbound_number_snapshot", read_only=True)
    supplier_number = serializers.CharField(source="payable.supplier_number_snapshot", read_only=True)
    supplier_name = serializers.CharField(source="payable.supplier_name_snapshot", read_only=True)
    material = serializers.CharField(source="material_snapshot", read_only=True)
    specification = serializers.CharField(source="specification_snapshot", read_only=True)
    part_name = serializers.CharField(source="part_name_snapshot", read_only=True)
    material_attributes = serializers.JSONField(source="material_attributes_snapshot", read_only=True)
    accepted_unit = serializers.CharField(source="source_unit_text_snapshot", read_only=True)
    received_quantity = serializers.SerializerMethodField()
    return_quantity = serializers.SerializerMethodField()
    received_weight_kg = serializers.SerializerMethodField()
    return_weight_kg = serializers.SerializerMethodField()
    accepted_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    accepted_weight_kg = serializers.DecimalField(max_digits=22, decimal_places=4, read_only=True)
    accepted_bar_count = serializers.IntegerField(read_only=True)
    settlement_quantity = serializers.DecimalField(source="accepted_quantity", max_digits=18, decimal_places=4, read_only=True)
    receipt_bar_counts = serializers.SerializerMethodField()
    reference_unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    reference_amount = serializers.DecimalField(max_digits=22, decimal_places=4, read_only=True)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True, read_only=True)
    price_unit = serializers.CharField(source="price_unit_text", allow_blank=True, read_only=True)
    currency_code = serializers.CharField(source="currency_code_snapshot", allow_null=True, read_only=True)
    price_confirmation_remark = serializers.CharField(source="price_remark", read_only=True)
    price_confirmed_by = serializers.SerializerMethodField()
    blocked_reason = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2, allow_null=True, read_only=True)

    class Meta:
        model = PurchasePayableLine
        fields = (
            "line_id", "material_inbound_line_id", "purchase_order_line_id",
            "id", "inbound_line_id", "purchase_order_number", "inbound_number", "supplier_number", "supplier_name",
            "material_snapshot", "specification_snapshot", "part_name_snapshot",
            "material_attributes_snapshot", "source_unit_text_snapshot",
            "material", "specification", "part_name", "material_attributes", "accepted_unit",
            "received_quantity", "return_quantity", "received_weight_kg", "return_weight_kg",
            "accepted_quantity", "accepted_weight_kg", "accepted_bar_count", "settlement_quantity", "receipt_bar_counts",
            "reference_unit_price", "reference_amount", "unit_price", "price_unit_text", "price_unit",
            "currency_code_snapshot", "currency_code", "price_source", "price_confirmed_by_name",
            "price_confirmed_at", "price_remark", "price_confirmation_remark", "price_confirmed_by",
            "tax_mode", "freight_mode", "blocked_reason", "amount",
        )

    def _inbound_line(self, obj):
        return getattr(obj, "material_inbound_line", None)

    def get_receipt_bar_counts(self, obj) -> dict[str, int] | None:
        line = self._inbound_line(obj)
        if is_root_receipt(line):
            return {"received": line.received_bar_count, "returned": line.return_bar_count}
        return None

    def get_received_quantity(self, obj):
        line = self._inbound_line(obj)
        return getattr(line, "received_quantity", None)

    def get_return_quantity(self, obj):
        line = self._inbound_line(obj)
        return getattr(line, "return_quantity", None)

    def get_received_weight_kg(self, obj):
        line = self._inbound_line(obj)
        return getattr(line, "received_weight_kg", None)

    def get_return_weight_kg(self, obj):
        line = self._inbound_line(obj)
        return getattr(line, "return_weight_kg", None)

    def get_price_confirmed_by(self, obj):
        if not obj.price_confirmed_by_name:
            return None
        return {"name": obj.price_confirmed_by_name}

    def get_blocked_reason(self, obj):
        if obj.accepted_quantity == 0:
            return None
        if obj.unit_price is None:
            return "待确认价格。"
        if obj.tax_mode is None or obj.freight_mode is None:
            return "含税和运费口径待确认。"
        return None


class PurchasePayableSerializer(serializers.ModelSerializer):
    supplier = serializers.SerializerMethodField()
    lines = PurchasePayableLineSerializer(many=True, read_only=True)
    supplier_number = serializers.CharField(source="supplier_number_snapshot", read_only=True)
    supplier_name = serializers.CharField(source="supplier_name_snapshot", read_only=True)
    purchase_order_id = serializers.UUIDField(source="material_inbound.purchase_order_id", read_only=True, allow_null=True)
    purchase_order_number = serializers.CharField(source="purchase_order_number_snapshot", read_only=True)
    inbound_id = serializers.UUIDField(source="material_inbound_id", read_only=True)
    inbound_number = serializers.CharField(source="inbound_number_snapshot", read_only=True)
    inbound_date = serializers.DateField(source="material_inbound.inbound_date", read_only=True)
    currency_code = serializers.CharField(source="currency_code_snapshot", read_only=True)
    status_display = serializers.SerializerMethodField()
    confirmed_by = serializers.SerializerMethodField()
    price_complete = serializers.SerializerMethodField()
    blocked_reason = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    can_price = serializers.SerializerMethodField()
    can_confirm = serializers.SerializerMethodField()
    can_void = serializers.SerializerMethodField()

    class Meta:
        model = PurchasePayable
        fields = (
            "id", "number", "material_inbound_id", "supplier", "supplier_number_snapshot",
            "supplier_name_snapshot", "purchase_order_number_snapshot", "inbound_number_snapshot",
            "currency_code_snapshot", "currency_name_snapshot", "status", "status_display", "amount",
            "supplier_number", "supplier_name", "purchase_order_id", "purchase_order_number", "inbound_id",
            "inbound_number", "inbound_date", "currency_code", "price_complete", "blocked_reason",
            "tax_mode", "freight_mode",
            "confirmed_by_employee_id", "confirmed_at", "voided_by_employee_id", "voided_at",
            "confirmed_by", "void_reason", "created_at", "updated_at", "etag", "can_price", "can_confirm",
            "can_void", "lines",
        )

    def get_supplier(self, obj):
        return {"id": str(obj.supplier_id), "number": obj.supplier_number_snapshot,
                "name": obj.supplier_name_snapshot} if obj.supplier_id else None

    def get_status_display(self, obj):
        return obj.get_status_display()

    def get_etag(self, obj):
        return etag_for_instance(obj)

    def get_can_price(self, obj):
        return obj.status in {PurchasePayableStatus.WAITING_PRICE, PurchasePayableStatus.WAITING_FINANCE_CONFIRM}

    def get_can_confirm(self, obj):
        return (obj.status == PurchasePayableStatus.WAITING_FINANCE_CONFIRM
                and obj.material_inbound.status == MaterialInboundStatus.CONFIRMED)

    def get_can_void(self, obj):
        return obj.status in {PurchasePayableStatus.WAITING_PRICE, PurchasePayableStatus.WAITING_FINANCE_CONFIRM}

    def get_confirmed_by(self, obj):
        employee = getattr(obj, "confirmed_by_employee", None)
        if employee is None:
            return None
        return {"id": str(employee.pk), "code": employee.employee_code, "name": employee.display_name}

    def get_price_complete(self, obj):
        lines = [line for line in obj.lines.all() if line.accepted_quantity > 0]
        return bool(lines) and all(line.unit_price is not None and line.amount is not None for line in lines)

    def get_blocked_reason(self, obj):
        if self.get_can_price(obj) and obj.material_inbound.status == MaterialInboundStatus.PENDING_QUALITY:
            return "本批入库仍待质检，可先核价，品质确认后再确认应付。"
        if obj.status == PurchasePayableStatus.WAITING_PRICE:
            return "尚有明细待确认价格。"
        if obj.status == PurchasePayableStatus.WAITING_FINANCE_CONFIRM:
            if not (obj.tax_mode or "").strip() or not (obj.freight_mode or "").strip():
                return "含税和运费口径待确认。"
        return None


class PurchasePayableResponseSerializer(serializers.Serializer):
    data = PurchasePayableSerializer()


class PurchasePayablePageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class PurchasePayablePageSerializer(serializers.Serializer):
    data = PurchasePayableSerializer(many=True)
    meta = PurchasePayablePageMetaSerializer()
