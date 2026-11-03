from decimal import Decimal
from django.test import TestCase, override_settings

from apps.material_catalog.models import MaterialCatalog
from ..catalog_stock_identity import build_catalog_stock_identity
from ..public_stock_identity import build_semi_finished_identity
from .test_public_stock_services import PublicStockFixture


class CatalogInventoryVisibilityTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="新材料可见性管材")
        self.saved = {"schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name, "scope": "BASE", "processing_state": "RAW",
            "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"},
            "unit_id": str(self.root_unit.pk), "unit_name": "根", "display_name": "新材料可见性管材"}

    def assert_visible(self, balance, kind, unit, quantity):
        for enabled in (False, True):
            with self.subTest(public_mode=enabled), override_settings(PUBLIC_STOCK_FLOW_ENABLED=enabled):
                response = self.client.get("/api/v1/material-inventory/", {"stock_kind": kind, "q": "新材料可见性管材"})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["count"], 1)
                row = response.data["results"][0]
                self.assertEqual(str(row["stock_item_id"]), str(self.catalog.pk))
                self.assertEqual(row["unit"], unit)
                self.assertEqual(row["inventory_quantity"], quantity)
                summary = self.client.get(f"/api/v1/material-inventory/{self.catalog.pk}/summary/", {"identity_key": balance.identity_key})
                self.assertEqual(summary.status_code, 200, summary.data)
                self.assertEqual(Decimal(summary.data["data"]["current_quantity"]), quantity)
                self.assertEqual(summary.data["data"]["unit"], unit)

    def test_raw_is_visible_without_switching_legacy_stock_mode(self):
        identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk, material_selection_snapshot=self.saved,
            raw_bar_length_m="6.00")
        balance = self.credit(3, identity=identity).balance
        self.assert_visible(balance, "RAW", "根", balance.quantity)

    def test_semi_list_summary_and_warehouse_filters_include_catalog_when_legacy(self):
        self.bom_line.material_catalog = self.catalog
        self.bom_line.material_selection_snapshot = self.saved
        identity = build_semi_finished_identity(bom_line=self.bom_line, completed_craft=self.craft, unit=self.piece_unit)
        balance = self.credit(4, identity=identity, zone=self.semi_zone).balance
        self.assert_visible(balance, "SEMI", "支", balance.quantity)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            options = self.client.get("/api/v1/material-inventory/options/", {"scope": "filters"})
            self.assertEqual(options.status_code, 200, options.data)
            self.assertIn(self.semi_zone.warehouse_id, [row["id"] for row in options.data["data"]["warehouses"]])
            receiving = self.client.get("/api/v1/material-inventory/options/", {"scope": "receiving"})
            self.assertTrue(all(row["warehouse_type"] == "MATERIAL" for row in receiving.data["data"]["warehouses"]))
            receiving = self.client.get("/api/v1/material-inventory/options/", {"scope": "receiving", "include_catalog_semi": "true"})
            self.assertIn(self.semi_zone.warehouse_id, [row["id"] for row in receiving.data["data"]["warehouses"]])
