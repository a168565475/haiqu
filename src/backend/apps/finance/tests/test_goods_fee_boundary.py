from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.finance import goods_services
from apps.finance.receipt_exceptions import ReceiptValidationError
from apps.finance.settlement_totals import MAX_AMOUNT, calculate_settlement_totals


class GoodsFeeBoundaryTests(SimpleTestCase):
    def test_cumulative_fee_rejected_before_account_or_file_lock(self):
        totals = calculate_settlement_totals(amount=Decimal("1000"), fee_amount=MAX_AMOUNT)
        with patch.object(goods_services, "_require_transaction"), \
                patch.object(goods_services, "_lock_selected_deposits", return_value=[]), \
                patch.object(goods_services, "settlement_totals_for", return_value=totals), \
                patch.object(goods_services, "account_line_totals", return_value=(Decimal("1"), Decimal("0.01"))), \
                patch.object(goods_services, "lock_receipt_accounts", side_effect=AssertionError("累计费用越界不得进入账户/文件锁")):
            with self.assertRaises(ReceiptValidationError) as caught:
                goods_services.create_goods_receipt(request=SimpleNamespace(), statement=SimpleNamespace(status="ACTIVE"),
                    data={"receipt_type": "GOODS", "account_lines": []}, resource_id=uuid4())
        self.assertEqual(caught.exception.api_error_code, "AMOUNT_OUT_OF_RANGE")
