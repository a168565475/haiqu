from uuid import uuid4

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.audit import write_audit_log
from apps.reference_data.models import ProductionUnit
from apps.inventory.models import Warehouse

from .definitions import SPRAY_FIELDS, TEMPLATES
from .colors import color_identity, unchanged_color, uses_product_color_identity
from .models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog, MaterialScope
from .public_configuration import SOURCES, _resolve_product_color, _validate_color_source, source_for
from .selectors import catalog_detail


def _locked_catalog(catalog_id, request):
    catalog = get_object_or_404(
        MaterialCatalog.objects.select_for_update(), pk=catalog_id, archived_at__isnull=True
    )
    require_matching_etag(request, catalog)
    return catalog


def _scope_fields(catalog, scope):
    if scope == MaterialScope.BASE:
        return TEMPLATES[catalog.template_key]["fields"]
    if scope == MaterialScope.SPRAY and catalog.spray_enabled and TEMPLATES[catalog.template_key]["supports_spray"]:
        return SPRAY_FIELDS
    raise ValidationError({"scope": "该物料未启用所选属性组。"})


def _snapshot_response(catalog):
    return catalog_detail(catalog), etag_for_instance(catalog)


def _finish_change(catalog, before, action, request):
    # 子项变更也刷新主档版本；前端始终以整份档案的 ETag 串行写入。
    catalog.save(update_fields=["name", "spray_enabled", "base_warehouse", "semi_warehouse", "updated_at"])
    after, etag = _snapshot_response(catalog)
    write_audit_log(
        object_type="MATERIAL_CATALOG", object_id=catalog.pk, action=action,
        actor_employee=getattr(request, "employee", None),
        before_data=before, after_data=after, request=request,
    )
    return after, etag


def _archive(option, request):
    option.archived_at = timezone.now()
    option.archived_by_employee = getattr(request, "employee", None)
    option.archive_reason = "从原料管理移除可选值"
    option.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])


def _restore(option):
    option.archived_at = None
    option.archived_by_employee = None
    option.archive_reason = ""
    option.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])


def create_catalog(*, data, request):
    from .editing import create_catalog as create_draft_catalog

    return create_draft_catalog(data=data, request=request)


@transaction.atomic
def update_catalog(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    enabled = data.get("spray_enabled", catalog.spray_enabled)
    if enabled and not TEMPLATES[catalog.template_key]["supports_spray"]:
        raise ValidationError({"spray_enabled": "该品名不支持半成品属性。"})
    warehouses = {}
    for field in ("base_warehouse_id", "semi_warehouse_id"):
        if field not in data:
            continue
        warehouse_id = data[field]
        if warehouse_id is not None and not Warehouse.objects.filter(pk=warehouse_id, status="ACTIVE").exists():
            raise ValidationError({field: "请选择现有且启用的仓库。"})
        if field == "semi_warehouse_id" and warehouse_id and catalog.category_key not in {"TUBE", "HARDWARE", "FABRIC_SEMI"}:
            raise ValidationError({field: "该类别没有现有半成品入口。"})
        warehouses[field] = warehouse_id
    before = catalog_detail(catalog)
    catalog.spray_enabled = enabled
    for field, warehouse_id in warehouses.items():
        setattr(catalog, field, warehouse_id)
    # 包含软删记录，避免重复开启时擅自恢复用户已经移除的默认颜色。
    if enabled and not catalog.attribute_values.filter(scope=MaterialScope.SPRAY).exists():
        MaterialAttributeValue.objects.create(catalog=catalog, scope=MaterialScope.SPRAY, field_key="color", value="无颜色")
    return _finish_change(catalog, before, "CATALOG_CHANGED", request)


def catalog_value_fields(catalog, scope, key, value, *, color=None, previous=None):
    ordinary_color = uses_product_color_identity(catalog, scope, key)
    _validate_color_source(ordinary_color, color)
    fields = {"value": value, "product_color_id": None, "color_card": "", "color_code": ""}
    if previous and previous.archived_at is None and (unchanged_color(previous, {**(color or {}), "value": value})
            if ordinary_color else previous.value == value):
        return {name: getattr(previous, name) for name in fields}
    source = source_for(catalog, scope, key)
    limit = 50 if key == "section_size" else 300
    if source in SOURCES:
        model, field, _ = SOURCES[source]
        limit = model._meta.get_field(field).max_length
    if not value.strip() or value.strip() in {"/", "-", "—"} or len(value) > limit:
        raise ValidationError({"value": f"请填写实际属性值，最多允许{limit}字。"})
    if ordinary_color:
        if color and color.get("product_color_id"):
            fields["product_color_id"] = _resolve_product_color(value, color, request=None, persist=False, create=False).pk
        else:
            identity = color_identity(value, color)
            fields.update(color_card=identity["color_card"], color_code=identity["color_code"])
    return fields


def _value_lookup(fields):
    if fields["product_color_id"]:
        return {"product_color_id": fields["product_color_id"]}
    return fields


@transaction.atomic
def add_value(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    fields = _scope_fields(catalog, data["scope"])
    definition = next((field for field in fields if field["key"] == data["field_key"] and field["kind"] != "unit"), None)
    if definition is None:
        raise ValidationError({"field_key": "该属性不在当前类别及属性组的固定名单中。"})
    parent_id = data.get("parent_id")
    if definition["kind"] == "dimension":
        if parent_id is None or not catalog.attribute_values.filter(
            pk=parent_id, scope=MaterialScope.BASE, field_key="shape", archived_at__isnull=True
        ).exists():
            raise ValidationError({"parent_id": "截面尺寸必须选择本物料有效的截面形状。"})
    elif parent_id is not None:
        raise ValidationError({"parent_id": "只有截面尺寸可以关联截面形状。"})
    before = catalog_detail(catalog)
    values = {"catalog": catalog, "scope": data["scope"], "field_key": data["field_key"], "parent_id": parent_id}
    fields = catalog_value_fields(catalog, data["scope"], data["field_key"], data["value"], color=data)
    existing = MaterialAttributeValue.objects.filter(**values, **_value_lookup(fields)).first()
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"value": "该属性值已存在。"})
        _restore(existing)
        action = "VALUE_RESTORED"
    else:
        MaterialAttributeValue.objects.create(**values, **fields)
        action = "VALUE_ADDED"
    return _finish_change(catalog, before, action, request)


@transaction.atomic
def update_value(*, catalog_id, value_id, value, request, color=None):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAttributeValue, pk=value_id, catalog=catalog, archived_at__isnull=True)
    fields = _scope_fields(catalog, option.scope)
    definition = next((field for field in fields if field["key"] == option.field_key and field["kind"] != "unit"), None)
    if definition is None:
        raise ValidationError({"value": "该属性不在当前类别及属性组的固定名单中。"})
    if definition["kind"] == "dimension" and not catalog.attribute_values.filter(
        pk=option.parent_id, scope=MaterialScope.BASE, field_key="shape", archived_at__isnull=True
    ).exists():
        raise ValidationError({"value": "该截面尺寸关联的形状已失效，请重新读取档案。"})
    fields = catalog_value_fields(catalog, option.scope, option.field_key, value, color=color, previous=option)
    if all(getattr(option, key) == field for key, field in fields.items()):
        return _snapshot_response(catalog)
    lookup = {"catalog": catalog, "scope": option.scope, "field_key": option.field_key, "parent_id": option.parent_id,
              **_value_lookup(fields)}
    # 唯一约束包含已归档项；编辑不合并颜色身份，也不改写公共颜色记录。
    if MaterialAttributeValue.objects.filter(**lookup).exclude(pk=option.pk).exists():
        raise ValidationError({"value": "该属性值已存在（含已移除的记录），请使用其他值。"})
    before = catalog_detail(catalog)
    for key, field in fields.items():
        setattr(option, key, field)
    option.save(update_fields=[*fields, "updated_at"])
    return _finish_change(catalog, before, "VALUE_CHANGED", request)


@transaction.atomic
def remove_value(*, catalog_id, value_id, request):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAttributeValue, pk=value_id, catalog=catalog, archived_at__isnull=True)
    _scope_fields(catalog, option.scope)
    if option.dimensions.filter(archived_at__isnull=True).exists():
        raise ValidationError({"parent_id": "该形状仍有截面尺寸，请先逐项移除尺寸。"})
    before = catalog_detail(catalog)
    _archive(option, request)
    return _finish_change(catalog, before, "VALUE_REMOVED", request)


def resolve_unit(data):
    if "unit_id" in data:
        unit = ProductionUnit.objects.filter(pk=data["unit_id"]).first()
    else:
        unit, _ = ProductionUnit.objects.get_or_create(
            unit_name=data["unit_name"], defaults={"unit_code": "MC" + uuid4().hex[:18]},
        )
    if unit is None or unit.status != "ACTIVE" or unit.archived_at is not None:
        raise ValidationError({"unit_id": "单位不存在、已停用或已归档。"})
    return unit


def resolve_catalog_unit(catalog, scope, data):
    units = ProductionUnit.for_catalog(catalog)
    if "unit_id" in data:
        unit = units.filter(pk=data["unit_id"]).first()
    else:
        name = data["unit_name"]
        candidates = units.filter(unit_name=name)
        # 已有归档关联也保留原单位身份。例如品名建“捆”之后，单位管理又新增了同名公共单位。
        unit = candidates.filter(material_catalog_options__catalog=catalog, material_catalog_options__scope=scope).order_by(
            F("material_catalog_options__archived_at").desc(nulls_first=True), "id"
        ).first()
        if unit is None:
            unit = candidates.filter(catalog_owner=catalog).first() or candidates.filter(catalog_owner=None).first()
        if unit is None:
            if name in {"/", "-", "—"}:
                raise ValidationError({"unit_name": "请填写实际的计量单位名称。"})
            unit = ProductionUnit.all_objects.create(catalog_owner=catalog, unit_name=name, unit_code="MC" + uuid4().hex[:18])
    if unit is None or unit.status != "ACTIVE" or unit.archived_at is not None:
        raise ValidationError({"unit_id": "单位不属于当前品名、已停用或已归档。"})
    return unit


@transaction.atomic
def add_unit(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    _scope_fields(catalog, data["scope"])
    unit = resolve_catalog_unit(catalog, data["scope"], data)
    before = catalog_detail(catalog)
    existing = MaterialAllowedUnit.objects.filter(catalog=catalog, scope=data["scope"], unit=unit).first()
    if catalog.allowed_units.filter(scope=data["scope"], unit__unit_name=unit.unit_name,
                                   archived_at__isnull=True).exclude(unit=unit).exists():
        raise ValidationError({"unit_id": "该属性组已包含同名可用单位。"})
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"unit_id": "该属性组已包含此可用单位。"})
        _restore(existing)
        action = "UNIT_RESTORED"
    else:
        MaterialAllowedUnit.objects.create(catalog=catalog, scope=data["scope"], unit=unit)
        action = "UNIT_ADDED"
    return _finish_change(catalog, before, action, request)


@transaction.atomic
def update_unit(*, catalog_id, option_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAllowedUnit, pk=option_id, catalog=catalog, archived_at__isnull=True)
    _scope_fields(catalog, option.scope)
    if data.get("unit_id") == option.unit_id or data.get("unit_name") == option.unit.unit_name:
        return _snapshot_response(catalog)
    unit = resolve_catalog_unit(catalog, option.scope, data)
    if MaterialAllowedUnit.objects.filter(catalog=catalog, scope=option.scope, unit__unit_name=unit.unit_name).exclude(pk=option.pk).exists():
        raise ValidationError({"unit_id": "该属性组已包含此单位（含已移除的记录），请选择其他单位。"})
    if option.unit_id == unit.pk:
        return _snapshot_response(catalog)
    before = catalog_detail(catalog)
    option.unit = unit
    option.save(update_fields=["unit", "updated_at"])
    return _finish_change(catalog, before, "UNIT_CHANGED", request)


@transaction.atomic
def remove_unit(*, catalog_id, option_id, request):
    catalog = _locked_catalog(catalog_id, request)
    option = get_object_or_404(MaterialAllowedUnit, pk=option_id, catalog=catalog, archived_at__isnull=True)
    _scope_fields(catalog, option.scope)
    before = catalog_detail(catalog)
    _archive(option, request)
    return _finish_change(catalog, before, "UNIT_REMOVED", request)
