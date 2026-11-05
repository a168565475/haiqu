from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.api.serializers import BomLineWriteSerializer
from apps.boms.material_flow_calculations import MaterialFlowValueError, packaging_quantity
from apps.procurement.models import PurchaseQuantityParseStatus
from apps.procurement.services import _source_quantity


class PackagingQuantityTests(SimpleTestCase):
    def test_packaging_usage_applies_to_boxes_and_other_packaging(self):
        self.assertEqual(packaging_quantity(units_per_box="2", order_quantity="101"), 51)
        self.assertEqual(packaging_quantity(units_per_box="1", order_quantity="101"), 101)

    def test_packaging_usage_validation_keeps_positive_integer_requirement(self):
        serializer = BomLineWriteSerializer()
        self.assertEqual(serializer.validate_units_per_box("2"), "2")
        self.assertEqual(serializer.validate_units_per_box(""), "")
        for value in ("abc", "0", "-1", "1.5", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaisesMessage(ValidationError, "用量（多少成品用一份）必须是正整数。"):
                serializer.validate_units_per_box(value)

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
