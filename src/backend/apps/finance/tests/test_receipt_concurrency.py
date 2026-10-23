from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from apps.core.api.concurrency import etag_for_instance
from apps.finance import receipt_common
from apps.finance.models import FinanceAccount
from apps.finance.receipt_models import Receipt
from apps.finance.receipt_services import create_receipt
from apps.finance.services import update_account
from .receipt_fixtures import ReceiptFixtureMixin


class ReceiptConcurrencyTests(ReceiptFixtureMixin, TransactionTestCase):
    def run_requests(self, keys):
        body = self.body(); etag = etag_for_instance(self.statement); barrier = Barrier(2)
        def submit(key):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                request = SimpleNamespace(employee=self.actor, data=body, headers={"Idempotency-Key": str(key), "If-Match": etag}, META={})
                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor: cursor.execute("SET LOCAL lock_timeout = '10s'")
                        receipt, replayed = create_receipt(request)
                    return str(receipt.pk), replayed
                except APIException as exc: return exc.status_code, getattr(exc, "api_error_code", None)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: return list(pool.map(submit, keys))

    def test_same_key_concurrent_create_only_one_receipt(self):
        key = uuid4(); results = self.run_requests([key, key])
        self.assertEqual(results[0][0], results[1][0]); self.assertEqual(sorted(value[1] for value in results), [False, True])
        self.assertEqual(Receipt.objects.count(), 1)

    def test_different_key_same_statement_etag_only_first_can_write(self):
        results = self.run_requests([uuid4(), uuid4()])
        self.assertEqual(sum(value[0] == 412 for value in results), 1, results)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_account_change_while_receipt_waits_is_revalidated_without_deadlock(self):
        body = self.body(); entered = Event(); release = Event(); real = receipt_common.lock_receipt_accounts
        def wait_before_accounts(lines):
            entered.set()
            if not release.wait(15): raise AssertionError("账户变更未结束")
            return real(lines)
        def receipt_worker():
            close_old_connections()
            try:
                request = SimpleNamespace(employee=self.actor, data=body, headers={"Idempotency-Key": str(uuid4()), "If-Match": etag_for_instance(self.statement)}, META={})
                try: create_receipt(request)
                except APIException as exc: return exc.api_error_code
                return "CREATED"
            finally: close_old_connections()
        with patch("apps.finance.deposit_services.lock_receipt_accounts", wait_before_accounts), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(receipt_worker)
            try:
                self.assertTrue(entered.wait(15))
                request = SimpleNamespace(employee=self.actor, headers={"If-Match": etag_for_instance(self.account)}, META={})
                update_account(request, self.account.pk, {"name": "并发账户改名"})
            finally: release.set()
            self.assertEqual(future.result(timeout=20), "ACCOUNT_CHANGED")
        self.assertFalse(Receipt.objects.exists()); self.assertEqual(FinanceAccount.objects.get(pk=self.account.pk).name, "并发账户改名")
