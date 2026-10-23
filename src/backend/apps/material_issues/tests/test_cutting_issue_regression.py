from apps.workshop_config.tests.factories import production_employee
import uuid
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, PublicStockMovement
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_scheduling.tests.test_production_scheduling_api import ensure_schedule_test_references
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop

from ..models import MaterialIssue, OrderMaterialRequirement
from . import test_material_issue_api as ordinary_fixture
from . import test_public_issue_services as public_fixture


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class CuttingIssueRegressionTests(APITestCase):
    def setUp(self):
        ensure_schedule_test_references()
        ordinary_fixture.MaterialIssueApiTests.setUp(self)
        meters, _ = ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "CUTTING-M"})
        self.raw_material.category = ProductCategory.objects.get(category_name="面料", item_type="MATERIAL")
        self.raw_material.material_name = "裁剪测试布料"
        self.raw_material.unit = meters
        self.raw_material.save(update_fields=["category", "material_name", "unit"])
        self.stock = MaterialStockBalance.objects.get(raw_material=self.raw_material)
        self.stock.unit = meters
        self.stock.save(update_fields=["unit"])
        self.bom_line.section.section_type = "FABRIC"
        self.bom_line.section.title = "面料类"
        self.bom_line.section.save(update_fields=["section_type", "title"])
        self.bom_line.category = "面料"
        self.bom_line.part_name = "裁剪测试布料"
        self.bom_line.material = "涤纶"
        self.bom_line.specification = "600D"
        self.bom_line.unit = "米"
        self.bom_line.total_purchase_quantity = "500"
        self.bom_line.save()
        self.workshop = Workshop.objects.get(name="车缝车间")
        self.recipient = production_employee(
            workshop=self.workshop, position="领料员", name="裁剪测试领料员", is_supervisor=False, status="ACTIVE",
        )
        craft = Craft.objects.create(
            craft_type="INTERNAL", name="裁剪测试工艺", workshop=self.workshop, plan_category="CUTTING",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=craft, craft_type_snapshot="INTERNAL",
            craft_name_snapshot=craft.name, plan_category="CUTTING",
        )
        response = self.client.get("/api/v1/material-issues/requirements/", {
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk), "plan_category": "CUTTING",
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["blockers"], [])
        self.requirement_id = response.data["data"]["items"][0]["requirement_id"]

    def payload(self, quantity="12.5000"):
        return {
            "client_request_id": str(uuid.uuid4()), "schedule_product_id": str(self.schedule_product.pk),
            "plan_category": "CUTTING", "production_task_id": str(self.task.pk),
            "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk), "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": self.requirement_id, "requested_quantity": quantity}],
        }

    def assert_fabric_line(self, response, quantity):
        line = response.data["data"]["lines"][0]
        self.assertEqual(response.data["data"]["stock_mode"], "PUBLIC_V2")
        self.assertEqual((line["section_code"], line["unit"]), ("FABRIC", "米"))
        self.assertEqual(Decimal(line["requested_quantity"]), Decimal(quantity))
        self.assertEqual(line["bom_attributes"], [
            {"key": "specification", "label": "规格", "value": "600D"},
            {"key": "material", "label": "材质", "value": "涤纶"},
        ])
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=self.requirement_id).measurement_kind, "OTHER")
        for key in ("pieces_per_bar", "public_identity", "public_bom_snapshot"):
            self.assertNotIn(key, line["conversion_snapshot"])

    def assert_stock_unchanged(self):
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("600"))
        self.assertFalse(MaterialStockMovement.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_create_cutting_fabric_with_session_csrf_preserves_attributes_without_deducting_stock(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        payload = self.payload()
        denied = client.post("/api/v1/material-issues/", payload, format="json")
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertFalse(MaterialIssue.objects.exists())
        client.get("/api/auth/me/")
        created = client.post("/api/v1/material-issues/", payload, format="json",
                              HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(created.status_code, 201, created.data)
        self.assert_fabric_line(created, "12.5")
        self.assert_stock_unchanged()
        retried = client.post("/api/v1/material-issues/", payload, format="json",
                              HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(retried.status_code, 201, retried.data)
        self.assertEqual(retried.data["data"]["id"], created.data["data"]["id"])
        self.assertEqual(MaterialIssue.objects.count(), 1)

    def test_edit_cutting_fabric_preserves_attributes_and_rejects_stale_version(self):
        payload = self.payload()
        payload["lines"] = []
        created = self.client.post("/api/v1/material-issues/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        path = f"/api/v1/material-issues/{created.data['data']['id']}/"
        changes = {"lines": self.payload("18.7500")["lines"]}
        missing_version = self.client.patch(path, changes, format="json")
        self.assertEqual(missing_version.status_code, 428, missing_version.data)
        edited = self.client.patch(path, changes, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assert_fabric_line(edited, "18.75")
        stale = self.client.patch(path, {"lines": self.payload("20")["lines"]},
                                  format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)
        invalid = self.client.patch(path, {"lines": self.payload("0")["lines"]},
                                    format="json", HTTP_IF_MATCH=edited["ETag"])
        self.assertEqual(invalid.status_code, 400, invalid.data)
        detail = self.client.get(path)
        self.assert_fabric_line(detail, "18.75")
        self.assert_stock_unchanged()
        submitted = self.client.post(path + "submit/", {}, format="json", HTTP_IF_MATCH=edited["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["data"]["status"], "PENDING_REVIEW")
        self.assert_stock_unchanged()


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicPipeIssueRegressionTests(public_fixture.PublicIssueFixture, APITestCase):
    def setUp(self):
        ensure_schedule_test_references()
        # 旧夹具通过采购批次准备管材；实际业务断言仍使用完整公共库存模式。
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            super().setUp()

    test_pipe_create_submit_preview_confirm_uses_public_balance_and_freezes_actuals = (
        public_fixture.PublicIssueServiceTests.test_pipe_create_submit_preview_confirm_uses_public_balance_and_freezes_actuals
    )
    test_pipe_must_be_whole_bar_and_multiple_components_share_one_stock_pool = (
        public_fixture.PublicIssueServiceTests.test_pipe_must_be_whole_bar_and_multiple_components_share_one_stock_pool
    )
