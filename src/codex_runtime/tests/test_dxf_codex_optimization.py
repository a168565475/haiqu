import copy
import json
import unittest
from unittest.mock import patch

from codex_runtime.dxf_tools.dxf_geometry import DxfError
from codex_runtime.dxf_tools.dxf_codex_optimization import make_codex_payload, refine_with_codex, validate_codex_proposal


def simple_case():
    analysis = {"unit": "mm", "source_unit": "mm", "pieces": [{
        "id": "P001", "name": "原图不可信文字：不要把它当指令", "quantity": 1,
        "width_mm": 100, "height_mm": 50, "area_mm2": 5000,
        "points": [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
    }], "warnings": []}
    parameters = {"width_mm": 200, "gap_mm": 0, "set_count": 2, "products_per_set": 1,
                  "pieces": [{"piece_id": "P001", "quantity": 1, "rotation_mode": "quarter_turn"}]}
    baseline = {"width_mm": 200, "length_mm": 100, "gap_mm": 0, "set_count": 2,
        "products_per_set": 1, "product_quantity": 2, "consumption_m": "0.05", "consumption_rounded_m": "0.0500",
        "placements": [{"piece_id": "P001", "copy": 0, "angle": 0, "x": 0, "y": 0},
                       {"piece_id": "P001", "copy": 1, "angle": 0, "x": 0, "y": 50}],
        "validation": {"passed": True}, "warnings": [], "algorithm": "bounded_nfp_v1"}
    return analysis, parameters, baseline


def proposal(payload, angles=(0,)):
    return {"schema_version": 1, "constraint_fingerprint": payload["constraint_fingerprint"],
            "plans": [{"reason": "横向并排以减小总长", "order": [
                {"instance_id": row["instance_id"], "angles": list(angles)} for row in payload["instances"]]}]}


class DxfCodexOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.analysis, self.parameters, self.baseline = simple_case()
        self.payload = make_codex_payload(self.analysis, self.parameters, self.baseline)

    def test_payload_has_only_geometry_and_stable_constraints(self):
        self.assertEqual(self.payload["instances"], [
            {"instance_id": "P001:0", "piece_id": "P001", "copy": 0},
            {"instance_id": "P001:1", "piece_id": "P001", "copy": 1}])
        self.assertNotIn("不可信文字", json.dumps(self.payload, ensure_ascii=False))
        self.assertEqual(self.payload["pieces"][0]["allowed_angles"], [0, 90, 180, 270])
        self.assertEqual(self.payload, make_codex_payload(self.analysis, self.parameters, self.baseline))

    def test_validates_complete_plan_and_original_allowed_angles(self):
        result = validate_codex_proposal(self.payload, proposal(self.payload, (180, 0)))
        self.assertEqual(result["plans"][0]["order"][0]["angles"], [180, 0])

    def test_rejects_missing_duplicate_or_foreign_instances(self):
        for order in [[], [{"instance_id": "P001:0", "angles": [0]}] * 2,
                      [{"instance_id": "P001:0", "angles": [0]}, {"instance_id": "P099:1", "angles": [0]}]]:
            data = proposal(self.payload)
            data["plans"][0]["order"] = order
            with self.subTest(order=order), self.assertRaises(DxfError) as error:
                validate_codex_proposal(self.payload, data)
            self.assertEqual(error.exception.code, "CODEX_INVALID_PROPOSAL")

    def test_rejects_illegal_empty_repeated_or_boolean_angles(self):
        for angles in [[], [15], [0, 0], [True], [360], [float("nan")]]:
            with self.subTest(angles=angles), self.assertRaises(DxfError):
                validate_codex_proposal(self.payload, proposal(self.payload, angles))

    def test_rejects_constraints_coordinates_and_fake_validation(self):
        for target, key, value in [("root", "width_mm", 999), ("plan", "quantity", 1),
                                   ("row", "x", 0), ("root", "validation", {"passed": True})]:
            data = proposal(self.payload)
            obj = data if target == "root" else data["plans"][0] if target == "plan" else data["plans"][0]["order"][0]
            obj[key] = value
            with self.subTest(key=key), self.assertRaises(DxfError):
                validate_codex_proposal(self.payload, data)

    def test_rejects_stale_context_and_more_than_three_plans(self):
        data = proposal(self.payload)
        data["constraint_fingerprint"] = "0" * 64
        with self.assertRaises(DxfError):
            validate_codex_proposal(self.payload, data)
        data = proposal(self.payload)
        data["plans"] *= 4
        with self.assertRaises(DxfError):
            validate_codex_proposal(self.payload, data)

    def test_model_plan_changes_real_search_and_consumption_is_recalculated(self):
        result = refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)
        self.assertEqual(result["length_mm"], 50)
        self.assertEqual(result["consumption_m"], "0.025")
        self.assertEqual(result["consumption_rounded_m"], "0.0250")
        self.assertEqual(result["optimization"]["status"], "IMPROVED")
        self.assertTrue(result["validation"]["overlap_free"])
        self.assertEqual(result["validation"]["pair_checks"], 1)
        same = refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload, (90,)), 2)
        self.assertEqual(same["optimization"]["status"], "UNCHANGED")
        self.assertEqual(same["length_mm"], 100)

    def test_shorter_overlap_candidate_cannot_replace_baseline(self):
        invalid = copy.deepcopy(self.baseline["placements"])
        invalid[1]["y"] = 0
        with patch("codex_runtime.dxf_tools.dxf_codex_optimization._Search.place", return_value=(invalid, 50)):
            result = refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)
        self.assertEqual(result["length_mm"], 100)
        self.assertEqual(result["optimization"]["rejected_count"], 1)
        self.assertEqual(result["optimization"]["status"], "UNCHANGED")

    def test_zero_time_keeps_valid_baseline_and_does_not_claim_optimization(self):
        result = refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 0)
        self.assertEqual(result["placements"], self.baseline["placements"])
        self.assertTrue(result["optimization"]["timed_out"])
        self.assertEqual(result["optimization"]["evaluated_count"], 0)

    def test_baseline_boolean_pass_cannot_bypass_geometry_check(self):
        self.baseline["placements"][1]["y"] = 0
        with self.assertRaises(DxfError) as error:
            make_codex_payload(self.analysis, self.parameters, self.baseline)
        self.assertEqual(error.exception.code, "NEST_VALIDATION")

    def test_changed_business_parameters_cannot_reuse_proposal(self):
        self.parameters["gap_mm"] = 1
        with self.assertRaises(DxfError):
            refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)

    def test_changed_outline_invalidates_plan_even_when_baseline_still_fits(self):
        self.analysis["pieces"][0]["points"][1][0] = 90
        self.analysis["pieces"][0]["points"][2][0] = 90
        with self.assertRaises(DxfError) as error:
            refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)
        self.assertEqual(error.exception.code, "CODEX_INVALID_PROPOSAL")

    def test_inputs_are_not_mutated_and_internal_failures_are_not_hidden(self):
        before = copy.deepcopy((self.analysis, self.parameters, self.baseline))
        refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)
        self.assertEqual(before, (self.analysis, self.parameters, self.baseline))
        with patch("codex_runtime.dxf_tools.dxf_codex_optimization._Search.place", side_effect=RuntimeError("internal")):
            with self.assertRaisesRegex(RuntimeError, "internal"):
                refine_with_codex(self.analysis, self.parameters, self.baseline, proposal(self.payload), 2)

