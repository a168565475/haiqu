"""公共候选直接读取生产维护原表；新表只承接原先没有独立配置的属性。"""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.audit import write_audit_log
from apps.reference_data.models import (
    AccessoryColor, AccessoryMaterial, AccessoryProductName, AccessorySpecification,
    FabricMaterial, FabricSpecification, FabricWidth, MaterialAttributePublicValue,
    ProductColor, ProductionUnit, TubeCoatingColor, TubeDiameter, TubeMaterial,
    TubeShape, TubeShapeDimension, TubeThickness,
)

from .definitions import CATEGORIES, CATEGORY_TEMPLATES, SPRAY_FIELDS, TEMPLATES
from .accessory_weights import WEIGHT_FIELDS, accessory_weight_records, find_specification_weight, is_accessory_weight
from .colors import COLOR_FIELDS, color_identity, color_metadata, unchanged_color, uses_product_color_identity


SOURCES = {
    "tube-materials": (TubeMaterial, "material_name", "tube-material"),
    "tube-shapes": (TubeShape, "shape_name", "tube-shape"),
    "tube-thicknesses": (TubeThickness, "thickness_value", "tube-thickness"),
    "fabric-materials": (FabricMaterial, "material_name", "fabric-material"),
    "fabric-specifications": (FabricSpecification, "specification_name", "fabric-specification"),
    "fabric-widths": (FabricWidth, "width_value", "fabric-width"),
    "accessory-materials": (AccessoryMaterial, "material_name", "accessory-material"),
    "accessory-specifications": (AccessorySpecification, "specification_value", "accessory-specification"),
    "accessory-colors": (AccessoryColor, "color_name", "accessory-color"),
    "product-colors": (ProductColor, "color_name", "color"),
    "tube-coating-colors": (TubeCoatingColor, "color_name", "tube-coating-color"),
    "production-units": (ProductionUnit, "unit_name", "unit"),
}
ACTIVE = {"status": "ACTIVE", "archived_at__isnull": True}


def context(category_key, template_key, scope="BASE"):
    if template_key not in CATEGORY_TEMPLATES.get(category_key, set()):
        raise ValidationError({"template_key": "请选择类别对应的有效模板。"})
    if scope not in {"BASE", "SPRAY"} or (scope == "SPRAY" and not TEMPLATES[template_key]["supports_spray"]):
        raise ValidationError({"scope": "该模板不支持所选属性组。"})
    return SimpleNamespace(category_key=category_key, template_key=template_key, name="")


def source_for(catalog, scope, key):
    context(catalog.category_key, catalog.template_key, scope)
    fields = SPRAY_FIELDS if scope == "SPRAY" else TEMPLATES[catalog.template_key]["fields"]
    if key not in {field["key"] for field in fields}:
        raise ValidationError({"field_key": "属性不在当前模板固定名单中。"})
    if key in {"unit", "flow_unit"}:
        return "production-units"
    if scope == "SPRAY" and key == "color":
        return "tube-coating-colors"
    if catalog.category_key == "TUBE" and key in {"material", "shape", "thickness", "section_size"}:
        return {"material": "tube-materials", "shape": "tube-shapes", "thickness": "tube-thicknesses", "section_size": "tube-shape-dimensions"}[key]
    if catalog.category_key in {"FABRIC", "FABRIC_SEMI"} and key in {"material", "fabric_spec", "width"}:
        return {"material": "fabric-materials", "fabric_spec": "fabric-specifications", "width": "fabric-widths"}[key]
    if catalog.category_key == "AUXILIARY" and key in {"material", "specification", "color"}:
        return {"material": "accessory-materials", "specification": "accessory-specifications", "color": "accessory-colors"}[key]
    if key == "color":
        return "product-colors"
    return "material-attribute-values"


def fields_for(catalog, scope):
    fields = SPRAY_FIELDS if scope == "SPRAY" else TEMPLATES[catalog.template_key]["fields"]
    return [{**field, "source": source_for(catalog, scope, field["key"]),
             "manage_url": "/settings/production-data?tab=" + SOURCES[source_for(catalog, scope, field["key"])][2]
             if source_for(catalog, scope, field["key"]) in SOURCES else ""} for field in fields]


def public_fields():
    categories = deepcopy(CATEGORIES)
    for category in categories:
        for template in category["templates"]:
            template["fields"] = fields_for(context(category["key"], template["key"]), "BASE")
    return {"categories": categories, "spray_fields": fields_for(context("TUBE", "TUBE", "SPRAY"), "SPRAY")}


def source_queryset(source, catalog, scope, key):
    if source == "material-attribute-values":
        return MaterialAttributePublicValue.objects.filter(
            category_key=catalog.category_key, template_key=catalog.template_key, scope=scope, field_key=key,
        ), "value"
    model, value_field, _ = SOURCES[source]
    queryset = model.objects.all()
    if model in {AccessorySpecification, AccessoryColor}:
        queryset = queryset.filter(product_name__status="ACTIVE", product_name__archived_at__isnull=True)
    return queryset, value_field


def public_options(category_key, template_key, scope):
    catalog = context(category_key, template_key, scope)
    values = []
    for field in fields_for(catalog, scope):
        key, source = field["key"], field["source"]
        if key == "unit":
            continue
        if is_accessory_weight(category_key, template_key, scope, key):
            values.extend({"id": row["id"], "scope": scope, "field_key": key, "value": row["value"], "parent_id": None}
                          for row in accessory_weight_records() if row["status"] == "ACTIVE" and row["archived_at"] is None)
            continue
        if source == "tube-shape-dimensions":
            shapes = list(TubeShape.objects.filter(**ACTIVE))
            relations = TubeShapeDimension.objects.filter(
                **ACTIVE, shape__status="ACTIVE", shape__archived_at__isnull=True,
                diameter__status="ACTIVE", diameter__archived_at__isnull=True,
            ).select_related("diameter")
            values.extend({"id": str(row.pk), "scope": scope, "field_key": key,
                           "value": row.diameter.diameter_value, "parent_id": str(row.shape_id)} for row in relations)
            # 无任何形状关系的旧直径仍可选；存在停用关系的直径不得退回通用候选。
            for diameter in TubeDiameter.objects.filter(**ACTIVE, shape_options__isnull=True):
                values.extend({"id": str(diameter.pk), "scope": scope, "field_key": key,
                               "value": diameter.diameter_value, "parent_id": str(shape.pk)} for shape in shapes)
            continue
        queryset, value_field = source_queryset(source, catalog, scope, key)
        color_identity_enabled = uses_product_color_identity(catalog, scope, key)
        seen = set()
        for row in queryset.filter(**ACTIVE):
            value = getattr(row, value_field)
            if not value.strip() or (not color_identity_enabled and value in seen):
                continue
            seen.add(value)
            values.append({"id": str(row.pk), "scope": scope, "field_key": key, "value": value, "parent_id": None,
                           **(color_metadata(row) if color_identity_enabled else {})})
    return {"category_key": category_key, "template_key": template_key, "scope": scope, "values": values,
            "units": [{"id": str(row.pk), "unit_name": row.unit_name} for row in ProductionUnit.objects.filter(**ACTIVE)],
            "fields": fields_for(catalog, scope)}


def can_contribute(request):
    return request is not None and (request.user.has_perm("material_catalog.change_materialcatalog") or (
        request.user.has_perm("material_catalog.view_materialcatalog") and request.user.has_perm("products.add_rawmaterialinformation")))


def validate_text(value, max_length=300):
    if not isinstance(value, str) or not value.strip() or value.strip() in {"/", "-", "—"}:
        raise ValidationError({"value": "公共属性必须填写实际值，不能使用空白或占位符。"})
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError({"value": f"该公共配置最多允许{max_length}字，不能自动截断。"})
    return value


@transaction.atomic
def require_public_value(catalog, scope, key, value, *, parent_value=None, lock=False, color=None):
    """只验证现有公共候选；BOM 选料不得借校验创建配置或形状尺寸关系。"""
    source = source_for(catalog, scope, key)
    value = validate_text(value)
    color_identity_enabled = uses_product_color_identity(catalog, scope, key)
    _validate_color_source(color_identity_enabled, color)
    if color_identity_enabled:
        return _resolve_product_color(value, color, request=None, persist=lock, create=False)

    def first(queryset):
        return (queryset.select_for_update() if lock else queryset).first()

    current = None
    if is_accessory_weight(catalog.category_key, catalog.template_key, scope, key):
        explicit = first(MaterialAttributePublicValue.objects.filter(**WEIGHT_FIELDS, value=value))
        if explicit is not None:
            current = explicit if explicit.status == "ACTIVE" and explicit.archived_at is None else None
        else:
            current = find_specification_weight(value, lock=lock)
    elif source == "tube-shape-dimensions":
        shape = first(TubeShape.objects.filter(shape_name=validate_text(parent_value, 150), **ACTIVE))
        diameter = first(TubeDiameter.objects.filter(diameter_value=validate_text(value, 50), **ACTIVE))
        if shape is not None and diameter is not None:
            current = first(TubeShapeDimension.objects.filter(shape=shape, diameter=diameter, **ACTIVE))
            # 和候选读取保持一致：从未绑定任何形状的旧直径可通用，但不在选料时新建关系。
            if current is None and not TubeShapeDimension.objects.filter(diameter=diameter).exists():
                current = diameter
    else:
        queryset, value_field = source_queryset(source, catalog, scope, key)
        value = validate_text(value, queryset.model._meta.get_field(value_field).max_length)
        if queryset.model in {AccessorySpecification, AccessoryColor}:
            queryset = queryset.select_related("product_name")
        current = first(queryset.filter(**{value_field: value}, **ACTIVE))
    if current is None:
        raise ValidationError({key: "所选值不存在、已停用或不属于当前公共候选，请先到生产维护新增或启用后重选。"})
    return current


def _validate_color_source(color_identity_enabled, color):
    if not color_identity_enabled and color and any(color.get(key) for key in COLOR_FIELDS):
        raise ValidationError({"product_color_id": "只有面料基础颜色可以使用色卡、色号和普通颜色标识。"})


def _resolve_product_color(value, color, *, request, persist, create):
    color = color or {}
    identity = color_identity(validate_text(value, 200), color)
    query = ProductColor.objects.select_for_update() if persist else ProductColor.objects.all()
    if color.get("product_color_id"):
        current = query.filter(pk=color["product_color_id"], **ACTIVE).first()
        if current is None:
            raise ValidationError({"product_color_id": "普通颜色不存在、已停用或归档，请到生产维护核实后重选。"})
        if current.color_name != identity["color_name"] or any(
                key in color and getattr(current, key) != identity[key] for key in identity):
            raise ValidationError({"product_color_id": "颜色标识与色卡、色号或颜色名不一致，请重新选择；编辑颜色时请清除原标识。"})
        return current
    # 旧调用没有ID时只匹配完整三元组，绝不按颜色名取第一条其他色卡记录。
    if create:
        return _ensure(ProductColor, identity, request=request, persist=persist)
    current = query.filter(**identity, **ACTIVE).first()
    if current is None:
        raise ValidationError({"product_color_id": "请选择生产维护中已有且有效的普通颜色，BOM不能新增颜色。"})
    return current


def _ensure(model, lookup, *, defaults=None, request, persist, allow_inactive=False, require_contribution=True):
    candidates = model.objects.filter(**lookup)
    if persist:
        candidates = candidates.select_for_update()
    current = candidates.filter(**ACTIVE).first()
    if current is not None:
        return current
    inactive = candidates.first()
    if inactive is not None:
        if allow_inactive:
            return inactive
        raise ValidationError({"value": "对应公共配置已停用或归档，请在生产维护核实；保存不会自动恢复。"})
    if require_contribution and request is not None and not can_contribute(request):
        raise PermissionDenied("当前账号没有补录公共原料配置的权限。")
    if not persist:
        return None
    # 唯一约束处理并发补录；get_or_create 保留其他请求创建的规范标识。
    current, created = model.objects.get_or_create(**lookup, defaults=defaults or {})
    if not created:
        current = model.objects.select_for_update().get(pk=current.pk)
    if current.status != "ACTIVE" or current.archived_at is not None:
        raise ValidationError({"value": "对应公共配置已停用或归档。"})
    if created:
        write_audit_log(object_type="MATERIAL_PUBLIC_CONFIG", object_id=current.pk, action="CREATED",
                        actor_employee=getattr(request, "employee", None),
                        after_data={"model": model._meta.label, **lookup, **(defaults or {})}, request=request)
    return current


@transaction.atomic
def ensure_public_value(catalog, scope, key, value, *, parent_value=None, unit_name="", request=None, persist=True, allow_inactive=False, color=None):
    source = source_for(catalog, scope, key)
    color_identity_enabled = uses_product_color_identity(catalog, scope, key)
    _validate_color_source(color_identity_enabled, color)
    if color_identity_enabled:
        return _resolve_product_color(value, color, request=request, persist=persist, create=True)
    if is_accessory_weight(catalog.category_key, catalog.template_key, scope, key):
        value = validate_text(value)
        # 先服从显式公共记录状态；无补录项时才复用现有规格事实，不复制或修改规格。
        if not MaterialAttributePublicValue.objects.filter(**WEIGHT_FIELDS, value=value).exists():
            specification = find_specification_weight(value, lock=persist)
            if specification is not None:
                return specification
    if source == "tube-shape-dimensions":
        shape_value = validate_text(parent_value, 150)
        diameter_value = validate_text(value, 50)
        shape = _ensure(TubeShape, {"shape_name": shape_value}, request=request, persist=persist, allow_inactive=allow_inactive)
        diameter = _ensure(TubeDiameter, {"diameter_value": diameter_value}, request=request, persist=persist, allow_inactive=allow_inactive)
        if shape is None or diameter is None:
            return None
        was_public = not TubeShapeDimension.objects.filter(diameter=diameter).exists()
        return _ensure(TubeShapeDimension, {"shape_id": shape.pk, "diameter_id": diameter.pk},
                       request=request, persist=persist, allow_inactive=allow_inactive, require_contribution=not was_public)
    queryset, value_field = source_queryset(source, catalog, scope, key)
    model = queryset.model
    value = validate_text(value, model._meta.get_field(value_field).max_length)
    lookup = {value_field: value}
    defaults = {}
    if source == "material-attribute-values":
        lookup.update(category_key=catalog.category_key, template_key=catalog.template_key, scope=scope, field_key=key)
    elif model in {AccessorySpecification, AccessoryColor}:
        candidates = queryset.filter(**lookup, **ACTIVE).select_related("product_name")
        existing = (candidates.select_for_update() if persist else candidates).first()
        if existing:
            return existing
        # 已停用的同值也不能借用新父品名绕过状态限制。
        if model.objects.filter(**lookup).exists():
            if allow_inactive:
                return model.objects.filter(**lookup).first()
            raise ValidationError({"value": "对应辅料公共选项或所属品名已停用/归档，请先核实生产维护。"})
        product_name = validate_text(catalog.name, 200)
        if not AccessoryProductName.objects.filter(product_name=product_name).exists():
            if not unit_name and hasattr(catalog, "allowed_units"):
                names = list(catalog.allowed_units.filter(
                    scope="BASE", archived_at__isnull=True, unit__status="ACTIVE", unit__archived_at__isnull=True,
                ).values_list("unit__unit_name", flat=True).distinct())
                if len(names) == 1:
                    unit_name = names[0]
            if not unit_name:
                raise ValidationError({"unit_name": "新增公共辅料品名需要明确单位；当前无唯一有效基础单位，请先指定单位后重试。"})
        product = _ensure(AccessoryProductName, {"product_name": product_name}, defaults={"unit_name": validate_text(unit_name, 50) if unit_name else ""},
                          request=request, persist=persist, allow_inactive=allow_inactive)
        if product is None:
            return None
        lookup["product_name_id"] = product.pk
    elif model is ProductionUnit:
        defaults["unit_code"] = "MC" + uuid4().hex[:18]
    elif model is ProductColor:
        defaults.update(color_card="", color_code="")
    return _ensure(model, lookup, defaults=defaults, request=request, persist=persist, allow_inactive=allow_inactive)


def ensure_public_draft(catalog, data, *, request):
    existing_values = {row.pk: row for row in catalog.attribute_values.select_related("product_color")}
    drafts = {row["id"]: row for row in data["values"]}
    unit_name = next((row["unit_name"] for row in data["units"] if row["scope"] == "BASE"), "")
    for row in data["values"]:
        previous = existing_values.get(row["id"])
        parent = drafts.get(row["parent_id"])
        same = previous is not None and previous.archived_at is None and previous.value == row["value"]
        ordinary_color = uses_product_color_identity(catalog, row["scope"], row["field_key"])
        _validate_color_source(ordinary_color, row)
        if ordinary_color:
            same = unchanged_color(previous, row)
            if same:
                row["product_color_id"] = previous.product_color_id
        if same and row["field_key"] == "section_size":
            same = parent is not None and previous.parent_id is not None and previous.parent.value == parent["value"]
        if same:
            continue
        public = ensure_public_value(catalog, row["scope"], row["field_key"], row["value"],
                            parent_value=parent["value"] if parent else None, unit_name=unit_name,
                            request=request, allow_inactive=same, color=row if ordinary_color else None)
        if ordinary_color:
            row["product_color_id"] = public.pk
    existing_units = {(row.pk, row.unit.unit_name) for row in catalog.allowed_units.filter(archived_at__isnull=True).select_related("unit")}
    for row in data["units"]:
        if (row["id"], row["unit_name"]) in existing_units:
            continue
        ensure_public_value(catalog, row["scope"], "unit", row["unit_name"], request=request,
                            allow_inactive=False)
