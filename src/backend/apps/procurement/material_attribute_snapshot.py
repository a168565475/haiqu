"""生产 BOM 物料属性的历史快照。

采购单一旦创建，不能再依赖 BOM 当前内容展示历史明细，因此这里把各分区
的属性整理成稳定的标签和值数组。样品采购不使用本快照，继续沿用原有字段。
"""


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _field(key, label, value):
    value = _text(value)
    return {"key": key, "label": label, "value": value} if value else None


def build_material_attribute_snapshot(line, section):
    """从 BOM 行生成结构化采购属性；喷塑颜色故意不纳入。"""
    raw = line.raw_values or {}
    title = _text(getattr(section, "title", ""))
    section_type = _text(getattr(section, "section_type", ""))

    if "型材" in title or section_type == "PROFILE":
        definitions = (
            ("part_name", "部件名称", line.part_name),
            ("material", "材质", line.material),
            ("specification", "规格", line.specification),
            ("tube_shape", "形状", raw.get("tube_shape")),
            ("tube_diameter", "直径", raw.get("tube_diameter")),
            ("tube_thickness", "厚度", raw.get("tube_thickness")),
        )
    elif "五金" in title:
        definitions = (
            ("part_name", "品名", line.part_name),
            ("material", "材质", line.material),
            ("hardware_color", "颜色", raw.get("hardware_color")),
            ("specification", "规格", line.specification),
        )
    elif "塑料" in title:
        definitions = (
            ("part_name", "品名", line.part_name),
            ("material", "材质", line.material),
            ("plastic_color", "颜色", raw.get("plastic_color")),
            ("specification", "规格", line.specification),
        )
    elif "面料" in title:
        definitions = (
            ("specification", "规格", line.specification),
            ("material", "材质", line.material),
            ("fabric_color_card", "色卡", raw.get("fabric_color_card")),
            ("fabric_color_name", "颜色", raw.get("fabric_color_name")),
            ("fabric_color_code", "色号", raw.get("fabric_color_code")),
            ("fabric_width", "门幅", raw.get("fabric_width")),
        )
    elif "辅料" in title:
        definitions = (
            ("part_name", "品名", line.part_name),
            ("specification", "规格", line.specification),
            ("accessory_color", "颜色", raw.get("accessory_color")),
            ("material", "材质", line.material),
        )
    elif "包材" in title:
        definitions = (
            ("part_name", "品名", line.part_name),
            ("material", "材质", line.material),
            ("packaging_color", "颜色", raw.get("packaging_color")),
            ("specification", "规格", line.specification),
        )
    else:
        definitions = (
            ("part_name", "品名", line.part_name),
            ("material", "材质", line.material),
            ("specification", "规格", line.specification),
        )

    fields = [item for item in (_field(*definition) for definition in definitions) if item]
    return {
        "schema_version": 1,
        "section_type": section_type,
        "section_title": title,
        "fields": fields,
    }


def legacy_material_attribute_snapshot(line):
    """为历史采购行提供通用字段降级展示。"""
    definitions = (
        ("part_name", "品名", getattr(line, "part_name_snapshot", "")),
        ("material", "材质", getattr(line, "material_snapshot", "")),
        ("specification", "规格", getattr(line, "specification_snapshot", "")),
    )
    return {
        "schema_version": 1,
        "section_type": getattr(line, "section_type_snapshot", ""),
        "section_title": getattr(line, "section_title_snapshot", ""),
        "fields": [item for item in (_field(*definition) for definition in definitions) if item],
    }


def purchase_line_attribute_text(snapshot, section_title=""):
    """生成供应商采购表使用的分区和属性文本；喷塑颜色不进入采购输出。"""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    title = _text(section_title) or _text(snapshot.get("section_title"))
    lines = [f"BOM分区：{title}"] if title else []
    for field in snapshot.get("fields") or []:
        if not isinstance(field, dict):
            continue
        key = _text(field.get("key"))
        label = _text(field.get("label"))
        value = _text(field.get("value"))
        if not label or not value or key == "tube_coating_color" or label == "喷塑颜色":
            continue
        lines.append(f"{label}：{value}")
    return "\n".join(lines)
