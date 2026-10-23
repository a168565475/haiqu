from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class ReceivableStatement(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "有效"
        VOID = "VOID", "已作废"

    number = models.CharField(max_length=50, unique=True)
    production_task = models.ForeignKey("production_tasks.ProductionTask", on_delete=models.PROTECT, related_name="finance_statements")
    salesperson = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="finance_statements")
    task_number_snapshot = models.CharField(max_length=50)
    salesperson_code_snapshot = models.CharField(max_length=50)
    salesperson_name_snapshot = models.CharField(max_length=150)
    source_order_date = models.DateField()
    source_revision = models.CharField(max_length=64)
    statement_revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    amount = models.DecimalField(max_digits=22, decimal_places=2)
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    void_reason = models.CharField(max_length=500, blank=True)
    voided_by = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "finance_receivable_statement"
        ordering = ["-created_at", "-id"]
        default_permissions = ("add", "change", "view", "delete")
        permissions = [("void_receivablestatement", "可作废应收对账单")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0, statement_revision__gte=1), name="finance_statement_amount_valid"),
            models.CheckConstraint(condition=Q(status="ACTIVE", voided_at__isnull=True, voided_by__isnull=True, void_reason="") | (Q(status="VOID", voided_at__isnull=False, voided_by__isnull=False) & ~Q(void_reason="")), name="finance_statement_status_valid"),
        ]


class ReceivableStatementLine(TimeStampedModel):
    statement = models.ForeignKey("finance.ReceivableStatement", on_delete=models.PROTECT, related_name="lines")
    production_task_product = models.ForeignKey("production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, related_name="finance_statement_lines")
    statement_revision = models.PositiveIntegerField()
    line_number = models.PositiveIntegerField()
    item_number_snapshot = models.CharField(max_length=100, blank=True)
    product_number_snapshot = models.CharField(max_length=100, blank=True)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    specification_snapshot = models.CharField(max_length=300, blank=True)
    unit_code_snapshot = models.CharField(max_length=20)
    unit_name_snapshot = models.CharField(max_length=80)
    quantity = models.PositiveBigIntegerField()
    reference_unit_price_cny = models.DecimalField(max_digits=18, decimal_places=4)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    amount = models.DecimalField(max_digits=22, decimal_places=2)
    source_currency_code = models.CharField(max_length=3)
    exchange_rate_snapshot = models.JSONField(default=dict)
    is_occupied = models.BooleanField(default=True)

    class Meta:
        db_table = "finance_receivable_statement_line"
        ordering = ["statement_revision", "line_number"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["production_task_product"], condition=Q(is_occupied=True), name="finance_statement_source_occupied"),
            models.UniqueConstraint(fields=["statement", "statement_revision", "line_number"], name="finance_statement_revision_line"),
            models.UniqueConstraint(fields=["statement", "statement_revision", "production_task_product"], name="finance_statement_revision_source"),
            models.CheckConstraint(condition=Q(quantity__gt=0, unit_price__gt=0, reference_unit_price_cny__gte=0, amount__gte=0, statement_revision__gte=1, line_number__gte=1), name="finance_statement_line_valid"),
        ]
