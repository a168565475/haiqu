"""采购合同明细的规格、物料属性与颜色分栏，不修改历史快照。"""


COLOR_KEYS = {
    "hardware_color", "plastic_color", "fabric_color_name", "accessory_color", "packaging_color",
}


def _text(value):
    return str(value).strip() if value is not None else ""


def purchase_sheet_line_display(line, *, sample_source=False):
    specification = _text(line.get("specification"))
    material = _text(line.get("material"))
    remark = _text(line.get("remark"))
    attributes = [f"材质：{material}"] if material else []
    colors = [remark] if sample_source and remark else []
    snapshot = line.get("material_attributes_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    fields = snapshot.get("fields")
    for field in fields if isinstance(fields, list) else []:
        if not isinstance(field, dict):
            continue
        key, label, value = (_text(field.get(name)) for name in ("key", "label", "value"))
        if not label or not value or key == "tube_coating_color" or label == "喷塑颜色":
            continue
        if key in {"part_name", "material", "specification"} or label in {"品名", "部件名称", "材质", "规格"}:
            continue
        is_color = not sample_source and (key in COLOR_KEYS or label == "颜色")
        target = colors if is_color else attributes
        text = value if is_color else f"{label}：{value}"
        if text not in target:
            target.append(text)
    if not sample_source and remark and f"要求：{remark}" not in attributes:
        attributes.append(f"要求：{remark}")
    return {"specification": specification, "attributes": "；".join(attributes), "color": " / ".join(colors)}
