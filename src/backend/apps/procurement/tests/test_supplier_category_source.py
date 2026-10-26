from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.procurement.models import SupplierCategory
from apps.procurement.sample_purchase_services import sample_source


class SampleSupplierCategorySourceTests(SimpleTestCase):
    category_cases = (
        ("tube", "PROFILE", "管材类", "TUBE"),
        ("hardware", "HARDWARE", "五金件", "HARDWARE"),
        ("plastic", "PLASTIC", "塑料件", "PLASTIC_PART"),
        ("accessory", "ACCESSORY", "辅料", "AUXILIARY"),
        ("fabric", "FABRIC", "面料类", "FABRIC"),
        ("packaging", "PACKAGING", "包装", "PACKAGING"),
    )

    def source(self, existing_order=None):
        items = Mock()
        items.all.return_value = []
        items.count.return_value = 0
        sample = SimpleNamespace(
            pk="sample-category-test", request_number="DY-CATEGORY",
            customer_account=SimpleNamespace(account_name="测试客户"),
            sample_due_date=date(2026, 10, 26), status="PROCUREMENT_PENDING",
            updated_at=datetime(2026, 10, 26, tzinfo=timezone.utc), items=items,
        )
        bindings = Mock()
        bindings.select_related.return_value.first.return_value = None
        procurement = SimpleNamespace(
            pk="procurement-category-test", notes="",
            material_request=SimpleNamespace(sample_request=sample),
            purchase_sources=bindings,
            lines=[
                {
                    "key": category, "category": category, "name": title,
                    "specification": "测试规格", "material": "测试材质",
                    "quantity": "5", "supplyQuantity": "2", "shortageQuantity": "3",
                    "unitLabel": "个",
                }
                for category, _, title, _ in self.category_cases
            ],
        )
        with (
            patch("apps.procurement.sample_purchase_services.PurchaseOrder.objects.filter") as orders,
            patch("apps.samples.product_attributes.sample_purchase_products", return_value=[]),
            patch("apps.samples.pipe_materials.sample_pipe_snapshot", return_value={
                "schema_version": 3, "shortage_meters": "3",
            }),
            patch("apps.samples.material_identity.sample_material_snapshot", return_value={}),
        ):
            orders.return_value.first.return_value = existing_order
            return sample_source(procurement)

    def assert_category_contract(self, lines):
        self.assertEqual(len(lines), len(self.category_cases))
        for line, (category, section, title, supplier_category) in zip(lines, self.category_cases):
            with self.subTest(category=category):
                self.assertEqual(line["sample_line_key"], category)
                self.assertEqual(line["section_type"], section)
                self.assertEqual(line["section_title"], title)
                self.assertEqual(line["category"], title)
                self.assertEqual(line["suggested_supplier_category"], supplier_category)
                self.assertIn(line["suggested_supplier_category"], SupplierCategory.values)
                self.assertEqual(line["category_source"], "SECTION")

    def test_six_sample_categories_match_supplier_options(self):
        source = self.source()
        self.assertTrue(source["can_create"])
        self.assertEqual(source["preview_lines"], [])
        self.assert_category_contract(source["lines"])

    def test_existing_purchase_preview_keeps_supplier_categories(self):
        source = self.source(SimpleNamespace(pk="existing-order", order_number="CG-CATEGORY"))
        self.assertFalse(source["can_create"])
        self.assertEqual(source["lines"], [])
        self.assertEqual(source["blockers"][0]["code"], "PURCHASE_ORDER_EXISTS")
        self.assert_category_contract(source["preview_lines"])
