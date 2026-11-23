import copy
import json
import unittest
from decimal import Decimal, localcontext

from rest_framework.exceptions import ValidationError

from apps.boms.hardware_weight import calculate_hardware_weight
from apps.boms.hardware_weight_data import RIVET_STEEL_WEIGHT_G


class HardwareWeightCalculationTests(unittest.TestCase):
    def rivet(self, **changes):
        return calculate_hardware_weight({
            "kind": "RIVET_GB873_STEEL", "material": "碳钢", "specification": "5×30", **changes,
        })

    def washer(self, **changes):
        return calculate_hardware_weight({
            "kind": "PLAIN_WASHER", "material": "碳钢", "specification": "非标平垫",
            "outer_diameter_mm": "12", "inner_diameter_mm": "6.4", "thickness_mm": "1.6", **changes,
        })

    def test_rivet_examples_match_reference_table_and_convert_grams_to_kg(self):
        for specification, grams, kg in (
            ("4×20", "2", "0.00200000"),
            ("5×30", "4.67", "0.00467000"),
            ("6×30", "6.69", "0.00669000"),
            ("5×50", "7.73", "0.00773000"),
        ):
            with self.subTest(specification=specification):
                result = self.rivet(specification=specification)
                self.assertEqual(result["unit_weight_g"], grams)
                self.assertEqual(result["unit_material_weight_kg"], kg)
                self.assertEqual(result["calculation_snapshot"]["method"], "STANDARD_TABLE")

    def test_small_rivet_does_not_round_to_zero(self):
        result = self.rivet(specification="1.2×1.5")
        self.assertEqual(result["unit_material_weight_kg"], "0.00002000")

    def test_reference_table_retains_empty_cells_and_excludes_disputed_length(self):
        self.assertEqual(RIVET_STEEL_WEIGHT_G[("1.4", "7")], "0.09")
        self.assertNotIn(("1.2", "7"), RIVET_STEEL_WEIGHT_G)
        self.assertFalse(any(length in ("38", "39") for _, length in RIVET_STEEL_WEIGHT_G))
        for (diameter, length), weight in RIVET_STEEL_WEIGHT_G.items():
            with self.subTest(diameter=diameter, length=length):
                result = self.rivet(specification=f"{diameter}×{length}")
                self.assertEqual(Decimal(result["unit_weight_g"]), Decimal(weight))
                self.assertEqual(result["calculation_snapshot"]["method"], "STANDARD_TABLE")

    def test_unlisted_rivet_lengths_are_estimated_from_steel_dimensions(self):
        for specification, grams in (("5*53", "8.28"), ("4×21", "2.16"), ("4×38", "3.84"),
                                     ("4×39", "3.94"), ("1.2×7", "0.07"), ("5×65", "10.13")):
            with self.subTest(specification=specification):
                result = self.rivet(specification=specification)
                self.assertEqual(result["unit_weight_g"], grams)
                self.assertEqual(Decimal(result["unit_material_weight_kg"]), Decimal(grams) / 1000)
                snapshot = result["calculation_snapshot"]
                self.assertEqual(snapshot["method"], "RIVET_GEOMETRY_ESTIMATE")
                self.assertNotIn("table_weight_kg_per_1000", snapshot)
                self.assertEqual(calculate_hardware_weight(snapshot["input"]), result)
        geometry = self.rivet(specification="5×53")["calculation_snapshot"]["geometry"]
        self.assertEqual(geometry["head_diameter_mm"], "10")
        self.assertEqual(geometry["hole_diameter_mm"], "3.54")
        self.assertEqual(geometry["density_g_cm3"], "7.85")

    def test_rivet_estimate_requires_known_steel_profile_and_room_for_the_hole(self):
        for specification in ("5.5×30", "5×1", "1.5mm", "110*16*1.8"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                self.rivet(specification=specification)
        with self.assertRaises(ValidationError):
            self.rivet(material="PE", specification="5×53")

    def test_rivet_requires_explicit_carbon_steel_identity(self):
        for material in ("", "未知", "不锈钢", "304", "铝", "铜", "304钢", "铝合金"):
            with self.subTest(material=material), self.assertRaises(ValidationError):
                self.rivet(material=material)
        self.assertEqual(self.rivet(material="Q235B")["unit_weight_g"], "4.67")

    def test_rivet_specification_accepts_only_unambiguous_diameter_and_length(self):
        for specification in (" Φ5 x 30 mm ", "GB/T 873-1986 5×30", "5*30", "GB873-86 5X30"):
            with self.subTest(specification=specification):
                self.assertEqual(self.rivet(specification=specification)["unit_weight_g"], "4.67")
        for specification in ("5×30×2", "5/30", "M5", "GB/T875 5×30", "5×30 或 6×30"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                self.rivet(specification=specification)

    def test_explicit_rivet_dimensions_work_without_specification(self):
        result = self.rivet(specification="", diameter_mm="5.0", length_mm="30.00")
        self.assertEqual(result["unit_weight_g"], "4.67")
        self.assertEqual(result["calculation_snapshot"]["input"]["diameter_mm"], "5")

    def test_catalog_diameter_symbols_are_equivalent_for_rivet_and_washer(self):
        for symbol in ("Φ", "φ", "Ф", "ф", "∅", "Ø", "⌀"):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.rivet(material="65Mn", specification=f"{symbol}4*40")["unit_material_weight_kg"], "0.00396000")
                washer = calculate_hardware_weight({
                    "kind": "PLAIN_WASHER", "material": "碳钢", "specification": f"{symbol}6",
                })
                self.assertEqual(washer["unit_material_weight_kg"], "0.00101645")

    def test_rivet_rejects_incomplete_or_conflicting_dimensions(self):
        for changes in ({"diameter_mm": "5"}, {"diameter_mm": "6", "length_mm": "30"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.rivet(**changes)

    def test_catalog_rivet_specification_and_size_are_checked_together(self):
        result = self.rivet(material="65Mn", specification="Φ4-40 / 4×40")
        self.assertEqual(result["unit_material_weight_kg"], "0.00396000")
        self.assertEqual(calculate_hardware_weight(result["calculation_snapshot"]["input"]), result)
        for specification in ("Φ4-40 / 4×35", "GB/T873-1986 4×40 / GB/T875 4×40"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                self.rivet(specification=specification, diameter_mm="4", length_mm="40")

    def test_rivet_does_not_scale_steel_table_by_other_density(self):
        self.assertEqual(self.rivet(density_g_cm3="7.85")["unit_weight_g"], "4.67")
        with self.assertRaises(ValidationError):
            self.rivet(density_g_cm3="2.7")

    def test_washer_uses_annular_volume_and_precise_kg(self):
        result = self.washer()
        self.assertEqual(result["unit_weight_g"], "1.01644848")
        self.assertEqual(result["unit_material_weight_kg"], "0.00101645")
        self.assertEqual(result["calculation_snapshot"]["parameters"]["density_g_cm3"], "7.85")

    def test_standard_washer_resolves_actual_hole_not_nominal_size(self):
        result = calculate_hardware_weight({
            "kind": "PLAIN_WASHER", "material": "碳钢", "specification": "GB/T 97.1-2002 M6",
        })
        snapshot = result["calculation_snapshot"]
        self.assertEqual(result["unit_weight_g"], "1.01644848")
        self.assertEqual(snapshot["input"]["inner_diameter_mm"], "6.4")
        self.assertEqual(snapshot["dimensions_source"], "STANDARD_TABLE")

    def test_standard_small_washer_retains_nonzero_weight(self):
        result = calculate_hardware_weight({
            "kind": "PLAIN_WASHER", "material": "碳钢", "specification": "GB/T 97.1-2002 M1.6",
        })
        self.assertGreater(Decimal(result["unit_material_weight_kg"]), 0)
        self.assertLess(Decimal(result["unit_material_weight_kg"]), Decimal("0.0001"))

    def test_washer_accepts_bare_m6_as_the_default_plain_washer_standard(self):
        result = calculate_hardware_weight({"kind": "PLAIN_WASHER", "material": "碳钢", "specification": "M6"})
        self.assertEqual(result["unit_weight_g"], "1.01644848")
        self.assertEqual(result["calculation_snapshot"]["dimensions_source"], "STANDARD_TABLE")
        self.assertIn("GB/T 97.1-2002", result["calculation_snapshot"]["notes"][-1])
        for specification in ("12×6.4×1.6", "GB/T97.2-2002 M6", "GB/T97.1-1985 M6"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                calculate_hardware_weight({"kind": "PLAIN_WASHER", "material": "碳钢", "specification": specification})

    def test_catalog_washer_standard_and_size_are_checked_together(self):
        result = calculate_hardware_weight({
            "kind": "PLAIN_WASHER", "material": "碳钢", "specification": "M6 / 12×6.4×1.6",
        })
        self.assertEqual(result["unit_material_weight_kg"], "0.00101645")
        self.assertEqual(calculate_hardware_weight(result["calculation_snapshot"]["input"]), result)
        for specification in ("M6 / 12×6×1.6", "M6 / M8", "M6 / GB/T97.2-2002 M6"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                self.washer(specification=specification)

    def test_65mn_rivet_and_washer_use_steel_reference(self):
        rivet = calculate_hardware_weight({
            "kind": "RIVET_GB873_STEEL", "material": "65Mn", "specification": "Φ4-40",
        })
        self.assertEqual(rivet["unit_weight_g"], "3.96")
        self.assertEqual(rivet["unit_material_weight_kg"], "0.00396000")
        self.assertIn("65Mn", rivet["calculation_snapshot"]["notes"][-1])
        washer = calculate_hardware_weight({
            "kind": "PLAIN_WASHER", "material": "65Mn", "specification": "M6",
        })
        self.assertEqual(washer["unit_weight_g"], "1.01644848")
        self.assertEqual(washer["calculation_snapshot"]["parameters"]["density_g_cm3"], "7.85")

    def test_washer_rejects_missing_or_conflicting_dimensions(self):
        for changes in (
            {"thickness_mm": ""}, {"inner_diameter_mm": "12"}, {"inner_diameter_mm": "13"},
            {"specification": "GB/T97.1-2002 M6", "inner_diameter_mm": "6"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.washer(**changes)

    def test_unknown_washer_material_requires_explicit_density(self):
        for material in ("不锈钢", "铝合金", "铜", "未知"):
            with self.subTest(material=material), self.assertRaises(ValidationError):
                self.washer(material=material)
        result = self.washer(material="不锈钢", density_g_cm3="7.9")
        self.assertEqual(result["calculation_snapshot"]["density_source"], "EXPLICIT")

    def test_specific_materials_use_documented_density(self):
        for material, density in (("铝", "2.7"), ("SUS304", "7.93"), ("304不锈钢", "7.93")):
            with self.subTest(material=material):
                snapshot = self.washer(material=material)["calculation_snapshot"]
                self.assertEqual(snapshot["parameters"]["density_g_cm3"], density)
                self.assertEqual(snapshot["density_source"], "MATERIAL_REFERENCE")
                self.assertTrue(snapshot["density_reference_url"])

    def test_explicit_density_override_is_visible_and_replayable(self):
        result = self.washer(density_g_cm3="2.70")
        snapshot = result["calculation_snapshot"]
        self.assertEqual(snapshot["input"]["density_g_cm3"], "2.7")
        self.assertEqual(snapshot["reference_density_g_cm3"], "7.85")
        self.assertIn("未采用材质参考密度 7.85", snapshot["notes"][1])
        self.assertEqual(calculate_hardware_weight(snapshot["input"]), result)

    def test_external_numeric_inputs_reject_nonfinite_negative_overflow_and_float(self):
        for value in (True, 1.5, "0", "-1", "NaN", "Infinity", "1e1000000", "1000000", "1.0000001", [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.washer(thickness_mm=value)
        with self.assertRaises(ValidationError):
            self.washer(density_g_cm3="1000")

    def test_unrepresentably_small_weight_errors_instead_of_returning_zero(self):
        with self.assertRaises(ValidationError) as error:
            self.washer(outer_diameter_mm="0.002", inner_diameter_mm="0.001", thickness_mm="0.001")
        self.assertIn("unit_material_weight_kg", error.exception.detail)

    def test_snapshot_replays_and_input_is_not_mutated(self):
        data = {"kind": "RIVET_GB873_STEEL", "material": "碳钢", "specification": " 5×30 "}
        before = copy.deepcopy(data)
        result = calculate_hardware_weight(data)
        self.assertEqual(data, before)
        self.assertEqual(calculate_hardware_weight(result["calculation_snapshot"]["input"]), result)
        json.dumps(result, ensure_ascii=False)

    def test_caller_decimal_precision_does_not_change_calculation(self):
        expected = self.washer()
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(self.washer(), expected)
            self.assertEqual(context.prec, 6)

    def test_invalid_payload_kind_and_text_return_validation_errors(self):
        for data in (None, [], {"kind": "UNKNOWN", "material": "碳钢"}, {"kind": True, "material": "碳钢"}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                calculate_hardware_weight(data)
        with self.assertRaises(ValidationError):
            self.rivet(specification="5" * 256)
