"""件数库存的实际重量账；旧库存无重量时保持未知，不能补造。"""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from .hardware_receipts import PIECE_UNITS, KG_UNITS, _number
from rest_framework.exceptions import ValidationError


def catalog_piece_weight_identity(identity):
    selected = identity.get("identity_snapshot", {}).get("material_selection_snapshot", {})
    return selected.get("category_key") == "HARDWARE" and str(selected.get("unit_name", "")).upper() in PIECE_UNITS | KG_UNITS


def piece_weight_change(*, before_quantity, before_weight, quantity, direction, weight_quantity=None, quantity_unit=""):
    if str(quantity_unit).upper() in KG_UNITS:
        if (before_weight is not None and before_weight != before_quantity) or (weight_quantity is not None and weight_quantity != quantity):
            raise ValidationError({"weight_quantity": "KG库存数量与实际重量不一致，不能继续记账。"})
        before_weight = _number(before_quantity, "weight_quantity", allow_zero=True)
        weight = _number(quantity, "weight_quantity", allow_zero=True)
        return before_weight, weight, before_weight + weight if direction == "IN" else before_weight - weight
    if before_weight is not None:
        before_weight = _number(before_weight, "weight_quantity", allow_zero=True)
    if direction == "IN":
        if weight_quantity is not None:
            weight_quantity = _number(weight_quantity, "weight_quantity", allow_zero=True)
            _number(quantity, "quantity", whole=True, allow_zero=True)
        if before_quantity == 0 and before_weight is None and weight_quantity is not None:
            before_weight = Decimal("0")
        after_weight = (before_weight + weight_quantity
                        if before_weight is not None and weight_quantity is not None else None)
        return before_weight, weight_quantity, after_weight
    if weight_quantity is not None:
        weight = _number(weight_quantity, "weight_quantity", allow_zero=True)
        _number(quantity, "quantity", whole=True, allow_zero=True)
        if before_weight is None:
            return None, weight, None
        if weight > before_weight:
            raise ValidationError({"weight_quantity": "原收货库区库存重量不足，请先核对领用或办理退料。"})
        return before_weight, weight, before_weight - weight
    if before_weight is None:
        return None, None, None
    _number(quantity, "quantity", whole=True)
    _number(before_quantity, "quantity", whole=True)
    if quantity == before_quantity:
        weight = before_weight
    else:
        with localcontext() as context:
            context.prec = 64
            weight = (before_weight * quantity / before_quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return before_weight, weight, before_weight - weight
