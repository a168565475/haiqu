"""使用真实独立连接与事务交错核对父仓、库区及订单的锁顺序。"""
import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.core.api.exceptions import Conflict
from apps.material_issues.tests.test_public_issue_services import PublicIssueFixture
from apps.procurement.models import PurchaseOrderLine
from apps.production_tasks.models import ProductionTask

from ..models import MaterialInbound, MaterialInboundLine, PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone
from ..pipe_stock_services import credit_pipe_inbound
from ..public_stock_services import credit_public_stock, lock_public_stock_locations
from ..services import confirm_material_quality, save_warehouse, save_zone
from ..stock_services import InventoryStockValidationError
from .test_public_stock_services import PublicStockFixture


class ConcurrentConnections:
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

    @staticmethod
    def await_event(event, message):
        if not event.wait(timeout=6):
            raise AssertionError(message)


class PublicLocationConcurrencyTests(ConcurrentConnections, PublicStockFixture, TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            super().setUp()

    def close(self, kind):
        if kind == "warehouse":
            return save_warehouse(instance=self.semi_warehouse, validated_data={"status": "DISABLED"},
                                  actor_employee=self.employee, request=None)
        return save_zone(instance=self.semi_zone, validated_data={"status": "DISABLED"},
                         actor_employee=self.employee, request=None)

    def credit_semi(self):
        return credit_public_stock(identity=self.semi_identity, zone=self.semi_zone, quantity=7,
            source_type="CONCURRENT_LOCATION_CREDIT", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee)

    def close_wins(self, kind):
        closing_has_parent, credit_waits_for_parent = threading.Event(), threading.Event()
        warehouse_table = Warehouse._meta.db_table

        def close_first():
            with transaction.atomic():
                Warehouse.objects.select_for_update(of=("self",), no_key=True).get(pk=self.semi_warehouse.pk)
                if kind == "zone":
                    WarehouseZone.objects.select_for_update(of=("self",), no_key=True).get(pk=self.semi_zone.pk)
                self.assertFalse(PublicStockBalance.objects.filter(zone=self.semi_zone).exists())
                closing_has_parent.set()
                self.await_event(credit_waits_for_parent, "入库没有先请求父仓锁")
                self.close(kind)
            return "CLOSED"

        def receive():
            self.await_event(closing_has_parent, "停用事务没有取得父仓锁")

            def observe(execute, sql, params, many, context):
                if f'FROM "{warehouse_table}"' in sql and "FOR NO KEY UPDATE" in sql:
                    credit_waits_for_parent.set()
                return execute(sql, params, many, context)

            try:
                with connections["default"].execute_wrapper(observe):
                    self.credit_semi()
            except InventoryStockValidationError as error:
                return error.api_error_code
            return "UNEXPECTED_CREDIT"

        results = self.threads(close_first, receive)
        self.assertCountEqual(results, ["CLOSED", "ZONE_UNAVAILABLE"])
        self.assertFalse(PublicStockBalance.objects.filter(zone=self.semi_zone).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type="CONCURRENT_LOCATION_CREDIT").exists())
        record = Warehouse.objects.get(pk=self.semi_warehouse.pk) if kind == "warehouse" else WarehouseZone.objects.get(pk=self.semi_zone.pk)
        self.assertEqual(record.status, "DISABLED")

    def credit_wins(self, kind):
        credited, closing_attempts_parent = threading.Event(), threading.Event()
        warehouse_table = Warehouse._meta.db_table

        def receive_first():
            with transaction.atomic():
                self.credit_semi()
                credited.set()
                self.await_event(closing_attempts_parent, "停用事务没有按父仓顺序等待")
            return "CREDITED"

        def close_after_credit():
            self.await_event(credited, "入库事务没有记账")

            def observe(execute, sql, params, many, context):
                if f'FROM "{warehouse_table}"' in sql and "FOR " in sql:
                    closing_attempts_parent.set()
                return execute(sql, params, many, context)

            try:
                with connections["default"].execute_wrapper(observe):
                    self.close(kind)
            except Conflict:
                return "CLOSE_BLOCKED"
            return "UNEXPECTED_CLOSE"

        self.assertCountEqual(self.threads(receive_first, close_after_credit), ["CREDITED", "CLOSE_BLOCKED"])
        self.assertEqual(PublicStockBalance.objects.get(zone=self.semi_zone).quantity, 7)
        self.assertEqual(Warehouse.objects.get(pk=self.semi_warehouse.pk).status, "ACTIVE")
        self.assertEqual(WarehouseZone.objects.get(pk=self.semi_zone.pk).status, "ACTIVE")

    def test_warehouse_disable_commits_before_first_semi_credit(self):
        self.close_wins("warehouse")

    def test_zone_disable_commits_before_first_semi_credit(self):
        self.close_wins("zone")

    def test_first_semi_credit_prevents_concurrent_warehouse_disable(self):
        self.credit_wins("warehouse")

    def test_first_semi_credit_prevents_concurrent_zone_disable(self):
        self.credit_wins("zone")

    def test_missing_zone_is_reported_before_any_balance_write(self):
        with self.assertRaises(InventoryStockValidationError) as error, transaction.atomic():
            lock_public_stock_locations([uuid.uuid4()])
        self.assertEqual(error.exception.api_error_code, "ZONE_UNAVAILABLE")
        self.assertFalse(PublicStockBalance.objects.filter(zone=self.semi_zone).exists())


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicReceiptIssueConcurrencyTests(ConcurrentConnections, PublicIssueFixture, TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            super().setUp()

    def source_receipt(self, *, quality_pending):
        order = self.task.purchase_order
        purchase_line = PurchaseOrderLine.objects.create(purchase_order=order, line_number=1,
            bom=self.bom, bom_line=self.bom_line, source_bom_line_id_snapshot=self.bom_line.pk,
            product_line_id_snapshot=self.product_line.pk, bom_number_snapshot=self.bom.bom_number,
            product_number_snapshot=self.product_line.product_number_snapshot,
            product_name_snapshot=self.product_line.product_name_snapshot, section_type_snapshot="PROFILE",
            section_title_snapshot="管材类", part_name_snapshot=self.bom_line.part_name,
            quantity_parse_status="READY", source_unit_text="米", actual_purchase_quantity=Decimal("6.10"))
        inbound = MaterialInbound.objects.create(inbound_number="CONCURRENT" + uuid.uuid4().hex.upper(),
            stock_mode="PUBLIC_V2", purchase_order=order, received_by_employee=self.employee,
            status="PENDING_QUALITY" if quality_pending else "CONFIRMED")
        identity = {**self.pipe_identity, "raw_bar_length_m": str(self.pipe_identity["raw_bar_length_m"])}
        return MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=purchase_line,
            raw_material_information=self.raw_material, zone=self.zone, measurement_kind="PIPE",
            raw_bar_length_m=Decimal("3.05"), received_bar_count=2, accepted_bar_count=2, return_bar_count=0,
            received_quantity=Decimal("6.10"), accepted_quantity=Decimal("6.10"), return_quantity=0,
            purchased_quantity_snapshot=Decimal("6.10"), source_unit_text_snapshot="米",
            calculation_snapshot={"public_stock_identity": identity})

    def receipt_and_issue(self, *, quality_pending):
        line = self.source_receipt(quality_pending=quality_pending)
        issue = self.submit(self.create("12"))
        issue_has_task, receipt_waits_for_task = threading.Event(), threading.Event()
        task_table = ProductionTask._meta.db_table

        def issue_first():
            with transaction.atomic():
                ProductionTask.objects.select_for_update(of=("self",)).get(pk=self.task.pk)
                issue_has_task.set()
                self.await_event(receipt_waits_for_task, "入库未在原料与库区之前请求来源订单锁")
                self.confirm(issue)
            return "ISSUED"

        def receive():
            self.await_event(issue_has_task, "领料未取得订单锁")

            def observe(execute, sql, params, many, context):
                if f'FROM "{task_table}"' in sql and "FOR " in sql:
                    receipt_waits_for_task.set()
                return execute(sql, params, many, context)

            with connections["default"].execute_wrapper(observe):
                if quality_pending:
                    request = SimpleNamespace(user=type(self.user).objects.get(pk=self.user.pk),
                        employee=self.employee, META={}, headers={})
                    confirm_material_quality(inbound_id=line.inbound_id, items=[{"line_id": line.pk,
                        "expected_received_quantity": Decimal("6.10"), "return_bar_count": 0,
                        "quality_remark": "并发合格入库"}], actor_employee=self.employee, request=request)
                else:
                    credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
            return "RECEIVED"

        self.assertCountEqual(self.threads(issue_first, receive), ["ISSUED", "RECEIVED"])
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (10, Decimal("30.50")))
        self.assertEqual(PublicStockMovement.objects.filter(balance=self.public_pipe, source_type="MATERIAL_INBOUND").count(), 1)
        self.assertEqual(PublicStockMovement.objects.filter(balance=self.public_pipe, direction="OUT").count(), 1)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "ISSUED")

    def test_quality_confirmation_and_issue_serialize_task_before_raw_and_zone(self):
        self.receipt_and_issue(quality_pending=True)

    def test_direct_pipe_credit_and_issue_serialize_task_before_raw_and_zone(self):
        self.receipt_and_issue(quality_pending=False)
