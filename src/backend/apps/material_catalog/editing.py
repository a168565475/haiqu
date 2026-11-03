"""品名及其全部可选属性在同一事务内保存，历史引用只归档、不物理删除。"""

from uuid import uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.audit import write_audit_log
from apps.inventory.models import Warehouse

from .definitions import SPRAY_FIELDS, TEMPLATES
from .models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog, MaterialScope
from .public_configuration import ensure_public_draft
from .selectors import catalog_detail
from .services import _archive, _finish_change, _locked_catalog, _restore, resolve_unit


def _raise_write_conflict(exc):
    constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
    errors = {
        "mat_catalog_category_name_uniq": {"name": "该类别下已存在相同品名（含已归档品名）。"},
        "mat_catalog_value_uniq": {"values": "属性值与已有记录重复，请重新读取后修改。"},
        "mat_catalog_color_uniq": {"values": "该普通颜色已关联当前品名，请保留已有记录。"},
        "mat_catalog_unit_uniq": {"units": "可用单位与已有记录重复，请重新读取后修改。"},
        "material_catalog_attribute_value_pkey": {"values": "属性标识已被占用，请重新读取后修改。"},
        "material_catalog_allowed_unit_pkey": {"units": "单位标识已被占用，请重新读取后修改。"},
    }
    if constraint in errors:
        raise ValidationError(errors[constraint]) from exc
    raise exc


def _validate_settings(catalog, data):
    if MaterialCatalog.objects.filter(category_key=catalog.category_key, name=data["name"]).exclude(pk=catalog.pk).exists():
        raise ValidationError({"name": "该类别下已存在相同品名（含已归档品名）。"})
    if data["spray_enabled"] and not TEMPLATES[catalog.template_key]["supports_spray"]:
        raise ValidationError({"spray_enabled": "该品名不支持半成品属性。"})
    for field in ("base_warehouse_id", "semi_warehouse_id"):
        warehouse_id = data[field]
        if warehouse_id is not None and not Warehouse.objects.filter(pk=warehouse_id, status="ACTIVE").exists():
            raise ValidationError({field: "请选择现有且启用的仓库。"})
        if field == "semi_warehouse_id" and warehouse_id and catalog.category_key not in {"TUBE", "HARDWARE", "FABRIC_SEMI"}:
            raise ValidationError({field: "该类别没有现有半成品入口。"})


def _draft_fields(catalog, scope):
    if scope == MaterialScope.BASE:
        return TEMPLATES[catalog.template_key]["fields"]
    # 开关只决定是否提供半成品入口，关闭时仍可完整保存已经编辑的配置。
    if scope == MaterialScope.SPRAY and TEMPLATES[catalog.template_key]["supports_spray"]:
        return SPRAY_FIELDS
    raise ValidationError({"scope": "该品名模板不支持所选属性组。"})


def _validate_ids(values, units, existing_values, existing_units):
    ids = [row["id"] for row in [*values, *units]]
    if len(ids) != len(set(ids)):
        raise ValidationError({"values": "属性与单位的标识不可重复。"})
    value_ids = {row["id"] for row in values}
    unit_ids = {row["id"] for row in units}
    if (MaterialAttributeValue.objects.filter(pk__in=value_ids - existing_values.keys()).exists()
            or MaterialAllowedUnit.objects.filter(pk__in=value_ids).exists()):
        raise ValidationError({"values": "属性标识不属于当前品名，或已被其他记录占用。"})
    if (MaterialAllowedUnit.objects.filter(pk__in=unit_ids - existing_units.keys()).exists()
            or MaterialAttributeValue.objects.filter(pk__in=unit_ids).exists()):
        raise ValidationError({"units": "单位标识不属于当前品名，或已被其他记录占用。"})


def _value_key(scope, field_key, value, parent_id, product_color_id=None):
    return scope, field_key, ("color", str(product_color_id)) if product_color_id else ("text", value), parent_id


def _plan_values(catalog, rows, existing):
    existing_by_value = {
        _value_key(row.scope, row.field_key, row.value, row.parent_id, row.product_color_id): row for row in existing.values()
    }
    planned = []
    canonical_ids = {}
    planned_values = set()
    shapes = set()
    # 先规范形状标识，尺寸才能引用同次新增或恢复的形状。
    for row in sorted(rows, key=lambda item: item["field_key"] == "section_size"):
        fields = _draft_fields(catalog, row["scope"])
        definition = next((field for field in fields if field["key"] == row["field_key"] and field["kind"] != "unit"), None)
        if definition is None:
            raise ValidationError({"values": "属性不在当前模板及属性组的固定名单中。"})
        parent_id = canonical_ids.get(row["parent_id"], row["parent_id"])
        if definition["kind"] == "dimension":
            if parent_id not in shapes:
                raise ValidationError({"values": "截面尺寸必须引用本次草稿中保留的有效截面形状。"})
        elif parent_id is not None:
            raise ValidationError({"values": "只有截面尺寸可以关联截面形状。"})
        product_color_id = row.get("product_color_id")
        key = _value_key(row["scope"], row["field_key"], row["value"], parent_id, product_color_id)
        if key in planned_values:
            raise ValidationError({"values": "同一属性组和形状下不可重复填写相同属性值。"})
        option = existing.get(row["id"])
        duplicate = existing_by_value.get(key)
        if option is not None:
            if (option.scope, option.field_key, option.parent_id) != (row["scope"], row["field_key"], parent_id):
                raise ValidationError({"values": "已有属性不可更换属性组、字段或所属形状。"})
            if option.archived_at is not None and (option.value != row["value"] or option.product_color_id != product_color_id):
                raise ValidationError({"values": "已移除属性只能按原值恢复，不能篡改历史记录。"})
            if duplicate is not None and duplicate.pk != option.pk:
                raise ValidationError({"values": "属性值已存在（含已移除记录），请使用其他值。"})
        elif duplicate is not None:
            if duplicate.archived_at is None:
                raise ValidationError({"values": "属性值已存在，请保留已有属性的标识。"})
            option = duplicate
        else:
            option = MaterialAttributeValue(
                id=row["id"], catalog=catalog, scope=row["scope"], field_key=row["field_key"],
                value=row["value"], parent_id=parent_id, product_color_id=product_color_id,
            )
        canonical_ids[row["id"]] = option.pk
        if row["scope"] == MaterialScope.BASE and row["field_key"] == "shape":
            shapes.add(option.pk)
        planned_values.add(key)
        planned.append((option, row["value"], product_color_id))
    return planned


def _plan_units(catalog, rows, existing):
    existing_by_unit = {(row.scope, row.unit_id): row for row in existing.values()}
    planned = []
    planned_units = set()
    for row in rows:
        _draft_fields(catalog, row["scope"])
        option = existing.get(row["id"])
        if option is not None:
            if option.scope != row["scope"]:
                raise ValidationError({"units": "已有可用单位不可更换属性组。"})
            if option.archived_at is not None and option.unit.unit_name != row["unit_name"]:
                raise ValidationError({"units": "已移除单位只能按原名称恢复，不能篡改历史记录。"})
        # 只变更本品名的单位关联；不修改共享 ProductionUnit 的名称。
        unit = option.unit if option is not None and option.archived_at is None and option.unit.unit_name == row["unit_name"] else resolve_unit({"unit_name": row["unit_name"]})
        key = row["scope"], unit.pk
        if key in planned_units:
            raise ValidationError({"units": "同一属性组不可重复填写相同可用单位。"})
        duplicate = existing_by_unit.get(key)
        if option is not None:
            if duplicate is not None and duplicate.pk != option.pk:
                raise ValidationError({"units": "可用单位已存在（含已移除记录），请选择其他单位。"})
        elif duplicate is not None:
            if duplicate.archived_at is None:
                raise ValidationError({"units": "可用单位已存在，请保留已有单位的标识。"})
            option = duplicate
        else:
            option = MaterialAllowedUnit(id=row["id"], catalog=catalog, scope=row["scope"], unit=unit)
        planned_units.add(key)
        planned.append((option, unit))
    return planned


def _apply_draft(catalog, data, request):
    existing_values = {row.pk: row for row in catalog.attribute_values.select_for_update()}
    existing_units = {row.pk: row for row in catalog.allowed_units.select_for_update(of=("self",)).select_related("unit")}
    _validate_ids(data["values"], data["units"], existing_values, existing_units)
    catalog.name = data["name"]
    ensure_public_draft(catalog, data, request=request)
    values = _plan_values(catalog, data["values"], existing_values)
    units = _plan_units(catalog, data["units"], existing_units)
    kept_values = {option.pk for option, _, _ in values}
    kept_units = {option.pk for option, _ in units}
    # 完整草稿中省略的项表示用户移除；开关状态本身不删除或恢复任何子项。
    for option in sorted(existing_values.values(), key=lambda item: item.parent_id is None):
        if option.pk not in kept_values and option.archived_at is None:
            _archive(option, request)
    for option in existing_units.values():
        if option.pk not in kept_units and option.archived_at is None:
            _archive(option, request)
    for option, value, product_color_id in values:
        if option._state.adding:
            option.save(force_insert=True)
        elif option.archived_at is not None:
            _restore(option)
        elif option.value != value or option.product_color_id != product_color_id:
            option.value = value
            option.product_color_id = product_color_id
            option.save(update_fields=["value", "product_color", "updated_at"])
    for option, unit in units:
        if option._state.adding:
            option.save(force_insert=True)
        elif option.archived_at is not None:
            _restore(option)
        elif option.unit_id != unit.pk:
            option.unit = unit
            option.save(update_fields=["unit", "updated_at"])
    for field in ("name", "spray_enabled", "base_warehouse_id", "semi_warehouse_id"):
        setattr(catalog, field, data[field])


def create_catalog(*, data, request):
    draft = {
        "spray_enabled": False, "base_warehouse_id": None, "semi_warehouse_id": None, "units": [], **data,
    }
    catalog = MaterialCatalog(category_key=draft["category_key"], template_key=draft["template_key"], name=draft["name"])
    if "values" not in draft:
        # 简单旧调用继续获得默认颜色；显式提交 values=[] 表示不添加默认项。
        draft["values"] = []
        scopes = [MaterialScope.BASE, MaterialScope.SPRAY] if draft["spray_enabled"] else [MaterialScope.BASE]
        for scope in scopes:
            if any(field["key"] == "color" for field in _draft_fields(catalog, scope)):
                draft["values"].append({
                    "id": uuid4(), "scope": scope, "field_key": "color", "value": "无颜色", "parent_id": None,
                })
    try:
        with transaction.atomic():
            _validate_settings(catalog, draft)
            catalog.save(force_insert=True)
            _apply_draft(catalog, draft, request)
            return _finish_change(catalog, None, "CREATED", request)
    except IntegrityError as exc:
        _raise_write_conflict(exc)


def save_catalog(*, catalog_id, data, request):
    try:
        with transaction.atomic():
            catalog = _locked_catalog(catalog_id, request)
            _validate_settings(catalog, data)
            before = catalog_detail(catalog)
            _apply_draft(catalog, data, request)
            return _finish_change(catalog, before, "CATALOG_SAVED", request)
    except IntegrityError as exc:
        _raise_write_conflict(exc)


@transaction.atomic
def archive_catalog(*, catalog_id, request):
    catalog = _locked_catalog(catalog_id, request)
    before = catalog_detail(catalog)
    catalog.archived_at = timezone.now()
    catalog.archived_by_employee = getattr(request, "employee", None)
    catalog.archive_reason = "从原料管理归档品名"
    catalog.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
    write_audit_log(
        object_type="MATERIAL_CATALOG", object_id=catalog.pk, action="ARCHIVED",
        actor_employee=getattr(request, "employee", None), before_data=before,
        after_data={**catalog_detail(catalog), "archived_at": catalog.archived_at.isoformat(), "archive_reason": catalog.archive_reason},
        request=request,
    )
