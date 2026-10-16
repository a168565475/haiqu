from rest_framework import serializers

from apps.products.models import ProductInformation, RawMaterialInformation
from apps.reference_data.models import ProductItemType, ReferenceStatus


class ProductCategoryOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category_name = serializers.CharField()


class ProductionUnitOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    unit_code = serializers.CharField()
    unit_name = serializers.CharField()


class ProductItemOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    item_number = serializers.CharField()
    category_id = serializers.UUIDField()
    category_name = serializers.CharField()


class ProductOptionsDataSerializer(serializers.Serializer):
    categories = ProductCategoryOptionSerializer(many=True)
    units = ProductionUnitOptionSerializer(many=True)
    items = ProductItemOptionSerializer(many=True)


class ProductOptionsResponseSerializer(serializers.Serializer):
    data = ProductOptionsDataSerializer()


class ProductSelectionProductSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    product_number = serializers.CharField()
    product_code = serializers.CharField()
    item_number = serializers.CharField()
    product_name = serializers.CharField()
    specification = serializers.CharField()
    unit_id = serializers.UUIDField()
    unit_code = serializers.CharField()
    unit_name = serializers.CharField()
    category_id = serializers.UUIDField()
    category_name = serializers.CharField()


class ProductSelectionSpecificationSerializer(serializers.Serializer):
    specification = serializers.CharField()
    products = ProductSelectionProductSerializer(many=True)


class ProductSelectionGroupSerializer(serializers.Serializer):
    product_name = serializers.CharField()
    specifications = ProductSelectionSpecificationSerializer(many=True)


class ProductSelectionCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category_name = serializers.CharField()


class ProductSelectionDataSerializer(serializers.Serializer):
    category = ProductSelectionCategorySerializer()
    groups = ProductSelectionGroupSerializer(many=True)


class ProductSelectionResponseSerializer(serializers.Serializer):
    data = ProductSelectionDataSerializer()


class RawMaterialValueOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class RawMaterialCategoryOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    item_type = serializers.CharField()
    category_name = serializers.CharField()


class RawMaterialColorOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    color_card = serializers.CharField()
    color_code = serializers.CharField()
    color_name = serializers.CharField()
    label = serializers.CharField()


class RawMaterialWarehouseOptionSerializer(serializers.Serializer):
    warehouse_number = serializers.CharField()
    warehouse_name = serializers.CharField()


class RawMaterialOptionsDataSerializer(serializers.Serializer):
    item_types = RawMaterialValueOptionSerializer(many=True)
    categories = RawMaterialCategoryOptionSerializer(many=True)
    units = ProductionUnitOptionSerializer(many=True)
    colors = RawMaterialColorOptionSerializer(many=True)
    warehouses = RawMaterialWarehouseOptionSerializer(many=True)
    box_shapes = RawMaterialValueOptionSerializer(many=True)


class RawMaterialOptionsResponseSerializer(serializers.Serializer):
    data = RawMaterialOptionsDataSerializer()


class ProductInformationSerializer(serializers.ModelSerializer):
    product_type_label = serializers.CharField(source="get_product_type_display", read_only=True)
    category_name = serializers.CharField(source="category.category_name", read_only=True)
    unit_code = serializers.CharField(source="unit.unit_code", read_only=True)
    unit_name = serializers.CharField(source="unit.unit_name", read_only=True)
    item_number = serializers.CharField(source="product_item.item_number", read_only=True)
    item_category_id = serializers.UUIDField(source="product_item.category_id", read_only=True)
    item_category_name = serializers.CharField(source="product_item.category.category_name", read_only=True)
    category_item_mismatch = serializers.SerializerMethodField()

    class Meta:
        model = ProductInformation
        fields = [
            "id",
            "product_number",
            "product_type",
            "product_type_label",
            "product_code",
            "category",
            "category_name",
            "product_name",
            "specification",
            "unit",
            "unit_code",
            "unit_name",
            "product_item",
            "item_number",
            "item_category_id",
            "item_category_name",
            "category_item_mismatch",
            "warehouse_number",
            "warehouse_name",
            "scale",
            "status",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = [
            "id",
            "product_type",
            "product_type_label",
            "category_name",
            "unit_code",
            "unit_name",
            "item_number",
            "item_category_id",
            "item_category_name",
            "category_item_mismatch",
            "created_at",
            "updated_at",
            "archived_at",
        ]

    def get_category_item_mismatch(self, instance) -> bool:
        return instance.category_id != instance.product_item.category_id

    def _relation_changed(self, field_name, value) -> bool:
        if self.instance is None:
            return True
        return getattr(self.instance, f"{field_name}_id") != value.pk

    def validate_category(self, value):
        if value.item_type != ProductItemType.FINISHED:
            raise serializers.ValidationError("产品类别必须是成品类别。")
        if self._relation_changed("category", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("产品类别已停用或归档。")
        return value

    def validate_unit(self, value):
        if self._relation_changed("unit", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("生产单位已停用或归档。")
        return value

    def validate_product_item(self, value):
        if self._relation_changed("product_item", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("货号已停用或归档。")
        return value

    def validate_product_code(self, value):
        normalized = value.strip()
        if not normalized:
            return ""
        queryset = ProductInformation.objects.filter(product_code=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("产品编码已存在。")
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        category = attrs.get("category", getattr(self.instance, "category", None))
        product_item = attrs.get("product_item", getattr(self.instance, "product_item", None))
        if category is None or product_item is None:
            return attrs

        relationship_changed = self.instance is None or (
            category.pk != self.instance.category_id
            or product_item.pk != self.instance.product_item_id
        )
        if relationship_changed and product_item.category_id != category.pk:
            raise serializers.ValidationError({"product_item": "货号必须属于所选产品类别。"})
        return attrs


class RawMaterialInformationSerializer(serializers.ModelSerializer):
    item_type_label = serializers.CharField(source="get_item_type_display", read_only=True)
    category_name = serializers.CharField(source="category.category_name", read_only=True)
    unit_code = serializers.CharField(source="unit.unit_code", read_only=True)
    unit_name = serializers.CharField(source="unit.unit_name", read_only=True)
    color_name = serializers.SerializerMethodField()
    color_label = serializers.SerializerMethodField()
    has_legacy_color = serializers.SerializerMethodField()

    class Meta:
        model = RawMaterialInformation
        fields = [
            "id",
            "material_number",
            "item_type",
            "item_type_label",
            "category",
            "category_name",
            "material_name",
            "specification",
            "unit",
            "unit_code",
            "unit_name",
            "color",
            "color_name",
            "color_label",
            "has_legacy_color",
            "material",
            "is_packaging_auxiliary",
            "box_shape",
            "notes",
            "warehouse_number",
            "warehouse_name",
            "diameter",
            "length",
            "width",
            "thickness",
            "model_number",
            "weight_kg",
            "flow_unit",
            "number_value",
            "source_unique_check",
            "source_row_number",
            "created_at",
            "updated_at",
            "archived_at",
        ]
        read_only_fields = [
            "id",
            "item_type_label",
            "category_name",
            "unit_code",
            "unit_name",
            "color_name",
            "color_label",
            "has_legacy_color",
            "diameter",
            "length",
            "width",
            "thickness",
            "model_number",
            "weight_kg",
            "flow_unit",
            "number_value",
            "source_unique_check",
            "source_row_number",
            "created_at",
            "updated_at",
            "archived_at",
        ]

    def get_color_name(self, instance) -> str:
        return instance.color.color_name if instance.color_id else instance.color_snapshot

    def get_color_label(self, instance) -> str:
        if not instance.color_id:
            return instance.color_snapshot
        parts = [
            instance.color.color_card,
            instance.color.color_code,
            instance.color.color_name,
        ]
        return " / ".join(part for part in parts if part)

    def get_has_legacy_color(self, instance) -> bool:
        return bool(instance.color_snapshot and not instance.color_id)

    def _relation_changed(self, field_name, value) -> bool:
        if self.instance is None:
            return True
        return getattr(self.instance, f"{field_name}_id") != (value.pk if value else None)

    def validate_material_number(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请输入品号。")
        if self.instance is not None and normalized == self.instance.material_number:
            return normalized
        if RawMaterialInformation.objects.filter(material_number=normalized).exists():
            raise serializers.ValidationError("品号已存在。")
        return normalized

    def validate_item_type(self, value):
        if value not in {ProductItemType.MATERIAL, ProductItemType.SEMI_FINISHED}:
            raise serializers.ValidationError("原料类型只允许材料或半成品。")
        return value

    def validate_category(self, value):
        if self._relation_changed("category", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("原料类别已停用或归档。")
        return value

    def validate_unit(self, value):
        if self._relation_changed("unit", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("生产单位已停用或归档。")
        return value

    def validate_color(self, value):
        if value is not None and self._relation_changed("color", value) and (
            value.status != ReferenceStatus.ACTIVE or value.archived_at is not None
        ):
            raise serializers.ValidationError("产品颜色已停用或归档。")
        return value

    def validate_material_name(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请输入品名。")
        return normalized

    def validate_specification(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请输入规格。")
        return normalized

    def validate_warehouse_number(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请选择仓库名称。")
        return normalized

    def validate_warehouse_name(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请选择仓库名称。")
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        item_type = attrs.get("item_type", getattr(self.instance, "item_type", None))
        category = attrs.get("category", getattr(self.instance, "category", None))
        if category is not None and category.item_type != item_type:
            raise serializers.ValidationError({"category": "原料类别必须与所选类型一致。"})

        warehouse_number = attrs.get(
            "warehouse_number",
            getattr(self.instance, "warehouse_number", ""),
        )
        warehouse_name = attrs.get(
            "warehouse_name",
            getattr(self.instance, "warehouse_name", ""),
        )
        allowed_warehouses = RawMaterialInformation.objects.exclude(
            warehouse_number="",
        ).exclude(
            warehouse_name="",
        ).values_list("warehouse_number", "warehouse_name").distinct()
        if (warehouse_number, warehouse_name) not in set(allowed_warehouses):
            raise serializers.ValidationError({"warehouse_name": "请选择附件中已有的仓库。"})

        is_packaging = bool(
            item_type == ProductItemType.MATERIAL
            and category is not None
            and category.category_name == "包材"
        )
        is_auxiliary = attrs.get(
            "is_packaging_auxiliary",
            getattr(self.instance, "is_packaging_auxiliary", False),
        )
        box_shape = attrs.get("box_shape", getattr(self.instance, "box_shape", ""))
        if not is_packaging and is_auxiliary:
            raise serializers.ValidationError(
                {"is_packaging_auxiliary": "只有包材类别可以设置包材辅料。"}
            )
        if not is_packaging and box_shape:
            raise serializers.ValidationError({"box_shape": "只有包材类别可以设置箱子形状。"})

        if "color" in attrs:
            color = attrs["color"]
            attrs["color_snapshot"] = color.color_name if color else ""
        return attrs
