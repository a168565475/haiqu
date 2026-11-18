import uuid
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.outsourcing.models import TubePlanReceiptLine
from apps.production_tasks.cost_selectors import task_cost_summary
from .test_part_flow_deferred_cost import PartFlowCostFixture


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PartFlowReceiptCostTests(PartFlowCostFixture, APITestCase):
    def assert_receipt_cost(self, amount, count, missing=0):
        summary = task_cost_summary(task=self.task)
        category = summary['categories'][2]
        self.assertEqual(category['amount'], amount, category)
        self.assertEqual((category['count'], category['missing_count']), (count, missing), category)
        self.assertTrue(all(row['id'].startswith('TUBE_OUTSOURCING:RECEIPT_LINE:') for row in category['items']), category)
        if missing:
            self.assertFalse(summary['complete'])
            self.assertIsNone(summary['current_difference'])
        return category

    def change_price(self, order, price):
        response = self.client.patch(f"/api/v1/tube-outsourcing-orders/{order['id']}/plan-quantity/", {
            'lines': [{'order_line_id': line['id'], 'quantity': line['quantity'], 'unit_price': price}
                      for line in order['lines']]}, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_plan_and_dispatch_have_no_cost_until_actual_receipts(self):
        order = self.create_part_plan(price='1.20')
        self.assert_receipt_cost('0.00', 0)
        order, _ = self.dispatch_part(order, 20)
        self.assert_receipt_cost('0.00', 0)
        order = self.receive_part(order, 3)
        self.assert_receipt_cost('3.60', 1)
        self.receive_part(order, 2)
        self.assert_receipt_cost('6.00', 2)

    def test_receipt_prices_stay_frozen_through_repricing_quantity_corrections_and_voids(self):
        order = self.receive_part(self.create_part_plan(price='1.20'), 3)
        first_id = order['receipt_records'][0]['id']
        order = self.change_price(order, '2.50')
        self.assert_receipt_cost('3.60', 1)
        order = self.receive_part(order, 4)
        second_id = next(row['id'] for row in order['receipt_records'] if row['id'] != first_id)
        self.assert_receipt_cost('13.60', 2)
        order = self.change_price(order, '9.00')
        self.assert_receipt_cost('13.60', 2)
        prices = TubePlanReceiptLine.objects.filter(receipt__order_id=order['id']).values_list('snapshot', flat=True)
        self.assertEqual({Decimal(row['unit_price']) for row in prices}, {Decimal('1.20'), Decimal('2.50')})
        second = next(row for row in order['receipt_records'] if row['id'] == second_id)
        order = self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=2, record=second))
        self.assert_receipt_cost('8.60', 2)
        first = next(row for row in order['receipt_records'] if row['id'] == first_id)
        order = self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE', record=first))
        self.assert_receipt_cost('5.00', 1)
        self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE'))
        self.assert_receipt_cost('0.00', 0)

    def test_upgraded_legacy_receipt_remains_unknown_and_old_dispatch_is_not_counted_again(self):
        order = self.as_legacy_plan(self.create_part_plan(price='1.20'))
        order = self.receive_part(order, 2)
        legacy_id = order['receipt_records'][0]['id']
        order, _ = self.dispatch_part(order, 20)
        before = task_cost_summary(task=self.task)['categories'][2]
        self.assertEqual((before['amount'], before['count'], before['missing_count']), ('0.00', 1, 1))
        self.assertTrue(before['items'][0]['id'].startswith('TUBE_OUTSOURCING:DEFERRED:'))
        order = self.change_price(order, '2.50')
        self.assert_receipt_cost('0.00', 1, missing=1)
        order = self.receive_part(order, 3)
        self.assert_receipt_cost('7.50', 2, missing=1)
        order = self.change_price(order, '1.00')
        self.assert_receipt_cost('7.50', 2, missing=1)
        legacy = next(row for row in order['receipt_records'] if row['id'] == legacy_id)
        order = self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE', record=legacy))
        self.assert_receipt_cost('7.50', 1)

    def test_finishing_dispatch_lines_do_not_duplicate_receipt_based_cost(self):
        order = self.create_part_plan('SEWING', self.finishing[0], price='2.00')
        response = self.client.post(f"/api/v1/tube-outsourcing-orders/{order['id']}/plan-dispatch/", {
            'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': 'SEWING', 'zone_id': None,
            'lines': [{'component_identity': str(self.part.component_identity), 'quantity': '20',
                       'factory_id': str(self.factory.pk)}]}, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = response.data['data']
        self.assert_receipt_cost('0.00', 0)
        self.receive_part(order, 4)
        self.assert_receipt_cost('8.00', 1)
