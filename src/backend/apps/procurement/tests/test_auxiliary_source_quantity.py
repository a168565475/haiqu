from decimal import Decimal

from django.test import SimpleTestCase

from apps.boms.models import Bom, BomLine, BomSection, BomSectionType
from apps.procurement.services import _source_quantity


class AuxiliarySourceQuantityTests(SimpleTestCase):
    def quantity(self, *, title="辅料类", **values):
        bom = Bom(order_quantity=Decimal("5000"))
        section = BomSection(section_type=BomSectionType.FABRIC, title=title)
        line = BomLine(section=section, **values)
        return _source_quantity(line, bom)

    def test_auxiliary_uses_saved_unit_consumption_and_keeps_unit(self):
        for consumption, unit, expected in [("1", "米", "5000"), ("2", "个", "10000"), ("0.00006", "PCS", "0.3")]:
            with self.subTest(consumption=consumption, unit=unit):
                value, field, text, actual_unit, status = self.quantity(
                    unit_consumption=consumption, purchase_consumption="9", unit=unit,
                )
                self.assertEqual(value, Decimal(expected))
                self.assertEqual(field, "unit_consumption*order_quantity")
                self.assertEqual(text, f"{consumption} × 5000")
                self.assertEqual(actual_unit, unit)
                self.assertEqual(status, "READY")

    def test_existing_totals_take_priority(self):
        for totals, expected, field in [
            ({"total_purchase_quantity": "7", "total_consumption": "8"}, "7", "total_purchase_quantity"),
            ({"total_consumption": "8"}, "8", "total_consumption"),
        ]:
            with self.subTest(totals=totals):
                value, actual_field, _, _, status = self.quantity(unit_consumption="2", **totals)
                self.assertEqual(value, Decimal(expected))
                self.assertEqual(actual_field, field)
                self.assertEqual(status, "READY")

    def test_invalid_values_are_not_hidden_by_fallback(self):
        for values in [
            {"unit_consumption": "abc", "purchase_consumption": "1"},
            {"unit_consumption": "-1", "purchase_consumption": "1"},
            {"unit_consumption": "2", "total_purchase_quantity": "abc"},
        ]:
            with self.subTest(values=values):
                value, _, _, _, status = self.quantity(**values)
                self.assertIsNone(value)
                self.assertEqual(status, "INVALID")
        self.assertEqual(self.quantity()[-1], "MISSING")

    def test_legacy_consumption_and_other_sections_keep_existing_rules(self):
        for title, unit_consumption in [("辅料类", ""), ("面料类", "2"), ("包材类", "2"), ("裁剪明细", "2")]:
            with self.subTest(title=title):
                value, field, _, _, status = self.quantity(
                    title=title, unit_consumption=unit_consumption, purchase_consumption="3",
                )
                self.assertEqual(value, Decimal("15000"))
                self.assertEqual(field, "purchase_consumption*order_quantity")
                self.assertEqual(status, "READY")
