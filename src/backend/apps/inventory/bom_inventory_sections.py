from django.db.models import Q

from apps.material_catalog.definitions import CATEGORIES
from apps.products.models import RawMaterialBoxShape


RAW_SECTIONS = {
    "TUBE": ("管材", ("管材", "管材类", "型材", "型材明细")),
    "HARDWARE": ("五金", ("五金", "五金件", "五金件类")),
    "PLASTIC": ("塑料", ("塑料", "塑料件", "塑料件类")),
    "FABRIC": ("面料", ("面料", "面料类")),
    "AUXILIARY": ("辅料", ("辅料", "辅料类")),
    "PACKAGING": ("包材", ("包材", "包材类")),
}
SEMI_SECTIONS = {
    "TUBE": ("管材", ("PIPE",)),
    "HARDWARE": ("五金", ("HARDWARE",)),
    "FABRIC_SEMI": ("裁片", ("CUT_PIECE",)),
    "SEWN_PART": ("部位半成品", ("SEWN_PART",)),
}
SECTIONS_BY_STOCK_KIND = {"RAW": RAW_SECTIONS, "SEMI": SEMI_SECTIONS}
LEGACY_FABRIC_CRAFT_CODES = {
    "FABRIC_SEMI": ("CUTTING",),
    "SEWN_PART": ("SEWING", "SCREEN_PRINTING", "EMBROIDERY"),
}
TUBE_PROCESSING_LABELS = {"METAL": "未喷塑", "POWDER_COATING": "已喷塑"}

COLOR_FIELDS = {"color_card": "色卡", "color_code": "色号"}
FIELD_LABELS = {
    "section_size": "截面规格", "length": "单根长度", "width": "宽度",
    "size": "尺寸", "specification": "规格", "material": "材质",
    "printing": "印刷版本/唛头",
}
LEGACY_RAW_FIELDS = {
    "section_size": "diameter", "width": "width", "thickness": "thickness",
    "model": "model_number", "flow_unit": "flow_unit", "box_type": "box_shape",
}
LEGACY_BOX_SHAPE_LABELS = dict(RawMaterialBoxShape.choices)


def legacy_semi_craft_filter(codes):
    return (Q(completed_craft__craft_type="INTERNAL", completed_craft__plan_category__in=codes)
            | Q(completed_craft__craft_type="EXTERNAL", completed_craft__outsourcing_code__in=codes))


def _selection_attributes(selection):
    return {
        **selection.get("attributes", {}),
        **{key: selection[key] for key in COLOR_FIELDS if key in selection},
    }


def raw_inventory_attributes(row, section, color):
    if selection := row.get("material_selection_snapshot"):
        attributes = _selection_attributes(selection)
    else:
        attributes = {key: row.get(f"raw_material__{field}") for key, field in LEGACY_RAW_FIELDS.items()}
        attributes.update(material=row["raw_material__material"], color=color)
        if section == "PACKAGING":
            attributes["box_type"] = LEGACY_BOX_SHAPE_LABELS.get(attributes["box_type"], attributes["box_type"])
        if section != "TUBE":
            attributes["fabric_spec" if section == "FABRIC" else "specification"] = row["raw_material__specification"]
    if section == "TUBE" and row["raw_bar_length_m"] is not None:
        attributes["length"] = f'{format(row["raw_bar_length_m"].normalize(), "f")} m'
    return attributes


def semi_inventory_attributes(snapshot):
    attributes = _selection_attributes(snapshot.get("material_selection_snapshot", {}))
    attributes.update({key: snapshot[key] for key in ("material", "color", "specification", "thickness", "pieces_per_set") if key in snapshot})
    attributes.update(snapshot.get("component_attributes", {}))
    if snapshot["semi_kind"] == "PIPE":
        attributes.update(shape=snapshot.get("tube_shape"), section_size=snapshot.get("tube_diameter"),
                          thickness=snapshot.get("tube_thickness"), cutting_length_mm=snapshot.get("cutting_length_mm"),
                          hardness=snapshot.get("hardness"))
    elif fabric := snapshot.get("fabric"):
        attributes.update(fabric_spec=fabric.get("specification"), color_card=fabric.get("color_card"), color_code=fabric.get("color_code"))
    return attributes


def legacy_semi_inventory_attributes(line, color, section):
    values = line.raw_values
    attributes = _selection_attributes(line.material_selection_snapshot)
    attributes.update(material=line.material, color=color, specification=line.specification)
    if section == "TUBE":
        attributes.update(shape=values.get("tube_shape") or values.get("E"),
                          section_size=values.get("tube_diameter") or values.get("F"),
                          thickness=values.get("tube_thickness") or values.get("G"),
                          cutting_length_mm=line.cutting_length_mm, hardness=line.hardness)
    elif section == "HARDWARE":
        attributes.update(thickness=values.get("thickness"), flow_unit=values.get("hardware_flow_unit"))
    elif section == "FABRIC_SEMI":
        attributes["pieces_per_set"] = line.cutting_pieces_per_set
    return attributes


def bom_inventory_section_options():
    catalog_fields = {}
    for category in CATEGORIES:
        fields = {}
        for template in category["templates"]:
            for field in template["fields"]:
                if field["kind"] != "unit":
                    fields.setdefault(field["key"], field["label"])
        key = category["key"]
        if key == "TUBE":
            fields.update(section_size=FIELD_LABELS["section_size"], length=FIELD_LABELS["length"])
        if key in {"FABRIC", "FABRIC_SEMI"}:
            fields.update(COLOR_FIELDS)
        if key in {"AUXILIARY", "PACKAGING"}:
            fields.update({field: label for field, label in FIELD_LABELS.items() if field in fields})
        catalog_fields[key] = fields

    # 五金半成品保留历史分类查询，页签由有字段定义的分区生成。
    semi_fields = {
        "TUBE": {key: label for key, label in catalog_fields["TUBE"].items() if key != "length"}
        | {"cutting_length_mm": "切割长度（mm）", "hardness": "硬度"},
        "FABRIC_SEMI": catalog_fields["FABRIC_SEMI"] | {"pieces_per_set": "每套片数"},
        "SEWN_PART": catalog_fields["FABRIC_SEMI"],
    }
    return {
        kind: [
            {"key": key, "label": label, "fields": [{"key": field, "label": name} for field, name in fields[key].items()]}
            for key, (label, _) in sections.items()
            if key in fields
        ]
        for kind, sections, fields in (("RAW", RAW_SECTIONS, catalog_fields), ("SEMI", SEMI_SECTIONS, semi_fields))
    }
