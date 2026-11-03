"""真实PostgreSQL事务：更正幂等与父总单ETag竞争。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient
from apps.inventory.models import PublicStockMovement

from ..models import TubePlanRecordCorrection
from .test_plan_orders_api import PlanApiFixture
from .test_plan_record_corrections import CorrectionApiMixin
from .test_tube_orders_api import BASE


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanCorrectionConcurrencyTests(CorrectionApiMixin, PlanApiFixture, TransactionTestCase):
    def concurrent(self, order, payloads):
        barrier = Barrier(2)

        def submit(payload):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait(timeout=20)
                response = client.post(BASE + order['id'] + '/plan-record-correction/', payload, format='json',
                    HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, payload) for payload in payloads]
            return [future.result(timeout=60) for future in futures]

    def test_same_uuid_only_one_correction_then_old_etag_loses_competing_update(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='200'))
        payload = self.correction_payload(order, quantity=180)
        outcomes = self.concurrent(order, [payload, payload])
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 200], outcomes)
        self.assertEqual(TubePlanRecordCorrection.objects.count(), 1)
        order = outcomes[0][1]['data']
        outcomes = self.concurrent(order, [self.correction_payload(order, quantity=160), self.correction_payload(order, quantity=150)])
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 412], outcomes)
        self.assertEqual(TubePlanRecordCorrection.objects.count(), 2)

    def test_same_receipt_update_uuid_credits_difference_once(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='200'))
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '80'))
        original = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        payload = self.correction_payload(order, 'RECEIPT', quantity=100)
        outcomes = self.concurrent(order, [payload, payload])
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 200], outcomes)
        original.balance.refresh_from_db()
        self.assertEqual(original.balance.quantity, 100)
        self.assertEqual(TubePlanRecordCorrection.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_PLAN_RECEIPT_CORRECTION').count(), 1)
