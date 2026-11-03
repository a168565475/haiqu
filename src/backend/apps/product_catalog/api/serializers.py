from collections.abc import Mapping

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "不支持此字段。" for key in sorted(unknown)})
        return super().to_internal_value(data)


class ProductOptionListField(serializers.ListField):
    def to_internal_value(self, data):
        if not isinstance(data, list) or any(not isinstance(value, str) for value in data):
            raise serializers.ValidationError("选项必须是文字列表。")
        values = super().to_internal_value(data)
        if len(set(values)) != len(values):
            raise serializers.ValidationError("同一产品的选项不能重复。")
        return values


class ProductFieldsSerializer(StrictSerializer):
    product_code = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)
    item_number = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)
    specification = serializers.CharField(max_length=300, allow_blank=True, trim_whitespace=False, required=False)
    unit = serializers.CharField(max_length=80, allow_blank=True, trim_whitespace=False, required=False)
    scale = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)
    materials = ProductOptionListField(child=serializers.CharField(max_length=200), max_length=500, required=False)
    thicknesses = ProductOptionListField(child=serializers.CharField(max_length=80), max_length=500, required=False)


class ProductEntryDraftSerializer(StrictSerializer):
    category_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    category_name = serializers.CharField(max_length=150)
    name_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    name = serializers.CharField(max_length=200)
    item_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    specification = serializers.CharField(max_length=300, allow_blank=True)
    product_code = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    unit_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    unit_name = serializers.CharField(max_length=80, allow_blank=True)
    color_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    color_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    material = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    sources = serializers.DictField(child=serializers.ChoiceField(choices=("selected", "typed")))

    def validate_sources(self, values):
        fields = {"category_name", "name", "item_number", "specification", "product_code", "unit_name", "color_name", "material"}
        if set(values) != fields:
            raise serializers.ValidationError("必须逐项记录类别、品名、货号、规格、编码、单位、颜色和材质的填写来源。")
        return values


class ProductSelectionSerializer(StrictSerializer):
    catalog_version = serializers.CharField(max_length=80, required=False, allow_blank=True)
    color_id = serializers.UUIDField(required=False, allow_null=True)
    material = serializers.CharField(max_length=200, required=False, allow_blank=True)
    thickness = serializers.CharField(max_length=80, required=False, allow_blank=True)
    draft = ProductEntryDraftSerializer(required=False)

    def validate(self, attrs):
        if "draft" not in attrs and not attrs.get("catalog_version"):
            raise serializers.ValidationError({"catalog_version": "请选择产品版本。"})
        return attrs

    def validate_catalog_version(self, value):
        from django.utils.dateparse import parse_datetime

        if not value:
            return value
        try:
            parsed = parse_datetime(value)
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None:
            raise serializers.ValidationError("产品版本必须是包含时区的时间字符串。")
        return value


class ProductCreateSerializer(ProductFieldsSerializer):
    name_id = serializers.UUIDField()


class ProductPatchSerializer(ProductFieldsSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("至少提交一个待保存字段。")
        return attrs


class NameCreateSerializer(StrictSerializer):
    category_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200, trim_whitespace=False)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("完整品名不能为空。")
        return value


class NamePatchSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, trim_whitespace=False)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("完整品名不能为空。")
        return value


class ColorCreateSerializer(StrictSerializer):
    value = serializers.CharField(max_length=200)


class EditorProductSerializer(ProductFieldsSerializer):
    id = serializers.UUIDField(required=False)
    colors = ProductOptionListField(child=serializers.CharField(max_length=200), max_length=500, required=False)


class EditorSaveSerializer(NamePatchSerializer):
    products = EditorProductSerializer(many=True, required=False, default=list)
    delete_product_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)

    def validate(self, attrs):
        ids = [row["id"] for row in attrs["products"] if "id" in row]
        deleted = attrs["delete_product_ids"]
        if len(ids) != len(set(ids)) or len(deleted) != len(set(deleted)):
            raise serializers.ValidationError("同一产品不能重复提交。")
        if set(ids) & set(deleted):
            raise serializers.ValidationError("同一产品不能同时修改和删除。")
        return attrs


class EditorCreateSerializer(NameCreateSerializer):
    products = EditorProductSerializer(many=True, required=False, default=list)

    def validate_products(self, values):
        if any("id" in row for row in values):
            raise serializers.ValidationError("新增品名不能携带已有产品。")
        return values


class NameListQuerySerializer(serializers.Serializer):
    category_id = serializers.UUIDField(required=False)
    q = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ProductListQuerySerializer(NameListQuerySerializer):
    name_id = serializers.UUIDField(required=False)


@extend_schema_serializer(component_name="ProductCatalogCategory")
class CategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    name_count = serializers.IntegerField(min_value=0, read_only=True)


@extend_schema_serializer(component_name="ProductCatalogOptions")
class CatalogOptionsSerializer(serializers.Serializer):
    categories = CategorySerializer(many=True)
    units = serializers.ListField(child=serializers.CharField())
    scales = serializers.ListField(child=serializers.CharField())


@extend_schema_serializer(component_name="ProductCatalogOptionsResponse")
class CatalogOptionsResponseSerializer(serializers.Serializer):
    data = CatalogOptionsSerializer()


class NameDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category_id = serializers.UUIDField()
    category_name = serializers.CharField()
    name = serializers.CharField()
    product_count = serializers.IntegerField()
    updated_at = serializers.DateTimeField()


class NameDetailResponseSerializer(serializers.Serializer):
    data = NameDetailSerializer()


@extend_schema_serializer(many=False)
class NameListResponseSerializer(serializers.Serializer):
    data = NameDetailSerializer(many=True)


class ColorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    value = serializers.CharField()


class ProductSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name_id = serializers.UUIDField()
    name = serializers.CharField()
    category_id = serializers.UUIDField()
    category_name = serializers.CharField()
    product_code = serializers.CharField(allow_blank=True)
    item_number = serializers.CharField(allow_blank=True)
    specification = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    scale = serializers.CharField(allow_blank=True)
    colors = ColorSerializer(many=True)
    materials = serializers.ListField(child=serializers.CharField())
    thicknesses = serializers.ListField(child=serializers.CharField())
    updated_at = serializers.DateTimeField()


class ProductSourceSerializer(serializers.Serializer):
    filename = serializers.CharField()
    sha256 = serializers.CharField()
    sheet = serializers.CharField()
    row = serializers.IntegerField()
    raw_fields = serializers.JSONField()


class ProductDetailSerializer(ProductSummarySerializer):
    created_at = serializers.DateTimeField()
    source = ProductSourceSerializer(allow_null=True)


class ProductSelectionOptionSerializer(ProductSummarySerializer):
    catalog_version = serializers.CharField()
    unit_id = serializers.UUIDField(allow_null=True)
    unit_code = serializers.CharField(allow_blank=True)


class ProductSelectionNameSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category_id = serializers.UUIDField()
    name = serializers.CharField()


class ProductSelectionCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ProductSelectionUnitSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    unit_name = serializers.CharField()
    unit_code = serializers.CharField()


class ProductSelectionOptionsSerializer(serializers.Serializer):
    categories = ProductSelectionCategorySerializer(many=True)
    names = ProductSelectionNameSerializer(many=True)
    products = ProductSelectionOptionSerializer(many=True)
    units = ProductSelectionUnitSerializer(many=True)


class ProductSelectionOptionsResponseSerializer(serializers.Serializer):
    data = ProductSelectionOptionsSerializer()


class ProductDetailResponseSerializer(serializers.Serializer):
    data = ProductDetailSerializer()


class EditorDetailSerializer(serializers.Serializer):
    name = NameDetailSerializer()
    products = ProductSummarySerializer(many=True)


class EditorResponseSerializer(serializers.Serializer):
    data = EditorDetailSerializer()


class PageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


@extend_schema_serializer(many=False)
class ProductListResponseSerializer(serializers.Serializer):
    data = ProductSummarySerializer(many=True)
    meta = PageMetaSerializer()


@extend_schema_serializer(component_name="ProductCatalogError")
class CatalogErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    field_errors = serializers.JSONField()
    request_id = serializers.CharField(allow_null=True)


@extend_schema_serializer(component_name="ProductCatalogErrorResponse")
class CatalogErrorResponseSerializer(serializers.Serializer):
    error = CatalogErrorSerializer()
