from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
    ConfigRelease,
    Country,
    Courier,
    Currency,
    DictionaryType,
    ExchangeRate,
    FabricMaterial,
    FabricSpecification,
    FabricWidth,
    Incoterm,
    NumberRule,
    PaymentMethod,
    Port,
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductionUnit,
    ReferenceDictionary,
    ReferenceStatus,
    SystemParameterDefinition,
    TubeCoatingColor,
    TubeDiameter,
    TubeMaterial,
    TubeProductName,
    TubeShape,
    TubeThickness,
    TransportMethod,
    Unit,
)
from apps.reference_data.services import (
    dictionary_reference_count,
    dictionary_type_reference_count,
    validate_parameter_value,
)


class DictionaryTypeSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True)
    active_item_count = serializers.SerializerMethodField()
    reference_count = serializers.SerializerMethodField()

    class Meta:
        model = DictionaryType
        fields = [
            "id",
            "code",
            "chinese_name",
            "english_name",
            "group_code",
            "status",
            "sort_order",
            "description",
            "item_count",
            "active_item_count",
            "reference_count",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "archived_at",
            "item_count",
            "active_item_count",
            "reference_count",
        ]

    def get_active_item_count(self, instance) -> int:
        return sum(
            item.status == ReferenceStatus.ACTIVE and item.archived_at is None
            for item in instance.items.all()
        )

    def get_reference_count(self, instance) -> int:
        counts = self.context.get("dictionary_reference_counts")
        if counts is not None and instance.pk in counts:
            return counts[instance.pk]
        return dictionary_type_reference_count(instance)


class ReferenceDictionarySerializer(serializers.ModelSerializer):
    type_code = serializers.CharField(source="dictionary_type.code", read_only=True)
    reference_count = serializers.SerializerMethodField()

    class Meta:
        model = ReferenceDictionary
        fields = [
            "id",
            "dictionary_type",
            "type_code",
            "item_code",
            "display_name",
            "english_name",
            "description",
            "status",
            "sort_order",
            "color",
            "extra_data",
            "reference_count",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = [
            "id",
            "type_code",
            "reference_count",
            "created_at",
            "updated_at",
            "archived_at",
        ]

    def get_reference_count(self, instance) -> int:
        counts = self.context.get("dictionary_reference_counts")
        if counts is not None and instance.pk in counts:
            return counts[instance.pk]
        return dictionary_reference_count(instance)

    def validate_dictionary_type(self, value):
        if value.status != ReferenceStatus.ACTIVE or value.archived_at is not None:
            raise serializers.ValidationError("字典类型已停用或归档。")
        return value


class CodedMasterDataSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [
            "id",
            "code",
            "chinese_name",
            "english_name",
            "status",
            "sort_order",
            "source_version",
            "description",
            "extra_data",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class CountrySerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = Country
        fields = CodedMasterDataSerializer.Meta.fields[:2] + [
            "alpha3_code",
            "numeric_code",
        ] + CodedMasterDataSerializer.Meta.fields[2:]


class CurrencySerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = Currency
        fields = CodedMasterDataSerializer.Meta.fields[:2] + [
            "numeric_code",
            "decimal_places",
            "symbol",
        ] + CodedMasterDataSerializer.Meta.fields[2:]


class UnitSerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = Unit
        fields = CodedMasterDataSerializer.Meta.fields[:2] + [
            "symbol",
            "category",
            "decimal_places",
        ] + CodedMasterDataSerializer.Meta.fields[2:]


class IncotermSerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = Incoterm
        fields = CodedMasterDataSerializer.Meta.fields[:2] + [
            "rules_version",
            "transport_scope",
        ] + CodedMasterDataSerializer.Meta.fields[2:]


class PaymentMethodSerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = PaymentMethod
        fields = CodedMasterDataSerializer.Meta.fields


class TransportMethodSerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = TransportMethod
        fields = CodedMasterDataSerializer.Meta.fields


class PortSerializer(CodedMasterDataSerializer):
    country_code = serializers.CharField(source="country.code", read_only=True)
    country_name = serializers.CharField(source="country.chinese_name", read_only=True)

    class Meta(CodedMasterDataSerializer.Meta):
        model = Port
        fields = CodedMasterDataSerializer.Meta.fields[:2] + [
            "country",
            "country_code",
            "country_name",
            "administrative_area",
        ] + CodedMasterDataSerializer.Meta.fields[2:]

    def validate_country(self, value):
        if value.status != ReferenceStatus.ACTIVE or value.archived_at is not None:
            raise serializers.ValidationError("所属国家 / 地区已停用或归档。")
        return value


class CourierSerializer(CodedMasterDataSerializer):
    class Meta(CodedMasterDataSerializer.Meta):
        model = Courier
        fields = CodedMasterDataSerializer.Meta.fields[:2] + ["tracking_url_template"] + CodedMasterDataSerializer.Meta.fields[2:]


class NumberRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NumberRule
        fields = [
            "id", "number_type", "chinese_name", "prefix", "format_pattern",
            "sequence_name", "sequence_padding", "date_granularity", "reset_policy",
            "is_configured", "status", "sort_order", "description", "created_at", "updated_at",
        ]
        read_only_fields = fields


class ExchangeRateSerializer(serializers.ModelSerializer):
    base_currency_code = serializers.CharField(source="base_currency.code", read_only=True)
    quote_currency_code = serializers.CharField(source="quote_currency.code", read_only=True)
    entered_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ExchangeRate
        fields = [
            "id",
            "base_currency",
            "base_currency_code",
            "quote_currency",
            "quote_currency_code",
            "rate",
            "effective_date",
            "source_name",
            "source_version",
            "status",
            "description",
            "entered_by_employee",
            "entered_by_name",
            "correction_of",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "base_currency_code",
            "quote_currency_code",
            "entered_by_employee",
            "entered_by_name",
            "correction_of",
            "created_at",
            "updated_at",
            "status",
        ]

    def get_entered_by_name(self, instance) -> str:
        employee = instance.entered_by_employee
        return employee.display_name if employee else "系统"

    def validate(self, attrs):
        base = attrs.get("base_currency")
        quote = attrs.get("quote_currency")
        if base == quote:
            raise serializers.ValidationError({"quote_currency": "基础币种和目标币种不能相同。"})
        for field_name, currency in (("base_currency", base), ("quote_currency", quote)):
            if currency and (currency.status != ReferenceStatus.ACTIVE or currency.archived_at is not None):
                raise serializers.ValidationError({field_name: "币种已停用或归档。"})
        if attrs.get("rate") is not None and attrs["rate"] <= 0:
            raise serializers.ValidationError({"rate": "汇率必须大于 0。"})
        return attrs


class ExchangeRateCorrectionSerializer(serializers.Serializer):
    rate = serializers.DecimalField(
        max_digits=20,
        decimal_places=8,
        min_value=Decimal("0.00000001"),
    )
    effective_date = serializers.DateField()
    source_name = serializers.CharField(max_length=150)
    source_version = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ProductCategorySerializer(serializers.ModelSerializer):
    item_type_label = serializers.CharField(source="get_item_type_display", read_only=True)
    reference_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductCategory
        fields = [
            "id", "item_type", "item_type_label", "category_name", "status", "sort_order",
            "description", "reference_count", "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "item_type_label", "reference_count", "created_at", "updated_at", "archived_at"]

    def get_reference_count(self, instance) -> int:
        if hasattr(instance, "product_item_count"):
            return instance.product_item_count + getattr(instance, "raw_material_count", 0)
        return (
            instance.product_items.filter(archived_at__isnull=True).count()
            + instance.raw_materials.filter(archived_at__isnull=True).count()
        )


class ProductionUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionUnit
        fields = [
            "id", "unit_code", "unit_name", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class ProductColorSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    has_image = serializers.SerializerMethodField()

    class Meta:
        model = ProductColor
        fields = [
            "id", "color_card", "color_code", "color_name", "image_url", "has_image",
            "status", "sort_order", "description", "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "image_url", "has_image", "created_at", "updated_at", "archived_at"]

    def get_image_url(self, instance) -> str | None:
        if not instance.image_file_id:
            return None
        return f"/api/v1/reference-data/product-colors/{instance.pk}/image/"

    def get_has_image(self, instance) -> bool:
        return bool(instance.image_file_id)


class ProductItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.category_name", read_only=True)
    item_type = serializers.CharField(source="category.item_type", read_only=True)
    item_type_label = serializers.CharField(source="category.get_item_type_display", read_only=True)

    class Meta:
        model = ProductItem
        fields = [
            "id", "item_number", "category", "category_name", "item_type", "item_type_label",
            "legacy_data_id", "status", "sort_order", "description", "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = [
            "id", "category_name", "item_type", "item_type_label", "legacy_data_id",
            "created_at", "updated_at", "archived_at",
        ]

    def validate_category(self, value):
        if self.instance is not None and self.instance.category_id == value.pk:
            return value
        if value.status != ReferenceStatus.ACTIVE or value.archived_at is not None:
            raise serializers.ValidationError("产品类别已停用或归档。")
        return value


class InventoryMaterialMappingGuardMixin:
    material_source_key = ""

    def validate_inventory_raw_material(self, value):
        if self.instance is None or self.instance.inventory_raw_material_id == getattr(value, "pk", None):
            return value

        from apps.boms.models import BomLine
        from apps.material_issues.models import RequirementContribution

        bom_line_ids = BomLine.objects.filter(
            **{f"raw_values__{self.material_source_key}": str(self.instance.pk)}
        ).values_list("pk", flat=True)
        has_confirmed_issue = RequirementContribution.objects.filter(
            bom_line_id__in=bom_line_ids,
        ).filter(
            Q(requirement__internal_issued_quantity__gt=0)
            | Q(requirement__outsourcing_issued_quantity__gt=0)
        ).exists()
        if has_confirmed_issue:
            raise serializers.ValidationError(
                "该材质已有确认发料记录，不能直接改绑库存原料；请先完成冲销或受控迁移。"
            )
        return value


class FabricMaterialSerializer(InventoryMaterialMappingGuardMixin, serializers.ModelSerializer):
    material_source_key = "source_fabric_material_id"
    inventory_raw_material = serializers.PrimaryKeyRelatedField(
        queryset=RawMaterialInformation.objects.filter(item_type="MATERIAL", archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    inventory_material_number = serializers.CharField(
        source="inventory_raw_material.material_number", read_only=True, allow_null=True
    )
    inventory_material_name = serializers.CharField(
        source="inventory_raw_material.material_name", read_only=True, allow_null=True
    )
    inventory_material_unit = serializers.CharField(
        source="inventory_raw_material.unit.unit_name", read_only=True, allow_null=True
    )

    class Meta:
        model = FabricMaterial
        fields = [
            "id", "material_name", "inventory_raw_material", "inventory_material_number",
            "inventory_material_name", "inventory_material_unit", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = [
            "id", "inventory_material_number", "inventory_material_name", "inventory_material_unit",
            "created_at", "updated_at", "archived_at",
        ]


class FabricSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricSpecification
        fields = [
            "id", "specification_name", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class FabricWidthSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricWidth
        fields = [
            "id", "width_value", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class TubeProductNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeProductName
        fields = [
            "id", "product_name", "pinyin_search", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "pinyin_search", "created_at", "updated_at", "archived_at"]


class TubeThicknessSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeThickness
        fields = [
            "id", "thickness_value", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class TubeDiameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeDiameter
        fields = [
            "id", "diameter_value", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class TubeMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeMaterial
        fields = [
            "id", "material_name", "pinyin_search", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "pinyin_search", "created_at", "updated_at", "archived_at"]


class TubeShapeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeShape
        fields = [
            "id", "shape_name", "pinyin_search", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "pinyin_search", "created_at", "updated_at", "archived_at"]


class TubeCoatingColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = TubeCoatingColor
        fields = [
            "id", "color_name", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]


class AccessoryProductNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessoryProductName
        fields = [
            "id", "product_name", "unit_name", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "archived_at"]
        extra_kwargs = {"unit_name": {"allow_blank": False}}


class AccessorySpecificationSerializer(serializers.ModelSerializer):
    product_name_label = serializers.CharField(source="product_name.product_name", read_only=True)
    unit_name = serializers.CharField(source="product_name.unit_name", read_only=True)

    class Meta:
        model = AccessorySpecification
        fields = [
            "id", "product_name", "product_name_label", "unit_name", "specification_value", "weight",
            "status", "sort_order", "description", "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "product_name_label", "unit_name", "created_at", "updated_at", "archived_at"]

    def validate_product_name(self, value):
        if self.instance is not None and self.instance.product_name_id == value.pk:
            return value
        if value.status != ReferenceStatus.ACTIVE or value.archived_at is not None:
            raise serializers.ValidationError("辅料品名已停用或归档。")
        return value


class AccessoryColorSerializer(serializers.ModelSerializer):
    product_name_label = serializers.CharField(source="product_name.product_name", read_only=True)
    unit_name = serializers.CharField(source="product_name.unit_name", read_only=True)

    class Meta:
        model = AccessoryColor
        fields = [
            "id", "product_name", "product_name_label", "unit_name", "color_name",
            "status", "sort_order", "description", "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = ["id", "product_name_label", "unit_name", "created_at", "updated_at", "archived_at"]

    def validate_product_name(self, value):
        if self.instance is not None and self.instance.product_name_id == value.pk:
            return value
        if value.status != ReferenceStatus.ACTIVE or value.archived_at is not None:
            raise serializers.ValidationError("辅料品名已停用或归档。")
        return value


class AccessoryMaterialSerializer(InventoryMaterialMappingGuardMixin, serializers.ModelSerializer):
    material_source_key = "source_accessory_material_id"
    inventory_raw_material = serializers.PrimaryKeyRelatedField(
        queryset=RawMaterialInformation.objects.filter(item_type="MATERIAL", archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    inventory_material_number = serializers.CharField(
        source="inventory_raw_material.material_number", read_only=True, allow_null=True
    )
    inventory_material_name = serializers.CharField(
        source="inventory_raw_material.material_name", read_only=True, allow_null=True
    )
    inventory_material_unit = serializers.CharField(
        source="inventory_raw_material.unit.unit_name", read_only=True, allow_null=True
    )

    class Meta:
        model = AccessoryMaterial
        fields = [
            "id", "material_name", "inventory_raw_material", "inventory_material_number",
            "inventory_material_name", "inventory_material_unit", "status", "sort_order", "description",
            "created_at", "updated_at", "archived_at",
        ]
        read_only_fields = [
            "id", "inventory_material_number", "inventory_material_name", "inventory_material_unit",
            "created_at", "updated_at", "archived_at",
        ]


class ConfigReleaseSerializer(serializers.ModelSerializer):
    published_by = serializers.SerializerMethodField()

    class Meta:
        model = ConfigRelease
        fields = [
            "id",
            "version",
            "status",
            "notes",
            "published_at",
            "published_by",
            "failure_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_published_by(self, instance) -> dict | None:
        employee = instance.published_by_employee
        if employee is None:
            return None
        return {
            "id": str(employee.pk),
            "employee_code": employee.employee_code,
            "display_name": employee.display_name,
        }


class PublishConfigSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class SystemParameterSerializer(serializers.ModelSerializer):
    draft_value = serializers.JSONField(source="value_record.draft_value", read_only=True)

    class Meta:
        model = SystemParameterDefinition
        fields = [
            "id",
            "code",
            "chinese_name",
            "english_name",
            "group_code",
            "value_type",
            "default_value",
            "draft_value",
            "validation_rules",
            "status",
            "sort_order",
            "description",
            "updated_at",
        ]
        read_only_fields = fields


class SystemParameterDraftSerializer(serializers.Serializer):
    draft_value = serializers.JSONField(allow_null=True)

    def validate_draft_value(self, value):
        return validate_parameter_value(self.context["definition"], value)


class StatusActionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
    confirm_references = serializers.BooleanField(default=False, required=False)


class ArchiveActionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class PublishedOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    label = serializers.CharField()
    english_label = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=ReferenceStatus.choices)
    sort_order = serializers.IntegerField()
    color = serializers.CharField(allow_blank=True)
    extra = serializers.DictField()


class PublishedOptionsResponseSerializer(serializers.Serializer):
    data = PublishedOptionSerializer(many=True)
    meta = serializers.DictField()


class PublishedConfigStateSerializer(serializers.Serializer):
    config_version = serializers.IntegerField(allow_null=True)
    config_revision = serializers.CharField()


class PublishedConfigVersionResponseSerializer(serializers.Serializer):
    data = PublishedConfigStateSerializer()


class PublishedOptionsBatchQuerySerializer(serializers.Serializer):
    type_codes = serializers.CharField(max_length=1300)

    def validate_type_codes(self, value):
        import re

        codes = list(dict.fromkeys(part.strip().upper() for part in value.split(',')))
        if not 1 <= len(codes) <= 20 or any(not re.fullmatch(r'[A-Z0-9_]{1,64}', code) for code in codes):
            raise serializers.ValidationError('每次需要1至20个有效字典类型编码。')
        return codes


class PublishedOptionsBatchResponseSerializer(serializers.Serializer):
    data = serializers.DictField(child=PublishedOptionSerializer(many=True))
    errors = serializers.DictField(child=serializers.CharField())
    meta = PublishedConfigStateSerializer()


class ReferenceDataSummarySerializer(serializers.Serializer):
    active_dictionary_items = serializers.IntegerField()
    active_system_parameters = serializers.IntegerField()
    pending_changes = serializers.IntegerField()
    config_version = serializers.IntegerField(allow_null=True)


class MasterDataSummarySerializer(serializers.Serializer):
    category_counts = serializers.DictField(child=serializers.IntegerField(min_value=0))
    standard_source_count = serializers.IntegerField(min_value=0)
    standard_sources = serializers.ListField(child=serializers.CharField())
    base_currency = serializers.CharField(allow_null=True)
    config_version = serializers.IntegerField(allow_null=True)


class ProductionDataSummarySerializer(serializers.Serializer):
    category_counts = serializers.DictField(child=serializers.IntegerField(min_value=0))
