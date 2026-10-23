from django.db import models
from django.db.models import F, Q

from apps.core.models import UUIDPrimaryKeyModel


class DepositAllocation(UUIDPrimaryKeyModel):
    goods_receipt = models.ForeignKey("finance.Receipt", on_delete=models.PROTECT, related_name="allocations")
    deposit_receipt = models.ForeignKey("finance.Receipt", on_delete=models.PROTECT, related_name="deposit_allocations")
    amount = models.DecimalField(max_digits=22, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "finance_deposit_allocation"
        default_permissions = ()
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["deposit_receipt"], condition=Q(is_active=True), name="finance_deposit_active_allocation"),
            models.CheckConstraint(condition=Q(amount__gt=0) & ~Q(goods_receipt=F("deposit_receipt")), name="finance_allocation_amount_valid"),
            models.CheckConstraint(condition=Q(is_active=True, voided_at__isnull=True) | Q(is_active=False, voided_at__isnull=False), name="finance_allocation_lifecycle"),
        ]
