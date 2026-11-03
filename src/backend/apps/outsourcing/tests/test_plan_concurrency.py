"""PostgreSQL事务竞争：总单同请求只入一次，不同请求按ETag串行累计。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.db.models import Sum
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from ..models import TubePlanReceipt, TubePlanReceiptLine
from .test_plan_orders_api import PlanApiFixture
from .test_tube_orders_api import BASE


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanConcurrencyTests(PlanApiFixture, TransactionTestCase):
    def concurrent_receipts(self, order, payloads):
        barrier = Barrier(2)

        def submit(payload):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait(timeout=20)
                response = client.post(BASE + f"{order['id']}/plan-receipt/", payload, format='json',
                    HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, payload) for payload in payloads]
            return [future.result(timeout=60) for future in futures]

    def test_same_request_and_competing_new_requests_never_double_receive(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='200'))
        payload = self.receipt_payload(order, '100')
        outcomes = self.concurrent_receipts(order, [payload, payload])
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 200], outcomes)
        self.assertEqual(TubePlanReceipt.objects.count(), 1)
        order = outcomes[0][1]['data']
        outcomes = self.concurrent_receipts(order, [self.receipt_payload(order, '80'), self.receipt_payload(order, '80')])
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 412], outcomes)
        self.assertEqual(TubePlanReceipt.objects.count(), 2)
        self.assertEqual(TubePlanReceiptLine.objects.aggregate(total=Sum('received_quantity'))['total'], 180)
