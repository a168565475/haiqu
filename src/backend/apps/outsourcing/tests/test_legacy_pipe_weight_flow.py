import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialStockBalance, MaterialStockMovement
from apps.inventory.services import create_manual_material_inbound

from ..dispatch_services import change_pipe_balance
from .test_material_flow import MaterialFlowFixture


class LegacyPipeWeightMovementTests(SimpleTestCase):
    def balance(self, *, roots="3", weight="4.1"):
        return SimpleNamespace(pk=uuid.uuid4(), quantity=Decimal(roots),
            meter_quantity=Decimal(roots) * Decimal("3.05"), raw_bar_length_m=Decimal("3.05"),
            weight_quantity=Decimal(weight) if weight is not None else None,
            bar_weight_kg=None, version=1, save=Mock())

    def change(self, balance, roots, direction, snapshot=None):
        return change_pipe_balance(balance, Decimal(roots), direction=direction,
            source_type="OUTSOURCING_DISPATCH" if direction == "OUT" else "OUTSOURCING_RAW_RETURN",
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), task=None, actor=None, snapshot=snapshot or {})

    def test_split_dispatch_consumes_actual_weight_with_last_root_remainder(self):
        balance = self.balance()
        with patch("apps.outsourcing.dispatch_services.MaterialStockMovement.objects.create") as create:
            self.change(balance, "1", "OUT")
            self.assertEqual(create.call_args.kwargs["weight_quantity"], Decimal("1.3667"))
            self.change(balance, "2", "OUT")
            self.assertEqual(create.call_args.kwargs["weight_quantity"], Decimal("2.7333"))
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (0, 0, 0))

    def test_return_uses_original_remaining_weight(self):
        balance = self.balance(roots="1", weight="1.3667")
        original = SimpleNamespace(quantity=Decimal("3"), weight_quantity=Decimal("4.1"), direction="OUT")
        previous = SimpleNamespace(quantity=Decimal("1"), weight_quantity=Decimal("1.3667"), direction="IN")
        with patch("apps.outsourcing.dispatch_services.MaterialStockMovement.objects.filter") as rows, \
                patch("apps.outsourcing.dispatch_services.MaterialStockMovement.objects.create") as create:
            rows.return_value.first.return_value = original
            rows.return_value.order_by.return_value = [previous]
            self.change(balance, "2", "IN", {"dispatch_line_id": str(uuid.uuid4())})
            self.assertEqual(create.call_args.kwargs["weight_quantity"], Decimal("2.7333"))
        self.assertEqual((balance.quantity, balance.weight_quantity), (3, Decimal("4.1")))

    def test_known_weight_cannot_return_without_original_weight(self):
        for original in (None, SimpleNamespace(weight_quantity=None, direction="OUT", quantity=Decimal("3"))):
            balance = self.balance(roots="0", weight="0")
            with self.subTest(original=original), \
                    patch("apps.outsourcing.dispatch_services.MaterialStockMovement.objects.filter") as rows:
                rows.return_value.first.return_value = original
                rows.return_value.order_by.return_value = []
                with self.assertRaises(APIException):
                    self.change(balance, "1", "IN", {"dispatch_line_id": str(uuid.uuid4())})
            balance.save.assert_not_called()

    def test_historical_unknown_weight_remains_unknown(self):
        balance = self.balance(weight=None)
        with patch("apps.outsourcing.dispatch_services.MaterialStockMovement.objects.create") as create:
            self.change(balance, "1", "OUT")
        self.assertIsNone(balance.weight_quantity)
        self.assertIsNone(create.call_args.kwargs["weight_quantity"])


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False,
                   ACCESS_RESOURCE_SCOPES_ENABLED=False, MODULE_ACCESS_ENABLED=False)
class LegacyOutsourcingWeightFlowTests(MaterialFlowFixture, APITestCase):
    def test_manual_actual_weight_dispatch_partial_return_and_revoke_conserve_weight(self):
        inbound = create_manual_material_inbound(client_request_id=uuid.uuid4(),
            inbound_date=timezone.localdate(), remark="旧库存实际重量守恒验证",
            items=[{"raw_material_id": self.raw_pipe.pk, "zone_id": self.pipe_batch.zone_id,
                    "received_bar_count": 3, "raw_bar_length_m": Decimal("3.05"),
                    "received_weight_kg": Decimal("4.1")}], actor_employee=self.f.employee, request=None)
        self.pipe_batch = inbound.lines.get()
        balance = MaterialStockBalance.objects.get(inbound_line=self.pipe_batch)
        self.assertEqual((inbound.stock_mode, balance.quantity, balance.weight_quantity),
                         ("LEGACY", 3, Decimal("4.1")))
        order_id = self.create(amount="18")
        _, source = self.dispatch(order_id, amount="18")
        original = MaterialStockMovement.objects.get(source_type="OUTSOURCING_DISPATCH", source_line_id=source.pk)
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (0, 0, 0))
        self.assertEqual((original.quantity, original.weight_quantity), (3, Decimal("4.1")))
        self.raw_return(order_id, source, 1)
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.weight_quantity), (1, Decimal("1.3667")))
        request_id = str(uuid.uuid4())
        payload = {"request_id": request_id, "reason": "退回其余实际重量"}
        self.post(order_id, "revoke-dispatched", payload)
        self.post(order_id, "revoke-dispatched", payload)
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity),
                         (3, Decimal("9.15"), Decimal("4.1")))
        returned = MaterialStockMovement.objects.filter(balance=balance, source_type="OUTSOURCING_RAW_RETURN")
        self.assertEqual(returned.count(), 2)
        self.assertEqual(sum(row.weight_quantity for row in returned), original.weight_quantity)
