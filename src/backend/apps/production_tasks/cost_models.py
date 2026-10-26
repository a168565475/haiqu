from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class ProductionTaskExpense(TimeStampedModel):
    class ExpenseType(models.TextChoices):
        LOADING = 'LOADING', '装卸费'
        TRANSPORT = 'TRANSPORT', '运输费'
        OTHER = 'OTHER', '其他费用'

    production_task = models.ForeignKey('production_tasks.ProductionTask', on_delete=models.PROTECT, related_name='cost_expenses')
    expense_type = models.CharField(max_length=20, choices=ExpenseType.choices)
    description = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    occurred_on = models.DateField()
    remark = models.CharField(max_length=500, blank=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    created_by_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT, related_name='+')
    updated_by_employee = models.ForeignKey('organizations.Employee', on_delete=models.PROTECT, related_name='+')
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        permissions = [('view_productiontaskcost', '查看订单成本'), ('manage_productiontaskexpense', '维护订单零星费用')]
        ordering = ['occurred_on', 'created_at', 'id']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='production_task_expense_positive_amount')]
