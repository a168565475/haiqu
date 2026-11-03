"""BOM新目录选料：预检只读，补录与BOM写入共用外层事务。"""
from copy import deepcopy

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.material_catalog.definitions import TEMPLATES
from apps.material_catalog.colors import COLOR_FIELDS, color_identity, color_metadata, unchanged_snapshot_color, uses_product_color_identity
from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
from apps.material_catalog.public_configuration import ensure_public_value, require_public_value
from apps.material_catalog.selectors import catalog_detail
from apps.material_catalog.services import _finish_change, _restore, resolve_unit
from apps.material_catalog.snapshots import build_material_snapshot
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft


SECTION_CATEGORIES = {
    "管材类": "TUBE", "五金件": "HARDWARE", "塑料件类": "PLASTIC",
    "辅料类": "AUXILIARY", "面料类": "FABRIC", "包材类": "PACKAGING", "裁剪明细": "FABRIC_SEMI",
}
LEGACY_SOURCE_FIELDS = (
    "source_inventory_material_id", "source_raw_material_id", "source_packaging_material_id",
    "source_cutting_material_id", "source_accessory_product_name_id", "source_accessory_specification_id",
    "source_accessory_color_id", "source_accessory_material_id", "source_fabric_material_id",
    "source_fabric_specification_id", "source_fabric_width_id", "source_product_color_id",
)


def uses_catalog(data, old=None):
    return bool(data.get("material_catalog_id") or data.get("material_selection") or (old and old.material_catalog_id))


def validate_catalog_input(data, old=None):
    if any(data.get(key) for key in (*LEGACY_SOURCE_FIELDS, "pending_raw_material")):
        raise ValidationError("新原料选择不能同时提交旧原料或生产维护来源。")
    if "material_catalog_id" in data and not data["material_catalog_id"]:
        raise ValidationError("新原料关联不能清空，请重新选择品名。")
    if data.get("material_selection") and not data.get("material_catalog_id"):
        raise ValidationError("请选择确定的新原料品名ID。")
    if not data.get("material_selection") and not (old and old.material_catalog_id and
            str(data.get("material_catalog_id", old.material_catalog_id)) == str(old.material_catalog_id)):
        raise ValidationError("新增或更换品名必须同时选择具体属性及单位。")


def required_fields(template, attributes, *, require_tube_length=True):
    fixed = {
        "TUBE": ("material", "shape", "section_size", "thickness") + (("length",) if require_tube_length else ()),
        "FABRIC": ("material", "fabric_spec", "width", "color"),
    }
    if template in fixed:
        return fixed[template]
    # 沿既有入口要求具体规格；多模板的尺寸/型号不强行映射为管材规格。
    identities = {
        "HARDWARE": ("specification", "size", "thread"), "PLASTIC": ("specification", "model", "size"),
        "CARTON": ("size", "model"), "BAG": ("size", "model"),
        "PACKAGING_GENERAL": ("specification", "model"), "TAPE": ("specification", "width"),
        "COTTON": ("specification", "thickness", "width"), "AUXILIARY_GENERAL": ("specification",),
        "FABRIC_SEMI": ("size", "specification", "model"),
    }
    identity = next((key for key in identities[template] if attributes.get(key, "").strip() not in {"", "/", "-", "—"}), None)
    if not identity:
        raise ValidationError({"attributes": "请选择实际规格、尺寸或型号，不能仅保存品名。"})
    # 旧原料合同的material允许为空；不把新目录所有模板的材质一律升级为必填。
    return (identity,)


def _craft_input(selection, category):
    state = selection["processing_state"]
    if category != "FABRIC_SEMI":
        if state != "RAW" or selection.get("completed_craft") or selection.get("semi_kind"):
            raise ValidationError({"processing_state": "该BOM分区保存基础用料；加工结果由相应加工来源创建。"})
        return None, None
    if state != "PROCESSED" or selection.get("semi_kind") != "CUTTING":
        raise ValidationError({"processing_state": "裁片须选择确定的加工结果及既有完成工艺。"})
    selected = selection.get("completed_craft") or {}
    craft = Craft.objects.filter(pk=selected.get("id"), status="ACTIVE").first()
    if craft is None:
        raise ValidationError({"completed_craft": "请选择有效的既有裁片工艺。"})
    from apps.inventory.public_stock_identity import _craft
    actual = _craft(craft)
    if actual != selected or actual["code"] not in {"CUTTING", "SEWING", "EMBROIDERY", "SCREEN_PRINTING"}:
        raise ValidationError({"completed_craft": "工艺ID、类型、代码或裁片种类不匹配。"})
    return actual, "CUTTING"


def apply_catalog_selection(line, data, *, old, request, persist, versions, allow_public_creation=True, require_tube_length=True, require_fabric_meter=False, inherit_fabric_source=False, selection_permission="material_catalog.view_materialcatalog"):
    validate_catalog_input(data, old)
    inherited = {}
    if inherit_fabric_source and line.section.title.strip() == "裁剪明细":
        from .material_flow_bom import cutting_fabric_attributes, inherit_cutting_fabric_attributes, validate_cutting_specification
        source = line.fabric_source_line
        if source is None:
            raise ValidationError({"fabric_source_line_id": "请先选择当前 BOM 中的来源面料。"})
        validate_cutting_specification(source.specification, line.line_number)
        inherited = cutting_fabric_attributes(source)
        selected = deepcopy(data.get("material_selection") or (old.material_selection_snapshot if old else {}))
        attrs = {key: value for key, value in selected.get("attributes", {}).items()
                 if key not in {"material", "width", "color", "fabric_spec", "specification", "size", "model", "process"}}
        attrs.update(inherited)
        selected["attributes"] = attrs
        source_snapshot = source.material_selection_snapshot or {}
        for key in COLOR_FIELDS:
            selected.pop(key, None)
        if source_snapshot.get("product_color_id"):
            selected.update({key: source_snapshot.get(key, "") for key in COLOR_FIELDS})
        data = {**data, "material_selection": selected}
    selection = data.get("material_selection")
    previous = old.material_selection_snapshot if old and old.material_catalog_id else None
    catalog_id = data.get("material_catalog_id", old.material_catalog_id if old else None)
    result_field = "tube_coating_color" if line.section.section_type == "PROFILE" else "powder_coating_color"
    result_changed = result_field in data and data[result_field] != ((old.raw_values or {}).get(result_field, "") if old else "")
    unchanged = previous and str(catalog_id) == str(old.material_catalog_id) and (not selection or (
        selection.get("attributes") == previous["attributes"] and
        str(selection.get("unit_id")) == previous["unit_id"] and
        selection.get("scope") == previous["scope"] and
        selection.get("processing_state") == previous["processing_state"] and
        selection.get("completed_craft") == previous["completed_craft"] and
        selection.get("semi_kind") == previous["semi_kind"] and
        unchanged_snapshot_color(selection, previous))) and not result_changed
    if unchanged:
        snapshot = deepcopy(previous)
    else:
        if not selection:
            raise ValidationError({"material_selection": "更换原料或半成品颜色时，请重新选择原料属性及单位。"})
        if not request.user.has_perm(selection_permission):
            raise PermissionDenied("当前账号没有选择此原料的权限。")
        query = MaterialCatalog.objects.filter(pk=catalog_id, archived_at__isnull=True)
        catalog = (query.select_for_update() if persist else query).first()
        if catalog is None or catalog.category_key != SECTION_CATEGORIES.get(line.section.title.strip()):
            raise ValidationError({"material_catalog_id": "品名不存在、已归档或不属于当前分区。"})
        version = selection.get("catalog_version")
        if not version:
            raise PreconditionRequired("请选择带内容版本的原料品名。")
        original_version = versions.setdefault(catalog.pk, catalog.updated_at.isoformat())
        if version != original_version:
            raise PreconditionFailed("原料品名选项已变化，请刷新该品名后重选；BOM草稿仍保留。")
        attrs = selection["attributes"]
        required = required_fields(catalog.template_key, attrs, require_tube_length=require_tube_length)
        scope = selection["scope"]
        if scope != "BASE":
            raise ValidationError({"scope": "BOM基础用料选择基础属性，不能把半成品属性当作完成工艺。"})
        craft, semi_kind = _craft_input(selection, catalog.category_key)
        fields = {field["key"] for field in TEMPLATES[catalog.template_key]["fields"] if field["kind"] != "unit"}
        if not attrs or set(attrs) - fields or any(not value.strip() or value.strip() in {"/", "-", "—"} for value in attrs.values()):
            raise ValidationError({"attributes": "属性必须属于当前模板且为实际有效值。"})
        if any(not attrs.get(key) for key in required):
            raise ValidationError({"attributes": "缺少具体材料必要属性：" + "、".join(required)})
        ordinary_color = bool(attrs.get("color")) and uses_product_color_identity(catalog, scope)
        if not ordinary_color and not inherited and any(selection.get(key) for key in COLOR_FIELDS):
            raise ValidationError({"product_color_id": "色卡、色号和普通颜色标识仅适用于面料基础颜色。"})
        before = catalog_detail(catalog) if persist else None
        selected_unit_name = selection.get("unit_name", "")
        if selection.get("unit_id"):
            selected_unit_name = ProductionUnit.objects.filter(pk=selection["unit_id"]).values_list("unit_name", flat=True).first() or ""

        def check_public_value(scope, key, value, *, parent_value=None):
            # 来自本次 BOM 已校验的来源面料，不要求用户再维护一份裁片颜色/规格公共候选。
            if scope == "BASE" and key in inherited:
                return None
            color = selection if scope == "BASE" and key == "color" and ordinary_color else None
            if allow_public_creation:
                return ensure_public_value(catalog, scope, key, value, parent_value=parent_value,
                                           unit_name=selected_unit_name, request=request, persist=persist, color=color)
            return require_public_value(catalog, scope, key, value, parent_value=parent_value, lock=persist, color=color)

        missing = []
        shape = None
        selected_color = None
        for key in sorted(attrs, key=lambda key: (key != "shape", key == "section_size", key)):
            value = attrs[key].strip()
            if key == "section_size" and not attrs.get("shape"):
                raise ValidationError({"attributes": "截面尺寸必须同时选择本品名的形状。"})
            public = check_public_value("BASE", key, value, parent_value=attrs.get("shape"))
            lookup = dict(catalog=catalog, scope="BASE", field_key=key, value=value)
            if key == "color" and ordinary_color:
                selected_color = public
                lookup["product_color_id"] = public.pk if public else None
                if public:
                    lookup.pop("value")
            if key == "section_size":
                lookup["parent"] = shape
            option = MaterialAttributeValue.objects.filter(**lookup).first() if key != "section_size" or shape else None
            if option is None or option.archived_at is not None:
                missing.append(key)
                # 公共值已通过校验；记录当前品名使用值属于正常选料，不能额外要求维护权限。
                if persist:
                    if option:
                        _restore(option)
                    else:
                        option = MaterialAttributeValue.objects.create(**{**lookup, "value": value})
            if key == "shape":
                shape = option
        result_color = str(data.get(result_field, "")).strip()
        if result_color and catalog.category_key in {"TUBE", "HARDWARE"}:
            if not catalog.spray_enabled:
                raise ValidationError({result_field: "请先在当前品名维护中启用半成品属性。"})
            check_public_value("SPRAY", "color", result_color)
            result_option = catalog.attribute_values.filter(scope="SPRAY", field_key="color", value=result_color, parent=None).first()
            if result_option is None or result_option.archived_at is not None:
                missing.append("result_color")
                if persist:
                    if result_option:
                        _restore(result_option)
                    else:
                        MaterialAttributeValue.objects.create(catalog=catalog, scope="SPRAY", field_key="color", value=result_color)
        unit_data = {key: selection[key] for key in ("unit_id", "unit_name") if selection.get(key)}
        unit_query = ProductionUnit.objects.filter(**({"pk": unit_data["unit_id"]} if "unit_id" in unit_data else {"unit_name": unit_data["unit_name"]}))
        unit = unit_query.first()
        if unit is None and "unit_id" in unit_data:
            raise ValidationError({"unit_id": "所选单位不存在。"})
        if unit and (unit.status != "ACTIVE" or unit.archived_at is not None):
            raise ValidationError({"unit_id": "所选单位已停用或归档。"})
        check_public_value(scope, "unit", unit.unit_name if unit else unit_data["unit_name"])
        allowed = catalog.allowed_units.filter(scope=scope, unit=unit).first() if unit else None
        if allowed is None or allowed.archived_at is not None:
            missing.append("unit")
            if persist:
                unit = resolve_unit(unit_data)
                if allowed:
                    _restore(allowed)
                else:
                    MaterialAllowedUnit.objects.create(catalog=catalog, scope=scope, unit=unit)
        if persist:
            if missing:
                _finish_change(catalog, before, "BOM_OPTIONS_ADDED", request)
            snapshot = build_material_snapshot(catalog=catalog, scope=scope, processing_state=selection["processing_state"],
                attributes=attrs, unit_id=unit.pk, required_fields=required, completed_craft=craft, semi_kind=semi_kind,
                product_color=selected_color)
        else:
            # 预检仅投影输入参与现有计算；不向数据库补录，也不伪造已保存的版本/单位ID。
            snapshot = {"catalog_id": str(catalog.pk), "name": catalog.name, "category_key": catalog.category_key,
                        "attributes": attrs, "unit_name": unit.unit_name if unit else unit_data["unit_name"],
                        "unit_id": str(unit.pk) if unit else None, "processing_state": selection["processing_state"],
                        "processing_stage": craft["code"] if craft else "RAW", "completed_craft": craft, "semi_kind": semi_kind}
            if ordinary_color:
                snapshot.update(color_metadata(selected_color) if selected_color else
                                {"product_color_id": None, **color_identity(attrs["color"], selection)})
    if snapshot["category_key"] != SECTION_CATEGORIES.get(line.section.title.strip()):
        raise ValidationError({"material_catalog_id": "已保存材料的目录类别不能移入不匹配的BOM分区。"})
    line.material_catalog_id = catalog_id
    line.material_selection_snapshot = snapshot
    if not unchanged and line.section.section_type == "PROFILE" and snapshot["unit_name"] != "根":
        raise ValidationError({"unit_id": "BOM管材沿原流程使用根，需求支数及采购米数仍由原切割参数计算。"})
    if require_fabric_meter and not unchanged and line.section.title.strip() == "面料类" and snapshot["unit_name"] != "米":
        raise ValidationError({"unit_id": "BOM面料用料单位固定为米，请重新选择米。"})
    if data.get("material_quantity") is not None and (not old or data["material_quantity"] != old.material_quantity):
        raise ValidationError({"material_quantity": "BOM沿原用量流程，不再接收独立材料总量。"})
    # 兼容字段不再参与取量；未重新选料的历史内容原样保留，不做数据换算或清洗。
    line.material_quantity = old.material_quantity if unchanged else None
    attrs = snapshot["attributes"]
    line.part_name, line.material, line.unit = snapshot["name"], attrs.get("material", ""), snapshot["unit_name"]
    line.category = line.section.title.strip()
    line.raw_material = ""
    line.specification = " / ".join(attrs[key] for key in ("fabric_spec", "specification", "section_size", "size", "model", "width") if attrs.get(key))
    for key in LEGACY_SOURCE_FIELDS:
        line.raw_values.pop(key, None)
    line.raw_values.pop("pipe_source_sync_pending", None)
    line.raw_values.pop("fabric_source_sync_pending", None)
    for target, key in {"tube_shape": "shape", "tube_diameter": "section_size", "tube_thickness": "thickness",
            "fabric_width": "width", "fabric_color_name": "color", "hardware_color": "color", "plastic_color": "color",
            "accessory_color": "color", "packaging_color": "color", "cutting_color": "color", "hardware_flow_unit": "flow_unit"}.items():
        line.raw_values[target] = attrs.get(key, "")
    if not unchanged:
        line.raw_values["fabric_color_card"] = snapshot.get("color_card", "")
        line.raw_values["fabric_color_code"] = snapshot.get("color_code", "")
    if inherited:
        line.raw_values.pop("cutting_category", None)
        inherit_cutting_fabric_attributes(line)
