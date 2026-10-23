from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event
import time
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from apps.core.api.concurrency import etag_for_instance
from apps.finance.allocation_models import DepositAllocation
from apps.finance.models import FinanceMutationKey
from apps.finance.receipt_models import Receipt
from apps.finance.receipt_services import create_receipt, void_receipt
from apps.finance import receipt_services
from apps.finance.settlement_selectors import settlement_totals_for
from apps.finance.source_selectors import source_revision
from apps.finance.statement_services import update_statement
from apps.production_tasks.models import ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from .goods_test_support import GoodsFixture


class GoodsConcurrencyTests(GoodsFixture, TransactionTestCase):
    def race(self, operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                        cursor.execute("SET LOCAL statement_timeout = '15s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        pid = cursor.fetchone()[0]
                    barrier.wait(timeout=10)
                    try:
                        value, changed = operation()
                        return pid, "OK", str(value.pk), changed
                    except APIException as exc:
                        return pid, getattr(exc, "api_error_code", exc.status_code), None, None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            results = list(pool.map(run, operations))
        self.assertEqual(len({row[0] for row in results}), len(operations), "必须是独立PostgreSQL连接")
        return results

    def test_same_deposit_and_etag_only_one_new_goods(self):
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        data = self.body(deposits=[deposit])
        requests = [self.request(data), self.request(data)]
        results = self.race([lambda request=request: create_receipt(request) for request in requests])
        self.assertCountEqual([row[1] for row in results], ["OK", 412])
        self.assertEqual(Receipt.objects.filter(receipt_type="GOODS").count(), 1)
        self.assertEqual(DepositAllocation.objects.filter(is_active=True).count(), 1)
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("700"))

    def test_two_cash_submissions_cannot_cross_remaining_balance(self):
        requests = [self.request(self.body(cash="800.00")) for _ in range(2)]
        results = self.race([lambda request=request: create_receipt(request) for request in requests])
        self.assertCountEqual([row[1] for row in results], ["OK", 412])
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("200"))
        self.assertEqual(Receipt.objects.count(), 1)

    def test_same_key_same_body_returns_single_receipt_and_replay(self):
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        request = self.request(self.body(deposits=[deposit]), key=uuid4())
        results = self.race([lambda: create_receipt(request), lambda: create_receipt(request)])
        self.assertEqual([row[1] for row in results], ["OK", "OK"])
        self.assertEqual(len({row[2] for row in results}), 1)
        self.assertEqual(sorted(row[3] for row in results), [False, True])
        self.assertEqual(DepositAllocation.objects.count(), 1)
        self.assertEqual(FinanceMutationKey.objects.filter(key=request.headers["Idempotency-Key"]).count(), 1)

    def test_same_key_different_body_is_conflict(self):
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        key = uuid4()
        requests = [self.request(self.body(deposits=[deposit], discount=discount), key=key) for discount in ("0.00", "1.00")]
        results = self.race([lambda request=request: create_receipt(request) for request in requests])
        self.assertCountEqual([row[1] for row in results], ["OK", "IDEMPOTENCY_KEY_REUSED"])
        self.assertEqual(Receipt.objects.filter(receipt_type="GOODS").count(), 1)

    def test_concurrent_goods_and_deposit_void_never_leave_live_allocation_to_void_deposit(self):
        deposit = self.create(kind="DEPOSIT", cash="300.00")
        goods = self.create(deposits=[deposit])
        requests = [(self.request({"reason": "隔离并发作废"}, item), item.pk) for item in (goods, deposit)]
        results = self.race([lambda request=request, pk=pk: void_receipt(request, pk) for request, pk in requests])
        self.assertEqual(results[0][1], "OK")
        self.assertIn(results[1][1], ("DEPOSIT_UNAVAILABLE", 412))
        goods.refresh_from_db(); deposit.refresh_from_db()
        self.assertEqual(goods.status, "VOID")
        self.assertEqual(deposit.status, "ACTIVE")
        self.assertFalse(DepositAllocation.objects.filter(is_active=True).exists())
        # 第一次失败不会吞掉新状态；重新读取ETag后可正常作废原订金。
        result, changed = void_receipt(self.request({"reason": "重新核对后作废"}, deposit,
            etag=etag_for_instance(deposit)), deposit.pk)
        self.assertTrue(changed)
        self.assertEqual(result.status, "VOID")
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("1000"))

    def test_two_goods_voids_keep_remaining_valid_deposit(self):
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        first = self.create(cash="300.00", deposits=[deposit])
        second = self.create(cash="400.00")
        requests = [(self.request({"reason": "隔离双货款作废"}, item), item.pk) for item in (first, second)]
        results = self.race([lambda request=request, pk=pk: void_receipt(request, pk) for request, pk in requests])
        self.assertEqual([row[1] for row in results], ["OK", "OK"])
        totals = settlement_totals_for(self.statement)
        self.assertEqual((totals.outstanding_amount, totals.available_deposit_amount, totals.bank_received_amount),
            (Decimal("1000"), Decimal("200"), Decimal("200")))
        self.assertFalse(DepositAllocation.objects.filter(is_active=True).exists())

    def test_receipt_holds_statement_lock_until_edit_is_rejected(self):
        unit = ProductionUnit.objects.create(unit_code="U05_PCS", unit_name="隔离件")
        task = self.statement.production_task
        product = ProductionTaskProduct.objects.create(production_task=task, line_number=1,
            product_name_snapshot="隔离来源产品", quantity=1, unit=unit, currency=self.currency,
            unit_price=Decimal("1000"), total_amount=Decimal("1000"), exchange_rate=1)
        edit_data = {"production_task_id": task.pk, "source_revision": source_revision(task, [product]),
            "acknowledge_salesperson_change": False,
            "lines": [{"production_task_product_id": product.pk, "unit_price": Decimal("900.0000")}]}
        create_request = self.request(self.body(cash="800.00"))
        edit_request = self.request({})
        locked, edit_started, release = Event(), Event(), Event()
        pids = {}
        actual_lock = receipt_services.lock_statement

        def held_lock(pk):
            statement = actual_lock(pk)
            locked.set()
            if not release.wait(10):
                raise AssertionError("测试未及时释放已确认的账单锁")
            return statement

        def run(kind):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '12s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        pids[kind] = cursor.fetchone()[0]
                    if kind == "create":
                        create_receipt(create_request)
                        return "OK"
                    edit_started.set()
                    try:
                        update_statement(edit_request, self.statement.pk, edit_data)
                        return "OK"
                    except APIException as exc:
                        return getattr(exc, "api_error_code", exc.status_code)
            finally:
                connections.close_all()

        with patch.object(receipt_services, "lock_statement", held_lock), ThreadPoolExecutor(max_workers=2) as pool:
            creating = pool.submit(run, "create")
            editing = None
            try:
                self.assertTrue(locked.wait(10), "收款没有取得真实账单行锁")
                editing = pool.submit(run, "edit")
                self.assertTrue(edit_started.wait(5))
                blockers, deadline = [], time.monotonic() + 5
                while pids["create"] not in blockers and time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [pids["edit"]])
                        blockers = cursor.fetchone()[0]
                    if pids["create"] not in blockers:
                        time.sleep(0.05)
                self.assertIn(pids["create"], blockers, "未观察到账单编辑等待收款行锁，不能声称锁等待已验证")
                print("U05 PostgreSQL pg_blocking_pids confirmed: statement edit waits for receipt transaction")
            finally:
                release.set()
            self.assertEqual(creating.result(timeout=15), "OK")
            self.assertIsNotNone(editing)
            self.assertEqual(editing.result(timeout=15), 412)
        self.statement.refresh_from_db()
        self.assertEqual(self.statement.amount, Decimal("1000"))
        self.assertEqual(settlement_totals_for(self.statement).outstanding_amount, Decimal("200"))
