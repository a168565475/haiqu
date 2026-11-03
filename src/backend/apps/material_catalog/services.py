from uuid import uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.audit import write_audit_log
from apps.reference_data.models import ProductionUnit
from apps.inventory.models import Warehouse

from .definitions import SPRAY_FIELDS, TEMPLATES
from .colors import COLOR_FIELDS, unchanged_color, uses_product_color_identity
from .models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog, MaterialScope
from .public_configuration import ensure_public_value
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
        ensure_public_value(catalog, MaterialScope.SPRAY, "color", "无颜色", request=request)
        MaterialAttributeValue.objects.create(catalog=catalog, scope=MaterialScope.SPRAY, field_key="color", value="无颜色")
    return _finish_change(catalog, before, "CATALOG_CHANGED", request)


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
    values = {"catalog": catalog, "scope": data["scope"], "field_key": data["field_key"], "value": data["value"], "parent_id": parent_id}
    parent_value = catalog.attribute_values.get(pk=parent_id).value if parent_id else None
    public = ensure_public_value(catalog, data["scope"], data["field_key"], data["value"], parent_value=parent_value, request=request, color=data)
    if uses_product_color_identity(catalog, data["scope"], data["field_key"]):
        values["product_color_id"] = public.pk
        lookup = {key: value for key, value in values.items() if key != "value"}
    else:
        lookup = {**values, "product_color_id": None}
    existing = MaterialAttributeValue.objects.filter(**lookup).first()
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"value": "该属性值已存在。"})
        _restore(existing)
        action = "VALUE_RESTORED"
    else:
        MaterialAttributeValue.objects.create(**values)
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
    ordinary_color = uses_product_color_identity(catalog, option.scope, option.field_key)
    if (ordinary_color and unchanged_color(option, {**(color or {}), "value": value})) or (
            not ordinary_color and option.value == value and not any((color or {}).get(key) for key in COLOR_FIELDS)):
        return _snapshot_response(catalog)
    public = ensure_public_value(catalog, option.scope, option.field_key, value,
                                parent_value=option.parent.value if option.parent_id else None, request=request, color=color)
    product_color_id = public.pk if ordinary_color else None
    lookup = {"catalog": catalog, "scope": option.scope, "field_key": option.field_key, "parent_id": option.parent_id,
              "product_color_id": product_color_id}
    if not product_color_id:
        lookup["value"] = value
    # 唯一约束包含已归档项；编辑不合并颜色身份，也不改写公共颜色记录。
    if MaterialAttributeValue.objects.filter(**lookup).exclude(pk=option.pk).exists():
        raise ValidationError({"value": "该属性值已存在（含已移除的记录），请使用其他值。"})
    if option.field_key == "shape":
        for dimension in option.dimensions.filter(archived_at__isnull=True):
            ensure_public_value(catalog, dimension.scope, dimension.field_key, dimension.value,
                                parent_value=value, request=request)
    before = catalog_detail(catalog)
    option.value = value
    option.product_color_id = product_color_id
    option.save(update_fields=["value", "product_color", "updated_at"])
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
        # 公共表只复用内部标识；新单位仅关联当前品名，不共享候选。
        unit, _ = ProductionUnit.objects.get_or_create(
            unit_name=data["unit_name"], defaults={"unit_code": "MC" + uuid4().hex[:18]},
        )
    if unit is None or unit.status != "ACTIVE" or unit.archived_at is not None:
        raise ValidationError({"unit_id": "单位不存在、已停用或已归档。"})
    return unit


def _ensure_public_unit(catalog, scope, data, request):
    if "unit_name" in data:
        name = data["unit_name"]
    else:
        name = ProductionUnit.objects.filter(pk=data["unit_id"]).values_list("unit_name", flat=True).first()
        if name is None:
            raise ValidationError({"unit_id": "单位不存在。"})
    ensure_public_value(catalog, scope, "unit", name, request=request)


@transaction.atomic
def add_unit(*, catalog_id, data, request):
    catalog = _locked_catalog(catalog_id, request)
    _scope_fields(catalog, data["scope"])
    _ensure_public_unit(catalog, data["scope"], data, request)
    unit = resolve_unit(data)
    before = catalog_detail(catalog)
    existing = MaterialAllowedUnit.objects.filter(catalog=catalog, scope=data["scope"], unit=unit).first()
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
    _ensure_public_unit(catalog, option.scope, data, request)
    unit = resolve_unit(data)
    if MaterialAllowedUnit.objects.filter(catalog=catalog, scope=option.scope, unit=unit).exclude(pk=option.pk).exists():
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
