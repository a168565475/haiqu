from apps.workshop_config.tests.factories import production_employee
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomSectionType, BomStatus
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.organizations.models import Employee
from apps.products.models import ProductInformation
from apps.production_scheduling.models import (
    ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus,
)
from apps.production_tasks.models import DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.reference_data.models import Currency, NumberRule, ProductCategory, ProductColor, ProductItem, ProductionUnit
from apps.workshop_config.models import Craft, CraftType, Operation, PlanCategory, Workshop

from ..models import (
    WageScheme, WageSchemeLine, WageSchemeStatus, WorkReport, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus,
)


class WorkshopReportingApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="wage-admin", password="test")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="WAGE-ADMIN", display_name="工价测试管理员"
        )
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.customer = CustomerAccount.objects.create(
            account_code="WAGE-CUSTOMER", account_name="工价测试客户", primary_country_code="CN"
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer, employee=self.employee, assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        self.currency, _ = Currency.objects.get_or_create(
            code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"}
        )
        for number_type, chinese_name, prefix, sequence_name, sort_order in (
            ("WAGE_SCHEME", "工价方案编号", "GJ", "haiqu_wage_scheme_seq", 73),
            ("WORK_REPORT", "计件报工编号", "BG", "haiqu_work_report_seq", 74),
        ):
            NumberRule.objects.update_or_create(
                number_type=number_type,
                defaults={
                    "chinese_name": chinese_name, "prefix": prefix,
                    "format_pattern": "{prefix}-{date}-{sequence}", "sequence_name": sequence_name,
                    "sequence_padding": 6, "date_granularity": "MONTH", "reset_policy": "NEVER",
                    "is_configured": True, "sort_order": sort_order, "status": "ACTIVE",
                },
            )
        self.unit = ProductionUnit.objects.create(unit_code="WG-PCS", unit_name="工价测试件")
        category = ProductCategory.objects.create(category_name="工价测试成品", item_type="FINISHED")
        item = ProductItem.objects.create(item_number="WG-ITEM", category=category)
        product = ProductInformation.objects.create(
            product_number="WG-PRODUCT", product_code="WG-CODE", category=category, product_name="工价测试产品",
            specification="100x100", unit=self.unit, product_item=item, scale="REGULAR",
        )
        color = ProductColor.objects.create(color_card="WG", color_code="001", color_name="工价测试色")
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT-WG-001", contract_number="WG-CONTRACT-001", order_source=OrderSource.NEW,
            order_number="WG-ORDER-001", customer_account=self.customer, order_date=today,
            delivery_date=today + timedelta(days=30), salesperson=self.employee, currency=self.currency,
            includes_tax=True, order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, planned_start_date=today,
            planned_end_date=today + timedelta(days=20), created_by_employee=self.employee,
        )
        self.task.followers.add(self.employee)
        self.product_line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=product,
            product_number_snapshot=product.product_number, product_code_snapshot=product.product_code,
            item_number_snapshot=item.item_number, product_name_snapshot=product.product_name,
            specification_snapshot=product.specification, product_color=color,
            color_card_snapshot=color.color_card, color_name_snapshot=color.color_name,
            color_code_snapshot=color.color_code, quantity=100, unit=self.unit, currency=self.currency,
            unit_price=Decimal("10"), total_amount=Decimal("1000"), exchange_rate=Decimal("1"),
        )
        self.workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        self.craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=self.workshop, name="工价测试金工",
            plan_category=PlanCategory.METAL,
        )
        self.operation = Operation.objects.create(
            operation_number="WG-OP-001", product_name="工价测试产品", craft=self.craft,
            name="切管", reporting_unit=self.unit,
        )
        self.worker = production_employee(
            workshop=self.workshop, position="操作工", name="计件员工甲", is_supervisor=False,
        )
        self.schedule = ProductionSchedule.objects.create(
            schedule_number="PC-WG-001", production_task=self.task, record_status=ScheduleStatus.ACTIVE,
            version=1, source_snapshot={"task_number": self.task.task_number}, source_revision_hash="a" * 64,
            client_request_id=uuid.uuid4(), request_payload_hash="b" * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        self.schedule_product = ProductionScheduleProduct.objects.create(
            schedule=self.schedule, product_line=self.product_line, line_number=1, planned_quantity=100,
            source_quantity_snapshot=100, unit=self.unit, unit_name_snapshot=self.unit.unit_name,
            material_inbound_date=today, metal_return_date=today + timedelta(days=1),
            sewing_return_date=today + timedelta(days=2), finished_inbound_date=today + timedelta(days=3),
            product_snapshot={"product_name": product.product_name}, source_revision_hash="c" * 64,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
        )
        self.bom = Bom.objects.create(
            bom_number="BOM-WG-BASE", production_task=self.task, product_line=self.product_line,
            version_number=1, creation_method=BomCreationMethod.BLANK, status=BomStatus.VERIFIED,
            product_number_snapshot=self.product_line.product_number_snapshot,
            product_name_snapshot=self.product_line.product_name_snapshot,
            specification_snapshot=self.product_line.specification_snapshot,
            order_quantity=self.product_line.quantity,
        )
        self.bom_profile_section = BomSection.objects.create(
            bom=self.bom, line_number=1, section_type=BomSectionType.PROFILE, title="管材类",
        )
        self.metal_bom_line = BomLine.objects.create(
            section=self.bom_profile_section, line_number=1,
            part_name="前脚管", material="铁", specification="20*1.0*500",
            cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=10,
            raw_bar_length_m="6.00", suggested_bar_count=20, suggested_purchase_meters="120.00",
        )
        self.task.status = ProductionTaskStatus.IN_PRODUCTION
        self.task.save(update_fields=["status", "updated_at"])

    def scheme_payload(self):
        return {
            "product_line_id": str(self.product_line.pk), "schedule_product_id": str(self.schedule_product.pk),
            "workshop_id": str(self.workshop.pk), "craft_ids": [str(self.craft.pk)],
            "operation_product_name": "工价测试产品", "remark": "测试方案",
            "lines": [{
                "craft_id": str(self.craft.pk), "operation_id": str(self.operation.pk),
                "bom_line_id": str(self.metal_bom_line.pk), "counting_mode": "PIECE",
                "display_name": "前脚管-铁-20*1.0*500", "production_description": "按定位线精准下料",
                "previous_price": "2.0000", "revised_price": "2.2000",
                "declared_price": "2.3450", "status": "ACTIVE", "note": "首件确认后批量制作",
            }],
        }

    def create_approved_scheme(self):
        created = self.client.post("/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/submit/", {}, format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        approved = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/approve/",
            {"effective_from": timezone.localdate().isoformat()}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        return approved

    def test_scheme_approval_defaults_to_server_date_when_date_is_omitted(self):
        created = self.client.post("/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)

        approved = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/approve/",
            {}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )

        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["data"]["effective_from"], timezone.localdate())

    def test_scheme_approval_and_report_are_real_and_idempotent(self):
        approved = self.create_approved_scheme()
        self.assertRegex(approved.data["data"]["scheme_number"], r"^GJ-\d{6}-\d{6,}$")
        self.assertEqual(approved.data["data"]["lines"][0]["production_description"], "按定位线精准下料")
        self.assertEqual(approved.data["data"]["lines"][0]["note"], "首件确认后批量制作")
        request_id = str(uuid.uuid4())
        payload = {
            "client_request_id": request_id, "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk), "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk), "quantity": "150.0000",
            }],
        }
        first = self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["data"]["total_amount"], "351.75")
        self.assertEqual(WorkReport.objects.count(), 1)
        repeated = self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(WorkReport.objects.count(), 1)
        changed = {**payload, "lines": [{**payload["lines"][0], "quantity": "151.0000"}]}
        conflict = self.client.post("/api/v1/workshop-reporting/work-reports/", changed, format="json")
        self.assertEqual(conflict.status_code, 409, conflict.data)
        line = WorkReportLine.objects.get()
        self.assertEqual(line.unit_price_snapshot, Decimal("2.3450"))
        self.assertEqual(line.quantity, Decimal("150.0000"))
        self.assertEqual(line.order_quantity_snapshot, self.product_line.quantity)
        report = WorkReport.objects.get()
        self.assertEqual(report.task_number_snapshot, "HT-WG-001")
        self.assertEqual(report.product_name_snapshot, "工价测试产品")
        self.task.task_number = "HT-WG-CHANGED"
        self.task.save(update_fields=["task_number", "updated_at"])
        self.employee.display_name = "已改名管理员"
        self.employee.save(update_fields=["display_name", "updated_at"])
        detail = self.client.get(f"/api/v1/workshop-reporting/work-reports/{report.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["production_task"]["task_number"], "HT-WG-001")
        self.assertEqual(detail.data["data"]["product"]["name"], "工价测试产品")
        self.assertEqual(detail.data["data"]["recorder"], "工价测试管理员")

    def test_reporting_context_includes_readonly_production_order(self):
        response = self.client.get(
            "/api/v1/workshop-reporting/context/",
            {"schedule_product_id": str(self.schedule_product.pk)},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["schedule_product"]["order_number"], "WG-ORDER-001")
        self.assertEqual(response.data["data"]["schedule_product"]["product_code"], self.product_line.product_code_snapshot)
        self.assertEqual(response.data["data"]["schedule_product"]["product_specification"], self.product_line.specification_snapshot)
        self.assertEqual(response.data["data"]["schedule_product"]["product_color"], self.product_line.color_name_snapshot)
        listed = next(
            item for item in response.data["data"]["schedule_products"]
            if item["id"] == str(self.schedule_product.pk)
        )
        self.assertEqual(listed["order_number"], "WG-ORDER-001")
        self.assertEqual(listed["product_code"], self.product_line.product_code_snapshot)

    def test_metal_context_uses_all_craft_operations_and_verified_bom_parts(self):
        other_operation = Operation.objects.create(
            operation_number="WG-OP-002", product_name="另一个目录品名", craft=self.craft,
            name="弯管", reporting_unit=self.unit,
        )
        BomLine.objects.create(
            section=self.bom_profile_section, line_number=2,
            part_name="前脚管", material="铁-中光", specification="20*1.0*500",
            cutting_length_mm=500, pieces_per_product=3, pieces_per_bar=10,
            raw_bar_length_m="6.00", suggested_bar_count=30, suggested_purchase_meters="180.00",
        )

        context = self.client.get(
            "/api/v1/workshop-reporting/context/",
            {"schedule_product_id": str(self.schedule_product.pk)},
        )

        self.assertEqual(context.status_code, 200, context.data)
        selected_craft = next(item for item in context.data["data"]["crafts"] if item["id"] == str(self.craft.pk))
        self.assertEqual(selected_craft["plan_category"], PlanCategory.METAL)
        self.assertEqual(
            context.data["data"]["schedule_product"]["order_quantity"],
            str(self.schedule_product.source_quantity_snapshot),
        )
        selected_bom = next(
            item for item in context.data["data"]["bom_items"]
            if item["id"] == str(self.metal_bom_line.pk)
        )
        self.assertEqual(selected_bom["label"], "前脚管-铁-20*1.0*500")
        self.assertEqual(selected_bom["material"], "铁")
        self.assertEqual(
            sorted(item["label"] for item in context.data["data"]["bom_items"]),
            ["前脚管-铁-20*1.0*500", "前脚管-铁-中光-20*1.0*500"],
        )
        self.assertEqual(selected_bom["pieces_per_product"], 2)
        self.assertEqual(selected_bom["source_type"], PlanCategory.METAL)

        payload = self.scheme_payload()
        payload.pop("operation_product_name")
        payload["lines"][0]["operation_id"] = str(other_operation.pk)
        payload["lines"][0]["display_name"] = "前脚管-铁-20*1.0*500"
        created = self.client.post("/api/v1/workshop-reporting/wage-schemes/", payload, format="json")

        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["operation_product_name"], self.craft.name)
        self.assertEqual(created.data["data"]["lines"][0]["operation_id"], str(other_operation.pk))
        self.assertEqual(created.data["data"]["lines"][0]["display_name"], "前脚管-铁-20*1.0*500")
        self.assertEqual(created.data["data"]["lines"][0]["required_quantity"], "200.0000")

    def test_metal_scheme_rejects_name_outside_verified_bom(self):
        payload = self.scheme_payload()
        payload["lines"][0]["bom_line_id"] = str(uuid.uuid4())

        response = self.client.post("/api/v1/workshop-reporting/wage-schemes/", payload, format="json")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("BOM", str(response.data))

    def test_scheme_rejects_more_than_one_craft(self):
        other_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=self.workshop, name="工价测试第二工艺",
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=other_craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=other_craft.name,
        )
        payload = self.scheme_payload()
        payload["craft_ids"].append(str(other_craft.pk))

        response = self.client.post("/api/v1/workshop-reporting/wage-schemes/", payload, format="json")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("只能选择一项工艺", str(response.data))

    def test_scheme_update_cannot_rename_existing_work_item(self):
        created = self.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        replacement = BomLine.objects.create(
            section=self.bom_profile_section, line_number=2,
            part_name="后脚管", material="铁", specification="22*1.0*520",
            cutting_length_mm=520, pieces_per_product=2, pieces_per_bar=10,
            raw_bar_length_m="6.00", suggested_bar_count=20, suggested_purchase_meters="120.00",
        )
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = created.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["bom_line_id"] = str(replacement.pk)
        payload["lines"][0]["display_name"] = "后脚管-铁-22*1.0*520"

        response = self.client.patch(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/",
            payload, format="json", HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不能把原工作项改为其他 BOM 名称/部位", str(response.data))

    def test_permissions_etag_unit_and_line_rules(self):
        created = self.client.post("/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json")
        missing_etag = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/submit/", {}, format="json"
        )
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        void_payload = self.scheme_payload(); void_payload["lines"][0]["status"] = "VOID"
        void_draft = self.client.patch(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/",
            void_payload, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(void_draft.status_code, 200, void_draft.data)
        void_blocked = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{void_draft.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=void_draft["ETag"],
        )
        self.assertEqual(void_blocked.status_code, 400, void_blocked.data)
        self.operation.reporting_unit = None; self.operation.save(update_fields=["reporting_unit", "updated_at"])
        BomLine.objects.create(
            section=self.bom_profile_section, line_number=2,
            part_name="后脚管", specification="22*1.0*520",
        )
        draft_payload = self.scheme_payload()
        draft_payload["lines"][0]["display_name"] = "后脚管-22*1.0*520"
        draft = self.client.patch(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/",
            draft_payload, format="json", HTTP_IF_MATCH=void_draft["ETag"],
        )
        self.assertEqual(draft.status_code, 200, draft.data)
        submitted_without_unit = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/submit/", {}, format="json",
            HTTP_IF_MATCH=draft["ETag"],
        )
        self.assertEqual(submitted_without_unit.status_code, 200, submitted_without_unit.data)
        other_user = get_user_model().objects.create_user(username="wage-no-approve")
        Employee.objects.create(user=other_user, employee_code="WAGE-NO-APPROVE", display_name="无审批权限")
        other_user.user_permissions.set(Permission.objects.filter(codename="view_wagescheme"))
        other = APIClient(); other.force_authenticate(other_user)
        forbidden = other.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/approve/",
            {"effective_from": timezone.localdate().isoformat()}, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.data)

    def test_day_summary_matches_detail_and_report_does_not_touch_inventory(self):
        approved = self.create_approved_scheme()
        plan_statuses = self.client.get(
            "/api/v1/workshop-reporting/plan-wage-statuses/",
            {
                "schedule_product_ids": str(self.schedule_product.pk),
                "production_date": timezone.localdate().isoformat(), "plan_category": "METAL",
            },
        )
        self.assertEqual(plan_statuses.status_code, 200, plan_statuses.data)
        self.assertTrue(plan_statuses.data["data"][0]["can_report"])
        self.assertEqual(plan_statuses.data["data"][0]["scheme_id"], approved.data["data"]["id"])
        self.assertEqual(plan_statuses.data["data"][0]["estimated_wage"], "469.0000")
        payload = {
            "client_request_id": str(uuid.uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk), "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [
                {"scheme_line_id": approved.data["data"]["lines"][0]["id"], "workshop_employee_id": str(self.worker.pk), "quantity": "3.0000"},
                {"scheme_line_id": approved.data["data"]["lines"][0]["id"], "workshop_employee_id": str(self.worker.pk), "quantity": "2.0000"},
            ],
        }
        self.product_line.quantity = 999
        self.product_line.save(update_fields=["quantity", "updated_at"])
        self.assertEqual(self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json").status_code, 201)
        days = self.client.get("/api/v1/workshop-reporting/work-report-days/")
        self.assertEqual(days.status_code, 200, days.data)
        self.assertEqual(days.data["data"][0]["total_amount"], "11.73")
        self.assertEqual(days.data["data"][0]["line_count"], 2)
        filtered_days = self.client.get(
            "/api/v1/workshop-reporting/work-report-days/",
            {"schedule_product_id": str(self.schedule_product.pk), "workshop_id": str(self.workshop.pk)},
        )
        self.assertEqual(filtered_days.status_code, 200, filtered_days.data)
        self.assertEqual(filtered_days.data["meta"]["total"], 1)
        wrong_workshop_days = self.client.get(
            "/api/v1/workshop-reporting/work-report-days/",
            {"schedule_product_id": str(self.schedule_product.pk), "workshop_id": str(uuid.uuid4())},
        )
        self.assertEqual(wrong_workshop_days.status_code, 200, wrong_workshop_days.data)
        self.assertEqual(wrong_workshop_days.data["meta"]["total"], 0)
        empty_days = self.client.get(
            "/api/v1/workshop-reporting/work-report-days/",
            {"schedule_product_id": str(uuid.uuid4())},
        )
        self.assertEqual(empty_days.status_code, 200, empty_days.data)
        self.assertEqual(empty_days.data["meta"]["total"], 0)
        detail = self.client.get(f"/api/v1/workshop-reporting/work-report-days/{timezone.localdate().isoformat()}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"][0]["total_amount"], "11.73")
        self.assertEqual(detail.data["data"][0]["lines"][0]["order_quantity_snapshot"], 100)
        self.assertEqual(detail.data["data"][0]["lines"][0]["cumulative_quantity"], "5.0000")
        self.assertEqual(detail.data["data"][0]["lines"][0]["required_quantity"], "200.0000")
        self.metal_bom_line.pieces_per_product = 9
        self.metal_bom_line.save(update_fields=["pieces_per_product", "updated_at"])
        stable_detail = self.client.get(
            f"/api/v1/workshop-reporting/work-report-days/{timezone.localdate().isoformat()}/"
        )
        self.assertEqual(stable_detail.data["data"][0]["lines"][0]["required_quantity"], "200.0000")
        filtered_detail = self.client.get(
            f"/api/v1/workshop-reporting/work-report-days/{timezone.localdate().isoformat()}/",
            {"schedule_product_id": str(self.schedule_product.pk)},
        )
        self.assertEqual(filtered_detail.status_code, 200, filtered_detail.data)
        self.assertEqual(filtered_detail.data["meta"]["total"], 1)
        empty_detail = self.client.get(
            f"/api/v1/workshop-reporting/work-report-days/{timezone.localdate().isoformat()}/",
            {"schedule_product_id": str(uuid.uuid4())},
        )
        self.assertEqual(empty_detail.status_code, 200, empty_detail.data)
        self.assertEqual(empty_detail.data["meta"]["total"], 0)
        price_context = self.client.get(
            "/api/v1/workshop-reporting/work-reports/price-context/",
            {
                "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
                "schedule_product_id": str(self.schedule_product.pk),
                "craft_id": str(self.craft.pk),
                "production_date": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(price_context.status_code, 200, price_context.data)
        self.assertEqual(price_context.data["data"]["lines"][0]["production_date_quantity"], "5.0000")
        self.assertEqual(price_context.data["data"]["lines"][0]["cumulative_quantity"], "5.0000")
        self.assertEqual(
            price_context.data["data"]["lines"][0]["last_workshop_employee_id"], str(self.worker.pk)
        )
        self.assertEqual(self.task.status, ProductionTaskStatus.IN_PRODUCTION)
        self.assertEqual(WageScheme.objects.get(pk=approved.data["data"]["id"]).status, WageSchemeStatus.APPROVED)

    def test_work_report_rejects_fractional_completion_count(self):
        approved = self.create_approved_scheme()
        response = self.client.post(
            "/api/v1/workshop-reporting/work-reports/",
            {
                "client_request_id": str(uuid.uuid4()),
                "production_date": timezone.localdate().isoformat(),
                "schedule_product_id": str(self.schedule_product.pk),
                "scheme_id": approved.data["data"]["id"],
                "scheme_revision": approved.data["data"]["revision"],
                "lines": [{
                    "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                    "workshop_employee_id": str(self.worker.pk),
                    "quantity": "0.5000",
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(WorkReport.objects.count(), 0)

    def test_last_report_requires_confirmation_and_completes_only_current_plan(self):
        approved = self.create_approved_scheme()
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk),
            "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk),
                "quantity": "200",
            }],
        }
        blocked = self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertEqual(WorkReport.objects.count(), 0)

        payload["confirm_plan_completion"] = True
        completed = self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(completed.status_code, 201, completed.data)
        self.assertTrue(completed.data["data"]["completed_plan"])
        execution = WorkshopPlanExecution.objects.get(
            schedule_product=self.schedule_product, craft=self.craft,
        )
        self.assertEqual(execution.status, WorkshopPlanStatus.COMPLETED)
        status_response = self.client.get("/api/v1/workshop-reporting/plan-wage-statuses/", {
            "schedule_product_ids": str(self.schedule_product.pk),
            "production_date": timezone.localdate().isoformat(),
            "plan_category": PlanCategory.METAL,
        })
        self.assertEqual(status_response.data["data"][0]["progress_percent"], 100)
        self.assertEqual(status_response.data["data"][0]["plan_status"], WorkshopPlanStatus.COMPLETED)
        self.assertFalse(status_response.data["data"][0]["can_report"])

    def test_sewing_required_quantity_supports_set_and_piece_modes(self):
        sewing_workshop, _ = Workshop.objects.get_or_create(name="车缝车间")
        sewing_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=sewing_workshop,
            name="工价测试车缝", plan_category=PlanCategory.SEWING,
        )
        set_operation = Operation.objects.create(
            operation_number="WG-SEW-SET", product_name="布套", craft=sewing_craft,
            name="整套车缝", reporting_unit=self.unit,
        )
        piece_operation = Operation.objects.create(
            operation_number="WG-SEW-PIECE", product_name="布套", craft=sewing_craft,
            name="裁片车缝", reporting_unit=self.unit,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=sewing_craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=sewing_craft.name,
            plan_category=PlanCategory.SEWING,
        )
        cutting_section = BomSection.objects.create(
            bom=self.bom, line_number=2, section_type=BomSectionType.FABRIC, title="裁剪明细",
        )
        cutting_line = BomLine.objects.create(
            section=cutting_section, line_number=1, part_name="椅套", specification="A款",
            cutting_pieces_per_set=4, fabric_meters_per_piece="0.2500",
            cutting_sets_per_product=3,
        )
        payload = {
            "product_line_id": str(self.product_line.pk),
            "schedule_product_id": str(self.schedule_product.pk),
            "workshop_id": str(sewing_workshop.pk),
            "craft_ids": [str(sewing_craft.pk)],
            "operation_product_name": "布套",
            "remark": "车缝计数测试",
            "lines": [
                {
                    "craft_id": str(sewing_craft.pk), "operation_id": str(set_operation.pk),
                    "bom_line_id": str(cutting_line.pk), "display_name": "椅套-A款",
                    "counting_mode": "SET", "declared_price": "1", "status": "ACTIVE",
                },
                {
                    "craft_id": str(sewing_craft.pk), "operation_id": str(piece_operation.pk),
                    "bom_line_id": str(cutting_line.pk), "display_name": "椅套-A款",
                    "counting_mode": "PIECE", "declared_price": "1", "status": "ACTIVE",
                },
            ],
        }
        response = self.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", payload, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        lines = response.data["data"]["lines"]
        self.assertEqual(lines[0]["required_quantity"], "300.0000")
        self.assertEqual(lines[1]["required_quantity"], "1200.0000")

    def test_schedule_list_progress_has_material_placeholder_and_weighted_work_progress(self):
        approved = self.create_approved_scheme()
        progress = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk),
            "production_date": timezone.localdate().isoformat(),
        })
        self.assertEqual(progress.status_code, 200, progress.data)
        values = progress.data["data"][0]["progress"]
        self.assertEqual(values["MATERIAL"]["display"], "100%")
        self.assertEqual(values["METAL"]["display"], "0%")
        self.assertEqual(values["SEWING"]["display"], "—")
        self.assertEqual(values["ASSEMBLY"]["display"], "0%")

        report = {
            "client_request_id": str(uuid.uuid4()),
            "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk),
            "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk), "quantity": "5",
            }],
        }
        self.assertEqual(
            self.client.post("/api/v1/workshop-reporting/work-reports/", report, format="json").status_code,
            201,
        )
        refreshed = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk),
            "production_date": timezone.localdate().isoformat(),
        })
        self.assertEqual(refreshed.data["data"][0]["progress"]["METAL"]["display"], "3%")

    def test_progress_is_isolated_by_schedule_product(self):
        approved = self.create_approved_scheme()
        today = timezone.localdate()
        first_report = self.client.post(
            "/api/v1/workshop-reporting/work-reports/",
            {
                "client_request_id": str(uuid.uuid4()),
                "production_date": today.isoformat(),
                "schedule_product_id": str(self.schedule_product.pk),
                "scheme_id": approved.data["data"]["id"],
                "scheme_revision": approved.data["data"]["revision"],
                "lines": [{
                    "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                    "workshop_employee_id": str(self.worker.pk), "quantity": "5",
                }],
            },
            format="json",
        )
        self.assertEqual(first_report.status_code, 201, first_report.data)
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.version += 1
        self.schedule.void_reason = "测试重新排产"
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.updated_by_employee = self.employee
        self.schedule.save()
        self.task.status = ProductionTaskStatus.READY
        self.task.save(update_fields=["status", "updated_at"])
        second_schedule = ProductionSchedule.objects.create(
            schedule_number="PC-WG-002", production_task=self.task, record_status=ScheduleStatus.ACTIVE,
            version=1, source_snapshot={"task_number": self.task.task_number}, source_revision_hash="d" * 64,
            client_request_id=uuid.uuid4(), request_payload_hash="e" * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        second_product = ProductionScheduleProduct.objects.create(
            schedule=second_schedule, product_line=self.product_line, line_number=1, planned_quantity=100,
            source_quantity_snapshot=100, unit=self.unit, unit_name_snapshot=self.unit.unit_name,
            material_inbound_date=today, metal_return_date=today + timedelta(days=1),
            sewing_return_date=today + timedelta(days=2), finished_inbound_date=today + timedelta(days=3),
            product_snapshot={"product_name": self.product_line.product_name_snapshot},
            source_revision_hash="f" * 64,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=second_product, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
        )
        plan_statuses = self.client.get("/api/v1/workshop-reporting/plan-wage-statuses/", {
            "schedule_product_ids": str(second_product.pk),
            "production_date": today.isoformat(), "plan_category": PlanCategory.METAL,
        })
        self.assertEqual(plan_statuses.status_code, 200, plan_statuses.data)
        self.assertEqual(plan_statuses.data["data"][0]["progress_percent"], 0)

        schedule_statuses = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(second_schedule.pk),
            "production_date": today.isoformat(),
        })
        self.assertEqual(schedule_statuses.status_code, 200, schedule_statuses.data)
        self.assertEqual(schedule_statuses.data["data"][0]["progress"]["METAL"]["display"], "0%")

        second_report = self.client.post(
            "/api/v1/workshop-reporting/work-reports/",
            {
                "client_request_id": str(uuid.uuid4()),
                "production_date": today.isoformat(),
                "schedule_product_id": str(second_product.pk),
                "scheme_id": approved.data["data"]["id"],
                "scheme_revision": approved.data["data"]["revision"],
                "lines": [{
                    "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                    "workshop_employee_id": str(self.worker.pk), "quantity": "5",
                }],
            },
            format="json",
        )
        self.assertEqual(second_report.status_code, 201, second_report.data)

    def test_plan_viewer_can_read_progress_without_reporting_permissions(self):
        self.create_approved_scheme()
        plan_user = get_user_model().objects.create_user(username="plan-progress-viewer", password="test")
        Employee.objects.create(
            user=plan_user, employee_code="PLAN-PROGRESS", display_name="计划进度查看员",
        )
        plan_user.user_permissions.set(Permission.objects.filter(codename__in=[
            "view_productionschedule", "view_all_productionschedule",
        ]))
        self.client.force_authenticate(plan_user)

        response = self.client.get("/api/v1/workshop-reporting/plan-wage-statuses/", {
            "schedule_product_ids": str(self.schedule_product.pk),
            "production_date": timezone.localdate().isoformat(),
            "plan_category": PlanCategory.METAL,
        })

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["progress_percent"], 0)
        self.assertFalse(response.data["data"][0]["can_report"])

    def test_cloth_hole_is_not_a_plan_reporting_entry(self):
        response = self.client.get(
            "/api/v1/workshop-reporting/plan-wage-statuses/",
            {
                "schedule_product_ids": str(self.schedule_product.pk),
                "production_date": timezone.localdate().isoformat(),
                "plan_category": "KNOCK_HOLE",
            },
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(response.data["error"]["message"], "计划分类参数不正确。")

    def test_paused_completed_and_cancelled_tasks_allow_late_reporting(self):
        approved = self.create_approved_scheme()
        for task_status in (
            ProductionTaskStatus.PAUSED,
            ProductionTaskStatus.COMPLETED,
            ProductionTaskStatus.CANCELLED,
        ):
            self.task.status = task_status
            self.task.save(update_fields=["status", "updated_at"])
            response = self.client.post(
                "/api/v1/workshop-reporting/work-reports/",
                {
                    "client_request_id": str(uuid.uuid4()),
                    "production_date": timezone.localdate().isoformat(),
                    "schedule_product_id": str(self.schedule_product.pk),
                    "scheme_id": approved.data["data"]["id"],
                    "scheme_revision": approved.data["data"]["revision"],
                    "lines": [{
                        "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                        "workshop_employee_id": str(self.worker.pk),
                        "quantity": "1.0000",
                    }],
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, (task_status, response.data))

        self.assertEqual(WorkReport.objects.count(), 3)

    def test_work_report_can_be_directly_edited_with_etag(self):
        approved = self.create_approved_scheme()
        created = self.client.post(
            "/api/v1/workshop-reporting/work-reports/",
            {
                "client_request_id": str(uuid.uuid4()),
                "production_date": timezone.localdate().isoformat(),
                "schedule_product_id": str(self.schedule_product.pk),
                "scheme_id": approved.data["data"]["id"],
                "scheme_revision": approved.data["data"]["revision"],
                "lines": [{
                    "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                    "workshop_employee_id": str(self.worker.pk),
                    "quantity": "2.0000",
                }],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        report_id = created.data["data"]["id"]
        detail = self.client.get(f"/api/v1/workshop-reporting/work-reports/{report_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        original_etag = detail["ETag"]
        original_number = detail.data["data"]["report_number"]

        tomorrow = timezone.localdate() + timedelta(days=1)
        change_payload = self.scheme_payload()
        change_payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        change_payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        change_payload["lines"][0]["declared_price"] = "3.0000"
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            change_payload,
            format="json",
            HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=changed["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        next_version = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/approve/",
            {"effective_from": tomorrow.isoformat()},
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(next_version.status_code, 200, next_version.data)
        edit_payload = {
            "production_date": tomorrow.isoformat(),
            "schedule_product_id": str(self.schedule_product.pk),
            "scheme_id": next_version.data["data"]["id"],
            "scheme_revision": next_version.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": next_version.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk),
                "quantity": "4.0000",
            }],
        }
        missing_etag = self.client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/", edit_payload, format="json"
        )
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)

        self.task.status = ProductionTaskStatus.CANCELLED
        self.task.save(update_fields=["status", "updated_at"])
        edited = self.client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/",
            edit_payload,
            format="json",
            HTTP_IF_MATCH=original_etag,
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["data"]["report_number"], original_number)
        self.assertEqual(edited.data["data"]["recorder"], "工价测试管理员")
        self.assertEqual(edited.data["data"]["updated_by"], "工价测试管理员")
        self.assertEqual(edited.data["data"]["revision"], 2)
        self.assertEqual(edited.data["data"]["production_date"], tomorrow)
        self.assertEqual(edited.data["data"]["scheme_version"], 2)
        self.assertEqual(edited.data["data"]["total_amount"], "12.00")
        self.assertEqual(edited.data["data"]["lines"][0]["quantity"], "4.0000")
        self.assertEqual(edited.data["data"]["lines"][0]["unit_price"], "3.0000")
        self.assertEqual(WorkReport.objects.count(), 1)

        days = self.client.get("/api/v1/workshop-reporting/work-report-days/")
        self.assertEqual(days.status_code, 200, days.data)
        self.assertEqual(days.data["data"][0]["production_date"], tomorrow)
        self.assertEqual(days.data["data"][0]["last_saved_at"], edited.data["data"]["updated_at"])

        invalid_payload = deepcopy(edit_payload)
        invalid_payload["lines"].append({
            "scheme_line_id": next_version.data["data"]["lines"][0]["id"],
            "workshop_employee_id": str(uuid.uuid4()),
            "quantity": "1.0000",
        })
        invalid = self.client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/",
            invalid_payload,
            format="json",
            HTTP_IF_MATCH=edited["ETag"],
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
        unchanged = WorkReport.objects.get(pk=report_id)
        self.assertEqual(unchanged.revision, 2)
        self.assertEqual(unchanged.total_amount, Decimal("12.00"))
        self.assertEqual(list(unchanged.lines.values_list("quantity", flat=True)), [Decimal("4.0000")])

        wrong_product_payload = deepcopy(edit_payload)
        wrong_product_payload["schedule_product_id"] = str(uuid.uuid4())
        wrong_product = self.client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/",
            wrong_product_payload,
            format="json",
            HTTP_IF_MATCH=edited["ETag"],
        )
        self.assertEqual(wrong_product.status_code, 400, wrong_product.data)

        stale = self.client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/",
            edit_payload,
            format="json",
            HTTP_IF_MATCH=original_etag,
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        view_only_user = get_user_model().objects.create_user(username="wage-report-view-only")
        Employee.objects.create(
            user=view_only_user, employee_code="WAGE-REPORT-VIEW", display_name="报工只读账号"
        )
        view_only_user.user_permissions.set(Permission.objects.filter(codename__in=[
            "view_workreport", "view_all_workreport",
        ]))
        view_only_client = APIClient(); view_only_client.force_authenticate(view_only_user)
        forbidden = view_only_client.patch(
            f"/api/v1/workshop-reporting/work-reports/{report_id}/",
            edit_payload,
            format="json",
            HTTP_IF_MATCH=edited["ETag"],
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.data)

    def test_different_craft_can_have_its_own_root_scheme(self):
        self.create_approved_scheme()
        other_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=self.workshop, name="工价测试其他工艺",
        )
        other_operation = Operation.objects.create(
            operation_number="WG-OP-002", product_name="工价测试产品", craft=other_craft,
            name="钻孔", reporting_unit=self.unit,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=other_craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=other_craft.name,
        )
        payload = self.scheme_payload()
        payload["craft_ids"] = [str(other_craft.pk)]
        payload["lines"][0]["craft_id"] = str(other_craft.pk)
        payload["lines"][0]["operation_id"] = str(other_operation.pk)
        created = self.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", payload, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)

    def test_database_rejects_overlapping_approved_versions_in_same_scope(self):
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WageScheme.objects.filter(pk=changed.data["data"]["id"]).update(
                status=WageSchemeStatus.APPROVED,
                effective_from=timezone.localdate(),
                approved_by_employee=self.employee,
                approved_at=timezone.now(),
            )

    def test_second_root_draft_in_same_scope_is_rejected(self):
        first = self.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json"
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json"
        )
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(WageScheme.objects.filter(parent_scheme__isnull=True).count(), 1)

    def test_change_version_preserves_work_item_and_source_line(self):
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        self.assertEqual(changed.data["data"]["version"], 2)
        duplicate = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(duplicate.status_code, 412, duplicate.data)
        changed_line = WageSchemeLine.objects.get(scheme_id=changed.data["data"]["id"])
        self.assertEqual(str(changed_line.work_item_id), approved.data["data"]["lines"][0]["work_item_id"])
        self.assertEqual(str(changed_line.source_line_id), approved.data["data"]["lines"][0]["id"])
        self.assertEqual(changed_line.production_description, "按定位线精准下料")
        self.assertEqual(changed_line.note, "首件确认后批量制作")

    def test_scheme_list_filters_change_type_and_orders_by_updated_at(self):
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)

        result = self.client.get("/api/v1/workshop-reporting/wage-schemes/", {
            "scheme_type": "CHANGE",
            "workshop_id": str(self.workshop.pk),
            "ordering": "-updated_at",
        })
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["meta"]["total"], 1)
        self.assertEqual(result.data["data"][0]["id"], changed.data["data"]["id"])
        self.assertIsNotNone(result.data["data"][0]["parent_scheme"])

        now = timezone.now()
        WageScheme.objects.filter(pk=approved.data["data"]["id"]).update(updated_at=now - timedelta(minutes=1))
        WageScheme.objects.filter(pk=changed.data["data"]["id"]).update(updated_at=now)
        ordered = self.client.get("/api/v1/workshop-reporting/wage-schemes/", {
            "workshop_id": str(self.workshop.pk),
            "updated_from": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "updated_to": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "ordering": "-updated_at",
        })
        self.assertEqual(ordered.status_code, 200, ordered.data)
        self.assertEqual(ordered.data["meta"]["total"], 2)
        self.assertEqual(ordered.data["data"][0]["id"], changed.data["data"]["id"])
        self.assertEqual(ordered.data["data"][1]["id"], approved.data["data"]["id"])

    def test_change_approval_same_day_supersedes_previous_version(self):
        today = timezone.localdate()
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        payload["lines"][0]["declared_price"] = "3.0000"
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=changed["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        same_day = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/approve/",
            {}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(same_day.status_code, 200, same_day.data)
        previous = WageScheme.objects.get(pk=approved.data["data"]["id"])
        self.assertEqual(previous.status, WageSchemeStatus.SUPERSEDED)
        self.assertTrue(previous.events.filter(
            action="UPDATED", comment__contains="已被替代"
        ).exists())

        current_price = self.client.get("/api/v1/workshop-reporting/work-reports/price-context/", {
            "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "craft_id": str(self.craft.pk),
            "production_date": today.isoformat(),
        })
        self.assertEqual(current_price.status_code, 200, current_price.data)
        self.assertEqual(current_price.data["data"]["id"], changed.data["data"]["id"])

    def test_change_approval_closes_previous_day_and_keeps_cross_date_pricing(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        payload["lines"][0]["declared_price"] = "3.0000"
        changed = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
            payload, format="json", HTTP_IF_MATCH=approved["ETag"],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=changed["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        next_day = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/approve/",
            {"effective_from": tomorrow.isoformat()}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(next_day.status_code, 200, next_day.data)
        previous = WageScheme.objects.get(pk=approved.data["data"]["id"])
        self.assertEqual(previous.effective_to, today)
        self.assertTrue(previous.events.filter(
            action="UPDATED", comment__contains="旧版自动截止"
        ).exists())
        self.assertEqual(next_day.data["data"]["parent_scheme"]["id"], str(previous.pk))

        old_price = self.client.get("/api/v1/workshop-reporting/work-reports/price-context/", {
            "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "craft_id": str(self.craft.pk),
            "production_date": today.isoformat(),
        })
        self.assertEqual(old_price.status_code, 200, old_price.data)
        self.assertEqual(old_price.data["data"]["id"], str(previous.pk))
        new_price = self.client.get("/api/v1/workshop-reporting/work-reports/price-context/", {
            "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "craft_id": str(self.craft.pk),
            "production_date": tomorrow.isoformat(),
        })
        self.assertEqual(new_price.status_code, 200, new_price.data)
        self.assertEqual(new_price.data["data"]["id"], changed.data["data"]["id"])
        self.assertEqual(new_price.data["data"]["lines"][0]["declared_price"], "3.0000")

    def test_report_permissions_use_report_scope_not_wage_scope(self):
        approved = self.create_approved_scheme()
        report_user = get_user_model().objects.create_user(username="report-all-user")
        Employee.objects.create(user=report_user, employee_code="REPORT-ALL", display_name="全车间报工员")
        report_user.user_permissions.set(Permission.objects.filter(codename__in=[
            "add_workreport", "view_workreport", "view_all_workreport", "view_all_productiontask",
        ]))
        report_client = APIClient(); report_client.force_authenticate(report_user)
        context = report_client.get(
            "/api/v1/workshop-reporting/context/",
            {"schedule_product_id": str(self.schedule_product.pk), "purpose": "work_report"},
        )
        self.assertEqual(context.status_code, 200, context.data)
        payload = {
            "client_request_id": str(uuid.uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk), "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk), "quantity": "1.0000",
            }],
        }
        created = report_client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)

        wage_only_user = get_user_model().objects.create_user(username="wage-all-report-scoped")
        Employee.objects.create(user=wage_only_user, employee_code="WAGE-ALL-REPORT-SCOPED", display_name="仅工价全车间")
        wage_only_user.user_permissions.set(Permission.objects.filter(codename__in=[
            "add_workreport", "view_workreport", "view_all_wagescheme", "view_all_productiontask",
        ]))
        wage_only_client = APIClient(); wage_only_client.force_authenticate(wage_only_user)
        payload["client_request_id"] = str(uuid.uuid4())
        forbidden = wage_only_client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(forbidden.status_code, 403, forbidden.data)


class WorkshopReportingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        with transaction.atomic():
            WorkshopReportingApiTests.setUp(self)

    scheme_payload = WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = WorkshopReportingApiTests.create_approved_scheme

    def test_two_concurrent_changes_create_only_one_child_version(self):
        approved = self.create_approved_scheme()
        payload = self.scheme_payload()
        payload["lines"][0]["work_item_id"] = approved.data["data"]["lines"][0]["work_item_id"]
        payload["lines"][0]["previous_price"] = approved.data["data"]["lines"][0]["declared_price"]
        barrier = Barrier(2)

        def create_change():
            close_old_connections()
            client = APIClient()
            client.force_authenticate(self.user)
            try:
                barrier.wait(timeout=10)
                response = client.post(
                    f"/api/v1/workshop-reporting/wage-schemes/{approved.data['data']['id']}/change/",
                    deepcopy(payload), format="json", HTTP_IF_MATCH=approved["ETag"],
                )
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(lambda _: create_change(), range(2)))

        self.assertEqual(statuses, [201, 412])
        source = WageScheme.objects.get(pk=approved.data["data"]["id"])
        self.assertEqual(source.change_versions.count(), 1)
        self.assertEqual(source.change_versions.get().version, 2)

    def test_two_concurrent_report_edits_only_apply_one_revision(self):
        approved = self.create_approved_scheme()
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk),
            "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk),
                "quantity": "1.0000",
            }],
        }
        created = self.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        report_id = created.data["data"]["id"]
        detail = self.client.get(f"/api/v1/workshop-reporting/work-reports/{report_id}/")
        etag = detail["ETag"]
        barrier = Barrier(2)

        def edit_report(quantity):
            close_old_connections()
            client = APIClient(); client.force_authenticate(self.user)
            edit_payload = {
                "production_date": timezone.localdate().isoformat(),
                "schedule_product_id": str(self.schedule_product.pk),
                "scheme_id": approved.data["data"]["id"],
                "scheme_revision": approved.data["data"]["revision"],
                "lines": [{
                    "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                    "workshop_employee_id": str(self.worker.pk),
                    "quantity": quantity,
                }],
            }
            try:
                barrier.wait(timeout=10)
                response = client.patch(
                    f"/api/v1/workshop-reporting/work-reports/{report_id}/",
                    edit_payload,
                    format="json",
                    HTTP_IF_MATCH=etag,
                )
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(edit_report, quantity) for quantity in ("3.0000", "4.0000")]
            statuses = sorted(future.result(timeout=20) for future in futures)

        self.assertEqual(statuses, [200, 412])
        report = WorkReport.objects.get(pk=report_id)
        self.assertEqual(report.revision, 2)
        self.assertIn(report.lines.get().quantity, {Decimal("3.0000"), Decimal("4.0000")})

    def test_schedule_void_and_report_create_do_not_deadlock(self):
        approved = self.create_approved_scheme()
        schedule_detail = self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/")
        self.assertEqual(schedule_detail.status_code, 200, schedule_detail.data)
        schedule_etag = schedule_detail["ETag"]
        report_payload = {
            "client_request_id": str(uuid.uuid4()),
            "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk),
            "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{
                "scheme_line_id": approved.data["data"]["lines"][0]["id"],
                "workshop_employee_id": str(self.worker.pk),
                "quantity": "1.0000",
            }],
        }
        barrier = Barrier(2)

        def create_report():
            close_old_connections()
            client = APIClient(); client.force_authenticate(self.user)
            try:
                barrier.wait(timeout=10)
                return client.post(
                    "/api/v1/workshop-reporting/work-reports/", deepcopy(report_payload), format="json"
                ).status_code
            finally:
                connections.close_all()

        def void_current_schedule():
            close_old_connections()
            client = APIClient(); client.force_authenticate(self.user)
            try:
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/production-schedules/{self.schedule.pk}/void/",
                    {"reason": "并发锁顺序测试"},
                    format="json",
                    HTTP_IF_MATCH=schedule_etag,
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            report_future = executor.submit(create_report)
            void_future = executor.submit(void_current_schedule)
            report_status = report_future.result(timeout=20)
            void_status = void_future.result(timeout=20)

        self.assertIn(report_status, {201, 400})
        self.assertEqual(void_status, 200)
