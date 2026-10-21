from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel, TimeStampedModel, uppercase_code_validator


class BomStatus(models.TextChoices):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION", "待确认"
    VERIFIED = "VERIFIED", "已确认"


class BomCreationMethod(models.TextChoices):
    IMPORT = "IMPORT", "从 Excel BOM 导入"
    COPY = "COPY", "复制历史 BOM"
    BLANK = "BLANK", "空白建立"


class BomSectionType(models.TextChoices):
    PROFILE = "PROFILE", "型材"
    ACCESSORY = "ACCESSORY", "配件"
    FABRIC = "FABRIC", "面辅料"


class Bom(ArchivableModel):
    bom_number = models.CharField(max_length=80, unique=True, validators=[uppercase_code_validator])
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        on_delete=models.PROTECT,
        related_name="boms",
    )
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct",
        on_delete=models.PROTECT,
        related_name="boms",
    )
    version_number = models.PositiveIntegerField(default=1)
    creation_method = models.CharField(max_length=20, choices=BomCreationMethod.choices)
    status = models.CharField(
        max_length=30,
        choices=BomStatus.choices,
        default=BomStatus.PENDING_CONFIRMATION,
    )
    copied_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="copied_versions",
    )

    product = models.ForeignKey(
        "products.ProductInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_records",
    )
    product_category = models.ForeignKey(
        "reference_data.ProductCategory",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_records",
    )
    product_unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_records",
    )
    product_color = models.ForeignKey(
        "reference_data.ProductColor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_records",
    )

    product_number_snapshot = models.CharField(max_length=100)
    product_code_snapshot = models.CharField(max_length=100, blank=True)
    item_number_snapshot = models.CharField(max_length=100, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    specification_snapshot = models.CharField(max_length=300)
    product_category_snapshot = models.CharField(max_length=150, blank=True)
    material_snapshot = models.TextField(blank=True)
    product_unit_code_snapshot = models.CharField(max_length=50, blank=True)
    product_unit_name_snapshot = models.CharField(max_length=100, blank=True)
    product_color_name_snapshot = models.CharField(max_length=200, blank=True)
    product_color_code_snapshot = models.CharField(max_length=100, blank=True)
    product_color_card_snapshot = models.CharField(max_length=100, blank=True)
    product_information_confirmed_at = models.DateTimeField(null=True, blank=True)
    product_information_confirmed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="product_reviewed_boms",
    )
    order_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    source_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    batch_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    quantity_difference = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))

    source_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bom_sources",
    )
    source_sheet_name = models.CharField(max_length=150, blank=True)
    source_original_name = models.CharField(max_length=255, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    calculation_summary = models.JSONField(default=dict, blank=True)
    maintenance_match_count = models.PositiveIntegerField(default=0)
    maintenance_unmatched_count = models.PositiveIntegerField(default=0)
    maintenance_unmatched_values = models.JSONField(default=list, blank=True)
    section_count = models.PositiveIntegerField(default=0)
    line_count = models.PositiveIntegerField(default=0)

    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_boms",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_boms",
    )
    confirmed_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_boms",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    quantity_difference_reason = models.TextField(blank=True, default="")
    confirmation_reason = models.TextField(blank=True)

    class Meta:
        db_table = "bom"
        ordering = ["-updated_at", "-id"]
        permissions = [
            ("view_all_bom", "可查看全部 BOM"),
            ("verify_bom", "可确认 BOM"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product_line", "version_number"],
                name="bom_product_version_unique",
            ),
            models.CheckConstraint(condition=Q(status__in=BomStatus.values), name="bom_status_valid"),
            models.CheckConstraint(
                condition=Q(creation_method__in=BomCreationMethod.values),
                name="bom_creation_method_valid",
            ),
            models.CheckConstraint(condition=Q(order_quantity__gt=0), name="bom_order_quantity_positive"),
            models.CheckConstraint(
                condition=Q(source_quantity__isnull=True) | Q(source_quantity__gte=0),
                name="bom_source_quantity_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(batch_quantity__isnull=True) | Q(batch_quantity__gte=0),
                name="bom_batch_quantity_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-updated_at"], name="bom_status_updated_idx"),
            models.Index(fields=["production_task", "-updated_at"], name="bom_task_updated_idx"),
            models.Index(fields=["product_line", "-version_number"], name="bom_product_version_idx"),
            models.Index(fields=["product", "status", "-updated_at"], name="bom_master_status_idx"),
        ]

    def __str__(self):
        return self.bom_number


class BomSection(TimeStampedModel):
    bom = models.ForeignKey(Bom, on_delete=models.CASCADE, related_name="sections")
    line_number = models.PositiveIntegerField()
    section_type = models.CharField(max_length=20, choices=BomSectionType.choices)
    title = models.CharField(max_length=300)
    source_title_row = models.PositiveIntegerField(null=True, blank=True)
    source_header_row = models.PositiveIntegerField(null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    calculation_rows = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "bom_section"
        ordering = ["bom", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["bom", "line_number"], name="bom_section_line_unique"),
            models.CheckConstraint(
                condition=Q(section_type__in=BomSectionType.values),
                name="bom_section_type_valid",
            ),
        ]


class BomLine(TimeStampedModel):
    # 空的类型字段表示旧行尚未准备；不得在迁移时猜测或换算旧库存。
    component_identity = models.UUIDField(default=uuid.uuid4, editable=False)
    cutting_length_mm = models.PositiveBigIntegerField(null=True, blank=True)
    pieces_per_product = models.PositiveBigIntegerField(null=True, blank=True)
    pieces_per_bar = models.PositiveBigIntegerField(null=True, blank=True)
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    suggested_bar_count = models.PositiveBigIntegerField(null=True, blank=True)
    suggested_purchase_meters = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    fabric_source_line = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="cutting_components",
    )
    fabric_meters_per_set = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cutting_pieces_per_set = models.PositiveBigIntegerField(null=True, blank=True)
    fabric_meters_per_piece = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cutting_sets_per_product = models.PositiveBigIntegerField(null=True, blank=True)
    section = models.ForeignKey(BomSection, on_delete=models.CASCADE, related_name="lines")
    line_number = models.PositiveIntegerField()
    source_row_number = models.PositiveIntegerField(null=True, blank=True)
    source_serial = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=150, blank=True)
    material = models.CharField(max_length=200, blank=True)
    part_name = models.CharField(max_length=300)
    specification = models.CharField(max_length=500, blank=True)
    raw_material = models.TextField(blank=True)
    length_value = models.CharField(max_length=100, blank=True)
    unit_consumption = models.CharField(max_length=100, blank=True)
    total_consumption = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    hardness = models.CharField(max_length=100, blank=True)
    original_material_length = models.CharField(max_length=100, blank=True)
    branch_count = models.CharField(max_length=100, blank=True)
    budget_quantity = models.CharField(max_length=100, blank=True)
    inventory_quantity = models.CharField(max_length=100, blank=True)
    weight_grams = models.CharField(max_length=100, blank=True)
    cut_piece_quantity = models.CharField(max_length=100, blank=True)
    purchase_consumption = models.CharField(max_length=100, blank=True)
    source_order_quantity = models.CharField(max_length=100, blank=True)
    total_purchase_quantity = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    raw_values = models.JSONField(default=dict, blank=True)
    source_formulas = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "bom_line"
        ordering = ["section", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["section", "line_number"], name="bom_line_number_unique"),
            models.CheckConstraint(
                condition=(Q(cutting_length_mm__isnull=True, pieces_per_product__isnull=True, pieces_per_bar__isnull=True,
                             raw_bar_length_m__isnull=True, suggested_bar_count__isnull=True, suggested_purchase_meters__isnull=True)
                    | Q(cutting_length_mm__isnull=False, cutting_length_mm__gt=0, pieces_per_product__isnull=False,
                        pieces_per_product__gt=0, pieces_per_bar__isnull=False, pieces_per_bar__gt=0,
                        raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0, suggested_bar_count__isnull=False,
                        suggested_bar_count__gt=0, suggested_purchase_meters__isnull=False, suggested_purchase_meters__gt=0)),
                name="bom_pipe_fields_complete",
            ),
            models.CheckConstraint(condition=Q(fabric_meters_per_set__isnull=True) | Q(fabric_meters_per_set__gt=0), name="bom_fabric_consumption_positive"),
            models.CheckConstraint(
                condition=((Q(cutting_pieces_per_set__isnull=True,
                             cutting_sets_per_product__isnull=True)
                    | Q(cutting_pieces_per_set__isnull=False, cutting_pieces_per_set__gt=0,
                        cutting_pieces_per_set__lt=100000000000000, cutting_sets_per_product__isnull=False,
                        cutting_sets_per_product__gt=0, cutting_sets_per_product__lt=100000000000000))
                    & (Q(fabric_meters_per_piece__isnull=True) | Q(fabric_meters_per_piece__gt=0))),
                name="bom_cutting_usage_complete",
            ),
        ]

    def __str__(self):
        return f"{self.section.bom.bom_number} - {self.part_name}"


class BomLineImage(TimeStampedModel):
    bom_line = models.ForeignKey(BomLine, on_delete=models.CASCADE, related_name="images")
    business_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="bom_line_images",
    )
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "bom_line_image"
        ordering = ["bom_line", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bom_line", "position"],
                name="bom_line_image_position_unique",
            ),
            models.UniqueConstraint(
                fields=["bom_line", "business_file"],
                name="bom_line_image_file_unique",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0),
                name="bom_line_image_position_positive",
            ),
        ]


class BomLineImageDraft(TimeStampedModel):
    bom = models.ForeignKey(Bom, on_delete=models.CASCADE, related_name="line_image_drafts")
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bom_line_image_drafts",
    )
    business_file = models.ForeignKey(
        "files.BusinessFile",
        on_delete=models.PROTECT,
        related_name="bom_line_image_drafts",
    )
    draft_key = models.UUIDField()
    position = models.PositiveIntegerField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "bom_line_image_draft"
        ordering = ["bom", "owner_user", "draft_key", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bom", "owner_user", "draft_key", "position"],
                name="bom_image_draft_position_unique",
            ),
            models.UniqueConstraint(
                fields=["business_file"],
                name="bom_image_draft_file_unique",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0),
                name="bom_image_draft_position_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["expires_at", "id"], name="bom_image_draft_expiry_idx"),
            models.Index(
                fields=["bom", "owner_user", "draft_key", "position"],
                name="bom_image_draft_scope_idx",
            ),
        ]
