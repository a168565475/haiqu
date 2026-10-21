"""确认 BOM 时按同一分区的物料属性判重，数量和来源编号不参与。"""
from rest_framework.exceptions import ValidationError

from .fabric_material_sync import _specification, _width
from .material_attributes import SECTION_FIELDS, bom_attribute_fields, spray_color_value
from .pipe_material_sync import pipe_parameter_values
from .selectors import pipe_dimension_numbers


def _text(value):
    return str(value or "").strip()


def _dimensions(value):
    return pipe_dimension_numbers(value) or _text(value)


def _material_key(line):
    title = line.section.title.strip()
    raw = line.raw_values or {}
    common = (_text(line.category), _text(line.unit))
    if line.section.section_type == "PROFILE":
        parameters = pipe_parameter_values(raw)
        # 规格显示可能附带长管长度；完整结构字段才是切割后部件的截面身份。
        specification = "" if all(parameters.values()) else _specification(line.specification)
        return (*common, _text(line.part_name), _text(line.material), parameters["tube_shape"],
                _dimensions(parameters["tube_diameter"]), _dimensions(parameters["tube_thickness"]),
                specification, line.cutting_length_mm or _dimensions(line.length_value),
                _text(line.hardness), spray_color_value(raw))
    if title not in SECTION_FIELDS:
        # 裁剪明细的产出、来源面料及每套片数有独立语义，不套用采购用料判重。
        return None
    values = {item["key"]: item["value"] for item in bom_attribute_fields(line)}
    values["specification"] = _specification(line.specification)
    if title == "面料类":
        values["fabric_width"] = _width(raw.get("fabric_width")) or _text(raw.get("fabric_width"))
    key = (*common, *(values.get(field, "") for field, _ in SECTION_FIELDS[title]))
    if title == "五金件":
        key += (_dimensions(raw.get("thickness")),)
    return key


def validate_duplicate_material_lines(lines):
    groups = {}
    for line in lines:
        material_key = _material_key(line)
        if material_key is not None:
            groups.setdefault((line.section.pk, material_key), []).append(line)
    errors = []
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        first = duplicates[0]
        numbers = "、".join(str(number) for number in sorted(line.line_number for line in duplicates))
        errors.append(f"“{first.section.title}”第 {numbers} 行物料属性完全相同，不能重复提交，请合并数量或核对物料属性。")
    if errors:
        raise ValidationError({"sections": errors})
