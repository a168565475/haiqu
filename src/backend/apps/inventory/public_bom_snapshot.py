"""冻结实物属性，供领料之后的金工交接使用；回货不再读取现行 BOM。"""

import json
from types import SimpleNamespace

from django.core.serializers.json import DjangoJSONEncoder

from .public_stock_identity import build_semi_finished_identity
from .stock_services import InventoryStockValidationError


_FIELDS = (
    "category", "part_name", "material", "specification", "unit", "hardness",
    "cutting_length_mm", "cutting_pieces_per_set", "raw_values",
)
_RAW_FIELDS = {
    "tube_shape", "tube_diameter", "tube_thickness", "tube_coating_color", "E", "F", "G",
    "cutting_category", "cutting_color", "fabric_color_name", "fabric_color_code", "fabric_color_card",
    "hardware_flow_unit", "thickness", "powder_coating_color", "hardware_color",
}


def _invalid():
    raise InventoryStockValidationError(
        {"detail": "缺少完整的领料时 BOM 实物属性快照，不能根据当前 BOM 猜补历史半成品。"},
        code="PUBLIC_STOCK_FROZEN_BOM_REQUIRED",
    )


def _freeze_line(line):
    section = getattr(line, "section", None)
    if line is None or section is None or not getattr(line, "pk", None) or not getattr(section, "bom_id", None):
        _invalid()
    raw_values = getattr(line, "raw_values", None)
    if raw_values is not None and not isinstance(raw_values, dict):
        _invalid()
    return {
        "id": str(line.pk),
        "section": {
            "section_type": section.section_type,
            "title": section.title,
            "bom_id": str(section.bom_id),
        },
        **{name: getattr(line, name, None) for name in _FIELDS},
        "raw_values": {key: value for key, value in (raw_values or {}).items() if key in _RAW_FIELDS},
    }


def freeze_bom_line(bom_line):
    """允许原料阶段尚无喷塑色；实际交接构造输出身份时严格核验。"""
    frozen = {"schema_version": 1, "line": _freeze_line(bom_line), "fabric_source_line": None}
    if bom_line.section.section_type == "FABRIC" and bom_line.section.title == "裁剪明细":
        source = getattr(bom_line, "fabric_source_line", None)
        if source is not None:
            frozen["fabric_source_line"] = _freeze_line(source)
    return json.loads(json.dumps(frozen, cls=DjangoJSONEncoder, allow_nan=False))


def _hydrate_line(value):
    if not isinstance(value, dict) or set(value) != {"id", "section", *_FIELDS}:
        _invalid()
    section = value["section"]
    if (not isinstance(section, dict) or set(section) != {"section_type", "title", "bom_id"}
            or not value["id"] or not section["bom_id"]):
        _invalid()
    return SimpleNamespace(pk=value["id"], section=SimpleNamespace(**section),
                           **{name: value[name] for name in _FIELDS})


def build_output_identity(frozen_bom_line, completed_craft, unit):
    if (not isinstance(frozen_bom_line, dict)
            or set(frozen_bom_line) != {"schema_version", "line", "fabric_source_line"}
            or type(frozen_bom_line["schema_version"]) is not int
            or frozen_bom_line["schema_version"] != 1):
        _invalid()
    line = _hydrate_line(frozen_bom_line["line"])
    source = frozen_bom_line["fabric_source_line"]
    line.fabric_source_line = _hydrate_line(source) if source is not None else None
    return build_semi_finished_identity(bom_line=line, completed_craft=completed_craft, unit=unit)
