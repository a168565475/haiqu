from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.procurement.purchase_sheet_services import _default_content, normalize_sheet_content
from apps.procurement.purchase_sheet_line_display import purchase_sheet_line_display


class HardwareWeightSheetTests(SimpleTestCase):
    def setUp(self):
        self.line = SimpleNamespace(
            pk="line-1", section_type_snapshot="ACCESSORY", section_title_snapshot="五金件",
            product_name_snapshot="成品", product_specification_snapshot="成品规格",
            part_name_snapshot="铆钉", specification_snapshot="Φ4×40", material_snapshot="65Mn",
            material_attributes_snapshot={}, material_catalog_id=None, raw_bar_length_m=None,
            actual_purchase_quantity=Decimal("0.0500"), source_unit_text="KG",
            unit_price=Decimal("8.5000"), amount=Decimal("0.4250"), delivery_date=date(2026, 11, 20),
            calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT", "hardware_unit_weight_kg": "0.00396000"},
        )
        order = SimpleNamespace(source_type="PRODUCTION", sales_order_number_snapshot="SO-1", production_task_number_snapshot="PT-1")
        self.content = _default_content(order, SimpleNamespace(supplier_name="五金供应商", phone=""), [self.line], SimpleNamespace(content_config={}), "SHEET-1")
        self.sheet = SimpleNamespace(content_snapshot=self.content, sheet_number="SHEET-1")

    def test_generation_carries_hardware_weight_snapshot(self):
        row = self.content["lines"][0]
        self.assertEqual(row.get("measurement_kind"), "HARDWARE_WEIGHT")
        self.assertEqual(row.get("calculation_snapshot"), self.line.calculation_snapshot)
        self.assertEqual(row.get("price_unit"), "元/kg")
        self.assertEqual(row["unit"], "KG")

    def test_quantity_unit_and_price_cannot_be_changed_in_draft_or_publish(self):
        for publish in (False, True):
            for field, value in (("quantity", "100"), ("unit", "个"), ("unit_price", "2")):
                with self.subTest(publish=publish, field=field):
                    submitted = deepcopy(self.content)
                    submitted["lines"][0][field] = value
                    with self.assertRaises(ValidationError):
                        normalize_sheet_content(self.sheet, submitted, for_publish=publish)

    def test_washer_and_rivet_snapshots_survive_marker_tampering(self):
        for name in ("铆钉", "垫片"):
            with self.subTest(name=name):
                submitted = deepcopy(self.content)
                submitted["lines"][0].update(part_name=name, measurement_kind="OTHER", calculation_snapshot={})
                row = normalize_sheet_content(self.sheet, submitted)[0]["lines"][0]
                self.assertEqual(row["measurement_kind"], "HARDWARE_WEIGHT")
                self.assertEqual(row["calculation_snapshot"], self.line.calculation_snapshot)

    def test_equal_numeric_formats_are_allowed_and_amount_is_recomputed(self):
        submitted = deepcopy(self.content)
        submitted["lines"][0].update(quantity="0.05", unit_price="8.5", amount="1000")
        normalized, total = normalize_sheet_content(self.sheet, submitted, for_publish=True)
        self.assertEqual(total, Decimal("0.4250"))
        self.assertEqual(normalized["lines"][0]["amount"], "0.4250")

    def test_hardware_weight_does_not_allow_amount_to_disappear(self):
        submitted = deepcopy(self.content)
        submitted["settlement_mode"] = "ACTUAL_WEIGHT"
        with self.assertRaises(ValidationError):
            normalize_sheet_content(self.sheet, submitted)

    def test_legacy_missing_marker_is_recovered_from_order_not_trusted(self):
        self.sheet.purchase_order_id = "order-1"
        self.sheet.supplier_id = "supplier-1"
        for field in ("measurement_kind", "calculation_snapshot", "price_unit"):
            self.content["lines"][0].pop(field, None)
        submitted = deepcopy(self.content)
        submitted["lines"][0].update(quantity="100", unit="个", unit_price="2")
        with patch("apps.procurement.models.PurchaseOrderLine.objects.filter", return_value=[self.line]):
            with self.assertRaises(ValidationError):
                normalize_sheet_content(self.sheet, submitted, for_publish=True)

    def test_changed_order_weight_is_detected(self):
        self.sheet.purchase_order_id = "order-1"
        self.sheet.supplier_id = "supplier-1"
        self.line.actual_purchase_quantity = Decimal("0.0600")
        with patch("apps.procurement.models.PurchaseOrderLine.objects.filter", return_value=[self.line]):
            with self.assertRaises(ValidationError):
                normalize_sheet_content(self.sheet, deepcopy(self.content), for_publish=True)

    def test_removed_hardware_order_row_is_detected(self):
        self.sheet.purchase_order_id = "order-1"
        self.sheet.supplier_id = "supplier-1"
        self.line.pk = "another-line"
        with patch("apps.procurement.models.PurchaseOrderLine.objects.filter", return_value=[self.line]):
            with self.assertRaises(ValidationError):
                normalize_sheet_content(self.sheet, deepcopy(self.content), for_publish=True)

    def test_printed_purchase_sheet_keeps_only_kg_quantity(self):
        row = self.content["lines"][0]
        row["calculation_snapshot"]["hardware_quantity_unit"] = "片"
        self.assertNotIn("参考", purchase_sheet_line_display(row)["attributes"])
        self.assertEqual(row["quantity"], "0.0500")
        self.assertEqual(row["amount"], "0.4250")
        row["quantity"] = "0.0079"
        self.assertNotIn("参考", purchase_sheet_line_display(row)["attributes"])
        row["quantity"] = "0.0039"
        self.assertNotIn("参考", purchase_sheet_line_display(row)["attributes"])
        row["calculation_snapshot"]["hardware_quantity_unit"] = "KG"
        self.assertNotIn("参考", purchase_sheet_line_display(row)["attributes"])

    def test_printed_sheet_does_not_add_stock_reference_units(self):
        row = self.content["lines"][0]
        for unit in ("个", "片", "件", "只", "颗", "粒", "枚", "支", "PCS", "PC", "PIECE", "PIECES", "pcs"):
            with self.subTest(unit=unit):
                row["calculation_snapshot"]["hardware_quantity_unit"] = unit
                self.assertNotIn("参考", purchase_sheet_line_display(row)["attributes"])
                self.assertEqual((row["quantity"], row["amount"]), ("0.0500", "0.4250"))
