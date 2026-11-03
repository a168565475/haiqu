from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from ..models import PurchaseOrder
from . import test_purchase_groups as group_tests
from .group_test_fixtures import ensure_group_test_reference_data


class PurchaseGroupConcurrencyTests(TransactionTestCase):
    make_task = group_tests.PurchaseGroupApiTests.make_task
    make_product_line = group_tests.PurchaseGroupApiTests.make_product_line
    make_bom = group_tests.PurchaseGroupApiTests.make_bom
    get_source = group_tests.PurchaseGroupApiTests.get_source
    detail = group_tests.PurchaseGroupApiTests.detail
    batch_payload = group_tests.PurchaseGroupApiTests.batch_payload

    def setUp(self):
        ensure_group_test_reference_data()
        group_tests.PurchaseGroupApiTests.setUp(self)

    def race(self, payloads):
        user_id, group_id, etag = self.user.pk, self.group_id, self.detail()["ETag"]
        barrier = Barrier(2)

        def create(payload):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=15)
                response = client.post(f"/api/v1/purchase-groups/{group_id}/batches/", payload,
                                       format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, payload) for payload in payloads]
            return [future.result(timeout=40) for future in futures]

    def test_concurrent_duplicate_request_creates_one_batch(self):
        payload = self.batch_payload()
        responses = self.race([payload, deepcopy(payload)])
        self.assertEqual(sorted(code for code, _ in responses), [200, 201], responses)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).count(), 1)
        self.assertEqual(responses[0][1]["data"]["id"], responses[1][1]["data"]["id"])

    def test_concurrent_distinct_requests_reject_stale_group_version(self):
        first = self.batch_payload()
        second = deepcopy(first)
        second["request_id"] = str(uuid4())
        responses = self.race([first, second])
        self.assertEqual(sorted(code for code, _ in responses), [201, 412], responses)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).count(), 1)
