"""采购进度不再阻断排产；其余来源、权限及并发契约保持。"""

import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import BomStatus
from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus
from apps.production_tasks.models import ProductionTaskStatus
from apps.workshop_config.models import RecordStatus

from ..models import ProductionSchedule
from . import test_production_scheduling_api as schedule_fixtures


class ProcurementIndependentScheduleTests(APITestCase):
    # 复用最小真实数据库夹具，不继承旧测试类，避免重复发现其整组测试。
    setUp = schedule_fixtures.ProductionSchedulingApiTests.setUp
    detail = schedule_fixtures.ProductionSchedulingApiTests.detail
    payload = schedule_fixtures.ProductionSchedulingApiTests.payload
    create_schedule = schedule_fixtures.ProductionSchedulingApiTests.create_schedule

    def _remove_purchase(self):
        PurchaseOrder.objects.filter(production_task=self.task).delete()
        self.assertFalse(PurchaseOrder.objects.filter(production_task=self.task).exists())

    def _candidate_ids(self):
        response = self.client.get("/api/v1/production-schedules/task-candidates/")
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.data["data"]}

    def _assert_ready_source(self, purchase_status):
        self.assertIn(str(self.task.pk), self._candidate_ids())
        source = self.detail()
        self.assertTrue(source["scheduling_ready"])
        self.assertTrue(source["selectable"])
        self.assertEqual(source["scheduling_blockers"], [])
        self.assertEqual(source["products"][0]["purchase_status"], purchase_status)
        return source

    def test_no_purchase_can_create_with_idempotency_and_duplicate_guard(self):
        self._remove_purchase()
        self._assert_ready_source("NOT_STARTED")
        payload = self.payload()
        created = self.create_schedule(payload)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.IN_PRODUCTION)
        self.assertTrue(AuditLog.objects.filter(
            object_type="PRODUCTION_TASK", object_id=self.task.pk, action="SCHEDULED",
        ).exists())

        retry = self.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertEqual(retry.data["data"]["id"], created.data["data"]["id"])
        duplicate = self.client.post(
            "/api/v1/production-schedules/",
            {**payload, "client_request_id": str(uuid.uuid4())}, format="json",
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.data)
        self.assertEqual(ProductionSchedule.objects.filter(production_task=self.task).count(), 1)
        self.assertFalse(PurchaseOrder.objects.filter(production_task=self.task).exists())

    def test_purchasing_order_can_be_candidate_and_create(self):
        self.purchase_order.status = PurchaseOrderStatus.PURCHASING
        self.purchase_order.completed_at = None
        self.purchase_order.completed_by_employee = None
        self.purchase_order.save(update_fields=[
            "status", "completed_at", "completed_by_employee", "updated_at",
        ])
        self._assert_ready_source("ORDER_PURCHASING")
        self.create_schedule()
        self.purchase_order.refresh_from_db()
        self.assertEqual(self.purchase_order.status, PurchaseOrderStatus.PURCHASING)
        self.assertIsNone(self.purchase_order.completed_at)

    def test_draft_purchase_can_be_candidate_and_create(self):
        self.purchase_order.status = PurchaseOrderStatus.DRAFT
        self.purchase_order.completed_at = None
        self.purchase_order.completed_by_employee = None
        self.purchase_order.save(update_fields=[
            "status", "completed_at", "completed_by_employee", "updated_at",
        ])
        self._assert_ready_source("ORDER_DRAFT")
        self.create_schedule()

    def test_ready_task_without_products_is_not_a_candidate_or_selectable_source(self):
        empty_task = type(self.task).objects.get(pk=self.task.pk)
        empty_task.pk = None
        empty_task.task_number = "HT-U3-EMPTY"
        empty_task.contract_number = "U3-EMPTY-CONTRACT"
        empty_task.order_number = "U3-EMPTY-ORDER"
        empty_task.save()
        self.assertFalse(empty_task.products.exists())
        self.assertFalse(PurchaseOrder.objects.filter(production_task=empty_task).exists())
        self.assertNotIn(str(empty_task.pk), self._candidate_ids())
        response = self.client.get(f"/api/v1/production-schedules/task-candidates/{empty_task.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        source = response.data["data"]
        self.assertEqual(source["products"], [])
        self.assertFalse(source["scheduling_ready"])
        self.assertFalse(source["selectable"])
        self.assertTrue(source["scheduling_blockers"])

    def test_no_purchase_existing_schedule_can_update_with_etag(self):
        self._remove_purchase()
        payload = self.payload()
        created = self.create_schedule(payload)
        source = self.detail()
        schedule_id = created.data["data"]["id"]
        self.assertEqual(source["existing_schedule_id"], schedule_id)
        self.assertEqual(source["status"], ProductionTaskStatus.IN_PRODUCTION)
        self.assertEqual(source["scheduling_blockers"], [])
        self.assertFalse(source["selectable"])
        self.assertNotIn(str(self.task.pk), self._candidate_ids())
        update = {
            "source_revision_hash": source["source_revision_hash"],
            "items": [{**payload["items"][0], "planned_quantity": 90}],
        }
        url = f"/api/v1/production-schedules/{schedule_id}/"
        missing = self.client.patch(url, update, format="json")
        self.assertEqual(missing.status_code, 428, missing.data)
        edited = self.client.patch(url, update, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["data"]["products"][0]["planned_quantity"], 90)
        stale = self.client.patch(url, update, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)
        audit = AuditLog.objects.get(
            object_type="PRODUCTION_SCHEDULE", object_id=schedule_id, action="UPDATED",
        )
        self.assertEqual(audit.before_data["products"][0]["planned_quantity"], 80)
        self.assertEqual(audit.after_data["products"][0]["planned_quantity"], 90)
        self.assertFalse(PurchaseOrder.objects.filter(production_task=self.task).exists())

    def test_no_purchase_unverified_bom_still_blocks_candidate_and_create(self):
        self._remove_purchase()
        self.bom.status = BomStatus.PENDING_CONFIRMATION
        self.bom.save(update_fields=["status", "updated_at"])
        self.assertNotIn(str(self.task.pk), self._candidate_ids())
        source = self.detail()
        self.assertFalse(source["scheduling_ready"])
        self.assertFalse(source["selectable"])
        self.assertIn("生产任务单内所有产品的 BOM 必须已确认", source["scheduling_blockers"])
        response = self.client.post("/api/v1/production-schedules/", self.payload(), format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("BOM 必须已确认", response.data["error"]["message"])
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_product_without_active_bom_still_blocks_candidate_source_and_create(self):
        self._remove_purchase()
        self.bom.archived_at = timezone.now()
        self.bom.save(update_fields=["archived_at"])
        self.assertNotIn(str(self.task.pk), self._candidate_ids())
        source = self.detail()
        self.assertFalse(source["scheduling_ready"])
        self.assertFalse(source["selectable"])
        response = self.client.post("/api/v1/production-schedules/", self.payload(), format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("BOM 必须已确认", response.data["error"]["message"])
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_no_purchase_invalid_task_state_or_archive_still_blocks(self):
        self._remove_purchase()
        payload = self.payload()
        states = [
            (ProductionTaskStatus.COMPLETED, None),
            (ProductionTaskStatus.CANCELLED, None),
            (ProductionTaskStatus.PAUSED, None),
            (ProductionTaskStatus.READY, timezone.now()),
        ]
        for status, archived_at in states:
            with self.subTest(status=status, archived=archived_at is not None):
                type(self.task).objects.filter(pk=self.task.pk).update(
                    status=status, archived_at=archived_at,
                )
                self.assertNotIn(str(self.task.pk), self._candidate_ids())
                source = self.client.get(f"/api/v1/production-schedules/task-candidates/{self.task.pk}/")
                self.assertEqual(source.status_code, 404, source.data)
                response = self.client.post("/api/v1/production-schedules/", payload, format="json")
                self.assertEqual(response.status_code, 409, response.data)
                self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_no_purchase_quantity_and_craft_validation_still_apply(self):
        self._remove_purchase()
        payload = self.payload()
        invalid_items = [
            {**payload["items"][0], "planned_quantity": 101},
            {**payload["items"][0], "planned_quantity": 0},
            {**payload["items"][0], "craft_ids": []},
            {**payload["items"][0], "craft_ids": [str(uuid.uuid4())]},
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                response = self.client.post(
                    "/api/v1/production-schedules/", {**payload, "items": [item]}, format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())
        self.internal_craft.status = RecordStatus.INACTIVE
        self.internal_craft.save(update_fields=["status", "updated_at"])
        response = self.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())

    def test_no_purchase_does_not_grant_schedule_write_or_read_permissions(self):
        self._remove_purchase()
        payload = self.payload()
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="production_scheduling", codename="view_productionschedule",
        ))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertIn(str(self.task.pk), self._candidate_ids())
        denied = self.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(denied.status_code, 403, denied.data)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        read = self.client.get("/api/v1/production-schedules/task-candidates/")
        self.assertEqual(read.status_code, 403, read.data)
        self.assertFalse(ProductionSchedule.objects.filter(production_task=self.task).exists())
