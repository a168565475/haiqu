from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class FinanceAccount(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        INACTIVE = "INACTIVE", "停用"

    account_type = models.CharField(max_length=80)
    code = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=80)
    name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=100)
    currency = models.ForeignKey("reference_data.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "finance_account"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["ACTIVE", "INACTIVE"]), name="finance_account_status_valid"),
            models.CheckConstraint(
                condition=~Q(code="") & ~Q(name="") & ~Q(account_number="") & ~Q(account_type="") & ~Q(category=""),
                name="finance_account_fields_required",
            ),
        ]


class AccountingSubject(TimeStampedModel):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    level = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=FinanceAccount.Status.choices, default="ACTIVE")
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "finance_accounting_subject"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=Q(parent__isnull=True), name="finance_subject_root_unique"),
            models.UniqueConstraint(fields=["parent", "name"], condition=Q(parent__isnull=False), name="finance_subject_sibling_unique"),
            models.CheckConstraint(condition=Q(level=1, parent__isnull=True) | Q(level__in=[2, 3], parent__isnull=False), name="finance_subject_level_parent"),
            models.CheckConstraint(condition=Q(status__in=["ACTIVE", "INACTIVE"]) & ~Q(name=""), name="finance_subject_fields_valid"),
        ]


class FinanceMutationKey(UUIDPrimaryKeyModel):
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    resource_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_mutation_key"
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["actor_employee", "action", "key"], name="finance_mutation_key_unique")]


from .statement_models import ReceivableStatement, ReceivableStatementLine  # noqa: E402,F401
from .receipt_models import FinanceReceiptUpload, Receipt, ReceiptAccountLine, ReceiptAttachment  # noqa: E402,F401
from .allocation_models import DepositAllocation  # noqa: E402,F401
