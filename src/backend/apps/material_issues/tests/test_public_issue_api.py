import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_identity import build_pipe_stock_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_pipe_stock_foundation import PipeFixture
from apps.organizations.models import Employee
from apps.material_issues.models import MaterialIssue, MaterialIssueBatchAllocation, OrderSemiFinishedRequirement
from apps.material_issues.tests import test_material_issue_api as ordinary_fixture


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicIssueApiTests(PipeFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.identity = build_pipe_stock_identity(raw_material=self.raw_material,
            raw_bar_length_m=self.bom_line.raw_bar_length_m, unit=self.raw_material.unit)
        self.credit(337)

    def credit(self, quantity):
        return credit_public_stock(identity=self.identity, zone=self.zone, quantity=quantity,
            source_type="S4_API_TEST", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)

    def rows(self, **extra):
        return self.client.get("/api/v1/material-issues/requirements/", {
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk), **extra,
        })

    def payload(self, quantity="600"):
        return {"client_request_id": str(uuid.uuid4()), "schedule_product_id": str(self.schedule_product.pk),
                "plan_category": "METAL", "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
                "recipient_workshop_employee_id": str(self.recipient.pk), "issue_at": timezone.now().isoformat(),
                "lines": [{"requirement_id": str(self.requirement.pk), "requested_quantity": quantity}]}

    def create(self, quantity="600"):
        response = self.client.post("/api/v1/material-issues/", self.payload(quantity), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def submit(self, created):
        identifier = created.data["data"]["id"]
        response = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_candidates_are_read_only_and_never_read_procurement_batches(self):
        before = (MaterialIssue.objects.count(), PublicStockMovement.objects.count(), OrderSemiFinishedRequirement.objects.count())
        with CaptureQueriesContext(connection) as queries:
            response = self.rows()
        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data["data"]["items"] if row["requirement_id"] == str(self.requirement.pk))
        self.assertEqual(row["stock_mode"], "PUBLIC_V2")
        self.assertEqual(Decimal(row["available_stock"]), 2022)
        self.assertFalse(row.get("batch_candidates"))
        for query in queries:
            self.assertNotIn('"inventory_material_inbound_line"', query["sql"])
            self.assertFalse(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")))
        self.assertEqual(before, (MaterialIssue.objects.count(), PublicStockMovement.objects.count(), OrderSemiFinishedRequirement.objects.count()))

    def test_preview_uses_current_public_stock_and_issued_detail_stays_frozen(self):
        created = self.create()
        self.assertEqual(created.data["data"]["stock_mode"], "PUBLIC_V2")
        pending = self.submit(created)
        identifier = created.data["data"]["id"]
        self.credit(3)
        preview = self.client.post(f"/api/v1/material-issues/{identifier}/preview-issue/", {}, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["data"]["can_confirm"], preview.data)
        row = preview.data["data"]["lines"][0]
        self.assertEqual(Decimal(row["available_stock"]), 2040)
        self.assertEqual(Decimal(row["bar_count"]), 100)
        self.assertEqual(Decimal(row["meters"]), Decimal("305.00"))
        self.assertEqual(row["line_id"], created.data["data"]["lines"][0]["id"])
        request_id = str(uuid.uuid4())
        confirmed = self.client.post(f"/api/v1/material-issues/{identifier}/confirm-issue/", {"request_id": request_id},
                                     format="json", HTTP_IF_MATCH=pending["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 240)
        self.assertFalse(MaterialIssueBatchAllocation.objects.filter(line__issue_id=identifier).exists())
        frozen = confirmed.data["data"]["lines"]
        self.credit(11)
        with CaptureQueriesContext(connection) as queries:
            detail = self.client.get(f"/api/v1/material-issues/{identifier}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["lines"], frozen)
        self.assertLess(len(queries), 30)
        self.assertFalse(any('"inventory_material_inbound_line"' in query["sql"] for query in queries))
        self.assertFalse(any('"inventory_public_stock_balance"' in query["sql"] for query in queries))

    def test_actor_permissions_and_version_checks_are_enforced(self):
        created = self.create()
        identifier = created.data["data"]["id"]
        missing_etag = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {}, format="json")
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        outsider = get_user_model().objects.create_user(username="s4_no_issue_permission")
        Employee.objects.create(user=outsider, employee_code="S4_NO_ISSUE", display_name="无领料权限")
        self.client.force_authenticate(outsider)
        denied = self.client.get(f"/api/v1/material-issues/{identifier}/")
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertEqual(MaterialIssue.objects.get(pk=identifier).status, "DRAFT")

    def test_real_session_write_requires_csrf(self):
        session_client = APIClient(enforce_csrf_checks=True)
        session_client.force_login(self.user)
        payload = self.payload()
        denied = session_client.post("/api/v1/material-issues/", payload, format="json")
        self.assertEqual(denied.status_code, 403, denied.data)
        session_client.get("/api/auth/me/")
        token = session_client.cookies["csrftoken"].value
        accepted = session_client.post("/api/v1/material-issues/", payload, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(accepted.status_code, 201, accepted.data)
        self.assertEqual(MaterialIssue.objects.count(), 1)

    def test_client_cannot_override_stock_mode_and_legacy_edit_keeps_legacy_candidates(self):
        payload = self.payload()
        payload["stock_mode"] = "LEGACY"
        created = self.client.post("/api/v1/material-issues/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["stock_mode"], "PUBLIC_V2")
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False):
            legacy = self.create()
        response = self.rows(issue_id=legacy.data["data"]["id"])
        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data["data"]["items"] if row["requirement_id"] == str(self.requirement.pk))
        self.assertNotEqual(row.get("stock_mode"), "PUBLIC_V2")
        self.assertTrue(row["batch_candidates"])


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicOrdinaryCandidateTests(APITestCase):
    _plan_source = ordinary_fixture.MaterialIssueApiTests._plan_source
    _requirements = ordinary_fixture.MaterialIssueApiTests._requirements
    _create_issue = ordinary_fixture.MaterialIssueApiTests._create_issue

    def setUp(self):
        ordinary_fixture.MaterialIssueApiTests.setUp(self)
        from apps.reference_data.models import ProductCategory
        self.raw_material.category = ProductCategory.objects.get(category_name="五金", item_type="MATERIAL")
        self.raw_material.save(update_fields=["category"])
        self.bom_line.section.title = "五金类"
        self.bom_line.section.save(update_fields=["title"])
        self.bom_line.category = "五金"
        self.bom_line.save(update_fields=["category"])

    def test_other_order_pending_reduces_candidate_max_but_not_physical_stock(self):
        created = self._create_issue("400")
        identifier = created.data["data"]["id"]
        submitted = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {},
            format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        from apps.boms.models import Bom, BomSection, BomLine
        from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
        task = ProductionTask.objects.get(pk=self.task.pk)
        task.pk = None
        task.task_number, task.contract_number, task.order_number = "S4-OTHER-TASK", "S4-OTHER-CONTRACT", "S4-OTHER-ORDER"
        task.save()
        product = ProductionTaskProduct.objects.get(pk=self.product_line.pk)
        product.pk, product.production_task = None, task
        product.save()
        bom = Bom.objects.get(pk=self.bom.pk)
        bom.pk, bom.production_task, bom.product_line, bom.bom_number = None, task, product, "S4-OTHER-BOM"
        bom.save()
        section = BomSection.objects.get(pk=self.bom_line.section_id)
        section.pk, section.bom = None, bom
        section.save()
        line = BomLine.objects.get(pk=self.bom_line.pk)
        line.pk, line.section, line.component_identity = None, section, uuid.uuid4()
        line.save()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/material-issues/requirements/", {
                "production_task_id": str(task.pk), "product_line_id": str(product.pk), "workshop_id": str(self.workshop.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"]["items"][0]
        self.assertEqual(tuple(Decimal(row[key]) for key in (
            "required_quantity", "available_stock", "pending_issue_quantity", "public_pending_quantity", "max_issue_quantity")),
            (500, 600, 0, 400, 200))
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for query in queries))
