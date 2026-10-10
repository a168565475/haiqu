from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel
from apps.reference_data.models import ProductItemType


class ProductScale(models.TextChoices):
    CUSTOM = "CUSTOM", "定制"
    REGULAR = "REGULAR", "常规"


class ProductStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "正常"
    INACTIVE = "INACTIVE", "废弃"


class RawMaterialBoxShape(models.TextChoices):
    HALF_COVER = "HALF_COVER", "半盖"
    FULL_COVER = "FULL_COVER", "全盖"
    LID_AND_BASE = "LID_AND_BASE", "天地盖"
    DISPLAY_BOX = "DISPLAY_BOX", "展示盒"
    OTHER = "OTHER", "其他"


class ProductInformation(ArchivableModel):
    product_number = models.CharField(max_length=100, unique=True)
    product_type = models.CharField(
        max_length=30,
        choices=[(ProductItemType.FINISHED, "成品")],
        default=ProductItemType.FINISHED,
    )
    product_code = models.CharField(max_length=100, blank=True)
    category = models.ForeignKey(
        "reference_data.ProductCategory",
        on_delete=models.PROTECT,
        related_name="products",
    )
    product_name = models.CharField(max_length=200)
    specification = models.CharField(max_length=300)
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="products",
    )
    product_item = models.ForeignKey(
        "reference_data.ProductItem",
        on_delete=models.PROTECT,
        related_name="products",
    )
    warehouse_number = models.CharField(max_length=100, blank=True)
    warehouse_name = models.CharField(max_length=150, blank=True)
    scale = models.CharField(max_length=20, choices=ProductScale.choices)
    status = models.CharField(max_length=20, choices=ProductStatus.choices, default=ProductStatus.ACTIVE)

    class Meta:
        db_table = "product_information"
        ordering = ["product_number", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(product_type=ProductItemType.FINISHED),
                name="product_information_type_finished",
            ),
            models.CheckConstraint(
                condition=Q(scale__in=ProductScale.values),
                name="product_information_scale_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=ProductStatus.values),
                name="product_information_status_valid",
            ),
            models.UniqueConstraint(
                fields=["product_code"],
                condition=~Q(product_code=""),
                name="product_information_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "category", "product_number"], name="prod_info_status_cat_idx"),
            models.Index(fields=["scale", "product_number"], name="product_info_scale_idx"),
            models.Index(fields=["-updated_at", "-id"], name="product_info_updated_idx"),
        ]

    def clean(self):
        super().clean()
        if self.product_type != ProductItemType.FINISHED:
            raise ValidationError({"product_type": "产品信息类型目前只允许成品。"})
        if self.category_id and self.category.item_type != ProductItemType.FINISHED:
            raise ValidationError({"category": "产品类别必须是成品类别。"})

    def delete(self, *args, **kwargs):
        raise ValidationError("产品信息不允许物理删除，请改为废弃状态。")

    def __str__(self):
        return f"{self.product_number} - {self.product_name}"


class RawMaterialInformation(ArchivableModel):
    material_number = models.CharField(max_length=100, db_index=True)
    item_type = models.CharField(
        max_length=30,
        choices=[
            (ProductItemType.MATERIAL, "材料"),
            (ProductItemType.SEMI_FINISHED, "半成品"),
        ],
    )
    category = models.ForeignKey(
        "reference_data.ProductCategory",
        on_delete=models.PROTECT,
        related_name="raw_materials",
    )
    material_name = models.CharField(max_length=200)
    specification = models.CharField(max_length=300)
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="raw_materials",
    )
    color = models.ForeignKey(
        "reference_data.ProductColor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="raw_materials",
    )
    color_snapshot = models.CharField(max_length=200, blank=True)
    material = models.CharField(max_length=200, blank=True)
    is_packaging_auxiliary = models.BooleanField(default=False)
    box_shape = models.CharField(max_length=30, choices=RawMaterialBoxShape.choices, blank=True)
    notes = models.TextField(blank=True)
    warehouse_number = models.CharField(max_length=100)
    warehouse_name = models.CharField(max_length=150)

    # 附件中暂未进入表单的历史字段仍需保留，避免导入时丢失原始资料。
    diameter = models.CharField(max_length=100, blank=True)
    length = models.CharField(max_length=100, blank=True)
    width = models.CharField(max_length=100, blank=True)
    thickness = models.CharField(max_length=100, blank=True)
    model_number = models.CharField(max_length=100, blank=True)
    weight_kg = models.CharField(max_length=100, blank=True)
    flow_unit = models.CharField(max_length=100, blank=True)
    number_value = models.CharField(max_length=100, blank=True)
    source_unique_check = models.CharField(max_length=300, blank=True)
    source_row_number = models.PositiveIntegerField(null=True, blank=True, unique=True)

    class Meta:
        db_table = "raw_material_information"
        ordering = ["material_number", "source_row_number", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(item_type__in=[ProductItemType.MATERIAL, ProductItemType.SEMI_FINISHED]),
                name="raw_material_item_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(box_shape="") | Q(box_shape__in=RawMaterialBoxShape.values),
                name="raw_material_box_shape_valid",
            ),
            models.UniqueConstraint(
                fields=["material_number"],
                condition=Q(source_row_number__isnull=True),
                name="raw_material_new_number_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["item_type", "category", "material_number"],
                name="raw_material_type_cat_idx",
            ),
            models.Index(
                fields=["warehouse_number", "warehouse_name"],
                name="raw_material_warehouse_idx",
            ),
            models.Index(fields=["-updated_at", "-id"], name="raw_material_updated_idx"),
        ]

    @property
    def is_packaging_category(self) -> bool:
        return bool(
            self.item_type == ProductItemType.MATERIAL
            and self.category_id
            and self.category.category_name == "包材"
        )

    def clean(self):
        super().clean()
        if self.item_type not in {ProductItemType.MATERIAL, ProductItemType.SEMI_FINISHED}:
            raise ValidationError({"item_type": "原料类型只允许材料或半成品。"})
        if self.category_id and self.category.item_type != self.item_type:
            raise ValidationError({"category": "原料类别必须与所选类型一致。"})
        if self.category_id and not self.is_packaging_category:
            if self.is_packaging_auxiliary:
                raise ValidationError({"is_packaging_auxiliary": "只有包材类别可以设置包材辅料。"})
            if self.box_shape:
                raise ValidationError({"box_shape": "只有包材类别可以设置箱子形状。"})

    def delete(self, *args, **kwargs):
        raise ValidationError("原料信息不允许物理删除。")

    def __str__(self):
        return f"{self.material_number} - {self.material_name}"
