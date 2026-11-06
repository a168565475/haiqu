from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.wecom.models import NotificationEvent

from ..models import ProductionTask, ProductionTaskStatus
from . import test_production_task_api as fixtures


@override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class ConfirmWithoutPlanDatesTests(APITestCase):
    setUp = fixtures.ProductionTaskApiTests.setUp
    payload = fixtures.ProductionTaskApiTests.payload

    def pending_task(self, **changes):
        created = self.client.post("/api/v1/production-tasks/", self.payload(**changes), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        submitted = self.client.post(
            f"/api/v1/production-tasks/{task.pk}/submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        task.refresh_from_db()
        return task, submitted

    def confirm(self, task, submitted, *, endpoint="confirm", **changes):
        return self.client.post(
            f"/api/v1/production-tasks/{task.pk}/{endpoint}/",
            {"decision": "CONFIRM", "follower_ids": [str(self.follower.pk)], **changes},
            format="json", HTTP_IF_MATCH=submitted["ETag"],
        )

    def assert_not_confirmed(self, task):
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTaskStatus.PENDING_VALIDATION)
        self.assertFalse(AuditLog.objects.filter(object_id=task.pk, action="CONFIRMED").exists())
        self.assertFalse(NotificationEvent.objects.filter(object_id=task.pk, event_code="PRODUCTION_TASK_CONFIRMED").exists())

    def test_both_confirmation_endpoints_accept_omitted_plan_dates(self):
        for endpoint in ("confirm", "pmc-decision"):
            with self.subTest(endpoint=endpoint):
                task, submitted = self.pending_task()
                confirmed = self.confirm(task, submitted, endpoint=endpoint)
                self.assertEqual(confirmed.status_code, 200, confirmed.data)
                task.refresh_from_db()
                self.assertEqual(task.status, ProductionTaskStatus.READY)
                self.assertIsNone(task.planned_start_date)
                self.assertIsNone(task.planned_end_date)
                self.assertEqual(AuditLog.objects.filter(object_id=task.pk, action="CONFIRMED").count(), 1)
                self.assertEqual(NotificationEvent.objects.filter(
                    object_id=task.pk, event_code="PRODUCTION_TASK_CONFIRMED",
                ).count(), 1)

    def test_confirmation_accepts_explicitly_empty_plan_dates(self):
        task, submitted = self.pending_task()
        confirmed = self.confirm(task, submitted, planned_start_date=None, planned_end_date=None)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        task.refresh_from_db()
        self.assertEqual(task.status, ProductionTaskStatus.READY)
        self.assertIsNone(task.planned_start_date)
        self.assertIsNone(task.planned_end_date)

    def test_confirmation_rejects_either_single_plan_date(self):
        for field in ("planned_start_date", "planned_end_date"):
            with self.subTest(field=field):
                task, submitted = self.pending_task()
                rejected = self.confirm(task, submitted, **{field: timezone.localdate().isoformat()})
                self.assertEqual(rejected.status_code, 400, rejected.data)
                self.assert_not_confirmed(task)
                self.assertIsNone(task.planned_start_date)
                self.assertIsNone(task.planned_end_date)

    def test_confirmation_rejects_end_before_existing_start(self):
        today = timezone.localdate()
        start, end = today + timedelta(days=1), today + timedelta(days=2)
        task, submitted = self.pending_task(planned_start_date=start.isoformat(), planned_end_date=end.isoformat())
        rejected = self.confirm(task, submitted, planned_end_date=today.isoformat())
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("planned_end_date", rejected.data["error"]["field_errors"])
        self.assert_not_confirmed(task)
        self.assertEqual(task.planned_start_date, start)
        self.assertEqual(task.planned_end_date, end)

    def test_confirmation_without_plan_dates_still_rejects_stale_etag(self):
        task, submitted = self.pending_task()
        rejected = self.confirm(task, {"ETag": '"stale-version"'})
        self.assertEqual(rejected.status_code, 412, rejected.data)
        self.assert_not_confirmed(task)
