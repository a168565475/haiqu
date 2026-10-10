from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel, uppercase_code_validator


class FactoryStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    DISABLED = "DISABLED", "停用"


class PaymentCycle(models.TextChoices):
    MONTHLY = "MONTHLY", "月结"


class OutsourcingOrderStatus(models.TextChoices):
    PENDING_DISPATCH = "PENDING_DISPATCH", "待外发"
    PROCESSING = "PROCESSING", "加工中"
    PARTIAL_RETURN = "PARTIAL_RETURN", "部分回货"
    CLOSED = "CLOSED", "已结清"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class OutsourcingFactory(TimeStampedModel):
    factory_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    name = models.CharField(max_length=255)
    processing_type = models.CharField(max_length=200)
    estimated_output = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    estimated_output_unit = models.CharField(max_length=50, blank=True)
    estimated_output_period = models.CharField(max_length=50, blank=True)
    contact_name = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=100)
    address = models.CharField(max_length=500)
    remark = models.TextField(blank=True)
    payment_cycle = models.CharField(max_length=20, choices=PaymentCycle.choices, default=PaymentCycle.MONTHLY)
    status = models.CharField(max_length=20, choices=FactoryStatus.choices, default=FactoryStatus.ACTIVE)
    version = models.PositiveIntegerField(default=1)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="created_outsourcing_factories"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="updated_outsourcing_factories"
    )

    class Meta:
        db_table = "outsourcing_factory"
        ordering = ["-updated_at", "-id"]
        permissions = [
            ("view_all_outsourcingfactory", "可查看全部加工厂"),
            ("disable_outsourcingfactory", "可停用加工厂"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=FactoryStatus.values), name="outs_factory_status_valid"),
            models.CheckConstraint(condition=Q(version__gt=0), name="outs_factory_version_positive"),
            models.CheckConstraint(
                condition=Q(estimated_output__isnull=True) | Q(estimated_output__gte=0),
                name="outs_factory_output_nonnegative",
            ),
        ]
        indexes = [models.Index(fields=["status", "name", "id"], name="outs_factory_status_name_idx")]

    def delete(self, *args, **kwargs):
        raise ValidationError("加工厂不允许物理删除，请使用停用。")


class OutsourcingFactoryCraft(TimeStampedModel):
    factory = models.ForeignKey(OutsourcingFactory, on_delete=models.PROTECT, related_name="craft_links")
    craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT, related_name="outsourcing_factories")
    craft_name_snapshot = models.CharField(max_length=100)

    class Meta:
        db_table = "outsourcing_factory_craft"
        ordering = ["factory", "craft_name_snapshot", "id"]
        constraints = [
            models.UniqueConstraint(fields=["factory", "craft"], name="outs_factory_craft_unique"),
        ]
        indexes = [models.Index(fields=["craft", "factory"], name="outs_factory_craft_idx")]


class OutsourcingOrder(TimeStampedModel):
    stock_mode = models.CharField(max_length=16, choices=[("LEGACY", "历史库存"), ("PUBLIC_V2", "公共库存")], default="LEGACY")
    order_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    schedule = models.ForeignKey(
        "production_scheduling.ProductionSchedule", on_delete=models.PROTECT, related_name="outsourcing_orders"
    )
    craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT, related_name="outsourcing_orders")
    craft_name_snapshot = models.CharField(max_length=100)
    craft_code_snapshot = models.CharField(max_length=30, blank=True)
    delivery_date = models.DateField()
    status = models.CharField(
        max_length=30, choices=OutsourcingOrderStatus.choices,
        default=OutsourcingOrderStatus.PENDING_DISPATCH,
    )
    source_snapshot = models.JSONField(default=dict)
    source_revision_hash = models.CharField(max_length=64)
    remark = models.TextField(blank=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="created_outsourcing_orders"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="updated_outsourcing_orders"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="cancelled_outsourcing_orders",
    )
    cancel_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_request_id = models.UUIDField(null=True, blank=True, unique=True)
    completion_payload_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "outsourcing_order"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("view_all_outsourcingorder", "可查看全部外发单"),
            ("cancel_outsourcingorder", "可取消外发单"),
            ("confirm_dispatch_outsourcingorder", "可确认委外发料"),
            ("confirm_return_outsourcingorder", "可确认委外回厂"),
            ("return_raw_outsourcingorder", "可确认外发原料退回"),
            ("reconcile_outsourcingorder", "可登记外发投入与损耗"),
            ("complete_outsourcingorder", "可结清外发单"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=OutsourcingOrderStatus.values), name="outs_order_status_valid"),
            models.CheckConstraint(condition=Q(stock_mode__in=["LEGACY", "PUBLIC_V2"]), name="outs_order_stock_mode_valid"),
            models.CheckConstraint(condition=Q(version__gt=0), name="outs_order_version_positive"),
        ]
        indexes = [
            models.Index(fields=["status", "delivery_date", "id"], name="outs_order_status_date_idx"),
            models.Index(fields=["craft", "-created_at", "id"], name="outs_order_craft_created_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("外发单不允许物理删除。")


class OutsourcingOrderProduct(TimeStampedModel):
    order = models.ForeignKey(OutsourcingOrder, on_delete=models.PROTECT, related_name="products")
    schedule_product = models.ForeignKey(
        "production_scheduling.ProductionScheduleProduct", on_delete=models.PROTECT,
        related_name="outsourcing_order_products",
    )
    bom = models.ForeignKey("boms.Bom", on_delete=models.PROTECT, related_name="outsourcing_order_products")
    line_number = models.PositiveIntegerField()
    product_snapshot = models.JSONField(default=dict)
    order_quantity_snapshot = models.PositiveBigIntegerField()
    planned_quantity_snapshot = models.PositiveBigIntegerField()
    bom_number_snapshot = models.CharField(max_length=80)
    bom_version_snapshot = models.PositiveIntegerField()
    source_revision_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "outsourcing_order_product"
        ordering = ["order", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "schedule_product"], name="outs_order_product_unique"),
            models.UniqueConstraint(fields=["order", "line_number"], name="outs_order_product_line_unique"),
        ]


class OutsourcingProcessingItem(TimeStampedModel):
    order_product = models.ForeignKey(OutsourcingOrderProduct, on_delete=models.PROTECT, related_name="processing_items")
    bom_line = models.ForeignKey("boms.BomLine", on_delete=models.PROTECT, related_name="outsourcing_processing_items")
    component_key = models.CharField(max_length=100)
    line_number = models.PositiveIntegerField()
    quantity = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="outsourcing_processing_items",
    )
    unit_snapshot = models.CharField(max_length=50)
    component_snapshot = models.JSONField(default=dict)
    processing_requirement = models.TextField(blank=True)

    class Meta:
        db_table = "outsourcing_processing_item"
        ordering = ["order_product", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order_product", "bom_line"], name="outs_processing_bom_line_unique"),
            models.UniqueConstraint(fields=["order_product", "line_number"], name="outs_processing_line_unique"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="outs_processing_qty_positive"),
        ]


class OutsourcingFactoryAllocation(TimeStampedModel):
    processing_item = models.ForeignKey(
        OutsourcingProcessingItem, on_delete=models.PROTECT, related_name="allocations"
    )
    factory = models.ForeignKey(OutsourcingFactory, on_delete=models.PROTECT, related_name="allocations")
    allocated_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    unit_price = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    factory_snapshot = models.JSONField(default=dict)
    remark = models.TextField(blank=True)
    input_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    input_unit_snapshot = models.CharField(max_length=50, blank=True)
    conversion_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "outsourcing_factory_allocation"
        ordering = ["processing_item", "factory", "id"]
        constraints = [
            models.UniqueConstraint(fields=["processing_item", "factory"], name="outs_allocation_factory_unique"),
            models.CheckConstraint(condition=Q(allocated_quantity__gte=0), name="outs_allocation_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="outs_allocation_price_nonnegative"),
        ]
        indexes = [models.Index(fields=["factory", "processing_item"], name="outs_allocation_factory_idx")]


class OutsourcingMaterialItem(TimeStampedModel):
    allocation = models.ForeignKey(
        OutsourcingFactoryAllocation, on_delete=models.PROTECT, related_name="material_items"
    )
    bom_material_line = models.ForeignKey(
        "boms.BomLine", on_delete=models.PROTECT, related_name="outsourcing_material_items"
    )
    line_number = models.PositiveIntegerField()
    material_snapshot = models.JSONField(default=dict)
    unit_text = models.CharField(max_length=50)
    reference_order_quantity_sets = models.PositiveBigIntegerField()
    consumption_basis = models.CharField(max_length=20, default="UNPARSED")
    consumption_per_set = models.DecimalField(max_digits=22, decimal_places=8, null=True, blank=True)
    reference_required_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    planned_issue_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    difference_reason = models.TextField(blank=True)
    remark = models.TextField(blank=True)
    planned_piece_count = models.PositiveBigIntegerField(null=True, blank=True)
    planned_meters = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    conversion_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "outsourcing_material_item"
        ordering = ["allocation", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["allocation", "bom_material_line"], name="outs_material_bom_line_unique"),
            models.UniqueConstraint(fields=["allocation", "line_number"], name="outs_material_line_unique"),
            models.CheckConstraint(condition=Q(planned_issue_quantity__gt=0), name="outs_material_qty_positive"),
        ]


class OutsourcingDispatch(TimeStampedModel):
    dispatch_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        validators=[uppercase_code_validator],
    )
    order = models.OneToOneField(
        OutsourcingOrder,
        on_delete=models.PROTECT,
        related_name="dispatch_record",
    )
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    dispatch_date = models.DateField(default=timezone.localdate)
    remark = models.TextField(blank=True)
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="confirmed_outsourcing_dispatches",
    )
    confirmed_at = models.DateTimeField()

    class Meta:
        db_table = "outsourcing_dispatch"
        ordering = ["-confirmed_at", "-id"]


class OutsourcingDispatchLine(TimeStampedModel):
    dispatch = models.ForeignKey(OutsourcingDispatch, on_delete=models.PROTECT, related_name="lines")
    material_item = models.ForeignKey(
        OutsourcingMaterialItem,
        on_delete=models.PROTECT,
        related_name="dispatch_lines",
    )
    requirement = models.ForeignKey(
        "material_issues.OrderMaterialRequirement",
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    inbound_line = models.ForeignKey(
        "inventory.MaterialInboundLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    zone = models.ForeignKey(
        "inventory.WarehouseZone",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    location = models.ForeignKey(
        "inventory.WarehouseLocation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outsourcing_dispatch_lines",
    )
    source_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    material_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    conversion_factor = models.DecimalField(
        max_digits=22,
        decimal_places=8,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    source_unit_snapshot = models.CharField(max_length=50, blank=True)
    conversion_evidence = models.TextField(blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    match_method = models.CharField(max_length=30, default="REFERENCE_ID")
    match_reason = models.TextField(blank=True)
    issued_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    snapshot = models.JSONField(default=dict)
    issued_piece_count = models.PositiveBigIntegerField(null=True, blank=True)
    issued_meters = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    stock_balance = models.ForeignKey("inventory.MaterialStockBalance", null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="outsourcing_dispatch_lines")
    public_stock_balance = models.ForeignKey("inventory.PublicStockBalance", null=True, blank=True,
        on_delete=models.PROTECT, related_name="outsourcing_dispatch_lines")
    public_stock_movement = models.OneToOneField("inventory.PublicStockMovement", null=True, blank=True,
        on_delete=models.PROTECT, related_name="outsourcing_dispatch_line")

    class Meta:
        db_table = "outsourcing_dispatch_line"
        ordering = ["dispatch", "material_item", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(issued_quantity__gt=0), name="outs_dispatch_line_qty_positive"),
            models.UniqueConstraint(
                fields=["dispatch", "material_item", "inbound_line"],
                condition=Q(inbound_line__isnull=False),
                name="outs_dispatch_source_unique",
            ),
        ]


class OutsourcingReturn(TimeStampedModel):
    return_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    order = models.ForeignKey(OutsourcingOrder, on_delete=models.PROTECT, related_name="return_records")
    factory = models.ForeignKey(
        OutsourcingFactory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="return_records",
    )
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    zone = models.ForeignKey(
        "inventory.WarehouseZone",
        on_delete=models.PROTECT,
        related_name="outsourcing_returns",
    )
    defective_zone = models.ForeignKey(
        "inventory.WarehouseZone",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="defective_outsourcing_returns",
    )
    received_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_outsourcing_returns",
    )
    return_date = models.DateField(default=timezone.localdate)
    delivery_note_number = models.CharField(max_length=100, blank=True)
    factory_snapshot = models.JSONField(default=dict, blank=True)
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="confirmed_outsourcing_returns",
    )
    confirmed_at = models.DateTimeField()
    remark = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "outsourcing_return"
        ordering = ["-confirmed_at", "-id"]
        indexes = [models.Index(fields=["order", "-confirmed_at"], name="outs_return_order_time_idx")]


class OutsourcingReturnLine(TimeStampedModel):
    return_record = models.ForeignKey(OutsourcingReturn, on_delete=models.PROTECT, related_name="lines")
    allocation = models.ForeignKey(
        OutsourcingFactoryAllocation,
        on_delete=models.PROTECT,
        related_name="return_lines",
    )
    returned_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    quality = models.CharField(
        max_length=20,
        choices=[("AVAILABLE", "合格可用"), ("DEFECTIVE", "不良隔离")],
    )
    semi_finished_balance = models.ForeignKey(
        "inventory.SemiFinishedStockBalance",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="outsourcing_return_lines",
    )
    snapshot = models.JSONField(default=dict)

    public_stock_movement = models.OneToOneField("inventory.PublicStockMovement", null=True, blank=True,
        on_delete=models.PROTECT, related_name="outsourcing_return_line")

    class Meta:
        db_table = "outsourcing_return_line"
        ordering = ["return_record", "allocation", "quality", "id"]
        constraints = [
            models.CheckConstraint(condition=(
                Q(semi_finished_balance__isnull=False, public_stock_movement__isnull=True)
                | Q(semi_finished_balance__isnull=True, public_stock_movement__isnull=False)
            ), name="outs_return_stock_route_xor"),
            models.UniqueConstraint(
                fields=["return_record", "allocation", "quality"],
                name="outs_return_line_identity_uniq",
            ),
            models.CheckConstraint(condition=Q(returned_quantity__gt=0), name="outs_return_line_qty_positive"),
            models.CheckConstraint(
                condition=Q(quality__in=["AVAILABLE", "DEFECTIVE"]),
                name="outs_return_line_quality_valid",
            ),
        ]


class OutsourcingRawReturn(TimeStampedModel):
    order = models.ForeignKey(OutsourcingOrder, on_delete=models.PROTECT, related_name="raw_return_records")
    factory = models.ForeignKey(OutsourcingFactory, on_delete=models.PROTECT)
    request_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    reason = models.TextField()
    actor = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "outsourcing_raw_return"


class OutsourcingRawReturnLine(TimeStampedModel):
    record = models.ForeignKey(OutsourcingRawReturn, on_delete=models.PROTECT, related_name="lines")
    dispatch_line = models.ForeignKey(OutsourcingDispatchLine, on_delete=models.PROTECT, related_name="raw_returns")
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)
    piece_quantity_equivalent = models.PositiveBigIntegerField(null=True, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "outsourcing_raw_return_line"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="outs_raw_return_qty_positive"),
            models.UniqueConstraint(fields=["record", "dispatch_line"], name="outs_raw_return_source_unique"),
        ]


class OutsourcingReconciliation(TimeStampedModel):
    order = models.ForeignKey(OutsourcingOrder, on_delete=models.PROTECT, related_name="reconciliation_records")
    request_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    actor = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "outsourcing_reconciliation"


class OutsourcingReconciliationEntry(TimeStampedModel):
    record = models.ForeignKey(OutsourcingReconciliation, on_delete=models.PROTECT, related_name="entries")
    allocation = models.ForeignKey(OutsourcingFactoryAllocation, on_delete=models.PROTECT, related_name="reconciliation_entries")
    dispatch_line = models.ForeignKey(OutsourcingDispatchLine, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="reconciliation_entries")
    kind = models.CharField(max_length=20, choices=[("RAW_INPUT", "投入加工"), ("RAW_LOSS", "原料损失"), ("OUTPUT_SCRAP", "加工报废")])
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_snapshot = models.CharField(max_length=50)
    reason = models.TextField()
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "outsourcing_reconciliation_entry"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="outs_reconcile_qty_positive"),
            models.CheckConstraint(condition=Q(kind__in=["RAW_INPUT", "RAW_LOSS", "OUTPUT_SCRAP"]), name="outs_reconcile_kind_valid"),
            models.CheckConstraint(condition=(Q(kind="OUTPUT_SCRAP", dispatch_line__isnull=True)
                | Q(kind__in=["RAW_INPUT", "RAW_LOSS"], dispatch_line__isnull=False)), name="outs_reconcile_source_required"),
        ]


from .tube_models import (TubeOutsourcingAction, TubeOutsourcingLine, TubeOutsourcingOrder,
                         TubeOutsourcingReceipt, TubeOutsourcingReceiptLine, TubeSourceKind)  # noqa: E402,F401
