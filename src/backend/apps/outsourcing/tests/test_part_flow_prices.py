from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.outsourcing.part_flow_prices import receipt_price_data, receipt_amount_summary


class PartFlowPriceTests(SimpleTestCase):
    def line(self, price, quantity=3, **snapshot):
        return SimpleNamespace(received_quantity=quantity,
            snapshot={'billing_basis': 'PART_RECEIPT', 'unit_price': price, **snapshot})

    def test_normal_zero_and_unknown_remain_distinct(self):
        self.assertEqual(receipt_price_data(self.line('1.20'))['received_amount'], '3.60')
        self.assertEqual(receipt_price_data(self.line('0'))['received_amount'], '0.00')
        self.assertEqual(receipt_amount_summary([self.line('1.20'), self.line(None)]),
            {'received_amount': '3.60', 'has_unknown_receipt_amount': True})
        self.assertIsNone(receipt_price_data(self.line('1.20', billing_basis=None))['received_amount'])

    def test_allowed_price_quantity_and_multi_line_sum_preserve_cents(self):
        line = self.line('99999999999999.99', 99999999999999)
        self.assertEqual(receipt_price_data(line)['received_amount'], '9999999999999899000000000000.01')
        self.assertEqual(receipt_amount_summary([line, line]),
            {'received_amount': '19999999999999798000000000000.02', 'has_unknown_receipt_amount': False})

    def test_corrupt_old_json_is_unknown_instead_of_zero_or_server_error(self):
        for value in (None, True, {}, [], 'broken', 'NaN', 'Infinity', '-1', '100000000000000'):
            with self.subTest(value=value):
                self.assertIsNone(receipt_price_data(self.line(value))['received_amount'])
