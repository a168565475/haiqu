"""统一把 BOM 六个生产用料分区转换为可读的物料属性。

采购有自己的快照口径；本模块只服务于生产、半成品和委外页面，刻意不包含裁剪明细。
"""

from collections import OrderedDict


def spray_color_value(raw_values):
    """按 BOM 同时保留管材、五金的喷塑颜色；冲突值显式并列显示。"""
    raw = raw_values or {}
    values = []
    for value in (raw.get("tube_coating_color"), raw.get("powder_coating_color")):
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return "、".join(values)


SECTION_FIELDS = {
    "管材类": (
        ("part_name", "部件名称"),
        ("material", "材质"),
        ("specification", "规格"),
        ("spray_color", "喷塑颜色"),
    ),
    "五金件": (
        ("part_name", "品名"),
        ("material", "材质"),
        ("hardware_color", "颜色"),
        ("specification", "规格"),
        ("spray_color", "喷塑颜色"),
    ),
    "塑料件类": (
        ("part_name", "品名"),
        ("material", "材质"),
        ("plastic_color", "颜色"),
        ("specification", "规格"),
    ),
    "面料类": (
        ("specification", "规格"),
        ("material", "材质"),
        ("fabric_color_card", "色卡"),
        ("fabric_color_name", "颜色"),
        ("fabric_color_code", "色号"),
        ("fabric_width", "门幅"),
    ),
    "辅料类": (
        ("part_name", "品名"),
        ("specification", "规格"),
        ("accessory_color", "颜色"),
        ("material", "材质"),
    ),
    "包材类": (
        ("part_name", "品名"),
        ("material", "材质"),
        ("packaging_color", "颜色"),
        ("specification", "规格"),
    ),
}
SECTION_FIELDS.update({
    "型材类": SECTION_FIELDS["管材类"],
    "型材": SECTION_FIELDS["管材类"],
})


def _value(line, key):
    if key == "part_name":
        return getattr(line, "part_name", "")
    if key == "material":
        return getattr(line, "material", "")
    if key == "specification":
        return getattr(line, "specification", "")
    raw = getattr(line, "raw_values", None) or {}
    if key == "spray_color":
        return spray_color_value(raw)
    return raw.get(key, "")


def bom_attribute_fields(line, *, spray_color_override=None):
    """返回非空的 ``[{key, label, value}]``，保留 BOM 字段顺序。"""
    title = str(getattr(getattr(line, "section", None), "title", "") or "").strip()
    fields = SECTION_FIELDS.get(title, ())
    result = []
    for key, label in fields:
        value = spray_color_override if key == "spray_color" and spray_color_override is not None else _value(line, key)
        value = str(value or "").strip()
        if value:
            result.append({"key": key, "label": label, "value": value})
    return result


def merge_bom_attribute_fields(field_groups):
    """合并同一库存物料对应的多个 BOM 行，去重后用顿号连接不同值。"""
    merged = OrderedDict()
    for fields in field_groups:
        for field in fields or ():
            key = str(field.get("key") or "").strip()
            value = str(field.get("value") or "").strip()
            if not key or not value:
                continue
            current = merged.get(key)
            if current is None:
                merged[key] = {"key": key, "label": field.get("label") or key, "value": value}
            elif value not in current["value"].split("、"):
                current["value"] = f'{current["value"]}、{value}'
    return list(merged.values())


def override_bom_attribute(fields, key, value, label=None):
    """为半成品结果替换某个属性，空值不会制造新的字段。"""
    value = str(value or "").strip()
    result = [dict(field) for field in fields or () if field.get("key") != key]
    if value:
        result.append({"key": key, "label": label or key, "value": value})
    return result
