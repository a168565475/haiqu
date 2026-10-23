from apps.workshop_config.tests.factories import production_employee
import uuid
import threading
import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomSectionType, BomStatus
from apps.customers.models import CustomerAccount
from apps.inventory.models import (
    MaterialStockBalance,
    MaterialStockMovement,
    MaterialStockQuality,
    SemiFinishedStockBalance,
    Warehouse,
    WarehouseType,
    WarehouseZone,
)
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.production_tasks.models import DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.production_scheduling.services import create_schedule
from apps.reference_data.models import Currency, FabricMaterial, ProductCategory, ProductionUnit
from apps.workshop_config.models import (
    Craft,
    CraftType,
    OutsourcingCode,
    PlanCategory,
    RecordStatus,
    Workshop,
    WorkshopEmployeeStatus,
)

from ..models import MaterialIssue, MaterialIssueAction, MaterialIssueStatus, OrderMaterialRequirement


class MaterialIssueApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="material_issue_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="MATERIAL_ISSUE_USER",
            display_name="领料测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=["material_issues", "inventory", "production_tasks"]
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.product = ProductInformation.objects.filter(
            status="ACTIVE", archived_at__isnull=True
        ).select_related("unit", "product_item").first()
        self.currency = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        material_category = ProductCategory.objects.filter(category_name="管材", item_type="MATERIAL").first()
        stock_unit = ProductionUnit.objects.filter(unit_name="PCS").first()
        self.assertIsNotNone(self.product)
        self.assertIsNotNone(self.currency)
        self.assertIsNotNone(material_category)
        self.assertIsNotNone(stock_unit)
        self.raw_material = RawMaterialInformation.objects.create(
            material_number="MAT-ISSUE-001",
            item_type="MATERIAL",
            category=material_category,
            material_name="领料测试钢管",
            specification="Φ25×1.0",
            unit=stock_unit,
            material="黑管",
            warehouse_number="CK-ISSUE",
            warehouse_name="领料测试仓",
        )
        self.customer = CustomerAccount.objects.create(
            account_code="MAT_ISSUE_CUSTOMER",
            account_name="领料测试客户",
            primary_country_code="CN",
        )
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT-ISSUE-0001",
            contract_number="HTC-ISSUE-0001",
            order_source=OrderSource.NEW,
            order_number="ORDER-ISSUE-001",
            customer_account=self.customer,
            order_date=today,
            delivery_date=today,
            salesperson=self.employee,
            currency=self.currency,
            includes_tax=True,
            order_tolerance_percent=Decimal("0"),
            is_repeat_order=False,
            preproduction_sample_required=False,
            delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY,
            created_by_employee=self.employee,
        )
        self.product_line = ProductionTaskProduct.objects.create(
            production_task=self.task,
            line_number=1,
            product=self.product,
            product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number,
            product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification,
            color_name_snapshot="黑色",
            quantity=500,
            unit=self.product.unit,
            currency=self.currency,
            unit_price=Decimal("1"),
            total_amount=Decimal("500"),
            exchange_rate=Decimal("1"),
        )
        self.bom = Bom.objects.create(
            bom_number="BOM-MAT-ISSUE-1",
            production_task=self.task,
            product_line=self.product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code,
            product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification,
            order_quantity=Decimal("500"),
            quantity_difference=Decimal("0"),
            section_count=1,
            line_count=1,
            created_by_employee=self.employee,
        )
        section = BomSection.objects.create(
            bom=self.bom,
            line_number=1,
            section_type=BomSectionType.ACCESSORY,
            title="管材类",
        )
        self.bom_line = BomLine.objects.create(
            section=section,
            line_number=1,
            category="管材",
            material="黑管",
            part_name="领料测试钢管",
            specification="Φ25×1.0",
            raw_material="黑管",
            unit="PCS",
            budget_quantity="500",
            raw_values={"source_raw_material_id": str(self.raw_material.pk)},
        )
        PurchaseOrder.objects.create(
            order_number="CGDD-MATERIAL-ISSUE-001",
            production_task=self.task,
            production_task_number_snapshot=self.task.task_number,
            sales_order_number_snapshot=self.task.order_number,
            customer_name_snapshot=self.task.customer_account.account_name,
            source_revision="material-issue-test",
            status=PurchaseOrderStatus.COMPLETED,
            created_by_employee=self.employee,
            completed_by_employee=self.employee,
            completed_at=timezone.now(),
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_number="CKISSUE",
            warehouse_name="领料测试仓",
            warehouse_type=WarehouseType.MATERIAL,
            status=RecordStatus.ACTIVE,
        )
        self.zone = WarehouseZone.objects.create(
            warehouse=self.warehouse,
            zone_name="一楼",
            status=RecordStatus.ACTIVE,
        )
        MaterialStockBalance.objects.create(
            raw_material=self.raw_material,
            zone=self.zone,
            unit=self.raw_material.unit,
            quality=MaterialStockQuality.AVAILABLE,
            quantity=Decimal("600"),
        )
        self.workshop = Workshop.objects.filter(status=RecordStatus.ACTIVE, name="金工车间").first()
        self.assertIsNotNone(self.workshop)
        self.recipient = production_employee(
            workshop=self.workshop,
            position="领料员",
            name="领料测试人",
            is_supervisor=False,
            status=WorkshopEmployeeStatus.ACTIVE,
        )
        self.plan_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            name="领料测试金工作业",
            workshop=self.workshop,
            plan_category=PlanCategory.METAL,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.sewing_plan_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            name="领料测试车缝作业",
            workshop=Workshop.objects.get(name="车缝车间"),
            plan_category=PlanCategory.SEWING,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.schedule = create_schedule(
            validated_data={
                "client_request_id": uuid.uuid4(),
                "production_task_id": self.task.pk,
                "source_revision_hash": "",
                "items": [
                    {
                        "product_line_id": self.product_line.pk,
                        "planned_quantity": self.product_line.quantity,
                        "craft_ids": {self.plan_craft.pk, self.sewing_plan_craft.pk},
                        "material_inbound_date": today,
                        "metal_return_date": today,
                        "sewing_return_date": today,
                        "finished_inbound_date": today,
                    }
                ],
            },
            actor_employee=self.employee,
        )
        self.schedule_product = self.schedule.products.get(product_line=self.product_line, removed_at__isnull=True)

    def _plan_source(self, category=PlanCategory.METAL):
        return {
            "schedule_product_id": str(self.schedule_product.pk),
            "plan_category": category,
        }

    def _requirements(self):
        response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["blockers"], [])
        self.assertIn("一楼", response.data["data"]["items"][0]["warehouse_zones"])
        return response.data["data"]["items"][0]

    def _create_issue(self, quantity="120.0000"):
        requirement = self._requirements()
        response = self.client.post(
            "/api/v1/material-issues/",
            {
                **self._plan_source(),
                "client_request_id": str(uuid.uuid4()),
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(self.workshop.pk),
                "recipient_workshop_employee_id": str(self.recipient.pk),
                "issue_at": timezone.now().isoformat(),
                "remark": "车间生产领料",
                "lines": [
                    {"requirement_id": requirement["requirement_id"], "requested_quantity": quantity}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_requirements_only_return_materials_allowed_for_workshop(self):
        sewing_workshop = Workshop.objects.get(name="车缝车间")
        self.bom_line.raw_values = {}
        self.bom_line.raw_material = "未映射金工管材"
        self.bom_line.material = "未映射金工管材"
        self.bom_line.save(update_fields=["raw_values", "raw_material", "material", "updated_at"])

        response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(sewing_workshop.pk),
            },
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["items"], [])
        self.assertEqual(response.data["data"]["blockers"], [])

    def test_create_rejects_material_outside_workshop_scope(self):
        requirement = self._requirements()
        sewing_workshop = Workshop.objects.get(name="车缝车间")
        sewing_recipient = production_employee(
            workshop=sewing_workshop,
            position="领料员",
            name="车缝领料测试人",
            is_supervisor=False,
            status=WorkshopEmployeeStatus.ACTIVE,
        )

        response = self.client.post(
            "/api/v1/material-issues/",
            {
                **self._plan_source(PlanCategory.SEWING),
                "client_request_id": str(uuid.uuid4()),
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(sewing_workshop.pk),
                "recipient_workshop_employee_id": str(sewing_recipient.pk),
                "issue_at": timezone.now().isoformat(),
                "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": "1"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不属于所选车间", str(response.data))

    def test_sewing_plan_rejects_fabric_even_in_same_workshop(self):
        fabric_requirement = OrderMaterialRequirement.objects.create(
            production_task=self.task,
            raw_material=self.raw_material,
            unit=self.raw_material.unit,
            line_type="RAW",
            section_code="FABRIC",
            required_quantity=Decimal("500"),
            source_revision_hash="fabric-scope-test",
        )
        sewing_workshop = Workshop.objects.get(name="车缝车间")
        sewing_recipient = production_employee(
            workshop=sewing_workshop,
            position="领料员",
            name="车缝面料越权测试人",
            is_supervisor=False,
            status=WorkshopEmployeeStatus.ACTIVE,
        )

        with patch(
            "apps.material_issues.services.sync_order_requirements",
            return_value=(self.task, [fabric_requirement], [], "fabric-scope-test"),
        ):
            response = self.client.post(
                "/api/v1/material-issues/",
                {
                    **self._plan_source(PlanCategory.SEWING),
                    "client_request_id": str(uuid.uuid4()),
                    "production_task_id": str(self.task.pk),
                    "product_line_id": str(self.product_line.pk),
                    "workshop_id": str(sewing_workshop.pk),
                    "recipient_workshop_employee_id": str(sewing_recipient.pk),
                    "issue_at": timezone.now().isoformat(),
                    "lines": [{"requirement_id": str(fabric_requirement.pk), "requested_quantity": "1"}],
                },
                format="json",
            )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不属于所选车间", str(response.data))

    def test_create_rejects_forged_work_plan_category(self):
        requirement = self._requirements()
        response = self.client.post(
            "/api/v1/material-issues/",
            {
                **self._plan_source(PlanCategory.ASSEMBLY),
                "client_request_id": str(uuid.uuid4()),
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(self.workshop.pk),
                "recipient_workshop_employee_id": str(self.recipient.pk),
                "issue_at": timezone.now().isoformat(),
                "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": "1"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("作业计划类型不一致", str(response.data))

    def test_created_issue_records_plan_source_and_reuses_request_id(self):
        requirement = self._requirements()
        request_id = str(uuid.uuid4())
        payload = {
            **self._plan_source(),
            "client_request_id": request_id,
            "production_task_id": str(self.task.pk),
            "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk),
            "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": "1"}],
        }

        first = self.client.post("/api/v1/material-issues/", payload, format="json")
        second = self.client.post("/api/v1/material-issues/", payload, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["data"]["id"], second.data["data"]["id"])
        issue = MaterialIssue.objects.get(pk=first.data["data"]["id"])
        self.assertRegex(issue.issue_number, rf"^LL{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        self.assertEqual(first.data["data"]["issue_number"], second.data["data"]["issue_number"])
        created_event = issue.audit_events.get(action=MaterialIssueAction.CREATED)
        self.assertEqual(created_event.snapshot["plan_source"]["schedule_product_id"], str(self.schedule_product.pk))
        self.assertEqual(created_event.snapshot["plan_source"]["plan_category"], PlanCategory.METAL)

    def test_list_filters_records_for_current_plan_product(self):
        created = self._create_issue(quantity="1")

        response = self.client.get(
            "/api/v1/material-issues/",
            {
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
            },
        )
        empty = self.client.get(
            "/api/v1/material-issues/",
            {"product_line_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([item["id"] for item in response.data["data"]], [created.data["data"]["id"]])
        self.assertEqual(
            response.data["meta"],
            {"page": 1, "page_size": 20, "total": 1, "total_pages": 1},
        )
        self.assertEqual(response.data["data"][0]["product"]["quantity"], "500")
        self.assertEqual(response.data["data"][0]["product"]["unit"], self.product.unit.unit_name)
        self.assertEqual(empty.status_code, 200, empty.data)
        self.assertEqual(empty.data["data"], [])

    def concurrency_create_with_same_request_id_returns_same_issue(self):
        requirement = self._requirements()
        request_id = str(uuid.uuid4())
        payload = {
            **self._plan_source(),
            "client_request_id": request_id,
            "production_task_id": str(self.task.pk),
            "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk),
            "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": "1"}],
        }
        barrier = threading.Barrier(2)
        results = []

        def worker():
            connections.close_all()
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            barrier.wait(timeout=5)
            response = client.post("/api/v1/material-issues/", payload, format="json")
            results.append((response.status_code, response.data.get("data", {}).get("id")))
            connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(status for status, _ in results), [201, 201])
        self.assertEqual(len({issue_id for _, issue_id in results}), 1)
        self.assertEqual(MaterialIssue.objects.filter(client_request_id=request_id).count(), 1)

    def concurrency_create_with_same_request_id_and_different_payload_conflicts(self):
        requirement = self._requirements()
        request_id = str(uuid.uuid4())
        base_payload = {
            **self._plan_source(),
            "client_request_id": request_id,
            "production_task_id": str(self.task.pk),
            "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk),
            "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": requirement["requirement_id"], "requested_quantity": "1"}],
        }
        barrier = threading.Barrier(2)
        results = []

        def worker(remark):
            connections.close_all()
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            barrier.wait(timeout=5)
            response = client.post(
                "/api/v1/material-issues/",
                {**base_payload, "remark": remark},
                format="json",
            )
            results.append(response.status_code)
            connections.close_all()

        threads = [
            threading.Thread(target=worker, args=("并发内容甲",)),
            threading.Thread(target=worker, args=("并发内容乙",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(MaterialIssue.objects.filter(client_request_id=request_id).count(), 1)

    def test_edit_cannot_change_scope_outside_original_work_plan(self):
        created = self._create_issue(quantity="1")
        sewing_workshop = Workshop.objects.get(name="车缝车间")
        sewing_recipient = production_employee(
            workshop=sewing_workshop,
            position="领料员",
            name="编辑绕过测试领料人",
            is_supervisor=False,
            status=WorkshopEmployeeStatus.ACTIVE,
        )

        response = self.client.patch(
            f"/api/v1/material-issues/{created.data['data']['id']}/",
            {
                "workshop_id": str(sewing_workshop.pk),
                "recipient_workshop_employee_id": str(sewing_recipient.pk),
            },
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("作业计划类型不一致", str(response.data))

    def concurrency_confirm_waits_for_bom_change_and_does_not_deduct_stale_material(self):
        created = self._create_issue(quantity="1")
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        bom_locked = threading.Event()
        release_bom = threading.Event()
        confirm_started = threading.Event()
        result = {}

        def edit_bom():
            connections.close_all()
            with transaction.atomic():
                bom = Bom.objects.select_for_update().get(pk=self.bom.pk)
                bom.status = BomStatus.PENDING_CONFIRMATION
                bom.save(update_fields=["status", "updated_at"])
                bom_locked.set()
                release_bom.wait(timeout=5)
            connections.close_all()

        def confirm():
            connections.close_all()
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            confirm_started.set()
            response = client.post(
                f"/api/v1/material-issues/{created.data['data']['id']}/confirm-issue/",
                {"request_id": str(uuid.uuid4())},
                format="json",
                HTTP_IF_MATCH=submitted["ETag"],
            )
            result["status"] = response.status_code
            result["data"] = response.data
            connections.close_all()

        editor = threading.Thread(target=edit_bom)
        confirmer = threading.Thread(target=confirm)
        editor.start()
        self.assertTrue(bom_locked.wait(timeout=5))
        confirmer.start()
        self.assertTrue(confirm_started.wait(timeout=5))
        time.sleep(0.2)
        self.assertTrue(confirmer.is_alive())
        release_bom.set()
        editor.join(timeout=10)
        confirmer.join(timeout=10)

        self.assertFalse(editor.is_alive())
        self.assertFalse(confirmer.is_alive())
        self.assertEqual(result.get("status"), 400, result.get("data"))
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, Decimal("600"))
        self.assertEqual(MaterialIssue.objects.get(pk=created.data["data"]["id"]).status, MaterialIssueStatus.PENDING_REVIEW)

    def test_other_workshop_cannot_start_material_issue(self):
        unsupported_workshop = Workshop.objects.get(name="敲布孔")

        response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(unsupported_workshop.pk),
            },
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("暂未开放", str(response.data))

    def test_fabric_material_mapping_resolves_requirement_and_missing_mapping_blocks(self):
        fabric_material = FabricMaterial.objects.create(material_name="领料测试映射面料")
        self.bom_line.raw_values = {"source_fabric_material_id": str(fabric_material.pk)}
        self.bom_line.save(update_fields=["raw_values", "updated_at"])

        blocked = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(blocked.status_code, 200, blocked.data)
        self.assertEqual(blocked.data["data"]["items"], [])
        self.assertEqual(blocked.data["data"]["blockers"][0]["code"], "MATERIAL_IDENTITY_UNRESOLVED")
        self.assertIn("面料材质尚未关联", blocked.data["data"]["blockers"][0]["detail"])
        blocked_revision_hash = blocked.data["data"]["source_revision_hash"]

        fabric_material.inventory_raw_material = self.raw_material
        fabric_material.save(update_fields=["inventory_raw_material", "updated_at"])
        resolved = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertEqual(resolved.data["data"]["blockers"], [])
        self.assertNotEqual(resolved.data["data"]["source_revision_hash"], blocked_revision_hash)
        requirement = resolved.data["data"]["items"][0]
        self.assertEqual(requirement["stock_item_id"], str(self.raw_material.pk))

    def test_mapping_change_after_confirmed_issue_does_not_create_fresh_allowance(self):
        fabric_material = FabricMaterial.objects.create(
            material_name="已领料映射面料",
            inventory_raw_material=self.raw_material,
        )
        self.bom_line.raw_values = {"source_fabric_material_id": str(fabric_material.pk)}
        self.bom_line.save(update_fields=["raw_values", "updated_at"])
        created = self._create_issue(quantity="120.0000")
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        replacement = RawMaterialInformation.objects.create(
            material_number="MAT-ISSUE-002",
            item_type="MATERIAL",
            category=self.raw_material.category,
            material_name="领料替换原料",
            specification="Φ25×1.0",
            unit=self.raw_material.unit,
            material="替换管",
            warehouse_number="CK-ISSUE",
            warehouse_name="领料测试仓",
        )
        fabric_material.inventory_raw_material = replacement
        fabric_material.save(update_fields=["inventory_raw_material", "updated_at"])

        requirements = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(requirements.status_code, 200, requirements.data)
        self.assertEqual(requirements.data["data"]["items"], [])
        self.assertEqual(
            requirements.data["data"]["blockers"][0]["code"],
            "MATERIAL_MAPPING_CHANGE_AFTER_ISSUE",
        )
        original_requirement = OrderMaterialRequirement.objects.get(
            production_task=self.task,
            raw_material=self.raw_material,
        )
        self.assertEqual(original_requirement.internal_issued_quantity, Decimal("120"))
        self.assertFalse(
            OrderMaterialRequirement.objects.filter(
                production_task=self.task,
                raw_material=replacement,
            ).exists()
        )

    def test_new_bom_version_cannot_remove_material_with_confirmed_issue(self):
        created = self._create_issue(quantity="120.0000")
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        confirmed = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        Bom.objects.create(
            bom_number="BOM-MAT-ISSUE-2",
            production_task=self.task,
            product_line=self.product_line,
            version_number=2,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code,
            product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification,
            order_quantity=Decimal("500"),
            quantity_difference=Decimal("0"),
            section_count=0,
            line_count=0,
            created_by_employee=self.employee,
        )

        response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(self.workshop.pk),
            },
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["items"], [])
        self.assertEqual(response.data["data"]["blockers"][0]["code"], "REQUIREMENT_REMOVED_AFTER_ISSUE")
        sewing_response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(Workshop.objects.get(name="车缝车间").pk),
            },
        )
        self.assertEqual(sewing_response.status_code, 200, sewing_response.data)
        self.assertEqual(
            sewing_response.data["data"]["blockers"][0]["code"],
            "REQUIREMENT_REMOVED_AFTER_ISSUE",
        )

    def test_create_requires_work_plan_source(self):
        self.user.user_permissions.remove(
            Permission.objects.get(codename="view_all_materialissue", content_type__app_label="material_issues")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/material-issues/",
            {"client_request_id": str(uuid.uuid4()), "remark": "稍后补齐"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("必须从作业计划发起", str(response.data))
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, Decimal("600"))

    def test_submit_does_not_deduct_and_confirm_deducts_once(self):
        created = self._create_issue()
        issue_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/material-issues/{issue_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["data"]["status"], MaterialIssueStatus.PENDING_REVIEW)
        balance = MaterialStockBalance.objects.get(raw_material=self.raw_material)
        self.assertEqual(balance.quantity, Decimal("600"))

        request_id = str(uuid.uuid4())
        confirmed = self.client.post(
            f"/api/v1/material-issues/{issue_id}/confirm-issue/",
            {"request_id": request_id},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal("480"))
        requirement = OrderMaterialRequirement.objects.get(production_task=self.task, raw_material=self.raw_material)
        self.assertEqual(requirement.internal_issued_quantity, Decimal("120"))
        issue_history = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/order-issues/")
        self.assertEqual(issue_history.status_code, 200, issue_history.data)
        self.assertEqual(issue_history.data["data"][0]["material_issue_id"], issue_id)
        self.assertEqual(issue_history.data["data"][0]["issued_quantity"], "120.0000")

        retried = self.client.post(
            f"/api/v1/material-issues/{issue_id}/confirm-issue/",
            {"request_id": request_id},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(retried.status_code, 200, retried.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal("480"))

        stale_second_request = self.client.post(
            f"/api/v1/material-issues/{issue_id}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(stale_second_request.status_code, 412, stale_second_request.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal("480"))

        snapshot_keys = (
            "required_quantity",
            "internal_issued_quantity",
            "outsourcing_issued_quantity",
            "order_remaining",
            "available_stock",
            "max_issue_quantity",
        )
        first_issue_snapshot = {
            key: confirmed.data["data"]["lines"][0][key]
            for key in snapshot_keys
        }
        second_created = self._create_issue(quantity="50")
        second_submitted = self.client.post(
            f"/api/v1/material-issues/{second_created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=second_created["ETag"],
        )
        self.assertEqual(second_submitted.status_code, 200, second_submitted.data)
        second_confirmed = self.client.post(
            f"/api/v1/material-issues/{second_created.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=second_submitted["ETag"],
        )
        self.assertEqual(second_confirmed.status_code, 200, second_confirmed.data)
        requirement.refresh_from_db()
        self.assertEqual(requirement.internal_issued_quantity, Decimal("170"))

        first_issue_after_second_outbound = self.client.get(f"/api/v1/material-issues/{issue_id}/")
        self.assertEqual(first_issue_after_second_outbound.status_code, 200, first_issue_after_second_outbound.data)
        self.assertEqual(
            {
                key: first_issue_after_second_outbound.data["data"]["lines"][0][key]
                for key in snapshot_keys
            },
            first_issue_snapshot,
        )

    def test_pending_review_quantity_is_visible_and_reserves_order_allowance(self):
        first_created = self._create_issue(quantity="120")
        first_submitted = self.client.post(
            f"/api/v1/material-issues/{first_created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=first_created["ETag"],
        )
        self.assertEqual(first_submitted.status_code, 200, first_submitted.data)

        draft = self._create_issue(quantity="30")
        requirement = self._requirements()
        self.assertEqual(requirement["internal_issued_quantity"], "0.0000")
        self.assertEqual(requirement["pending_issue_quantity"], "120.0000")
        self.assertEqual(requirement["order_remaining"], "380.0000")
        self.assertEqual(requirement["max_issue_quantity"], "380.0000")
        self.assertEqual(MaterialIssue.objects.get(pk=draft.data["data"]["id"]).status, MaterialIssueStatus.DRAFT)

        duplicate = self._create_issue(quantity="381")
        duplicate_submit = self.client.post(
            f"/api/v1/material-issues/{duplicate.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=duplicate["ETag"],
        )
        self.assertEqual(duplicate_submit.status_code, 400, duplicate_submit.data)
        self.assertIn("PENDING_ISSUE_CONFLICT", str(duplicate_submit.data))
        self.assertEqual(MaterialIssue.objects.get(pk=duplicate.data["data"]["id"]).status, MaterialIssueStatus.DRAFT)

        returned = self.client.post(
            f"/api/v1/material-issues/{first_created.data['data']['id']}/return/",
            {"reason": "释放待审核领料额度"},
            format="json",
            HTTP_IF_MATCH=first_submitted["ETag"],
        )
        self.assertEqual(returned.status_code, 200, returned.data)
        released = self._requirements()
        self.assertEqual(released["pending_issue_quantity"], "0")
        self.assertEqual(released["order_remaining"], "500.0000")

    def concurrency_pending_review_reservation_prevents_duplicate_submit(self):
        first_created = self._create_issue(quantity="300")
        second_created = self._create_issue(quantity="300")
        barrier = threading.Barrier(2)
        results = []

        def worker(issue_id, etag):
            connections.close_all()
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            barrier.wait(timeout=5)
            response = client.post(
                f"/api/v1/material-issues/{issue_id}/submit/",
                {},
                format="json",
                HTTP_IF_MATCH=etag,
            )
            results.append((response.status_code, str(response.data)))
            connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(first_created.data["data"]["id"], first_created["ETag"])),
            threading.Thread(target=worker, args=(second_created.data["data"]["id"], second_created["ETag"])),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(status for status, _ in results), [200, 400])
        self.assertEqual(MaterialIssue.objects.filter(status=MaterialIssueStatus.PENDING_REVIEW).count(), 1)
        self.assertTrue(any("PENDING_ISSUE_CONFLICT" in body for status, body in results if status == 400))

    def test_confirm_rechecks_recipient_active_state_before_stock_write(self):
        created = self._create_issue()
        issue_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/material-issues/{issue_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.recipient.status = WorkshopEmployeeStatus.LEFT
        self.recipient.save(update_fields=["status", "updated_at"])

        rejected = self.client.post(
            f"/api/v1/material-issues/{issue_id}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, Decimal("600"))
        self.assertEqual(MaterialIssue.objects.get(pk=issue_id).status, MaterialIssueStatus.PENDING_REVIEW)

    def test_changing_product_without_rebuilding_lines_is_rejected(self):
        created = self._create_issue()

        rejected = self.client.patch(
            f"/api/v1/material-issues/{created.data['data']['id']}/",
            {"product_line_id": None},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(rejected.status_code, 400, rejected.data)
        issue = MaterialIssue.objects.get(pk=created.data["data"]["id"])
        self.assertEqual(issue.product_line_id, self.product_line.pk)
        self.assertEqual(issue.lines.count(), 1)

    def test_confirm_uses_auditable_stable_allocation_across_multiple_zones(self):
        created = self._create_issue()
        first_balance = MaterialStockBalance.objects.get(raw_material=self.raw_material)
        first_balance.quantity = Decimal("50")
        first_balance.save(update_fields=["quantity", "updated_at"])
        second_zone = WarehouseZone.objects.create(
            warehouse=self.warehouse,
            zone_name="二楼",
            status=RecordStatus.ACTIVE,
        )
        MaterialStockBalance.objects.create(
            raw_material=self.raw_material,
            zone=second_zone,
            unit=self.raw_material.unit,
            quality=MaterialStockQuality.AVAILABLE,
            quantity=Decimal("100"),
        )
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        confirmed = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )

        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balances = MaterialStockBalance.objects.filter(raw_material=self.raw_material)
        self.assertEqual(sum((item.quantity for item in balances), Decimal("0")), Decimal("30"))
        movements = MaterialStockMovement.objects.filter(
            source_type="MATERIAL_ISSUE",
            source_id=created.data["data"]["id"],
        ).order_by("balance__zone_id")
        self.assertEqual(movements.count(), 2)
        self.assertTrue(all(item.snapshot["allocation_policy"] == "ZONE_ID_ASC" for item in movements))

    def test_semi_finished_requirement_uses_independent_balance_and_confirm_deducts_it(self):
        craft = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="领料测试委外喷塑",
            outsourcing_code=OutsourcingCode.POWDER_COATING,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        warehouse = Warehouse.objects.create(
            warehouse_number="CKSEMIISSUE",
            warehouse_name="领料测试半成品仓",
            warehouse_type=WarehouseType.SEMI_FINISHED,
            status=RecordStatus.ACTIVE,
        )
        zone = WarehouseZone.objects.create(
            warehouse=warehouse,
            zone_name="半成品一区",
            status=RecordStatus.ACTIVE,
        )
        semi_balance = SemiFinishedStockBalance.objects.create(
            production_task=self.task,
            product_line=self.product_line,
            bom_line=self.bom_line,
            completed_craft=craft,
            color_snapshot="哑黑",
            unit=self.product_line.unit,
            zone=zone,
            quality=MaterialStockQuality.AVAILABLE,
            quantity=Decimal("80"),
        )
        requirements = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(requirements.status_code, 200, requirements.data)
        semi = next(item for item in requirements.data["data"]["items"] if item["line_type"] == "SEMI")
        self.assertEqual(semi["requirement_id"], str(semi_balance.pk))
        self.assertEqual(semi["completed_craft"], craft.name)

        created = self.client.post(
            "/api/v1/material-issues/",
            {
                **self._plan_source(),
                "client_request_id": str(uuid.uuid4()),
                "production_task_id": str(self.task.pk),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(self.workshop.pk),
                "recipient_workshop_employee_id": str(self.recipient.pk),
                "issue_at": timezone.now().isoformat(),
                "lines": [{"requirement_id": str(semi_balance.pk), "requested_quantity": "30"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        semi_balance.refresh_from_db()
        self.assertEqual(semi_balance.quantity, Decimal("50"))
        self.assertEqual(confirmed.data["data"]["lines"][0]["line_type"], "SEMI")

    def test_return_requires_reason_and_preserves_history(self):
        created = self._create_issue()
        issue_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/material-issues/{issue_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        invalid = self.client.post(
            f"/api/v1/material-issues/{issue_id}/return/",
            {"reason": ""},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
        returned = self.client.post(
            f"/api/v1/material-issues/{issue_id}/return/",
            {"reason": "请核对本次数量"},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data["data"]["status"], MaterialIssueStatus.RETURNED)
        reasons = [item["reason"] for item in returned.data["data"]["audit_events"]]
        self.assertIn("请核对本次数量", reasons)

    def test_submit_rejects_stock_shortage_without_writes(self):
        created = self._create_issue(quantity="700.0000")
        issue_id = created.data["data"]["id"]
        response = self.client.post(
            f"/api/v1/material-issues/{issue_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "ORDER_ALLOWANCE_EXCEEDED")
        self.assertEqual(MaterialIssue.objects.get(pk=issue_id).status, MaterialIssueStatus.DRAFT)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, Decimal("600"))

    def test_user_without_review_permission_cannot_confirm_issue(self):
        created = self._create_issue()
        issue_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/material-issues/{issue_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.user.user_permissions.remove(
            Permission.objects.get(codename="review_materialissue", content_type__app_label="material_issues")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

        rejected = self.client.post(
            f"/api/v1/material-issues/{issue_id}/confirm-issue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )

        self.assertEqual(rejected.status_code, 403, rejected.data)
        self.assertEqual(rejected.data["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, Decimal("600"))

    def test_non_owner_cannot_modify_or_submit_another_users_draft(self):
        created = self._create_issue()
        other_user = get_user_model().objects.create_user(username="other_material_issue_user")
        Employee.objects.create(user=other_user, employee_code="OTHER_MI_USER", display_name="其他制单人")
        other_user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=["material_issues", "production_tasks"],
                codename__in=[
                    "view_materialissue", "change_materialissue", "submit_materialissue",
                    "view_productiontask", "view_all_productiontask",
                ],
            )
        )
        self.client.force_authenticate(other_user)

        updated = self.client.patch(
            f"/api/v1/material-issues/{created.data['data']['id']}/",
            {"remark": "越权修改"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 403, updated.data)
        self.assertEqual(submitted.status_code, 403, submitted.data)
        self.assertEqual(MaterialIssue.objects.get(pk=created.data["data"]["id"]).status, MaterialIssueStatus.DRAFT)

    def test_changed_product_quantity_blocks_stale_bom_requirement(self):
        self.product_line.quantity = Decimal("501")
        self.product_line.save(update_fields=["quantity", "updated_at"])

        response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("BOM_QUANTITY_STALE", {item["code"] for item in response.data["data"]["blockers"]})
        self.assertEqual(response.data["data"]["items"], [])


class MaterialIssueConcurrencyTests(APITransactionTestCase):
    serialized_rollback = True
    setUp = MaterialIssueApiTests.setUp
    _plan_source = MaterialIssueApiTests._plan_source
    _requirements = MaterialIssueApiTests._requirements
    _create_issue = MaterialIssueApiTests._create_issue

    test_concurrent_create_with_same_request_id_returns_same_issue = (
        MaterialIssueApiTests.concurrency_create_with_same_request_id_returns_same_issue
    )
    test_concurrent_create_with_same_request_id_and_different_payload_conflicts = (
        MaterialIssueApiTests.concurrency_create_with_same_request_id_and_different_payload_conflicts
    )
    test_pending_review_reservation_prevents_duplicate_submit = (
        MaterialIssueApiTests.concurrency_pending_review_reservation_prevents_duplicate_submit
    )
    test_confirm_waits_for_bom_change_and_does_not_deduct_stale_material = (
        MaterialIssueApiTests.concurrency_confirm_waits_for_bom_change_and_does_not_deduct_stale_material
    )
