"""消费人工确认的原料规范数据，不读取或推断源表业务含义。"""

from collections.abc import Mapping

from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.core.audit import write_audit_log
from apps.reference_data.models import ProductionUnit

from .api.serializers import (
    AttributeValueCreateSerializer,
    CatalogCreateSerializer,
    CatalogPatchSerializer,
    StrictSerializer,
)
from .definitions import SPRAY_FIELDS, TEMPLATES
from .models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog, MaterialScope
from .selectors import catalog_detail


class ImportSourceSerializer(StrictSerializer):
    filename = serializers.CharField(max_length=255)
    sha256 = serializers.RegexField(r"\A[0-9a-fA-F]{64}\Z")

    def validate_filename(self, value):
        if value in {".", ".."} or any(character in value for character in ("/", "\\", ":")):
            raise ValidationError("来源必须填写文件名，不能填写路径。")
        return value

    def validate_sha256(self, value):
        return value.lower()


class ImportValueSerializer(AttributeValueCreateSerializer):
    parent_id = None
    parent_value = serializers.CharField(max_length=300, required=False)


class ImportUnitSerializer(StrictSerializer):
    scope = serializers.ChoiceField(choices=MaterialScope.choices)
    unit_name = serializers.CharField(max_length=80)


class ImportCatalogSerializer(CatalogCreateSerializer):
    spray_enabled = serializers.BooleanField()
    values = ImportValueSerializer(many=True)
    units = ImportUnitSerializer(many=True)

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and "spray_enabled" in data:
            switch = CatalogPatchSerializer(data={"spray_enabled": data["spray_enabled"]})
            switch.is_valid(raise_exception=True)
        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["spray_enabled"] and not TEMPLATES[attrs["template_key"]]["supports_spray"]:
            raise ValidationError({"spray_enabled": "该模板不支持喷塑属性。"})
        return attrs


class ImportPayloadSerializer(StrictSerializer):
    version = serializers.IntegerField()
    source = ImportSourceSerializer()
    catalogs = ImportCatalogSerializer(many=True, allow_empty=False)

    def validate_version(self, value):
        if type(self.initial_data["version"]) is not int or value != 1:
            raise ValidationError("只接受整数版本号 1。")
        return value


def _value_key(value):
    return value["scope"], value["field_key"], value["value"], value.get("parent_value")


def _merge_catalogs(rows):
    merged = {}
    for row in rows:
        key = row["category_key"], row["name"]
        if key not in merged:
            merged[key] = {**row, "values": {}, "units": {}}
        target = merged[key]
        if target["template_key"] != row["template_key"] or target["spray_enabled"] != row["spray_enabled"]:
            raise ValidationError({"catalogs": f"{row['name']} 的重复记录存在模板或喷塑开关冲突。"})
        target["values"].update((_value_key(value), value) for value in row["values"])
        target["units"].update(((unit["scope"], unit["unit_name"]), unit) for unit in row["units"])
    return [merged[key] for key in sorted(merged)]


def _fail(row, field, message):
    raise ValidationError({"catalogs": {f"{row['category_key']}/{row['name']}": {field: message}}})


def _prepare_catalog(row, catalog, units):
    if catalog is not None:
        if catalog.archived_at is not None:
            _fail(row, "name", "同名档案已归档，导入不会恢复。")
        if catalog.template_key != row["template_key"]:
            _fail(row, "template_key", "同名档案使用不同模板，不能合并。")
    enabled = row["spray_enabled"] or bool(catalog and catalog.spray_enabled)
    existing_values = {
        (value.scope, value.field_key, value.value, value.parent.value if value.parent else None): value
        for value in catalog.attribute_values.select_related("parent").all()
    } if catalog else {}
    existing_units = {
        (unit.scope, unit.unit_id): unit for unit in catalog.allowed_units.all()
    } if catalog else {}
    desired_values = dict(row["values"])
    fields = {field["key"]: field for field in TEMPLATES[row["template_key"]]["fields"]}
    # 与页面新建规则一致；已有档案的默认颜色不补回，避免恢复用户删除的选项。
    default_scopes = []
    if catalog is None and "color" in fields:
        default_scopes.append(MaterialScope.BASE)
    if enabled and (catalog is None or not catalog.spray_enabled) and not any(
        key[0] == MaterialScope.SPRAY for key in existing_values
    ):
        default_scopes.append(MaterialScope.SPRAY)
    for scope in default_scopes:
        value = {"scope": scope, "field_key": "color", "value": "无颜色"}
        desired_values.setdefault(_value_key(value), value)

    added_values = []
    for key, value in desired_values.items():
        if value["scope"] == MaterialScope.BASE:
            available_fields = fields
        elif enabled:
            available_fields = {field["key"]: field for field in SPRAY_FIELDS}
        else:
            available_fields = {}
        definition = available_fields.get(value["field_key"])
        if definition is None or definition["kind"] == "unit":
            _fail(row, "values", f"{value['scope']}/{value['field_key']} 不属于已启用属性组的固定属性。")
        parent_value = value.get("parent_value")
        if definition["kind"] == "dimension":
            parent_key = (MaterialScope.BASE, "shape", parent_value, None)
            parent = existing_values.get(parent_key)
            if not parent_value or (parent_key not in desired_values and (parent is None or parent.archived_at is not None)):
                _fail(row, "values", f"尺寸 {value['value']} 缺少本档案有效的截面形状。")
        elif parent_value is not None:
            _fail(row, "values", "只有截面尺寸可以填写 parent_value。")
        existing = existing_values.get(key)
        if existing is not None and existing.archived_at is not None:
            _fail(row, "values", f"{value['field_key']}：{value['value']} 已归档，导入不会恢复。")
        if existing is None:
            added_values.append(value)

    added_units = []
    for value in row["units"].values():
        if value["scope"] == MaterialScope.SPRAY and not enabled:
            _fail(row, "units", "未启用喷塑，不能导入喷塑单位。")
        unit = units.get(value["unit_name"])
        if unit is None or unit.status != "ACTIVE" or unit.archived_at is not None:
            _fail(row, "units", f"单位 {value['unit_name']} 不存在、已停用或已归档。")
        existing = existing_units.get((value["scope"], unit.pk))
        if existing is not None and existing.archived_at is not None:
            _fail(row, "units", f"{value['scope']} 的单位 {unit.unit_name} 已归档，导入不会恢复。")
        if existing is None:
            added_units.append({"scope": value["scope"], "unit": unit})
    return {
        "catalog": catalog, "row": row, "spray_enabled": enabled,
        "values": added_values, "units": added_units, "existing_values": existing_values,
        "changed": catalog is None or bool(added_values or added_units) or catalog.spray_enabled != enabled,
    }


def _apply_catalog(plan, source):
    catalog = plan["catalog"]
    before = catalog_detail(catalog) if catalog else {}
    if catalog is None:
        catalog = MaterialCatalog.objects.create(
            category_key=plan["row"]["category_key"], template_key=plan["row"]["template_key"],
            name=plan["row"]["name"], spray_enabled=plan["spray_enabled"],
        )
    values = dict(plan["existing_values"])
    ordinary_values = []
    dimensions = []
    for value in plan["values"]:
        if value.get("parent_value") is not None:
            dimensions.append(value)
            continue
        option = MaterialAttributeValue(catalog=catalog, scope=value["scope"], field_key=value["field_key"], value=value["value"])
        ordinary_values.append(option)
        values[_value_key(value)] = option
    MaterialAttributeValue.objects.bulk_create(ordinary_values)
    MaterialAttributeValue.objects.bulk_create([
        MaterialAttributeValue(
            catalog=catalog, scope=value["scope"], field_key=value["field_key"], value=value["value"],
            parent=values[(MaterialScope.BASE, "shape", value["parent_value"], None)],
        ) for value in dimensions
    ])
    MaterialAllowedUnit.objects.bulk_create([MaterialAllowedUnit(catalog=catalog, **unit) for unit in plan["units"]])
    catalog.spray_enabled = plan["spray_enabled"]
    catalog.save(update_fields=["spray_enabled", "updated_at"])
    after = catalog_detail(catalog)
    after.update(import_source=source, import_method="AUTHORIZED_MANAGEMENT_COMMAND")
    write_audit_log(
        object_type="MATERIAL_CATALOG", object_id=catalog.pk, action="IMPORTED",
        actor_employee=None, before_data=before, after_data=after,
    )


def import_catalog_payload(payload, *, apply=False):
    """整批预检后追加；缺省 dry-run，不恢复归档记录或覆盖已有属性。"""
    serializer = ImportPayloadSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    rows = _merge_catalogs(data["catalogs"])
    unit_names = {unit["unit_name"] for row in rows for unit in row["units"].values()}
    try:
        with transaction.atomic():
            catalogs = []
            # 与页面写入保持先锁主档的顺序；全部预检通过后才写任何业务记录。
            for row in rows:
                query = MaterialCatalog.objects.filter(category_key=row["category_key"], name=row["name"])
                if apply:
                    query = query.select_for_update()
                catalogs.append((row, query.first()))
            unit_query = ProductionUnit.objects.filter(unit_name__in=unit_names).order_by("pk")
            if apply:
                # 阻止单位状态变更，同时允许其他事务新增对此单位的外键引用。
                unit_query = unit_query.select_for_update(no_key=True)
            units = {unit.unit_name: unit for unit in unit_query}
            plans = [_prepare_catalog(row, catalog, units) for row, catalog in catalogs]
            result = {
                "mode": "apply" if apply else "dry-run", "source": data["source"],
                "catalogs_total": len(plans),
                "catalogs_created": sum(plan["catalog"] is None for plan in plans),
                "catalogs_changed": sum(plan["catalog"] is not None and plan["changed"] for plan in plans),
                "catalogs_unchanged": sum(not plan["changed"] for plan in plans),
                "values_created": sum(len(plan["values"]) for plan in plans),
                "units_created": sum(len(plan["units"]) for plan in plans),
            }
            if apply:
                for plan in plans:
                    if plan["changed"]:
                        _apply_catalog(plan, data["source"])
            return result
    except IntegrityError as exc:
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) == "mat_catalog_category_name_uniq":
            raise ValidationError({"catalogs": "有同名档案被并发创建，本批次已回滚，请重新预检。"}) from exc
        raise
