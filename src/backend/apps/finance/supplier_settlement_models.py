from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class SupplierSettlementDocument(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "有效"
        VOID = "VOID", "已作废"

    number = models.CharField(max_length=50, unique=True)
    business_date = models.DateField()
    recorded_by = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    void_reason = models.CharField(max_length=500, blank=True)
    replaces = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="replacement")

    class Meta:
        abstract = True
        default_permissions = ("add",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status="ACTIVE", voided_at__isnull=True, voided_by__isnull=True, void_reason="")
                    | (Q(status="VOID", voided_at__isnull=False, voided_by__isnull=False) & ~Q(void_reason=""))
                ),
                name="finance_%(class)s_lifecycle",
            ),
        ]


class SupplierPayment(SupplierSettlementDocument):
    class Nature(models.TextChoices):
        GOODS = "GOODS", "货款"
        PREPAYMENT = "PREPAYMENT", "预付款"

    supplier = models.ForeignKey("procurement.Supplier", on_delete=models.PROTECT, related_name="ledger_payments")
    application = models.ForeignKey(
        "finance.SupplierPaymentApplication", null=True, blank=True, on_delete=models.PROTECT, related_name="payments",
    )
    supplier_name_snapshot = models.CharField(max_length=255)
    nature = models.CharField(max_length=12, choices=Nature.choices)
    account = models.ForeignKey("finance.FinanceAccount", on_delete=models.PROTECT, related_name="supplier_payments")
    account_snapshot = models.JSONField()
    payee = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=22, decimal_places=2)
    voucher = models.CharField(max_length=255)

    class Meta(SupplierSettlementDocument.Meta):
        db_table = "finance_supplier_payment"
        default_permissions = ("add", "view")
        permissions = [("void_supplierpayment", "更正供应商付款")]
        constraints = SupplierSettlementDocument.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(amount__gt=0, nature__in=["GOODS", "PREPAYMENT"]) & ~Q(payee="") & ~Q(voucher=""),
                name="finance_supplier_payment_fields",
            ),
        ]
        indexes = [models.Index(fields=["supplier", "business_date"], name="fin_sup_pay_supplier_date")]


class SupplierOffset(SupplierSettlementDocument):
    payment = models.ForeignKey(SupplierPayment, on_delete=models.PROTECT, related_name="offsets")

    class Meta(SupplierSettlementDocument.Meta):
        db_table = "finance_supplier_offset"
        permissions = [("void_supplieroffset", "更正供应商抵账")]
        indexes = [models.Index(fields=["payment", "business_date"], name="fin_sup_off_payment_date")]


class SupplierAllocation(TimeStampedModel):
    offset = models.ForeignKey(SupplierOffset, on_delete=models.PROTECT, related_name="allocations")
    payable = models.ForeignKey("finance.PurchasePayable", on_delete=models.PROTECT, related_name="supplier_allocations")
    amount = models.DecimalField(max_digits=22, decimal_places=2)

    class Meta:
        db_table = "finance_supplier_allocation"
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["offset", "payable"], name="finance_supplier_allocation_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_supplier_allocation_positive"),
        ]
