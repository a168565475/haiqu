"""目录材料收货复制采购事实；质检后的合格数量才计入公共库存。"""
from rest_framework.exceptions import ValidationError
from django.db import transaction

from apps.material_catalog.saved_selection import validate_saved_material
from .catalog_stock_identity import build_catalog_stock_identity


def catalog_receipt_values(*, purchase_line, item):
    from apps.procurement.catalog_materials import purchase_catalog_selection
    selected = purchase_catalog_selection(purchase_line)
    if selected["category_key"] == "TUBE" and selected["processing_state"] == "RAW":
        from apps.procurement.pipe_purchase import pipe_meters
        length = purchase_line.raw_bar_length_m
        if item.get("raw_bar_length_m") is not None and item["raw_bar_length_m"] != length:
            raise ValidationError({"raw_bar_length_m": "实到单根长度与采购保存长度不同，请核对原单。"})
        roots, meters = pipe_meters(item.get("received_bar_count"), length, field="received_bar_count")
        item["received_quantity"] = meters
        return {"material_catalog_id": purchase_line.material_catalog_id, "material_selection_snapshot": selected,
            "measurement_kind": "PIPE", "raw_bar_length_m": length, "received_bar_count": roots,
            "accepted_bar_count": roots, "return_bar_count": 0,
            "calculation_snapshot": {**purchase_line.calculation_snapshot, "received_bar_count": roots, "received_meters": str(meters)}}
    if item.get("received_bar_count") is not None or item.get("raw_bar_length_m") is not None:
        raise ValidationError({"items": "新材料请按所选单位填写到货数量；采购根米计价参数不作为收货换算。"})
    quantity = item.get("received_quantity")
    if quantity is None or quantity <= 0:
        raise ValidationError({"received_quantity": "请填写所选单位下的实际到货数量。"})
    if selected["unit_name"] in {"根", "支", "套"} and quantity != quantity.to_integral_value():
        raise ValidationError({"received_quantity": "按根、支、套收货须填写整数。"})
    return {"material_catalog_id": purchase_line.material_catalog_id, "material_selection_snapshot": selected,
            "calculation_snapshot": purchase_line.calculation_snapshot, "measurement_kind": "OTHER"}


def validate_catalog_inbound(line):
    selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
    pipe = selected["category_key"] == "TUBE" and selected["processing_state"] == "RAW"
    if ("米" if pipe else selected["unit_name"]) != line.source_unit_text_snapshot:
        raise ValidationError({"items": "入库数量单位与保存材料不一致。"})
    if line.purchase_order_line_id:
        purchase = line.purchase_order_line
        if purchase.material_catalog_id != line.material_catalog_id or purchase.material_selection_snapshot != selected:
            raise ValidationError({"items": "入库材料与保存采购来源不一致。"})
    expected = "MATERIAL" if selected["processing_state"] == "RAW" else "SEMI_FINISHED"
    if line.zone.status != "ACTIVE" or line.zone.warehouse.status != "ACTIVE" or line.zone.warehouse.warehouse_type != expected:
        raise ValidationError({"zone_id": "入库库区与原料/半成品状态不匹配或已停用。"})
    if not pipe and selected["unit_name"] in {"根", "支", "套"} and any(value != value.to_integral_value() for value in
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
    return credit_public_stock(identity=identity, zone=line.zone, quantity=line.accepted_bar_count if line.measurement_kind == "PIPE" else line.accepted_quantity,
        source_type="MATERIAL_INBOUND", source_id=line.inbound_id, source_line_id=line.pk,
        actor_employee=actor_employee, production_task=purchase.purchase_order.production_task_id if purchase else None,
        product_line=purchase.product_line_id_snapshot if purchase else None, bom_line=purchase.bom_line_id if purchase else None,
        snapshot={"material_selection_snapshot": line.material_selection_snapshot, "inbound_number": line.inbound.inbound_number,
                  "purchase_order_number": line.purchase_order_number_snapshot, "unit_name": line.source_unit_text_snapshot})
