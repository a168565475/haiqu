from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase

from apps.core.models import DailyBusinessNumberCounter
from apps.finance.deposit_services import create_deposit_receipt_locked
from apps.finance.models import FinanceMutationKey
from apps.finance.receipt_exceptions import ReceiptValidationError
from apps.finance.receipt_models import Receipt, ReceiptAttachment
from apps.finance.settlement_selectors import settlement_totals_for
from apps.finance.settlement_totals import MAX_AMOUNT, calculate_settlement_totals
from .receipt_fixtures import ReceiptFixtureMixin, ROOT


class DepositFeeOrderTests(SimpleTestCase):
    def test_cumulative_fee_rejected_before_account_locks_or_writes(self):
        totals = calculate_settlement_totals(amount=Decimal("100"), deposit_amount=Decimal("1"),
            deposit_cash_amount=Decimal("1"), fee_amount=MAX_AMOUNT)
        with patch("apps.finance.deposit_services.settlement_totals_for", return_value=totals), \
             patch("apps.finance.deposit_services.account_line_totals", return_value=(Decimal("1"), Decimal("0.01"))), \
             patch("apps.finance.deposit_services.lock_receipt_accounts", side_effect=AssertionError("累计手续费越界不得继续锁账户")):
            with self.assertRaises(ReceiptValidationError) as caught:
                create_deposit_receipt_locked(request=None, statement=None, data={"account_lines": []}, resource_id=uuid4())
            self.assertEqual(caught.exception.api_error_code, "AMOUNT_OUT_OF_RANGE")


class DepositFeeBoundaryTests(ReceiptFixtureMixin, TestCase):
    def test_maximum_fee_then_one_cent_rejected_without_partial_write(self):
        first = self.create(self.body("1.00", str(MAX_AMOUNT)))
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(settlement_totals_for(self.statement).fee_amount, MAX_AMOUNT)
        upload = self.upload()
        key = uuid4()
        counters = list(DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_RECEIPT").values())
        self.statement.refresh_from_db()
        before_updated_at = self.statement.updated_at
        rejected = self.create(self.body("1.00", "0.01", upload=upload), key=key)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertEqual(rejected.data["error"]["code"], "AMOUNT_OUT_OF_RANGE")
        self.assertEqual(Receipt.objects.filter(statement=self.statement).count(), 1)
        self.assertFalse(FinanceMutationKey.objects.filter(key=key).exists())
        self.assertEqual(list(DailyBusinessNumberCounter.objects.filter(number_type="FINANCE_RECEIPT").values()), counters)
        self.statement.refresh_from_db(); self.assertEqual(self.statement.updated_at, before_updated_at)
        upload.refresh_from_db(); self.assertEqual(upload.status, "UNBOUND")
        self.assertFalse(ReceiptAttachment.objects.filter(file=upload.file).exists())
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.fee_amount, totals.bank_received_amount, totals.outstanding_amount), (MAX_AMOUNT, Decimal("1"), Decimal("100")))
        self.assertEqual(self.client.get(ROOT).status_code, 200)
