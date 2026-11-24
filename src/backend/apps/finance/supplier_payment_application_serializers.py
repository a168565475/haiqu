from decimal import Decimal

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.api.fields import CalendarMonthField


class SupplierApplicationLineInputSerializer(serializers.Serializer):
    payable_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2, min_value=Decimal("0.01"))


class SupplierApplicationCreateSerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    applied_on = serializers.DateField(default=timezone.localdate)
    payee = serializers.CharField(max_length=255)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    lines = SupplierApplicationLineInputSerializer(many=True, allow_empty=False)

    def validate_applied_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("申请日期不能晚于今天。")
        return value

    def validate(self, data):
        lines = data["lines"]
        if len({line["payable_id"] for line in lines}) != len(lines):
            raise serializers.ValidationError({"lines": "同一张采购应付只能选择一次。"})
        total = sum(line["amount"] for line in lines)
        if total >= Decimal("1e22"):
            raise serializers.ValidationError({"lines": "申请合计超出可保存金额范围。"})
        return {**data, "amount": total}


class SupplierApplicationPayablesQuerySerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    due_through_month = CalendarMonthField(required=False)


class SupplierApplicationPayableSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    inbound_date = serializers.DateField(source="material_inbound.inbound_date")
    confirmed_amount = serializers.DecimalField(max_digits=22, decimal_places=2, source="amount")
    offset_amount = serializers.DecimalField(max_digits=22, decimal_places=2, source="allocated_amount")
    current_balance = serializers.DecimalField(max_digits=22, decimal_places=2, source="available_amount")
    occupied_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    requestable_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    payment_term_months = serializers.IntegerField(allow_null=True)
    due_month = CalendarMonthField(allow_null=True)


class SupplierDuePayableDetailSerializer(SupplierApplicationPayableSerializer):
    receipt_month = CalendarMonthField(source="material_inbound.inbound_date")


class SupplierDuePayablesSummarySerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField(source="supplier__supplier_name")
    overdue_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    current_due_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    due_total = serializers.DecimalField(max_digits=30, decimal_places=2)


class SupplierApplicationMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    current_balance = serializers.DecimalField(max_digits=30, decimal_places=2)
    occupied_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    requestable_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    payables = SupplierApplicationPayableSerializer(many=True)


class SupplierApplicationRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    applied_on = serializers.DateField()
    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField(source="supplier_name_snapshot")
    payee = serializers.CharField()
    amount = serializers.DecimalField(max_digits=24, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=24, decimal_places=2)
    remaining_amount = serializers.DecimalField(max_digits=24, decimal_places=2)
    recorded_by_name = serializers.CharField(source="recorded_by_name_snapshot")
    withdrawn_at = serializers.DateTimeField(allow_null=True)


class SupplierApplicationLineSerializer(serializers.Serializer):
    payable_id = serializers.UUIDField()
    payable_number = serializers.CharField()
    inbound_date = serializers.DateField()
    month = serializers.SerializerMethodField()
    confirmed_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    offset_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    released_amount = serializers.DecimalField(max_digits=22, decimal_places=2)

    @extend_schema_field(OpenApiTypes.STR)
    def get_month(self, row):
        return row.inbound_date.strftime("%Y-%m")


class SupplierApplicationPaymentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    business_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2)


class SupplierApplicationDetailSerializer(SupplierApplicationRowSerializer):
    department_name = serializers.CharField(source="department_name_snapshot")
    note = serializers.CharField()
    withdrawal_reason = serializers.CharField()
    lines = SupplierApplicationLineSerializer(many=True)
    payments = SupplierApplicationPaymentSerializer(many=True, source="active_payments")
