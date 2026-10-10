from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Floor
from django.utils import timezone

from apps.core.models import TimeStampedModel, uppercase_code_validator


class RecordStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "正常"
    DISABLED = "DISABLED", "停用"


class WarehouseType(models.TextChoices):
    MATERIAL = "MATERIAL", "材料仓"
    SEMI_FINISHED = "SEMI_FINISHED", "半成品仓"
    FINISHED = "FINISHED", "成品仓"
    DEFECTIVE = "DEFECTIVE", "不良品仓"


class MaterialInboundStatus(models.TextChoices):
    PENDING_QUALITY = "PENDING_QUALITY", "待品质确认"
    CONFIRMED = "CONFIRMED", "已入库"


class NoPhysicalDeleteMixin:
    def delete(self, *args, **kwargs):
        raise ValidationError("仓库基础资料不允许物理删除，请使用停用状态。")


class Warehouse(NoPhysicalDeleteMixin, TimeStampedModel):
    warehouse_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    warehouse_name = models.CharField(max_length=150)
    warehouse_type = models.CharField(max_length=30, choices=WarehouseType.choices)
    address = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    responsible_person_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=100, blank=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="created_warehouses"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="updated_warehouses"
    )

    class Meta:
        db_table = "inventory_warehouse"
        ordering = ["warehouse_number", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(warehouse_type__in=WarehouseType.values), name="inv_warehouse_type_valid"),
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="inv_warehouse_status_valid"),
        ]
        indexes = [models.Index(fields=["warehouse_type", "status"], name="inv_wh_type_status_idx")]

    def __str__(self):
        return f"{self.warehouse_number} - {self.warehouse_name}"


class WarehouseZone(NoPhysicalDeleteMixin, TimeStampedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="zones")
    zone_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="created_warehouse_zones"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="updated_warehouse_zones"
    )

    class Meta:
        db_table = "inventory_warehouse_zone"
        ordering = ["warehouse__warehouse_number", "zone_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "zone_name"], name="inv_zone_warehouse_name_uniq"),
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="inv_zone_status_valid"),
        ]
        indexes = [models.Index(fields=["warehouse", "status"], name="inv_zone_wh_status_idx")]

    def __str__(self):
        return f"{self.warehouse.warehouse_number} / {self.zone_name}"


class WarehouseLocation(NoPhysicalDeleteMixin, TimeStampedModel):
    zone = models.ForeignKey(WarehouseZone, on_delete=models.PROTECT, related_name="locations")
    location_number = models.CharField(max_length=100)
    capacity_box_slots = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="created_warehouse_locations"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="updated_warehouse_locations"
    )

    class Meta:
        db_table = "inventory_warehouse_location"
        ordering = ["zone__warehouse__warehouse_number", "zone__zone_name", "location_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["zone", "location_number"], name="inv_location_zone_number_uniq"),
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="inv_location_status_valid"),
            models.CheckConstraint(
                condition=Q(capacity_box_slots__isnull=True) | Q(capacity_box_slots__gt=0),
                name="inv_location_capacity_positive",
            ),
        ]
        indexes = [models.Index(fields=["zone", "status"], name="inv_location_zone_status_idx")]

    @property
    def unique_key(self):
        return f"{self.zone.warehouse.warehouse_number}{self.zone.zone_name}{self.location_number}"

    def clean(self):
        super().clean()
        if self.location_number.strip() == "-":
            raise ValidationError({"location_number": "“-”只代表库区记录，不能作为实际库位号。"})

    def __str__(self):
        return f"{self.zone} / {self.location_number}"


class FinishedGoodsReceiptSource(models.TextChoices):
    PRODUCTION_ORDER = "PRODUCTION_ORDER", "生产订单入库"
    SAMPLE_INVENTORY = "SAMPLE_INVENTORY", "样品入库"


class FinishedGoodsReceipt(TimeStampedModel):
    receipt_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    production_task_product = models.ForeignKey(
        "production_tasks.ProductionTaskProduct",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finished_goods_receipts",
    )
    source_type = models.CharField(
        max_length=30,
        choices=FinishedGoodsReceiptSource.choices,
        default=FinishedGoodsReceiptSource.PRODUCTION_ORDER,
    )
    source_document_number = models.CharField(max_length=100, blank=True)
    source_sample_inventory_line = models.OneToOneField(
        "samples.SampleInventoryLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finished_goods_receipt",
    )
    location = models.ForeignKey(WarehouseLocation, on_delete=models.PROTECT, related_name="finished_goods_receipts")
    supplier = models.ForeignKey(
        "procurement.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="finished_goods_receipts"
    )
    task_number_snapshot = models.CharField(max_length=50)
    order_number_snapshot = models.CharField(max_length=100)
    category_snapshot = models.CharField(max_length=150, blank=True)
    product_number_snapshot = models.CharField(max_length=100)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    product_name_pinyin_search = models.TextField(blank=True)
    item_number_snapshot = models.CharField(max_length=100)
    specification_snapshot = models.CharField(max_length=300, blank=True)
    actual_color = models.CharField(max_length=200)
    unit = models.ForeignKey("reference_data.ProductionUnit", on_delete=models.PROTECT, related_name="finished_goods_receipts")
    received_quantity = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    remaining_quantity = models.PositiveBigIntegerField()
    quantity_per_box = models.PositiveBigIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    box_count = models.PositiveBigIntegerField(null=True, blank=True)
    tail_quantity = models.PositiveBigIntegerField(null=True, blank=True)
    occupied_box_slots = models.PositiveBigIntegerField(null=True, blank=True)
    remaining_box_slots = models.PositiveBigIntegerField(null=True, blank=True)
    remark = models.TextField(blank=True)
    received_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="finished_goods_receipts"
    )
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inventory_finished_goods_receipt"
        ordering = ["-received_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(source_type__in=FinishedGoodsReceiptSource.values),
                name="inv_receipt_source_type_valid",
            ),
            models.CheckConstraint(condition=Q(received_quantity__gt=0), name="inv_receipt_qty_positive"),
            models.CheckConstraint(
                condition=Q(quantity_per_box__isnull=True) | Q(quantity_per_box__gt=0),
                name="inv_receipt_pack_positive",
            ),
            models.CheckConstraint(condition=Q(remaining_quantity__gte=0), name="inv_receipt_remaining_nonneg"),
            models.CheckConstraint(condition=Q(remaining_quantity__lte=models.F("received_quantity")), name="inv_receipt_remaining_lte"),
        ]
        indexes = [
            models.Index(fields=["production_task_product", "received_at"], name="inv_receipt_product_idx"),
            models.Index(fields=["location", "remaining_quantity"], name="inv_receipt_location_idx"),
        ]


class FinishedGoodsOutbound(TimeStampedModel):
    outbound_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    receiver_name = models.CharField(max_length=150, blank=True)
    used_for_order_number = models.CharField(max_length=100, blank=True)
    remark = models.TextField(blank=True)
    outbound_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="finished_goods_outbounds"
    )
    outbound_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inventory_finished_goods_outbound"
        ordering = ["-outbound_at", "-id"]


class FinishedGoodsOutboundLine(TimeStampedModel):
    outbound = models.ForeignKey(FinishedGoodsOutbound, on_delete=models.PROTECT, related_name="lines")
    receipt = models.ForeignKey(FinishedGoodsReceipt, on_delete=models.PROTECT, related_name="outbound_lines")
    outbound_quantity = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    quantity_per_box = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    box_count = models.PositiveBigIntegerField()
    tail_quantity = models.PositiveBigIntegerField()
    before_quantity = models.PositiveBigIntegerField()
    after_quantity = models.PositiveBigIntegerField()

    class Meta:
        db_table = "inventory_finished_goods_outbound_line"
        ordering = ["outbound", "id"]
        constraints = [
            models.UniqueConstraint(fields=["outbound", "receipt"], name="inv_outbound_receipt_uniq"),
            models.CheckConstraint(condition=Q(outbound_quantity__gt=0), name="inv_outbound_qty_positive"),
            models.CheckConstraint(condition=Q(quantity_per_box__gt=0), name="inv_outbound_pack_positive"),
            models.CheckConstraint(condition=Q(after_quantity__lte=models.F("before_quantity")), name="inv_outbound_after_lte"),
        ]


class MaterialInbound(TimeStampedModel):
    stock_mode = models.CharField(max_length=12, choices=[("LEGACY", "原有库存"), ("PUBLIC_V2", "公共库存")], default="LEGACY")
    inbound_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    client_request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    purchase_order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_inbounds",
    )
    inbound_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=30,
        choices=MaterialInboundStatus.choices,
        default=MaterialInboundStatus.PENDING_QUALITY,
    )
    remark = models.TextField(blank=True)
    received_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="material_inbounds",
    )
    quality_confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quality_confirmed_material_inbounds",
    )
    quality_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventory_material_inbound"
        ordering = ["-inbound_date", "-created_at", "-id"]
        permissions = [
            ("receive_material", "Can receive material inventory"),
            ("view_material_receipt", "Can view material receipt details"),
            ("quality_confirm_material", "Can confirm material quality"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(stock_mode__in=["LEGACY", "PUBLIC_V2"]), name="inv_inbound_stock_mode_valid"),
            models.CheckConstraint(
                condition=Q(status__in=MaterialInboundStatus.values),
                name="inv_material_inbound_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="inv_mat_inbound_status_idx"),
            models.Index(fields=["purchase_order", "-created_at"], name="inv_mat_inbound_po_idx"),
        ]


class MaterialMeasurementKind(models.TextChoices):
    PIPE = "PIPE", "管材根米"
    OTHER = "OTHER", "原有单位"


class MaterialInboundLine(TimeStampedModel):
    measurement_kind = models.CharField(max_length=10, choices=MaterialMeasurementKind.choices, default=MaterialMeasurementKind.OTHER)
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    received_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    accepted_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    return_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    inbound = models.ForeignKey(MaterialInbound, on_delete=models.PROTECT, related_name="lines")
    purchase_order_line = models.ForeignKey(
        "procurement.PurchaseOrderLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_inbound_lines",
    )
    raw_material_information = models.ForeignKey(
        "products.RawMaterialInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_inbound_lines",
    )
    zone = models.ForeignKey(
        WarehouseZone,
        on_delete=models.PROTECT,
        related_name="material_inbound_lines",
    )
    location = models.ForeignKey(
        WarehouseLocation,
        on_delete=models.PROTECT,
        related_name="material_inbound_lines",
        null=True,
        blank=True,
    )
    received_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    return_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    accepted_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quality_remark = models.TextField(blank=True)
    remark = models.TextField(blank=True)
    purchase_order_number_snapshot = models.CharField(max_length=50)
    production_task_number_snapshot = models.CharField(max_length=50)
    sales_order_number_snapshot = models.CharField(max_length=100, blank=True)
    supplier_number_snapshot = models.CharField(max_length=8, blank=True)
    supplier_name_snapshot = models.CharField(max_length=255, blank=True)
    bom_number_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=200)
    section_type_snapshot = models.CharField(max_length=20)
    section_title_snapshot = models.CharField(max_length=300)
    category_snapshot = models.CharField(max_length=150, blank=True)
    material_snapshot = models.CharField(max_length=200, blank=True)
    part_name_snapshot = models.CharField(max_length=300)
    specification_snapshot = models.CharField(max_length=500, blank=True)
    raw_material_snapshot = models.TextField(blank=True)
    material_attributes_snapshot = models.JSONField(default=dict, blank=True)
    source_unit_text_snapshot = models.CharField(max_length=50)
    purchased_quantity_snapshot = models.DecimalField(max_digits=18, decimal_places=4)
    material_pinyin_search = models.TextField(blank=True)

    class Meta:
        db_table = "inventory_material_inbound_line"
        ordering = ["inbound", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(purchase_order_line__isnull=False) | Q(raw_material_information__isnull=False),
                name="inv_mat_line_source_valid",
            ),
            models.CheckConstraint(
                condition=Q(received_quantity__gt=0),
                name="inv_material_inbound_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(purchased_quantity_snapshot__gt=0),
                name="inv_material_purchase_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(return_quantity__gte=0) & Q(return_quantity__lte=F("received_quantity")),
                name="inv_material_return_qty_valid",
            ),
            models.CheckConstraint(
                condition=Q(accepted_quantity=F("received_quantity") - F("return_quantity")),
                name="inv_material_accepted_qty_valid",
            ),
            models.CheckConstraint(
                condition=(Q(measurement_kind="OTHER", raw_bar_length_m__isnull=True, received_bar_count__isnull=True,
                             accepted_bar_count__isnull=True, return_bar_count__isnull=True)
                    | Q(measurement_kind="PIPE", raw_material_information__isnull=False, raw_bar_length_m__isnull=False,
                        raw_bar_length_m__gt=0, received_bar_count__isnull=False, received_bar_count__gt=0,
                        accepted_bar_count__isnull=False, return_bar_count__isnull=False,
                        received_bar_count=F("accepted_bar_count") + F("return_bar_count"),
                        received_quantity=F("received_bar_count") * F("raw_bar_length_m"),
                        accepted_quantity=F("accepted_bar_count") * F("raw_bar_length_m"),
                        return_quantity=F("return_bar_count") * F("raw_bar_length_m"))),
                name="inv_pipe_inbound_shape_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["purchase_order_line", "created_at"], name="inv_mat_po_line_idx"),
            models.Index(fields=["zone", "created_at"], name="inv_mat_zone_idx"),
            models.Index(fields=["location", "created_at"], name="inv_mat_location_idx"),
            models.Index(fields=["section_title_snapshot"], name="inv_mat_section_idx"),
        ]


class MaterialStockQuality(models.TextChoices):
    AVAILABLE = "AVAILABLE", "合格可用"
    DEFECTIVE = "DEFECTIVE", "不良隔离"


class MaterialStockDirection(models.TextChoices):
    IN = "IN", "入库"
    OUT = "OUT", "出库"


class MaterialStockBalance(TimeStampedModel):
    measurement_kind = models.CharField(max_length=10, choices=MaterialMeasurementKind.choices, default=MaterialMeasurementKind.OTHER)
    inbound_line = models.ForeignKey(MaterialInboundLine, on_delete=models.PROTECT, null=True, blank=True, related_name="pipe_balances")
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    """按稳定原料、库区、单位和品质维护的净库存余额。"""

    raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    zone = models.ForeignKey(WarehouseZone, on_delete=models.PROTECT, related_name="material_stock_balances")
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="material_stock_balances",
    )
    quality = models.CharField(
        max_length=20,
        choices=MaterialStockQuality.choices,
        default=MaterialStockQuality.AVAILABLE,
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "inventory_material_stock_balance"
        ordering = ["raw_material", "zone", "quality", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["raw_material", "zone", "unit", "quality"],
                condition=Q(measurement_kind="OTHER"),
                name="inv_mat_other_balance_uniq",
            ),
            models.UniqueConstraint(fields=["inbound_line", "zone", "quality"], condition=Q(measurement_kind="PIPE"), name="inv_pipe_batch_balance_uniq"),
            models.CheckConstraint(
                condition=(Q(measurement_kind="OTHER", inbound_line__isnull=True, raw_bar_length_m__isnull=True, meter_quantity__isnull=True)
                    | Q(measurement_kind="PIPE", inbound_line__isnull=False, raw_bar_length_m__isnull=False,
                        raw_bar_length_m__gt=0, meter_quantity__isnull=False, meter_quantity__gte=0,
                        meter_quantity=F("quantity") * F("raw_bar_length_m"))),
                name="inv_pipe_balance_shape_valid",
            ),
            models.CheckConstraint(condition=Q(measurement_kind="OTHER") | Q(quantity=Floor(F("quantity"))), name="inv_pipe_balance_whole_roots"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="inv_mat_balance_qty_nonnegative"),
            models.CheckConstraint(condition=Q(version__gt=0), name="inv_mat_balance_version_positive"),
            models.CheckConstraint(
                condition=Q(quality__in=MaterialStockQuality.values),
                name="inv_mat_balance_quality_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["raw_material", "quality", "unit"],
                name="inv_mat_balance_lookup_idx",
            ),
            models.Index(fields=["zone", "quality"], name="inv_mat_balance_zone_idx"),
        ]


class MaterialStockMovement(TimeStampedModel):
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    before_meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    after_meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    """只追加的材料库存流水；来源业务行与方向共同保证幂等。"""

    balance = models.ForeignKey(
        MaterialStockBalance,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    direction = models.CharField(max_length=10, choices=MaterialStockDirection.choices)
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    before_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    after_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    source_type = models.CharField(max_length=50)
    source_id = models.UUIDField()
    source_line_id = models.UUIDField()
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_stock_movements",
    )
    actor_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="material_stock_movements",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "inventory_material_stock_movement"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_line_id", "direction", "balance"],
                name="inv_mat_movement_source_uniq",
            ),
            models.UniqueConstraint(fields=["source_type", "source_line_id", "direction"],
                condition=Q(meter_quantity__isnull=False), name="inv_pipe_movement_source_uniq"),
            models.CheckConstraint(
                condition=(Q(meter_quantity__isnull=True, before_meter_quantity__isnull=True, after_meter_quantity__isnull=True)
                    | (Q(meter_quantity__isnull=False, meter_quantity__gt=0,
                         before_meter_quantity__isnull=False, before_meter_quantity__gte=0,
                         after_meter_quantity__isnull=False, after_meter_quantity__gte=0,
                         quantity=Floor(F("quantity")), before_quantity=Floor(F("before_quantity")),
                         after_quantity=Floor(F("after_quantity")))
                       & (Q(direction="IN", after_quantity=F("before_quantity") + F("quantity"),
                            after_meter_quantity=F("before_meter_quantity") + F("meter_quantity"))
                          | Q(direction="OUT", after_quantity=F("before_quantity") - F("quantity"),
                              after_meter_quantity=F("before_meter_quantity") - F("meter_quantity"))))),
                name="inv_pipe_movement_amount_valid",
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inv_mat_movement_qty_positive"),
            models.CheckConstraint(
                condition=Q(direction__in=MaterialStockDirection.values),
                name="inv_mat_movement_direction_valid",
            ),
            models.CheckConstraint(
                condition=Q(before_quantity__gte=0) & Q(after_quantity__gte=0),
                name="inv_mat_movement_balances_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="inv_mat_movement_source_idx"),
            models.Index(fields=["production_task", "-occurred_at"], name="inv_mat_movement_task_idx"),
            models.Index(fields=["balance", "-occurred_at"], name="inv_mat_movement_balance_idx"),
        ]


class SemiFinishedStockBalance(TimeStampedModel):
    """委外回厂半成品余额；身份不得退化为原材料身份。"""

    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_balances",
    )
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_balances",
    )
    bom_line = models.ForeignKey(
        "boms.BomLine",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_balances",
    )
    completed_craft = models.ForeignKey(
        "workshop_config.Craft",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_balances",
    )
    color_snapshot = models.CharField(max_length=200, blank=True)
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_balances",
    )
    zone = models.ForeignKey(WarehouseZone, on_delete=models.PROTECT, related_name="semi_finished_stock_balances")
    quality = models.CharField(
        max_length=20,
        choices=MaterialStockQuality.choices,
        default=MaterialStockQuality.AVAILABLE,
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "inventory_semi_finished_stock_balance"
        ordering = ["production_task", "product_line", "bom_line", "completed_craft", "quality", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "production_task", "product_line", "bom_line", "completed_craft",
                    "color_snapshot", "unit", "zone", "quality",
                ],
                name="inv_semi_balance_identity_uniq",
            ),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="inv_semi_balance_qty_nonnegative"),
            models.CheckConstraint(condition=Q(version__gt=0), name="inv_semi_balance_version_positive"),
            models.CheckConstraint(
                condition=Q(quality__in=MaterialStockQuality.values),
                name="inv_semi_balance_quality_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["production_task", "product_line", "completed_craft", "quality"],
                name="inv_semi_task_product_idx",
            ),
            models.Index(fields=["bom_line", "quality"], name="inv_semi_bom_quality_idx"),
            models.Index(fields=["zone", "quality"], name="inv_semi_zone_quality_idx"),
        ]


class SemiFinishedStockMovement(TimeStampedModel):
    """只追加的半成品库存流水。"""

    balance = models.ForeignKey(
        SemiFinishedStockBalance,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    direction = models.CharField(max_length=10, choices=MaterialStockDirection.choices)
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    before_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    after_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    source_type = models.CharField(max_length=50)
    source_id = models.UUIDField()
    source_line_id = models.UUIDField()
    actor_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="semi_finished_stock_movements",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "inventory_semi_finished_stock_movement"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_line_id", "direction"],
                name="inv_semi_movement_source_uniq",
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inv_semi_movement_qty_positive"),
            models.CheckConstraint(
                condition=Q(direction__in=MaterialStockDirection.values),
                name="inv_semi_movement_direction_valid",
            ),
            models.CheckConstraint(
                condition=Q(before_quantity__gte=0) & Q(after_quantity__gte=0),
                name="inv_semi_movement_balances_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="inv_semi_movement_src_idx"),
            models.Index(fields=["balance", "-occurred_at"], name="inv_semi_movement_bal_idx"),
        ]


class PublicStockKind(models.TextChoices):
    RAW_PIPE = "RAW_PIPE", "公共原料管材"
    SEMI = "SEMI", "公共半成品"


class PublicStockBalance(TimeStampedModel):
    """第 3 步新增底层；尚未接入旧业务入口，不与旧余额相加。"""

    stock_kind = models.CharField(max_length=12, choices=PublicStockKind.choices)
    identity_key = models.CharField(max_length=64)
    identity_snapshot = models.JSONField()
    raw_material = models.ForeignKey(
        "products.RawMaterialInformation", on_delete=models.PROTECT,
        null=True, blank=True, related_name="public_pipe_stock_balances",
    )
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    unit = models.ForeignKey("reference_data.ProductionUnit", on_delete=models.PROTECT,
                             related_name="public_stock_balances")
    zone = models.ForeignKey(WarehouseZone, on_delete=models.PROTECT, related_name="public_stock_balances")
    quality = models.CharField(max_length=20, choices=MaterialStockQuality.choices,
                               default=MaterialStockQuality.AVAILABLE)
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "inventory_public_stock_balance"
        ordering = ["stock_kind", "identity_key", "zone", "quality", "id"]
        constraints = [
            models.UniqueConstraint(fields=["stock_kind", "identity_key", "unit", "zone", "quality"],
                                    name="inv_pub_balance_identity_uniq"),
            models.CheckConstraint(condition=Q(stock_kind__in=PublicStockKind.values),
                                   name="inv_pub_balance_kind_valid"),
            models.CheckConstraint(condition=Q(quality__in=MaterialStockQuality.values),
                                   name="inv_pub_balance_quality"),
            models.CheckConstraint(condition=Q(quantity__gte=0) & Q(quantity=Floor(F("quantity"))),
                                   name="inv_pub_balance_whole_qty"),
            models.CheckConstraint(condition=Q(version__gt=0), name="inv_pub_balance_version"),
            models.CheckConstraint(
                condition=(Q(stock_kind="RAW_PIPE", raw_material__isnull=False,
                             raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0,
                             meter_quantity__isnull=False, meter_quantity__gte=0,
                             meter_quantity=F("quantity") * F("raw_bar_length_m"))
                           | Q(stock_kind="SEMI", raw_material__isnull=True,
                               raw_bar_length_m__isnull=True, meter_quantity__isnull=True)),
                name="inv_pub_balance_shape_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["stock_kind", "identity_key", "quality"], name="inv_pub_balance_lookup"),
            models.Index(fields=["zone", "quality"], name="inv_pub_balance_zone"),
        ]


class PublicStockMovement(TimeStampedModel):
    """保留来源单据和领用订单，不以来源批次分割公共余额。"""

    balance = models.ForeignKey(PublicStockBalance, on_delete=models.PROTECT, related_name="movements")
    direction = models.CharField(max_length=10, choices=MaterialStockDirection.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    before_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    after_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    before_meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    after_meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    source_type = models.CharField(max_length=50)
    source_id = models.UUIDField()
    source_line_id = models.UUIDField()
    production_task = models.ForeignKey("production_tasks.ProductionTask", on_delete=models.PROTECT,
                                        null=True, blank=True, related_name="public_stock_movements")
    product_line = models.ForeignKey("production_tasks.ProductionTaskProduct", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="public_stock_movements")
    bom_line = models.ForeignKey("boms.BomLine", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="public_stock_movements")
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                       related_name="public_stock_movements")
    occurred_at = models.DateTimeField(default=timezone.now)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "inventory_public_stock_movement"
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["source_type", "source_line_id", "direction"],
                                    name="inv_pub_movement_source_uniq"),
            models.CheckConstraint(condition=Q(direction__in=MaterialStockDirection.values),
                                   name="inv_pub_movement_direction"),
            models.CheckConstraint(condition=Q(quantity__gt=0) & Q(quantity=Floor(F("quantity")))
                                   & Q(before_quantity__gte=0) & Q(after_quantity__gte=0)
                                   & Q(before_quantity=Floor(F("before_quantity")))
                                   & Q(after_quantity=Floor(F("after_quantity"))),
                                   name="inv_pub_movement_whole_qty"),
            models.CheckConstraint(
                condition=(Q(direction="IN", after_quantity=F("before_quantity") + F("quantity"))
                           | Q(direction="OUT", after_quantity=F("before_quantity") - F("quantity"))),
                name="inv_pub_movement_amount",
            ),
            models.CheckConstraint(
                condition=(Q(meter_quantity__isnull=True, before_meter_quantity__isnull=True,
                             after_meter_quantity__isnull=True)
                           | (Q(meter_quantity__isnull=False, meter_quantity__gt=0,
                                before_meter_quantity__isnull=False, before_meter_quantity__gte=0,
                                after_meter_quantity__isnull=False, after_meter_quantity__gte=0)
                              & (Q(direction="IN", after_meter_quantity=F("before_meter_quantity") + F("meter_quantity"))
                                 | Q(direction="OUT", after_meter_quantity=F("before_meter_quantity") - F("meter_quantity"))))),
                name="inv_pub_movement_meters",
            ),
        ]
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="inv_pub_movement_source"),
            models.Index(fields=["balance", "-occurred_at"], name="inv_pub_movement_balance"),
            models.Index(fields=["production_task", "-occurred_at"], name="inv_pub_movement_task"),
        ]


class PublicStockCutoverControl(TimeStampedModel):
    """切换停写状态持久保存，服务重启不能恢复旧账写入。"""

    key = models.CharField(max_length=30, default="PUBLIC_STOCK", unique=True, editable=False)
    state = models.CharField(max_length=20, choices=[("MAINTENANCE", "切换停写"), ("PUBLIC", "公共库存")])
    reason = models.TextField()
    started_by = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="stock_cutovers_started")
    started_at = models.DateTimeField(default=timezone.now)
    activated_by = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="stock_cutovers_activated")
    activated_at = models.DateTimeField(null=True, blank=True)
    activation_manifest_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "inventory_public_stock_cutover_control"
        constraints = [
            models.CheckConstraint(condition=Q(key="PUBLIC_STOCK"), name="inv_pub_cutover_singleton"),
            models.CheckConstraint(condition=Q(state__in=["MAINTENANCE", "PUBLIC"]), name="inv_pub_cutover_state"),
        ]

# 厂内入库记录模型由 Django 统一注册，库存仍使用 PublicStockBalance。
from .internal_receipt_models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine  # noqa: F401,E402
from .assembly_receipt_models import AssemblyReceiptSource  # noqa: F401,E402
