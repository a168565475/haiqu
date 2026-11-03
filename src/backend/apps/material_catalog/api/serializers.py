from collections.abc import Mapping

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..definitions import CATEGORY_CHOICES, CATEGORY_TEMPLATES, TEMPLATE_CHOICES
from ..models import MaterialScope


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "不支持此字段。" for key in sorted(unknown)})
        return super().to_internal_value(data)


class OrdinaryColorInputSerializer(StrictSerializer):
    product_color_id = serializers.UUIDField(required=False, allow_null=True)
    color_card = serializers.CharField(max_length=100, required=False, allow_blank=True)
    color_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    color_name = serializers.CharField(max_length=200, required=False)


class CatalogDraftValueSerializer(OrdinaryColorInputSerializer):
    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    field_key = serializers.CharField(max_length=40)
    value = serializers.CharField(max_length=300, trim_whitespace=True)
    parent_id = serializers.UUIDField(allow_null=True)


class CatalogDraftUnitSerializer(StrictSerializer):
    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    unit_name = serializers.CharField(max_length=80, trim_whitespace=True)


class CatalogSaveSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, trim_whitespace=True)
    spray_enabled = serializers.BooleanField()
    base_warehouse_id = serializers.UUIDField(allow_null=True)
    semi_warehouse_id = serializers.UUIDField(allow_null=True)
    values = CatalogDraftValueSerializer(many=True)
    units = CatalogDraftUnitSerializer(many=True)

    def validate_spray_enabled(self, value):
        if not isinstance(self.initial_data["spray_enabled"], bool):
            raise serializers.ValidationError("喷塑开关必须为布尔值。")
        return value


class CatalogCreateSerializer(CatalogSaveSerializer):
    name = serializers.CharField(max_length=200, trim_whitespace=True)
    category_key = serializers.ChoiceField(choices=CATEGORY_CHOICES)
    template_key = serializers.ChoiceField(choices=TEMPLATE_CHOICES)
    spray_enabled = serializers.BooleanField(required=False, default=False)
    base_warehouse_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    semi_warehouse_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    values = CatalogDraftValueSerializer(many=True, required=False)
    units = CatalogDraftUnitSerializer(many=True, required=False, default=list)

    def validate_spray_enabled(self, value):
        if "spray_enabled" in self.initial_data:
            return super().validate_spray_enabled(value)
        return value

    def validate(self, attrs):
        if attrs["template_key"] not in CATEGORY_TEMPLATES[attrs["category_key"]]:
            raise serializers.ValidationError({"template_key": "请选择该类别已确认的模板。"})
        return attrs


class CatalogPatchSerializer(StrictSerializer):
    spray_enabled = serializers.BooleanField(required=False)
    base_warehouse_id = serializers.UUIDField(required=False, allow_null=True)
    semi_warehouse_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("至少提交一个待修改字段。")
        return attrs

    def validate_spray_enabled(self, value):
        if not isinstance(self.initial_data["spray_enabled"], bool):
            raise serializers.ValidationError("喷塑开关必须为布尔值。")
        return value


class AttributeValueCreateSerializer(OrdinaryColorInputSerializer):
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    field_key = serializers.CharField(max_length=40)
    value = serializers.CharField(max_length=300, trim_whitespace=True)
    parent_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class UnitSelectionSerializer(StrictSerializer):
    unit_id = serializers.UUIDField(required=False)
    unit_name = serializers.CharField(max_length=80, trim_whitespace=True, required=False)

    def validate(self, attrs):
        if ("unit_id" in attrs) == ("unit_name" in attrs):
            raise serializers.ValidationError("单位ID与单位文字必须且只能填写一个。")
        return attrs


class AllowedUnitCreateSerializer(UnitSelectionSerializer):
    scope = serializers.ChoiceField(choices=MaterialScope.choices)


class AttributeValuePatchSerializer(OrdinaryColorInputSerializer):
    value = serializers.CharField(max_length=300, trim_whitespace=True)


class AllowedUnitPatchSerializer(UnitSelectionSerializer):
    pass


class CatalogListQuerySerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=CATEGORY_CHOICES, required=False, allow_blank=True)
    q = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True)


class CatalogSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category_key = serializers.CharField()
    template_key = serializers.CharField()
    name = serializers.CharField()
    spray_enabled = serializers.BooleanField()
    updated_at = serializers.DateTimeField()


class CatalogPageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


@extend_schema_serializer(many=False)
class CatalogListResponseSerializer(serializers.Serializer):
    data = CatalogSummarySerializer(many=True)
    meta = CatalogPageMetaSerializer()


class CatalogErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    field_errors = serializers.JSONField()
    request_id = serializers.CharField(allow_null=True)


class CatalogErrorResponseSerializer(serializers.Serializer):
    error = CatalogErrorSerializer()


class AttributeValueResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    field_key = serializers.CharField()
    value = serializers.CharField()
    parent_id = serializers.UUIDField(allow_null=True)
    product_color_id = serializers.UUIDField(allow_null=True, required=False)
    color_card = serializers.CharField(required=False, allow_blank=True)
    color_code = serializers.CharField(required=False, allow_blank=True)
    color_name = serializers.CharField(required=False)


class AllowedUnitResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    unit_id = serializers.UUIDField()
    unit_name = serializers.CharField()


class CatalogDetailSerializer(CatalogSummarySerializer):
    base_warehouse_id = serializers.UUIDField(allow_null=True)
    semi_warehouse_id = serializers.UUIDField(allow_null=True)
    values = AttributeValueResponseSerializer(many=True)
    units = AllowedUnitResponseSerializer(many=True)


class CatalogDetailResponseSerializer(serializers.Serializer):
    data = CatalogDetailSerializer()


class FieldDefinitionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=["text", "shape", "dimension", "unit"])


class TemplateDefinitionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    supports_spray = serializers.BooleanField()
    fields = FieldDefinitionSerializer(many=True)


class CategoryDefinitionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    templates = TemplateDefinitionSerializer(many=True)


class UnitOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    unit_name = serializers.CharField()


class CatalogWarehouseOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    warehouse_number = serializers.CharField()
    warehouse_name = serializers.CharField()
    warehouse_type = serializers.CharField()


class CatalogOptionsSerializer(serializers.Serializer):
    warehouses = CatalogWarehouseOptionSerializer(many=True)
    categories = CategoryDefinitionSerializer(many=True)
    spray_fields = FieldDefinitionSerializer(many=True)
    units = UnitOptionSerializer(many=True)


class CatalogOptionsResponseSerializer(serializers.Serializer):
    data = CatalogOptionsSerializer()
