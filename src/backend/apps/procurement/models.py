import uuid
from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import ArchivableModel, TimeStampedModel


supplier_number_validator = RegexValidator(
    regex=r"^GYS[0-9]{5}$",
    message="供应商编号必须是 GYS 加 5 位数字。",
)


class SupplierType(models.TextChoices):
    MATERIAL = "MATERIAL", "材料供应商"
    FINISHED = "FINISHED", "成品供应商"


class SupplierCategory(models.TextChoices):
    TUBE = "TUBE", "管材"
    HARDWARE = "HARDWARE", "五金"
    PLASTIC_PART = "PLASTIC_PART", "塑料件"
    PACKAGING = "PACKAGING", "包材"
    FABRIC = "FABRIC", "面料"
    AUXILIARY = "AUXILIARY", "辅料"
    FINISHED_GOODS = "FINISHED_GOODS", "成品"


class SupplierPaymentCycle(models.TextChoices):
    MONTHLY = "MONTHLY", "月结"


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    # 保留已投入使用的数据库值，业务界面统一称为“已确认”。
    SUBMITTED = "SUBMITTED", "已确认"
    PURCHASING = "PURCHASING", "采购中"
    COMPLETED = "COMPLETED", "已完成采购"


class PurchaseReturnStatus(models.TextChoices):
    QUALITY_GENERATED = "QUALITY_GENERATED", "品质生成 · 待确认退货"
    PROCUREMENT_CONFIRMED = "PROCUREMENT_CONFIRMED", "已确认退货 · 待退货完成"
    COMPLETED = "COMPLETED", "退货完成"


class PurchaseContractTemplateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    INACTIVE = "INACTIVE", "停用"


class SupplierPurchaseSheetStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PUBLISHED = "PUBLISHED", "已发布"


class PurchaseQuantityParseStatus(models.TextChoices):
    READY = "READY", "已识别"
    MISSING = "MISSING", "未填写"
    INVALID = "INVALID", "格式异常"


class PurchaseRequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    SUBMITTED = "SUBMITTED", "已提交"
    ALLOCATING = "ALLOCATING", "分配中"
    FULLY_ALLOCATED = "FULLY_ALLOCATED", "已分配完成"
    CANCELLED = "CANCELLED", "已取消"


class PurchaseAllocationStatus(models.TextChoices):
    DRAFT = "DRAFT", "待下单"
    ORDERED = "ORDERED", "已下单"
    CANCELLED = "CANCELLED", "已取消"


class Supplier(ArchivableModel):
    supplier_number = models.CharField(
        max_length=8,
        unique=True,
        validators=[supplier_number_validator],
    )
    supplier_type = models.CharField(max_length=20, choices=SupplierType.choices)
    supplier_categories = ArrayField(
        models.CharField(max_length=30, choices=SupplierCategory.choices),
        default=list,
    )
    supplier_name = models.CharField(max_length=255)
    payment_cycle = models.CharField(
        max_length=20,
        choices=SupplierPaymentCycle.choices,
        blank=True,
    )
    remark = models.TextField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    is_disabled = models.BooleanField(default=False)
    submitted_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="submitted_suppliers",
    )
    submitted_by_name = models.CharField(max_length=150, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_suppliers",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_suppliers",
    )

    class Meta:
        db_table = "procurement_supplier"
        ordering = ["-supplier_number", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(supplier_number__regex=r"^GYS[0-9]{5}$"),
                name="supplier_number_format_valid",
            ),
            models.CheckConstraint(
                condition=Q(supplier_type__in=SupplierType.values),
                name="supplier_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(payment_cycle="") | Q(payment_cycle__in=SupplierPaymentCycle.values),
                name="supplier_payment_cycle_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["supplier_type", "is_disabled"], name="supplier_type_disabled_idx"),
            models.Index(fields=["payment_cycle", "-updated_at"], name="supplier_payment_idx"),
            models.Index(fields=["-updated_at", "-id"], name="supplier_updated_idx"),
        ]

    def clean(self):
        super().clean()
        categories = self.supplier_categories
        if not isinstance(categories, list) or not categories:
            raise ValidationError({"supplier_categories": "请至少选择一个供应商类别。"})
        invalid = [value for value in categories if value not in SupplierCategory.values]
        if invalid:
            raise ValidationError({"supplier_categories": "供应商类别包含不支持的选项。"})
        if len(categories) != len(set(categories)):
            raise ValidationError({"supplier_categories": "供应商类别不能重复。"})

    def delete(self, *args, **kwargs):
        raise ValidationError("供应商不允许物理删除，请使用禁用状态。")

    def __str__(self):
        return f"{self.supplier_number} - {self.supplier_name}"


class PurchaseOrderSourceType(models.TextChoices):
    PRODUCTION = "PRODUCTION", "生产订单"
    SAMPLE = "SAMPLE", "打样单"


class PurchaseOrder(ArchivableModel):
    source_type = models.CharField(max_length=20, choices=PurchaseOrderSourceType.choices, default=PurchaseOrderSourceType.PRODUCTION)
    sample_procurement_request = models.OneToOneField(
        "samples.SampleMaterialProcurementRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="purchase_order",
    )
    sample_number_snapshot = models.CharField(max_length=50, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="completed_purchase_orders",
    )
    completion_remark = models.TextField(blank=True, max_length=2000)
    order_number = models.CharField(max_length=50, unique=True, validators=[RegexValidator(
        regex=r"^CGDD(?:[0-9]{6}[0-9]{3,40}|[0-9]{8}[0-9]{2,38})$",
        message="采购订单号必须是 CGDD 加 6 位日期和至少 3 位流水，兼容历史 8 位日期和至少 2 位流水，总长不超过 50 位。",
    )])
    production_task = models.OneToOneField(
        "production_tasks.ProductionTask",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_order",
    )
    production_task_number_snapshot = models.CharField(max_length=50)
    sales_order_number_snapshot = models.CharField(max_length=100)
    customer_name_snapshot = models.CharField(max_length=255)
    source_revision = models.CharField(max_length=64)
    currency = models.ForeignKey(
        "reference_data.Currency",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    currency_code_snapshot = models.CharField(max_length=3, blank=True)
    currency_name_snapshot = models.CharField(max_length=150, blank=True)
    currency_symbol_snapshot = models.CharField(max_length=20, blank=True)
    is_mailed = models.BooleanField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.DRAFT,
    )
    total_amount = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_purchase_orders",
    )

    class Meta:
        db_table = "procurement_purchase_order"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("submit_purchaseorder", "Can submit purchase order"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(source_type="PRODUCTION", production_task__isnull=False, sample_procurement_request__isnull=True)
                           | Q(source_type="SAMPLE", production_task__isnull=True, sample_procurement_request__isnull=False)),
                name="purchase_order_source_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=PurchaseOrderStatus.values),
                name="purchase_order_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__isnull=True) | Q(total_amount__gte=0),
                name="purchase_order_total_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="purchase_order_status_idx"),
            models.Index(fields=["currency", "-created_at"], name="purchase_order_currency_idx"),
        ]

    def __str__(self):
        return self.order_number


class PurchaseReturn(TimeStampedModel):
    return_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="returns")
    inbound = models.ForeignKey("inventory.MaterialInbound", on_delete=models.PROTECT, related_name="purchase_returns")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_returns")
    supplier_number_snapshot = models.CharField(max_length=8)
    supplier_name_snapshot = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=PurchaseReturnStatus.choices, default=PurchaseReturnStatus.QUALITY_GENERATED)
    generated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="generated_purchase_returns")
    confirmed_by_employee = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="confirmed_purchase_returns")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_by_employee = models.ForeignKey("organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="completed_purchase_returns")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "procurement_purchase_return"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["inbound", "supplier"], name="purchase_return_inbound_supplier_unique"),
            models.CheckConstraint(condition=Q(status__in=PurchaseReturnStatus.values), name="purchase_return_status_valid"),
        ]


class PurchaseReturnLine(TimeStampedModel):
    return_order = models.ForeignKey(PurchaseReturn, on_delete=models.PROTECT, related_name="lines")
    inbound_line = models.OneToOneField("inventory.MaterialInboundLine", on_delete=models.PROTECT, related_name="purchase_return_line")
    quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])

    class Meta:
        db_table = "procurement_purchase_return_line"
        ordering = ["created_at", "id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="purchase_return_quantity_positive")]


class PurchaseOrderLine(models.Model):
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    suggested_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    suggested_purchase_meters = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    actual_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    actual_purchase_meters = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    quantity_difference_reason = models.TextField(blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    line_number = models.PositiveIntegerField()
    bom = models.ForeignKey(
        "boms.Bom",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_order_lines",
    )
    bom_line = models.ForeignKey(
        "boms.BomLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_order_lines",
    )
    source_bom_line_id_snapshot = models.UUIDField(null=True, blank=True)
    product_line_id_snapshot = models.UUIDField(null=True, blank=True)
    sample_demand_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    sample_supply_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    color_snapshot = models.CharField(max_length=500, blank=True)
    bom_number_snapshot = models.CharField(max_length=80)
    product_number_snapshot = models.CharField(max_length=100)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    product_specification_snapshot = models.CharField(max_length=300, blank=True)
    section_type_snapshot = models.CharField(max_length=20)
    section_title_snapshot = models.CharField(max_length=300)
    category_snapshot = models.CharField(max_length=150, blank=True)
    material_snapshot = models.CharField(max_length=200, blank=True)
    part_name_snapshot = models.CharField(max_length=300)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    raw_material_snapshot = models.TextField(blank=True)
    material_attributes_snapshot = models.JSONField(default=dict, blank=True)
    required_quantity = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    source_quantity_field = models.CharField(max_length=80, blank=True)
    source_quantity_text = models.CharField(max_length=255, blank=True)
    source_unit_text = models.CharField(max_length=50, blank=True)
    quantity_parse_status = models.CharField(
        max_length=20,
        choices=PurchaseQuantityParseStatus.choices,
    )
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_order_lines",
    )
    supplier_number_snapshot = models.CharField(max_length=8, blank=True)
    supplier_name_snapshot = models.CharField(max_length=255, blank=True)
    supplier_type_snapshot = models.CharField(max_length=20, blank=True)
    supplier_categories_snapshot = ArrayField(
        models.CharField(max_length=30),
        default=list,
        blank=True,
    )
    delivery_date = models.DateField(null=True, blank=True)
    actual_purchase_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    amount = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )

    class Meta:
        db_table = "procurement_purchase_order_line"
        ordering = ["purchase_order", "line_number"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(raw_bar_length_m__isnull=True, suggested_bar_count__isnull=True,
                             suggested_purchase_meters__isnull=True, actual_bar_count__isnull=True,
                             actual_purchase_meters__isnull=True)
                           | (Q(raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0,
                                suggested_bar_count__isnull=False, suggested_bar_count__gt=0,
                                suggested_purchase_meters__isnull=False, source_unit_text='米',
                                suggested_purchase_meters=F('suggested_bar_count') * F('raw_bar_length_m'))
                              & (Q(actual_bar_count__isnull=True, actual_purchase_meters__isnull=True, actual_purchase_quantity__isnull=True)
                                 | Q(actual_bar_count__isnull=False, actual_bar_count__gt=0,
                                     actual_purchase_meters__isnull=False, actual_purchase_quantity__isnull=False,
                                     actual_purchase_meters=F('actual_bar_count') * F('raw_bar_length_m'),
                                     actual_purchase_quantity=F('actual_purchase_meters'))))),
                name='purchase_pipe_root_meter_consistent',
            ),
            models.UniqueConstraint(
                fields=["purchase_order", "line_number"],
                name="purchase_order_line_number_unique",
            ),
            models.UniqueConstraint(
                fields=["purchase_order", "source_bom_line_id_snapshot"],
                name="purchase_order_bom_line_unique",
            ),
            models.CheckConstraint(
                condition=Q(quantity_parse_status__in=PurchaseQuantityParseStatus.values),
                name="purchase_qty_parse_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(required_quantity__isnull=True) | Q(required_quantity__gte=0),
                name="purchase_required_qty_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(actual_purchase_quantity__isnull=True) | Q(actual_purchase_quantity__gt=0),
                name="purchase_actual_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0),
                name="purchase_unit_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(amount__isnull=True) | Q(amount__gte=0),
                name="purchase_line_amount_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(actual_purchase_quantity__isnull=True, amount__isnull=True)
                    | Q(unit_price__isnull=True, amount__isnull=True)
                    | Q(
                        actual_purchase_quantity__isnull=False,
                        unit_price__isnull=False,
                        amount__isnull=False,
                    )
                ),
                name="purchase_line_amount_completeness",
            ),
        ]
        indexes = [
            models.Index(fields=["supplier", "delivery_date"], name="po_line_supp_date_idx"),
            models.Index(fields=["bom", "line_number"], name="purchase_line_bom_idx"),
        ]

    def __str__(self):
        return f"{self.purchase_order.order_number} - {self.line_number}"


class PurchaseRequest(ArchivableModel):
    request_number = models.CharField(max_length=50, unique=True)
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    sales_order_delivery_batch = models.ForeignKey(
        "sales_orders.SalesOrderDeliveryBatch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    bom = models.OneToOneField(
        "boms.Bom",
        on_delete=models.PROTECT,
        related_name="purchase_request",
    )
    status = models.CharField(max_length=20, choices=PurchaseRequestStatus.choices, default=PurchaseRequestStatus.DRAFT)
    gross_requirement_notice = models.CharField(
        max_length=250,
        default="BOM 数量为毛需求，未自动扣减库存、在途、已分配、损耗或 MOQ。",
    )
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_requests_created",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "purchase_request"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=PurchaseRequestStatus.values), name="purchase_request_status_valid"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at", "-id"], name="purchase_request_status_idx"),
            models.Index(fields=["production_task", "-created_at"], name="purchase_request_task_idx"),
        ]

    def __str__(self):
        return self.request_number


class PurchaseRequestLine(TimeStampedModel):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    bom_line = models.ForeignKey("boms.BomLine", on_delete=models.PROTECT, related_name="purchase_request_lines")
    material_snapshot = models.CharField(max_length=300)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    unit_snapshot = models.CharField(max_length=50)
    gross_requirement_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    actual_request_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    difference_reason = models.TextField(blank=True)
    required_date = models.DateField(null=True, blank=True)
    suggested_supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="suggested_purchase_request_lines",
    )

    class Meta:
        db_table = "purchase_request_line"
        ordering = ["purchase_request", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["purchase_request", "line_number"], name="purchase_request_line_number_uniq"),
            models.UniqueConstraint(fields=["purchase_request", "bom_line"], name="purchase_request_bom_line_uniq"),
            models.CheckConstraint(condition=Q(gross_requirement_quantity__gt=0), name="purchase_request_gross_qty_positive"),
            models.CheckConstraint(
                condition=Q(actual_request_quantity__isnull=True) | Q(actual_request_quantity__gt=0),
                name="purchase_request_actual_qty_positive",
            ),
        ]

    @property
    def allocated_quantity(self):
        return self.allocations.filter(
            status__in=[PurchaseAllocationStatus.DRAFT, PurchaseAllocationStatus.ORDERED]
        ).aggregate(value=models.Sum("quantity"))["value"] or Decimal("0")

    @property
    def remaining_quantity(self):
        return max(Decimal(self.actual_request_quantity or 0) - Decimal(self.allocated_quantity), Decimal("0"))


class PurchaseRequestAllocation(TimeStampedModel):
    purchase_request_line = models.ForeignKey(
        PurchaseRequestLine,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_request_allocations")
    procurement_batch_number = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    expected_arrival_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=PurchaseAllocationStatus.choices,
        default=PurchaseAllocationStatus.DRAFT,
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_request_allocations_created",
    )
    supplier_purchase_sheet = models.ForeignKey(
        "SupplierPurchaseSheet",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_request_allocations",
    )

    class Meta:
        db_table = "purchase_request_allocation"
        ordering = ["purchase_request_line", "created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="purchase_allocation_qty_positive"),
            models.CheckConstraint(condition=Q(status__in=PurchaseAllocationStatus.values), name="purchase_allocation_status_valid"),
        ]
        indexes = [
            models.Index(fields=["supplier", "status", "expected_arrival_date"], name="pr_alloc_supplier_idx"),
        ]


class PurchaseContractTemplate(ArchivableModel):
    template_code = models.CharField(max_length=50, unique=True)
    template_name = models.CharField(max_length=150)
    supplier_categories = ArrayField(
        models.CharField(max_length=30, choices=SupplierCategory.choices),
        default=list,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PurchaseContractTemplateStatus.choices,
        default=PurchaseContractTemplateStatus.ACTIVE,
    )
    current_version_number = models.PositiveIntegerField(default=1)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_purchase_contract_templates",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_purchase_contract_templates",
    )

    class Meta:
        db_table = "procurement_purchase_contract_template"
        ordering = ["template_code", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=PurchaseContractTemplateStatus.values),
                name="purchase_tpl_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(current_version_number__gte=1),
                name="purchase_tpl_version_positive",
            ),
        ]

    def __str__(self):
        return f"{self.template_code} - {self.template_name}"


class PurchaseContractTemplateVersion(TimeStampedModel):
    template = models.ForeignKey(
        PurchaseContractTemplate,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    version_name = models.CharField(max_length=150, default="初始版")
    content_config = models.JSONField(default=dict)
    change_summary = models.CharField(max_length=500, blank=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_purchase_contract_template_versions",
    )

    class Meta:
        db_table = "procurement_purchase_contract_template_version"
        ordering = ["template", "-version_number", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version_number"],
                name="purchase_tpl_version_unique",
            ),
            models.CheckConstraint(
                condition=Q(version_number__gte=1),
                name="purchase_tpl_ver_positive",
            ),
        ]

    def __str__(self):
        return f"{self.template.template_code} - {self.version_name}"


class SupplierPurchaseSheet(ArchivableModel):
    series_id = models.UUIDField(default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_purchase_sheets",
    )
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_purchase_sheets",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_sheets",
    )
    supplier_number_snapshot = models.CharField(max_length=8)
    supplier_name_snapshot = models.CharField(max_length=255)
    supplier_phone_snapshot = models.CharField(max_length=100, blank=True)
    sheet_number = models.CharField(
        max_length=50,
        validators=[RegexValidator(
            regex=r"^CGDD(?:[0-9]{6}[0-9]{3,40}|[0-9]{8}[0-9]{2,38})$",
            message="采购表编号必须是 CGDD 加 6 位日期和至少 3 位流水，兼容历史 8 位日期和至少 2 位流水，总长不超过 50 位。",
        )],
    )
    version_number = models.PositiveIntegerField(default=1)
    procurement_batch_number = models.CharField(max_length=100, blank=True)
    is_current = models.BooleanField(default=True)
    template_version = models.ForeignKey(
        PurchaseContractTemplateVersion,
        on_delete=models.PROTECT,
        related_name="purchase_sheets",
    )
    status = models.CharField(
        max_length=20,
        choices=SupplierPurchaseSheetStatus.choices,
        default=SupplierPurchaseSheetStatus.DRAFT,
    )
    content_snapshot = models.JSONField(default=dict)
    total_amount = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    pdf_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_purchase_sheet_pdfs",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_supplier_purchase_sheets",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_supplier_purchase_sheets",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_supplier_purchase_sheets",
    )

    class Meta:
        db_table = "procurement_supplier_purchase_sheet"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("publish_supplierpurchasesheet", "Can publish supplier purchase sheet"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["series_id", "version_number"],
                name="supplier_sheet_series_ver_unique",
            ),
            models.UniqueConstraint(
                fields=["purchase_order", "supplier"],
                condition=Q(is_current=True, archived_at__isnull=True),
                name="supplier_sheet_current_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=SupplierPurchaseSheetStatus.values),
                name="supplier_sheet_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(version_number__gte=1),
                name="supplier_sheet_ver_positive",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__isnull=True) | Q(total_amount__gte=0),
                name="supplier_sheet_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(purchase_order__isnull=False, purchase_request__isnull=True)
                | Q(purchase_order__isnull=True, purchase_request__isnull=False),
                name="supplier_sheet_source_exactly_one",
            ),
            models.UniqueConstraint(
                fields=["purchase_request", "supplier", "procurement_batch_number"],
                condition=Q(is_current=True, archived_at__isnull=True, purchase_request__isnull=False),
                name="supplier_sheet_request_current_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["purchase_order", "is_current"], name="supplier_sheet_order_idx"),
            models.Index(fields=["supplier", "status"], name="supplier_sheet_supplier_idx"),
            models.Index(fields=["sheet_number", "-version_number"], name="supplier_sheet_number_idx"),
        ]

    def __str__(self):
        return f"{self.sheet_number} V{self.version_number}"


class SupplierPurchaseSheetLineImage(TimeStampedModel):
    """采购表某一来源明细的图片；版本之间各自保存引用，避免覆盖历史 PDF。"""

    sheet = models.ForeignKey(
        SupplierPurchaseSheet,
        on_delete=models.CASCADE,
        related_name="line_images",
    )
    source_purchase_order_line_id = models.UUIDField()
    image_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="supplier_purchase_sheet_line_images",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_supplier_purchase_sheet_line_images",
    )

    class Meta:
        db_table = "procurement_supplier_purchase_sheet_line_image"
        ordering = ["sheet", "source_purchase_order_line_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "source_purchase_order_line_id"],
                name="supplier_sheet_line_image_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["sheet", "source_purchase_order_line_id"], name="supplier_sheet_line_img_idx"),
        ]

    def __str__(self):
        return f"{self.sheet} - {self.source_purchase_order_line_id}"


class SupplierPurchaseSheetSealImage(TimeStampedModel):
    """采购表当前版本的甲方盖章图片；每个版本独立保存文件引用。"""

    sheet = models.OneToOneField(
        SupplierPurchaseSheet,
        on_delete=models.CASCADE,
        related_name="seal_image",
    )
    image_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="supplier_purchase_sheet_seal_images",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_supplier_purchase_sheet_seal_images",
    )

    class Meta:
        db_table = "procurement_supplier_purchase_sheet_seal_image"

    def __str__(self):
        return f"{self.sheet} - 甲方盖章"
