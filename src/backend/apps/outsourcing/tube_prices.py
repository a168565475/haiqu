"""加工单价按支计，历史未录入价格保持未知。"""
from decimal import Decimal, localcontext


def line_price_data(line):
    price = line.unit_price
    with localcontext() as context:
        context.prec = 40
        return {'unit_price': format(price, '.2f') if price is not None else None,
                'planned_amount': format(Decimal(line.quantity) * price, '.2f') if price is not None else None}


def planned_amount(lines):
    lines = list(lines)
    if not lines or any(line.unit_price is None for line in lines):
        return None
    with localcontext() as context:
        context.prec = 40
        return format(sum((Decimal(line.quantity) * line.unit_price for line in lines), Decimal(0)), '.2f')
