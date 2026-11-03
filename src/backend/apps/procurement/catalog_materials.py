"""采购中的新材料保存契约；数量单位与管材米数计价分别处理。"""
from rest_framework.exceptions import ValidationError

from apps.material_catalog.saved_selection import validate_saved_material


def bom_catalog_fields(line):
    if not line.material_catalog_id:
        return {"material_catalog_id": None, "material_selection_snapshot": {}}
    return {"material_catalog_id": line.material_catalog_id,
            "material_selection_snapshot": validate_saved_material(
                line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)}


def purchase_catalog_selection(line):
    selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
    expected_unit = "米" if line.section_type_snapshot == "PROFILE" else selected["unit_name"]
    if line.section_type_snapshot == "PROFILE" and selected["unit_name"] != "根":
        raise ValidationError({"lines": "管材保存选料须沿用根制原料单位。"})
    if line.source_unit_text != expected_unit:
        raise ValidationError({"lines": "采购数量单位与保存材料快照不一致。"})
    return selected


def physical_pipe_quantity(snapshot, data, pipe_values):
    """采购界面填根数；新旧管材内部数量均沿用由根长计算的米数。"""
    return pipe_values["actual_purchase_meters"]


def priced_quantity(*, section_type, material_catalog_id, physical_quantity, pipe_values):
    return pipe_values.get("actual_purchase_meters") if section_type == "PROFILE" and material_catalog_id else physical_quantity
