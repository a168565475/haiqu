from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .supplier_ledger_serializers import SupplierLedgerOptionSerializer
from .supplier_settlement_models import SupplierPayment


class SettlementCreateSerializer(serializers.Serializer):
    replaces_id = serializers.UUIDField(required=False)


class SupplierPaymentCreateSerializer(SettlementCreateSerializer):
    supplier_id = serializers.UUIDField()
    account_id = serializers.UUIDField()
    nature = serializers.ChoiceField(choices=SupplierPayment.Nature.choices)
    paid_on = serializers.DateField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2, min_value=Decimal("0.01"))
    payee = serializers.CharField(max_length=255)
    voucher = serializers.CharField(max_length=255)

    def validate_paid_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("实际付款日期不能晚于今天。")
        return value


class SupplierAllocationInputSerializer(serializers.Serializer):
    payable_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2, min_value=Decimal("0.01"))


class SupplierPaymentRegistrationSerializer(SupplierPaymentCreateSerializer):
    application_id = serializers.UUIDField(required=False)


class SupplierOffsetCreateSerializer(SettlementCreateSerializer):
    payment_id = serializers.UUIDField()
    offset_on = serializers.DateField()
    allocations = SupplierAllocationInputSerializer(many=True, allow_empty=False, max_length=100)

    def validate_allocations(self, rows):
        if len({row["payable_id"] for row in rows}) != len(rows):
            raise serializers.ValidationError("同一张应付单只能分配一次。")
        return rows


class SettlementVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class SettlementDocumentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    business_date = serializers.DateField()
    status = serializers.CharField()
    status_display = serializers.CharField(source="get_status_display")
    recorded_by_name = serializers.CharField(source="recorded_by.display_name")
    voided_by_name = serializers.CharField(source="voided_by.display_name", allow_null=True)
    voided_at = serializers.DateTimeField(allow_null=True)
    void_reason = serializers.CharField()
    replaces_id = serializers.UUIDField(allow_null=True)
    replaces_number = serializers.CharField(source="replaces.number", allow_null=True)
    replacement_id = serializers.UUIDField(source="replacement.id", allow_null=True)
    replacement_number = serializers.CharField(source="replacement.number", allow_null=True)


class SupplierPaymentSerializer(SettlementDocumentSerializer):
    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField(source="supplier_name_snapshot")
    nature = serializers.ChoiceField(choices=SupplierPayment.Nature.choices)
    nature_display = serializers.CharField(source="get_nature_display")
    account_id = serializers.UUIDField()
    account_name = serializers.CharField(source="account_snapshot.name")
    payee = serializers.CharField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    available_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    voucher = serializers.CharField()


class OffsetAllocationSerializer(serializers.Serializer):
    payable_id = serializers.UUIDField()
    payable_number = serializers.CharField(source="payable.number")
    amount = serializers.DecimalField(max_digits=22, decimal_places=2)


class SupplierOffsetSerializer(SettlementDocumentSerializer):
    payment_id = serializers.UUIDField()
    payment_number = serializers.CharField(source="payment.number")
    supplier_name = serializers.CharField(source="payment.supplier_name_snapshot")
    allocations = OffsetAllocationSerializer(many=True)


class PaymentAccountOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    etag = serializers.CharField()


class PaymentOptionsSerializer(serializers.Serializer):
    suppliers = SupplierLedgerOptionSerializer(many=True)
    accounts = PaymentAccountOptionSerializer(many=True)


class PaymentPickSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    business_date = serializers.DateField()
    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField(source="supplier_name_snapshot")
    nature_display = serializers.CharField(source="get_nature_display")
    available_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    etag = serializers.CharField()


class PayablePickQuerySerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()


class PayablePickSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    inbound_date = serializers.DateField(source="material_inbound.inbound_date")
    confirmed_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    available_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
