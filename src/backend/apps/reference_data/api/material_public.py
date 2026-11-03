from collections.abc import Mapping

from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.permissions import HasActiveEmployee
from apps.core.audit import write_audit_log
from apps.material_catalog.api.public import PublicConfigurationReadPermission
from apps.material_catalog.public_configuration import can_contribute, context, source_for, validate_text
from apps.material_catalog.accessory_weights import WEIGHT_FIELDS, accessory_weight_records, find_specification_weight, is_accessory_weight

from ..models import MaterialAttributePublicValue, TubeShapeDimension
from .serializers import StatusActionSerializer
from .views import ManagedReferenceViewSet


class PublicMaintenancePermission(BasePermission):
    def has_permission(self, request, view):
        if view.action in {"list", "retrieve", "metadata"}:
            return PublicConfigurationReadPermission().has_permission(request, view)
        if view.action in {"activate", "deactivate"}:
            return request.user.has_perm("material_catalog.change_materialcatalog")
        if view.action in {"create", "partial_update"}:
            return can_contribute(request)
        return False


class PublicConfigSerializer(serializers.ModelSerializer):
    patch_fields = {"description", "sort_order"}

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            allowed = self.patch_fields if self.instance is not None else set(self.fields) - set(self.Meta.read_only_fields)
            unknown = set(data) - allowed
            if unknown:
                raise serializers.ValidationError({key: "不允许修改此字段。" for key in sorted(unknown)})
        return super().to_internal_value(data)


class MaterialAttributePublicValueSerializer(PublicConfigSerializer):
    patch_fields = PublicConfigSerializer.patch_fields | {"value"}
    source_kind = serializers.ChoiceField(choices=["PUBLIC", "SPECIFICATION"], read_only=True)
    editable = serializers.BooleanField(read_only=True)
    source_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MaterialAttributePublicValue
        fields = ["id", "category_key", "template_key", "scope", "field_key", "value", "status", "sort_order", "description", "updated_at", "archived_at", "source_kind", "editable", "source_count"]
        read_only_fields = ["id", "updated_at", "archived_at", "source_kind", "editable", "source_count"]

    def validate_value(self, value):
        return validate_text(value)

    def validate(self, attrs):
        def current(key):
            return attrs.get(key, getattr(self.instance, key, None))
        catalog = context(current("category_key"), current("template_key"), current("scope"))
        if source_for(catalog, current("scope"), current("field_key")) != "material-attribute-values":
            raise serializers.ValidationError({"field_key": "该属性已有生产维护来源，请使用原维护入口。"})
        if (is_accessory_weight(catalog.category_key, catalog.template_key, current("scope"), current("field_key"))
                and (self.instance is None or current("value") != self.instance.value)
                and find_specification_weight(current("value")) is not None):
            raise serializers.ValidationError({"value": "该克重已由有效辅料规格提供，请使用已有候选；修改来源请到辅料规格维护。"})
        return attrs


class TubeShapeDimensionSerializer(PublicConfigSerializer):
    shape_name = serializers.CharField(source="shape.shape_name", read_only=True)
    diameter_value = serializers.CharField(source="diameter.diameter_value", read_only=True)

    class Meta:
        model = TubeShapeDimension
        fields = ["id", "shape", "shape_name", "diameter", "diameter_value", "status", "sort_order", "description", "updated_at", "archived_at"]
        read_only_fields = ["id", "shape_name", "diameter_value", "updated_at", "archived_at"]

    def validate(self, attrs):
        for key in ("shape", "diameter"):
            row = attrs.get(key, getattr(self.instance, key, None))
            if row is None or row.status != "ACTIVE" or row.archived_at is not None:
                raise serializers.ValidationError({key: "请选择现有且启用的公共形状和直径。"})
        return attrs


class MaterialPublicMaintenanceViewSet(ManagedReferenceViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, PublicMaintenancePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as exc:
            if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) in {
                "ref_material_attribute_unique", "ref_tube_shape_dimension_unique",
            }:
                raise ValidationError("公共配置已存在，请刷新后使用已有选项。") from exc
            raise

    def partial_update(self, request, *args, **kwargs):
        try:
            return super().partial_update(request, *args, **kwargs)
        except IntegrityError as exc:
            if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) == "ref_material_attribute_unique":
                raise ValidationError({"value": "该公共属性值已存在。"}) from exc
            raise

    def _set_status(self, request, target_status):
        current = self.get_object()
        serializer = StatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = self.locked_instance(current.pk)
            require_matching_etag(request, instance)
            if instance.archived_at is not None:
                raise ValidationError("已归档配置不能通过启停接口恢复。")
            if target_status == "ACTIVE" and isinstance(instance, TubeShapeDimension):
                if any(row.status != "ACTIVE" or row.archived_at is not None for row in (instance.shape, instance.diameter)):
                    raise ValidationError("请先启用关联的形状和直径。")
            before = self.get_serializer(instance).data
            instance.status = target_status
            instance.save(update_fields=["status", "updated_at"])
            after = self.get_serializer(instance).data
            write_audit_log(object_type=self.object_type, object_id=instance.pk,
                            action="ACTIVATED" if target_status == "ACTIVE" else "DEACTIVATED",
                            actor_employee=self.actor_employee(), before_data=before,
                            after_data={**after, "reason": serializer.validated_data["reason"]}, request=request)
            return self.response_with_etag(after, instance)


class MaterialAttributePublicValueViewSet(MaterialPublicMaintenanceViewSet):
    queryset = MaterialAttributePublicValue.objects.all()
    serializer_class = MaterialAttributePublicValueSerializer
    search_fields = ("value",)
    object_type = "MATERIAL_PUBLIC_ATTRIBUTE"

    def list(self, request, *args, **kwargs):
        if all(request.query_params.get(key) == value for key, value in WEIGHT_FIELDS.items()):
            rows = accessory_weight_records()
            if request.query_params.get("include_archived") != "true":
                rows = [row for row in rows if row["archived_at"] is None]
            status = request.query_params.get("status")
            if status in {"ACTIVE", "INACTIVE"}:
                rows = [row for row in rows if row["status"] == status]
            keyword = request.query_params.get("q", "").strip().casefold()
            if keyword:
                rows = [row for row in rows if keyword in row["value"].casefold()]
            return self.get_paginated_response(self.paginate_queryset(rows))
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        for key in ("category_key", "template_key", "scope", "field_key"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{key: value})
        return queryset


class TubeShapeDimensionViewSet(MaterialPublicMaintenanceViewSet):
    queryset = TubeShapeDimension.objects.select_related("shape", "diameter")
    serializer_class = TubeShapeDimensionSerializer
    search_fields = ("shape__shape_name", "diameter__diameter_value")
    object_type = "TUBE_SHAPE_DIMENSION"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("shape"):
            field = serializers.UUIDField()
            queryset = queryset.filter(shape_id=field.run_validation(self.request.query_params["shape"]))
        return queryset
