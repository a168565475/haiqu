from decimal import Decimal as D, localcontext
from unittest import TestCase

from apps.finance.settlement_totals import (
    MAX_AMOUNT, SettlementAmountError, calculate_settlement_totals, checked_money,
    statement_amount, statement_line_amount, sum_money, validate_goods_settlement, validate_new_deposit,
)


class SettlementTotalsTests(TestCase):
    def assert_code(self, code, call):
        with self.assertRaises(SettlementAmountError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def totals(self, **values):
        return calculate_settlement_totals(**{key: D(str(value)) for key, value in {"amount": "1000", **values}.items()})

    def test_m01_m03_round_each_line_half_up(self):
        self.assertEqual(statement_line_amount(60, D("61.09")), D("3665.40"))
        self.assertEqual(statement_amount([(3, D("0.3350")), (3, D("0.3350"))]), D("2.02"))

    def test_m04_deposit_does_not_settle(self):
        totals = self.totals(deposit_amount=200, deposit_cash_amount=200)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount),
            (D("1000.00"), D("200.00"), D("200.00")))
        self.assertEqual(totals.settlement_status, "UNSETTLED")

    def test_m05_cash_deposit_discount_are_distinct(self):
        initial = self.totals(deposit_amount=200, deposit_cash_amount=200)
        result = validate_goods_settlement(initial, cash_amount=D(500), allocated_deposit_amount=D(200), discount_amount=D(20))
        self.assertEqual((result.settled_amount, result.outstanding_after, result.available_deposit_after), (D(700), D(280), D(0)))
        totals = self.totals(goods_cash_amount=500, allocated_deposit_amount=200, discount_amount=20,
            deposit_amount=200, deposit_cash_amount=200, fee_amount=10)
        self.assertEqual((totals.settled_amount, totals.bank_received_amount, totals.outstanding_amount), (D(700), D(700), D(280)))

    def test_m06_void_recomputes_remaining_receipts(self):
        paid = self.totals(goods_cash_amount=780, allocated_deposit_amount=200, discount_amount=20,
            deposit_amount=200, deposit_cash_amount=200)
        self.assertEqual(paid.settlement_status, "SETTLED")
        remaining = self.totals(goods_cash_amount=280, deposit_amount=200, deposit_cash_amount=200)
        self.assertEqual((remaining.outstanding_amount, remaining.available_deposit_amount, remaining.bank_received_amount),
            (D(720), D(200), D(480)))

    def test_m07_fee_does_not_pay_debt(self):
        totals = self.totals(goods_cash_amount=990, fee_amount=10)
        self.assertEqual((totals.outstanding_amount, totals.settled_amount, totals.settlement_status), (D(10), D(990), "PARTIAL"))

    def test_m08_pure_deposit_no_new_cash(self):
        initial = self.totals(amount=300, deposit_amount=300, deposit_cash_amount=300)
        result = validate_goods_settlement(initial, cash_amount=D(0), allocated_deposit_amount=D(300))
        self.assertEqual(result.outstanding_after, D(0))
        final = self.totals(amount=300, allocated_deposit_amount=300, deposit_amount=300, deposit_cash_amount=300)
        self.assertEqual(final.bank_received_amount, D(300))

    def test_m09_entire_deposit_cannot_be_truncated(self):
        initial = self.totals(amount=250, deposit_amount=300, deposit_cash_amount=300)
        self.assert_code("OVER_SETTLEMENT", lambda: validate_goods_settlement(initial, cash_amount=D(0), allocated_deposit_amount=D(300)))

    def test_m10_discount_cannot_over_settle(self):
        self.assert_code("OVER_SETTLEMENT", lambda: validate_goods_settlement(self.totals(amount=100),
            cash_amount=D(80), allocated_deposit_amount=D(0), discount_amount=D(30)))

    def test_m11_unselected_deposit_must_have_remaining_debt(self):
        initial = self.totals(deposit_amount=300, deposit_cash_amount=300)
        error = self.assert_code("DEPOSIT_EXCESS_AFTER_SETTLEMENT", lambda: validate_goods_settlement(initial,
            cash_amount=D(800), allocated_deposit_amount=D(0)))
        self.assertEqual(error.meta["excess_amount"], "100.00")
        self.assert_code("OVER_SETTLEMENT", lambda: validate_goods_settlement(initial,
            cash_amount=D(800), allocated_deposit_amount=D(300)))

    def test_m12_persisted_deposit_cash_mismatch_is_not_success(self):
        self.assert_code("SETTLEMENT_INCONSISTENT", lambda: self.totals(amount=20000, deposit_amount=10800, deposit_cash_amount=12600))

    def test_new_deposit_capacity(self):
        totals = self.totals(deposit_amount=300, deposit_cash_amount=300)
        self.assertEqual(validate_new_deposit(totals, deposit_amount=D(700)), D(1000))
        self.assert_code("DEPOSIT_EXCESS", lambda: validate_new_deposit(totals, deposit_amount=D("700.01")))

    def test_discount_only_and_empty_goods_rejected(self):
        for discount in (D(0), D(20)):
            self.assert_code("FUNDS_REQUIRED", lambda: validate_goods_settlement(self.totals(),
                cash_amount=D(0), allocated_deposit_amount=D(0), discount_amount=discount))

    def test_precision_nonfinite_negative_and_overflow(self):
        for value in (D("NaN"), D("Infinity"), D("-1"), D("0.001"), MAX_AMOUNT + D("0.01")):
            self.assert_code("AMOUNT_OUT_OF_RANGE", lambda: checked_money(value))
        with self.assertRaises(TypeError):
            checked_money(1.01)
        self.assert_code("AMOUNT_OUT_OF_RANGE", lambda: sum_money([MAX_AMOUNT, D("0.01")]))
        self.assert_code("AMOUNT_OUT_OF_RANGE", lambda: statement_line_amount(10000000, D("99999999999999.9999")))
        self.assert_code("AMOUNT_OUT_OF_RANGE", lambda: statement_line_amount(1, D("0.00001")))

    def test_bad_quantity_and_empty_lines(self):
        for quantity in (D("1.5"), D(0), D(-1)):
            self.assert_code("VALIDATION_ERROR", lambda: statement_line_amount(quantity, D(1)))
        self.assert_code("VALIDATION_ERROR", lambda: statement_amount([]))

    def test_cent_precision_near_maximum(self):
        with localcontext() as context:
            context.prec = 28
            total = calculate_settlement_totals(amount=MAX_AMOUNT, goods_cash_amount=MAX_AMOUNT - D("0.01"))
            self.assertEqual(total.outstanding_amount, D("0.01"))
            self.assertEqual(total.settlement_status, "PARTIAL")
