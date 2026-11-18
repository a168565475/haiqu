"""BOM 五金单重纯计算；不查数据库，不联网，不修改输入。"""

import re
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP, localcontext

from rest_framework.exceptions import ValidationError

from .hardware_weight_data import (
    DENSITY_REFERENCE_URLS,
    REFERENCE_VERSION,
    RIVET_SOURCE_URL,
    RIVET_STEEL_WEIGHT_G,
    WASHER_DIMENSIONS_MM,
    WASHER_SOURCE_URL,
)

PI = Decimal("3.1415926535897932384626433832795028841971693993751")
WEIGHT_QUANTUM = Decimal("0.00000001")
_NUMBER = r"[0-9]{1,6}(?:\.[0-9]{1,6})?"
_RIVET_SPEC = re.compile(rf"(?:GB/?T?873(?:[-—](?:1986|86))?)?[ΦØФ∅⌀]?({_NUMBER})[X×*\-—－]({_NUMBER})(?:MM)?")
# 普通平垫的 M6/Φ6 默认按 GB/T 97.1-2002 A 级尺寸表；其他标准仍应填三项实际尺寸。
_WASHER_SPEC = re.compile(rf"(?:GB/?T?97\.1[-—]2002)?[MΦØФ∅⌀]({_NUMBER})(?:MM)?")
_WASHER_SIZE = re.compile(rf"({_NUMBER})[X×*]({_NUMBER})[X×*]({_NUMBER})(?:MM)?")
_CARBON_STEEL_NAMES = {
    "碳钢", "碳素钢", "低碳钢", "普通碳钢", "铁", "铁制", "钢", "钢制",
    "Q195", "Q215", "Q235", "Q235A", "Q235B", "Q235C", "Q235D", "CARBONSTEEL",
}
_STEEL_REFERENCE_NAMES = {"65MN", "65锰", "65锰钢"}
_ALUMINIUM_NAMES = {"铝", "纯铝", "AL", "ALUMINIUM", "ALUMINUM"}
_SUS304_NAMES = {"304", "SUS304", "304不锈钢", "不锈钢304", "06CR19NI10"}
_WASHER_FIELDS = ("outer_diameter_mm", "inner_diameter_mm", "thickness_mm")
_FIELD_LABELS = {
    "diameter_mm": "杆径", "length_mm": "长度", "outer_diameter_mm": "外径",
    "inner_diameter_mm": "内径", "thickness_mm": "厚度", "density_g_cm3": "密度",
}


def _text(data, field, *, required=False):
    value = data.get(field, "")
    if not isinstance(value, str) or len(value) > 255:
        raise ValidationError({field: "请填写不超过 255 字的文本。"})
    value = value.strip()
    if required and not value:
        raise ValidationError({field: "此项不能为空。"})
    return value


def _compact(value):
    return format(value, "f").rstrip("0").rstrip(".") if value % 1 else format(value, ".0f")


def _positive_decimal(value, field):
    label = _FIELD_LABELS[field]
    if isinstance(value, Decimal):
        if not value.is_finite() or value.adjusted() > 5 or value.as_tuple().exponent < -6:
            raise ValidationError({field: f"{label}必须是最多 6 位整数、6 位小数的正数。"})
        value = format(value, "f")
    elif isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(_NUMBER, value.strip()):
        raise ValidationError({field: f"{label}必须是最多 6 位整数、6 位小数的正数。"})
    number = Decimal(value.strip())
    if number <= 0:
        raise ValidationError({field: f"{label}必须大于 0。"})
    return number


def _provided(data, field):
    return field in data and data[field] not in (None, "")


def _material_reference(material):
    key = re.sub(r"\s+", "", material).upper()
    if key in _CARBON_STEEL_NAMES:
        return "CARBON_STEEL", Decimal("7.85")
    if key in _STEEL_REFERENCE_NAMES:
        return "STEEL", Decimal("7.85")
    if key in _ALUMINIUM_NAMES:
        return "ALUMINIUM", Decimal("2.70")
    if key in _SUS304_NAMES:
        return "SUS304", Decimal("7.93")
    return "", None


def _rivet_dimensions(data, specification):
    # 目录将规格、尺寸等属性用“ / ”展示；保留 GB/T 中没有两侧空格的斜杠。
    parts = re.split(r"\s+/\s+", specification)
    matches = [_RIVET_SPEC.fullmatch(re.sub(r"\s+", "", part).upper()) for part in parts]
    if len(parts) > 1 and not all(matches):
        raise ValidationError({"specification": "铆钉规格属性包含无法核对的尺寸或标准，请核实规格和尺寸。"})
    parsed_values = [tuple(Decimal(value) for value in match.groups()) for match in matches if match]
    if len(set(parsed_values)) > 1:
        raise ValidationError({"specification": "铆钉规格和尺寸属性中的杆径、长度不一致。"})
    parsed = parsed_values[0] if parsed_values else None
    fields = ("diameter_mm", "length_mm")
    provided = [_provided(data, field) for field in fields]
    if any(provided) and not all(provided):
        raise ValidationError({"diameter_mm": "请同时填写铆钉杆径和长度。"})
    if all(provided):
        values = tuple(_positive_decimal(data[field], field) for field in fields)
        if parsed and values != parsed:
            raise ValidationError({"specification": "规格中的杆径、长度与输入尺寸不一致。"})
        return values
    if parsed:
        return tuple(_positive_decimal(value, field) for field, value in zip(fields, parsed, strict=True))
    raise ValidationError({"specification": "请填写明确的杆径×长度，例如 5×30，或分别填写杆径和长度。"})


def _washer_dimensions(data, specification):
    standard_dimensions = None
    size_dimensions = []
    parts = re.split(r"\s+/\s+", specification)
    for part in parts:
        compact = re.sub(r"\s+", "", part).upper()
        match = _WASHER_SPEC.fullmatch(compact)
        size = _WASHER_SIZE.fullmatch(compact)
        if match:
            nominal = _compact(Decimal(match.group(1)))
            dimensions = WASHER_DIMENSIONS_MM.get(nominal)
            if dimensions is None:
                raise ValidationError({"specification": "该 GB/T 97.1-2002 平垫规格没有已核对的尺寸，请核实规格。"})
            dimensions = tuple(Decimal(value) for value in dimensions)
            if standard_dimensions and standard_dimensions != dimensions:
                raise ValidationError({"specification": "平垫规格属性中的标准尺寸不一致。"})
            standard_dimensions = dimensions
        elif size:
            size_dimensions.append(tuple(Decimal(value) for value in size.groups()))
        elif len(parts) > 1:
            raise ValidationError({"specification": "平垫规格属性包含无法核对的尺寸或标准，请核实规格和尺寸。"})
    provided = [_provided(data, field) for field in _WASHER_FIELDS]
    if any(provided) and not all(provided):
        raise ValidationError({"outer_diameter_mm": "请完整填写平垫外径、内径和厚度。"})
    if all(provided):
        dimensions = tuple(_positive_decimal(data[field], field) for field in _WASHER_FIELDS)
        if standard_dimensions and dimensions != standard_dimensions:
            raise ValidationError({"specification": "输入尺寸与指定的 GB/T 97.1-2002 标准尺寸不一致。"})
    elif standard_dimensions:
        dimensions = standard_dimensions
    else:
        raise ValidationError({"outer_diameter_mm": "请填写普通 M6/Φ6 或完整标准规格；加大、异形及非标垫片请分别填写外径、内径和厚度。"})
    # 单独三数字不猜顺序；已有标准或明确输入后才核对外径×内径×厚度。
    if any(size != dimensions for size in size_dimensions):
        raise ValidationError({"specification": "平垫尺寸属性与标准或输入的外径、内径、厚度不一致。"})
    if dimensions[0] <= dimensions[1]:
        raise ValidationError({"outer_diameter_mm": "平垫外径必须大于内径。"})
    return dimensions, "GB/T 97.1-2002" if standard_dimensions else ""


def calculate_hardware_weight(data):
    """返回单件 g、kg 字符串及可追溯快照；缺失条件时明确报错，不猜规格。"""
    if not isinstance(data, Mapping):
        raise ValidationError({"non_field_errors": "五金重量计算参数必须是对象。"})
    kind = _text(data, "kind", required=True)
    material = _text(data, "material", required=True)
    specification = _text(data, "specification")
    if kind not in ("RIVET_GB873_STEEL", "PLAIN_WASHER"):
        raise ValidationError({"kind": "暂不支持该五金重量计算方式。"})
    material_kind, reference_density = _material_reference(material)
    normalized_input = {"kind": kind, "material": material, "specification": specification}
    notes = ["理论重量未计镀层、制造公差及实际批次差异。"]

    with localcontext() as context:
        context.prec = 64
        if kind == "RIVET_GB873_STEEL":
            if material_kind not in {"CARBON_STEEL", "STEEL"}:
                raise ValidationError({"material": "此表仅用于明确的钢制扁圆头半空心铆钉，不能用于不锈钢、铝、铜或未知材质。"})
            if _provided(data, "density_g_cm3"):
                density = _positive_decimal(data["density_g_cm3"], "density_g_cm3")
                if density != reference_density:
                    raise ValidationError({"density_g_cm3": "钢制铆钉按参考表查重，不支持使用其他密度换算。"})
                normalized_input["density_g_cm3"] = _compact(density)
            diameter, length = _rivet_dimensions(data, specification)
            parameters = {"diameter_mm": _compact(diameter), "length_mm": _compact(length)}
            weight = RIVET_STEEL_WEIGHT_G.get((parameters["diameter_mm"], parameters["length_mm"]))
            if weight is None:
                raise ValidationError({"specification": "该杆径和长度没有已核对的钢制铆钉重量；38/39 mm 存在来源疑点，均不自动计算。"})
            unit_weight_g = Decimal(weight)
            standard, method, source_url = "GB/T 873-1986", "STANDARD_TABLE", RIVET_SOURCE_URL
            extra = {"table_weight_kg_per_1000": weight}
            if material_kind == "STEEL":
                notes.append("65Mn 按钢制 GB/T 873-1986 标准表查重，未按牌号密度缩放。")
        else:
            dimensions, standard = _washer_dimensions(data, specification)
            parameters = {field: _compact(value) for field, value in zip(_WASHER_FIELDS, dimensions, strict=True)}
            explicit_density = _provided(data, "density_g_cm3")
            if explicit_density:
                density = _positive_decimal(data["density_g_cm3"], "density_g_cm3")
            elif reference_density is not None:
                density = reference_density
            else:
                raise ValidationError({"density_g_cm3": "该材质没有明确密度，请填写密度；笼统的不锈钢或铝合金不能自动选密度。"})
            if density > 100:
                raise ValidationError({"density_g_cm3": "密度单位为 g/cm³，请填写不超过 100 的有效值。"})
            parameters["density_g_cm3"] = _compact(density)
            if explicit_density:
                normalized_input["density_g_cm3"] = _compact(density)
            if explicit_density and reference_density is not None and density != reference_density:
                notes.append(f"使用输入密度 {_compact(density)} g/cm³，未采用材质参考密度 {_compact(reference_density)} g/cm³。")
            outer, inner, thickness = dimensions
            unit_weight_g = PI / 4 * (outer * outer - inner * inner) * thickness * density / 1000
            method, source_url = "ANNULAR_VOLUME", WASHER_SOURCE_URL
            extra = {
                "formula": "π/4×(外径²−内径²)×厚度×密度/1000；尺寸 mm，密度 g/cm³，结果 g/件",
                "density_source": "EXPLICIT" if explicit_density else "MATERIAL_REFERENCE",
                "reference_density_g_cm3": _compact(reference_density) if reference_density is not None else "",
                "density_reference_url": DENSITY_REFERENCE_URLS.get(material_kind, DENSITY_REFERENCE_URLS.get("CARBON_STEEL", "")),
                "dimensions_source": "STANDARD_TABLE" if standard else "EXPLICIT",
            }
            if not specification.upper().replace(" ", "").startswith("GB/T97.1-2002"):
                notes.append("未标注其他标准时，按普通平垫 GB/T 97.1-2002 A 级尺寸表解释。")
        weight_kg = (unit_weight_g / 1000).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
        if weight_kg <= 0:
            raise ValidationError({"unit_material_weight_kg": "单重小于当前 8 位小数精度，请核对尺寸或使用实测重量，不能按零保存。"})
        weight_g_text = _compact(unit_weight_g.quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP))
        weight_kg_text = format(weight_kg, ".8f")
        normalized_input.update({key: value for key, value in parameters.items() if key != "density_g_cm3"})
        snapshot = {
            "version": 1, "reference_version": REFERENCE_VERSION,
            "kind": kind, "method": method, "standard": standard, "source_url": source_url,
            "material": material, "specification": specification, "input": normalized_input,
            "parameters": parameters, "unit_weight_g": weight_g_text,
            "unit_material_weight_kg": weight_kg_text, "notes": notes, **extra,
        }
    return {"unit_material_weight_kg": weight_kg_text, "unit_weight_g": weight_g_text, "calculation_snapshot": snapshot}
