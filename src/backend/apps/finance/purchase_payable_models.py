from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class PurchasePayableStatus(models.TextChoices):
    WAITING_PRICE = "WAITING_PRICE", "待核价"
    WAITING_FINANCE_CONFIRM = "WAITING_FINANCE_CONFIRM", "待财务确认"
    WAITING_PAYMENT = "WAITING_PAYMENT", "待付款"
    VOID = "VOID", "已作废"


class PurchasePayable(TimeStampedModel):
    """采购入库转财务应付的结算单；本期只走到待付款。"""

    number = models.CharField(max_length=50, unique=True)
    material_inbound = models.ForeignKey(
        "inventory.MaterialInbound", on_delete=models.PROTECT, related_name="purchase_payables",
    )
    supplier = models.ForeignKey(
        "procurement.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_payables",
    )
    supplier_number_snapshot = models.CharField(max_length=8, blank=True)
    supplier_name_snapshot = models.CharField(max_length=255, blank=True)
    payment_term = models.ForeignKey("procurement.SupplierPaymentTerm", null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="+")
    payment_term_months = models.PositiveSmallIntegerField(null=True, blank=True)
    due_month = models.DateField(null=True, blank=True, db_index=True)
    purchase_order_number_snapshot = models.CharField(max_length=50, blank=True)
    inbound_number_snapshot = models.CharField(max_length=50, blank=True)
    currency_code_snapshot = models.CharField(max_length=3, blank=True)
    currency_name_snapshot = models.CharField(max_length=150, blank=True)
    # 含税/运费口径本期只保留待确认字段，不参与金额计算。
    tax_mode = models.CharField(max_length=50, null=True, blank=True)
    freight_mode = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=40, choices=PurchasePayableStatus.choices, default=PurchasePayableStatus.WAITING_PRICE)
    amount = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="confirmed_purchase_payables",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    voided_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="voided_purchase_payables",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "finance_purchase_payable"
        ordering = ["-created_at", "-id"]
        default_permissions = ("add", "change", "delete", "view")
        permissions = [
            ("confirm_purchasepayable", "确认采购应付"),
            ("void_purchasepayable", "作废采购应付"),
            ("view_supplierledger", "查看供应商往来明细"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["material_inbound", "supplier"], name="finance_payable_inbound_supplier_unique"),
            models.CheckConstraint(condition=Q(status__in=PurchasePayableStatus.values), name="finance_payable_status_valid"),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0), name="finance_payable_amount_nonnegative"),
            models.CheckConstraint(
                condition=(Q(status__in=[PurchasePayableStatus.WAITING_PAYMENT, PurchasePayableStatus.VOID]) | Q(confirmed_at__isnull=True)),
                name="finance_payable_confirmed_at_state_valid",
            ),
            models.CheckConstraint(
                condition=(Q(status=PurchasePayableStatus.VOID, voided_at__isnull=False, voided_by_employee__isnull=False) |
                           (~Q(status=PurchasePayableStatus.VOID) & Q(voided_at__isnull=True) & Q(voided_by_employee__isnull=True))),
                name="finance_payable_void_state_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="finance_payable_status_idx"),
            models.Index(fields=["supplier", "-created_at"], name="finance_payable_supplier_idx"),
            models.Index(fields=["material_inbound", "-created_at"], name="finance_payable_inbound_idx"),
        ]


class PurchasePayableLine(TimeStampedModel):
    payable = models.ForeignKey(PurchasePayable, on_delete=models.PROTECT, related_name="lines")
    material_inbound_line = models.OneToOneField(
        "inventory.MaterialInboundLine", on_delete=models.PROTECT, related_name="purchase_payable_line",
    )
    purchase_order_line = models.ForeignKey(
        "procurement.PurchaseOrderLine", on_delete=models.PROTECT, related_name="purchase_payable_lines",
    )
    material_snapshot = models.CharField(max_length=200, blank=True)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    part_name_snapshot = models.CharField(max_length=300, blank=True)
    material_attributes_snapshot = models.JSONField(default=dict, blank=True)
    source_unit_text_snapshot = models.CharField(max_length=50, blank=True)
    accepted_quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(0)])
    accepted_weight_kg = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True,
                                             validators=[MinValueValidator(0)])
    accepted_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    reference_unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True,
                                               validators=[MinValueValidator(0)])
    reference_amount = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True,
                                           validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True,
                                     validators=[MinValueValidator(0)])
    price_unit_text = models.CharField(max_length=50, blank=True)
    currency_code_snapshot = models.CharField(max_length=3, blank=True)
    price_source = models.CharField(max_length=100, blank=True)
    price_confirmed_by_name = models.CharField(max_length=150, blank=True)
    price_confirmed_at = models.DateTimeField(null=True, blank=True)
    price_remark = models.TextField(blank=True)
    tax_mode = models.CharField(max_length=50, null=True, blank=True)
    freight_mode = models.CharField(max_length=50, null=True, blank=True)
    amount = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(0)])

    class Meta:
        db_table = "finance_purchase_payable_line"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(accepted_quantity__gte=0), name="finance_payable_line_qty_nonnegative"),
            models.CheckConstraint(condition=Q(accepted_weight_kg__isnull=True) | Q(accepted_weight_kg__gte=0),
                                   name="finance_payable_line_weight_nonnegative"),
            models.CheckConstraint(condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0),
                                   name="finance_payable_line_price_nonnegative"),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0),
                                   name="finance_payable_line_amount_nonnegative"),
        ]
        indexes = [
            models.Index(fields=["payable", "id"], name="fin_pay_line_pay_idx"),
            models.Index(fields=["purchase_order_line", "id"], name="fin_pay_line_po_idx"),
        ]
