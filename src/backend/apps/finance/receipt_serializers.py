import re
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .receipt_exceptions import ReceiptInputError, ReceiptValidationError


class StrictReceiptSerializer(serializers.Serializer):
    def is_valid(self, *, raise_exception=False):
        try:
            if hasattr(self, "_receipt_input_error"):
                raise self._receipt_input_error
            return super().is_valid(raise_exception=raise_exception)
        except ReceiptInputError as exc:
            self._receipt_input_error = exc
            self._validated_data = {}
            self._errors = exc.detail if isinstance(exc.detail, (dict, list)) else {"non_field_errors": [exc.detail]}
            if raise_exception:
                raise ReceiptValidationError(exc.api_error_code, self._errors, meta=exc.error_meta) from exc
            return False

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("请求必须是 JSON 对象。")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ReceiptInputError("RECEIPT_TYPE_FIELDS_INVALID", {name: "当前收款类型不支持此字段。" for name in sorted(unknown)})
        return super().to_internal_value(data)


@extend_schema_field({"type": "string", "pattern": r"^[0-9]+(?:\.[0-9]{1,2})?$", "example": "100.00"})
class ReceiptMoneyField(serializers.Field):
    def __init__(self, *, positive=False, **kwargs):
        self.positive = positive
        super().__init__(**kwargs)

    def to_internal_value(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
            raise serializers.ValidationError("请输入非负十进制金额字符串，最多两位小数。")
        if len(value.partition(".")[0].lstrip("0")) > 20:
            raise ReceiptInputError("AMOUNT_OUT_OF_RANGE", {self.field_name: "金额超出允许范围。"},
                meta={"field": self.field_name, "max_amount": "99999999999999999999.99", "recovery_action": "REVIEW_AMOUNTS"})
        result = Decimal(value)
        if self.positive and result <= 0:
            raise serializers.ValidationError("到账金额必须大于零。")
        return result.quantize(Decimal("0.01"))

    def to_representation(self, value):
        return format(value, ".2f")


class ReceiptAccountListSerializer(serializers.ListSerializer):
    def to_internal_value(self, data):
        self._receipt_row_index = 0
        return super().to_internal_value(data)

    def run_child_validation(self, data):
        index = self._receipt_row_index
        self._receipt_row_index += 1
        try:
            return super().run_child_validation(data)
        except ReceiptInputError as exc:
            prefix = f"account_lines.{index}"
            detail = {f"{prefix}.{field}": value for field, value in exc.detail.items()} if isinstance(exc.detail, dict) else {prefix: exc.detail}
            meta = {**(exc.error_meta or {}), "row_index": index}
            if meta.get("field"):
                meta["field"] = f"{prefix}.{meta['field']}"
            raise ReceiptInputError(exc.api_error_code, detail, meta=meta) from exc


class ReceiptAccountInputSerializer(StrictReceiptSerializer):
    account_id = serializers.UUIDField()
    account_etag = serializers.CharField(max_length=66)
    cash_amount = ReceiptMoneyField(positive=True)
    fee_amount = ReceiptMoneyField()
    received_on = serializers.DateField()

    class Meta:
        list_serializer_class = ReceiptAccountListSerializer


class ReceiptCreateSerializer(StrictReceiptSerializer):
    receipt_type = serializers.ChoiceField(choices=["DEPOSIT", "GOODS"])
    statement_id = serializers.UUIDField()
    account_lines = ReceiptAccountInputSerializer(many=True, allow_empty=True)
    upload_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
    deposit_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    discount_amount = ReceiptMoneyField(required=False)

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get("receipt_type") == "DEPOSIT":
            forbidden = set(data) & {"deposit_ids", "discount_amount", "deposit_amount", "settled_amount"}
            if forbidden:
                raise ReceiptInputError("RECEIPT_TYPE_FIELDS_INVALID", {name: "订金不能提交此字段。" for name in sorted(forbidden)})
        return super().to_internal_value(data)

    def validate(self, data):
        for field in ("upload_ids", "deposit_ids"):
            values = data.get(field, [])
            if len(set(values)) != len(values):
                raise serializers.ValidationError({field: "不能重复选择同一记录。"})
        if data["receipt_type"] == "DEPOSIT" and not data["account_lines"]:
            raise ReceiptInputError("FUNDS_REQUIRED", {"account_lines": "订金必须有实际到账。"})
        if data["receipt_type"] == "GOODS":
            data.setdefault("deposit_ids", [])
            data.setdefault("discount_amount", Decimal("0.00"))
        return data


class ReceiptVoidSerializer(StrictReceiptSerializer):
    reason = serializers.CharField(max_length=500, allow_blank=False)


class ReceiptQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    receipt_type = serializers.ChoiceField(choices=["DEPOSIT", "GOODS"], required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "VOID"], required=False)
    statement_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class ReceiptUploadInputSerializer(serializers.Serializer):
    statement_id = serializers.UUIDField()
    upload_key = serializers.UUIDField()
    file = serializers.FileField()


class ReceiptUploadQuerySerializer(serializers.Serializer):
    statement_id = serializers.UUIDField()


class ReceiptDepositQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    include_unavailable = serializers.BooleanField(default=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)
