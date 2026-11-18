"""保留整根取整的数学边界，并验证不能静默丢弃仍有重量的库存。"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.inventory.pipe_receipts import quality_pipe_quantities
from apps.procurement.pipe_purchase import pipe_roots_from_weight


class PipeWeightRoundingBoundaryTests(SimpleTestCase):
    def test_reproduces_rounded_roots_requiring_more_than_received_weight(self):
        received_weight = Decimal("4.1")
        bar_weight = Decimal("2.5")
        roots = pipe_roots_from_weight(received_weight, bar_weight)

        self.assertEqual(roots, 2)
        self.assertEqual(roots * bar_weight, Decimal("5"))
        self.assertGreater(roots * bar_weight, received_weight)

    def test_partial_weight_return_keeps_rounded_remaining_roots(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="KG",
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=2, received_weight_kg=Decimal("4.1"),
            received_quantity=Decimal("12"),
        )

        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("3")}), Decimal("6"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (1, 1))
        self.assertEqual((line.return_weight_kg, line.accepted_weight_kg), (Decimal("3"), Decimal("1.1")))

    def test_small_weight_return_can_have_zero_reference_roots(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="公斤",
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=1, received_weight_kg=Decimal("2"),
        )
        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("0.1")}), Decimal("0"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (0, 1))
        self.assertEqual((line.return_weight_kg, line.accepted_weight_kg), (Decimal("0.1"), Decimal("1.9")))

    def test_reproduces_receipt_splitting_changing_derived_root_total(self):
        bar_weight = Decimal("2.5")
        once = pipe_roots_from_weight(Decimal("5"), bar_weight)
        split = sum(pipe_roots_from_weight(weight, bar_weight) for weight in (Decimal("1"), Decimal("4")))

        self.assertEqual(once, 2)
        self.assertEqual(split, 3)

    def test_whole_standard_weight_return_has_matching_roots_and_weight(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="KG",
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=2, received_weight_kg=Decimal("5"),
        )

        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("2.5")}), Decimal("6"))
        self.assertEqual(line.accepted_bar_count, 1)
        self.assertEqual(line.accepted_weight_kg, Decimal("2.5"))
