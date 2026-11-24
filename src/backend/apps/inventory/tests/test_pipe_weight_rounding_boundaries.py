"""保留整根取整的数学边界，并验证不能静默丢弃仍有重量的库存。"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.pipe_receipts import estimated_receipt_roots, quality_pipe_quantities
from apps.procurement.pipe_purchase import pipe_roots_from_weight


class PipeWeightRoundingBoundaryTests(SimpleTestCase):
    def test_purchase_order_still_rounds_up_its_reference_roots(self):
        received_weight = Decimal("4.1")
        bar_weight = Decimal("2.5")
        roots = pipe_roots_from_weight(received_weight, bar_weight)

        self.assertEqual(roots, 2)
        self.assertEqual(roots * bar_weight, Decimal("5"))
        self.assertGreater(roots * bar_weight, received_weight)

    def test_existing_receipt_keeps_its_original_partial_return_rule(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="KG", calculation_snapshot={},
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=2, received_weight_kg=Decimal("4.1"),
            received_quantity=Decimal("12"),
        )

        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("3")}), Decimal("6"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (1, 1))
        self.assertEqual((line.return_weight_kg, line.accepted_weight_kg), (Decimal("3"), Decimal("1.1")))

    def test_small_weight_return_can_have_zero_reference_roots(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="公斤", calculation_snapshot={},
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=1, received_weight_kg=Decimal("2"),
        )
        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("0.1")}), Decimal("0"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (0, 1))
        self.assertEqual((line.return_weight_kg, line.accepted_weight_kg), (Decimal("0.1"), Decimal("1.9")))

    def test_new_partial_return_uses_whole_remaining_roots_and_keeps_all_actual_weight(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="KG",
            calculation_snapshot={"receipt_root_rounding": "FLOOR"},
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=3, received_weight_kg=Decimal("8.1"),
        )
        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("3.2")}), Decimal("12"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count, line.accepted_weight_kg), (2, 1, Decimal("4.9")))
        with self.assertRaisesMessage(ValidationError, "不足一根"):
            quality_pipe_quantities(line, {"return_weight_kg": Decimal("5.7")})

    def test_production_receipts_only_count_whole_roots_in_each_batch(self):
        bar_weight = Decimal("2.5")
        once = estimated_receipt_roots(Decimal("8.2"), bar_weight, round_down=True)
        split = sum(estimated_receipt_roots(weight, bar_weight, round_down=True) for weight in (Decimal("4.1"), Decimal("4.1")))

        self.assertEqual(once, 3)
        self.assertEqual(split, 2)

    def test_whole_standard_weight_return_has_matching_roots_and_weight(self):
        line = SimpleNamespace(
            measurement_kind="PIPE", source_unit_text_snapshot="KG", calculation_snapshot={},
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=2, received_weight_kg=Decimal("5"),
        )

        self.assertEqual(quality_pipe_quantities(line, {"return_weight_kg": Decimal("2.5")}), Decimal("6"))
        self.assertEqual(line.accepted_bar_count, 1)
        self.assertEqual(line.accepted_weight_kg, Decimal("2.5"))
