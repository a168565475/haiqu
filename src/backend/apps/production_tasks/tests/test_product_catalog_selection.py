from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.production_tasks.services import (
    _prepare_catalog_products, _product_identity_changed, _product_line_snapshot_values,
)
from apps.boms.api.serializers import BomProductConfirmationSerializer
from apps.production_scheduling.services import product_source_snapshot


class ProductCatalogSelectionTests(SimpleTestCase):
    def snapshot(self):
        return {
            "name": "折叠椅", "product_code": "NEW-1", "item_number": "A1",
            "specification": "50*60", "material": "铁", "color_name": "蓝色",
            "unit_id": str(uuid4()), "thickness": "0.8",
        }

    def test_new_product_uses_selection_snapshot_without_old_master(self):
        snapshot = self.snapshot()
        catalog = SimpleNamespace(pk=uuid4())
        values = _product_line_snapshot_values(product=None, color=None, data={
            "product_catalog": catalog, "product_selection_snapshot": snapshot,
        })
        self.assertIs(values["product_catalog"], catalog)
        self.assertIsNone(values["product"])
        self.assertEqual(values["product_code_snapshot"], "NEW-1")
        self.assertEqual(values["color_name_snapshot"], "蓝色")
        self.assertEqual(values["product_selection_snapshot"], snapshot)

    def test_unchanged_selection_passes_original_snapshot_to_resolver(self):
        snapshot = self.snapshot()
        catalog = SimpleNamespace(pk=uuid4())
        line = SimpleNamespace(pk=uuid4(), product_catalog_id=catalog.pk, product_selection_snapshot=snapshot)
        task = SimpleNamespace(products=SimpleNamespace(all=lambda: [line]))
        data = {"client_key": str(line.pk), "product_catalog_id": catalog.pk,
                "unit": SimpleNamespace(pk=snapshot["unit_id"])}
        with patch("apps.product_catalog.selection.resolve_product_selection", return_value=(catalog, snapshot)) as resolve:
            _prepare_catalog_products([data], task)
        resolve.assert_called_once_with(catalog.pk, None, existing_catalog_id=catalog.pk, existing_snapshot=snapshot)
        self.assertEqual(data["product_selection_snapshot"], snapshot)

    def test_catalog_unit_cannot_be_replaced(self):
        catalog = SimpleNamespace(pk=uuid4())
        with patch("apps.product_catalog.selection.resolve_product_selection", return_value=(catalog, self.snapshot())):
            with self.assertRaises(ValidationError):
                _prepare_catalog_products([{"client_key": "one", "product_catalog_id": catalog.pk,
                                            "unit": SimpleNamespace(pk=uuid4())}])

    def test_different_selected_attributes_are_different_product_identity(self):
        snapshot = self.snapshot()
        catalog = SimpleNamespace(pk=uuid4())
        line = SimpleNamespace(product_id=None, product_catalog_id=catalog.pk, product_selection_snapshot=snapshot)
        self.assertTrue(_product_identity_changed(line, {"product_catalog": catalog,
            "product_selection_snapshot": {**snapshot, "thickness": "1.0"}}))

    def test_bom_confirmation_accepts_new_catalog_without_legacy_color(self):
        serializer = BomProductConfirmationSerializer(data={"product_catalog_id": str(uuid4())})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_scheduling_snapshot_preserves_catalog_identity(self):
        fields = {key: "" for key in ("product_number_snapshot", "product_code_snapshot", "item_number_snapshot",
            "product_name_snapshot", "specification_snapshot", "color_card_snapshot", "color_name_snapshot",
            "color_code_snapshot", "special_requirements", "packaging_method")}
        line = SimpleNamespace(**fields, product_id=None, product_color_id=None,
            product_catalog_id=uuid4(), product_selection_snapshot=self.snapshot())
        snapshot = product_source_snapshot(line)
        self.assertIsNone(snapshot["product_id"])
        self.assertEqual(snapshot["product_catalog_id"], str(line.product_catalog_id))
        self.assertEqual(snapshot["product_selection_snapshot"], line.product_selection_snapshot)
