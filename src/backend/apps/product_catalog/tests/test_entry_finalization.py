from copy import deepcopy

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory

from apps.reference_data.models import ProductionUnit
from apps.product_catalog.finalization import finalize_product_entry
from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from apps.product_catalog.selection import resolve_product_selection


@override_settings(MODULE_ACCESS_ENABLED=False)
class ProductEntryFinalizationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(username="entry_finalizer", password="test-only")
        self.request = APIRequestFactory().post("/api/v1/boms/test/verify/", {}, format="json")
        self.request.user = user
        self.request.employee = None

    def draft(self, **changes):
        values = {"category_name": "临时新类别", "name": "临时新产品", "item_number": "ENTRY-01",
                  "specification": "60*80", "product_code": "ENTRY-CODE", "unit_name": "临时新单位",
                  "color_name": "酒红色", "material": "铝"}
        values.update(changes)
        values["sources"] = {key: "typed" for key in values}
        return values

    def snapshot(self, draft=None):
        _, snapshot = resolve_product_selection(None, {"draft": draft or self.draft()})
        return snapshot

    def test_draft_creates_nothing_and_final_confirmation_creates_only_final_values(self):
        before = (ProductCatalog.objects.count(), ProductCatalogColor.objects.count(), ProductionUnit.objects.count())
        original = self.snapshot(self.draft(color_name="红色"))
        corrected = deepcopy(original["entry_draft"])
        corrected["color_name"] = "酒红色"
        _, snapshot = resolve_product_selection(None, {"draft": corrected}, existing_snapshot=original)
        self.assertEqual(before, (ProductCatalog.objects.count(), ProductCatalogColor.objects.count(), ProductionUnit.objects.count()))
        product, final = finalize_product_entry(snapshot=snapshot, request=self.request)
        self.assertEqual(list(product.colors.values_list("value", flat=True)), ["酒红色"])
        self.assertEqual(product.materials, ["铝"])
        self.assertEqual(final["entry_state"], "confirmed")
        self.assertTrue(ProductionUnit.objects.filter(pk=final["unit_id"], unit_name="临时新单位").exists())
        self.assertEqual(final["entry_draft"]["sources"]["color_name"], "typed")

    def test_repeated_same_draft_reuses_product_and_options(self):
        snapshot = self.snapshot()
        first, _ = finalize_product_entry(snapshot=snapshot, request=self.request)
        second, _ = finalize_product_entry(snapshot=snapshot, request=self.request)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.colors.count(), 1)
        self.assertEqual(ProductCatalog.objects.filter(item_number="ENTRY-01").count(), 1)

    def test_both_item_number_and_product_code_required_without_partial_writes(self):
        for field in ("item_number", "product_code"):
            with self.subTest(field=field):
                snapshot = self.snapshot(self.draft(**{field: ""}))
                with self.assertRaises(ValidationError):
                    finalize_product_entry(snapshot=snapshot, request=self.request)
                self.assertFalse(ProductCatalogCategory.objects.filter(name="临时新类别").exists())
                self.assertFalse(ProductionUnit.objects.filter(unit_name="临时新单位").exists())

    def test_existing_product_keeps_other_options_and_adds_only_final_option(self):
        first, final = finalize_product_entry(snapshot=self.snapshot(), request=self.request)
        draft = self.draft(color_name="蓝色", material="铁", unit_name=first.unit)
        _, draft_snapshot = resolve_product_selection(None, {"draft": draft})
        product, updated = finalize_product_entry(snapshot=draft_snapshot, request=self.request)
        self.assertEqual(product.pk, first.pk)
        self.assertEqual(set(product.colors.values_list("value", flat=True)), {"酒红色", "蓝色"})
        self.assertEqual(product.materials, ["铝", "铁"])
        self.assertEqual(updated["color_name"], "蓝色")
        self.assertEqual(final["color_name"], "酒红色")

    def test_conflicting_code_does_not_change_existing_product_or_create_unit(self):
        product, _ = finalize_product_entry(snapshot=self.snapshot(), request=self.request)
        snapshot = self.snapshot(self.draft(product_code="DIFFERENT", unit_name="另一个临时单位"))
        with self.assertRaises(ValidationError):
            finalize_product_entry(snapshot=snapshot, request=self.request)
        product.refresh_from_db()
        self.assertEqual(product.product_code, "ENTRY-CODE")
        self.assertFalse(ProductionUnit.objects.filter(unit_name="另一个临时单位").exists())

    def test_finalization_requires_master_permissions_and_rolls_back(self):
        self.request.user = get_user_model().objects.create_user(username="entry_without_permissions")
        with self.assertRaises(PermissionDenied):
            finalize_product_entry(snapshot=self.snapshot(), request=self.request)
        self.assertFalse(ProductCatalogName.objects.filter(name="临时新产品").exists())
        self.assertFalse(ProductionUnit.objects.filter(unit_name="临时新单位").exists())
