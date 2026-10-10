from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import ArchivableModel, TimeStampedModel, uppercase_code_condition, uppercase_code_validator
from apps.reference_data.pinyin_search import build_pinyin_search


alpha2_code_validator = RegexValidator(r"^[A-Z]{2}$", "Alpha-2 编码必须是两位大写字母。")
alpha3_code_validator = RegexValidator(r"^[A-Z]{3}$", "三字母编码必须是三位大写字母。")
numeric3_code_validator = RegexValidator(r"^[0-9]{3}$", "数字编码必须是三位数字字符串。")
port_code_validator = RegexValidator(r"^[A-Z]{2}[A-Z0-9]{3}$", "港口编码必须是五位 UN/LOCODE。")


class ReferenceStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    INACTIVE = "INACTIVE", "停用"


# 保留旧名称，避免现有业务模块导入失效。
DictionaryStatus = ReferenceStatus


class ProtectedReferenceModel(ArchivableModel):
    """配置资料只能停用或归档，不允许通过模型实例物理删除。"""

    status = models.CharField(max_length=20, choices=ReferenceStatus.choices, default=ReferenceStatus.ACTIVE)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise ValidationError("基础配置不允许物理删除，请使用停用或归档。")


class PinyinSearchModelMixin:
    """名称保存时同步维护隐藏拼音检索值。"""

    pinyin_source_field = ""

    def save(self, *args, **kwargs):
        requested_update_fields = kwargs.get("update_fields")
        update_fields = None if requested_update_fields is None else set(requested_update_fields)
        if update_fields is not None:
            kwargs["update_fields"] = update_fields
        source_is_saved = update_fields is None or self.pinyin_source_field in update_fields
        if source_is_saved:
            self.pinyin_search = build_pinyin_search(getattr(self, self.pinyin_source_field, ""))
            if update_fields is not None:
                update_fields.add("pinyin_search")
        return super().save(*args, **kwargs)


class DictionaryType(ProtectedReferenceModel):
    code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    chinese_name = models.CharField(max_length=150)
    english_name = models.CharField(max_length=150, blank=True)
    group_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "dictionary_type"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="dict_type_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="dict_type_code_uppercase"),
            models.CheckConstraint(
                condition=uppercase_code_condition("group_code"),
                name="dict_type_group_uppercase",
            ),
        ]
        indexes = [
            models.Index(
                fields=["group_code", "status", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="dict_type_active_list_idx",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.chinese_name}"


class ReferenceDictionary(ProtectedReferenceModel):
    """简单可配置选项；保留 category_code 作为旧接口兼容字段。"""

    dictionary_type = models.ForeignKey(
        DictionaryType,
        on_delete=models.PROTECT,
        related_name="items",
    )
    category_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    item_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    display_name = models.CharField(max_length=150)
    english_name = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=30, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "reference_dictionary"
        ordering = ["category_code", "sort_order", "item_code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="ref_dict_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("category_code"), name="ref_dict_category_uppercase"),
            models.CheckConstraint(condition=uppercase_code_condition("item_code"), name="ref_dict_item_uppercase"),
            models.UniqueConstraint(fields=["category_code", "item_code"], name="ref_dict_category_item_uniq"),
            models.UniqueConstraint(fields=["dictionary_type", "item_code"], name="ref_dict_type_item_uniq"),
        ]
        indexes = [
            models.Index(
                fields=["category_code", "status", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="ref_dict_active_list_idx",
            ),
            models.Index(
                fields=["dictionary_type", "status", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="ref_dict_type_list_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.dictionary_type_id and self.category_code != self.dictionary_type.code:
            raise ValidationError({"category_code": "兼容分类编码必须与字典类型编码一致。"})

    def save(self, *args, **kwargs):
        if self.dictionary_type_id:
            self.category_code = self.dictionary_type.code
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.category_code}.{self.item_code} - {self.display_name}"


class ConfigReleaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "生成中"
    PUBLISHED = "PUBLISHED", "已发布"
    FAILED = "FAILED", "发布失败"


class ConfigRelease(TimeStampedModel):
    version = models.PositiveIntegerField(unique=True)
    status = models.CharField(max_length=20, choices=ConfigReleaseStatus.choices)
    notes = models.CharField(max_length=500, blank=True)
    snapshot = models.JSONField(default=dict)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_config_releases",
    )
    failure_message = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "config_release"
        ordering = ["-version"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ConfigReleaseStatus.values), name="config_release_status_valid"),
            models.CheckConstraint(
                condition=Q(status=ConfigReleaseStatus.PUBLISHED, published_at__isnull=False)
                | ~Q(status=ConfigReleaseStatus.PUBLISHED),
                name="config_release_published_time_required",
            ),
        ]
        permissions = [("publish_configrelease", "可发布系统配置版本")]

    def delete(self, *args, **kwargs):
        raise ValidationError("配置发布记录不可删除。")


class ParameterValueType(models.TextChoices):
    STRING = "STRING", "文本"
    INTEGER = "INTEGER", "整数"
    BOOLEAN = "BOOLEAN", "布尔值"
    DATE_FORMAT = "DATE_FORMAT", "日期格式"
    COUNTRY_CODE = "COUNTRY_CODE", "国家代码"
    CURRENCY_CODE = "CURRENCY_CODE", "币种代码"


class SystemParameterDefinition(ProtectedReferenceModel):
    code = models.CharField(max_length=80, unique=True, validators=[uppercase_code_validator])
    chinese_name = models.CharField(max_length=150)
    english_name = models.CharField(max_length=150, blank=True)
    group_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    value_type = models.CharField(max_length=30, choices=ParameterValueType.choices)
    default_value = models.JSONField(null=True, blank=True)
    validation_rules = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "system_parameter_definition"
        ordering = ["group_code", "sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="sys_param_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="sys_param_code_uppercase"),
            models.CheckConstraint(condition=uppercase_code_condition("group_code"), name="sys_param_group_uppercase"),
            models.CheckConstraint(condition=Q(value_type__in=ParameterValueType.values), name="sys_param_value_type_valid"),
        ]

    def __str__(self):
        return f"{self.code} - {self.chinese_name}"


class SystemParameterValue(TimeStampedModel):
    definition = models.OneToOneField(SystemParameterDefinition, on_delete=models.PROTECT, related_name="value_record")
    draft_value = models.JSONField(null=True, blank=True)
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_system_parameter_values",
    )

    class Meta:
        db_table = "system_parameter_value"

    def delete(self, *args, **kwargs):
        raise ValidationError("系统参数值不可删除。")


class CodedMasterData(ProtectedReferenceModel):
    code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    chinese_name = models.CharField(max_length=150)
    english_name = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    source_version = models.CharField(max_length=100, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class Country(CodedMasterData):
    code = models.CharField(max_length=2, unique=True, validators=[alpha2_code_validator])
    alpha3_code = models.CharField(max_length=3, unique=True, validators=[alpha3_code_validator])
    numeric_code = models.CharField(max_length=3, unique=True, validators=[numeric3_code_validator])

    class Meta:
        db_table = "reference_country"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="country_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="country_code_uppercase"),
            models.CheckConstraint(condition=uppercase_code_condition("alpha3_code"), name="country_a3_uppercase"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="country_active_list_idx")]


class Currency(CodedMasterData):
    code = models.CharField(max_length=3, unique=True, validators=[alpha3_code_validator])
    numeric_code = models.CharField(max_length=3, unique=True, validators=[numeric3_code_validator])
    decimal_places = models.PositiveSmallIntegerField(default=2, validators=[MaxValueValidator(6)])
    symbol = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "reference_currency"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="currency_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="currency_code_uppercase"),
        ]


class Unit(CodedMasterData):
    symbol = models.CharField(max_length=30, blank=True)
    category = models.CharField(max_length=80, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(6)])

    class Meta:
        db_table = "reference_unit"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="unit_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="unit_code_uppercase"),
        ]


class Incoterm(CodedMasterData):
    rules_version = models.CharField(max_length=20)
    transport_scope = models.CharField(max_length=80)

    class Meta:
        db_table = "reference_incoterm"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="incoterm_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="incoterm_code_uppercase"),
        ]


class PaymentMethod(CodedMasterData):
    class Meta:
        db_table = "reference_payment_method"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="payment_method_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="payment_method_code_uppercase"),
        ]


class TransportMethod(CodedMasterData):
    class Meta:
        db_table = "reference_transport_method"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="transport_method_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="transport_method_code_uppercase"),
        ]


class Port(CodedMasterData):
    code = models.CharField(max_length=5, unique=True, validators=[port_code_validator])
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="ports")
    administrative_area = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "reference_port"
        ordering = ["country__code", "sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="port_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="port_code_uppercase"),
        ]
        indexes = [models.Index(fields=["country", "status", "sort_order", "id"], name="port_country_list_idx")]


class Courier(CodedMasterData):
    tracking_url_template = models.URLField(max_length=500, blank=True)

    class Meta:
        db_table = "reference_courier"
        ordering = ["sort_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="courier_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("code"), name="courier_code_uppercase"),
        ]


class ExchangeRate(ProtectedReferenceModel):
    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="base_exchange_rates")
    quote_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="quote_exchange_rates")
    rate = models.DecimalField(max_digits=20, decimal_places=8, validators=[MinValueValidator(Decimal("0.00000001"))])
    effective_date = models.DateField()
    source_name = models.CharField(max_length=150)
    source_version = models.CharField(max_length=100, blank=True)
    entered_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="entered_exchange_rates",
    )
    correction_of = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="corrected_by",
    )

    class Meta:
        db_table = "reference_exchange_rate"
        ordering = ["-effective_date", "base_currency__code", "quote_currency__code", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="exchange_rate_status_valid"),
            models.CheckConstraint(condition=Q(rate__gt=0), name="exchange_rate_positive"),
            models.CheckConstraint(condition=~Q(base_currency=F("quote_currency")), name="exchange_rate_currency_distinct"),
        ]
        indexes = [
            models.Index(
                fields=["base_currency", "quote_currency", "-effective_date", "-created_at"],
                name="exchange_rate_pair_date_idx",
            )
        ]

    def clean(self):
        super().clean()
        if self.base_currency_id and self.base_currency_id == self.quote_currency_id:
            raise ValidationError({"quote_currency": "基础币种和目标币种不能相同。"})
        if self.rate is not None and self.rate <= 0:
            raise ValidationError({"rate": "汇率必须大于 0。"})


class ProductItemType(models.TextChoices):
    FINISHED = "FINISHED", "成品"
    SEMI_FINISHED = "SEMI_FINISHED", "半成品"
    MATERIAL = "MATERIAL", "材料"


class ProductCategory(ProtectedReferenceModel):
    item_type = models.CharField(max_length=30, choices=ProductItemType.choices)
    category_name = models.CharField(max_length=150, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_product_category"
        ordering = ["sort_order", "category_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="product_category_status_valid"),
            models.CheckConstraint(condition=Q(item_type__in=ProductItemType.values), name="product_category_type_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="product_category_list_idx")]

    def __str__(self):
        return f"{self.get_item_type_display()} - {self.category_name}"


class ProductionUnit(ProtectedReferenceModel):
    unit_code = models.CharField(max_length=20, unique=True)
    unit_name = models.CharField(max_length=80, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_production_unit"
        ordering = ["sort_order", "unit_code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="production_unit_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="production_unit_list_idx")]

    def __str__(self):
        return f"{self.unit_code} - {self.unit_name}"


class ProductColor(ProtectedReferenceModel):
    color_card = models.CharField(max_length=100)
    color_code = models.CharField(max_length=100)
    color_name = models.CharField(max_length=200)
    image_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="product_colors",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_product_color"
        ordering = ["sort_order", "color_card", "color_code", "color_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="product_color_status_valid"),
            models.UniqueConstraint(
                fields=["color_card", "color_code", "color_name"],
                name="product_color_identity_uniq",
            ),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="product_color_list_idx")]

    def __str__(self):
        return f"{self.color_card} {self.color_code} {self.color_name}"


class ProductItem(ProtectedReferenceModel):
    item_number = models.CharField(max_length=100, unique=True)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="product_items")
    legacy_data_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_product_item"
        ordering = ["sort_order", "item_number"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="product_item_status_valid"),
        ]
        indexes = [
            models.Index(fields=["category", "status", "sort_order", "id"], name="product_item_category_idx"),
        ]

    def __str__(self):
        return self.item_number


class FabricMaterial(ProtectedReferenceModel):
    material_name = models.CharField(max_length=150, unique=True)
    inventory_raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fabric_material_mappings",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_fabric_material"
        ordering = ["sort_order", "material_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="fabric_material_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="fabric_material_list_idx")]

    def __str__(self):
        return self.material_name


class FabricSpecification(ProtectedReferenceModel):
    specification_name = models.CharField(max_length=150, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_fabric_specification"
        ordering = ["sort_order", "specification_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="fabric_spec_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="fabric_spec_list_idx")]

    def __str__(self):
        return self.specification_name


class FabricWidth(ProtectedReferenceModel):
    width_value = models.CharField(max_length=50, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_fabric_width"
        ordering = ["sort_order", "width_value"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="fabric_width_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="fabric_width_list_idx")]

    def __str__(self):
        return self.width_value


class TubeProductName(PinyinSearchModelMixin, ProtectedReferenceModel):
    pinyin_source_field = "product_name"
    product_name = models.CharField(max_length=200, unique=True)
    pinyin_search = models.TextField(blank=True, editable=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_product_name"
        ordering = ["sort_order", "product_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_product_name_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_product_name_list_idx")]

    def __str__(self):
        return self.product_name


class TubeThickness(ProtectedReferenceModel):
    thickness_value = models.CharField(max_length=50, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_thickness"
        ordering = ["sort_order", "thickness_value"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_thickness_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_thickness_list_idx")]

    def __str__(self):
        return self.thickness_value


class TubeDiameter(ProtectedReferenceModel):
    diameter_value = models.CharField(max_length=50, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_diameter"
        ordering = ["sort_order", "diameter_value"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_diameter_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_diameter_list_idx")]

    def __str__(self):
        return self.diameter_value


class TubeMaterial(PinyinSearchModelMixin, ProtectedReferenceModel):
    pinyin_source_field = "material_name"
    material_name = models.CharField(max_length=150, unique=True)
    pinyin_search = models.TextField(blank=True, editable=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_material"
        ordering = ["sort_order", "material_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_material_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_material_list_idx")]

    def __str__(self):
        return self.material_name


class TubeShape(PinyinSearchModelMixin, ProtectedReferenceModel):
    pinyin_source_field = "shape_name"
    shape_name = models.CharField(max_length=150, unique=True)
    pinyin_search = models.TextField(blank=True, editable=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_shape"
        ordering = ["sort_order", "shape_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_shape_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_shape_list_idx")]

    def __str__(self):
        return self.shape_name


class TubeCoatingColor(ProtectedReferenceModel):
    color_name = models.CharField(max_length=200, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_tube_coating_color"
        ordering = ["sort_order", "color_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="tube_coating_color_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="tube_coating_color_list_idx")]

    def __str__(self):
        return self.color_name


class AccessoryProductName(ProtectedReferenceModel):
    product_name = models.CharField(max_length=200, unique=True)
    unit_name = models.CharField(max_length=50, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_accessory_product_name"
        ordering = ["sort_order", "product_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="acc_product_name_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="acc_product_name_list_idx")]

    def __str__(self):
        return self.product_name


class AccessorySpecification(ProtectedReferenceModel):
    product_name = models.ForeignKey(
        AccessoryProductName,
        on_delete=models.PROTECT,
        related_name="specifications",
    )
    specification_value = models.CharField(max_length=300)
    weight = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_accessory_specification"
        ordering = ["sort_order", "product_name__product_name", "specification_value"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="acc_spec_status_valid"),
            models.UniqueConstraint(
                fields=["product_name", "specification_value"],
                name="acc_spec_name_value_uniq",
            ),
        ]
        indexes = [models.Index(fields=["product_name", "status", "sort_order"], name="acc_specification_list_idx")]

    def __str__(self):
        return f"{self.product_name.product_name} - {self.specification_value}"


class AccessoryColor(ProtectedReferenceModel):
    product_name = models.ForeignKey(
        AccessoryProductName,
        on_delete=models.PROTECT,
        related_name="colors",
    )
    color_name = models.CharField(max_length=200)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_accessory_color"
        ordering = ["sort_order", "product_name__product_name", "color_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="acc_color_status_valid"),
            models.UniqueConstraint(fields=["product_name", "color_name"], name="acc_color_name_uniq"),
        ]
        indexes = [models.Index(fields=["product_name", "status", "sort_order"], name="acc_color_list_idx")]

    def __str__(self):
        return f"{self.product_name.product_name} - {self.color_name}"


class AccessoryMaterial(ProtectedReferenceModel):
    material_name = models.CharField(max_length=150, unique=True)
    inventory_raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accessory_material_mappings",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_accessory_material"
        ordering = ["sort_order", "material_name"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="acc_material_status_valid"),
        ]
        indexes = [models.Index(fields=["status", "sort_order", "id"], name="acc_material_list_idx")]

    def __str__(self):
        return self.material_name


class NumberRule(ProtectedReferenceModel):
    """业务编号的已登记事实；修改规则前必须先保证生成器与现有序列兼容。"""

    number_type = models.CharField(max_length=30, unique=True, validators=[uppercase_code_validator])
    chinese_name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=20, blank=True, validators=[uppercase_code_validator])
    format_pattern = models.CharField(max_length=100, blank=True)
    sequence_name = models.CharField(max_length=100, blank=True)
    sequence_padding = models.PositiveSmallIntegerField(default=6, validators=[MaxValueValidator(12)])
    date_granularity = models.CharField(
        max_length=10,
        choices=[("NONE", "不含日期"), ("YEAR", "按年展示"), ("MONTH", "按月展示"), ("DAY", "按日展示")],
        default="NONE",
    )
    reset_policy = models.CharField(max_length=20, default="NEVER")
    is_configured = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "reference_number_rule"
        ordering = ["sort_order", "number_type"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ReferenceStatus.values), name="number_rule_status_valid"),
            models.CheckConstraint(condition=uppercase_code_condition("number_type"), name="number_rule_type_uppercase"),
            models.CheckConstraint(
                condition=Q(date_granularity__in=["NONE", "YEAR", "MONTH", "DAY"]),
                name="number_rule_date_granularity_valid",
            ),
            models.CheckConstraint(
                condition=Q(reset_policy__in=["NEVER", "DAILY", "YEARLY"]),
                name="number_rule_reset_policy_valid",
            ),
            models.CheckConstraint(
                condition=Q(is_configured=False) | (~Q(prefix="") & ~Q(format_pattern="") & ~Q(sequence_name="")),
                name="number_rule_configured_fields_required",
            ),
        ]
