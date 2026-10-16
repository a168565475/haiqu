import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomCreationMethod, BomStatus
from apps.core.api.concurrency import etag_for_instance
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.core.api.exceptions import Conflict
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus
from apps.products.models import ProductInformation
from apps.production_tasks.models import (
    DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskProductImage, ProductionTaskStatus,
)
from apps.reference_data.models import (
    Currency, NumberRule, ProductCategory, ProductColor, ProductItem, ProductionUnit,
)
from apps.sales_orders.models import SalesOrder, SalesOrderDeliveryBatch, SalesOrderDeliveryBatchLine, SalesOrderLine
from apps.workshop_config.models import Craft, CraftType, PlanCategory, RecordStatus, Workshop

from ..models import ProductionSchedule, ProductionScheduleProduct, ScheduleStatus
from ..services import create_schedule, create_schedule_batch, source_revision, update_schedule


def ensure_schedule_test_references():
    NumberRule.objects.update_or_create(
        number_type="PRODUCTION_SCHEDULE",
        defaults={
            "chinese_name": "生产排产单号",
            "prefix": "PC",
            "format_pattern": "{prefix}-{date}-{sequence}",
            "sequence_name": "haiqu_production_schedule_number_seq",
            "sequence_padding": 3,
            "date_granularity": "DAY",
            "reset_policy": "NEVER",
            "is_configured": True,
            "sort_order": 62,
            "status": "ACTIVE",
        },
    )
    currency, _ = Currency.objects.get_or_create(
        code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"}
    )
    category, _ = ProductCategory.objects.get_or_create(
        category_name="排产测试成品", defaults={"item_type": "FINISHED"}
    )
    unit, _ = ProductionUnit.objects.get_or_create(unit_code="SCHED-PCS", defaults={"unit_name": "排产测试件"})
    item, _ = ProductItem.objects.get_or_create(item_number="SCHED-ITEM", defaults={"category": category})
    product, _ = ProductInformation.objects.get_or_create(
        product_number="SCHED-PRODUCT-001",
        defaults={
            "product_code": "SCHED-PRODUCT-CODE", "category": category, "product_name": "排产测试产品",
            "specification": "100x100", "unit": unit, "product_item": item, "scale": "REGULAR",
        },
    )
    color, _ = ProductColor.objects.get_or_create(
        color_card="SCHED", color_code="001", color_name="排产测试色"
    )
    workshop, _ = Workshop.objects.get_or_create(name="金工车间")
    return product, currency, color, workshop


def make_schedule_prerequisites(*, task, line, employee):
    sequence = PurchaseOrder.objects.count() + 1
    bom = Bom.objects.create(
        bom_number=f"BOM-SCHEDULE-{task.task_number}-{line.line_number}",
        production_task=task,
        product_line=line,
        version_number=1,
        creation_method=BomCreationMethod.BLANK,
        status=BomStatus.VERIFIED,
        product_number_snapshot=line.product_number_snapshot,
        product_code_snapshot=line.product_code_snapshot,
        product_name_snapshot=line.product_name_snapshot,
        specification_snapshot=line.specification_snapshot,
        product_category_snapshot=line.product.category.category_name,
        order_quantity=line.quantity,
        created_by_employee=employee,
        confirmed_by_employee=employee,
        confirmed_at=timezone.now(),
    )
    purchase_order = PurchaseOrder.objects.create(
        order_number=f"CGDD20260915{sequence:02d}",
        production_task=task,
        production_task_number_snapshot=task.task_number,
        sales_order_number_snapshot=task.order_number,
        customer_name_snapshot=task.customer_account.account_name,
        source_revision="production-scheduling-test",
        status=PurchaseOrderStatus.COMPLETED,
        created_by_employee=employee,
        completed_by_employee=employee,
        completed_at=timezone.now(),
    )
    return bom, purchase_order


class ProductionSchedulingApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="schedule-user")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="SCHEDULE-USER", display_name="排产测试员工"
        )
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="production_scheduling"))
        self.customer = CustomerAccount.objects.create(
            account_code="SCHEDULE-CUSTOMER", account_name="排产测试客户", primary_country_code="CN"
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer, employee=self.employee, assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        self.product, self.currency, self.color, workshop = ensure_schedule_test_references()
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT26991", contract_number="SCHEDULE-CONTRACT-001", order_source=OrderSource.NEW,
            order_number="SCHEDULE-ORDER-001", customer_account=self.customer, order_date=today,
            delivery_date=today + timedelta(days=30), salesperson=self.employee, currency=self.currency,
            includes_tax=True, order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, planned_start_date=today + timedelta(days=3),
            planned_end_date=today + timedelta(days=20), created_by_employee=self.employee,
        )
        self.task.followers.add(self.employee)
        self.line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=self.product,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification, product_color=self.color,
            color_card_snapshot=self.color.color_card, color_name_snapshot=self.color.color_name,
            color_code_snapshot=self.color.color_code, quantity=100, unit=self.product.unit, currency=self.currency,
            unit_price=Decimal("10"), total_amount=Decimal("1000"), exchange_rate=Decimal("1"),
        )
        self.bom, self.purchase_order = make_schedule_prerequisites(
            task=self.task, line=self.line, employee=self.employee
        )
        self.internal_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=workshop, name="排产测试管材加工",
            plan_category=PlanCategory.METAL, status=RecordStatus.ACTIVE,
        )
        self.external_craft = Craft.objects.create(
            craft_type=CraftType.EXTERNAL, name="排产测试丝印", status=RecordStatus.ACTIVE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def detail(self):
        response = self.client.get(f"/api/v1/production-schedules/task-candidates/{self.task.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def payload(self, **overrides):
        source = self.detail()
        payload = {
            "production_task_id": str(self.task.pk),
            "source_revision_hash": source["source_revision_hash"],
            "client_request_id": str(uuid.uuid4()),
            "items": [{
                "product_line_id": str(self.line.pk), "planned_quantity": 80,
                "material_inbound_date": "2026-09-16", "metal_return_date": "2026-09-20",
                "sewing_return_date": "2026-09-23", "finished_inbound_date": "2026-09-26",
                "craft_ids": [str(self.internal_craft.pk), str(self.external_craft.pk)],
            }],
        }
        payload.update(overrides)
        return payload

    def create_schedule(self, payload=None):
        response = self.client.post("/api/v1/production-schedules/", payload or self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def create_task_with_product(self, task_number="HT26992"):
        today = timezone.localdate()
        task = ProductionTask.objects.create(
            task_number=task_number, contract_number=f"{task_number}-CONTRACT", order_source=OrderSource.NEW,
            order_number=f"{task_number}-ORDER", customer_account=self.customer, order_date=today,
            delivery_date=today + timedelta(days=35), salesperson=self.employee, currency=self.currency,
            includes_tax=True, order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, planned_start_date=today + timedelta(days=5),
            planned_end_date=today + timedelta(days=25), created_by_employee=self.employee,
        )
        task.followers.add(self.employee)
        line = ProductionTaskProduct.objects.create(
            production_task=task, line_number=1, product=self.product,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification, product_color=self.color,
            color_card_snapshot=self.color.color_card, color_name_snapshot=self.color.color_name,
            color_code_snapshot=self.color.color_code, quantity=60, unit=self.product.unit, currency=self.currency,
            unit_price=Decimal("10"), total_amount=Decimal("600"), exchange_rate=Decimal("1"),
        )
        make_schedule_prerequisites(task=task, line=line, employee=self.employee)
        return task, line

    def payload_for(self, task, line):
        source = self.client.get(f"/api/v1/production-schedules/task-candidates/{task.pk}/").data["data"]
        return {
            "production_task_id": str(task.pk),
            "source_revision_hash": source["source_revision_hash"],
            "client_request_id": str(uuid.uuid4()),
            "items": [{
                "product_line_id": str(line.pk), "planned_quantity": line.quantity,
                "material_inbound_date": "2026-09-16", "metal_return_date": "2026-09-20",
                "sewing_return_date": "2026-09-23", "finished_inbound_date": "2026-09-26",
                "craft_ids": [str(self.internal_craft.pk)],
            }],
        }

    def test_candidate_product_display_fields_keep_raw_source_and_revision(self):
        raw_specification = "47*55*79；加厚；颜色：酒红色；材质：PE"
        self.line.specification_snapshot = raw_specification
        self.line.color_name_snapshot = "酒红色"
        self.line.material_snapshot = "PE"
        self.line.save(update_fields=["specification_snapshot", "color_name_snapshot", "material_snapshot", "updated_at"])
        revision = source_revision(self.task, [self.line])

        candidates = self.client.get("/api/v1/production-schedules/task-candidates/")
        self.assertEqual(candidates.status_code, 200, candidates.data)
        candidate = next(row for row in candidates.data["data"] if row["id"] == str(self.task.pk))
        detail = self.detail()
        for product in [candidate["product_summaries"][0], detail["product_summaries"][0], detail["products"][0]]:
            self.assertEqual(product["specification"], raw_specification)
            self.assertEqual(product["specification_display"], "47*55*79；加厚")
            self.assertEqual(product["material"], "PE")
            self.assertEqual(product["color_name"], "酒红色")
        self.assertEqual(candidate["source_revision_hash"], revision)
        self.assertEqual(detail["source_revision_hash"], revision)
        self.line.refresh_from_db()
        self.assertEqual(self.line.specification_snapshot, raw_specification)
        self.assertEqual(self.line.material_snapshot, "PE")

    def test_candidate_product_display_keeps_unverified_suffix_and_missing_material(self):
        self.line.specification_snapshot = "47*55*79；颜色：未确认颜色；材质：未知"
        self.line.material_snapshot = ""
        self.line.save(update_fields=["specification_snapshot", "material_snapshot", "updated_at"])

        product = self.detail()["products"][0]

        self.assertEqual(product["specification_display"], self.line.specification_snapshot)
        self.assertEqual(product["material"], "")

    def test_candidate_create_detail_and_category_list_use_real_source(self):
        candidates = self.client.get("/api/v1/production-schedules/task-candidates/")
        self.assertEqual(candidates.status_code, 200, candidates.data)
        candidate = next(row for row in candidates.data["data"] if row["id"] == str(self.task.pk))
        self.assertEqual(candidate["salesperson_name"], "排产测试员工")
        self.assertEqual(candidate["follower_names"], ["排产测试员工"])
        self.assertEqual(candidate["planned_start_date"], self.task.planned_start_date)
        self.assertEqual(candidate["planned_end_date"], self.task.planned_end_date)
        self.assertEqual(candidate["product_summaries"][0]["product_name"], "排产测试产品")
        self.assertEqual(candidate["product_summaries"][0]["specification"], "100x100")
        self.assertEqual(candidate["product_summaries"][0]["color_name"], "排产测试色")
        source = self.detail()
        self.assertTrue(source["scheduling_ready"])
        self.assertTrue(source["selectable"])
        self.assertEqual(source["unselectable_reason"], "")
        self.assertEqual(source["scheduling_blockers"], [])
        self.assertEqual(source["products"][0]["bom_status"], "VERIFIED")
        self.assertEqual(source["products"][0]["bom_status_display"], "已确认")
        self.assertEqual(source["products"][0]["purchase_status"], "ORDER_COMPLETED")
        self.assertEqual(source["products"][0]["purchase_status_display"], "已完成采购")
        filtered = self.client.get("/api/v1/production-schedules/task-candidates/", {
            "customer_id": str(self.customer.pk), "product_search": "SCHED-ITEM",
            "delivery_from": self.task.delivery_date.isoformat(),
            "delivery_to": self.task.delivery_date.isoformat(),
        })
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["meta"]["total"], 1)
        invalid_date = self.client.get(
            "/api/v1/production-schedules/task-candidates/", {"delivery_from": "2026-02-30"}
        )
        self.assertEqual(invalid_date.status_code, 400, invalid_date.data)
        created = self.create_schedule()
        detail = created.data["data"]
        self.assertRegex(detail["schedule_number"], r"^PC-\d{8}-\d{3,}$")
        self.assertEqual(detail["products"][0]["planned_quantity"], 80)
        self.assertEqual(len(detail["products"][0]["crafts"]), 2)
        self.assertTrue(created.has_header("ETag"))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.IN_PRODUCTION)
        self.assertEqual(self.task.get_status_display(), "生产中")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCTION_TASK",
                object_id=self.task.pk,
                action="SCHEDULED",
            ).exists()
        )
        metal = self.client.get("/api/v1/production-schedule-items/", {"category": "METAL"})
        self.assertEqual(metal.status_code, 200, metal.data)
        self.assertEqual(metal.data["meta"]["total"], 1)
        self.assertEqual(metal.data["data"][0]["plan_date"].isoformat(), "2026-09-20")
        self.assertEqual(metal.data["data"][0]["craft_names"], ["排产测试管材加工"])
        self.assertEqual(metal.data["data"][0]["job_status"], "IN_PROGRESS")
        self.assertEqual(metal.data["data"][0]["job_status_display"], "进行中")

        ProductionTask.objects.filter(pk=self.task.pk).update(
            status=ProductionTaskStatus.COMPLETED,
            completed_at=timezone.now(),
        )
        completed = self.client.get("/api/v1/production-schedule-items/", {"category": "METAL"})
        self.assertEqual(completed.data["data"][0]["job_status"], "COMPLETED")
        self.assertEqual(completed.data["data"][0]["job_status_display"], "已完成")

    def test_create_requires_all_boms_to_be_verified(self):
        self.bom.status = BomStatus.PENDING_CONFIRMATION
        self.bom.save(update_fields=["status", "updated_at"])

        source = self.detail()
        self.assertFalse(source["scheduling_ready"])
        self.assertFalse(source["selectable"])
        self.assertIn("BOM 必须已确认", source["unselectable_reason"])
        self.assertIn("生产任务单内所有产品的 BOM 必须已确认", source["scheduling_blockers"])
        response = self.client.post("/api/v1/production-schedules/", self.payload(), format="json")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("BOM 必须已确认", response.data["error"]["message"])
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_create_requires_completed_purchase_order(self):
        self.purchase_order.status = PurchaseOrderStatus.PURCHASING
        self.purchase_order.completed_at = None
        self.purchase_order.completed_by_employee = None
        self.purchase_order.save(update_fields=[
            "status", "completed_at", "completed_by_employee", "updated_at",
        ])

        source = self.detail()
        self.assertFalse(source["scheduling_ready"])
        self.assertFalse(source["selectable"])
        self.assertIn("已完成采购", source["unselectable_reason"])
        self.assertIn("采购订单必须为“已完成采购”", source["scheduling_blockers"])
        response = self.client.post("/api/v1/production-schedules/", self.payload(), format="json")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("已完成采购", response.data["error"]["message"])
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_create_is_idempotent_and_blocks_second_active_schedule(self):
        payload = self.payload()
        first = self.create_schedule(payload)
        retry = self.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertEqual(retry.data["data"]["id"], first.data["data"]["id"])
        duplicate_payload = {**payload, "client_request_id": str(uuid.uuid4())}
        duplicate = self.client.post("/api/v1/production-schedules/", duplicate_payload, format="json")
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 1)

    def test_candidates_hide_tasks_with_active_schedule(self):
        self.create_schedule()
        candidates = self.client.get("/api/v1/production-schedules/task-candidates/")
        self.assertEqual(candidates.status_code, 200, candidates.data)
        self.assertNotIn(str(self.task.pk), {row["id"] for row in candidates.data["data"]})

    def test_batch_create_generates_one_schedule_per_task_atomically(self):
        second_task, second_line = self.create_task_with_product()
        payload = {"schedules": [self.payload(), self.payload_for(second_task, second_line)]}
        response = self.client.post("/api/v1/production-schedules/batch/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(
            {row["production_task_id"] for row in response.data["data"]},
            {str(self.task.pk), str(second_task.pk)},
        )
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 2)

        retry = self.client.post("/api/v1/production-schedules/batch/", payload, format="json")
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertEqual(
            [row["id"] for row in retry.data["data"]],
            [row["id"] for row in response.data["data"]],
        )
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 2)

        third_task, third_line = self.create_task_with_product("HT26993")
        partial_retry_payload = {
            "schedules": [payload["schedules"][0], self.payload_for(third_task, third_line)]
        }
        partial_retry = self.client.post(
            "/api/v1/production-schedules/batch/", partial_retry_payload, format="json"
        )
        self.assertEqual(partial_retry.status_code, 201, partial_retry.data)
        self.assertEqual(partial_retry.data["data"][0]["id"], response.data["data"][0]["id"])
        self.assertEqual(partial_retry.data["data"][1]["production_task_id"], str(third_task.pk))
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 3)

        fourth_task, fourth_line = self.create_task_with_product("HT26994")
        fifth_task, fifth_line = self.create_task_with_product("HT26995")
        invalid_payload = {"schedules": [
            self.payload_for(fourth_task, fourth_line),
            self.payload_for(fifth_task, fifth_line),
        ]}
        invalid_payload["schedules"][1]["items"][0]["craft_ids"] = [str(uuid.uuid4())]
        failed = self.client.post("/api/v1/production-schedules/batch/", invalid_payload, format="json")
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertFalse(ProductionSchedule.objects.filter(production_task__in=[fourth_task, fifth_task]).exists())

        sixth_task, sixth_line = self.create_task_with_product("HT26996")
        reused_request_payload = {
            **payload["schedules"][1],
            "items": [{**payload["schedules"][1]["items"][0]}],
        }
        reused_request_payload["client_request_id"] = payload["schedules"][0]["client_request_id"]
        conflict_payload = {
            "schedules": [self.payload_for(sixth_task, sixth_line), reused_request_payload]
        }
        conflict = self.client.post(
            "/api/v1/production-schedules/batch/", conflict_payload, format="json"
        )
        self.assertEqual(conflict.status_code, 409, conflict.data)
        self.assertFalse(ProductionSchedule.objects.filter(production_task=sixth_task).exists())
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 3)

    def test_batch_create_requires_add_permission(self):
        second_task, second_line = self.create_task_with_product()
        payload = {"schedules": [self.payload_for(second_task, second_line)]}
        view_only_user = get_user_model().objects.create_user(username="schedule-view-only")
        Employee.objects.create(
            user=view_only_user, employee_code="SCHEDULE-VIEW", display_name="排产只读员工"
        )
        view_only_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="production_scheduling", codename="view_productionschedule"
            )
        )
        self.client.force_authenticate(view_only_user)
        response = self.client.post("/api/v1/production-schedules/batch/", payload, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(ProductionSchedule.objects.filter(production_task=second_task).exists())

        add_only_user = get_user_model().objects.create_user(username="schedule-add-only")
        add_only_employee = Employee.objects.create(
            user=add_only_user, employee_code="SCHEDULE-ADD", display_name="排产新增员工"
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer, employee=add_only_employee,
            assignment_role="COLLABORATOR", effective_from=timezone.now(),
        )
        add_only_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="production_scheduling", codename="add_productionschedule"
            )
        )
        self.client.force_authenticate(add_only_user)
        allowed = self.client.post("/api/v1/production-schedules/batch/", payload, format="json")
        self.assertEqual(allowed.status_code, 201, allowed.data)
        self.assertEqual(allowed.data["data"][0]["production_task_id"], str(second_task.pk))

    def test_create_rejects_missing_date_empty_craft_and_excess_quantity(self):
        missing_date = self.payload()
        missing_date["items"][0].pop("metal_return_date")
        response = self.client.post("/api/v1/production-schedules/", missing_date, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        empty_craft = self.payload()
        empty_craft["items"][0]["craft_ids"] = []
        response = self.client.post("/api/v1/production-schedules/", empty_craft, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        excess = self.payload()
        excess["items"][0]["planned_quantity"] = 101
        response = self.client.post("/api/v1/production-schedules/", excess, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_edit_requires_etag_updates_parent_version_and_void_allows_replacement(self):
        create_payload = self.payload()
        created = self.create_schedule(create_payload)
        schedule_id = created.data["data"]["id"]
        update = {**create_payload, "items": [{**create_payload["items"][0]}]}
        update.pop("production_task_id")
        update.pop("client_request_id")
        update["source_revision_hash"] = created.data["data"]["source_revision_hash"]
        update["items"][0]["planned_quantity"] = 90
        missing = self.client.patch(f"/api/v1/production-schedules/{schedule_id}/", update, format="json")
        self.assertEqual(missing.status_code, 428, missing.data)
        edited = self.client.patch(
            f"/api/v1/production-schedules/{schedule_id}/", update, format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["data"]["version"], 2)
        self.assertEqual(edited.data["data"]["products"][0]["planned_quantity"], 90)
        audit = AuditLog.objects.get(object_type="PRODUCTION_SCHEDULE", object_id=schedule_id, action="UPDATED")
        self.assertEqual(audit.before_data["products"][0]["planned_quantity"], 80)
        self.assertEqual(audit.after_data["products"][0]["planned_quantity"], 90)
        voided = self.client.post(
            f"/api/v1/production-schedules/{schedule_id}/void/", {"reason": "排产信息录入错误"},
            format="json", HTTP_IF_MATCH=edited["ETag"],
        )
        self.assertEqual(voided.status_code, 200, voided.data)
        self.assertEqual(voided.data["data"]["record_status"], "VOID")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.READY)
        self.assertEqual(self.task.get_status_display(), "已接单")
        alternative_unit = ProductionUnit.objects.create(
            unit_code="SCHED-ALT", unit_name="排产历史保护测试单位"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionTaskProduct.objects.filter(pk=self.line.pk).update(unit=alternative_unit)
        replacement = self.create_schedule()
        self.assertNotEqual(replacement.data["data"]["id"], schedule_id)

    def test_existing_ready_revision_remains_editable_after_status_backfill(self):
        create_payload = self.payload()
        created = self.create_schedule(create_payload)
        schedule_id = created.data["data"]["id"]
        legacy_revision = source_revision(self.task, [self.line])
        ProductionSchedule.objects.filter(pk=schedule_id).update(source_revision_hash=legacy_revision)
        ProductionScheduleProduct.objects.filter(schedule_id=schedule_id).update(
            source_revision_hash=legacy_revision
        )
        current_schedule = ProductionSchedule.objects.get(pk=schedule_id)
        update = {**create_payload, "items": [{**create_payload["items"][0]}]}
        update.pop("production_task_id")
        update.pop("client_request_id")
        update["source_revision_hash"] = legacy_revision
        update["items"][0]["planned_quantity"] = 90

        edited = self.client.patch(
            f"/api/v1/production-schedules/{schedule_id}/",
            update,
            format="json",
            HTTP_IF_MATCH=etag_for_instance(current_schedule),
        )

        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertNotEqual(edited.data["data"]["source_revision_hash"], legacy_revision)

    def test_database_unique_constraint_blocks_two_active_plans(self):
        created = self.create_schedule()
        first = ProductionSchedule.objects.get(pk=created.data["data"]["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionSchedule.objects.create(
                schedule_number="PC-20260915-999", production_task=self.task,
                source_snapshot=first.source_snapshot, source_revision_hash=first.source_revision_hash,
                client_request_id=uuid.uuid4(), request_payload_hash="0" * 64,
                created_by_employee=self.employee, updated_by_employee=self.employee,
            )

    def test_database_triggers_block_direct_write_bypasses(self):
        created = self.create_schedule()
        schedule = ProductionSchedule.objects.get(pk=created.data["data"]["id"])
        row = ProductionScheduleProduct.objects.get(schedule=schedule, removed_at__isnull=True)
        original_version = schedule.version
        original_updated_at = schedule.updated_at
        ProductionScheduleProduct.objects.filter(pk=row.pk).update(planned_quantity=81)
        schedule.refresh_from_db()
        self.assertEqual(schedule.version, original_version + 1)
        self.assertGreater(schedule.updated_at, original_updated_at)
        today = timezone.localdate()
        empty_task = ProductionTask.objects.create(
            task_number="HT26993", contract_number="SCHEDULE-EMPTY-001", order_source=OrderSource.NEW,
            order_number="SCHEDULE-EMPTY-ORDER", customer_account=self.customer, order_date=today,
            delivery_date=today + timedelta(days=30), salesperson=self.employee, currency=self.currency,
            includes_tax=True, order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, created_by_employee=self.employee,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionScheduleProduct.objects.filter(pk=row.pk).update(source_quantity_snapshot=999)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionSchedule.objects.filter(pk=schedule.pk).update(production_task=empty_task)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionTaskProduct.objects.filter(pk=self.line.pk).update(quantity=79)
        self.external_craft.name = "排产测试丝印（已改名）"
        self.external_craft.save(update_fields=["name", "updated_at"])
        external_link = row.crafts.get(craft=self.external_craft, removed_at__isnull=True)
        external_link.removed_at = timezone.now()
        external_link.removed_by_employee = self.employee
        external_link.save(update_fields=["removed_at", "removed_by_employee", "updated_at"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Craft.objects.filter(pk=self.external_craft.pk).update(plan_category=PlanCategory.METAL)
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.crafts.filter(removed_at__isnull=True).update(removed_at=timezone.now(), removed_by_employee=self.employee)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionSchedule.objects.create(
                schedule_number="PC-20260915-998", production_task=empty_task,
                source_snapshot=schedule.source_snapshot, source_revision_hash=schedule.source_revision_hash,
                client_request_id=uuid.uuid4(), request_payload_hash="1" * 64,
                created_by_employee=self.employee, updated_by_employee=self.employee,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionScheduleProduct.objects.filter(pk=row.pk).delete()

    def test_user_without_schedule_permission_is_denied(self):
        self.user.user_permissions.clear()
        response = self.client.get("/api/v1/production-schedules/")
        self.assertEqual(response.status_code, 403, response.data)

    def _product_image(self, folder, name):
        content = name.encode()
        Path(folder, name).write_bytes(content)
        return BusinessFile.objects.create(
            uploaded_by_employee=self.employee, original_name=name, storage_key=name,
            content_type="image/png", size_bytes=len(content), scan_status=FileScanStatus.CLEAN,
        )

    def _source_order_image(self, image, task=None, line=None):
        task = task or self.task
        line = line or self.line
        order = SalesOrder.objects.create(
            order_number=f"IMAGE-{task.task_number}", source_type="DIRECT", customer_account=self.customer,
            salesperson=self.employee, order_date=task.order_date, currency_code="CNY",
        )
        source_line = SalesOrderLine.objects.create(
            sales_order=order, line_number=1, product=self.product, product_image=image,
            product_number_snapshot=self.product.product_number, product_name_snapshot=self.product.product_name,
            unit_code_snapshot=self.product.unit.unit_code, quantity=100, unit_price=10, line_total=1000,
        )
        batch = SalesOrderDeliveryBatch.objects.create(
            sales_order=order, line_number=1, batch_number="B1", planned_delivery_date=task.delivery_date,
        )
        batch_line = SalesOrderDeliveryBatchLine.objects.create(
            delivery_batch=batch, sales_order_line=source_line, quantity=100,
        )
        task.sales_order = order
        task.sales_order_delivery_batch = batch
        task.sales_order_line = source_line
        task.save(update_fields=["sales_order", "sales_order_delivery_batch", "sales_order_line", "updated_at"])
        line.sales_order_delivery_batch_line = batch_line
        line.save(update_fields=["sales_order_delivery_batch_line", "updated_at"])
        return source_line

    def test_candidate_image_prefers_task_primary_then_ordered_task_images(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            source_image = self._product_image(folder, "source.png")
            self._source_order_image(source_image)
            primary = self._product_image(folder, "primary.png")
            first = self._product_image(folder, "first.png")
            second = self._product_image(folder, "second.png")
            ProductionTaskProductImage.objects.create(product_line=self.line, line_number=2, image_file=second)
            ProductionTaskProductImage.objects.create(product_line=self.line, line_number=1, image_file=first)
            self.line.image_file = primary
            self.line.save(update_fields=["image_file", "updated_at"])
            self.assertEqual(self.detail()["products"][0]["image_file_id"], str(primary.pk))

            self.line.image_file = None
            self.line.save(update_fields=["image_file", "updated_at"])
            self.assertEqual(self.detail()["products"][0]["image_file_id"], str(first.pk))

    def test_candidate_source_order_image_is_readable_and_saved_in_new_schedule(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            source_image = self._product_image(folder, "source.png")
            self._source_order_image(source_image)
            revision = source_revision(self.task, [self.line])
            detail = self.detail()
            candidates = self.client.get("/api/v1/production-schedules/task-candidates/").data["data"]
            for product in [detail["products"][0], detail["product_summaries"][0], candidates[0]["product_summaries"][0]]:
                self.assertEqual(product["image_file_id"], str(source_image.pk))
            self.assertEqual(detail["source_revision_hash"], revision)
            response = self.client.get(f"/api/v1/production-schedules/task-files/{self.task.pk}/{source_image.pk}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"source.png")

            created = self.create_schedule()
            self.assertEqual(created.status_code, 201, created.data)
            saved = ProductionScheduleProduct.objects.get(schedule_id=created.data["data"]["id"])
            self.assertEqual(saved.image_file_id, source_image.pk)
            self.line.refresh_from_db()
            self.assertIsNone(self.line.image_file_id)
            self.assertFalse(self.line.images.exists())

    def test_candidate_without_explicit_source_does_not_borrow_product_or_color_image(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            source_image = self._product_image(folder, "other-source.png")
            other_task, other_line = self.create_task_with_product()
            self._source_order_image(source_image, other_task, other_line)
            self.color.image_file = source_image
            self.color.save(update_fields=["image_file", "updated_at"])
            self.assertIsNone(self.detail()["products"][0]["image_file_id"])
            response = self.client.get(f"/api/v1/production-schedules/task-files/{self.task.pk}/{source_image.pk}/")
            self.assertEqual(response.status_code, 404)

    def test_source_order_image_keeps_scan_and_archive_checks(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            source_image = self._product_image(folder, "source.png")
            self._source_order_image(source_image)
            url = f"/api/v1/production-schedules/task-files/{self.task.pk}/{source_image.pk}/"
            source_image.scan_status = FileScanStatus.INFECTED
            source_image.save(update_fields=["scan_status", "updated_at"])
            self.assertIsNone(self.detail()["products"][0]["image_file_id"])
            self.assertEqual(self.client.get(url).status_code, 400)
            source_image.archived_at = timezone.now()
            source_image.save(update_fields=["archived_at", "updated_at"])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_schedule_permission_can_read_linked_product_image(self):
        self.assertFalse(self.user.has_perm("production_tasks.view_productiontask"))
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            content = b"schedule-product-image"
            storage_key = "production-scheduling/test-product.png"
            storage_path = Path(folder, storage_key)
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.write_bytes(content)
            business_file = BusinessFile.objects.create(
                uploaded_by_employee=self.employee,
                original_name="test-product.png",
                storage_key=storage_key,
                content_type="image/png",
                size_bytes=len(content),
                scan_status=FileScanStatus.CLEAN,
            )
            self.line.image_file = business_file
            self.line.save(update_fields=["image_file", "updated_at"])

            response = self.client.get(
                f"/api/v1/production-schedules/task-files/{self.task.pk}/{business_file.pk}/"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), content)
            for close_file in response._resource_closers:
                close_file()

            unrelated_file = BusinessFile.objects.create(
                uploaded_by_employee=self.employee,
                original_name="unrelated.png",
                storage_key="production-scheduling/unrelated.png",
                content_type="image/png",
                size_bytes=1,
                scan_status=FileScanStatus.CLEAN,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/v1/production-schedules/task-files/{self.task.pk}/{unrelated_file.pk}/"
                ).status_code,
                404,
            )


class ProductionSchedulingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="schedule-concurrency-user")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="SCHEDULE-CONCURRENCY", display_name="排产并发测试员工"
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SCHEDULE-CONCURRENCY-CUSTOMER", account_name="排产并发测试客户",
            primary_country_code="CN",
        )
        product, currency, color, workshop = ensure_schedule_test_references()
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT26992", contract_number="SCHEDULE-CONCURRENCY-001",
            order_source=OrderSource.NEW, order_number="SCHEDULE-CONCURRENCY-ORDER",
            customer_account=self.customer, order_date=today, delivery_date=today + timedelta(days=30),
            salesperson=self.employee, currency=currency, includes_tax=True,
            order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY, created_by_employee=self.employee,
        )
        self.line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=product,
            product_number_snapshot=product.product_number, product_code_snapshot=product.product_code,
            item_number_snapshot=product.product_item.item_number, product_name_snapshot=product.product_name,
            specification_snapshot=product.specification, product_color=color,
            color_card_snapshot=color.color_card, color_name_snapshot=color.color_name,
            color_code_snapshot=color.color_code, quantity=100, unit=product.unit, currency=currency,
            unit_price=Decimal("10"), total_amount=Decimal("1000"), exchange_rate=Decimal("1"),
        )
        make_schedule_prerequisites(task=self.task, line=self.line, employee=self.employee)
        self.craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=workshop,
            name="排产并发测试金工", plan_category=PlanCategory.METAL, status=RecordStatus.ACTIVE,
        )
        self.revision = source_revision(self.task, [self.line])

    def _create_in_thread(self, barrier, request_id=None):
        close_old_connections()
        try:
            actor = Employee.objects.get(pk=self.employee.pk)
            barrier.wait(timeout=10)
            schedule = create_schedule(
                validated_data={
                    "production_task_id": self.task.pk,
                    "source_revision_hash": self.revision,
                    "client_request_id": request_id or uuid.uuid4(),
                    "items": [{
                        "product_line_id": self.line.pk, "planned_quantity": 80,
                        "material_inbound_date": timezone.localdate() + timedelta(days=1),
                        "metal_return_date": timezone.localdate() + timedelta(days=5),
                        "sewing_return_date": timezone.localdate() + timedelta(days=8),
                        "finished_inbound_date": timezone.localdate() + timedelta(days=11),
                        "craft_ids": [self.craft.pk],
                    }],
                },
                actor_employee=actor,
            )
            return "created", str(schedule.pk)
        except Conflict:
            return "conflict", None
        finally:
            close_old_connections()

    def test_concurrent_create_keeps_exactly_one_active_schedule(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self._create_in_thread(barrier), range(2)))
        self.assertCountEqual([result[0] for result in results], ["created", "conflict"])
        self.assertEqual(
            ProductionSchedule.objects.filter(
                production_task=self.task, record_status=ScheduleStatus.ACTIVE
            ).count(),
            1,
        )

    def test_concurrent_retry_with_same_request_id_returns_same_schedule(self):
        barrier = Barrier(2)
        request_id = uuid.uuid4()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._create_in_thread, barrier, request_id) for _ in range(2)]
            results = [future.result() for future in futures]
        self.assertEqual([result[0] for result in results], ["created", "created"])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(ProductionSchedule.objects.filter(record_status=ScheduleStatus.ACTIVE).count(), 1)

    def test_batch_idempotent_retry_and_edit_complete_without_deadlock(self):
        request_id = uuid.uuid4()
        create_data = {
            "production_task_id": self.task.pk,
            "source_revision_hash": self.revision,
            "client_request_id": request_id,
            "items": [{
                "product_line_id": self.line.pk, "planned_quantity": 80,
                "material_inbound_date": timezone.localdate() + timedelta(days=1),
                "metal_return_date": timezone.localdate() + timedelta(days=5),
                "sewing_return_date": timezone.localdate() + timedelta(days=8),
                "finished_inbound_date": timezone.localdate() + timedelta(days=11),
                "craft_ids": [self.craft.pk],
            }],
        }
        schedule = create_schedule(validated_data=create_data, actor_employee=self.employee)
        etag = etag_for_instance(schedule)
        update_data = {
            "source_revision_hash": self.revision,
            "items": [{**create_data["items"][0], "planned_quantity": 70}],
        }
        barrier = Barrier(2)

        def retry_batch():
            close_old_connections()
            try:
                actor = Employee.objects.get(pk=self.employee.pk)
                barrier.wait(timeout=10)
                result = create_schedule_batch(
                    validated_data={"schedules": [create_data]}, actor_employee=actor
                )
                return str(result[0].pk)
            finally:
                close_old_connections()

        def edit_schedule():
            close_old_connections()
            try:
                actor = Employee.objects.get(pk=self.employee.pk)
                request = RequestFactory().patch("/", HTTP_IF_MATCH=etag)
                barrier.wait(timeout=10)
                result = update_schedule(
                    schedule_id=schedule.pk, validated_data=update_data,
                    actor_employee=actor, request=request,
                )
                return str(result.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            retry_future = executor.submit(retry_batch)
            edit_future = executor.submit(edit_schedule)
            results = [retry_future.result(timeout=20), edit_future.result(timeout=20)]
        self.assertEqual(results, [str(schedule.pk), str(schedule.pk)])
        schedule.refresh_from_db()
        self.assertEqual(schedule.version, 2)
        self.assertEqual(
            schedule.products.get(removed_at__isnull=True).planned_quantity,
            70,
        )
