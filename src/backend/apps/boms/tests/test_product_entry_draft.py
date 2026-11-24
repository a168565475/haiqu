from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.audit.models import AuditLog
from apps.product_catalog.finalization import finalize_product_entry
from apps.product_catalog.models import ProductCatalog, ProductCatalogColor
from apps.product_catalog.selection import resolve_product_selection
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
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

    def catalog_draft(self, color="蓝色"):
        name = self.catalog.name
        draft = {
            "category_id": str(name.category_id), "category_name": name.category.name,
            "name_id": str(name.pk), "name": name.name,
            "item_number": self.catalog.item_number, "product_code": self.catalog.product_code,
            "specification": self.catalog.specification, "unit_id": str(self.unit.pk), "unit_name": self.unit.unit_name,
            "color_name": color, "color_id": str(self.blue.pk) if color == self.blue.value else None, "material": "铁",
            "sources": {field: "selected" for field in self.draft()["sources"]},
        }
        if draft["color_id"] is None:
            draft["sources"]["color_name"] = "typed"
        return {"draft": draft, "catalog_version": self.catalog.updated_at.isoformat()}

    def create_reviewed_catalog_bom(self, color="蓝色"):
        created = self.client.post("/api/v1/production-tasks/", self.catalog_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        task.status = ProductionTaskStatus.READY
        task.save(update_fields=["status"])
        bom = self.create_bom_with_material(task.products.get())
        return bom, self.confirm_bom(bom, self.catalog_draft(color))

    def change_catalog(self, method, suffix="", data=None):
        url = f"/api/v1/product-catalog/{self.catalog.pk}/"
        current = self.client.get(url)
        self.assertEqual(current.status_code, 200, current.data)
        response = getattr(self.client, method)(url + suffix, data or {}, format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.catalog.refresh_from_db()

    def test_product_review_refreshes_saved_draft_after_color_is_added(self):
        bom, _ = self.create_reviewed_catalog_bom()
        self.change_catalog("post", "colors/", {"value": "绿色"})

        reviewed = self.confirm_bom(bom)
        snapshot = reviewed.data["data"]["product_selection_snapshot"]
        self.assertEqual(snapshot["catalog_version"], self.catalog.updated_at.isoformat())
        self.assertEqual(snapshot["specification"], "60*80")
        self.assertEqual(snapshot["color_id"], str(self.blue.pk))
        self.verify_bom(bom, reviewed)

    def test_previously_reviewed_bom_can_verify_after_other_boms_add_colors(self):
        bom, reviewed = self.create_reviewed_catalog_bom(color="藏青色")
        request = APIRequestFactory().post("/api/v1/boms/verify/", {}, format="json")
        request.user = self.user
        request.employee = self.employee
        for color in ("藏青色", "墨绿色"):
            _, snapshot = resolve_product_selection(self.catalog.pk, self.catalog_draft(color))
            finalize_product_entry(snapshot=snapshot, catalog_id=self.catalog.pk,
                                   request=request, actor_employee=self.employee)
            self.catalog.refresh_from_db()

        self.verify_bom(bom, reviewed)
        bom.refresh_from_db()
        self.assertEqual(bom.product_selection_snapshot["catalog_version"], self.catalog.updated_at.isoformat())
        self.assertEqual(bom.product_selection_snapshot["color_name"], "藏青色")
        self.assertEqual(bom.product_catalog_id, self.catalog.pk)

    def test_previously_reviewed_bom_can_use_color_additions_in_historical_audit(self):
        bom, reviewed = self.create_reviewed_catalog_bom(color="藏青色")
        previous_colors = list(self.catalog.colors.values_list("value", flat=True))
        ProductCatalogColor.objects.create(product=self.catalog, value="藏青色")
        self.catalog.save(update_fields=["updated_at"])
        # 已有线上记录的此类审计没有单独保存档案版本时间。
        AuditLog.objects.create(
            object_type="PRODUCT_CATALOG", object_id=self.catalog.pk, action="UPDATED",
            before_data={"colors": previous_colors, "materials": self.catalog.materials},
            after_data={"color": "藏青色", "material": "铁", "source": "BOM_CONFIRMATION"},
            occurred_at=timezone.now(),
        )

        self.verify_bom(bom, reviewed)
        bom.refresh_from_db()
        self.assertEqual(bom.product_selection_snapshot["catalog_version"], self.catalog.updated_at.isoformat())

    def test_product_review_rejects_spec_change_even_after_another_color_is_added(self):
        bom, reviewed = self.create_reviewed_catalog_bom()
        self.change_catalog("patch", data={"specification": "80*100"})
        self.change_catalog("post", "colors/", {"value": "绿色"})

        response = self.client.post(f"/api/v1/boms/{bom.pk}/confirm-product/",
            {"product_catalog_id": str(self.catalog.pk)}, format="json", HTTP_IF_MATCH=reviewed["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("product_selection", response.data["error"]["field_errors"])
        bom.refresh_from_db()
        self.assertEqual(bom.specification_snapshot, "60*80")

    def test_product_review_rejects_removed_selected_color(self):
        bom, reviewed = self.create_reviewed_catalog_bom()
        self.change_catalog("delete", f"colors/{self.blue.pk}/")

        response = self.client.post(f"/api/v1/boms/{bom.pk}/confirm-product/",
            {"product_catalog_id": str(self.catalog.pk)}, format="json", HTTP_IF_MATCH=reviewed["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("product_selection", response.data["error"]["field_errors"])

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
