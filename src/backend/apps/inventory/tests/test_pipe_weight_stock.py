from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.pipe_weight_quantities import issued_pipe_weight
from apps.inventory.public_stock_services import _record


class PipeWeightStockTests(SimpleTestCase):
    def test_partial_issue_uses_actual_weight_share(self):
        self.assertEqual(issued_pipe_weight(available_roots=2, available_weight_kg=Decimal("4.1"), issued_roots=1), Decimal("2.0500"))

    def test_last_issue_takes_all_remaining_weight(self):
        remaining = Decimal("1")
        weights = []
        for roots in (3, 2, 1):
            weight = issued_pipe_weight(available_roots=roots, available_weight_kg=remaining, issued_roots=1)
            weights.append(weight)
            remaining -= weight
        self.assertEqual(sum(weights), Decimal("1"))
        self.assertEqual(remaining, 0)

    def test_full_issue_uses_actual_weight_even_when_standard_total_is_larger(self):
        self.assertEqual(issued_pipe_weight(available_roots=2, available_weight_kg=Decimal("4.1"), issued_roots=2), Decimal("4.1"))

    def test_missing_negative_or_nonfinite_weight_is_rejected(self):
        for value in (None, Decimal("-0.0001"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                issued_pipe_weight(available_roots=2, available_weight_kg=value, issued_roots=1)

    def test_invalid_or_excessive_root_quantity_is_rejected(self):
        for available, issued in ((0, 1), (2, 3), (2, 0), (2, Decimal("0.5"))):
            with self.subTest(available=available, issued=issued), self.assertRaises(ValidationError):
                issued_pipe_weight(available_roots=available, available_weight_kg=Decimal("4.1"), issued_roots=issued)

    def balance(self, **changes):
        return SimpleNamespace(quantity=Decimal("2"), raw_bar_length_m=Decimal("6"),
            meter_quantity=Decimal("12"), bar_weight_kg=Decimal("2.5"),
            weight_quantity=Decimal("4.1"), version=1, stock_kind="RAW_PIPE", save=Mock(), **changes)

    def test_public_stock_full_root_issue_clears_actual_weight(self):
        balance = self.balance()
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create") as create:
            _record(balance=balance, quantity=Decimal("2"), direction="OUT", source={})
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (0, 0, 0))
        self.assertEqual(create.call_args.kwargs["weight_quantity"], Decimal("4.1"))

    def test_legacy_unknown_weight_stays_unknown(self):
        balance = self.balance()
        balance.bar_weight_kg = balance.weight_quantity = None
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create") as create:
            _record(balance=balance, quantity=Decimal("1"), direction="OUT", source={})
        self.assertIsNone(balance.weight_quantity)
        self.assertIsNone(create.call_args.kwargs["weight_quantity"])

    def test_public_stock_missing_weight_rejects_before_save(self):
        balance = self.balance()
        balance.weight_quantity = None
        with self.assertRaises(ValidationError):
            _record(balance=balance, quantity=Decimal("1"), direction="OUT", source={})
        balance.save.assert_not_called()
