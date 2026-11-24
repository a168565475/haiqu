from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel


class SupplierPaymentApplication(TimeStampedModel):
    number = models.CharField(max_length=50, unique=True)
    applied_on = models.DateField()
    supplier = models.ForeignKey("procurement.Supplier", on_delete=models.PROTECT, related_name="+")
    supplier_name_snapshot = models.CharField(max_length=255)
    payee = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=24, decimal_places=2)
    note = models.CharField(max_length=500, blank=True)
    department_name_snapshot = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    recorded_by_name_snapshot = models.CharField(max_length=150)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    withdrawal_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "finance_supplier_payment_application"
        default_permissions = ("add",)
        permissions = [("withdraw_supplierpaymentapplication", "撤回供应商付款申请")]
        indexes = [models.Index(fields=["supplier", "applied_on"], name="fin_sup_app_supplier_date")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0) & ~Q(payee=""), name="fin_sup_application_positive"),
            models.CheckConstraint(
                condition=(
                    Q(withdrawn_at__isnull=True, withdrawn_by__isnull=True, withdrawal_reason="")
                    | (Q(withdrawn_at__isnull=False, withdrawn_by__isnull=False) & ~Q(withdrawal_reason=""))
                ),
                name="fin_sup_application_withdrawal",
            ),
        ]

    @property
    def remaining_amount(self):
        return 0 if self.withdrawn_at else self.amount - self.paid_amount


class SupplierPaymentApplicationLine(TimeStampedModel):
    application = models.ForeignKey(SupplierPaymentApplication, on_delete=models.PROTECT, related_name="lines")
    payable = models.ForeignKey("finance.PurchasePayable", on_delete=models.PROTECT, related_name="payment_application_lines")
    payable_number = models.CharField(max_length=50)
    inbound_date = models.DateField()
    confirmed_amount = models.DecimalField(max_digits=22, decimal_places=2)
    offset_amount = models.DecimalField(max_digits=22, decimal_places=2)
    amount = models.DecimalField(max_digits=22, decimal_places=2)
    released_amount = models.DecimalField(max_digits=22, decimal_places=2, default=0)

    class Meta:
        db_table = "finance_supplier_payment_application_line"
        default_permissions = ()
        ordering = ("inbound_date", "payable_number", "id")
        constraints = [
            models.UniqueConstraint(fields=["application", "payable"], name="fin_sup_app_line_unique"),
            models.CheckConstraint(
                condition=Q(amount__gt=0, released_amount__gte=0, released_amount__lte=F("amount")),
                name="fin_sup_app_line_amounts",
            ),
        ]
