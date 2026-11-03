from copy import deepcopy

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError


FORMULAS = {
    "ROUND": {
        "group_key": "ROUND",
        "area_expression": "直径*3.14*管材长度/1000000",
        "weight_expression": "(直径-壁厚)*壁厚*3.14*7.854*管材长度/1000000",
        "updated_at": "2026-10-29T00:00:00Z",
    },
    "RECTANGULAR": {
        "group_key": "RECTANGULAR",
        "area_expression": "(截面长+截面宽)*2*管材长度/1000000",
        "weight_expression": "((截面长+截面宽)*2/3.14-壁厚)*壁厚*3.14*7.854*管材长度/1000000",
        "updated_at": "2026-10-29T00:00:00Z",
    },
    "OVAL": {
        "group_key": "OVAL",
        "area_expression": "截面长/2*截面宽/2*3.14*管材长度/1000000",
        "weight_expression": "(截面长*截面宽-(截面长-2*壁厚)*(截面宽-2*壁厚))/4*3.14*7.854*管材长度/1000000",
        "updated_at": "2026-10-29T00:00:00Z",
    },
}


class TubeFormulaCalculationTests(SimpleTestCase):
    def calculate(self, group="ROUND", **overrides):
        from apps.reference_data.tube_formulas import calculate_tube_metrics

        values = {
            "shape": {"ROUND": "圆管", "RECTANGULAR": "方管", "OVAL": "椭圆管"}[group],
            "specification": "25" if group == "ROUND" else "25×15",
            "thickness": "1.5",
            "length_mm": "1000",
            "formula": deepcopy(FORMULAS[group]),
        }
        values.update(overrides)
        return calculate_tube_metrics(**values)

    def test_six_confirmed_formulas_calculate_one_piece_without_quantity(self):
        # 固定规格的独立手算值，椭圆面积严格保留用户确认的截面积乘管长口径。
        for group, area, weight in (
            ("ROUND", "0.0785", "0.8693"),
            ("RECTANGULAR", "0.0800", "0.8870"),
            ("OVAL", "0.2944", "0.6844"),
        ):
            with self.subTest(group=group):
                result = self.calculate(group)
                self.assertEqual(result["coating_unit_area_sqm"], area)
                self.assertEqual(result["purchase_unit_weight_kg"], weight)
                self.assertEqual(result["formula_snapshot"], FORMULAS[group])

    def test_shape_aliases_share_the_same_formula_group(self):
        for group, names in (
            ("ROUND", ("圆管", "圆")),
            ("RECTANGULAR", ("方管", "矩形管", "方", "矩形")),
            ("OVAL", ("椭圆管", "扁圆管", "椭圆", "扁圆")),
        ):
            expected = self.calculate(group)
            for name in names:
                with self.subTest(shape=name):
                    self.assertEqual(self.calculate(group, shape=name), expected)

    def test_rectangular_specification_supports_separators_and_square_single_dimension(self):
        expected = self.calculate("RECTANGULAR")
        for specification in ("25x15", "25X15", "25*15", " 25 × 15 "):
            self.assertEqual(self.calculate("RECTANGULAR", specification=specification), expected)
        self.assertEqual(
            self.calculate("RECTANGULAR", specification="25"),
            self.calculate("RECTANGULAR", specification="25×25"),
        )

    def test_snapshot_is_used_without_database_and_is_not_mutated(self):
        formula = deepcopy(FORMULAS["ROUND"])
        formula["area_expression"] = "直径*管材长度/1000000"
        original = deepcopy(formula)
        result = self.calculate(formula=formula)
        self.assertEqual(result["coating_unit_area_sqm"], "0.0250")
        self.assertEqual(formula, original)
        self.assertEqual(result["formula_snapshot"], original)

    def test_existing_explicit_millimeter_and_diameter_notation_remains_supported(self):
        expected = self.calculate()
        for specification in ("Φ25", "φ25mm", "Ø25毫米", "ø25 MM"):
            with self.subTest(specification=specification):
                self.assertEqual(self.calculate(specification=specification, thickness="1.5mm", length_mm="1000毫米"), expected)
        self.assertEqual(self.calculate("RECTANGULAR", specification="25 x 15毫米"), self.calculate("RECTANGULAR"))

    def test_decimal_rounding_is_half_up(self):
        formula = {**FORMULAS["ROUND"], "area_expression": "0.00005", "weight_expression": "0.00015"}
        result = self.calculate(formula=formula)
        self.assertEqual(result["coating_unit_area_sqm"], "0.0001")
        self.assertEqual(result["purchase_unit_weight_kg"], "0.0002")

    def test_invalid_dimensions_and_unknown_shapes_are_rejected(self):
        for changes in (
            {"shape": "D形管"}, {"specification": "25×15"}, {"specification": "NaN"},
            {"specification": "0"}, {"specification": "1e3"}, {"thickness": "0"},
            {"thickness": "12.5"}, {"thickness": "-1"}, {"length_mm": "0"},
            {"length_mm": "Infinity"}, {"length_mm": True}, {"length_mm": "1000米"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.calculate(**changes)
        for group in ("RECTANGULAR", "OVAL"):
            with self.subTest(group=group), self.assertRaises(ValidationError):
                self.calculate(group, thickness="7.5")
        with self.assertRaises(ValidationError):
            self.calculate("OVAL", specification="25")

    def test_snapshot_group_must_match_shape(self):
        with self.assertRaises(ValidationError):
            self.calculate(formula=FORMULAS["OVAL"])

    def test_unsafe_or_excessively_complex_expressions_are_rejected(self):
        for expression in (
            "__import__('os')", "直径.real", "直径**2", "直径//2", "直径%2", "[直径]",
            "直径 if 1 else 0", "截面长*管材长度", "数量*直径", "1e1000", "NaN", "1/0",
            "-1", "", "1+" * 60 + "1", "(" * 30 + "1" + ")" * 30, "1" * 501,
        ):
            with self.subTest(expression=expression), self.assertRaises(ValidationError):
                self.calculate(formula={**FORMULAS["ROUND"], "area_expression": expression})

    def test_runtime_zero_denominator_and_negative_result_are_rejected(self):
        for expression in ("1/(直径-25)", "20-直径"):
            with self.subTest(expression=expression), self.assertRaises(ValidationError):
                self.calculate(formula={**FORMULAS["ROUND"], "area_expression": expression})

    def test_formula_group_variable_whitelist_is_validated_before_saving(self):
        from apps.reference_data.tube_formulas import validate_tube_expression

        for group in ("RECTANGULAR", "OVAL"):
            with self.subTest(group=group), self.assertRaises(ValidationError):
                validate_tube_expression("直径*管材长度", group_key=group)
        self.assertEqual(validate_tube_expression(" 直径 * 3.14 ", group_key="ROUND"), "直径 * 3.14")

    def test_chinese_arithmetic_symbols_are_normalized_for_save_and_calculation(self):
        from apps.reference_data.tube_formulas import validate_tube_expression

        expression = "（直径－壁厚）×壁厚×3.14×7.854×管材长度÷1000000"
        # 全角减号不在约定支持范围内，仍须明确拒绝。
        with self.assertRaises(ValidationError):
            validate_tube_expression(expression, group_key="ROUND")
        expression = expression.replace("－", "-")
        self.assertEqual(validate_tube_expression(expression, group_key="ROUND"), FORMULAS["ROUND"]["weight_expression"])
        formula = {**FORMULAS["ROUND"], "weight_expression": expression}
        result = self.calculate(formula=formula)
        self.assertEqual(result["purchase_unit_weight_kg"], "0.8693")
        self.assertEqual(result["formula_snapshot"]["weight_expression"], FORMULAS["ROUND"]["weight_expression"])
        with self.assertRaises(ValidationError):
            validate_tube_expression("（" * 251 + "1", group_key="ROUND")
