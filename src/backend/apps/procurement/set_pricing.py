from decimal import Decimal

from rest_framework.exceptions import ValidationError


def line_set_pricing(line):
    return (line.calculation_snapshot or {}).get("set_pricing")


def material_calculation_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if key not in ("set_pricing", "set_pricing_review")}


def apply_set_pricing(line, submitted):
    """物料数量仍走收货单位。套价只计在组内指定行，物料本身没有散买价。"""
    from .services import _money

    pricing = submitted.get("set_pricing", line_set_pricing(line))
    if (pricing or line.unit_price is not None) and "set_pricing_review" in (line.calculation_snapshot or {}):
        line.calculation_snapshot = dict(line.calculation_snapshot)
        del line.calculation_snapshot["set_pricing_review"]
    if not pricing:
        if line_set_pricing(line):
            line.calculation_snapshot = dict(line.calculation_snapshot)
            del line.calculation_snapshot["set_pricing"]
        return
    if not line.purchase_group_line_id:
        raise ValidationError({"lines": "只有从采购需求创建的材料批次可以按套采购。"})
    if line.unit_price is not None:
        raise ValidationError({"lines": f"第 {line.line_number} 行已按套计价，请清空单件价格。"})
    if not line.actual_purchase_quantity:
        raise ValidationError({"lines": f"第 {line.line_number} 行套餐材料须填写实际采购数量。"})
    pricing = {"anchor_id": str(pricing["anchor_id"]), "quantity": pricing["quantity"],
               "unit_price": format(Decimal(pricing["unit_price"]), ".4f")}
    line.calculation_snapshot = {**(line.calculation_snapshot or {}), "set_pricing": pricing}
    line.amount = (_money(pricing["quantity"] * Decimal(pricing["unit_price"]))
                   if str(line.purchase_group_line_id) == pricing["anchor_id"] else Decimal("0"))


def validate_set_members(lines):
    groups = {}
    for line in lines:
        pricing = line_set_pricing(line)
        if pricing:
            groups.setdefault(pricing["anchor_id"], []).append(line)
    for anchor_id, members in groups.items():
        if len(members) < 2 or not any(str(line.purchase_group_line_id) == anchor_id for line in members):
            raise ValidationError({"lines": "每套须包含发起行和至少一个其他部件，请重新选择套餐材料。"})
        first = members[0]
        for line in members[1:]:
            if (line_set_pricing(line) != line_set_pricing(first) or line.supplier_id != first.supplier_id
                    or line.delivery_date != first.delivery_date):
                raise ValidationError({"lines": "同一套餐的套数、套价、供应商和交期必须一致。"})


def set_sheet_fields(line, anchors):
    pricing = line_set_pricing(line)
    if not pricing:
        return {}
    anchor = anchors[pricing["anchor_id"]]
    is_anchor = anchor.pk == line.pk
    quantity = format(line.actual_purchase_quantity, "f")
    return {
        "set_pricing": pricing, "is_set_anchor": is_anchor,
        "set_line_number": anchor.line_number,
        "physical_quantity": quantity, "physical_unit": line.source_unit_text,
        "quantity": str(pricing["quantity"]) if is_anchor else quantity,
        "unit": "套" if is_anchor else line.source_unit_text,
        "price_unit": "元/套" if is_anchor else "已含套价",
        "unit_price": pricing["unit_price"] if is_anchor else "",
    }


def sheet_set_description(line):
    if not line.get("set_pricing"):
        return ""
    label = f"套餐 {line['set_line_number']}"
    quantity = format(Decimal(line["physical_quantity"]), "f")
    if "." in quantity:
        quantity = quantity.rstrip("0").rstrip(".")
    return f"{label} · 实物 {quantity} {line['physical_unit']}" if line["is_set_anchor"] else f"{label} · 已含套价"
