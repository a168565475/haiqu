from django.contrib.auth.models import Permission

from apps.product_catalog.models import ProductCatalog, ProductCatalogColor
from apps.production_tasks.tests import test_catalog_business_flow as flow
from apps.reference_data.models import ProductionUnit


class BomProductEntryDraftTests(flow.CatalogProductionBomBusinessTests):
    def setUp(self):
        super().setUp()
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="product_catalog"))
        self.user.user_permissions.add(Permission.objects.get(codename="add_productionunit"))

    def draft(self):
        values = {"category_name": "BOM临时产品类别", "name": "BOM临时产品", "item_number": "NEW-ITEM",
                  "product_code": "NEW-CODE", "specification": "80*100", "unit_name": "BOM临时单位",
                  "color_name": "酒红色", "material": "铝"}
        return {**values, "sources": {field: "typed" for field in values}}

    def review_draft(self, bom):
        current = self.client.get(f"/api/v1/boms/{bom.pk}/")
        reviewed = self.client.post(f"/api/v1/boms/{bom.pk}/confirm-product/",
            {"product_catalog_id": None, "product_selection": {"draft": self.draft()}},
            format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        self.assertTrue(reviewed.data["data"]["product_information_confirmed"])
        return reviewed

    def test_review_only_saves_draft_and_verify_creates_final_catalog(self):
        _, line = self.create_catalog_task()
        bom = self.create_bom_with_material(line)
        product_count = ProductCatalog.objects.count()
        reviewed = self.review_draft(bom)
        self.assertEqual(ProductCatalog.objects.count(), product_count)
        self.assertFalse(ProductionUnit.objects.filter(unit_name="BOM临时单位").exists())
        self.verify_bom(bom, reviewed)
        bom.refresh_from_db()
        line.refresh_from_db()
        self.assertIsNotNone(bom.product_catalog_id)
        self.assertEqual(bom.product_catalog_id, line.product_catalog_id)
        self.assertEqual(line.unit.unit_name, "BOM临时单位")
        self.assertEqual(bom.product_selection_snapshot["entry_state"], "confirmed")
        self.assertEqual(list(ProductCatalogColor.objects.filter(product_id=bom.product_catalog_id).values_list("value", flat=True)), ["酒红色"])

    def test_failed_bom_validation_does_not_create_catalog(self):
        _, line = self.create_catalog_task()
        bom = self.create_bom_with_material(line)
        self.review_draft(bom)
        from apps.boms.models import Bom
        Bom.objects.filter(pk=bom.pk).update(line_count=0)
        current = self.client.get(f"/api/v1/boms/{bom.pk}/")
        response = self.client.post(f"/api/v1/boms/{bom.pk}/verify/", {}, format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ProductCatalog.objects.filter(item_number="NEW-ITEM").exists())
        self.assertFalse(ProductionUnit.objects.filter(unit_name="BOM临时单位").exists())
