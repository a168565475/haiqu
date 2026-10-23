from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class Receipt(TimeStampedModel):
    class Type(models.TextChoices):
        DEPOSIT = "DEPOSIT", "订金"
        GOODS = "GOODS", "货款"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "有效"
        VOID = "VOID", "已作废"

    number = models.CharField(max_length=50, unique=True)
    statement = models.ForeignKey("finance.ReceivableStatement", on_delete=models.PROTECT, related_name="receipts")
    receipt_type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    cash_amount = models.DecimalField(max_digits=22, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    allocated_deposit_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    settled_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    statement_snapshot = models.JSONField(default=dict)
    void_reason = models.CharField(max_length=500, blank=True)
    voided_by = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "finance_receipt"
        ordering = ["-created_at", "-id"]
        default_permissions = ("add", "view", "delete")
        permissions = [("void_receipt", "Can void receipt")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["ACTIVE", "VOID"]), name="finance_receipt_status_valid"),
            models.CheckConstraint(condition=Q(cash_amount__gte=0, fee_amount__gte=0, deposit_amount__gte=0,
                allocated_deposit_amount__gte=0, discount_amount__gte=0, settled_amount__gte=0), name="finance_receipt_amounts_positive"),
            models.CheckConstraint(condition=(
                Q(receipt_type="DEPOSIT", cash_amount__gt=0, deposit_amount=F("cash_amount"),
                  allocated_deposit_amount=0, discount_amount=0, settled_amount=0)
                | (Q(receipt_type="GOODS", deposit_amount=0, settled_amount=F("cash_amount") + F("allocated_deposit_amount"))
                   & (Q(cash_amount__gt=0) | Q(allocated_deposit_amount__gt=0)))
            ), name="finance_receipt_type_amounts"),
            models.CheckConstraint(condition=(Q(status="ACTIVE", voided_at__isnull=True, voided_by__isnull=True, void_reason="")
                | (Q(status="VOID", voided_at__isnull=False, voided_by__isnull=False) & ~Q(void_reason=""))),
                name="finance_receipt_void_fields"),
        ]


class ReceiptAccountLine(UUIDPrimaryKeyModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name="account_lines")
    account = models.ForeignKey("finance.FinanceAccount", on_delete=models.PROTECT, related_name="receipt_lines")
    line_number = models.PositiveIntegerField()
    account_snapshot = models.JSONField(default=dict)
    cash_amount = models.DecimalField(max_digits=22, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)
    received_on = models.DateField()

    class Meta:
        db_table = "finance_receipt_account_line"
        default_permissions = ()
        ordering = ["line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["receipt", "line_number"], name="finance_receipt_line_unique"),
            models.CheckConstraint(condition=Q(cash_amount__gt=0, fee_amount__gte=0, line_number__gt=0), name="finance_receipt_line_amounts"),
        ]


class ReceiptAttachment(UUIDPrimaryKeyModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name="attachments")
    file = models.OneToOneField("files.BusinessFile", on_delete=models.PROTECT, related_name="finance_receipt_attachment")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_receipt_attachment"
        default_permissions = ()


class FinanceReceiptUpload(UUIDPrimaryKeyModel):
    class Status(models.TextChoices):
        UNBOUND = "UNBOUND", "未绑定"
        BOUND = "BOUND", "已绑定"
        DISCARD_PENDING = "DISCARD_PENDING", "待清理"
        DISCARDED = "DISCARDED", "已放弃"

    file = models.OneToOneField("files.BusinessFile", on_delete=models.PROTECT, related_name="finance_receipt_upload")
    owner_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    statement = models.ForeignKey("finance.ReceivableStatement", on_delete=models.PROTECT, related_name="receipt_uploads")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNBOUND)
    upload_key = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    bound_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "finance_receipt_upload"
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=(
            Q(status__in=["UNBOUND", "DISCARD_PENDING"], bound_at__isnull=True, discarded_at__isnull=True)
            | Q(status="BOUND", bound_at__isnull=False, discarded_at__isnull=True)
            | Q(status="DISCARDED", bound_at__isnull=True, discarded_at__isnull=False)
        ), name="finance_upload_lifecycle_valid")]
