from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.sales_orders.api.serializers import DeliveryBatchLineReadSerializer, SalesOrderListSerializer


def relation(*items):
    return SimpleNamespace(all=lambda: items)


def allocation_line(quantity, allocated, *, tolerance="3", cancelled=False):
    task = SimpleNamespace(status="CANCELLED" if cancelled else "DRAFT")
    product = SimpleNamespace(quantity=Decimal(allocated), production_task=task, production_task_id="task-1")
    batch = SimpleNamespace(
        status="ACTIVE", sales_order=SimpleNamespace(order_tolerance_percent=Decimal(tolerance)),
        production_tasks=relation(),
    )
    line = SimpleNamespace(quantity=Decimal(quantity), production_task_products=relation(product), delivery_batch=batch)
    batch.lines = relation(line)
    return line


class ProductionCapacityTests(SimpleTestCase):
    def test_nominal_quantity_fully_allocated_has_no_remaining_even_with_tolerance(self):
        line = allocation_line("100", "100")
        self.assertEqual(Decimal(DeliveryBatchLineReadSerializer().get_remaining_quantity(line)), Decimal("0"))

    def test_partial_allocation_remaining_excludes_tolerance(self):
        line = allocation_line("100", "80")
        self.assertEqual(Decimal(DeliveryBatchLineReadSerializer().get_remaining_quantity(line)), Decimal("20"))

    def test_cancelled_production_does_not_consume_allocation(self):
        line = allocation_line("100", "100", cancelled=True)
        self.assertEqual(Decimal(DeliveryBatchLineReadSerializer().get_remaining_quantity(line)), Decimal("100"))

    def test_source_order_availability_tracks_all_active_lines(self):
        complete = allocation_line("100", "100").delivery_batch
        partial = allocation_line("50", "20").delivery_batch
        serializer = SalesOrderListSerializer()
        availability = getattr(serializer, "get_has_remaining_production_capacity", lambda order: None)
        self.assertIs(availability(SimpleNamespace(delivery_batches=relation(complete))), False)
        self.assertIs(availability(SimpleNamespace(delivery_batches=relation(complete, partial))), True)
        partial.status = "CANCELLED"
        self.assertIs(availability(SimpleNamespace(delivery_batches=relation(complete, partial))), False)

