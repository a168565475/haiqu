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


class ProductFieldsSerializer(StrictSerializer):
    product_code = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)
    item_number = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)
    specification = serializers.CharField(max_length=300, allow_blank=True, trim_whitespace=False, required=False)
    unit = serializers.CharField(max_length=80, allow_blank=True, trim_whitespace=False, required=False)
    scale = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=False, required=False)


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


class ProductDetailResponseSerializer(serializers.Serializer):
    data = ProductDetailSerializer()


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
