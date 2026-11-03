from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.boms.material_flow_calculations import MaterialFlowValueError, packaging_quantity
from apps.procurement.models import PurchaseQuantityParseStatus
from apps.procurement.services import _source_quantity


class PackagingQuantityTests(SimpleTestCase):
    def test_whole_partial_and_zero_boxes(self):
        for order, expected in (("20", 2), ("21", 3), ("0", 0), ("20.0001", 3)):
            with self.subTest(order=order):
                self.assertEqual(packaging_quantity(units_per_box="10", order_quantity=order), expected)

    def test_invalid_box_quantity_is_rejected(self):
        for value in ("", "0", "-1", "1.5", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(MaterialFlowValueError):
                packaging_quantity(units_per_box=value, order_quantity="25")

    def test_purchase_and_issue_source_ignore_old_budget_total_and_consumption(self):
        line = SimpleNamespace(section=SimpleNamespace(section_type="ACCESSORY", title="包材类"),
                               raw_values={"units_per_box": "10"}, unit="个", budget_quantity="999",
                               total_consumption="999", unit_consumption="999")
        self.assertEqual(_source_quantity(line, SimpleNamespace(order_quantity=Decimal("25"))),
                         (Decimal("3"), "units_per_box", "10", "个", PurchaseQuantityParseStatus.READY))
        for value, status in (("", PurchaseQuantityParseStatus.MISSING), ("0", PurchaseQuantityParseStatus.INVALID)):
            line.raw_values["units_per_box"] = value
            self.assertEqual(_source_quantity(line, SimpleNamespace(order_quantity=Decimal("25")))[4], status)
