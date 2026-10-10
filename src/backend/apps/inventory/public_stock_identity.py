"""按已确认 BOM 实物属性生成公共库存身份；不读取采购或回货批次。

调用方在交接时持久化返回值，回货时验证该冻结值。这里不会用最新 BOM
补齐历史快照。SHA256 用于索引及内容一致性校验，不替代来源单据权限校验。
"""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID

from .stock_services import InventoryStockValidationError


_EMPTY_VALUES = {"", "/", "—", "-", "--", "–", "N/A", "n/a", "NULL", "null"}
_IDENTITY_FIELDS = {
    "stock_kind", "identity_key", "identity_snapshot", "raw_material_id",
    "raw_bar_length_m", "unit_id",
}
_COMMON_FIELDS = {"schema_version", "stock_kind", "unit_id", "unit_name"}
_SEMI_FIELDS = {
    "semi_kind", "category", "part_name", "material", "color", "completed_craft",
}
_PIPE_FIELDS = {"tube_shape", "tube_diameter", "tube_thickness", "cutting_length_mm", "hardness"}
_CUTTING_FIELDS = {"specification", "pieces_per_set", "fabric"}
_HARDWARE_FIELDS = {"specification", "thickness"}


def _invalid(field, message, *, code="PUBLIC_STOCK_IDENTITY_INVALID"):
    raise InventoryStockValidationError(
        {field: message}, code=code, meta={"field": field},
    )


def _text(value, field, *, required=True):
    if value is None:
        value = ""
    if not isinstance(value, str):
        _invalid(field, "属性必须是明确的文字，不能使用布尔值或复合数据。")
    value = value.strip()
    if value in _EMPTY_VALUES:
        if required:
            _invalid(field, "缺少确定的实物属性，空白和占位符不能合并库存。",
                     code="PUBLIC_STOCK_IDENTITY_INCOMPLETE")
        return ""
    if len(value) > 500:
        _invalid(field, "属性文字长度不能超过 500。")
    return value


def _uuid(value, field):
    if isinstance(value, bool):
        _invalid(field, "编号格式不正确。")
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        _invalid(field, "缺少有效的稳定编号。")


def _positive_decimal(value, field, *, places=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        _invalid(field, "数值必须是有限的正数，不接受布尔值或浮点数。")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        _invalid(field, "数值格式不正确。")
    if not number.is_finite() or number <= 0 or number.adjusted() > 17:
        _invalid(field, "数值必须是有限的正数，最多 18 位整数。")
    # 拒绝无意义超长精度，避免恶意小数造成巨大字符串。
    if number.as_tuple().exponent < -8:
        _invalid(field, "数值精度超出允许范围。")
    if places is not None and number != number.quantize(Decimal(1).scaleb(-places)):
        _invalid(field, f"最多允许 {places} 位小数，不自动舍入。")
    return number


def _number_text(value, field, *, places=None):
    number = _positive_decimal(value, field, places=places)
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _positive_integer(value, field):
    number = _positive_decimal(value, field, places=0)
    return int(number)


def _dimensions(value, field):
    text = _text(value, field)
    text = re.sub(r"\s+", "", text).replace("×", "*").replace("＊", "*")
    text = text.replace("x", "*").replace("X", "*")
    text = re.sub(r"^[ΦФφØ∅]", "", text)
    text = re.sub(r"(?:mm|毫米)$", "", text, flags=re.IGNORECASE)
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:\*\d+(?:\.\d+)?)*", text):
        _invalid(field, "尺寸需要明确的数字或数字乘积，不能猜测自由文字中的尺寸。")
    return "*".join(_number_text(part, field) for part in text.split("*"))


def _specification(value, field):
    text = _text(value, field)
    # 只统一明确的尺寸写法，不修改品名、材料、色号或维度顺序。
    if re.fullmatch(r"\s*[ΦФφØ∅]?\s*\d+(?:\.\d+)?(?:\s*[xX*×＊]\s*\d+(?:\.\d+)?)+(?:\s*(?:mm|毫米))?\s*", text, re.IGNORECASE):
        return _dimensions(text, field)
    return text


def _raw_values(line):
    values = getattr(line, "raw_values", None)
    if values is None:
        return {}
    if not isinstance(values, dict):
        _invalid("raw_values", "BOM 属性数据格式不正确。")
    return values


def _pipe_value(values, key, legacy_key):
    primary = _text(values.get(key), key, required=False)
    legacy = _text(values.get(legacy_key), key, required=False)
    if primary and legacy:
        normalize = (lambda value: "圆管" if value in {"Φ", "Ф", "φ"} else value) if key == "tube_shape" else (lambda value: _dimensions(value, key))
        if normalize(primary) != normalize(legacy):
            _invalid(key, "BOM 结构字段与历史字段冲突，不能自动选择。",
                     code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT")
    return _text(primary or legacy, key)


def profile_spray_color(values):
    """读取型材 BOM 的喷塑颜色。

    型材正式字段是 ``tube_coating_color``，它和五金的喷塑颜色使用同一
    颜色字典；为兼容外部导入或过渡数据，也接受 ``powder_coating_color``。
    两个字段同时有值且不一致时不能猜测，以免外发回货形成两个库存身份。
    """
    values = values if isinstance(values, dict) else {}
    powder = _text(values.get("powder_coating_color"), "powder_coating_color", required=False)
    legacy = _text(values.get("tube_coating_color"), "tube_coating_color", required=False)
    if powder and legacy and powder != legacy:
        _invalid(
            "powder_coating_color",
            "型材喷塑颜色与历史喷塑颜色字段冲突，不能自动选择。",
            code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT",
        )
    return legacy or powder


def _craft(craft):
    kind = _text(getattr(craft, "craft_type", None), "completed_craft.craft_type")
    if kind not in {"INTERNAL", "EXTERNAL"}:
        _invalid("completed_craft", "缺少确定的已完成工艺类型。")
    code = getattr(craft, "outsourcing_code" if kind == "EXTERNAL" else "plan_category", None)
    result = {
        "id": _uuid(getattr(craft, "pk", None), "completed_craft.id"),
        "craft_type": kind,
        "code": _text(code, "completed_craft.code"),
    }
    valid_codes = {"POWDER_COATING", "SCREEN_PRINTING", "CUTTING", "SEWING"} if kind == "EXTERNAL" else {"METAL", "CUTTING", "SEWING", "ASSEMBLY"}
    if result["code"] not in valid_codes:
        _invalid("completed_craft.code", "工艺编码与实际工艺类型不一致。")
    return result


def _make_identity(snapshot):
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "stock_kind": snapshot["stock_kind"],
        "identity_key": hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest(),
        "identity_snapshot": json.loads(snapshot_text),
        "raw_material_id": snapshot.get("raw_material_id"),
        "raw_bar_length_m": Decimal(snapshot["raw_bar_length_m"]) if snapshot["stock_kind"] == "RAW_PIPE" else None,
        "unit_id": snapshot["unit_id"],
    }


def build_pipe_stock_identity(*, raw_material, raw_bar_length_m, unit):
    """新口径原料管材：同一原料、原料长度、根单位构成公共身份。"""
    if (getattr(raw_material, "item_type", None) != "MATERIAL"
            or getattr(raw_material, "archived_at", None) is not None
            or getattr(getattr(raw_material, "category", None), "category_name", None) != "管材"):
        _invalid("raw_material", "必须是有效管材原料，旧米制库存不在这里转换。")
    unit_id = _uuid(getattr(unit, "pk", None), "unit_id")
    if (_text(getattr(unit, "unit_name", None), "unit_name") != "根"
            or _uuid(getattr(raw_material, "unit_id", None), "raw_material.unit_id") != unit_id):
        _invalid("unit", "新口径原料管材库存必须按原料档案的根单位记账。")
    return _make_identity({
        "schema_version": 1, "stock_kind": "RAW_PIPE", "unit_id": unit_id, "unit_name": "根",
        "raw_material_id": _uuid(getattr(raw_material, "pk", None), "raw_material_id"),
        "raw_bar_length_m": _number_text(raw_bar_length_m, "raw_bar_length_m", places=2),
    })


def _pipe_properties(line, values, craft, *, material_cache=None):
    internal = craft["code"] == "METAL" and craft["craft_type"] == "INTERNAL"
    if not internal and not (craft["code"] == "POWDER_COATING" and craft["craft_type"] == "EXTERNAL"):
        _invalid("completed_craft", "管材只支持厂内金工完成或外发喷塑完成。")
    # 厂内金工半成品尚未喷塑，不把原料颜色带入半成品身份；否则同一
    # 部位会因原料档案颜色变化被拆成不同库存。喷塑完成的外发身份
    # 则必须使用 BOM 型材的喷塑颜色。
    color = "" if internal else profile_spray_color(values)
    shape = _pipe_value(values, "tube_shape", "E")
    shape = "圆管" if shape in {"Φ", "Ф", "φ"} else shape
    diameter = _dimensions(_pipe_value(values, "tube_diameter", "F"), "tube_diameter")
    thickness = _number_text(_pipe_value(values, "tube_thickness", "G"), "tube_thickness")
    specification = _text(getattr(line, "specification", None), "specification", required=False)
    # 已有管材规格末尾可带原料长管长度；只核对截面和厚度，不将长管长度带入半成品。
    if specification:
        normalized = _specification(specification, "specification")
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\*\d+(?:\.\d+)?)+", normalized):
            expected = (diameter + "*" + thickness).split("*")
            actual = normalized.split("*")
            if len(actual) not in {len(expected), len(expected) + 1} or actual[:len(expected)] != expected:
                _invalid("specification", "管材规格中的截面/厚度与结构字段冲突。",
                         code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT")
    return {
        "tube_shape": shape, "tube_diameter": diameter, "tube_thickness": thickness,
        "cutting_length_mm": _positive_integer(getattr(line, "cutting_length_mm", None), "cutting_length_mm"),
        "hardness": _text(getattr(line, "hardness", None), "hardness", required=False),
        "color": _text(color, "color" if internal else "tube_coating_color", required=not internal),
    }


def _cutting_properties(line, values):
    source = getattr(line, "fabric_source_line", None)
    source_section = getattr(source, "section", None)
    if (source is None or getattr(source_section, "section_type", None) != "FABRIC"
            or _text(getattr(source_section, "title", None), "fabric_source_line.title", required=False) != "面料类"):
        _invalid("fabric_source_line", "裁片必须关联本 BOM 的面料行，不能猜来源面料。")
    # 关联不是匹配身份的一部分，但必须先确认不是误选另一张 BOM 的面料。
    source_bom_id = getattr(source_section, "bom_id", None)
    target_bom_id = getattr(line.section, "bom_id", None)
    if not source_bom_id or not target_bom_id or source_bom_id != target_bom_id:
        _invalid("fabric_source_line", "裁片与来源面料必须属于同一 BOM。")
    source_values = _raw_values(source)
    fabric = {
        "material": _text(getattr(source, "material", None), "fabric.material"),
        "specification": _specification(getattr(source, "specification", None), "fabric.specification"),
        "color_name": _text(source_values.get("fabric_color_name"), "fabric.color_name", required=False),
        "color_code": _text(source_values.get("fabric_color_code"), "fabric.color_code", required=False),
        "color_card": _text(source_values.get("fabric_color_card"), "fabric.color_card", required=False),
    }
    if not fabric["color_name"] and not fabric["color_code"]:
        _invalid("fabric.color", "来源面料缺少明确颜色或色号。", code="PUBLIC_STOCK_IDENTITY_INCOMPLETE")
    material = _text(getattr(line, "material", None), "material", required=False)
    color = _text(values.get("cutting_color"), "cutting_color", required=False)
    if material and material != fabric["material"]:
        _invalid("material", "裁片材质与来源面料材质冲突。", code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT")
    if color and color not in {fabric["color_name"], fabric["color_code"]}:
        _invalid("cutting_color", "裁片颜色与来源面料颜色/色号冲突。", code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT")
    return {
        "material": fabric["material"], "color": fabric["color_name"] or fabric["color_code"],
        "specification": _specification(getattr(line, "specification", None), "specification"),
        "pieces_per_set": _positive_integer(getattr(line, "cutting_pieces_per_set", None), "cutting_pieces_per_set"),
        "fabric": fabric,
    }


def build_semi_finished_identity(*, bom_line, completed_craft, unit, material_cache=None):
    """按实物字段冻结半成品身份；不生成档案，不保留来源 BOM/订单标识。"""
    line = bom_line
    section = getattr(line, "section", None)
    section_type = getattr(section, "section_type", None)
    title = _text(getattr(section, "title", None), "section.title")
    values = _raw_values(line)
    craft = _craft(completed_craft)
    unit_name = _text(getattr(unit, "unit_name", None), "unit_name")
    if section_type == "PROFILE":
        semi_kind, required_unit = "PIPE", "支"
        properties = _pipe_properties(line, values, craft, material_cache=material_cache)
    elif section_type == "FABRIC" and title == "裁剪明细":
        semi_kind, required_unit = "CUTTING", "套"
        if craft["code"] not in {"CUTTING", "SEWING", "SCREEN_PRINTING"}:
            _invalid("completed_craft", "裁片完成工艺必须是既有裁剪、车缝或丝印工艺。")
        properties = _cutting_properties(line, values)
    elif section_type == "ACCESSORY" and title == "五金件":
        semi_kind = "HARDWARE"
        required_unit = unit_name
        flow_unit = _text(values.get("hardware_flow_unit") or getattr(line, "unit", None), "flow_unit")
        if flow_unit not in {unit_name, getattr(unit, "unit_code", None)}:
            _invalid("unit", "五金半成品流转单位与 BOM 不一致。")
        properties = {
            "specification": _specification(getattr(line, "specification", None), "specification"),
            "thickness": _number_text(values["thickness"], "thickness") if _text(values.get("thickness"), "thickness", required=False) else "",
            "color": _text(values.get("powder_coating_color" if craft["code"] == "POWDER_COATING" else "hardware_color"), "color"),
        }
    else:
        _invalid("bom_line", "当前 BOM 行不属于已有管材、裁片或五金半成品。")
    if unit_name != required_unit:
        _invalid("unit", f"该半成品必须按{required_unit}记账，不能沿用原料单位。")
    category = _text(getattr(line, "category", None), "category")
    if semi_kind == "CUTTING":
        cutting_category = _text(values.get("cutting_category"), "cutting_category", required=False)
        if cutting_category and cutting_category != category:
            _invalid("category", "裁剪类别与 BOM 行类别冲突。", code="PUBLIC_STOCK_ATTRIBUTE_CONFLICT")
    snapshot = {
        "schema_version": 1, "stock_kind": "SEMI", "semi_kind": semi_kind,
        "unit_id": _uuid(getattr(unit, "pk", None), "unit_id"), "unit_name": unit_name,
        "category": category, "part_name": _text(getattr(line, "part_name", None), "part_name"),
        "material": properties.pop("material", None) or _text(getattr(line, "material", None), "material"),
        "completed_craft": craft, **properties,
    }
    return validate_public_identity(_make_identity(snapshot))


def validate_public_identity(identity):
    """校验冻结内容、索引和外围记账字段的一致性，返回独立的规范值。

该函数不查询当前 BOM 或字典；旧快照始终按当时实物解释。写入服务仍需
锁定有效单位/库区并验证来源权限，不能把客户端自造哈希当成受信任来源。
"""
    if not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS:
        _invalid("identity", "公共库存身份字段缺失或包含未支持字段。")
    snapshot = identity["identity_snapshot"]
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        _invalid("identity_snapshot", "不支持或缺失的库存属性快照版本。")
    kind = snapshot.get("stock_kind")
    if not isinstance(kind, str):
        _invalid("stock_kind", "库存种类必须是文字。")
    if _uuid(snapshot.get("unit_id"), "unit_id") != snapshot.get("unit_id"):
        _invalid("unit_id", "快照单位编号未经规范化。")
    unit_name = _text(snapshot.get("unit_name"), "unit_name")
    if unit_name != snapshot.get("unit_name"):
        _invalid("unit_name", "快照单位名称未经规范化。")
    if kind == "RAW_PIPE":
        expected_fields = _COMMON_FIELDS | {"raw_material_id", "raw_bar_length_m"}
        if _uuid(snapshot.get("raw_material_id"), "raw_material_id") != snapshot.get("raw_material_id"):
            _invalid("raw_material_id", "快照原料编号未经规范化。")
        length = _number_text(snapshot.get("raw_bar_length_m"), "raw_bar_length_m", places=2)
        if length != snapshot.get("raw_bar_length_m") or unit_name != "根":
            _invalid("identity_snapshot", "管材快照长度或单位不符合规范。")
    elif kind == "SEMI":
        semi_kind = snapshot.get("semi_kind")
        if not isinstance(semi_kind, str):
            _invalid("semi_kind", "半成品种类必须是文字。")
        extra = {"PIPE": _PIPE_FIELDS, "CUTTING": _CUTTING_FIELDS, "HARDWARE": _HARDWARE_FIELDS}.get(semi_kind)
        if extra is None:
            _invalid("semi_kind", "不支持的半成品类型。")
        expected_fields = _COMMON_FIELDS | _SEMI_FIELDS | extra
        # 厂内金工阶段尚未喷塑，新的身份允许颜色为空；外发喷塑以及
        # 其他半成品仍必须有明确颜色。这里仅放宽“必填”校验，仍要求
        # 空字符串经过规范化，避免把 None、"/" 等占位值混入库存。
        snapshot_craft = snapshot.get("completed_craft")
        allow_internal_metal_color_blank = (
            isinstance(snapshot_craft, dict)
            and snapshot_craft.get("craft_type") == "INTERNAL"
            and snapshot_craft.get("code") == "METAL"
        )
        for field in ("category", "part_name", "material", "color"):
            required = not (field == "color" and allow_internal_metal_color_blank)
            if _text(snapshot.get(field), field, required=required) != snapshot.get(field):
                _invalid(field, "快照文字未经规范化。")
        craft = snapshot.get("completed_craft")
        if not isinstance(craft, dict) or set(craft) != {"id", "craft_type", "code"}:
            _invalid("completed_craft", "已完成工艺快照不完整。")
        if _uuid(craft["id"], "completed_craft.id") != craft["id"]:
            _invalid("completed_craft.id", "工艺编号未经规范化。")
        if not isinstance(craft["craft_type"], str) or craft["craft_type"] not in {"INTERNAL", "EXTERNAL"}:
            _invalid("completed_craft", "工艺类型不正确。")
        if _text(craft["code"], "completed_craft.code") != craft["code"]:
            _invalid("completed_craft", "工艺编码未经规范化。")
        valid_codes = {"POWDER_COATING", "SCREEN_PRINTING", "CUTTING", "SEWING"} if craft["craft_type"] == "EXTERNAL" else {"METAL", "CUTTING", "SEWING", "ASSEMBLY"}
        if craft["code"] not in valid_codes:
            _invalid("completed_craft.code", "工艺编码与实际工艺类型不一致。")
        if semi_kind == "PIPE":
            if unit_name != "支" or (craft["craft_type"], craft["code"]) not in {("EXTERNAL", "POWDER_COATING"), ("INTERNAL", "METAL")}:
                _invalid("identity_snapshot", "管材半成品必须按支记录真实的金工或喷塑完成阶段。")
            if _text(snapshot.get("tube_shape"), "tube_shape") != snapshot.get("tube_shape") or snapshot.get("tube_shape") in {"Φ", "Ф", "φ"}:
                _invalid("tube_shape", "截面形状未经规范化。")
            if _dimensions(snapshot.get("tube_diameter"), "tube_diameter") != snapshot.get("tube_diameter"):
                _invalid("tube_diameter", "截面尺寸未经规范化。")
            if _number_text(snapshot.get("tube_thickness"), "tube_thickness") != snapshot.get("tube_thickness"):
                _invalid("tube_thickness", "壁厚未经规范化。")
            if type(snapshot.get("cutting_length_mm")) is not int:
                _invalid("cutting_length_mm", "切割长度必须是整数毫米。")
            _positive_integer(snapshot["cutting_length_mm"], "cutting_length_mm")
            if _text(snapshot.get("hardness"), "hardness", required=False) != snapshot.get("hardness"):
                _invalid("hardness", "硬度文字未经规范化。")
        elif semi_kind == "CUTTING":
            if unit_name != "套" or craft["code"] not in {"CUTTING", "SEWING", "SCREEN_PRINTING"}:
                _invalid("identity_snapshot", "裁片半成品工艺或套单位不正确。")
            if _specification(snapshot.get("specification"), "specification") != snapshot.get("specification"):
                _invalid("specification", "裁片规格未经规范化。")
            if type(snapshot.get("pieces_per_set")) is not int:
                _invalid("pieces_per_set", "每套片数必须是正整数。")
            _positive_integer(snapshot["pieces_per_set"], "pieces_per_set")
            fabric = snapshot.get("fabric")
            if not isinstance(fabric, dict) or set(fabric) != {"material", "specification", "color_name", "color_code", "color_card"}:
                _invalid("fabric", "冻结面料属性不完整。")
            for field in ("material", "specification"):
                normal = _specification(fabric[field], f"fabric.{field}") if field == "specification" else _text(fabric[field], f"fabric.{field}")
                if normal != fabric[field]:
                    _invalid("fabric", "来源面料属性未经规范化。")
            for field in ("color_name", "color_code", "color_card"):
                if _text(fabric[field], f"fabric.{field}", required=False) != fabric[field]:
                    _invalid("fabric", "来源面料颜色信息未经规范化。")
            if (not fabric["color_name"] and not fabric["color_code"]
                    or snapshot["material"] != fabric["material"]
                    or snapshot["color"] != (fabric["color_name"] or fabric["color_code"])):
                _invalid("fabric", "裁片与冻结来源面料的材质/颜色冲突。")
        else:
            if _specification(snapshot.get("specification"), "specification") != snapshot.get("specification"):
                _invalid("specification", "五金规格未经规范化。")
            thickness = _text(snapshot.get("thickness"), "thickness", required=False)
            if thickness != snapshot.get("thickness") or (thickness and _number_text(thickness, "thickness") != thickness):
                _invalid("thickness", "厚度未经规范化。")
    else:
        _invalid("stock_kind", "不支持的公共库存种类。")
    if set(snapshot) != expected_fields:
        _invalid("identity_snapshot", "快照字段缺失或包含订单、批次等非实物字段。")
    expected = _make_identity(snapshot)
    if (identity["stock_kind"] != expected["stock_kind"] or identity["identity_key"] != expected["identity_key"]
            or identity["unit_id"] != expected["unit_id"] or identity["raw_material_id"] != expected["raw_material_id"]):
        _invalid("identity", "公共库存身份索引、单位或原料字段与冻结内容不一致。")
    if kind == "RAW_PIPE":
        if _positive_decimal(identity["raw_bar_length_m"], "raw_bar_length_m", places=2) != expected["raw_bar_length_m"]:
            _invalid("raw_bar_length_m", "外围原料长度与冻结内容不一致。")
    elif identity["raw_bar_length_m"] is not None:
        _invalid("raw_bar_length_m", "半成品身份不能带入原料长管长度。")
    return expected
