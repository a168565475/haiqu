"""管材首次产出额度：报工、订单净需求、实际投入共同封顶。"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


MAX_PIECES = 99_999_999_999_999


class TubeQuantityError(ValueError):
    pass


def whole_pieces(value, label='支数'):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise TubeQuantityError(f'{label}必须是整数支数。')
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TubeQuantityError(f'{label}不是有效数字。') from exc
    if not number.is_finite() or number < 0 or number > MAX_PIECES or number != number.to_integral_value():
        raise TubeQuantityError(f'{label}必须是范围内的非负整数支数。')
    return int(number)


@dataclass(frozen=True)
class TubeAllowance:
    required: int
    issued: int
    reported_minimum: int
    received: int
    dispatched: int
    reserved: int
    used: int
    remaining: int
    report_protected_usage: int


def calculate_tube_allowance(*, order_required, issued, operation_totals,
                             received=0, dispatched=0, reserved=0, legacy_dispatched=0):
    if not isinstance(operation_totals, dict) or not operation_totals:
        raise TubeQuantityError('请先完善工价方案，不能用手工完成量替代报工。')
    if any(not isinstance(key, str) or not key.strip() or key != key.strip() for key in operation_totals):
        raise TubeQuantityError('工序必须有唯一稳定身份。')
    operations = [whole_pieces(value, '工序累计报工') for value in operation_totals.values()]
    required = whole_pieces(order_required, '部位净需求')
    issued = whole_pieces(issued, '实际领用投入')
    received = whole_pieces(received, '累计首次入库')
    dispatched = whole_pieces(dispatched, '累计直接交接')
    reserved = whole_pieces(reserved, '有效待发预留')
    legacy = whole_pieces(legacy_dispatched, '历史接续交接')
    if legacy > dispatched:
        raise TubeQuantityError('历史接续量不能大于实际直接交接量。')
    used = whole_pieces(received + dispatched + reserved, '累计占用')
    reported = min(operations)
    return TubeAllowance(required, issued, reported, received, dispatched, reserved, used,
                         max(0, min(required, issued, reported) - used), used - legacy)


def assert_report_basis(allowance):
    if allowance.reported_minimum < allowance.report_protected_usage:
        raise TubeQuantityError(
            f'最低报工仅{allowance.reported_minimum}支，不能低于已入库、已直接交接和有效预留'
            f'合计{allowance.report_protected_usage}支。')
