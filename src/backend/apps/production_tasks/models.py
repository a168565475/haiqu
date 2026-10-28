from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import ArchivableModel, TimeStampedModel, uppercase_code_validator


class ProductionTaskStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PENDING_VALIDATION = "PENDING_VALIDATION", "待校验"
    READY = "READY", "已接单"
    IN_PRODUCTION = "IN_PRODUCTION", "生产中"
    PAUSED = "PAUSED", "已暂停"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class OrderSource(models.TextChoices):
    NEW = "NEW", "新下单"
    REPEAT = "REPEAT", "返单"


class DeliveryMethod(models.TextChoices):
    SINGLE = "SINGLE", "一次交货"
    SPLIT = "SPLIT", "分批交货"


class ProductionPriority(models.TextChoices):
    LOW = "LOW", "低"
    NORMAL = "NORMAL", "普通"
    HIGH = "HIGH", "高"
    URGENT = "URGENT", "紧急"


class ProductionRunBatchStatus(models.TextChoices):
    PLANNED = "PLANNED", "待生产"
    IN_PROGRESS = "IN_PROGRESS", "生产中"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class ProductionTask(ArchivableModel):
    task_number = models.CharField(max_length=50, db_index=True, validators=[uppercase_code_validator])
    contract_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    order_source = models.CharField(max_length=20, choices=OrderSource.choices)
    order_number = models.CharField(max_length=100)
    sales_order = models.ForeignKey(
        "sales_orders.SalesOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_tasks",
    )
    sales_order_delivery_batch = models.ForeignKey(
        "sales_orders.SalesOrderDeliveryBatch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_tasks",
    )
    sales_order_line = models.ForeignKey(
        "sales_orders.SalesOrderLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_tasks",
    )
    source_request_key = models.UUIDField(null=True, blank=True, unique=True)
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_tasks",
    )
    order_date = models.DateField()
    delivery_date = models.DateField()
    salesperson = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="sold_production_tasks",
    )
    followers = models.ManyToManyField(
        "organizations.Employee",
        through="ProductionTaskFollower",
        related_name="followed_production_tasks",
        blank=True,
    )
    currency = models.ForeignKey(
        "reference_data.Currency",
        on_delete=models.PROTECT,
        related_name="production_tasks",
    )
    includes_tax = models.BooleanField()
    tax_rate = models.PositiveSmallIntegerField(null=True, blank=True, choices=[(3, "3%"), (5, "5%"), (7, "7%")])
    order_tolerance_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    is_repeat_order = models.BooleanField()
    preproduction_sample_required = models.BooleanField()
    delivery_method = models.CharField(max_length=20, choices=DeliveryMethod.choices)
    special_requirements_html = models.TextField(blank=True)
    packaging_method_html = models.TextField(blank=True)
    freight_amount = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    other_fee_amount = models.DecimalField(
        max_digits=22,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    status = models.CharField(
        max_length=30,
        choices=ProductionTaskStatus.choices,
        default=ProductionTaskStatus.DRAFT,
    )
    status_reason = models.CharField(max_length=500, blank=True)
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    production_priority = models.CharField(
        max_length=20,
        choices=ProductionPriority.choices,
        default=ProductionPriority.NORMAL,
    )
    production_batch_number = models.CharField(max_length=100, blank=True)
    planner = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="planned_production_tasks",
    )
    accepted_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_production_tasks",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    start_waiver_reason = models.TextField(blank=True)
    start_waiver_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_start_waivers",
    )
    start_waiver_at = models.DateTimeField(null=True, blank=True)
    actual_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    actual_good_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    excess_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_production_tasks",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "production_task"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("view_all_productiontask", "可查看全部生产任务单"),
            ("submit_productiontask", "可提交生产任务单校验"),
            ("confirm_productiontask", "可确认生产任务单"),
            ("start_productiontask", "可开始生产任务单"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task_number"], condition=Q(archived_at__isnull=True),
                name="prod_task_active_number_uniq",
            ),
            models.CheckConstraint(
                condition=Q(tax_rate__isnull=True) | Q(includes_tax=True, tax_rate__in=[3, 5, 7]),
                name="prod_task_tax_rate_valid",
            ),
            models.CheckConstraint(condition=Q(status__in=ProductionTaskStatus.values), name="prod_task_status_valid"),
            models.CheckConstraint(condition=Q(order_source__in=OrderSource.values), name="prod_task_source_valid"),
            models.CheckConstraint(condition=Q(delivery_method__in=DeliveryMethod.values), name="prod_task_delivery_valid"),
            models.CheckConstraint(
                condition=Q(order_tolerance_percent__gte=0, order_tolerance_percent__lte=100),
                name="prod_task_tolerance_range",
            ),
            models.CheckConstraint(condition=Q(delivery_date__gte=F("order_date")), name="prod_task_dates_valid"),
            models.CheckConstraint(condition=Q(freight_amount__gte=0), name="prod_task_freight_nonnegative"),
            models.CheckConstraint(condition=Q(other_fee_amount__gte=0), name="prod_task_other_fee_nonnegative"),
            models.CheckConstraint(condition=Q(production_priority__in=ProductionPriority.values), name="prod_task_priority_valid"),
            models.CheckConstraint(condition=Q(actual_quantity__gte=0), name="prod_task_actual_qty_nonnegative"),
            models.CheckConstraint(condition=Q(actual_good_quantity__gte=0), name="prod_task_good_qty_nonnegative"),
            models.CheckConstraint(condition=Q(excess_quantity__gte=0), name="prod_task_excess_qty_nonnegative"),
            models.CheckConstraint(
                condition=Q(planned_start_date__isnull=True)
                | Q(planned_end_date__isnull=True)
                | Q(planned_end_date__gte=F("planned_start_date")),
                name="prod_task_plan_dates_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="prod_task_status_idx"),
            models.Index(fields=["customer_account", "-created_at"], name="prod_task_customer_idx"),
            models.Index(fields=["salesperson", "-created_at"], name="prod_task_sales_idx"),
        ]

    def clean(self):
        super().clean()
        if self.delivery_date and self.order_date and self.delivery_date < self.order_date:
            raise ValidationError({"delivery_date": "交期日期不能早于下单日期。"})
        if self.sales_order_id or self.sales_order_delivery_batch_id or self.sales_order_line_id:
            if not self.sales_order_id or not self.sales_order_delivery_batch_id:
                raise ValidationError("销售来源生产订单必须同时关联销售订单和交付批次。")
        if self.sales_order_delivery_batch_id and self.sales_order_delivery_batch.sales_order_id != self.sales_order_id:
            raise ValidationError({"sales_order_delivery_batch": "交付批次不属于来源销售订单。"})
        if self.sales_order_line_id and self.sales_order_line.sales_order_id != self.sales_order_id:
            raise ValidationError({"sales_order_line": "订单明细不属于来源销售订单。"})

    def __str__(self):
        return self.task_number


class ProductionTaskFollower(TimeStampedModel):
    production_task = models.ForeignKey(
        ProductionTask,
        on_delete=models.PROTECT,
        related_name="follower_links",
    )
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="production_task_follower_links",
    )

    class Meta:
        db_table = "production_task_follower"
        constraints = [
            models.UniqueConstraint(fields=["production_task", "employee"], name="prod_task_follower_unique"),
        ]


class ProductionTaskProduct(TimeStampedModel):
    production_task = models.ForeignKey(ProductionTask, on_delete=models.PROTECT, related_name="products")
    line_number = models.PositiveIntegerField()
    product = models.ForeignKey(
        "products.ProductInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_lines",
    )
    product_category = models.ForeignKey(
        "reference_data.ProductCategory",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_line_categories",
    )
    sales_order_delivery_batch_line = models.ForeignKey(
        "sales_orders.SalesOrderDeliveryBatchLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    product_number_snapshot = models.CharField(max_length=100, blank=True)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    item_number_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    specification_snapshot = models.CharField(max_length=300)
    # 销售/BOM 之前允许只记录客户输入的产品信息；这些字段保留原始输入，
    # 即使后续绑定了产品主数据也不覆盖历史客户描述。
    customer_product_name_snapshot = models.CharField(max_length=200, blank=True)
    customer_specification_snapshot = models.CharField(max_length=300, blank=True)
    customer_color_snapshot = models.CharField(max_length=200, blank=True)
    material_snapshot = models.TextField(blank=True)
    image_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    product_color = models.ForeignKey(
        "reference_data.ProductColor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    color_card_snapshot = models.CharField(max_length=100, blank=True)
    color_name_snapshot = models.CharField(max_length=200, blank=True)
    color_code_snapshot = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    currency = models.ForeignKey(
        "reference_data.Currency",
        on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    total_amount = models.DecimalField(max_digits=22, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    exchange_rate = models.DecimalField(max_digits=25, decimal_places=8, validators=[MinValueValidator(Decimal("0.00000001"))])
    exchange_rate_record = models.ForeignKey(
        "reference_data.ExchangeRate", null=True, blank=True, on_delete=models.PROTECT,
        related_name="production_task_products",
    )
    exchange_rate_snapshot = models.JSONField(default=dict, blank=True)
    special_requirements = models.TextField(blank=True)
    packaging_method = models.TextField(blank=True)

    class Meta:
        db_table = "production_task_product"
        ordering = ["production_task", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["production_task", "line_number"], name="prod_task_product_line_unique"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="prod_task_product_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="prod_task_product_price_nonnegative"),
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="prod_task_product_total_nonnegative"),
            models.CheckConstraint(condition=Q(exchange_rate__gt=0), name="prod_task_product_rate_positive"),
        ]
        indexes = [
            models.Index(fields=["sales_order_delivery_batch_line", "id"], name="prod_task_source_line_idx"),
            models.Index(fields=["product", "id"], name="prod_task_product_idx"),
        ]

    def clean(self):
        super().clean()
        if not self.sales_order_delivery_batch_line_id:
            return
        source_line = self.sales_order_delivery_batch_line
        if self.production_task.sales_order_delivery_batch_id != source_line.delivery_batch_id:
            raise ValidationError({"sales_order_delivery_batch_line": "产品来源行必须属于生产任务选择的销售交付批次。"})
        source_product_id = source_line.sales_order_line.product_id
        if source_product_id and self.product_id != source_product_id:
            raise ValidationError({"product": "销售来源产品不可替换。"})


class ProductionTaskProductImage(TimeStampedModel):
    product_line = models.ForeignKey(
        ProductionTaskProduct,
        on_delete=models.PROTECT,
        related_name="images",
    )
    line_number = models.PositiveIntegerField()
    image_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="production_task_product_images",
    )

    class Meta:
        db_table = "production_task_product_image"
        ordering = ["product_line", "line_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["product_line", "line_number"],
                name="prod_task_product_image_line_unique",
            ),
            models.UniqueConstraint(
                fields=["product_line", "image_file"],
                name="prod_task_product_image_file_unique",
            ),
        ]


class ProductionTaskDetail(TimeStampedModel):
    product_line = models.ForeignKey(
        ProductionTaskProduct,
        on_delete=models.PROTECT,
        related_name="details",
    )
    line_number = models.PositiveIntegerField()
    template_key = models.CharField(max_length=64, blank=True)
    detail_type = models.CharField(max_length=100)
    category_label = models.CharField(max_length=100, blank=True)
    is_selected = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    image_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_task_details",
    )

    class Meta:
        db_table = "production_task_detail"
        ordering = ["product_line", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["product_line", "line_number"], name="prod_task_detail_line_unique"),
        ]


class ProductionDeliveryBatch(TimeStampedModel):
    production_task = models.ForeignKey(ProductionTask, on_delete=models.PROTECT, related_name="delivery_batches")
    line_number = models.PositiveIntegerField()
    quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    delivery_date = models.DateField()
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "production_delivery_batch"
        ordering = ["production_task", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["production_task", "line_number"], name="prod_task_batch_line_unique"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="prod_task_batch_qty_positive"),
        ]


class ProductionRunBatch(TimeStampedModel):
    production_task = models.ForeignKey(ProductionTask, on_delete=models.PROTECT, related_name="run_batches")
    batch_number = models.CharField(max_length=100)
    planned_quantity = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    actual_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    good_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    status = models.CharField(
        max_length=20,
        choices=ProductionRunBatchStatus.choices,
        default=ProductionRunBatchStatus.PLANNED,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "production_run_batch"
        ordering = ["production_task", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["production_task", "batch_number"], name="prod_run_batch_number_uniq"),
            models.CheckConstraint(condition=Q(planned_quantity__gt=0), name="prod_run_batch_plan_qty_positive"),
            models.CheckConstraint(condition=Q(actual_quantity__gte=0), name="prod_run_batch_actual_qty_nonnegative"),
            models.CheckConstraint(condition=Q(good_quantity__gte=0), name="prod_run_batch_good_qty_nonnegative"),
            models.CheckConstraint(condition=Q(status__in=ProductionRunBatchStatus.values), name="prod_run_batch_status_valid"),
        ]


from .cost_models import ProductionTaskExpense  # noqa: E402,F401
