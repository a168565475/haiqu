from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import ArchivableModel, TimeStampedModel, currency_code_validator, uppercase_code_validator


class SalesOrderSource(models.TextChoices):
    QUOTATION = "QUOTATION", "报价转单"
    DIRECT = "DIRECT", "无报价直接下单"
    REPEAT = "REPEAT", "返单"


class SalesOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    CONFIRMED = "CONFIRMED", "已确认"
    FULFILLING = "FULFILLING", "履约中"
    COMPLETED = "COMPLETED", "已完成"
    PAUSED = "PAUSED", "已暂停"
    CANCELLED = "CANCELLED", "已取消"


class CustomerConfirmationMethod(models.TextChoices):
    CUSTOMER_PO = "CUSTOMER_PO", "客户 PO"
    SIGNED_CONTRACT = "SIGNED_CONTRACT", "签署 PI/合同"
    EMAIL = "EMAIL", "邮件"
    CHAT = "CHAT", "聊天书面确认"


class PriceExceptionStatus(models.TextChoices):
    PENDING = "PENDING", "待审批"
    APPROVED = "APPROVED", "已通过"
    REJECTED = "REJECTED", "已退回"


class DeliveryBatchStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "有效"
    CANCELLED = "CANCELLED", "已取消"


class CollaborationEventSource(models.TextChoices):
    SYSTEM = "SYSTEM", "系统事件"
    MANUAL = "MANUAL", "人工登记"


class CollaborationEventStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    COMPLETED = "COMPLETED", "已完成"
    RISK = "RISK", "有风险"
    CANCELLED = "CANCELLED", "已取消"


class CollaborationEventType(models.TextChoices):
    DEPOSIT = "DEPOSIT", "订金确认"
    CONTRACT = "CONTRACT", "合同/PI"
    PREPRODUCTION_SAMPLE = "PREPRODUCTION_SAMPLE", "产前样确认"
    INSPECTION = "INSPECTION", "验货"
    BOOKING = "BOOKING", "订舱"
    SHIPMENT = "SHIPMENT", "发货"
    BALANCE = "BALANCE", "余款"
    DOCUMENT = "DOCUMENT", "单证"
    NOTE = "NOTE", "协同备注"


class SalesOrder(ArchivableModel):
    order_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    version_number = models.PositiveIntegerField(default=1)
    source_type = models.CharField(max_length=20, choices=SalesOrderSource.choices)
    source_quotation_version = models.ForeignKey(
        "quotations.QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_orders",
    )
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="sales_orders",
    )
    transaction_entity = models.ForeignKey(
        "customers.CustomerTransactionEntity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_orders",
    )
    buyer_address = models.ForeignKey(
        "customers.CustomerEntityAddress",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_orders",
    )
    salesperson = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="sold_sales_orders",
    )
    merchandiser = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merchandised_sales_orders",
    )
    customer_po_number = models.CharField(max_length=100, blank=True)
    contract_number = models.CharField(max_length=100, blank=True)
    order_date = models.DateField()
    direct_order_reason = models.TextField(blank=True)
    currency_code = models.CharField(max_length=3, validators=[currency_code_validator])
    exchange_rate = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.000001"))],
    )
    incoterm_code = models.CharField(max_length=20, blank=True)
    payment_terms = models.TextField(blank=True)
    deposit_required = models.BooleanField(default=False)
    includes_tax = models.BooleanField(default=False)
    tax_basis = models.CharField(max_length=200, blank=True)
    order_tolerance_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    preproduction_sample_required = models.BooleanField(default=False)
    buyer_snapshot = models.JSONField(default=dict, blank=True)
    buyer_address_snapshot = models.JSONField(default=dict, blank=True)
    seller_snapshot = models.JSONField(default=dict, blank=True)
    terms_snapshot = models.JSONField(default=dict, blank=True)
    customer_requirement_snapshot = models.JSONField(default=dict, blank=True)
    confirmation_method = models.CharField(
        max_length=30,
        choices=CustomerConfirmationMethod.choices,
        blank=True,
    )
    customer_confirmer = models.CharField(max_length=150, blank=True)
    customer_confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=SalesOrderStatus.choices, default=SalesOrderStatus.DRAFT)
    total_amount = models.DecimalField(max_digits=22, decimal_places=4, default=Decimal("0"))
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_sales_orders",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_sales_orders",
    )

    class Meta:
        db_table = "sales_order"
        ordering = ["-order_date", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(source_type__in=SalesOrderSource.values), name="sales_order_source_valid"),
            models.CheckConstraint(condition=Q(status__in=SalesOrderStatus.values), name="sales_order_status_valid"),
            models.CheckConstraint(condition=Q(exchange_rate__gt=0), name="sales_order_rate_positive"),
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="sales_order_total_nonnegative"),
            models.CheckConstraint(
                condition=Q(order_tolerance_percent__gte=0, order_tolerance_percent__lte=100),
                name="sales_order_tolerance_range",
            ),
            models.CheckConstraint(
                condition=Q(source_type=SalesOrderSource.QUOTATION, source_quotation_version__isnull=False)
                | (~Q(source_type=SalesOrderSource.QUOTATION) & Q(source_quotation_version__isnull=True)),
                name="sales_order_quote_source_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-order_date", "-id"], name="sales_order_status_idx"),
            models.Index(fields=["customer_account", "-order_date", "-id"], name="sales_order_customer_idx"),
            models.Index(fields=["salesperson", "status", "-id"], name="sales_order_salesperson_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "买方主体必须属于当前客户。"
        if self.buyer_address_id and self.buyer_address.transaction_entity_id != self.transaction_entity_id:
            errors["buyer_address"] = "买方地址必须属于当前买方主体。"
        if self.source_quotation_version_id:
            quotation = self.source_quotation_version.quotation
            if quotation.customer_account_id != self.customer_account_id:
                errors["source_quotation_version"] = "来源报价必须属于当前客户。"
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.order_number


class SalesOrderLine(TimeStampedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    source_quotation_line = models.ForeignKey(
        "quotations.QuotationLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_lines",
    )
    product = models.ForeignKey(
        "products.ProductInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_lines",
    )
    # 客户在 BOM 确认前可能只提供文字产品信息；这些快照保留客户当时的输入，
    # 不要求已经建立产品主档关联。BOM 确认后再把当前业务字段关联到正式产品。
    customer_product_name_snapshot = models.CharField(max_length=200, blank=True)
    customer_specification_snapshot = models.CharField(max_length=500, blank=True)
    customer_color_snapshot = models.CharField(max_length=200, blank=True)
    product_number_snapshot = models.CharField(max_length=100)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    unit_code_snapshot = models.CharField(max_length=30, validators=[uppercase_code_validator])
    quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    quoted_quantity_snapshot = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    quoted_unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    line_total = models.DecimalField(max_digits=22, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    price_difference = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    price_difference_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    lower_price_reason = models.TextField(blank=True)
    quality_requirements = models.TextField(blank=True)
    packaging_requirements = models.TextField(blank=True)
    shipping_mark_requirements = models.TextField(blank=True)

    class Meta:
        db_table = "sales_order_line"
        ordering = ["sales_order", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["sales_order", "line_number"], name="sales_order_line_number_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="sales_order_line_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="sales_order_line_price_nonneg"),
            models.CheckConstraint(condition=Q(line_total__gte=0), name="sales_order_line_total_nonneg"),
            models.CheckConstraint(
                condition=Q(quoted_unit_price__isnull=True) | Q(quoted_unit_price__gte=0),
                name="sales_order_line_quote_price_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["source_quotation_line", "id"], name="sales_order_quote_line_idx"),
            models.Index(fields=["product", "id"], name="sales_order_product_idx"),
        ]

    def clean(self):
        super().clean()
        if not self.product_id and not (self.customer_product_name_snapshot or self.product_name_snapshot).strip():
            raise ValidationError({"customer_product_name_snapshot": "未关联产品主档时必须填写客户产品名称。"})
        if (
            self.source_quotation_line_id
            and self.sales_order.source_quotation_version_id
            and self.source_quotation_line.quotation_version_id != self.sales_order.source_quotation_version_id
        ):
            raise ValidationError({"source_quotation_line": "报价行必须属于销售订单的来源报价版本。"})


class SalesOrderDeliveryBatch(TimeStampedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="delivery_batches")
    line_number = models.PositiveIntegerField()
    batch_number = models.CharField(max_length=50)
    planned_delivery_date = models.DateField()
    status = models.CharField(max_length=20, choices=DeliveryBatchStatus.choices, default=DeliveryBatchStatus.ACTIVE)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sales_order_delivery_batch"
        ordering = ["sales_order", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["sales_order", "line_number"], name="sales_order_batch_line_uniq"),
            models.UniqueConstraint(fields=["sales_order", "batch_number"], name="sales_order_batch_number_uniq"),
            models.CheckConstraint(condition=Q(status__in=DeliveryBatchStatus.values), name="sales_order_batch_status_valid"),
        ]


class SalesOrderDeliveryBatchLine(TimeStampedModel):
    delivery_batch = models.ForeignKey(SalesOrderDeliveryBatch, on_delete=models.PROTECT, related_name="lines")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="delivery_batch_lines")
    quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])

    class Meta:
        db_table = "sales_order_delivery_batch_line"
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_batch", "sales_order_line"],
                name="sales_order_batch_product_uniq",
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="sales_order_batch_qty_positive"),
        ]

    def clean(self):
        super().clean()
        if self.delivery_batch.sales_order_id != self.sales_order_line.sales_order_id:
            raise ValidationError("交付批次明细必须属于同一张销售订单。")


class SalesOrderEvidence(TimeStampedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="evidence_links")
    business_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="sales_order_evidence_links",
    )
    evidence_type = models.CharField(max_length=50, default="CUSTOMER_CONFIRMATION")
    caption = models.CharField(max_length=250, blank=True)
    uploaded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_order_evidence_uploaded",
    )

    class Meta:
        db_table = "sales_order_evidence"
        constraints = [
            models.UniqueConstraint(fields=["sales_order", "business_file"], name="sales_order_evidence_uniq"),
        ]


class SalesOrderPriceException(TimeStampedModel):
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="price_exceptions")
    requested_unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    quoted_unit_price_snapshot = models.DecimalField(max_digits=18, decimal_places=4)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=PriceExceptionStatus.choices, default=PriceExceptionStatus.PENDING)
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="sales_order_price_exceptions_requested",
    )
    decided_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_price_exceptions_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "sales_order_price_exception"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=PriceExceptionStatus.values), name="sales_order_price_exc_status_valid"),
            models.CheckConstraint(condition=Q(requested_unit_price__gte=0), name="sales_order_price_exc_price_nonneg"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at", "-id"], name="sales_order_price_exc_idx"),
        ]


class SalesOrderVersion(TimeStampedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    change_reason = models.TextField(blank=True)
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_versions_confirmed",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sales_order_version"
        ordering = ["sales_order", "-version_number", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["sales_order", "version_number"], name="sales_order_version_uniq"),
        ]


class SalesOrderCollaborationEvent(TimeStampedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="collaboration_events")
    delivery_batch = models.ForeignKey(
        SalesOrderDeliveryBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collaboration_events",
    )
    event_type = models.CharField(max_length=40, choices=CollaborationEventType.choices)
    source_type = models.CharField(
        max_length=20,
        choices=CollaborationEventSource.choices,
        default=CollaborationEventSource.MANUAL,
    )
    status = models.CharField(
        max_length=20,
        choices=CollaborationEventStatus.choices,
        default=CollaborationEventStatus.PENDING,
    )
    title = models.CharField(max_length=200)
    note = models.TextField(blank=True)
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    occurred_at = models.DateTimeField()
    evidence_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_collaboration_events",
    )
    recorded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_order_collaboration_events_recorded",
    )

    class Meta:
        db_table = "sales_order_collaboration_event"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(event_type__in=CollaborationEventType.values), name="sales_order_event_type_valid"),
            models.CheckConstraint(condition=Q(source_type__in=CollaborationEventSource.values), name="sales_order_event_source_valid"),
            models.CheckConstraint(condition=Q(status__in=CollaborationEventStatus.values), name="sales_order_event_status_valid"),
            models.CheckConstraint(
                condition=Q(quantity__isnull=True) | Q(quantity__gt=0),
                name="sales_order_event_quantity_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["sales_order", "event_type", "-occurred_at"], name="sales_order_event_order_idx"),
            models.Index(fields=["delivery_batch", "event_type", "-occurred_at"], name="sales_order_event_batch_idx"),
        ]

    def clean(self):
        super().clean()
        if self.delivery_batch_id and self.delivery_batch.sales_order_id != self.sales_order_id:
            raise ValidationError({"delivery_batch": "协同事件批次必须属于当前销售订单。"})
