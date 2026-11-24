from datetime import date

from django.utils import timezone
from rest_framework import serializers



def current_month():
    return timezone.localdate().strftime("%Y-%m")


class SupplierLedgerQuerySerializer(serializers.Serializer):
    month = serializers.RegexField(r"^[0-9]{4}-(0[1-9]|1[0-2])$", default=current_month)
    supplier_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.ChoiceField(choices=(20, 50, 100), required=False)

    def validate_month(self, value):
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise serializers.ValidationError("请输入有效月份。") from exc
        return value


class SupplierLedgerEntryQuerySerializer(SupplierLedgerQuerySerializer):
    supplier_id = serializers.UUIDField()


class SupplierLedgerSummarySerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField()
    supplier_number = serializers.CharField()
    opening_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    current_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    offset_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    closing_amount = serializers.DecimalField(max_digits=30, decimal_places=2)
    unused_prepayment = serializers.DecimalField(max_digits=30, decimal_places=2)
    pending_count = serializers.IntegerField()


class SupplierLedgerEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    entry_kind = serializers.ChoiceField(choices=("PAYABLE", "PAYMENT", "OFFSET"))
    type_display = serializers.CharField()
    business_date = serializers.DateField()
    document_id = serializers.UUIDField(default=None, allow_null=True)
    payable_id = serializers.UUIDField(default=None, allow_null=True)
    number = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    amount = serializers.DecimalField(max_digits=22, decimal_places=2, allow_null=True, default=None)
    paid_amount = serializers.DecimalField(max_digits=22, decimal_places=2, allow_null=True, default=None)
    offset_amount = serializers.DecimalField(max_digits=22, decimal_places=2, allow_null=True, default=None)
    inbound_date = serializers.DateField(default=None, allow_null=True)
    confirmed_date = serializers.DateField(default=None, allow_null=True)
    confirmed_by = serializers.CharField(default="")
    purchase_order_id = serializers.UUIDField(default=None, allow_null=True)
    purchase_order_number = serializers.CharField(default="")
    inbound_id = serializers.UUIDField(default=None, allow_null=True)
    inbound_number = serializers.CharField(default="")
    production_task_id = serializers.UUIDField(default=None, allow_null=True)
    production_task_number = serializers.CharField(default="")
    material = serializers.CharField(default="")
    specification = serializers.CharField(default="")
    quantity = serializers.DecimalField(max_digits=22, decimal_places=4, allow_null=True, default=None)
    unit = serializers.CharField(default="")
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True, default=None)


class SupplierLedgerPageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class SupplierLedgerSummaryPageSerializer(serializers.Serializer):
    data = SupplierLedgerSummarySerializer(many=True)
    meta = SupplierLedgerPageMetaSerializer()


class SupplierLedgerEntryMetaSerializer(SupplierLedgerPageMetaSerializer):
    supplier_name = serializers.CharField()


class SupplierLedgerEntryPageSerializer(serializers.Serializer):
    data = SupplierLedgerEntrySerializer(many=True)
    meta = SupplierLedgerEntryMetaSerializer()


class SupplierLedgerOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    supplier_name = serializers.CharField()
    supplier_number = serializers.CharField()


class SupplierLedgerOptionsResponseSerializer(serializers.Serializer):
    data = SupplierLedgerOptionSerializer(many=True)
