"""目录材料收货复制采购事实；质检后的合格数量才计入公共库存。"""
from rest_framework.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal

from apps.material_catalog.saved_selection import validate_saved_material
from .catalog_stock_identity import build_catalog_stock_identity
from .hardware_receipts import hardware_receipt_values, is_hardware_weight, validate_hardware_inbound
from .pipe_receipts import weight_pipe_receipt_quantities


def catalog_receipt_values(*, purchase_line, item):
    from apps.procurement.catalog_materials import purchase_catalog_selection
    selected = purchase_catalog_selection(purchase_line)
    if is_hardware_weight(purchase_line):
        return {"material_catalog_id": purchase_line.material_catalog_id, "material_selection_snapshot": selected,
                **hardware_receipt_values(purchase_line=purchase_line, item=item, piece_unit=selected["unit_name"])}
    if selected["category_key"] == "TUBE" and selected["processing_state"] == "RAW":
        from apps.procurement.pipe_purchase import pipe_meters
        length = purchase_line.raw_bar_length_m
        if item.get("raw_bar_length_m") is not None and item["raw_bar_length_m"] != length:
            raise ValidationError({"raw_bar_length_m": "实到单根长度与采购保存长度不同，请核对原单。"})
        weight_mode = purchase_line.source_unit_text in {"KG", "kg", "千克"}
        snapshot = purchase_line.calculation_snapshot or {}
        if weight_mode:
            weight, bar_weight, roots, snapshot = weight_pipe_receipt_quantities(purchase_line, item)
            roots, meters = pipe_meters(roots, length, field="received_bar_count")
            item["received_weight_kg"] = weight
        else:
            roots, meters = pipe_meters(item.get("received_bar_count"), length, field="received_bar_count")
        item["received_quantity"] = meters
        return {"material_catalog_id": purchase_line.material_catalog_id, "material_selection_snapshot": selected,
            "measurement_kind": "PIPE", "raw_bar_length_m": length,
            "bar_weight_kg": (bar_weight if weight_mode else None), "received_bar_count": roots,
            "accepted_bar_count": roots, "return_bar_count": 0,
            "received_weight_kg": (weight if weight_mode else None),
            "accepted_weight_kg": (weight if weight_mode else None),
            "return_weight_kg": (Decimal("0") if weight_mode else None),
            "calculation_snapshot": {**snapshot, "received_bar_count": roots,
                                      "received_meters": str(meters),
                                      **({"received_weight_kg": format(weight, ".4f")} if weight_mode else {})}}
    if item.get("received_bar_count") is not None or item.get("raw_bar_length_m") is not None:
        raise ValidationError({"items": "新材料请按所选单位填写到货数量；采购根米计价参数不作为收货换算。"})
    hardware_weight = (purchase_line.calculation_snapshot or {}).get("measurement_kind") == "HARDWARE_WEIGHT"
    quantity = item.get("received_quantity")
    if quantity is None or quantity <= 0:
        raise ValidationError({"received_quantity": "请填写所选单位下的实际到货数量。"})
    if not hardware_weight and selected["unit_name"] in {"根", "支", "套"} and quantity != quantity.to_integral_value():
        raise ValidationError({"received_quantity": "按根、支、套收货须填写整数。"})
    return {"material_catalog_id": purchase_line.material_catalog_id, "material_selection_snapshot": selected,
            "calculation_snapshot": purchase_line.calculation_snapshot, "measurement_kind": "OTHER"}


def validate_catalog_inbound(line):
    selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
    pipe = selected["category_key"] == "TUBE" and selected["processing_state"] == "RAW"
    hardware_weight = (line.calculation_snapshot or {}).get("measurement_kind") == "HARDWARE_WEIGHT"
    if hardware_weight:
        validate_hardware_inbound(line, selected["unit_name"])
    expected_unit = ("KG" if line.received_weight_kg is not None else "米") if pipe else ("KG" if hardware_weight else selected["unit_name"])
    if expected_unit != line.source_unit_text_snapshot:
        raise ValidationError({"items": "入库数量单位与保存材料不一致。"})
    if pipe and expected_unit == "KG":
        weights = (line.received_weight_kg, line.accepted_weight_kg, line.return_weight_kg)
        if (any(value is None or not value.is_finite() or value < 0 for value in weights)
                or weights[0] <= 0 or weights[0] != weights[1] + weights[2]):
            raise ValidationError({"items": "管材到货、合格和退货重量缺失或不一致。"})
    if line.purchase_order_line_id:
        purchase = line.purchase_order_line
        if purchase.material_catalog_id != line.material_catalog_id or purchase.material_selection_snapshot != selected:
            raise ValidationError({"items": "入库材料与保存采购来源不一致。"})
    expected = "MATERIAL" if selected["processing_state"] == "RAW" else "SEMI_FINISHED"
    if line.zone.status != "ACTIVE" or line.zone.warehouse.status != "ACTIVE" or line.zone.warehouse.warehouse_type != expected:
        raise ValidationError({"zone_id": "入库库区与原料/半成品状态不匹配或已停用。"})
    if not pipe and not hardware_weight and selected["unit_name"] in {"根", "支", "套"} and any(value != value.to_integral_value() for value in
                                              (line.received_quantity, line.accepted_quantity, line.return_quantity)):
        raise ValidationError({"items": "按根、支、套收货和质检数量必须为整数。"})
    return build_catalog_stock_identity(material_catalog_id=line.material_catalog_id, material_selection_snapshot=selected,
        raw_bar_length_m=line.raw_bar_length_m if pipe else None)


@transaction.atomic
def credit_catalog_inbound(*, line, actor_employee):
    from .public_stock_services import credit_public_stock
    from .models import MaterialInbound
    identity = validate_catalog_inbound(line)
    if not MaterialInbound.objects.select_for_update().filter(pk=line.inbound_id, status="CONFIRMED").exists():
        raise ValidationError({"items": "入库尚未确认，不能记入可用库存。"})
    purchase = line.purchase_order_line
    contributions = (purchase.calculation_snapshot or {}).get("group_source_contributions", []) if purchase else []
    shared_product = len({row["product_line_id"] for row in contributions}) > 1
    pipe_weight_mode = line.measurement_kind == "PIPE" and line.source_unit_text_snapshot == "KG"
    return credit_public_stock(identity=identity, zone=line.zone, quantity=line.accepted_bar_count if line.measurement_kind == "PIPE" else line.accepted_quantity,
        source_type="MATERIAL_INBOUND", source_id=line.inbound_id, source_line_id=line.pk,
        actor_employee=actor_employee, production_task=purchase.purchase_order.production_task_id if purchase else None,
        product_line=purchase.product_line_id_snapshot if purchase and not shared_product else None,
        bom_line=purchase.bom_line_id if purchase and len(contributions) <= 1 else None,
        bar_weight_kg=line.bar_weight_kg if pipe_weight_mode else None,
        weight_quantity=line.accepted_weight_kg if pipe_weight_mode or is_hardware_weight(line) else None,
        snapshot={"material_selection_snapshot": line.material_selection_snapshot, "inbound_number": line.inbound.inbound_number,
                  **({"group_source_contributions": contributions} if contributions else {}),
                  "purchase_order_number": line.purchase_order_number_snapshot,
                  "unit_name": line.material_selection_snapshot["unit_name"] if is_hardware_weight(line) else line.source_unit_text_snapshot,
                  **({"purchase_unit": line.source_unit_text_snapshot, "accepted_weight_kg": str(line.accepted_weight_kg),
                      "measurement_kind": "HARDWARE_WEIGHT"} if is_hardware_weight(line) else {}),
                  **({"bar_weight_kg": str(line.bar_weight_kg) if line.bar_weight_kg is not None else None,
                      "accepted_weight_kg": str(line.accepted_weight_kg)} if pipe_weight_mode else {})})
