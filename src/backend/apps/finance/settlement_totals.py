"""财务唯一金额口径；只计算 Decimal，不查询数据库或接收前端合计。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Iterable


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("99999999999999999999.99")
MAX_UNIT_PRICE = Decimal("99999999999999.9999")


class SettlementAmountError(ValueError):
    def __init__(self, code, message, *, meta=None):
        super().__init__(message)
        self.code = code
        self.meta = meta or {}


def checked_money(value: Decimal) -> Decimal:
    """外部输入先由 Serializer 转换；内部禁止浮点及隐式舍入。"""
    if not isinstance(value, Decimal):
        raise TypeError("财务计算必须使用 Decimal。")
    if not value.is_finite() or value < ZERO or value > MAX_AMOUNT:
        raise SettlementAmountError("AMOUNT_OUT_OF_RANGE", "金额必须在允许的非负范围内。")
    with localcontext() as context:
        context.prec = 64
        rounded = value.quantize(CENT)
    if rounded != value:
        raise SettlementAmountError("AMOUNT_OUT_OF_RANGE", "到账、费用、折让最多保留两位小数。")
    return rounded


def statement_line_amount(quantity: int | Decimal, unit_price: Decimal) -> Decimal:
    if isinstance(quantity, bool) or not isinstance(quantity, (int, Decimal)):
        raise TypeError("数量必须为整数或 Decimal。")
    quantity = Decimal(quantity)
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise SettlementAmountError("VALIDATION_ERROR", "来源数量必须为正整数整行数量。")
    if not isinstance(unit_price, Decimal):
        raise TypeError("对账单价必须使用 Decimal。")
    if not unit_price.is_finite() or unit_price <= 0 or unit_price > MAX_UNIT_PRICE:
        raise SettlementAmountError("AMOUNT_OUT_OF_RANGE", "对账单价必须为允许范围内的正数。")
    with localcontext() as context:
        context.prec = 64
        if unit_price.quantize(Decimal("0.0001")) != unit_price:
            raise SettlementAmountError("AMOUNT_OUT_OF_RANGE", "对账单价最多保留四位小数。")
        product = quantity * unit_price
        if product > MAX_AMOUNT + CENT:
            raise SettlementAmountError("AMOUNT_OUT_OF_RANGE", "明细金额超出允许范围。")
        return checked_money(product.quantize(CENT, rounding=ROUND_HALF_UP))


def sum_money(values: Iterable[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        return checked_money(sum((checked_money(value) for value in values), ZERO))


def statement_amount(lines: Iterable[tuple[int | Decimal, Decimal]]) -> Decimal:
    amounts = [statement_line_amount(quantity, price) for quantity, price in lines]
    if not amounts:
        raise SettlementAmountError("VALIDATION_ERROR", "对账单至少选择一条来源产品明细。")
    return sum_money(amounts)


@dataclass(frozen=True)
class SettlementTotals:
    amount: Decimal
    goods_cash_amount: Decimal
    allocated_deposit_amount: Decimal
    discount_amount: Decimal
    deposit_amount: Decimal
    deposit_cash_amount: Decimal
    fee_amount: Decimal
    settled_amount: Decimal
    outstanding_amount: Decimal
    available_deposit_amount: Decimal
    bank_received_amount: Decimal
    settlement_status: str


def calculate_settlement_totals(*, amount: Decimal, goods_cash_amount: Decimal = ZERO,
        allocated_deposit_amount: Decimal = ZERO, discount_amount: Decimal = ZERO,
        deposit_amount: Decimal = ZERO, deposit_cash_amount: Decimal = ZERO,
        fee_amount: Decimal = ZERO) -> SettlementTotals:
    """参数均为有效记录聚合；订金 cash 与 deposit 分别传入以检查资金一致性。"""
    amount, cash, allocated, discount, deposits, deposit_cash, fees = map(checked_money,
        (amount, goods_cash_amount, allocated_deposit_amount, discount_amount,
         deposit_amount, deposit_cash_amount, fee_amount))
    settled = sum_money((cash, allocated))
    outstanding = amount - settled - discount
    available = deposits - allocated
    if outstanding < ZERO or available < ZERO or deposits != deposit_cash:
        # 这是已存记录的不一致，调用方不能吞掉并返回零余额或“已结清”。
        raise SettlementAmountError("SETTLEMENT_INCONSISTENT", "有效资金记录不一致，不能继续结算。")
    status = "SETTLED" if outstanding == ZERO else "UNSETTLED" if outstanding == amount else "PARTIAL"
    return SettlementTotals(amount, cash, allocated, discount, deposits, deposit_cash, fees,
        settled, outstanding, available, sum_money((deposit_cash, cash)), status)


@dataclass(frozen=True)
class GoodsSettlement:
    cash_amount: Decimal
    allocated_deposit_amount: Decimal
    discount_amount: Decimal
    settled_amount: Decimal
    outstanding_before: Decimal
    outstanding_after: Decimal
    available_deposit_after: Decimal


def validate_goods_settlement(totals: SettlementTotals, *, cash_amount: Decimal,
        allocated_deposit_amount: Decimal, discount_amount: Decimal = ZERO) -> GoodsSettlement:
    cash, allocated, discount = map(checked_money, (cash_amount, allocated_deposit_amount, discount_amount))
    settled = sum_money((cash, allocated))
    meta = {"outstanding_amount": str(totals.outstanding_amount),
        "available_deposit_amount": str(totals.available_deposit_amount),
        "cash_amount": str(cash), "allocated_deposit_amount": str(allocated),
        "discount_amount": str(discount), "recovery_action": "REVIEW_AMOUNTS"}
    if settled == ZERO:
        raise SettlementAmountError("FUNDS_REQUIRED", "货款必须有正数实际到账或整笔订金抵扣。", meta=meta)
    if allocated > totals.available_deposit_amount:
        raise SettlementAmountError("DEPOSIT_UNAVAILABLE", "所选订金已不可用，请刷新后重新确认。", meta=meta)
    outstanding = totals.outstanding_amount - settled - discount
    if outstanding < ZERO:
        raise SettlementAmountError("OVER_SETTLEMENT", "本次到账、订金抵扣和折让超过当前未付。",
            meta={**meta, "excess_amount": str(-outstanding)})
    available = totals.available_deposit_amount - allocated
    if available > outstanding:
        excess = available - outstanding
        raise SettlementAmountError("DEPOSIT_EXCESS_AFTER_SETTLEMENT",
            f"已收订金与本次到账、折让超出当前未付{excess:.2f}元，请核对实际收款。",
            meta={**meta, "excess_amount": str(excess)})
    return GoodsSettlement(cash, allocated, discount, settled, totals.outstanding_amount, outstanding, available)


def validate_new_deposit(totals: SettlementTotals, *, deposit_amount: Decimal) -> Decimal:
    deposit = checked_money(deposit_amount)
    if deposit == ZERO:
        raise SettlementAmountError("FUNDS_REQUIRED", "订金实际到账必须大于零。")
    available = sum_money((totals.available_deposit_amount, deposit))
    if available > totals.outstanding_amount:
        raise SettlementAmountError("DEPOSIT_EXCESS", "已有未用订金与本笔订金超过当前未付，请核对实际收款。",
            meta={"outstanding_amount": str(totals.outstanding_amount),
                "available_deposit_amount": str(totals.available_deposit_amount),
                "cash_amount": str(deposit), "excess_amount": str(available - totals.outstanding_amount),
                "recovery_action": "REVIEW_AMOUNTS"})
    return available
