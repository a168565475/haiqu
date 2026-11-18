from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.pipe_weight_quantities import returned_pipe_weight
from apps.inventory.public_stock_services import _check_replay, _locked_balance, _record


class PipeWeightReturnTests(SimpleTestCase):
    def movement(self, roots, weight, direction="OUT"):
        return SimpleNamespace(quantity=Decimal(roots), weight_quantity=None if weight is None else Decimal(weight), direction=direction)

    def test_full_return_restores_actual_dispatch_weight(self):
        self.assertEqual(returned_pipe_weight(original=self.movement("2", "4.1"), adjustments=[], returned_roots=2), Decimal("4.1"))

    def test_partial_returns_conserve_all_original_weight(self):
        original = self.movement("3", "1")
        history = []
        for _ in range(3):
            weight = returned_pipe_weight(original=original, adjustments=history, returned_roots=1)
            history.append(self.movement("1", weight, "IN"))
        self.assertEqual(sum(row.weight_quantity for row in history), Decimal("1"))

    def test_correction_can_return_original_and_additional_dispatch_weight(self):
        original = self.movement("2", "4.1")
        history = [self.movement("1", "2.05", "IN"), self.movement("2", "3.2", "OUT")]
        self.assertEqual(returned_pipe_weight(original=original, adjustments=history, returned_roots=3), Decimal("5.25"))

    def test_legacy_unknown_weight_is_never_invented(self):
        self.assertIsNone(returned_pipe_weight(original=self.movement("2", None), adjustments=[], returned_roots=1))

    def test_missing_or_excessive_historical_weight_blocks_return(self):
        for history in ([self.movement("1", None, "IN")], [self.movement("1", "5", "IN")]):
            with self.subTest(history=history), self.assertRaises(ValidationError):
                returned_pipe_weight(original=self.movement("2", "4.1"), adjustments=history, returned_roots=1)

    def test_known_weight_cannot_be_credited_without_actual_weight(self):
        balance = SimpleNamespace(quantity=Decimal("2"), raw_bar_length_m=Decimal("6"), meter_quantity=Decimal("12"),
            bar_weight_kg=Decimal("2.5"), weight_quantity=Decimal("4.1"), save=Mock())
        with self.assertRaises(ValidationError):
            _record(balance=balance, quantity=Decimal("1"), direction="IN", source={})
        balance.save.assert_not_called()

    def test_legacy_unknown_credit_remains_supported(self):
        balance = SimpleNamespace(quantity=Decimal("2"), raw_bar_length_m=Decimal("6"), meter_quantity=Decimal("12"),
            bar_weight_kg=None, weight_quantity=None, save=Mock(), stock_kind="RAW_PIPE", version=1)
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create"):
            _record(balance=balance, quantity=Decimal("1"), direction="IN", source={})
        self.assertEqual(balance.quantity, Decimal("3"))
        self.assertIsNone(balance.weight_quantity)

    def locked(self, *, roots, weight, requested_weight, existing_bar_weight=None, incoming_bar_weight=None):
        identity = {"stock_kind": "RAW_PIPE", "identity_key": "pipe", "unit_id": uuid4(),
            "identity_snapshot": {}, "raw_material_id": uuid4(), "raw_bar_length_m": Decimal("6")}
        balance = SimpleNamespace(identity_snapshot={}, raw_material_id=identity["raw_material_id"],
            raw_bar_length_m=Decimal("6"), quantity=Decimal(roots), meter_quantity=Decimal(roots) * 6,
            bar_weight_kg=existing_bar_weight, weight_quantity=weight, save=Mock(), stock_kind="RAW_PIPE", version=1)
        with patch("apps.inventory.public_stock_services.PublicStockBalance.objects.select_for_update") as rows:
            rows.return_value.filter.return_value.order_by.return_value.first.return_value = balance
            return _locked_balance(identity, uuid4(), "AVAILABLE", weight_quantity=requested_weight, bar_weight_kg=incoming_bar_weight)

    def test_empty_legacy_balance_can_start_new_actual_weight_without_standard_weight(self):
        balance = self.locked(roots="0", weight=None, requested_weight=Decimal("4.1"))
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create") as create:
            _record(balance=balance, quantity=Decimal("2"), direction="IN", source={}, weight_quantity=Decimal("4.1"))
        self.assertEqual(balance.weight_quantity, Decimal("4.1"))
        self.assertIsNone(balance.bar_weight_kg)
        self.assertEqual(create.call_args.kwargs["before_weight_quantity"], 0)

    def test_positive_legacy_balance_cannot_be_backfilled_with_incoming_weight(self):
        with self.assertRaises(ValidationError) as caught:
            self.locked(roots="2", weight=None, requested_weight=Decimal("4.1"))
        self.assertEqual(caught.exception.api_error_code, "IDENTITY_CONFLICT")

    def test_known_weight_stock_accepts_different_source_standard_weights(self):
        for previous, incoming in ((None, Decimal("2.5")), (Decimal("2.5"), Decimal("2.6")), (Decimal("2.5"), None)):
            with self.subTest(previous=previous, incoming=incoming):
                balance = self.locked(roots="2", weight=Decimal("4.1"), requested_weight=Decimal("3.2"),
                    existing_bar_weight=previous, incoming_bar_weight=incoming)
                with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create"):
                    _record(balance=balance, quantity=Decimal("2"), direction="IN", source={}, weight_quantity=Decimal("3.2"))
                self.assertEqual((balance.quantity, balance.weight_quantity), (4, Decimal("7.3")))
                self.assertIsNone(balance.bar_weight_kg)

    def test_credit_replay_rejects_changed_actual_weight(self):
        source = {name: None for name in ("source_id", "production_task_id", "product_line_id", "bom_line_id")}
        source["snapshot"] = {}
        movement = SimpleNamespace(quantity=Decimal("2"), weight_quantity=Decimal("4.1"), **source)
        with self.assertRaises(ValidationError) as caught:
            _check_replay(movement, source=source, quantity=Decimal("2"), check_weight=True, weight_quantity=Decimal("4.2"))
        self.assertEqual(caught.exception.api_error_code, "IDEMPOTENCY_CONFLICT")
