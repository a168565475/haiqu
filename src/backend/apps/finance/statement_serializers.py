import re
from decimal import Decimal

from rest_framework import serializers

from .serializers import TextField
from .source_selectors import ALLOWED_TASK_STATUSES
from .statement_models import ReceivableStatement
from apps.core.api.concurrency import etag_for_instance


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("请求必须是JSON对象。")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: "不支持此字段。" for field in sorted(unknown)})
        return super().to_internal_value(data)


class UnitPriceField(serializers.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"), **kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?", data):
            raise serializers.ValidationError("单价须为正数十进制字符串，最多4位小数，不支持指数。")
        return super().to_internal_value(data)


class StatementLineWriteSerializer(StrictSerializer):
    production_task_product_id = serializers.UUIDField()
    unit_price = UnitPriceField()


class StatementWriteSerializer(StrictSerializer):
    production_task_id = serializers.UUIDField()
    source_revision = serializers.RegexField(r"^[0-9a-f]{64}$")
    acknowledge_salesperson_change = serializers.BooleanField(default=False)
    lines = StatementLineWriteSerializer(many=True, allow_empty=False, max_length=1000)

    def validate_lines(self, values):
        if len({line["production_task_product_id"] for line in values}) != len(values):
            raise serializers.ValidationError("同一来源产品行不能重复选择。")
        return values


class StatementVoidSerializer(StrictSerializer):
    reason = TextField(max_length=500)


class StatementQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    task_id = serializers.UUIDField(required=False)
    salesperson_id = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=("ACTIVE", "VOID"), required=False)
    settlement_status = serializers.ChoiceField(choices=("UNSETTLED", "PARTIAL", "SETTLED"), required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class SourceQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=ALLOWED_TASK_STATUSES, required=False)
    salesperson_id = serializers.UUIDField(required=False)
    mode = serializers.ChoiceField(choices=("statement", "receipt"), default="statement")
    editing_statement_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class StatementSerializer(serializers.ModelSerializer):
    production_task_id = serializers.UUIDField(read_only=True)
    task_number = serializers.CharField(source="task_number_snapshot", read_only=True)
    salesperson = serializers.SerializerMethodField()
    operator = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()
    quantity_totals = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_void = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    delete_block_reason = serializers.SerializerMethodField()
    blocked_reason = serializers.SerializerMethodField()
    settled_amount = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)
    outstanding_amount = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)
    available_deposit_amount = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)
    bank_received_amount = serializers.DecimalField(max_digits=22, decimal_places=2, read_only=True)
    settlement_status = serializers.CharField(read_only=True)

    class Meta:
        model = ReceivableStatement
        fields = ("id", "number", "production_task_id", "task_number", "source_order_date", "salesperson", "operator",
                  "source_revision", "statement_revision", "status", "amount", "created_at", "updated_at", "etag",
                  "lines", "quantity_totals", "can_edit", "can_void", "can_delete", "delete_block_reason", "blocked_reason", "void_reason", "voided_at",
                  "settled_amount", "discount_amount", "outstanding_amount", "available_deposit_amount", "bank_received_amount", "settlement_status")

    def to_representation(self, instance):
        from .settlement_selectors import settlement_summary
        totals = self.context["totals"][instance.pk]
        result = super().to_representation(instance)
        result.update(settlement_summary(totals))
        return result

    def get_salesperson(self, obj) -> dict:
        return {"id": str(obj.salesperson_id), "code": obj.salesperson_code_snapshot, "name": obj.salesperson_name_snapshot}

    def get_operator(self, obj) -> dict:
        return {"id": str(obj.created_by_employee_id), "code": obj.created_by_employee.employee_code, "name": obj.created_by_employee.display_name}

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)

    def get_can_edit(self, obj) -> bool:
        return obj.status == "ACTIVE" and not obj.has_active_receipts

    def get_can_void(self, obj) -> bool:
        return self.get_can_edit(obj)

    def get_can_delete(self, obj) -> bool:
        return self.get_delete_block_reason(obj) is None

    def get_delete_block_reason(self, obj) -> str | None:
        from .deletion_services import statement_delete_block_reason
        return statement_delete_block_reason(obj)

    def get_blocked_reason(self, obj) -> str | None:
        if obj.status == "VOID":
            return "对账单已作废"
        return "有效收款已冻结对账单" if obj.has_active_receipts else None

    def get_lines(self, obj) -> list[dict]:
        fields = ("item_number_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot", "specification_snapshot")
        return [{"id": str(line.pk), "production_task_product_id": str(line.production_task_product_id),
                 "line_number": line.line_number, "statement_revision": line.statement_revision,
                 **{field: getattr(line, field) for field in fields}, "unit_code": line.unit_code_snapshot,
                 "unit_name": line.unit_name_snapshot, "quantity": str(line.quantity),
                 "reference_unit_price_cny": str(line.reference_unit_price_cny), "unit_price": str(line.unit_price), "amount": str(line.amount)}
                for line in getattr(obj, "current_lines", [])]

    def get_quantity_totals(self, obj) -> list[dict]:
        totals = {}
        for line in getattr(obj, "current_lines", []):
            group = totals.setdefault(line.unit_code_snapshot, {"unit_code": line.unit_code_snapshot, "unit_name": line.unit_name_snapshot, "quantity": 0})
            group["quantity"] += line.quantity
        return [{**group, "quantity": str(group["quantity"])} for group in totals.values()]


class StatementResponseSerializer(serializers.Serializer):
    data = StatementSerializer()
