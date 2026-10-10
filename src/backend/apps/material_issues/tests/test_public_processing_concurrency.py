"""真实双连接核对 P4 公共回货的锁范围与同单数量串行保护。"""

import threading
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.core.api.concurrency import PreconditionFailed
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask
from apps.workshop_config.models import Craft

from ..models import MetalProcessingExternalGoodReturn, MetalProcessingExternalOrder, MetalProcessingSource
from ..p4_services import confirm_external_good_return
from .test_public_processing_flow import PublicProcessingFixture


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicProcessingConcurrencyTests(PublicProcessingFixture, TransactionTestCase):
    serialized_rollback = True

    @transaction.atomic
    def setUp(self):
        # 夹具内有锁查询；初始化独立提交后，工作线程才能看见同一批业务记录。
        super().setUp()
        self.order = self.create_order(5)
        self.dispatch_external(self.order)
        self.order.refresh_from_db()
        self.etag = self.external_detail(self.order)["etag"]
        self.raw_out_before = list(PublicStockMovement.objects.filter(direction="OUT").order_by("pk").values())
        self.source_before = MetalProcessingSource.objects.values().get(pk=self.order.source_id)

    @staticmethod
    def await_event(event, message):
        if not event.wait(timeout=6):
            raise AssertionError(message)

    def threads(self, *calls):
        results = []

        def run(call):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '15s'")
                results.append(call())
            except Exception as error:
                results.append(f"UNEXPECTED {type(error).__name__}: {error}")
            finally:
                connections.close_all()

        workers = [threading.Thread(target=run, args=(call,)) for call in calls]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
        self.assertFalse(any(worker.is_alive() for worker in workers), results)
        return results

    def return_good(self, payload):
        request = SimpleNamespace(
            user=get_user_model().objects.get(pk=self.f.user.pk),
            employee=Employee.objects.get(pk=self.f.employee.pk),
            headers={"If-Match": self.etag}, META={},
        )
        return confirm_external_good_return(request=request, order_id=self.order.pk, **payload)

    def assert_single_return(self, pieces):
        self.order.refresh_from_db()
        self.assertEqual(self.order.returned_good_pieces, pieces)
        self.assertEqual(self.order.handoff_pieces, 5)
        self.assertEqual(self.order.status, "PROCESSING")
        record = MetalProcessingExternalGoodReturn.objects.get(order=self.order)
        movement = PublicStockMovement.objects.get(source_type="METAL_P4_EXTERNAL_RETURN", source_id=self.order.pk)
        self.assertEqual(record.good_pieces, pieces)
        self.assertEqual(record.public_stock_movement_id, movement.pk)
        self.assertEqual(movement.direction, "IN")
        self.assertEqual(movement.quantity, pieces)
        self.assertEqual(PublicStockBalance.objects.get(stock_kind="SEMI").quantity, pieces)
        self.assertEqual(list(PublicStockMovement.objects.filter(direction="OUT").order_by("pk").values()), self.raw_out_before)
        self.assertEqual(MetalProcessingSource.objects.values().get(pk=self.order.source_id), self.source_before)

    def test_return_waiting_for_task_does_not_hold_craft_or_source(self):
        task_locked, return_requests_task = threading.Event(), threading.Event()
        task_table = ProductionTask._meta.db_table
        payload = self.good_payload(3)

        def task_then_craft():
            with transaction.atomic():
                ProductionTask.objects.select_for_update(of=("self",)).get(pk=self.task.pk)
                task_locked.set()
                self.await_event(return_requests_task, "P4 回货没有进入任务锁等待")
                # 旧查询会先连带锁住工艺；NOWAIT 使反序稳定报错，无需等死锁超时。
                Craft.objects.select_for_update(of=("self",), nowait=True).get(pk=self.order.craft_id)
                MetalProcessingSource.objects.select_for_update(of=("self",), nowait=True).get(pk=self.order.source_id)
            return "TASK_THEN_CRAFT"

        def receive():
            self.await_event(task_locked, "另一事务没有取得任务锁")

            def observe(execute, sql, params, many, context):
                if f'FROM "{task_table}"' in sql and "FOR UPDATE" in sql:
                    return_requests_task.set()
                return execute(sql, params, many, context)

            with connections["default"].execute_wrapper(observe):
                self.return_good(payload)
            return "RETURNED"

        self.assertCountEqual(self.threads(task_then_craft, receive), ["TASK_THEN_CRAFT", "RETURNED"])
        self.assert_single_return(3)

    def test_same_order_returns_remain_serialized_by_order_lock(self):
        first_locked_order, second_requests_order = threading.Event(), threading.Event()
        order_table = MetalProcessingExternalOrder._meta.db_table
        first_payload, second_payload = self.good_payload(3), self.good_payload(3)

        def first_return():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if f'FROM "{order_table}"' in sql and "FOR UPDATE" in sql:
                    first_locked_order.set()
                    self.await_event(second_requests_order, "第二次回货没有请求同单行锁")
                return result

            with connections["default"].execute_wrapper(observe):
                self.return_good(first_payload)
            return "RETURNED"

        def second_return():
            self.await_event(first_locked_order, "第一次回货没有取得同单行锁")

            def observe(execute, sql, params, many, context):
                if f'FROM "{order_table}"' in sql and "FOR UPDATE" in sql:
                    second_requests_order.set()
                return execute(sql, params, many, context)

            try:
                with connections["default"].execute_wrapper(observe):
                    self.return_good(second_payload)
            except PreconditionFailed:
                return "STALE_ETAG"
            return "UNEXPECTED_SECOND_RETURN"

        self.assertCountEqual(self.threads(first_return, second_return), ["RETURNED", "STALE_ETAG"])
        self.assert_single_return(3)
