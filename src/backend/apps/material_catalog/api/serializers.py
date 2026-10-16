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


class CatalogCreateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, trim_whitespace=True)
    category_key = serializers.ChoiceField(choices=CATEGORY_CHOICES)
    template_key = serializers.ChoiceField(choices=TEMPLATE_CHOICES)

    def validate(self, attrs):
        if attrs["template_key"] not in CATEGORY_TEMPLATES[attrs["category_key"]]:
            raise serializers.ValidationError({"template_key": "请选择该类别已确认的模板。"})
        return attrs


class CatalogPatchSerializer(StrictSerializer):
    spray_enabled = serializers.BooleanField()

    def validate_spray_enabled(self, value):
        if not isinstance(self.initial_data["spray_enabled"], bool):
            raise serializers.ValidationError("喷塑开关必须为布尔值。")
        return value


class AttributeValueCreateSerializer(StrictSerializer):
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    field_key = serializers.CharField(max_length=40)
    value = serializers.CharField(max_length=300, trim_whitespace=True)
    parent_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class AllowedUnitCreateSerializer(StrictSerializer):
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    unit_id = serializers.UUIDField()


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


class AllowedUnitResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    unit_id = serializers.UUIDField()
    unit_name = serializers.CharField()


class CatalogDetailSerializer(CatalogSummarySerializer):
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


class CatalogOptionsSerializer(serializers.Serializer):
    categories = CategoryDefinitionSerializer(many=True)
    spray_fields = FieldDefinitionSerializer(many=True)
    units = UnitOptionSerializer(many=True)


class CatalogOptionsResponseSerializer(serializers.Serializer):
    data = CatalogOptionsSerializer()
