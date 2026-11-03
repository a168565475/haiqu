from copy import deepcopy

from rest_framework.test import APITestCase

from apps.product_catalog.models import ProductCatalog
from apps.product_catalog.tests.test_product_entry_drafts import typed_product_draft
from apps.product_catalog.selection import resolve_product_selection
from apps.quotations.models import QuotationLine
from apps.reference_data.models import ProductionUnit

from ..catalog_products import apply_catalog_selection
from ..models import SampleRequest
from ..services import sample_product_values_from_source
from . import test_application_api as fixtures


class ProductEntrySampleTests(APITestCase):
    setUp = fixtures.SampleApplicationApiTests.setUp
    create_customer = fixtures.SampleApplicationApiTests.create_customer
    payload = fixtures.SampleApplicationApiTests.payload
    submit = fixtures.SampleApplicationApiTests.submit
    review = fixtures.SampleApplicationApiTests.review

    def test_sample_application_and_completion_preserve_unlinked_draft(self):
        before = (ProductCatalog.objects.count(), ProductionUnit.objects.count())
        created = self.submit(self.payload(product_catalog_id=None, product_selection={"draft": typed_product_draft()}))
        self.assertEqual(created.status_code, 201, created.data)
        product = SampleRequest.objects.get(pk=created.data["data"]["id"]).products.get()
        snapshot = deepcopy(product.product_selection_snapshot)
        self.assertIsNone(product.product_catalog_id)
        self.assertEqual(product.product_name, "草稿折叠椅")
        self.assertEqual(product.details.get().unit_code, "")
        self.assertEqual(product.details.get().color_name_snapshot, self.product_color.color_name)
        approved = self.review(created)
        self.assertEqual(approved.status_code, 200, approved.data)
        detail = product.details.get()
        response = self.client.patch(f"/api/v1/sample-requests/{product.sample_request_id}/application-products/", {
            "purpose": "补充打样数量", "products": [{"id": str(product.pk), "product_catalog_id": None,
                "product_name": product.product_name, "specification": product.specification, "category_id": None,
                "details": [{"id": str(detail.pk), "product_color_id": None, "sample_quantity": 5, "tolerance": "NONE"}]}],
        }, format="json", HTTP_IF_MATCH=approved["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        product.refresh_from_db()
        self.assertEqual(product.product_selection_snapshot, snapshot)
        self.assertEqual(product.details.get().sample_quantity, 5)
        self.assertEqual((ProductCatalog.objects.count(), ProductionUnit.objects.count()), before)

    def test_upstream_draft_is_copied_without_catalog_or_legacy_color(self):
        _, snapshot = resolve_product_selection(None, {"draft": typed_product_draft()})
        source = QuotationLine(product_catalog=None, product_selection_snapshot=snapshot)
        values = sample_product_values_from_source(source)
        self.assertEqual(values["product_selection_snapshot"], snapshot)
        self.assertIsNone(values["product_catalog"])
        inherited = {"product_catalog_id": None}
        self.assertTrue(apply_catalog_selection(inherited, source=source))
        self.assertEqual(inherited["product_selection_snapshot"], snapshot)
