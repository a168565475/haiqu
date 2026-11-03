from copy import deepcopy

from rest_framework.test import APITestCase

from apps.product_catalog.models import ProductCatalog
from apps.product_catalog.tests.test_product_entry_drafts import typed_product_draft
from apps.reference_data.models import ProductionUnit

from ..models import ProductionTask
from . import test_production_task_api as fixtures


class ProductEntryProductionTests(APITestCase):
    setUp = fixtures.ProductionTaskApiTests.setUp
    payload = fixtures.ProductionTaskApiTests.payload

    def test_manual_task_saves_and_reedits_draft_with_no_formal_unit(self):
        before = (ProductCatalog.objects.count(), ProductionUnit.objects.count())
        payload = self.payload()
        payload["products"][0].update(product_id=None, product_color_id=None, color_code="", product_catalog_id=None,
                                      product_selection={"draft": typed_product_draft()}, unit_id=None)
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        product = task.products.get()
        snapshot = deepcopy(product.product_selection_snapshot)
        self.assertIsNone(product.unit_id)
        self.assertIsNone(product.product_catalog_id)
        self.assertEqual(product.unit_name, "未建档单位")
        self.assertEqual(created.data["data"]["products"][0]["unit_name"], "未建档单位")
        payload["products"][0].pop("product_selection")
        payload["products"][0]["client_key"] = str(product.pk)
        payload["products"][0]["details"][0]["client_key"] = str(product.details.get().pk)
        updated = self.client.patch(f"/api/v1/production-tasks/{task.pk}/", {"products": payload["products"]},
                                    format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(updated.status_code, 200, updated.data)
        product.refresh_from_db()
        self.assertEqual(product.product_selection_snapshot, snapshot)
        self.assertEqual(product.product_code_snapshot, "DRAFT-CODE")
        self.assertEqual((ProductCatalog.objects.count(), ProductionUnit.objects.count()), before)

    def test_legacy_task_still_requires_selected_unit(self):
        payload = self.payload()
        payload["products"][0]["unit_id"] = None
        response = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
