from copy import deepcopy
from decimal import Decimal

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from ..models import PurchaseGroup
from ..multi_bom_sources import merge_purchase_snapshots, purchase_merge_key
from .test_multi_product_purchase import MultiProductPurchaseFixture


class SavedPurchaseIdentityTests(MultiProductPurchaseFixture, APITestCase):
    def test_catalog_material_with_missing_legacy_display_fields_still_orders_once(self):
        payload = self.payload()
        old = self.client.post("/api/v1/purchase-groups/", {
            "production_task_id": payload["production_task_id"], **payload["sources"][0],
        }, format="json")
        self.assertEqual(old.status_code, 201, old.data)
        line = PurchaseGroup.objects.get(pk=old.data["data"]["id"]).lines.get()
        for old_value in (None, {}, {"fields": []}):
            with self.subTest(attributes=old_value):
                saved = {**line.source_snapshot, "material_attributes_snapshot": old_value}
                self.assertEqual(purchase_merge_key(saved), purchase_merge_key(line.source_snapshot))
        line.source_snapshot.pop("material_attributes_snapshot")
        line.save(update_fields=["source_snapshot"])
        merged = self.client.post("/api/v1/purchase-groups/", payload, format="json")
        self.assertEqual(merged.status_code, 201, merged.data)
        self.group_id = merged.data["data"]["id"]
        row, = merged.data["data"]["progress"]["lines"]
        self.line_id = row["id"]
        self.assertEqual(Decimal(row["required_quantity"]), 2000)
        self.assertEqual(len(self.batch("700")["lines"]), 1)


class PipePurchaseMergeTests(SimpleTestCase):
    def test_string_root_counts_and_decimal_lengths_preserve_weight_and_original_cutting_plans(self):
        snapshot = {"material_selection_snapshot": {}, "section_type_snapshot": "PROFILE", "section_title_snapshot": "管材类",
                    "source_unit_text": "KG", "material_attributes_snapshot": {"fields": []}, "raw_bar_length_m": "2.25",
                    "raw_bar_weight_kg": Decimal("1.5"), "calculation_snapshot": {"raw_material_id": "frozen-pipe",
                    "raw_bar_length_m": "2.250", "raw_bar_weight_kg": "1.5000", "cutting_length_mm": 200,
                    "suggested_bar_count": "2", "suggested_purchase_meters": "4.500", "suggested_purchase_weight_kg": "3.0000"},
                    "required_quantity": "3.0", "bom_id": "a", "bom_line_id": "a1", "component_identity": "part",
                    "product_line_id_snapshot": "a", "product_color": "红", "product_name_snapshot": "折叠床",
                    "product_specification_snapshot": "款一"}
        other = deepcopy(snapshot)
        other.update(bom_id="b", bom_line_id="b1", required_quantity="4.50")
        other["calculation_snapshot"].update(cutting_length_mm=300, suggested_bar_count=3,
                                            suggested_purchase_meters="6.75", suggested_purchase_weight_kg="4.5")
        self.assertEqual(purchase_merge_key(snapshot), purchase_merge_key(other))
        merged = merge_purchase_snapshots([snapshot, other])
        self.assertEqual((merged["suggested_bar_count"], merged["suggested_purchase_meters"], merged["suggested_purchase_weight_kg"]),
                         (5, "11.25", "7.5000"))
        self.assertNotIn("cutting_length_mm", merged["calculation_snapshot"])
        for field in ("raw_bar_length_m", "raw_bar_weight_kg"):
            different = deepcopy(snapshot)
            different[field] = different["calculation_snapshot"][field] = "9.0"
            self.assertNotEqual(purchase_merge_key(different), purchase_merge_key(snapshot))
        with self.assertRaises(ValidationError):
            purchase_merge_key({**snapshot, "raw_bar_weight_kg": "2.0"})
        with self.assertRaisesMessage(ValidationError, "床头管"):
            purchase_merge_key({**snapshot, "part_name_snapshot": "床头管", "calculation_snapshot": {}})
