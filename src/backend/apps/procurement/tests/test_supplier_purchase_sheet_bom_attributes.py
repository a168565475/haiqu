from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from ..purchase_sheet_services import _default_content, normalize_sheet_content
from ..purchase_sheet_xlsx import _line_values


class SupplierPurchaseSheetBomAttributeTests(SimpleTestCase):
    def setUp(self):
        self.attributes = {
            "schema_version": 1,
            "section_type": "HARDWARE",
            "section_title": "五金件",
            "fields": [
                {"key": "part_name", "label": "品名", "value": "连接件"},
                {"key": "material", "label": "材质", "value": "钢"},
                {"key": "specification", "label": "规格", "value": "M8"},
                {"key": "tube_coating_color", "label": "喷塑颜色", "value": "黑色"},
            ],
        }
        self.line = SimpleNamespace(
            pk="line-1",
            section_type_snapshot="HARDWARE",
            section_title_snapshot="五金件",
            product_name_snapshot="成品",
            product_specification_snapshot="成品规格",
            part_name_snapshot="连接件",
            specification_snapshot="M8",
            material_snapshot="钢",
            raw_material_snapshot="钢材",
            material_attributes_snapshot=deepcopy(self.attributes),
            actual_purchase_quantity=Decimal("2"),
            source_unit_text="PCS",
            unit_price=Decimal("3.5"),
            amount=Decimal("7"),
            delivery_date=date(2026, 10, 20),
            color_snapshot="",
            raw_bar_length_m=None,
        )
        self.order = SimpleNamespace(
            source_type="PRODUCTION",
            sales_order_number_snapshot="SO-1",
            production_task_number_snapshot="PT-1",
            sales_order_number="SO-1",
            sample_number_snapshot="",
        )
        self.supplier = SimpleNamespace(supplier_name="供应商", phone="")
        self.template_version = SimpleNamespace(content_config={})

    def test_default_content_copies_order_bom_partition_and_attributes(self):
        content = _default_content(self.order, self.supplier, [self.line], self.template_version, "CGDD2026101201")

        row = content["lines"][0]
        self.assertEqual(row["section_type"], "HARDWARE")
        self.assertEqual(row["section_title"], "五金件")
        self.assertEqual(row["material_attributes_snapshot"], self.attributes)

    def test_update_keeps_order_source_attributes_when_submitted_content_changes(self):
        current = _default_content(self.order, self.supplier, [self.line], self.template_version, "CGDD2026101201")
        sheet = SimpleNamespace(content_snapshot=current, sheet_number="CGDD2026101201")
        submitted = deepcopy(current)
        submitted["lines"][0]["section_title"] = "被修改分区"
        submitted["lines"][0]["material_attributes_snapshot"] = {
            "fields": [{"label": "规格", "value": "被修改规格"}],
        }

        normalized, _ = normalize_sheet_content(sheet, submitted)

        row = normalized["lines"][0]
        self.assertEqual(row["section_title"], "五金件")
        self.assertEqual(row["material_attributes_snapshot"], self.attributes)

    def test_xlsx_line_contains_partition_and_attributes_but_not_powder_color(self):
        values = _line_values(
            "DEFAULT",
            {
                "part_name": "连接件",
                "specification": "M8",
                "section_title": "五金件",
                "material_attributes_snapshot": self.attributes,
                "material": "钢",
            },
            1,
            "SO-1",
            False,
        )

        self.assertIn("BOM分区：五金件", values[2])
        self.assertIn("规格：M8", values[2])
        self.assertNotIn("喷塑颜色", values[2])
        self.assertNotIn("黑色", values[2])
