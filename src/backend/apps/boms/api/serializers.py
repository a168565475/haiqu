import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from rest_framework import serializers

from apps.products.models import ProductInformation, RawMaterialInformation
from apps.products.api.serializers import ProductInformationSerializer, RawMaterialInformationSerializer
from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
    FabricMaterial,
    FabricSpecification,
    FabricWidth,
    ProductColor,
    ProductItemType,
    ReferenceStatus,
)
from apps.reference_data.pinyin_search import build_pinyin_search
from apps.production_tasks.api.serializers import ProductionTaskProductInputSerializer

from ..maintenance import CONFIGURED_FIELD_LABELS
from ..fabric_material_sync import FABRIC_REFERENCE_FIELDS
from ..models import Bom, BomCreationMethod, BomLine, BomSection, BomSectionType
from ..selectors import pipe_dimension_numbers
from .image_serializers import BomLineImageSerializer


FIXED_BOM_SECTIONS = (
    ("管材类", BomSectionType.PROFILE),
    ("五金件", BomSectionType.ACCESSORY),
    ("塑料件类", BomSectionType.ACCESSORY),
    ("辅料类", BomSectionType.FABRIC),
    ("面料类", BomSectionType.FABRIC),
    ("包材类", BomSectionType.ACCESSORY),
    ("裁剪明细", BomSectionType.FABRIC),
)


class BomLineSerializer(serializers.ModelSerializer):
    fabric_source_line_id = serializers.UUIDField(read_only=True, allow_null=True)
    tube_shape = serializers.SerializerMethodField()
    tube_diameter = serializers.SerializerMethodField()
    tube_thickness = serializers.SerializerMethodField()
    tube_coating_color = serializers.SerializerMethodField()
    coating_unit_area_sqm = serializers.SerializerMethodField()
    purchase_unit_weight_kg = serializers.SerializerMethodField()
    tube_cut_piece_count = serializers.SerializerMethodField()
    tube_cut_length_m = serializers.SerializerMethodField()
    long_material_unit_weight_kg = serializers.SerializerMethodField()
    tube_unit_weight_kg = serializers.SerializerMethodField()
    long_material_total_weight_kg = serializers.SerializerMethodField()
    source_inventory_material_id = serializers.SerializerMethodField()
    source_raw_material_id = serializers.SerializerMethodField()
    hardware_material_number = serializers.SerializerMethodField()
    hardware_color = serializers.SerializerMethodField()
    hardware_flow_unit = serializers.SerializerMethodField()
    unit_material_weight_kg = serializers.SerializerMethodField()
    powder_coating_color = serializers.SerializerMethodField()
    powder_coating_unit_area_sqm = serializers.SerializerMethodField()
    plastic_material_number = serializers.SerializerMethodField()
    plastic_color = serializers.SerializerMethodField()
    source_accessory_product_name_id = serializers.SerializerMethodField()
    source_accessory_specification_id = serializers.SerializerMethodField()
    source_accessory_color_id = serializers.SerializerMethodField()
    source_accessory_material_id = serializers.SerializerMethodField()
    accessory_color = serializers.SerializerMethodField()
    source_fabric_material_id = serializers.SerializerMethodField()
    source_fabric_specification_id = serializers.SerializerMethodField()
    source_fabric_width_id = serializers.SerializerMethodField()
    source_product_color_id = serializers.SerializerMethodField()
    fabric_width = serializers.SerializerMethodField()
    fabric_color_card = serializers.SerializerMethodField()
    fabric_color_code = serializers.SerializerMethodField()
    fabric_color_name = serializers.SerializerMethodField()
    source_packaging_material_id = serializers.SerializerMethodField()
    packaging_material_number = serializers.SerializerMethodField()
    packaging_color = serializers.SerializerMethodField()
    units_per_box = serializers.SerializerMethodField()
    source_cutting_material_id = serializers.SerializerMethodField()
    cutting_material_number = serializers.SerializerMethodField()
    cutting_item_type = serializers.SerializerMethodField()
    cutting_item_type_display = serializers.SerializerMethodField()
    cutting_category = serializers.SerializerMethodField()
    cutting_color = serializers.SerializerMethodField()
    cutting_material_original = serializers.SerializerMethodField()
    images = BomLineImageSerializer(many=True, read_only=True)

    @staticmethod
    def _raw_value(obj, key, legacy_column=""):
        raw_values = obj.raw_values or {}
        value = raw_values.get(key, "")
        if key not in raw_values and legacy_column:
            value = raw_values.get(legacy_column, "")
        return str(value or "")

    @staticmethod
    def _is_hardware_line(obj):
        return (
            obj.section.section_type == BomSectionType.ACCESSORY
            and obj.section.title.strip() == "五金件"
        )

    @staticmethod
    def _is_plastic_line(obj):
        return (
            obj.section.section_type == BomSectionType.ACCESSORY
            and obj.section.title.strip() == "塑料件类"
        )

    @staticmethod
    def _is_auxiliary_line(obj):
        return (
            obj.section.section_type == BomSectionType.FABRIC
            and obj.section.title.strip() == "辅料类"
        )

    @staticmethod
    def _is_fabric_line(obj):
        return (
            obj.section.section_type == BomSectionType.FABRIC
            and obj.section.title.strip() == "面料类"
        )

    @staticmethod
    def _is_packaging_line(obj):
        return (
            obj.section.section_type == BomSectionType.ACCESSORY
            and obj.section.title.strip() == "包材类"
        )

    @staticmethod
    def _is_cutting_line(obj):
        return (
            obj.section.section_type == BomSectionType.FABRIC
            and obj.section.title.strip() == "裁剪明细"
        )

    def get_tube_shape(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        value = self._raw_value(obj, "tube_shape", "E")
        return "圆管" if value in {"Φ", "Ф", "φ"} else value

    def get_tube_diameter(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_diameter", "F")

    def get_tube_thickness(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_thickness", "G")

    def get_tube_coating_color(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_coating_color")

    def get_coating_unit_area_sqm(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "coating_unit_area_sqm")

    def get_purchase_unit_weight_kg(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "purchase_unit_weight_kg")

    def get_tube_cut_piece_count(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_cut_piece_count")

    def get_tube_cut_length_m(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_cut_length_m")

    def get_long_material_unit_weight_kg(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "long_material_unit_weight_kg")

    def get_tube_unit_weight_kg(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "tube_unit_weight_kg")

    def get_long_material_total_weight_kg(self, obj):
        if obj.section.section_type != BomSectionType.PROFILE:
            return ""
        return self._raw_value(obj, "long_material_total_weight_kg")

    def get_source_inventory_material_id(self, obj):
        return self._raw_value(obj, "source_inventory_material_id") or None

    def get_source_raw_material_id(self, obj):
        if not (self._is_hardware_line(obj) or self._is_plastic_line(obj)):
            return None
        return self._raw_value(obj, "source_raw_material_id") or None

    def get_hardware_material_number(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "hardware_material_number")

    def get_hardware_color(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "hardware_color")

    def get_hardware_flow_unit(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "hardware_flow_unit")

    def get_unit_material_weight_kg(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "unit_material_weight_kg")

    def get_powder_coating_color(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "powder_coating_color")

    def get_powder_coating_unit_area_sqm(self, obj):
        if not self._is_hardware_line(obj):
            return ""
        return self._raw_value(obj, "powder_coating_unit_area_sqm")

    def get_plastic_material_number(self, obj):
        if not self._is_plastic_line(obj):
            return ""
        return self._raw_value(obj, "plastic_material_number")

    def get_plastic_color(self, obj):
        if not self._is_plastic_line(obj):
            return ""
        return self._raw_value(obj, "plastic_color")

    def _auxiliary_source_id(self, obj, field):
        if not self._is_auxiliary_line(obj):
            return None
        return self._raw_value(obj, field) or None

    def get_source_accessory_product_name_id(self, obj):
        return self._auxiliary_source_id(obj, "source_accessory_product_name_id")

    def get_source_accessory_specification_id(self, obj):
        return self._auxiliary_source_id(obj, "source_accessory_specification_id")

    def get_source_accessory_color_id(self, obj):
        return self._auxiliary_source_id(obj, "source_accessory_color_id")

    def get_source_accessory_material_id(self, obj):
        return self._auxiliary_source_id(obj, "source_accessory_material_id")

    def get_accessory_color(self, obj):
        if not self._is_auxiliary_line(obj):
            return ""
        return self._raw_value(obj, "accessory_color")

    def _fabric_source_id(self, obj, field):
        if not self._is_fabric_line(obj):
            return None
        return self._raw_value(obj, field) or None

    def get_source_fabric_material_id(self, obj):
        return self._fabric_source_id(obj, "source_fabric_material_id")

    def get_source_fabric_specification_id(self, obj):
        return self._fabric_source_id(obj, "source_fabric_specification_id")

    def get_source_fabric_width_id(self, obj):
        return self._fabric_source_id(obj, "source_fabric_width_id")

    def get_source_product_color_id(self, obj):
        return self._fabric_source_id(obj, "source_product_color_id")

    def get_fabric_width(self, obj):
        if not self._is_fabric_line(obj):
            return ""
        return self._raw_value(obj, "fabric_width")

    def get_fabric_color_card(self, obj):
        if not self._is_fabric_line(obj):
            return ""
        return self._raw_value(obj, "fabric_color_card")

    def get_fabric_color_code(self, obj):
        if not self._is_fabric_line(obj):
            return ""
        return self._raw_value(obj, "fabric_color_code")

    def get_fabric_color_name(self, obj):
        if not self._is_fabric_line(obj):
            return ""
        return self._raw_value(obj, "fabric_color_name")

    def _packaging_value(self, obj, field):
        if not self._is_packaging_line(obj):
            return ""
        return self._raw_value(obj, field)

    def get_source_packaging_material_id(self, obj):
        return self._packaging_value(obj, "source_packaging_material_id") or None

    def get_packaging_material_number(self, obj):
        return self._packaging_value(obj, "packaging_material_number")

    def get_packaging_color(self, obj):
        return self._packaging_value(obj, "packaging_color")

    def get_units_per_box(self, obj):
        return self._packaging_value(obj, "units_per_box")

    def _cutting_value(self, obj, field):
        if not self._is_cutting_line(obj):
            return ""
        return self._raw_value(obj, field)

    def get_source_cutting_material_id(self, obj):
        return self._cutting_value(obj, "source_cutting_material_id") or None

    def get_cutting_material_number(self, obj):
        return self._cutting_value(obj, "cutting_material_number")

    def _cutting_source(self, obj):
        if not self._is_cutting_line(obj):
            return None
        cache_attribute = "_bom_cutting_source_cache"
        if hasattr(obj, cache_attribute):
            return getattr(obj, cache_attribute)
        source_id = self._raw_value(obj, "source_cutting_material_id")
        source = None
        if source_id:
            source = (
                RawMaterialInformation.objects.select_related("category", "color")
                .filter(pk=source_id)
                .first()
            )
        setattr(obj, cache_attribute, source)
        return source

    def get_cutting_item_type(self, obj):
        value = self._cutting_value(obj, "cutting_item_type")
        source = self._cutting_source(obj) if not value else None
        return value or (source.item_type if source else "")

    def get_cutting_item_type_display(self, obj):
        value = self._cutting_value(obj, "cutting_item_type_display")
        source = self._cutting_source(obj) if not value else None
        return value or (source.get_item_type_display() if source else "")

    def get_cutting_category(self, obj):
        return self._cutting_value(obj, "cutting_category") or (obj.category if self._is_cutting_line(obj) else "")

    def get_cutting_color(self, obj):
        value = self._cutting_value(obj, "cutting_color")
        source = self._cutting_source(obj) if not value else None
        if not source:
            return value
        return source.color.color_name if source.color_id else source.color_snapshot

    def get_cutting_material_original(self, obj) -> str | None:
        if not self._is_cutting_line(obj):
            return None
        return (obj.raw_values or {}).get("cutting_material_original", obj.material)

    class Meta:
        model = BomLine
        fields = [
            "id",
            "component_identity", "cutting_length_mm", "pieces_per_product", "pieces_per_bar",
            "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters",
            "fabric_source_line_id", "fabric_meters_per_set",
            "cutting_pieces_per_set", "fabric_meters_per_piece", "cutting_sets_per_product",
            "line_number",
            "source_row_number",
            "source_serial",
            "category",
            "material",
            "part_name",
            "specification",
            "raw_material",
            "length_value",
            "unit_consumption",
            "total_consumption",
            "unit",
            "hardness",
            "original_material_length",
            "branch_count",
            "budget_quantity",
            "inventory_quantity",
            "weight_grams",
            "cut_piece_quantity",
            "purchase_consumption",
            "source_order_quantity",
            "total_purchase_quantity",
            "notes",
            "tube_shape",
            "tube_diameter",
            "tube_thickness",
            "tube_coating_color",
            "coating_unit_area_sqm",
            "purchase_unit_weight_kg",
            "tube_cut_piece_count",
            "tube_cut_length_m",
            "long_material_unit_weight_kg",
            "tube_unit_weight_kg",
            "long_material_total_weight_kg",
            "source_inventory_material_id",
            "source_raw_material_id",
            "hardware_material_number",
            "hardware_color",
            "hardware_flow_unit",
            "unit_material_weight_kg",
            "powder_coating_color",
            "powder_coating_unit_area_sqm",
            "plastic_material_number",
            "plastic_color",
            "source_accessory_product_name_id",
            "source_accessory_specification_id",
            "source_accessory_color_id",
            "source_accessory_material_id",
            "accessory_color",
            "source_fabric_material_id",
            "source_fabric_specification_id",
            "source_fabric_width_id",
            "source_product_color_id",
            "fabric_width",
            "fabric_color_card",
            "fabric_color_code",
            "fabric_color_name",
            "source_packaging_material_id",
            "packaging_material_number",
            "packaging_color",
            "units_per_box",
            "source_cutting_material_id",
            "cutting_material_number",
            "cutting_item_type",
            "cutting_item_type_display",
            "cutting_category",
            "cutting_color",
            "cutting_material_original",
            "images",
            "raw_values",
            "source_formulas",
        ]


class BomSectionSerializer(serializers.ModelSerializer):
    section_type_display = serializers.CharField(source="get_section_type_display", read_only=True)
    lines = BomLineSerializer(many=True, read_only=True)

    class Meta:
        model = BomSection
        fields = [
            "id",
            "line_number",
            "section_type",
            "section_type_display",
            "title",
            "source_title_row",
            "source_header_row",
            "headers",
            "calculation_rows",
            "lines",
        ]


class BomHardwareMaterialSerializer(serializers.ModelSerializer):
    item_type_display = serializers.CharField(source="get_item_type_display", read_only=True)
    category_name = serializers.CharField(source="category.category_name", read_only=True)
    unit_code = serializers.CharField(source="unit.unit_code", read_only=True)
    unit_name = serializers.CharField(source="unit.unit_name", read_only=True)
    color_name = serializers.SerializerMethodField()

    class Meta:
        model = RawMaterialInformation
        fields = [
            "id",
            "material_number",
            "item_type",
            "item_type_display",
            "category_name",
            "material_name",
            "material",
            "color_name",
            "specification",
            "unit_code",
            "unit_name",
            "weight_kg",
            "flow_unit",
            "number_value",
        ]

    @staticmethod
    def get_color_name(instance) -> str:
        return instance.color.color_name if instance.color_id else instance.color_snapshot


class BomPipeMaterialMatchQuerySerializer(serializers.Serializer):
    material = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    diameter = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    thickness = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    tube_shape = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    raw_bar_length_m = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"), required=False)

    def validate_diameter(self, value):
        numbers = pipe_dimension_numbers(value)
        if value and (not numbers or len(numbers) > 2):
            raise serializers.ValidationError("管材截面须为一个或两个有效毫米尺寸。")
        return value

    def validate_thickness(self, value):
        numbers = pipe_dimension_numbers(value)
        if value and (not numbers or len(numbers) != 1):
            raise serializers.ValidationError("管材厚度须为有效的正数毫米。")
        return value


class BomPipeMaterialMatchCandidateSerializer(BomHardwareMaterialSerializer):
    class Meta(BomHardwareMaterialSerializer.Meta):
        fields = [*BomHardwareMaterialSerializer.Meta.fields, "diameter", "thickness", "length"]


class BomPipeMaterialMatchResultSerializer(serializers.Serializer):
    candidates = BomPipeMaterialMatchCandidateSerializer(many=True)
    automatic_source_id = serializers.UUIDField(allow_null=True)
    reason = serializers.ChoiceField(choices=["unique", "multiple", "no_match", "incomplete", "needs_review"])


class BomPipeMaterialMatchResponseSerializer(serializers.Serializer):
    data = BomPipeMaterialMatchResultSerializer()


class BomRawMaterialGroupSerializer(serializers.Serializer):
    material_name = serializers.CharField()
    count = serializers.IntegerField()
    pinyin_search = serializers.CharField()


class BomRawMaterialGroupsResponseSerializer(serializers.Serializer):
    data = BomRawMaterialGroupSerializer(many=True)


class BomAccessorySpecificationOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessorySpecification
        fields = ["id", "specification_value"]


class BomAccessoryColorOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessoryColor
        fields = ["id", "color_name"]


class BomAuxiliaryProductOptionSerializer(serializers.ModelSerializer):
    pinyin_search = serializers.SerializerMethodField()
    specifications = BomAccessorySpecificationOptionSerializer(
        source="active_specifications",
        many=True,
        read_only=True,
    )
    colors = BomAccessoryColorOptionSerializer(
        source="active_colors",
        many=True,
        read_only=True,
    )

    class Meta:
        model = AccessoryProductName
        fields = ["id", "product_name", "pinyin_search", "unit_name", "specifications", "colors"]

    @staticmethod
    def get_pinyin_search(instance) -> str:
        return build_pinyin_search(instance.product_name)


class BomAuxiliaryCreateInputSerializer(serializers.Serializer):
    product_name = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)
    unit_name = serializers.CharField(max_length=50, allow_blank=False, trim_whitespace=True)
    specification = serializers.CharField(max_length=300, allow_blank=False, trim_whitespace=True)
    color = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)
    material = serializers.CharField(max_length=150, allow_blank=True, required=False, trim_whitespace=True)


class BomAccessoryMaterialOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessoryMaterial
        fields = ["id", "material_name"]


class BomFabricMaterialOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricMaterial
        fields = ["id", "material_name"]


class BomFabricSpecificationOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricSpecification
        fields = ["id", "specification_name"]


class BomFabricWidthOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricWidth
        fields = ["id", "width_value"]


class BomProductColorOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductColor
        fields = ["id", "color_card", "color_code", "color_name"]


class BomEditorReferenceOptionsDataSerializer(serializers.Serializer):
    auxiliary_products = BomAuxiliaryProductOptionSerializer(many=True)
    accessory_materials = BomAccessoryMaterialOptionSerializer(many=True)
    fabric_materials = BomFabricMaterialOptionSerializer(many=True)
    fabric_specifications = BomFabricSpecificationOptionSerializer(many=True)
    fabric_widths = BomFabricWidthOptionSerializer(many=True)
    product_colors = BomProductColorOptionSerializer(many=True)


class BomEditorReferenceOptionsResponseSerializer(serializers.Serializer):
    data = BomEditorReferenceOptionsDataSerializer()


class BomListSerializer(serializers.ModelSerializer):
    production_task_number = serializers.CharField(source="production_task.task_number", read_only=True)
    order_number = serializers.CharField(source="production_task.order_number", read_only=True)
    product_color_snapshot = serializers.SerializerMethodField()
    source_sales_order_number = serializers.CharField(
        source="production_task.sales_order.order_number",
        read_only=True,
        allow_null=True,
    )
    is_historical_unlinked = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    creation_method_display = serializers.CharField(source="get_creation_method_display", read_only=True)
    updated_by_name = serializers.SerializerMethodField()
    section_summary = serializers.SerializerMethodField()
    batch_quantity_breakdown = serializers.SerializerMethodField()
    current_order_quantity = serializers.DecimalField(
        source="product_line.quantity",
        max_digits=18,
        decimal_places=4,
        read_only=True,
    )
    product_unit_name = serializers.SerializerMethodField()
    is_order_quantity_outdated = serializers.SerializerMethodField()
    is_order_product_outdated = serializers.SerializerMethodField()
    quantity_requires_confirmation = serializers.SerializerMethodField()
    confirmed_by_name = serializers.CharField(source="confirmed_by_employee.display_name", read_only=True, allow_null=True)
    customer_name = serializers.CharField(source="production_task.customer_account.account_name", read_only=True, default="")
    planned_start_date = serializers.DateField(source="production_task.planned_start_date", read_only=True, allow_null=True)
    planned_end_date = serializers.DateField(source="production_task.planned_end_date", read_only=True, allow_null=True)
    product_master_id = serializers.UUIDField(source="product_id", read_only=True, allow_null=True)
    product_category_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_unit_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_color_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Bom
        fields = [
            "id",
            "bom_number",
            "version_number",
            "production_task_number",
            "order_number",
            "customer_name",
            "planned_start_date",
            "planned_end_date",
            "source_sales_order_number",
            "is_historical_unlinked",
            "product_number_snapshot",
            "product_code_snapshot",
            "item_number_snapshot",
            "product_name_snapshot",
            "specification_snapshot",
            "material_snapshot",
            "product_master_id",
            "product_category_id",
            "product_unit_id",
            "product_color_id",
            "product_color_snapshot",
            "product_color_name_snapshot",
            "product_color_code_snapshot",
            "product_color_card_snapshot",
            "product_unit_code_snapshot",
            "product_unit_name_snapshot",
            "product_category_snapshot",
            "order_quantity",
            "current_order_quantity",
            "product_unit_name",
            "is_order_quantity_outdated",
            "is_order_product_outdated",
            "source_quantity",
            "batch_quantity",
            "batch_quantity_breakdown",
            "quantity_difference",
            "quantity_requires_confirmation",
            "status",
            "status_display",
            "creation_method",
            "creation_method_display",
            "section_count",
            "line_count",
            "section_summary",
            "maintenance_match_count",
            "maintenance_unmatched_count",
            "source_original_name",
            "source_sheet_name",
            "updated_by_name",
            "confirmed_by_name",
            "confirmed_at",
            "quantity_difference_reason",
            "confirmation_reason",
            "created_at",
            "updated_at",
        ]

    def get_updated_by_name(self, obj):
        employee = obj.updated_by_employee or obj.created_by_employee
        return employee.display_name if employee else "系统"

    def get_product_color_snapshot(self, obj) -> str:
        return obj.product_color_name_snapshot if obj.product_information_confirmed_at else (obj.product_color_name_snapshot or obj.product_line.color_name_snapshot)

    def get_product_unit_name(self, obj) -> str:
        return obj.product_unit_name_snapshot or obj.product_line.unit.unit_name

    def get_is_historical_unlinked(self, obj) -> bool:
        return obj.production_task.sales_order_id is None

    def get_section_summary(self, obj):
        return [
            {
                "type": section.section_type,
                "label": section.get_section_type_display(),
                "count": getattr(section, "prefetched_line_count", None)
                if getattr(section, "prefetched_line_count", None) is not None
                else section.lines.count(),
            }
            for section in obj.sections.all()
        ]

    def get_batch_quantity_breakdown(self, obj):
        return [batch.quantity for batch in obj.production_task.delivery_batches.all()]

    def get_is_order_quantity_outdated(self, obj) -> bool:
        latest_active_bom_id = getattr(obj, "latest_active_bom_id", None)
        if latest_active_bom_id is None:
            latest_active_bom_id = (
                Bom.objects.filter(
                    product_line_id=obj.product_line_id,
                    archived_at__isnull=True,
                )
                .order_by("-version_number", "-id")
                .values_list("id", flat=True)
                .first()
            )
        return latest_active_bom_id == obj.pk and obj.product_line.quantity != obj.order_quantity

    def get_is_order_product_outdated(self, obj) -> bool:
        # 核对后 BOM 可以有意采用与任务单不同的产品；确认前尚未回写，不代表订单已变更。
        if obj.product_information_confirmed_at:
            return False
        latest_active_bom_id = getattr(obj, "latest_active_bom_id", None)
        if latest_active_bom_id is None:
            latest_active_bom_id = (
                Bom.objects.filter(
                    product_line_id=obj.product_line_id,
                    archived_at__isnull=True,
                )
                .order_by("-version_number", "-id")
                .values_list("id", flat=True)
                .first()
            )
        if latest_active_bom_id != obj.pk:
            return False
        product_line = obj.product_line
        return any(
            [
                obj.product_number_snapshot != product_line.product_number_snapshot,
                obj.product_code_snapshot != product_line.product_code_snapshot,
                obj.product_name_snapshot != product_line.product_name_snapshot,
                obj.specification_snapshot != product_line.specification_snapshot,
            ]
        )

    def get_quantity_requires_confirmation(self, obj) -> bool:
        return (
            self.get_is_order_quantity_outdated(obj)
            or self.get_is_order_product_outdated(obj)
            or (obj.source_quantity is not None and obj.source_quantity != obj.order_quantity)
            or (obj.batch_quantity is not None and obj.batch_quantity != obj.order_quantity)
        )


class BomDetailSerializer(BomListSerializer):
    product_information = ProductInformationSerializer(source="product", read_only=True, allow_null=True)
    sections = BomSectionSerializer(many=True, read_only=True)
    copied_from_number = serializers.CharField(source="copied_from.bom_number", read_only=True, allow_null=True)
    configured_field_labels = serializers.SerializerMethodField()
    production_task_id = serializers.UUIDField(read_only=True)
    production_task_product_id = serializers.UUIDField(source="product_line.id", read_only=True)
    production_task_product_master_id = serializers.UUIDField(source="product_line.product_id", read_only=True, allow_null=True)
    production_task_customer_product_name = serializers.CharField(source="product_line.customer_product_name_snapshot", read_only=True)
    production_task_customer_specification = serializers.CharField(source="product_line.customer_specification_snapshot", read_only=True)
    production_task_customer_color = serializers.CharField(source="product_line.customer_color_snapshot", read_only=True)
    product_information_confirmed = serializers.SerializerMethodField()
    product_information_confirmed_by_name = serializers.CharField(source="product_information_confirmed_by_employee.display_name", read_only=True, allow_null=True)

    class Meta(BomListSerializer.Meta):
        fields = BomListSerializer.Meta.fields + [
            "product_information",
            "source_metadata",
            "calculation_summary",
            "maintenance_unmatched_values",
            "copied_from_number",
            "configured_field_labels",
            "sections",
            "production_task_id",
            "production_task_product_id",
            "production_task_product_master_id",
            "production_task_customer_product_name",
            "production_task_customer_specification",
            "production_task_customer_color",
            "product_information_confirmed",
            "product_information_confirmed_at",
            "product_information_confirmed_by_name",
        ]

    def get_configured_field_labels(self, _obj) -> list[str]:
        return CONFIGURED_FIELD_LABELS

    def get_product_information_confirmed(self, obj) -> bool:
        return bool(obj.product_information_confirmed_at and obj.product_id and obj.product_color_id)


class BomProductConfirmationSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True),
        required=False,
    )
    new_product = ProductInformationSerializer(required=False)
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    color_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    material = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if ("product" in attrs) == ("new_product" in attrs):
            raise serializers.ValidationError({"product_id": "请选择已有产品，或填写完整的新产品资料。"})
        return attrs


class ProductionTaskProductUpdateField(serializers.Field):
    default_error_messages = {"invalid": "生产任务产品更新数据格式不正确。"}

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError, json.JSONDecodeError):
                self.fail("invalid")
        if not isinstance(data, dict):
            self.fail("invalid")
        serializer = ProductionTaskProductInputSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if not values.get("details"):
            raise serializers.ValidationError("必须填写生产任务单明细。")
        if values["unit"].pk != values["product"].unit_id:
            raise serializers.ValidationError("单位必须使用产品生产维护单位。")
        if values["color_code"] != values["product_color"].color_code:
            raise serializers.ValidationError("色号与所选色卡、颜色不匹配。")
        if values["currency"].code == "CNY" and values["exchange_rate"] != Decimal("1"):
            raise serializers.ValidationError("CNY 汇率必须为 1。")
        return values

    def to_representation(self, value):
        return value


class BomCreateInputSerializer(serializers.Serializer):
    production_task_product_id = serializers.UUIDField()
    creation_method = serializers.ChoiceField(choices=BomCreationMethod.choices)
    source_bom_id = serializers.UUIDField(required=False, allow_null=True)
    workbook = serializers.FileField(required=False)
    production_task_product_update = ProductionTaskProductUpdateField(required=False)
    quantity_difference_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        method = attrs["creation_method"]
        if method == BomCreationMethod.IMPORT and not attrs.get("workbook"):
            raise serializers.ValidationError({"workbook": "请选择 BOM Excel 文件。"})
        if method == BomCreationMethod.COPY and not attrs.get("source_bom_id"):
            raise serializers.ValidationError({"source_bom_id": "请选择要复制的历史 BOM。"})
        if method != BomCreationMethod.IMPORT and attrs.get("workbook"):
            raise serializers.ValidationError({"workbook": "当前建立方式不接收 Excel 文件。"})
        return attrs


class BomPreviewInputSerializer(serializers.Serializer):
    production_task_product_id = serializers.UUIDField()
    workbook = serializers.FileField()
    production_task_product_update = ProductionTaskProductUpdateField(required=False)


class PendingRawMaterialSerializer(RawMaterialInformationSerializer):
    # 原模型字段的 UniqueValidator 也要延后，否则同档复用在完整身份匹配前就被拒绝。
    material_number = serializers.CharField(max_length=100)

    def validate_material_number(self, value):
        # 全属性匹配可能复用已存在品号；冲突由规划器在匹配后检查，不提前误拒绝。
        value = value.strip()
        if not value:
            raise serializers.ValidationError("请输入品号。")
        return value


class BomLineWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    client_key = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    category = serializers.CharField(required=False, allow_blank=True, max_length=150, trim_whitespace=True)
    material = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    part_name = serializers.CharField(max_length=300, trim_whitespace=True)
    specification = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)
    raw_material = serializers.CharField(required=False, allow_blank=True, max_length=2000, trim_whitespace=True)
    length_value = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    unit_consumption = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    total_consumption = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    unit = serializers.CharField(required=False, allow_blank=True, max_length=50, trim_whitespace=True)
    hardness = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    original_material_length = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    branch_count = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    budget_quantity = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    inventory_quantity = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    weight_grams = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    cut_piece_quantity = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    purchase_consumption = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    source_order_quantity = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    total_purchase_quantity = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, trim_whitespace=True)
    tube_shape = serializers.CharField(required=False, allow_blank=True, max_length=150, trim_whitespace=True)
    tube_diameter = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    tube_thickness = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    tube_coating_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    coating_unit_area_sqm = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    purchase_unit_weight_kg = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    fabric_source_line_id = serializers.UUIDField(required=False, allow_null=True)
    fabric_source_client_key = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    fabric_meters_per_set = serializers.DecimalField(required=False, allow_null=True, max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    cutting_pieces_per_set = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=99999999999999)
    fabric_meters_per_piece = serializers.DecimalField(required=False, allow_null=True, max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    cutting_sets_per_product = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=99999999999999)
    tube_cut_piece_count = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    source_inventory_material_id = serializers.UUIDField(required=False, allow_null=True)
    pending_raw_material = PendingRawMaterialSerializer(required=False, write_only=True)
    source_raw_material_id = serializers.UUIDField(required=False, allow_null=True)
    hardware_material_number = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    hardware_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    hardware_flow_unit = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    unit_material_weight_kg = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    powder_coating_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    powder_coating_unit_area_sqm = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    plastic_material_number = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    plastic_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    source_accessory_product_name_id = serializers.UUIDField(required=False, allow_null=True)
    source_accessory_specification_id = serializers.UUIDField(required=False, allow_null=True)
    source_accessory_color_id = serializers.UUIDField(required=False, allow_null=True)
    source_accessory_material_id = serializers.UUIDField(required=False, allow_null=True)
    accessory_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    source_fabric_material_id = serializers.UUIDField(required=False, allow_null=True)
    source_fabric_specification_id = serializers.UUIDField(required=False, allow_null=True)
    source_fabric_width_id = serializers.UUIDField(required=False, allow_null=True)
    source_product_color_id = serializers.UUIDField(required=False, allow_null=True)
    fabric_width = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    fabric_color_card = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    fabric_color_code = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    fabric_color_name = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    source_packaging_material_id = serializers.UUIDField(required=False, allow_null=True)
    packaging_material_number = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    packaging_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    units_per_box = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    source_cutting_material_id = serializers.UUIDField(required=False, allow_null=True)
    cutting_material_number = serializers.CharField(required=False, allow_blank=True, max_length=100, trim_whitespace=True)
    cutting_item_type = serializers.CharField(required=False, allow_blank=True, max_length=30, trim_whitespace=True)
    cutting_item_type_display = serializers.CharField(required=False, allow_blank=True, max_length=50, trim_whitespace=True)
    cutting_category = serializers.CharField(required=False, allow_blank=True, max_length=150, trim_whitespace=True)
    cutting_color = serializers.CharField(required=False, allow_blank=True, max_length=200, trim_whitespace=True)
    draft_image_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        max_length=20,
        write_only=True,
    )

    def validate(self, attrs):
        if attrs.get("pending_raw_material") and any(attrs.get(field) for field in (
            "source_inventory_material_id", "source_raw_material_id", "source_cutting_material_id",
            "source_packaging_material_id",
        )):
            raise serializers.ValidationError("待新增原料不能同时指定已存在的库存来源。")
        if attrs.get("fabric_source_line_id") and attrs.get("fabric_source_client_key"):
            raise serializers.ValidationError("来源面料不能同时指定已保存行和未保存行。")
        return attrs

    @staticmethod
    def _nonnegative_decimal(value, label):
        if value == "":
            return value
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise serializers.ValidationError(f"{label}必须是有效数字。") from exc
        if not parsed.is_finite() or parsed < 0:
            raise serializers.ValidationError(f"{label}不能小于 0。")
        return value

    def validate_unit_material_weight_kg(self, value):
        return self._nonnegative_decimal(value, "单个材料重量")

    def validate_powder_coating_unit_area_sqm(self, value):
        return self._nonnegative_decimal(value, "喷塑单个面积")

    def validate_cut_piece_quantity(self, value):
        return self._nonnegative_decimal(value, "裁片量")

    def validate_units_per_box(self, value):
        if value == "":
            return value
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise serializers.ValidationError("箱数（多少一箱）必须是正整数。") from exc
        if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
            raise serializers.ValidationError("箱数（多少一箱）必须是正整数。")
        return format(parsed.to_integral_value(), "f")


class BomSectionWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    section_type = serializers.ChoiceField(choices=BomSectionType.choices)
    title = serializers.CharField(max_length=300, trim_whitespace=True)
    lines = BomLineWriteSerializer(many=True, allow_empty=True, max_length=5000)


class BomMaterialFlowPreviewInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['PIPE', 'FABRIC'])
    order_quantity = serializers.CharField(max_length=30)
    cutting_length_mm = serializers.CharField(max_length=30, required=False)
    pieces_per_product = serializers.CharField(max_length=30, required=False)
    pieces_per_bar = serializers.CharField(max_length=30, required=False)
    unit_consumption = serializers.CharField(max_length=30, required=False)


class BomMaterialFlowPreviewResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()


class BomUpdateInputSerializer(serializers.Serializer):
    sections = BomSectionWriteSerializer(many=True, allow_empty=True, max_length=20)
    intent = serializers.ChoiceField(choices=("draft", "verify"), default="draft")
    confirmation_token = serializers.CharField(required=False, allow_blank=True, max_length=100000)
    quantity_confirmation_reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    @staticmethod
    def _fixed_title_for_existing_section(section, used_titles):
        if section.section_type == BomSectionType.PROFILE:
            return "管材类"

        compact_title = "".join(section.title.split())
        keyword_groups = (
            ("裁剪明细", ("裁剪", "裁片")),
            ("塑料件类", ("塑料",)),
            ("包材类", ("包材", "包装")),
            ("五金件", ("五金", "配件")),
            ("面料类", ("面辅料", "面料")),
            ("辅料类", ("辅料",)),
        )
        for fixed_title, keywords in keyword_groups:
            if fixed_title not in used_titles and any(keyword in compact_title for keyword in keywords):
                return fixed_title

        candidates = (
            ("面料类", "辅料类", "裁剪明细")
            if section.section_type == BomSectionType.FABRIC
            else ("五金件", "塑料件类", "包材类")
        )
        return next((title for title in candidates if title not in used_titles), section.title)

    @classmethod
    def _validate_fixed_sections(cls, sections, bom):
        expected_by_title = dict(FIXED_BOM_SECTIONS)
        submitted_pairs = [(section["title"].strip(), section["section_type"]) for section in sections]
        expected_pairs = set(FIXED_BOM_SECTIONS)
        if len(submitted_pairs) != len(FIXED_BOM_SECTIONS) or set(submitted_pairs) != expected_pairs:
            raise serializers.ValidationError(
                "保存时必须完整提交固定七个分区：管材类、五金件、塑料件类、辅料类、面料类、包材类、裁剪明细，且不能新增、删除或重复。"
            )

        if bom:
            existing_sections = list(bom.sections.all().order_by("line_number", "id"))
            existing_by_id = {section.pk: section for section in existing_sections}
            submitted_ids = {section["id"] for section in sections if section.get("id")}
            unknown_ids = submitted_ids - set(existing_by_id)
            missing_ids = set(existing_by_id) - submitted_ids
            if unknown_ids:
                raise serializers.ValidationError("存在不属于当前 BOM 的用料分区，请刷新后重试。")
            if missing_ids:
                raise serializers.ValidationError("已有用料分区不能删除，请保留固定七个分区后重试。")

            used_titles = set()
            canonical_titles = {}
            for existing in existing_sections:
                fixed_title = cls._fixed_title_for_existing_section(existing, used_titles)
                canonical_titles[existing.pk] = fixed_title
                if fixed_title in expected_by_title:
                    used_titles.add(fixed_title)

            for submitted in sections:
                section_id = submitted.get("id")
                if not section_id:
                    continue
                existing = existing_by_id[section_id]
                if submitted["section_type"] != existing.section_type:
                    raise serializers.ValidationError("已有用料分区的类型不能修改。")
                if submitted["title"].strip() != canonical_titles[section_id]:
                    raise serializers.ValidationError("已有用料分区的名称不能修改。")

        fixed_order = {title: index for index, (title, _) in enumerate(FIXED_BOM_SECTIONS)}
        sections.sort(key=lambda section: fixed_order[section["title"].strip()])
        return sections

    @staticmethod
    def _set_hardware_source_snapshot(line, source, existing_line=None):
        existing_raw_values = existing_line.raw_values or {} if existing_line else {}
        same_existing_source = bool(
            existing_line
            and str(existing_raw_values.get("source_raw_material_id") or "") == str(source.pk)
        )
        if same_existing_source:
            # 已保存的来源字段是历史快照，生产维护后续改名不应污染已有 BOM。
            line.update(
                {
                    "category": existing_line.category,
                    "part_name": existing_line.part_name,
                    "material": existing_line.material,
                    "specification": existing_line.specification,
                    "raw_material": existing_line.raw_material,
                    "unit": existing_line.unit,
                    "hardware_material_number": existing_raw_values.get("hardware_material_number", ""),
                    "hardware_color": existing_raw_values.get("hardware_color", ""),
                    "hardware_flow_unit": existing_raw_values.get("hardware_flow_unit") or source.flow_unit or "",
                }
            )
            return

        line.update(
            {
                "category": "五金",
                "part_name": source.material_name,
                "material": source.material,
                "specification": source.specification,
                "raw_material": source.material_number,
                "unit": source.unit.unit_name,
                "hardware_material_number": source.material_number,
                "hardware_color": source.color.color_name if source.color_id else source.color_snapshot,
                "hardware_flow_unit": source.flow_unit or "",
            }
        )

    @staticmethod
    def _raw_source_id(existing_line, field):
        if existing_line is None:
            return ""
        return str((existing_line.raw_values or {}).get(field) or "")

    @classmethod
    def _same_source(cls, existing_line, field, source_id):
        return bool(source_id and cls._raw_source_id(existing_line, field) == str(source_id))

    @staticmethod
    def _active_reference(instance):
        return instance.status == ReferenceStatus.ACTIVE and instance.archived_at is None

    @staticmethod
    def _active_raw_material(instance, category_name):
        return bool(
            instance.item_type == ProductItemType.MATERIAL
            and instance.category.item_type == ProductItemType.MATERIAL
            and instance.category.category_name == category_name
            and instance.archived_at is None
            and instance.category.status == ReferenceStatus.ACTIVE
            and instance.category.archived_at is None
        )

    @staticmethod
    def _active_semi_finished(instance):
        return bool(
            instance.item_type == ProductItemType.SEMI_FINISHED
            and instance.category.item_type == ProductItemType.SEMI_FINISHED
            and instance.archived_at is None
            and instance.category.status == ReferenceStatus.ACTIVE
            and instance.category.archived_at is None
        )

    @classmethod
    def _set_inventory_source_snapshot(cls, line, source, existing_line=None):
        if cls._same_source(existing_line, "source_inventory_material_id", source.pk):
            line.update(
                {
                    "category": existing_line.category,
                    "part_name": existing_line.part_name,
                    "material": existing_line.material,
                    "specification": existing_line.specification,
                    "raw_material": existing_line.raw_material,
                    "unit": existing_line.unit,
                }
            )
            return
        line.update(
            {
                "category": source.category.category_name,
                "part_name": source.material_name,
                "material": source.material,
                "specification": source.specification,
                "raw_material": source.material_number,
                "unit": source.unit.unit_name,
            }
        )

    @staticmethod
    def _raw_material_color(source):
        return source.color.color_name if source.color_id else source.color_snapshot

    @classmethod
    def _set_plastic_source_snapshot(cls, line, source, existing_line=None):
        existing_values = existing_line.raw_values or {} if existing_line else {}
        if cls._same_source(existing_line, "source_raw_material_id", source.pk):
            line.update(
                {
                    "category": existing_line.category,
                    "part_name": existing_line.part_name,
                    "material": existing_line.material,
                    "specification": existing_line.specification,
                    "raw_material": existing_line.raw_material,
                    "unit": existing_line.unit,
                    "plastic_material_number": existing_values.get("plastic_material_number", ""),
                    "plastic_color": existing_values.get("plastic_color", ""),
                }
            )
            return
        line.update(
            {
                "category": "塑料件",
                "part_name": source.material_name,
                "material": source.material,
                "specification": source.specification,
                "raw_material": source.material_number,
                "unit": source.unit.unit_name,
                "plastic_material_number": source.material_number,
                "plastic_color": cls._raw_material_color(source),
            }
        )

    @classmethod
    def _set_packaging_source_snapshot(cls, line, source, existing_line=None):
        existing_values = existing_line.raw_values or {} if existing_line else {}
        if cls._same_source(existing_line, "source_packaging_material_id", source.pk):
            line.update(
                {
                    "category": existing_line.category,
                    "part_name": existing_line.part_name,
                    "material": existing_line.material,
                    "specification": existing_line.specification,
                    "raw_material": existing_line.raw_material,
                    "unit": existing_line.unit,
                    "packaging_material_number": existing_values.get("packaging_material_number", ""),
                    "packaging_color": existing_values.get("packaging_color", ""),
                }
            )
            return
        line.update(
            {
                "category": "包材",
                "part_name": source.material_name,
                "material": source.material,
                "specification": source.specification,
                "raw_material": source.material_number,
                "unit": source.unit.unit_name,
                "packaging_material_number": source.material_number,
                "packaging_color": cls._raw_material_color(source),
            }
        )

    @classmethod
    def _set_cutting_source_snapshot(cls, line, source, existing_line=None):
        existing_values = existing_line.raw_values or {} if existing_line else {}
        editable_snapshot = {
            field: line[field]
            for field in ("material", "specification", "unit")
            if field in line
        }
        if cls._same_source(existing_line, "source_cutting_material_id", source.pk):
            line.update(
                {
                    "category": existing_line.category,
                    "part_name": existing_line.part_name,
                    "material": existing_line.material,
                    "specification": existing_line.specification,
                    "raw_material": existing_line.raw_material,
                    "unit": existing_line.unit,
                    "cutting_material_number": existing_values.get("cutting_material_number", ""),
                    "cutting_item_type": existing_values.get("cutting_item_type") or source.item_type,
                    "cutting_item_type_display": (
                        existing_values.get("cutting_item_type_display") or source.get_item_type_display()
                    ),
                    "cutting_category": existing_values.get("cutting_category") or existing_line.category,
                    "cutting_color": existing_values.get("cutting_color") or cls._raw_material_color(source),
                }
            )
        else:
            line.update(
                {
                    "category": source.category.category_name,
                    "part_name": source.material_name,
                    "material": source.material,
                    "specification": source.specification,
                    "raw_material": source.material_number,
                    "unit": source.unit.unit_name,
                    "cutting_material_number": source.material_number,
                    "cutting_item_type": source.item_type,
                    "cutting_item_type_display": source.get_item_type_display(),
                    "cutting_category": source.category.category_name,
                    "cutting_color": cls._raw_material_color(source),
                }
            )
        line.update(editable_snapshot)

    @classmethod
    def _set_auxiliary_source_snapshot(
        cls,
        line,
        product_name,
        specification,
        color,
        material,
        existing_line=None,
    ):
        existing_values = existing_line.raw_values or {} if existing_line else {}
        same_product = cls._same_source(
            existing_line,
            "source_accessory_product_name_id",
            product_name.pk,
        )
        same_specification = cls._same_source(
            existing_line,
            "source_accessory_specification_id",
            specification.pk,
        )
        same_color = cls._same_source(
            existing_line,
            "source_accessory_color_id",
            color.pk,
        )
        same_material = cls._same_source(
            existing_line,
            "source_accessory_material_id",
            material.pk,
        )
        line.update(
            {
                "category": "辅料",
                "part_name": existing_line.part_name if same_product else product_name.product_name,
                "unit": (
                    existing_line.unit
                    if same_product and existing_line.unit.strip()
                    else product_name.unit_name
                ),
                "specification": (
                    existing_line.specification if same_specification else specification.specification_value
                ),
                "accessory_color": (
                    existing_values.get("accessory_color", "") if same_color else color.color_name
                ),
                "material": existing_line.material if same_material else material.material_name,
            }
        )

    @classmethod
    def _apply_fabric_source_snapshot(cls, line, existing_line, field, source):
        existing_values = existing_line.raw_values or {} if existing_line else {}
        same_source = cls._same_source(existing_line, field, source.pk) if source else False
        if field == "source_fabric_material_id":
            line["material"] = existing_line.material if same_source else (source.material_name if source else "")
        elif field == "source_fabric_specification_id":
            line["specification"] = (
                existing_line.specification if same_source else (source.specification_name if source else "")
            )
        elif field == "source_fabric_width_id":
            line["fabric_width"] = (
                existing_values.get("fabric_width", "") if same_source else (source.width_value if source else "")
            )
        elif field == "source_product_color_id":
            line.update(
                {
                    "fabric_color_card": (
                        existing_values.get("fabric_color_card", "") if same_source else (source.color_card if source else "")
                    ),
                    "fabric_color_code": (
                        existing_values.get("fabric_color_code", "") if same_source else (source.color_code if source else "")
                    ),
                    "fabric_color_name": (
                        existing_values.get("fabric_color_name", "") if same_source else (source.color_name if source else "")
                    ),
                }
            )

    @staticmethod
    def _restore_fabric_source_snapshot(line, existing_line, field):
        existing_values = existing_line.raw_values or {}
        if field == "source_fabric_material_id":
            line["material"] = existing_line.material
        elif field == "source_fabric_specification_id":
            line["specification"] = existing_line.specification
        elif field == "source_fabric_width_id":
            line["fabric_width"] = existing_values.get("fabric_width", "")
        elif field == "source_product_color_id":
            line.update(
                {
                    "fabric_color_card": existing_values.get("fabric_color_card", ""),
                    "fabric_color_code": existing_values.get("fabric_color_code", ""),
                    "fabric_color_name": existing_values.get("fabric_color_name", ""),
                }
            )

    def validate_sections(self, sections):
        bom = self.context.get("bom")
        sections = self._validate_fixed_sections(sections, bom)
        submitted_lines = {
            serializers.UUIDField().to_internal_value(line["id"]): line
            for section in self.initial_data.get("sections", [])
            for line in section["lines"]
            if line.get("id") is not None
        }
        section_ids = [item["id"] for item in sections if item.get("id")]
        if len(section_ids) != len(set(section_ids)):
            raise serializers.ValidationError("用料分区不能重复提交。")
        line_ids = [line["id"] for section in sections for line in section["lines"] if line.get("id")]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("用料明细不能重复提交。")
        if sum(len(section["lines"]) for section in sections) > 5000:
            raise serializers.ValidationError("单个 BOM 最多保存 5000 行用料明细。")

        used_draft_image_ids = set()
        for section in sections:
            for line_number, line in enumerate(section["lines"], start=1):
                draft_image_ids = line.get("draft_image_ids", [])
                if len(draft_image_ids) != len(set(draft_image_ids)):
                    raise serializers.ValidationError(
                        f"“{section['title']}”第 {line_number} 行包含重复的草稿图片。"
                    )
                if used_draft_image_ids.intersection(draft_image_ids):
                    raise serializers.ValidationError("同一张草稿图片不能绑定到多条用料明细。")
                used_draft_image_ids.update(draft_image_ids)

        existing_lines = {}
        if bom:
            existing_lines = {
                line.pk: line
                for section in bom.sections.prefetch_related("lines").all()
                for line in section.lines.all()
            }

        fabric_reference_line_ids = set()
        for section in sections:
            if section["title"].strip() != "面料类":
                continue
            for line in section["lines"]:
                existing_line = existing_lines.get(line.get("id"))
                previous = existing_line.raw_values or {} if existing_line else {}
                previous_inventory_id = previous.get("source_inventory_material_id")
                same_inventory_source = not previous_inventory_id or str(
                    line.get("source_inventory_material_id", previous_inventory_id)
                ) == str(previous_inventory_id)
                if existing_line and same_inventory_source and (
                    any(field in line and not line[field].strip() and getattr(existing_line, field).strip()
                        for field in ("material", "specification"))
                    or any(field in line and not line[field].strip() and str(previous.get(field) or "").strip()
                           for field in ("fabric_width", "fabric_color_card", "fabric_color_code", "fabric_color_name"))
                ):
                    # 历史行可能没有完整字典 ID；明确清空可见字段仍不能借旧库存来源确认。
                    line["fabric_source_sync_pending"] = True
                if (any(line.get(field) or previous.get(field) for field in FABRIC_REFERENCE_FIELDS)
                        or previous.get("fabric_source_sync_pending") or line.get("fabric_source_sync_pending")):
                    fabric_reference_line_ids.add(id(line))

        direct_rows = []
        direct_source_ids = set()
        for section in sections:
            for line_number, line in enumerate(section["lines"], start=1):
                existing_line = existing_lines.get(line.get("id"))
                if line.get("pending_raw_material"):
                    continue
                existing_source_id = self._raw_source_id(
                    existing_line,
                    "source_inventory_material_id",
                )
                if existing_source_id and "source_inventory_material_id" not in line:
                    line["source_inventory_material_id"] = UUID(existing_source_id)
                if existing_source_id and line.get("source_inventory_material_id") is None:
                    raise serializers.ValidationError(
                        f"“{section['title']}”第 {line_number} 行已关联库存原料，不能清空稳定原料 ID。"
                    )
                source_id = line.get("source_inventory_material_id")
                if source_id:
                    direct_source_ids.add(source_id)
                    direct_rows.append((section, line_number, line, existing_line))

        direct_sources = {
            source.pk: source
            for source in RawMaterialInformation.objects.filter(pk__in=direct_source_ids).select_related(
                "category",
                "unit",
                "color",
            )
        }
        if direct_source_ids - set(direct_sources):
            raise serializers.ValidationError("BOM 中包含不存在的稳定库存原料 ID。")

        direct_line_object_ids = set()
        expected_categories = {
            "管材类": "管材",
            "五金件": "五金",
            "塑料件类": "塑料件",
            "辅料类": "辅料",
            "面料类": "面料",
            "包材类": "包材",
        }
        for section, line_number, line, existing_line in direct_rows:
            source_id = line["source_inventory_material_id"]
            source = direct_sources[source_id]
            same_source = self._same_source(
                existing_line,
                "source_inventory_material_id",
                source_id,
            )
            if section["title"].strip() == "裁剪明细":
                source_valid = same_source or self._active_semi_finished(source)
            else:
                expected_category = expected_categories.get(section["title"].strip())
                source_valid = bool(
                    expected_category
                    and (
                        same_source
                        or self._active_raw_material(source, expected_category)
                    )
                )
            if not source_valid:
                raise serializers.ValidationError(
                    f"“{section['title']}”第 {line_number} 行的稳定库存原料类型或类别不匹配。"
                )
            pipe_values = {}
            if section["section_type"] == BomSectionType.PROFILE:
                # 保存服务按本次参数重新关联；旧来源快照不能覆盖用户刚修改的材质和规格。
                pipe_values = {field: line[field] for field in ("material", "specification") if field in line}
                previous_material = existing_line.material if same_source else source.material
                if "material" in pipe_values and pipe_values["material"].strip() != previous_material.strip():
                    line["pipe_source_sync_pending"] = True
            fabric_values = {
                field: line[field] for field in ("material", "specification")
                if id(line) in fabric_reference_line_ids and field in line
            }
            part_name = line.get("part_name", "")
            # 裁剪明细沿用已有编辑契约；稳定来源 ID 只固定来源，不覆盖裁片自填属性。
            cutting_values = {
                field: line[field]
                for field in ("material", "specification", "unit")
                if section["title"].strip() == "裁剪明细" and field in line
            }
            self._set_inventory_source_snapshot(line, source, existing_line)
            line.update(cutting_values)
            line.update(pipe_values)
            line.update(fabric_values)
            if section["title"].strip() in {"管材类", "面料类"} and part_name:
                line["part_name"] = part_name
            # 辅料字典仍可更改，不能让旧库存快照绕过当前字典校验与完整身份匹配。
            if not (section["title"].strip() == "辅料类" and any(
                line.get(field) for field in ("source_accessory_product_name_id", "source_accessory_specification_id",
                                             "source_accessory_color_id", "source_accessory_material_id")
            )):
                direct_line_object_ids.add(id(line))

        for section in sections:
            for line_number, line in enumerate(section["lines"], start=1):
                pending = line.get("pending_raw_material")
                if not pending:
                    continue
                source = RawMaterialInformation(**pending)
                title = section["title"].strip()
                valid = self._active_semi_finished(source) if title == "裁剪明细" else self._active_raw_material(
                    source, expected_categories.get(title),
                )
                if not valid:
                    raise serializers.ValidationError(f"“{title}”第 {line_number} 行的待新增原料类型或类别不匹配。")
                self._set_inventory_source_snapshot(line, source)
                snapshot = {"五金件": self._set_hardware_source_snapshot,
                            "塑料件类": self._set_plastic_source_snapshot,
                            "包材类": self._set_packaging_source_snapshot,
                            "裁剪明细": self._set_cutting_source_snapshot}.get(title)
                if snapshot:
                    snapshot(line, source)
                line["_pending_raw_source"] = source
                direct_line_object_ids.add(id(line))

        auxiliary_source_fields = (
            "source_accessory_product_name_id",
            "source_accessory_specification_id",
            "source_accessory_color_id",
            "source_accessory_material_id",
        )
        fabric_source_fields = (
            "source_fabric_material_id",
            "source_fabric_specification_id",
            "source_fabric_width_id",
            "source_product_color_id",
        )
        packaging_source_fields = (
            "source_packaging_material_id",
            "packaging_material_number",
            "packaging_color",
            "units_per_box",
        )
        cutting_source_fields = (
            "source_cutting_material_id",
            "cutting_material_number",
            "cutting_item_type",
            "cutting_item_type_display",
            "cutting_category",
            "cutting_color",
        )
        for section in sections:
            is_hardware_section = (
                section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "五金件"
            )
            is_plastic_section = (
                section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "塑料件类"
            )
            is_auxiliary_section = (
                section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "辅料类"
            )
            is_fabric_section = (
                section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "面料类"
            )
            is_packaging_section = (
                section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "包材类"
            )
            is_cutting_section = (
                section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "裁剪明细"
            )
            for line_number, line in enumerate(section["lines"], start=1):
                existing_line = existing_lines.get(line.get("id"))
                existing_values = existing_line.raw_values or {} if existing_line else {}
                existing_source_id = existing_values.get("source_raw_material_id")
                if (line.get("source_raw_material_id") or existing_source_id) and not (
                    is_hardware_section or is_plastic_section
                ):
                    raise serializers.ValidationError(
                        f"第 {line_number} 行的原料来源只能保存在“五金件”或“塑料件类”分区。"
                    )
                if any(line.get(field) or existing_values.get(field) for field in auxiliary_source_fields) and not is_auxiliary_section:
                    raise serializers.ValidationError(
                        f"第 {line_number} 行的辅料来源只能保存在“辅料类”分区。"
                    )
                if any(line.get(field) or existing_values.get(field) for field in fabric_source_fields) and not is_fabric_section:
                    raise serializers.ValidationError(
                        f"第 {line_number} 行的面料来源只能保存在“面料类”分区。"
                    )
                if any(line.get(field) or existing_values.get(field) for field in packaging_source_fields) and not is_packaging_section:
                    raise serializers.ValidationError(
                        f"第 {line_number} 行的包材来源只能保存在“包材类”分区。"
                    )
                if any(line.get(field) or existing_values.get(field) for field in cutting_source_fields) and not is_cutting_section:
                    raise serializers.ValidationError(
                        f"第 {line_number} 行的裁剪来源只能保存在“裁剪明细”分区。"
                    )

        hardware_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "五金件"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids
        ]
        for line_number, line in hardware_lines:
            existing_line = existing_lines.get(line.get("id"))
            existing_source_id = (
                (existing_line.raw_values or {}).get("source_raw_material_id") if existing_line else None
            )
            if existing_source_id and not line.get("source_raw_material_id"):
                raise serializers.ValidationError(
                    f"“五金件”第 {line_number} 行已关联原料数据，不能清空数据来源。"
                )
            if not line.get("id") and not line.get("source_raw_material_id"):
                raise serializers.ValidationError(
                    f"“五金件”第 {line_number} 行请先通过“选择数据”添加五金资料。"
                )

        source_ids = {line["source_raw_material_id"] for _, line in hardware_lines if line.get("source_raw_material_id")}
        source_materials = {}
        if source_ids:
            source_materials = {
                source.pk: source
                for source in RawMaterialInformation.objects.filter(
                    pk__in=source_ids,
                    item_type=ProductItemType.MATERIAL,
                    category__category_name="五金",
                ).select_related("category", "unit", "color")
            }
            if source_ids - set(source_materials):
                raise serializers.ValidationError("五金件中包含无效或非五金类别的原料数据。")

        for line_number, line in hardware_lines:
            source_id = line.get("source_raw_material_id")
            if source_id:
                existing_line = existing_lines.get(line.get("id"))
                source = source_materials[source_id]
                if not self._same_source(existing_line, "source_raw_material_id", source_id) and not self._active_raw_material(
                    source,
                    "五金",
                ):
                    raise serializers.ValidationError(
                        f"“五金件”第 {line_number} 行包含已停用、已归档或非五金类别的原料数据。"
                    )
                self._set_hardware_source_snapshot(
                    line,
                    source,
                    existing_line,
                )
            flow_unit = str(line.get("hardware_flow_unit", "")).strip().upper()
            weight = str(line.get("unit_material_weight_kg", "")).strip()
            if flow_unit == "KG" and (not weight or Decimal(weight) <= 0):
                raise serializers.ValidationError(
                    f"“五金件”第 {line_number} 行按重量流转，请填写大于 0 的单个材料重量（kg）。"
                )

        plastic_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "塑料件类"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids
        ]
        for line_number, line in plastic_lines:
            existing_line = existing_lines.get(line.get("id"))
            existing_source_id = self._raw_source_id(existing_line, "source_raw_material_id")
            if existing_source_id and not line.get("source_raw_material_id"):
                raise serializers.ValidationError(
                    f"“塑料件类”第 {line_number} 行已关联原料数据，不能清空数据来源。"
                )
            if not line.get("id") and not line.get("source_raw_material_id"):
                raise serializers.ValidationError(
                    f"“塑料件类”第 {line_number} 行请先通过“选择数据”添加塑料件资料。"
                )

        plastic_source_ids = {
            line["source_raw_material_id"]
            for _, line in plastic_lines
            if line.get("source_raw_material_id")
        }
        plastic_sources = {
            source.pk: source
            for source in RawMaterialInformation.objects.filter(pk__in=plastic_source_ids).select_related(
                "category",
                "unit",
                "color",
            )
        }
        if plastic_source_ids - set(plastic_sources):
            raise serializers.ValidationError("塑料件类中包含不存在的原料数据。")
        for line_number, line in plastic_lines:
            source_id = line.get("source_raw_material_id")
            if not source_id:
                continue
            existing_line = existing_lines.get(line.get("id"))
            source = plastic_sources[source_id]
            if not self._same_source(existing_line, "source_raw_material_id", source_id) and not self._active_raw_material(
                source,
                "塑料件",
            ):
                raise serializers.ValidationError(
                    f"“塑料件类”第 {line_number} 行包含已停用、已归档或非塑料件类别的原料数据。"
                )
            self._set_plastic_source_snapshot(line, source, existing_line)

        packaging_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.ACCESSORY and section["title"].strip() == "包材类"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids
        ]
        packaging_source_ids = {
            line["source_packaging_material_id"]
            for _, line in packaging_lines
            if line.get("source_packaging_material_id")
        }
        packaging_sources = {
            source.pk: source
            for source in RawMaterialInformation.objects.filter(pk__in=packaging_source_ids).select_related(
                "category",
                "unit",
                "color",
            )
        }
        if packaging_source_ids - set(packaging_sources):
            raise serializers.ValidationError("包材类中包含不存在的原料数据。")
        for line_number, line in packaging_lines:
            existing_line = existing_lines.get(line.get("id"))
            existing_source_id = self._raw_source_id(existing_line, "source_packaging_material_id")
            source_id = line.get("source_packaging_material_id")
            if existing_source_id and not source_id:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行已关联原料数据，不能清空数据来源。"
                )
            if not line.get("id") and not source_id:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行请先通过“选择数据”添加包材资料。"
                )
            units_per_box = str(line.get("units_per_box", "")).strip()
            unit_consumption = str(line.get("unit_consumption", "")).strip()
            if not units_per_box:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行请填写箱数（多少一箱）。"
                )
            if not unit_consumption:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行请填写单个用量。"
                )
            try:
                parsed_consumption = Decimal(unit_consumption)
            except (InvalidOperation, ValueError) as exc:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行的单个用量必须是有效数字。"
                ) from exc
            if not parsed_consumption.is_finite() or parsed_consumption <= 0:
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行的单个用量必须大于 0。"
                )
            if not source_id:
                continue
            source = packaging_sources[source_id]
            if not self._same_source(existing_line, "source_packaging_material_id", source_id) and not self._active_raw_material(
                source,
                "包材",
            ):
                raise serializers.ValidationError(
                    f"“包材类”第 {line_number} 行包含已停用、已归档或非包材类别的原料数据。"
                )
            self._set_packaging_source_snapshot(line, source, existing_line)

        cutting_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "裁剪明细"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids
        ]
        cutting_source_ids = {
            line["source_cutting_material_id"]
            for _, line in cutting_lines
            if line.get("source_cutting_material_id")
        }
        cutting_sources = {
            source.pk: source
            for source in RawMaterialInformation.objects.filter(pk__in=cutting_source_ids).select_related(
                "category",
                "unit",
                "color",
            )
        }
        if cutting_source_ids - set(cutting_sources):
            raise serializers.ValidationError("裁剪明细中包含不存在的半成品数据。")
        for line_number, line in cutting_lines:
            existing_line = existing_lines.get(line.get("id"))
            existing_source_id = self._raw_source_id(existing_line, "source_cutting_material_id")
            source_id = line.get("source_cutting_material_id")
            if existing_source_id and not source_id:
                raise serializers.ValidationError(
                    f"“裁剪明细”第 {line_number} 行已关联半成品数据，不能清空数据来源。"
                )
            if not line.get("id") and not source_id:
                raise serializers.ValidationError(
                    f"“裁剪明细”第 {line_number} 行请先通过“选择数据”添加半成品资料。"
                )
            if not source_id:
                continue
            source = cutting_sources[source_id]
            if not self._same_source(existing_line, "source_cutting_material_id", source_id) and not self._active_semi_finished(
                source
            ):
                raise serializers.ValidationError(
                    f"“裁剪明细”第 {line_number} 行包含已停用、已归档或非半成品类型的原料数据。"
                )
            self._set_cutting_source_snapshot(line, source, existing_line)

        auxiliary_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "辅料类"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids
        ]
        sourced_auxiliary_lines = []
        for line_number, line in auxiliary_lines:
            existing_line = existing_lines.get(line.get("id"))
            existing_product_id = self._raw_source_id(existing_line, "source_accessory_product_name_id")
            product_id = line.get("source_accessory_product_name_id")
            child_ids = [line.get(field) for field in auxiliary_source_fields[1:]]
            if existing_product_id and not product_id:
                raise serializers.ValidationError(
                    f"“辅料类”第 {line_number} 行已关联辅料品名，不能清空数据来源。"
                )
            if not line.get("id") and not product_id:
                raise serializers.ValidationError(
                    f"“辅料类”第 {line_number} 行请先通过“选择数据”添加辅料品名。"
                )
            if not product_id:
                if any(child_ids):
                    raise serializers.ValidationError(
                        f"“辅料类”第 {line_number} 行必须先选择辅料品名。"
                    )
                continue
            missing_labels = [
                label
                for field, label in zip(auxiliary_source_fields[1:], ("规格", "颜色", "材质"))
                if not line.get(field)
            ]
            if missing_labels:
                raise serializers.ValidationError(
                    f"“辅料类”第 {line_number} 行请选择{'、'.join(missing_labels)}。"
                )
            sourced_auxiliary_lines.append((line_number, line, existing_line))

        auxiliary_product_ids = {
            line["source_accessory_product_name_id"] for _, line, _ in sourced_auxiliary_lines
        }
        auxiliary_specification_ids = {
            line["source_accessory_specification_id"] for _, line, _ in sourced_auxiliary_lines
        }
        auxiliary_color_ids = {
            line["source_accessory_color_id"] for _, line, _ in sourced_auxiliary_lines
        }
        auxiliary_material_ids = {
            line["source_accessory_material_id"] for _, line, _ in sourced_auxiliary_lines
        }
        auxiliary_products = {
            item.pk: item for item in AccessoryProductName.objects.filter(pk__in=auxiliary_product_ids)
        }
        auxiliary_specifications = {
            item.pk: item
            for item in AccessorySpecification.objects.filter(pk__in=auxiliary_specification_ids).select_related(
                "product_name"
            )
        }
        auxiliary_colors = {
            item.pk: item
            for item in AccessoryColor.objects.filter(pk__in=auxiliary_color_ids).select_related("product_name")
        }
        auxiliary_materials = {
            item.pk: item for item in AccessoryMaterial.objects.filter(pk__in=auxiliary_material_ids)
        }
        if (
            auxiliary_product_ids - set(auxiliary_products)
            or auxiliary_specification_ids - set(auxiliary_specifications)
            or auxiliary_color_ids - set(auxiliary_colors)
            or auxiliary_material_ids - set(auxiliary_materials)
        ):
            raise serializers.ValidationError("辅料类中包含不存在的品名、规格、颜色或材质数据。")

        for line_number, line, existing_line in sourced_auxiliary_lines:
            product = auxiliary_products[line["source_accessory_product_name_id"]]
            specification = auxiliary_specifications[line["source_accessory_specification_id"]]
            color = auxiliary_colors[line["source_accessory_color_id"]]
            material = auxiliary_materials[line["source_accessory_material_id"]]
            if specification.product_name_id != product.pk:
                raise serializers.ValidationError(
                    f"“辅料类”第 {line_number} 行所选规格不属于当前辅料品名。"
                )
            if color.product_name_id != product.pk:
                raise serializers.ValidationError(
                    f"“辅料类”第 {line_number} 行所选颜色不属于当前辅料品名。"
                )
            references = (
                ("source_accessory_product_name_id", product, "品名"),
                ("source_accessory_specification_id", specification, "规格"),
                ("source_accessory_color_id", color, "颜色"),
                ("source_accessory_material_id", material, "材质"),
            )
            for field, source, label in references:
                if not self._same_source(existing_line, field, source.pk) and not self._active_reference(source):
                    raise serializers.ValidationError(
                        f"“辅料类”第 {line_number} 行所选{label}已停用或归档。"
                    )
            self._set_auxiliary_source_snapshot(
                line,
                product,
                specification,
                color,
                material,
                existing_line,
            )

        fabric_lines = [
            (index, line)
            for section in sections
            if section["section_type"] == BomSectionType.FABRIC and section["title"].strip() == "面料类"
            for index, line in enumerate(section["lines"], start=1)
            if id(line) not in direct_line_object_ids or id(line) in fabric_reference_line_ids
        ]
        fabric_models = {
            "source_fabric_material_id": FabricMaterial,
            "source_fabric_specification_id": FabricSpecification,
            "source_fabric_width_id": FabricWidth,
            "source_product_color_id": ProductColor,
        }
        fabric_sources = {}
        for field, model in fabric_models.items():
            ids = {line[field] for _, line in fabric_lines if line.get(field)}
            items = {item.pk: item for item in model.objects.filter(pk__in=ids)}
            if ids - set(items):
                raise serializers.ValidationError(f"面料类中包含不存在的{field}数据。")
            fabric_sources[field] = items

        for line_number, line in fabric_lines:
            existing_line = existing_lines.get(line.get("id"))
            line["unit"] = "米"
            for field in fabric_source_fields:
                if field not in line:
                    if existing_line and self._raw_source_id(existing_line, field):
                        # 字段省略表示沿用已保存来源，并恢复历史快照；只有显式 null 才表示清空。
                        self._restore_fabric_source_snapshot(line, existing_line, field)
                    continue
                source_id = line.get(field)
                source = fabric_sources[field].get(source_id) if source_id else None
                if source and not self._same_source(existing_line, field, source_id) and not self._active_reference(source):
                    raise serializers.ValidationError(
                        f"“面料类”第 {line_number} 行所选生产维护数据已停用或归档。"
                    )
                if source or self._raw_source_id(existing_line, field):
                    self._apply_fabric_source_snapshot(line, existing_line, field, source)

        for section in sections:
            if section["title"].strip() != "裁剪明细":
                continue
            for line in section["lines"]:
                existing_line = existing_lines.get(line.get("id"))
                existing_values = existing_line.raw_values or {} if existing_line else {}
                if "cutting_material_original" not in existing_values:
                    continue
                source_id = line.get("source_inventory_material_id") or line.get("source_cutting_material_id")
                existing_source_id = existing_values.get("source_inventory_material_id") or existing_values.get("source_cutting_material_id")
                submitted_line = submitted_lines.get(existing_line.pk, {})
                material_omitted = "material" not in submitted_line
                unchanged_response = (
                    "cutting_material_original" in submitted_line
                    and line.get("material", existing_line.material) == existing_line.material
                )
                if str(source_id or "") == str(existing_source_id or "") and (material_omitted or unchanged_response):
                    # 完整响应回传或省略材质时，旧的面料补充值不应变成裁片自己的材质。
                    line["material"] = existing_values["cutting_material_original"]
        return sections


class BomMaterialSaveLocationSerializer(serializers.Serializer):
    section_title = serializers.CharField()
    line_number = serializers.IntegerField()


class BomNewMaterialPreviewSerializer(serializers.Serializer):
    key = serializers.CharField()
    item_type = serializers.ChoiceField(choices=("MATERIAL", "SEMI_FINISHED"))
    category_name = serializers.CharField()
    material_name = serializers.CharField()
    specification = serializers.CharField()
    color_name = serializers.CharField(allow_blank=True)
    color_label = serializers.CharField(allow_blank=True)
    width = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)
    unit_name = serializers.CharField()
    warehouse_name = serializers.CharField()
    locations = BomMaterialSaveLocationSerializer(many=True)


class BomMaterialSavePreviewDataSerializer(serializers.Serializer):
    confirmation_token = serializers.CharField(allow_null=True)
    new_materials = BomNewMaterialPreviewSerializer(many=True)


class BomMaterialSavePreviewResponseSerializer(serializers.Serializer):
    data = BomMaterialSavePreviewDataSerializer()


class BomVerifyInputSerializer(serializers.Serializer):
    quantity_confirmation_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        trim_whitespace=True,
    )
