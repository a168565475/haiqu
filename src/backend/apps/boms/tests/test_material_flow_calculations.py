from decimal import Decimal, localcontext
from types import SimpleNamespace
from django.test import SimpleTestCase

from apps.boms.material_flow_calculations import MaterialFlowValueError, fabric_output, pipe_issue, pipe_plan, pipe_plan_for_line


class MaterialFlowCalculationTests(SimpleTestCase):
    def plan(self, **changes):
        return pipe_plan(**{"cutting_length_mm": 500, "pieces_per_product": 2, "pieces_per_bar": 6, "order_quantity": 1000, **changes})

    def test_new_purchase_uses_net_demand_and_whole_bars(self):
        result = self.plan()
        self.assertEqual((result["schema_version"], result["calculation_version"], result["raw_bar_length_m"], result["suggested_bar_count"], result["suggested_purchase_meters"], result["allowance_pieces"]), (2, 3, "3.05", 334, "1018.70", 2004))

    def test_exact_whole_bar_demand_has_no_extra_allowance(self):
        result = self.plan(order_quantity=2000, pieces_per_bar=5)
        self.assertEqual((result["demand_pieces"], result["suggested_bar_count"], result["allowance_pieces"]), (4000, 800, 4000))

    def test_legacy_snapshot_keeps_original_keys_and_values(self):
        self.assertEqual(self.plan(calculation_version=2), {
            "schema_version": 2, "cutting_length_mm": 500, "pieces_per_product": 2,
            "pieces_per_bar": 6, "order_quantity": 1000, "demand_pieces": 2000,
            "raw_bar_length_m": "3.05", "suggested_bar_count": 337,
            "suggested_purchase_meters": "1027.85", "allowance_pieces": 2022,
        })

    def test_saved_unmarked_line_reads_legacy_and_marked_line_reads_new_version(self):
        line = SimpleNamespace(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=5,
            raw_values={}, section=SimpleNamespace(bom=SimpleNamespace(order_quantity=2000)))
        self.assertEqual(pipe_plan_for_line(line)["allowance_pieces"], 4040)
        self.assertEqual(line.raw_values, {})
        line.raw_values["pipe_plan_version"] = 3
        self.assertEqual(pipe_plan_for_line(line)["allowance_pieces"], 4000)

    def test_unknown_calculation_versions_are_rejected(self):
        for value in (None, True, "3", 3.0, 0, 4):
            with self.subTest(version=value), self.assertRaises(MaterialFlowValueError):
                self.plan(calculation_version=value)

    def test_length_always_rounds_up(self):
        self.assertEqual(self.plan(cutting_length_mm=501)["raw_bar_length_m"], "3.06")

    def test_issue_requires_whole_roots_and_exact_meters(self):
        with self.assertRaises(MaterialFlowValueError) as error:
            pipe_issue(requested_pieces=2000, pieces_per_bar=6, raw_bar_length_m="3.05")
        self.assertEqual(error.exception.code, "PIPE_WHOLE_BAR_REQUIRED")
        self.assertEqual(pipe_issue(requested_pieces=2004, pieces_per_bar=6, raw_bar_length_m="3.05"),
                         {"requested_pieces": 2004, "bar_count": 334, "meters": "1018.70"})

    def test_invalid_integer_inputs_are_not_rounded(self):
        for value in [None, "", "NaN", "sNaN", "Infinity", "-1", "0", "1.2", True, 1.0, "1e1000000", "999999999999999"]:
            with self.subTest(value=value), self.assertRaises(MaterialFlowValueError):
                self.plan(pieces_per_bar=value)

    def test_overflow_from_multiplication_is_rejected(self):
        with self.assertRaises(MaterialFlowValueError):
            self.plan(order_quantity=99999999999999, pieces_per_product=2)

    def test_caller_decimal_precision_does_not_change_results(self):
        with localcontext() as context:
            context.prec = 6
            result = self.plan(order_quantity=1234567)
        self.assertEqual(result, self.plan(order_quantity=1234567))

    def test_fabric_sets_and_remainder_are_separate(self):
        self.assertEqual(fabric_output(issued_meters="100", meters_per_set="1.5"), {"expected_sets": 66, "remainder_meters": "1.0000"})
        self.assertEqual(fabric_output(issued_meters="1", meters_per_set="1.5"), {"expected_sets": 0, "remainder_meters": "1.0000"})

    def test_excess_fabric_precision_is_rejected(self):
        with self.assertRaises(MaterialFlowValueError):
            fabric_output(issued_meters="1.00001", meters_per_set="1")
