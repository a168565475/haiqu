from decimal import Decimal
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from apps.inventory.tests.test_public_stock_services import PublicStockFixture
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.material_catalog.models import MaterialCatalog
from ..catalog_requirements import catalog_requirement_specs
from ..models import MaterialIssue, OrderMaterialRequirement


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class CatalogIssueApiTests(PublicStockFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="领料新管材")
        self.saved = {"schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name, "scope": "BASE", "processing_state": "RAW",
            "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"},
            "unit_id": str(self.root_unit.pk), "unit_name": "根", "display_name": "领料新管材 / 根"}
        self.set_source()

    def set_source(self, roots=True):
        if roots:
            self.saved.update(unit_id=str(self.root_unit.pk), unit_name="根")
        self.bom_line.material_catalog = self.catalog
        self.bom_line.raw_values["pipe_plan_version"] = 3
        self.bom_line.material_selection_snapshot = self.saved
        self.bom_line.material_quantity = None
        self.bom_line.unit = self.saved["unit_name"]
        self.bom_line.save()
        self.identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk, material_selection_snapshot=self.saved,
            raw_bar_length_m=self.bom_line.raw_bar_length_m)
        specs, blockers = catalog_requirement_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        self.spec = specs[0]

    def payload(self, quantity="12"):
        return {"client_request_id": str(uuid4()), "schedule_product_id": str(self.schedule_product.pk), "plan_category": "METAL",
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk), "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": str(self.spec["id"]), "requested_quantity": quantity}]}

    def create(self, quantity="12"):
        response = self.client.post("/api/v1/material-issues/", self.payload(quantity), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def issue(self, created):
        identifier = created.data["data"]["id"]
        submitted = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        preview = self.client.post(f"/api/v1/material-issues/{identifier}/preview-issue/", {}, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["data"]["can_confirm"], preview.data)
        request_id = str(uuid4())
        confirmed = self.client.post(f"/api/v1/material-issues/{identifier}/confirm-issue/", {"request_id": request_id},
            format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return MaterialIssue.objects.get(pk=identifier), request_id

    def test_different_actual_length_stock_does_not_supply_expected_length(self):
        other = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.saved, raw_bar_length_m="6.00")
        self.credit(10, identity=other)
        response = self.client.post("/api/v1/material-issues/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialIssue.objects.exists())
        self.assertEqual(PublicStockBalance.objects.get().quantity, 10)

    def test_root_issue_preserves_actual_pieces_and_separate_deducted_roots(self):
        self.set_source(roots=True)
        self.credit(10, identity=self.identity)
        issue, _ = self.issue(self.create("12"))
        line = issue.lines.get()
        self.assertEqual(line.unit_snapshot, "支")
        self.assertEqual(line.material_selection_snapshot["unit_name"], "根")
        self.assertEqual(Decimal(line.conversion_snapshot["manufacturing_issued_pieces"]), 12)
        self.assertEqual(Decimal(line.conversion_snapshot["physical_issued_quantity"]), 2)
        self.assertEqual(line.public_stock_allocations.get().stock_quantity, 2)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 8)

    def test_candidates_do_not_create_requirements_and_preserve_piece_unit(self):
        self.credit(3, identity=self.identity)
        before = OrderMaterialRequirement.objects.count()
        response = self.client.get("/api/v1/material-issues/requirements/", {"production_task_id": str(self.task.pk),
            "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data["data"]["items"] if row["requirement_id"] == str(self.spec["id"]))
        self.assertEqual(row["unit"], "支")
        self.assertEqual(Decimal(row["available_stock"]), 3 * self.bom_line.pieces_per_bar)
        self.assertEqual(before, OrderMaterialRequirement.objects.count())

    def test_preview_detects_changed_catalog_demand_without_rewriting_requirements(self):
        self.credit(10, identity=self.identity)
        created = self.create()
        identifier = created.data["data"]["id"]
        submitted = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        before = OrderMaterialRequirement.objects.get().source_revision_hash
        self.bom_line.material_selection_snapshot = {**self.saved, "attributes": {**self.saved["attributes"], "thickness": "2"}}
        self.bom_line.save()
        preview = self.client.post(f"/api/v1/material-issues/{identifier}/preview-issue/", {}, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["data"]["can_confirm"])
        self.assertIn("SOURCE_CHANGED", [row["code"] for row in preview.data["data"]["errors"]])
        self.assertEqual(OrderMaterialRequirement.objects.get().source_revision_hash, before)

    def test_real_session_requires_csrf_for_new_material_issue(self):
        self.credit(10, identity=self.identity)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/v1/material-issues/", self.payload(), format="json").status_code, 403)
        client.get("/api/auth/me/")
        response = client.post("/api/v1/material-issues/", self.payload(), format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.data)

    def test_insufficient_stock_rolls_back_issue_and_ledger(self):
        self.credit(1, identity=self.identity)
        response = self.client.post("/api/v1/material-issues/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialIssue.objects.exists())
        self.assertEqual(PublicStockMovement.objects.count(), 1)
