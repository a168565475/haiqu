from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from rest_framework.exceptions import ValidationError


def hardware_reference_text(line):
    snapshot = line.get("calculation_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("measurement_kind") != "HARDWARE_WEIGHT":
        return ""
    unit = str(snapshot.get("hardware_quantity_unit") or "").strip()
    if unit.upper() not in {"个", "片", "件", "只", "颗", "粒", "枚", "支", "PCS", "PC", "PIECE", "PIECES"}:
        return ""
    try:
        weight = Decimal(str(line.get("quantity")))
        unit_weight = Decimal(str(snapshot.get("hardware_unit_weight_kg")))
        if not weight.is_finite() or not unit_weight.is_finite() or weight < 0 or unit_weight <= 0:
            return ""
        with localcontext() as context:
            context.prec = 64
            pieces = (weight / unit_weight).to_integral_value(rounding=ROUND_FLOOR)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    value = format(pieces, ",.0f")
    return f"约 {value} {unit}（参考）"


def hardware_sheet_fields(line):
    snapshot = getattr(line, "calculation_snapshot", None)
    if not isinstance(snapshot, dict) or snapshot.get("measurement_kind") != "HARDWARE_WEIGHT":
        return {}
    if str(line.source_unit_text).upper() != "KG":
        raise ValidationError({"lines": "五金重量采购的单位必须为 KG，请核对采购单。"})
    return {
        "measurement_kind": "HARDWARE_WEIGHT",
        "calculation_snapshot": deepcopy(snapshot),
        "price_unit": "元/kg",
    }


def hardware_sheet_sources(sheet, original_by_id):
    """从已确认采购识别五金，兼容旧采购表没有保存重量标志的情况。"""
    if not getattr(sheet, "purchase_order_id", None):
        return {}
    from .models import PurchaseOrderLine
    sources = {}
    for line in PurchaseOrderLine.objects.filter(
        purchase_order_id=sheet.purchase_order_id, supplier_id=sheet.supplier_id,
        calculation_snapshot__measurement_kind="HARDWARE_WEIGHT",
    ):
        source_id = str(line.pk)
        if source_id not in original_by_id:
            raise ValidationError({"lines": "五金采购表明细与采购单不一致，请重新核对采购来源。"})
        sources[source_id] = {
            **hardware_sheet_fields(line),
            "quantity": str(line.actual_purchase_quantity) if line.actual_purchase_quantity is not None else "",
            "unit": "KG",
            "unit_price": str(line.unit_price) if line.unit_price is not None else "",
        }
    if any(row.get("measurement_kind") == "HARDWARE_WEIGHT" and source_id not in sources
           for source_id, row in original_by_id.items()):
        raise ValidationError({"lines": "五金采购来源已变化，请重新核对采购单。"})
    return sources


def normalize_hardware_sheet_line(original, submitted, settlement_mode):
    if original.get("measurement_kind") != "HARDWARE_WEIGHT":
        return {}
    if settlement_mode == "ACTUAL_WEIGHT":
        raise ValidationError({"settlement_mode": "铆钉、垫片已按采购重量计价，请使用普通结算；重量调整请返回采购流程。"})
    for key in ("quantity", "unit_price", "unit"):
        value = submitted.get(key, original.get(key))
        expected = original.get(key)
        if key == "unit":
            equal = str(value).upper() == "KG" and str(expected).upper() == "KG"
        else:
            try:
                equal = Decimal(str(value)) == Decimal(str(expected))
            except (InvalidOperation, ValueError, TypeError):
                equal = value in (None, "") and expected in (None, "")
        if not equal:
            raise ValidationError({"lines": "五金重量、单位和每公斤单价已由采购确认，请返回采购流程调整。"})
    return {key: deepcopy(original[key]) for key in ("measurement_kind", "calculation_snapshot", "price_unit")}
