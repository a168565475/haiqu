"""按余额实际重量分摊整根领用，最后一次领用扣清余重。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from .stock_services import InventoryStockValidationError


def actual_pipe_weight(value):
    if isinstance(value, (bool, float)):
        raise InventoryStockValidationError("管材实际重量必须使用精确十进制数。", code="PIPE_BALANCE_INVALID")
    try:
        weight = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise InventoryStockValidationError("管材实际重量缺失或格式无效。", code="PIPE_BALANCE_INVALID") from error
    if (not weight.is_finite() or weight < 0 or weight > Decimal("999999999999999999.9999")
            or weight.as_tuple().exponent < -4):
        raise InventoryStockValidationError("管材实际重量须为非负有限数字且最多保留4位小数。", code="PIPE_BALANCE_INVALID")
    return weight


def issued_pipe_weight(*, available_roots, available_weight_kg, issued_roots):
    try:
        roots = Decimal(available_roots)
        issued = Decimal(issued_roots)
        weight = Decimal(available_weight_kg)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise InventoryStockValidationError("管材实际重量或根数缺失，请核对库存。", code="PIPE_BALANCE_INVALID") from error
    if (not roots.is_finite() or not issued.is_finite() or roots <= 0 or issued <= 0
            or roots != roots.to_integral_value() or issued != issued.to_integral_value() or issued > roots):
        raise InventoryStockValidationError("领用根数必须是库存范围内的正整数。", code="PIPE_BALANCE_INVALID")
    if not weight.is_finite() or weight < 0:
        raise InventoryStockValidationError("管材实际库存重量不能为负数或非有限数字。", code="PIPE_BALANCE_INVALID")
    if issued == roots:
        return weight
    with localcontext() as context:
        context.prec = 64
        return (weight * issued / roots).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def returned_pipe_weight(*, original, adjustments, returned_roots):
    """退回原出库剩余的实际重量；更正的追加出库和已退库都计入冻结凭证。"""
    if original.direction != "OUT":
        raise InventoryStockValidationError("退料缺少原出库凭据。", code="PIPE_BALANCE_INVALID")
    adjustments = list(adjustments)
    if original.weight_quantity is None:
        if any(row.weight_quantity is not None for row in adjustments):
            raise InventoryStockValidationError("原出库缺少实际重量，不能根据后续记录补造。", code="PIPE_BALANCE_INVALID")
        return None
    roots = original.quantity
    weight = actual_pipe_weight(original.weight_quantity)
    for row in adjustments:
        if row.direction not in {"IN", "OUT"}:
            raise InventoryStockValidationError("历史退料或更正方向无效。", code="PIPE_BALANCE_INVALID")
        delta = actual_pipe_weight(row.weight_quantity)
        sign = 1 if row.direction == "OUT" else -1
        roots += sign * row.quantity
        weight += sign * delta
        if roots < 0 or weight < 0:
            raise InventoryStockValidationError("历史退料超过原出库实际数量或重量。", code="PIPE_BALANCE_INVALID")
    return issued_pipe_weight(available_roots=roots, available_weight_kg=weight, issued_roots=returned_roots)
