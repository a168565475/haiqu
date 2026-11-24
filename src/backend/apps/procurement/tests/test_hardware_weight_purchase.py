from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.models import BomSectionType
from apps.procurement.services import (
    _hardware_weight_data,
    _source_quantity,
    _validate_hardware_actual_weight,
    is_hardware_weight_snapshot,
    _money,
)
from apps.procurement.catalog_materials import priced_quantity


class HardwareWeightPurchaseTests(SimpleTestCase):
    def _line(self, **raw_values):
        return SimpleNamespace(
            section=SimpleNamespace(section_type=BomSectionType.ACCESSORY, title="五金件"),
            part_name="铆钉",
            raw_values={
                "hardware_weight_mode": "AUTO",
                "unit_material_weight_kg": "0.00396000",
                **raw_values,
            },
            budget_quantity="12",
            total_consumption="",
            unit_consumption="",
            unit="个",
            material_catalog_id=None,
        )

    def test_hardware_source_quantity_uses_kg_and_preserves_piece_basis(self):
        value, field, text, unit, status = _source_quantity(self._line(), SimpleNamespace(order_quantity=Decimal("1")))

        self.assertEqual(value, Decimal("0.0475"))
        self.assertEqual(field, "hardware_weight_kg")
        self.assertEqual(unit, "KG")
        self.assertIn("12 个", text)
        self.assertEqual(status, "READY")

    def test_hardware_weight_data_marks_missing_unit_weight(self):
        data = _hardware_weight_data(
            self._line(unit_material_weight_kg=""), SimpleNamespace(order_quantity=Decimal("1"))
        )

        self.assertIsNotNone(data)
        self.assertIsNone(data["total_weight_kg"] if "total_weight_kg" in data else None)
        self.assertEqual(data["unit_status"], "MISSING")

    def test_configured_piece_units_all_produce_kg_purchase_quantities(self):
        for unit in ("个", "片", "件", "只", "颗", "粒", "枚", "支", "PCS", "PC", "PIECE", "PIECES", "pcs"):
            with self.subTest(unit=unit):
                line = self._line()
                line.unit = unit
                result = _source_quantity(line, SimpleNamespace(order_quantity=1))
                self.assertEqual((result[0], result[3], result[4]), (Decimal("0.0475"), "KG", "READY"))
                self.assertIn(f"12 {unit}", result[2])

    def test_kg_source_keeps_weight_instead_of_multiplying_again(self):
        for unit in ("KG", "kg", "公斤", "千克"):
            with self.subTest(unit=unit):
                line = self._line()
                line.unit = unit
                result = _source_quantity(line, SimpleNamespace(order_quantity=Decimal("1")))
                self.assertEqual(result[0], Decimal("12.0000"))
                self.assertEqual(result[3:], ("KG", "READY"))
                self.assertNotIn("个", result[2])
                self.assertIsNone(_hardware_weight_data(line, SimpleNamespace(order_quantity=1))["piece_quantity"])

    def test_washer_piece_source_preserves_piece_unit(self):
        line = self._line(unit_material_weight_kg="0.00101645")
        line.part_name = "垫片"
        line.unit = "片"
        result = _source_quantity(line, SimpleNamespace(order_quantity=1))
        self.assertEqual(result[0], Decimal("0.0122"))
        self.assertIn("12 片", result[2])
        self.assertIn("kg/片", result[2])

    def test_unknown_quantity_units_do_not_produce_a_purchase_weight(self):
        for unit in ("包", "千件", "箱", ""):
            with self.subTest(unit=unit):
                line = self._line()
                line.unit = unit
                result = _source_quantity(line, SimpleNamespace(order_quantity=1))
                self.assertIsNone(result[0])
                self.assertEqual(result[4], "INVALID")

    def test_zero_piece_weight_is_invalid_not_ready(self):
        result = _source_quantity(self._line(unit_material_weight_kg="0"), SimpleNamespace(order_quantity=1))
        self.assertIsNone(result[0])
        self.assertEqual(result[4], "INVALID")

    def test_actual_weight_edit_is_checked_against_quantity(self):
        snapshot = {"measurement_kind": "HARDWARE_WEIGHT"}
        with self.assertRaises(ValidationError):
            _validate_hardware_actual_weight(snapshot, {"actual_purchase_weight_kg": Decimal("0.0500")}, Decimal("0.0475"))
        _validate_hardware_actual_weight(snapshot, {"actual_purchase_weight_kg": Decimal("0.0475")}, Decimal("0.0475"))
        self.assertTrue(is_hardware_weight_snapshot(snapshot))

    def test_hardware_purchase_amount_uses_actual_kg(self):
        quantity = priced_quantity(
            section_type="ACCESSORY", material_catalog_id=None,
            physical_quantity=Decimal("0.0500"),
            pipe_values={"calculation_snapshot": {"measurement_kind": "HARDWARE_WEIGHT"}},
        )
        self.assertEqual(quantity, Decimal("0.0500"))
        self.assertEqual(_money(quantity * Decimal("8.5000")), Decimal("0.4250"))
