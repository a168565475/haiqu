import json
import threading
import uuid
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities
from apps.material_issues.tests.test_public_issue_services import PublicIssueFixture
from apps.outsourcing.models import OutsourcingFactory, OutsourcingOrder, TubeOutsourcingLine, TubeOutsourcingOrder
from apps.outsourcing.public_stock_services import public_dispatch_context
from apps.outsourcing.tests.test_public_stock_flow import PublicOutsourcingFixture

from ..models import PublicStockBalance, PublicStockMovement, WarehouseZone
from ..public_stock_services import debit_public_stock
from ..stock_services import InventoryStockValidationError
from ..tube_outsourcing_reservations import tube_public_reserved_quantities, tube_raw_reserved_quantities


def create_reservation(*, schedule_product, bom_line, craft, factory, employee, source_kind,
                       zone, identity, quantity, stock_quantity):
    today = timezone.localdate()
    order = TubeOutsourcingOrder.objects.create(
        order_number=f"TUBE-RESERVE-{uuid.uuid4().hex}", schedule_product=schedule_product,
        product_line_id=schedule_product.product_line_id, bom_id=bom_line.section.bom_id,
        craft=craft, source_kind=source_kind, zone=zone, planned_dispatch_date=today,
        expected_return_date=today, client_request_id=uuid.uuid4(), request_payload_hash="a" * 64,
        source_revision_hash="b" * 64, created_by_employee=employee, updated_by_employee=employee,
    )
    TubeOutsourcingLine.objects.create(
        order=order, bom_line=bom_line, component_identity=bom_line.component_identity,
        factory=factory, quantity=quantity, stock_quantity=stock_quantity,
        input_identity=json.loads(json.dumps(identity, cls=DjangoJSONEncoder)),
    )
    return order


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=False)
class TubeReservationStockTests(PublicIssueFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.factory = OutsourcingFactory.objects.create(
            factory_number="TUBE-RESERVATION", name="预留加工厂", processing_type="喷塑",
            contact_name="测试", contact_phone="000", address="测试库", created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )

    def reserve(self, quantity=12, *, semi=False, zone=None, scope=None):
        scope = scope or self.scope()
        return create_reservation(
            schedule_product=scope.schedule_product, bom_line=scope.bom_line, craft=self.coating,
            factory=self.factory, employee=self.employee, source_kind="PUBLIC_SEMI" if semi else "RAW_PIPE",
            zone=zone or (self.semi_zone if semi else self.zone),
            identity=self.semi_identity if semi else self.pipe_identity, quantity=quantity,
            stock_quantity=quantity if semi else quantity // 6,
        )

    def quantities(self, issue):
        return public_line_quantities(issue.lines.get(), context=public_issue_quantity_context(issue, exclude_issue_id=issue.pk))

    def debit(self, balance, quantity, **changes):
        values = dict(balance_id=balance.pk, quantity=quantity, source_type="RESERVATION_TEST",
                      source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        values.update(changes)
        return debit_public_stock(**values)

    def test_raw_reservation_combines_existing_pending_without_deducting_stock(self):
        self.submit(self.create("12"))
        self.reserve(18)
        values = self.quantities(self.create("6"))
        self.assertEqual(Decimal(values["pending_issue_quantity"]), 30)
        self.assertEqual(Decimal(values["public_pending_quantity"]), 30)
        self.assertEqual(Decimal(values["max_issue_quantity"]), 30)
        self.assertEqual(Decimal(values["order_remaining"]), self.requirement.required_quantity - 30)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
        self.assertFalse(PublicStockMovement.objects.filter(direction="OUT").exists())

    def test_cross_order_raw_reserves_shared_pool_but_not_other_order_allowance(self):
        other = self.other_scope()
        self.reserve(24, scope=other)
        values = self.quantities(self.create("6"))
        self.assertEqual(Decimal(values["pending_issue_quantity"]), 0)
        self.assertEqual(Decimal(values["public_pending_quantity"]), 24)
        self.assertEqual(Decimal(values["max_issue_quantity"]), 36)

    def test_semi_reservation_combines_old_pending_and_does_not_reduce_raw_allowance(self):
        self.submit(self.create("20", semi=True))
        self.reserve(30, semi=True)
        values = self.quantities(self.create("10", semi=True))
        self.assertEqual(Decimal(values["pending_issue_quantity"]), 20)
        self.assertEqual(Decimal(values["public_pending_quantity"]), 50)
        self.assertEqual(Decimal(values["max_issue_quantity"]), 50)
        raw = self.quantities(self.create("6"))
        self.assertEqual(Decimal(raw["pending_issue_quantity"]), 0)
        self.assertEqual(Decimal(raw["public_pending_quantity"]), 0)

    def test_low_level_cannot_consume_reserved_stock_even_when_entry_flag_is_off(self):
        self.reserve(48)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            with self.assertRaises(InventoryStockValidationError) as caught:
                self.debit(self.public_pipe, 3)
        self.assertEqual(caught.exception.api_error_code, "TUBE_OUTSOURCING_STOCK_RESERVED")
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
        movement = self.debit(self.public_pipe, 2)
        self.assertEqual(movement.after_quantity, 8)

    def test_other_zone_remains_available_and_issue_skips_reserved_zone(self):
        # 让预留库区排在前面，确认领料不会先扣它再失败。
        other_zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="无预留区")
        first, second = sorted([self.zone, other_zone], key=lambda row: row.pk)
        if first.pk != self.zone.pk:
            self.credit(self.pipe_identity, first, 10)
            reserved_zone = first
            free_balance = self.public_pipe
        else:
            free_balance = self.credit(self.pipe_identity, second, 10).balance
            reserved_zone = self.zone
        self.reserve(60, zone=reserved_zone)
        issued = self.confirm(self.submit(self.create("12")))
        allocations = list(issued.lines.get().public_stock_allocations.all())
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].balance_id, free_balance.pk)
        self.assertEqual(allocations[0].stock_quantity, 2)
        self.assertEqual(self.debit(free_balance, 1).after_quantity, 7)

    def test_semi_low_level_guard_uses_stock_identity_and_zone(self):
        self.reserve(99, semi=True)
        with self.assertRaises(InventoryStockValidationError):
            self.debit(self.public_semi, 2)
        self.assertEqual(self.debit(self.public_pipe, 2).after_quantity, 8)
        self.assertEqual(self.debit(self.public_semi, 1).after_quantity, 99)

    def test_successful_debit_replay_is_not_blocked_by_later_reservation(self):
        source_id, source_line_id = uuid.uuid4(), uuid.uuid4()
        first = self.debit(self.public_pipe, 2, source_id=source_id, source_line_id=source_line_id)
        self.reserve(48)
        repeated = self.debit(self.public_pipe, 2, source_id=source_id, source_line_id=source_line_id)
        self.assertEqual(repeated.pk, first.pk)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 8)

    def test_reservations_are_aggregated_in_two_queries_for_multiple_orders(self):
        for _ in range(4):
            self.reserve(6)
        with CaptureQueriesContext(connection) as queries:
            raw = tube_raw_reserved_quantities([(self.product_line.pk, self.bom_line.component_identity)])
            stock = tube_public_reserved_quantities([self.pipe_identity])
        self.assertEqual(len(queries), 2)
        self.assertEqual(raw[(str(self.product_line.pk), str(self.bom_line.component_identity))], 24)
        pool = (self.pipe_identity["stock_kind"], self.pipe_identity["identity_key"], str(self.pipe_identity["unit_id"]))
        self.assertEqual(stock[(pool, str(self.zone.pk))], 4)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeReservationOldOutsourcingTests(PublicOutsourcingFixture, APITestCase):
    def test_new_raw_reservation_reduces_old_outsourcing_context_and_blocks_excess(self):
        order_id = self.create(amount="402")
        order = OutsourcingOrder.objects.get(pk=order_id)
        before = public_dispatch_context(order)["materials"][0]
        create_reservation(
            schedule_product=self.f.schedule_product, bom_line=self.f.profile, craft=order.craft,
            factory=self.f.factory, employee=self.f.employee, source_kind="RAW_PIPE",
            zone=self.pipe_batch.zone, identity=self.identity, quantity=12, stock_quantity=2,
        )
        after = public_dispatch_context(order)["materials"][0]
        self.assertEqual(Decimal(after["order_remaining"]), Decimal(before["order_remaining"]) - 12)
        self.assertEqual(Decimal(after["public_pending_quantity"]), 12)
        self.assertEqual(Decimal(after["max_issue_quantity"]), 396)
        self.dispatch(order_id, amount="402", expected=409)
        self.public_balance.refresh_from_db()
        self.assertEqual(self.public_balance.quantity, 100)


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=False)
class TubeReservationConcurrencyTests(PublicIssueFixture, TransactionTestCase):
    serialized_rollback = True

    def test_debit_rechecks_new_reservation_after_waiting_for_balance_lock(self):
        factory = OutsourcingFactory.objects.create(
            factory_number="TUBE-CONCURRENT", name="并发预留加工厂", processing_type="喷塑",
            contact_name="测试", contact_phone="000", address="测试库", created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        balance_lock_requested = threading.Event()
        results = []

        def observe_lock(execute, sql, params, many, context):
            if "inventory_public_stock_balance" in sql and "FOR UPDATE" in sql.upper():
                balance_lock_requested.set()
            return execute(sql, params, many, context)

        def debit():
            connections.close_all()
            try:
                with connections["default"].execute_wrapper(observe_lock), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                    debit_public_stock(balance_id=self.public_pipe.pk, quantity=3, source_type="TUBE_CONCURRENT",
                        source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
                results.append("UNEXPECTED_DEBIT")
            except InventoryStockValidationError as error:
                results.append(error.api_error_code)
            except Exception as error:
                results.append(f"{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        worker = threading.Thread(target=debit)
        try:
            with transaction.atomic():
                PublicStockBalance.objects.select_for_update().get(pk=self.public_pipe.pk)
                worker.start()
                self.assertTrue(balance_lock_requested.wait(timeout=8), "扣库未到达余额锁")
                create_reservation(
                    schedule_product=self.schedule_product, bom_line=self.bom_line, craft=self.coating,
                    factory=factory, employee=self.employee, source_kind="RAW_PIPE", zone=self.zone,
                    identity=self.pipe_identity, quantity=48, stock_quantity=8,
                )
        finally:
            worker.join(timeout=12)
        self.assertFalse(worker.is_alive(), results)
        self.assertEqual(results, ["TUBE_OUTSOURCING_STOCK_RESERVED"])
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
