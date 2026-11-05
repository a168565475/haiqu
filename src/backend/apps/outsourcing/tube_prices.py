"""管材委外按支或按平方米计价；历史未知面积和价格保持未知。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext

from .tube_models import PriceUnit


AREA_QUANTUM = Decimal('0.0001')
MONEY_QUANTUM = Decimal('0.01')


def parse_unit_area(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        area = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not area.is_finite() or area <= 0:
        return None
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        area = area.quantize(AREA_QUANTUM)
    return area if area > 0 else None


def _line_area(line):
    if line.unit_area_sqm is None:
        return None
    return Decimal(line.quantity) * line.unit_area_sqm


def _line_amount(line):
    if line.unit_price is None:
        return None
    if line.price_unit == PriceUnit.SQUARE_METER:
        area = _line_area(line)
        return None if area is None else area * line.unit_price
    return Decimal(line.quantity) * line.unit_price


def _format(value, quantum):
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        return format(value.quantize(quantum), 'f')


def line_area_data(line):
    return {
        'price_unit': line.price_unit,
        'unit_area_sqm': _format(line.unit_area_sqm, AREA_QUANTUM),
        'line_area_sqm': _format(_line_area(line), AREA_QUANTUM),
    }


def line_price_data(line):
    return {
        'unit_price': _format(line.unit_price, MONEY_QUANTUM),
        'planned_amount': _format(_line_amount(line), MONEY_QUANTUM),
    }


def total_area(lines):
    lines = list(lines)
    areas = [_line_area(line) for line in lines]
    if not lines or any(area is None for area in areas):
        return None
    return _format(sum(areas, Decimal(0)), AREA_QUANTUM)


def planned_amount(lines):
    lines = list(lines)
    amounts = [_line_amount(line) for line in lines]
    if not lines or any(amount is None for amount in amounts):
        return None
    return _format(sum(amounts, Decimal(0)), MONEY_QUANTUM)
