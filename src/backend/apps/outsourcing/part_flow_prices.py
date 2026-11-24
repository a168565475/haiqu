"""部位按实际回货计费；历史回货未冻结价格时保持未知。"""
from decimal import Decimal, InvalidOperation, localcontext

from .tube_prices import MONEY_QUANTUM, _format


PART_RECEIPT = 'PART_RECEIPT'


def receipt_price_snapshot(line):
    return {'billing_basis': PART_RECEIPT, 'unit_price': _format(line.unit_price, MONEY_QUANTUM),
            'price_unit': 'PIECE', 'unit': line.snapshot.get('unit')}


def receipt_price_data(line):
    snapshot = line.snapshot or {}
    price = snapshot.get('unit_price') if snapshot.get('billing_basis') == PART_RECEIPT else None
    try:
        value = Decimal(price) if isinstance(price, str) else None
    except InvalidOperation:
        value = None
    if value is None or not value.is_finite() or value < 0 or value >= Decimal('100000000000000'):
        price, amount = None, None
    else:
        price = _format(value, MONEY_QUANTUM)
        with localcontext() as context:
            context.prec = 64
            amount = value * line.received_quantity
    return {'billing_basis': PART_RECEIPT, 'unit_price': price, 'price_unit': 'PIECE',
            'received_amount': _format(amount, MONEY_QUANTUM)}


def receipt_amount_summary(lines):
    amounts = [receipt_price_data(line)['received_amount'] for line in lines]
    with localcontext() as context:
        context.prec = 64
        amount = sum((Decimal(value) for value in amounts if value is not None), Decimal(0))
    return {'received_amount': _format(amount, MONEY_QUANTUM),
            'has_unknown_receipt_amount': any(value is None for value in amounts)}
