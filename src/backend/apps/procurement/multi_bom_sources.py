"""跨产品采购按收货物料合并，保留各产品冻结时的 BOM 用量。"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import pipe_meters_text
from apps.material_catalog.snapshots import material_identity_key
from apps.material_catalog.saved_selection import validate_saved_material


def _number(value, label, *, whole=False):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError({"sources": f"{label}缺少有效数字，请核对保存的采购来源。"}) from exc
    if not number.is_finite() or number < 0 or (whole and number != number.to_integral_value()):
        raise ValidationError({"sources": f"{label}数量不正确，请核对保存的采购来源。"})
    return int(number) if whole else number


def purchase_merge_key(snapshot):
    selected = snapshot.get("material_selection_snapshot")
    calculation = snapshot.get("calculation_snapshot") or {}
    if selected or snapshot.get("material_catalog_id"):
        selected = validate_saved_material(selected, material_catalog_id=snapshot.get("material_catalog_id"))
    if selected and selected["processing_state"] == "PROCESSED":
        from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
        identity = build_catalog_stock_identity(material_catalog_id=selected["catalog_id"], material_selection_snapshot=selected)
        material = ("catalog", identity["identity_key"])
    elif selected:
        material = ("catalog", material_identity_key(selected))
    elif calculation.get("raw_material_id"):
        material = ("raw", calculation["raw_material_id"])
    else:
        label = snapshot.get("part_name_snapshot") or snapshot.get("source_bom_line_id_snapshot") or "采购行"
        raise ValidationError({"sources": f"{label}缺少保存的收货物料身份，请核对原需求。"})
    section = snapshot["section_type_snapshot"]
    # 目录库存以保存选料为准。旧单可缺少悬浮展示字段，这不会改变其收货身份。
    fields = [] if selected else (snapshot.get("material_attributes_snapshot") or {}).get("fields", [])
    attributes = tuple(sorted((field["key"], field["value"]) for field in fields if field["key"] != "part_name" or section != "PROFILE"))
    unit_weight = calculation.get("hardware_unit_weight_kg")
    length = weight = None
    if section == "PROFILE":
        length = _number(snapshot.get("raw_bar_length_m"), "原管长度")
        weight = _number(snapshot.get("raw_bar_weight_kg"), "原管单重")
        if (not length or not weight or length != _number(calculation.get("raw_bar_length_m"), "冻结原管长度")
                or weight != _number(calculation.get("raw_bar_weight_kg"), "冻结原管单重")):
            raise ValidationError({"sources": "原管长度或单重与保存的换算依据不一致，请核对原需求。"})
    return (material, section, snapshot["section_title_snapshot"], attributes, snapshot["source_unit_text"],
            length, weight,
            calculation.get("measurement_kind"), calculation.get("hardware_quantity_unit"),
            _number(unit_weight, "五金单重") if unit_weight else None)


def matches_combined_source(line, source):
    """分批保存时冻结用量；后续某款转外供只改变剩余需求。"""
    rows = line.calculation_snapshot.get("group_source_contributions")
    if not rows or "source_contributions" not in source.source_snapshot:
        return False
    saved_line = {
        "material_selection_snapshot": line.material_selection_snapshot, "calculation_snapshot": line.calculation_snapshot,
        "section_type_snapshot": line.section_type_snapshot, "section_title_snapshot": line.section_title_snapshot,
        "material_attributes_snapshot": line.material_attributes_snapshot, "source_unit_text": line.source_unit_text,
        "raw_bar_length_m": line.raw_bar_length_m, "raw_bar_weight_kg": line.raw_bar_weight_kg,
    }
    try:
        return (line.required_quantity == sum(_number(row["required_quantity"], "建议用量") for row in rows)
                and purchase_merge_key(saved_line) == purchase_merge_key(source.source_snapshot))
    except ValidationError:
        return False


def merge_purchase_snapshots(snapshots):
    result = deepcopy(snapshots[0])
    result["source_contributions"] = [
        {"bom_id": row["bom_id"], "bom_line_id": row["bom_line_id"],
         "component_identity": row["component_identity"], "product_line_id": row["product_line_id_snapshot"],
         "product_name": row["product_name_snapshot"], "product_color": row["product_color"],
         "product_specification": row["product_specification_snapshot"],
         "previous_group_line_id": row.get("previous_group_line_id"),
         "required_quantity": row["required_quantity"], "source_unit_text": row["source_unit_text"],
         "source_snapshot": row}
        for row in snapshots
    ]
    if len(snapshots) == 1:
        return result
    total = sum(_number(row["required_quantity"], "建议用量") for row in snapshots)
    if total >= Decimal("1e18"):
        raise ValidationError({"sources": "合并后的建议采购数量超出可保存范围。"})
    result.update(required_quantity=format(total, "f"), source_quantity_field="combined_bom_quantity",
                  source_quantity_text=format(total, "f"))
    calculation = result["calculation_snapshot"]
    inputs = [row["calculation_snapshot"] for row in snapshots]
    if result["section_type_snapshot"] == "PROFILE":
        # 不同产品的切割方案保存在各自的来源中，采购行仅汇总原管数量与长度、重量。
        totals = {
            "suggested_bar_count": sum(_number(row.get("suggested_bar_count"), "原管根数", whole=True) for row in inputs),
            "suggested_purchase_meters": pipe_meters_text(sum(_number(row.get("suggested_purchase_meters"), "原管米数") for row in inputs)),
            "suggested_purchase_weight_kg": format(total, ".4f"),
        }
        if totals["suggested_bar_count"] >= 2**63 or Decimal(totals["suggested_purchase_meters"]) >= Decimal("1e20"):
            raise ValidationError({"sources": "合并后的管材数量、重量或米数超出可保存范围。"})
        for key in ("pieces_per_product", "pieces_per_bar", "cutting_length_mm", "order_quantity",
                    "purchase_allowance_rule", "purchase_allowance_mode", "source_purchase_allowance_percent",
                    "calculation_version", "bom_id", "bom_line_id", "component_identity"):
            calculation.pop(key, None)
        for key in ("demand_pieces", "allowance_pieces", "base_purchase_bar_count", "purchase_allowance_bar_count"):
            if all(key in row for row in inputs):
                calculation[key] = sum(_number(row[key], "管材件数", whole=True) for row in inputs)
            else:
                calculation.pop(key, None)
        calculation.update(totals)
        result.update(totals)
    elif calculation.get("measurement_kind") == "HARDWARE_WEIGHT":
        calculation["hardware_suggested_weight_kg"] = format(total, ".4f")
        calculation["hardware_piece_quantity"] = (
            format(sum(_number(row["hardware_piece_quantity"], "五金件数") for row in inputs), "f")
            if all(row.get("hardware_piece_quantity") for row in inputs) else ""
        )
    return result
