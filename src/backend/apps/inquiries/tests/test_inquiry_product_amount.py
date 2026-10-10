import csv
import io
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.inquiries.models import InquiryItem
from apps.inquiries.selectors import inquiry_product_amount
from . import test_inquiry_api


class ProductAmountTests(SimpleTestCase):
    def summary(self, rows):
        items = [SimpleNamespace(quantity=Decimal(qty), target_unit_price=Decimal(price) if price is not None else None, target_currency_code=currency) for qty, price, currency in rows]
        return inquiry_product_amount(SimpleNamespace(list_items=items))

    def test_multiple_lines_group_by_currency(self):
        result = self.summary([('2000', '100', 'USD'), ('3', '0.25', 'USD'), ('2', '5', 'CNY')])
        self.assertEqual(result['totals'], [{'currency_code': 'CNY', 'amount': '10'}, {'currency_code': 'USD', 'amount': '200000.75'}])
        self.assertEqual(result['missing_price_count'], 0)

    def test_zero_missing_price_currency_and_empty(self):
        self.assertEqual(self.summary([]), {'item_count': 0, 'missing_price_count': 0, 'totals': []})
        result = self.summary([('2', '0', 'USD'), ('1', None, 'USD'), ('3', '8', '')])
        self.assertEqual(result['missing_price_count'], 2)
        self.assertEqual(result['totals'], [{'currency_code': 'USD', 'amount': '0'}])

    def test_full_model_decimal_precision(self):
        result = self.summary([('99999999999999.9999', '99999999999999.9999', 'USD')])
        self.assertEqual(result['totals'][0]['amount'], '9999999999999999980000000000.00000001')
        self.assertEqual(self.summary([('0.0001', '0.0001', 'USD')])['totals'][0]['amount'], '0.00000001')


class ProductAmountApiTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def test_list_and_export_use_current_product_amount(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        InquiryItem.objects.filter(inquiry_id=inquiry_id).update(quantity='2000', target_unit_price='100', target_currency_code='USD')
        response = self.client.get('/api/v1/inquiries/')
        self.assertEqual(response.status_code, 200)
        summary = response.data['data'][0]['product_amount']
        self.assertEqual(summary['totals'], [{'currency_code': 'USD', 'amount': '200000.00000000'}])
        response = self.client.get('/api/v1/inquiries/export/')
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        index = rows[0].index('预估金额（目标单价×数量）')
        self.assertEqual(rows[1][index], 'USD 200000.00000000')
        InquiryItem.objects.filter(inquiry_id=inquiry_id).update(target_unit_price=None)
        response = self.client.get('/api/v1/inquiries/export/')
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[1][index], '待补齐')
