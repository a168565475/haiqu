"""五金以实称公斤入库，按采购冻结单重向下折算原单位参考数量。"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from rest_framework.exceptions import ValidationError


PIECE_UNITS = {"个", "片", "件", "只", "颗", "粒", "枚", "支", "PCS", "PC", "PIECE", "PIECES"}
KG_UNITS = {"KG", "kg", "千克", "公斤"}


def is_hardware_weight(line):
    snapshot = getattr(line, "calculation_snapshot", None)
    if snapshot is None:
        return False
    if not isinstance(snapshot, dict):
        raise ValidationError({"calculation_snapshot": "材料计量快照格式无效，请核对原采购来源。"})
    return snapshot.get("measurement_kind") == "HARDWARE_WEIGHT"


def hardware_piece_unit(line):
    snapshot = getattr(line, "calculation_snapshot", None) or {}
    if snapshot.get("piece_unit"):
        return snapshot["piece_unit"]
    selected = getattr(line, "material_selection_snapshot", None) or {}
    if selected:
        return selected.get("unit_name", "")
    material = getattr(line, "raw_material_information", None)
    if material is not None:
        return material.unit.unit_name
    if snapshot.get("unit_id"):
        from apps.reference_data.models import ProductionUnit
        return ProductionUnit.objects.filter(pk=snapshot["unit_id"]).values_list("unit_name", flat=True).first() or ""
    return snapshot.get("hardware_quantity_unit", "")


def _number(value, field, *, whole=False, allow_zero=False):
    try:
        if isinstance(value, (bool, float)):
            raise ValueError
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError({field: "参考数量无效，请核对重量及采购保存的单重。" if whole else "请填写实际重量（KG）。"}) from error
    if (not number.is_finite() or number < 0 or (not allow_zero and number == 0)
            or number > Decimal("99999999999999.9999")
            or (whole and number != number.to_integral_value())
            or (not whole and number.as_tuple().exponent < -4)):
        raise ValidationError({field: "参考数量须为有效整数。" if whole else "重量须为有效非负数字，最多4位小数。"})
    return number


def _unit_weight(snapshot):
    if not isinstance(snapshot, dict):
        raise ValidationError({"items": "采购保存的单重快照格式无效，请核对原采购来源。"})
    try:
        value = snapshot.get("hardware_unit_weight_kg")
        if isinstance(value, (bool, float)):
            raise ValueError
        weight = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError({"items": "采购保存的单个重量缺失，请核对原采购来源后重新确认。"}) from error
    if not weight.is_finite() or weight <= 0 or weight.as_tuple().exponent < -8:
        raise ValidationError({"items": "采购保存的单个重量无效，不能自动折算参考数量。"})
    return weight


def _reference_quantity(weight, snapshot):
    with localcontext() as context:
        context.prec = 64
        quantity = (weight / _unit_weight(snapshot)).to_integral_value(rounding=ROUND_FLOOR)
    return _number(quantity, "reference_quantity", whole=True, allow_zero=True)


def hardware_receipt_values(*, purchase_line, item, piece_unit):
    native_kg = str(piece_unit).upper() in KG_UNITS
    if not native_kg and str(piece_unit).upper() not in PIECE_UNITS:
        raise ValidationError({"items": "五金公斤采购缺少明确的个/片库存单位，请先核对材料的库存单位。"})
    if purchase_line.source_unit_text not in KG_UNITS:
        raise ValidationError({"items": "五金计重采购的来源单位必须是KG。"})
    if item.get("received_bar_count") is not None or item.get("raw_bar_length_m") is not None:
        raise ValidationError({"items": "铆钉、垫片请填写实际公斤数，不使用管材根数或长度。"})
    weight = _number(item.get("received_weight_kg", item.get("received_quantity")), "received_weight_kg")
    # 参考数量由采购时冻结单重权威折算；客户端旧件数输入不能覆盖。
    pieces = weight if native_kg else _reference_quantity(weight, purchase_line.calculation_snapshot)
    item["received_quantity"] = pieces
    item["received_weight_kg"] = weight
    return {"measurement_kind": "OTHER", "received_weight_kg": weight,
            "accepted_weight_kg": weight, "return_weight_kg": Decimal("0"),
            "calculation_snapshot": {**purchase_line.calculation_snapshot, "piece_unit": piece_unit, "quantity_basis": "NATIVE_KG" if native_kg else "WEIGHT_FLOOR",
                                     "received_piece_count": None if native_kg else str(pieces), "received_weight_kg": str(weight)}}


def quality_hardware_quantities(line, item):
    if item.get("return_bar_count") is not None:
        raise ValidationError({"items": "铆钉、垫片请填写实际退货重量，不使用管材根数。"})
    native_kg = str((line.calculation_snapshot or {}).get("piece_unit", "")).upper() in KG_UNITS
    weight = _number(item.get("return_weight_kg", item.get("return_quantity")), "return_weight_kg", allow_zero=True)
    received = _number(line.received_quantity, "received_quantity", whole=not native_kg, allow_zero=not native_kg)
    received_weight = _number(line.received_weight_kg, "received_weight_kg")
    if weight > received_weight:
        raise ValidationError({"items": "退货重量不能超过本批实际到货重量。"})
    accepted_weight = received_weight - weight
    accepted = accepted_weight if native_kg else received if weight == 0 else _reference_quantity(accepted_weight, line.calculation_snapshot)
    pieces = received - accepted
    line.return_weight_kg = weight
    line.accepted_weight_kg = accepted_weight
    return pieces


def validate_hardware_inbound(line, piece_unit):
    native_kg = str(piece_unit).upper() in KG_UNITS
    if (not native_kg and str(piece_unit).upper() not in PIECE_UNITS) or line.source_unit_text_snapshot not in KG_UNITS:
        raise ValidationError({"items": "五金入库须同时有明确的个/片库存单位和KG采购单位。"})
    if (line.calculation_snapshot or {}).get("piece_unit") != piece_unit:
        raise ValidationError({"items": "五金入库的参考数量单位缺失或与原材料不一致，请核对原入库记录。"})
    counts = [_number(getattr(line, f"{name}_quantity"), f"{name}_quantity", whole=not native_kg, allow_zero=not native_kg or name != "received")
              for name in ("received", "accepted", "return")]
    weights = [_number(getattr(line, f"{name}_weight_kg"), f"{name}_weight_kg", allow_zero=name != "received")
               for name in ("received", "accepted", "return")]
    if counts[0] != counts[1] + counts[2] or weights[0] != weights[1] + weights[2]:
        raise ValidationError({"items": "五金到货、合格、退货的参考数量或重量不一致。"})
    if native_kg and counts != weights:
        raise ValidationError({"items": "KG库存数量须与实际公斤数一致。"})
    if not native_kg:
        expected_received = _reference_quantity(weights[0], line.calculation_snapshot)
        expected_accepted = counts[0] if weights[2] == 0 else _reference_quantity(weights[1], line.calculation_snapshot)
        if counts[0] != expected_received or counts[1] != expected_accepted:
            raise ValidationError({"items": "五金参考数量与采购冻结单重的向下取整结果不一致。"})
