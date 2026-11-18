"""采购中的新材料保存契约；数量单位与管材米数计价分别处理。"""
from rest_framework.exceptions import ValidationError

from apps.material_catalog.saved_selection import validate_saved_material


def is_weight_purchase(line):
    snapshot = getattr(line, "calculation_snapshot", None)
    return line.source_unit_text == "KG" and (
        line.section_type_snapshot == "PROFILE"
        or isinstance(snapshot, dict) and snapshot.get("measurement_kind") == "HARDWARE_WEIGHT"
    )


def bom_catalog_fields(line):
    if not line.material_catalog_id:
        return {"material_catalog_id": None, "material_selection_snapshot": {}}
    return {"material_catalog_id": line.material_catalog_id,
            "material_selection_snapshot": validate_saved_material(
                line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)}


def purchase_catalog_selection(line):
    selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
    calculation = line.calculation_snapshot or {}
    hardware = calculation.get("measurement_kind") == "HARDWARE_WEIGHT"
    expected_unit = ("KG" if line.section_type_snapshot == "PROFILE" and line.source_unit_text == "KG" else "米") if line.section_type_snapshot == "PROFILE" else ("KG" if hardware else selected["unit_name"])
    if line.section_type_snapshot == "PROFILE" and selected["unit_name"] != "根":
        raise ValidationError({"lines": "管材保存选料须沿用根制原料单位。"})
    if line.source_unit_text != expected_unit:
        raise ValidationError({"lines": "采购数量单位与保存材料快照不一致。"})
    return selected


def physical_pipe_quantity(snapshot, data, pipe_values):
    """采购界面新口径填 KG；旧米制快照继续返回米数。"""
    if snapshot.get("measurement_unit") == "kg":
        return pipe_values.get("actual_purchase_weight_kg")
    return pipe_values["actual_purchase_meters"]


def priced_quantity(*, section_type, material_catalog_id, physical_quantity, pipe_values):
    if section_type == "PROFILE" and pipe_values.get("calculation_snapshot", {}).get("measurement_unit") == "kg":
        return pipe_values.get("actual_purchase_weight_kg") or physical_quantity
    return pipe_values.get("actual_purchase_meters") if section_type == "PROFILE" and material_catalog_id else physical_quantity
