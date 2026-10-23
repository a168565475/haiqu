from rest_framework import serializers
from drf_spectacular.utils import extend_schema_serializer

from apps.core.api.concurrency import etag_for_instance
from .receipt_models import FinanceReceiptUpload, Receipt, ReceiptAccountLine
from .receipt_selectors import used_deposit_allocations


def receipt_file_data(file):
    labels = {"CLEAN": "扫描通过", "SKIPPED": "未扫描（当前配置跳过）", "PENDING": "待扫描", "FAILED": "扫描失败", "INFECTED": "风险文件"}
    return {"file_id": str(file.pk), "original_name": file.original_name,
        "size_bytes": file.size_bytes, "scan_status": file.scan_status, "scan_label": labels[file.scan_status]}


class ReceiptUploadSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(read_only=True)
    statement_id = serializers.UUIDField(read_only=True)
    original_name = serializers.CharField(source="file.original_name", read_only=True)
    size_bytes = serializers.IntegerField(source="file.size_bytes", read_only=True)
    scan_status = serializers.CharField(source="file.scan_status", read_only=True)
    scan_label = serializers.SerializerMethodField()

    class Meta:
        model = FinanceReceiptUpload
        fields = ("id", "file_id", "statement_id", "upload_key", "status", "original_name", "size_bytes", "scan_status", "scan_label", "created_at")

    def get_scan_label(self, obj) -> str:
        return receipt_file_data(obj.file)["scan_label"]


class ReceiptAccountLineSerializer(serializers.ModelSerializer):
    account_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ReceiptAccountLine
        fields = ("id", "account_id", "line_number", "account_snapshot", "cash_amount", "fee_amount", "received_on")


class ReceiptSerializer(serializers.ModelSerializer):
    statement_id = serializers.UUIDField(read_only=True)
    account_lines = ReceiptAccountLineSerializer(many=True, read_only=True)
    attachments = serializers.SerializerMethodField()
    allocations = serializers.SerializerMethodField()
    inherited_attachments = serializers.SerializerMethodField()
    operator = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()
    statement_etag = serializers.SerializerMethodField()
    outstanding_before = serializers.CharField(source="statement_snapshot.outstanding_before", read_only=True)
    outstanding_after = serializers.CharField(source="statement_snapshot.outstanding_after", read_only=True)
    can_void = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    delete_block_reason = serializers.SerializerMethodField()
    blocked_reason = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ("id", "number", "receipt_type", "status", "statement_id", "cash_amount", "fee_amount",
            "deposit_amount", "allocated_deposit_amount", "discount_amount", "settled_amount", "statement_snapshot",
            "outstanding_before", "outstanding_after", "account_lines", "attachments", "allocations", "inherited_attachments",
            "operator", "etag", "statement_etag", "created_at", "updated_at", "void_reason", "voided_at", "can_void", "can_delete", "delete_block_reason", "blocked_reason")

    def get_attachments(self, obj) -> list[dict]:
        return [receipt_file_data(item.file) for item in obj.attachments.all()]

    def allocation_rows(self, obj):
        if not hasattr(obj, "_receipt_allocations"):
            if obj.receipt_type == "GOODS":
                from .allocation_models import DepositAllocation
                obj._receipt_allocations = list(DepositAllocation.objects.filter(goods_receipt=obj)
                    .select_related("deposit_receipt").prefetch_related("deposit_receipt__attachments__file").order_by("pk"))
            else:
                obj._receipt_allocations = []
        return obj._receipt_allocations

    def get_allocations(self, obj) -> list[dict]:
        return [{"id": str(item.pk), "deposit_receipt_id": str(item.deposit_receipt_id),
            "deposit_number": item.deposit_receipt.number, "amount": str(item.amount), "is_active": item.is_active}
            for item in self.allocation_rows(obj)]

    def get_inherited_attachments(self, obj) -> list[dict]:
        return [{**receipt_file_data(attachment.file), "deposit_receipt_id": str(item.deposit_receipt_id),
            "deposit_number": item.deposit_receipt.number} for item in self.allocation_rows(obj)
            for attachment in item.deposit_receipt.attachments.all()]

    def get_operator(self, obj) -> dict:
        actor = obj.created_by_employee
        return {"id": str(actor.pk), "code": actor.employee_code, "name": actor.display_name}

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)

    def get_statement_etag(self, obj) -> str:
        return etag_for_instance(obj.statement)

    def get_can_void(self, obj) -> bool:
        if obj.status != "ACTIVE":
            return False
        if obj.receipt_type == "DEPOSIT":
            if not hasattr(obj, "_deposit_used"):
                obj._deposit_used = used_deposit_allocations(obj.pk).exists()
            return not obj._deposit_used
        return True

    def get_blocked_reason(self, obj) -> str | None:
        if obj.status == "VOID":
            return "收款单已作废。"
        return None if self.get_can_void(obj) else "订金已用于货款，请先作废关联货款。"

    def get_can_delete(self, obj) -> bool:
        return self.get_delete_block_reason(obj) is None

    def get_delete_block_reason(self, obj) -> str | None:
        from .deletion_services import receipt_delete_block_reason
        return receipt_delete_block_reason(obj)


@extend_schema_serializer(component_name="FinanceReceiptResponse")
class ReceiptResponseSerializer(serializers.Serializer):
    data = ReceiptSerializer()


class ReceiptUploadResponseSerializer(serializers.Serializer):
    data = ReceiptUploadSerializer()


class ReceiptPageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class ReceiptPageSerializer(serializers.Serializer):
    data = ReceiptSerializer(many=True)
    meta = ReceiptPageMetaSerializer()


class ReceiptFileSerializer(serializers.Serializer):
    file_id = serializers.UUIDField()
    original_name = serializers.CharField()
    size_bytes = serializers.IntegerField()
    scan_status = serializers.CharField()
    scan_label = serializers.CharField()


class ReceiptDepositOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=["ACTIVE", "VOID"])
    received_on = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()
    deposit_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    available_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    can_select = serializers.BooleanField()
    blocked_reason = serializers.CharField(allow_null=True)
    allocated_goods_id = serializers.UUIDField(allow_null=True)
    allocated_goods_number = serializers.CharField(allow_null=True)
    attachments = ReceiptFileSerializer(many=True)


class ReceiptDepositPageSerializer(serializers.Serializer):
    data = ReceiptDepositOptionSerializer(many=True)
    meta = ReceiptPageMetaSerializer()
    statement_etag = serializers.CharField()
    outstanding_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
    available_deposit_amount = serializers.DecimalField(max_digits=22, decimal_places=2)
