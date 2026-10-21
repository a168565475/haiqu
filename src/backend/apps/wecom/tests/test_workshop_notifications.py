"""07：隔离PostgreSQL真实服务/API；网络不发送，不能替代正式身份验收。"""
from uuid import uuid4

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.core.api.concurrency import etag_for_instance
from apps.wecom.models import NotificationDelivery, NotificationEvent
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_catalog import target_for
from apps.wecom.notification_selectors import recipient_payload
from apps.workshop_reporting.models import WageScheme, WorkReport

from .test_notifications import SETTINGS, create_rule, employee, grant_role


def receiver(code, permission, *, workshop=None):
    member = employee(code)
    role = grant_role(member, code, permission, "WORKSHOP" if workshop else "MODULE")
    if workshop:
        RoleGrantResource.objects.create(grant=RoleActionGrant.objects.get(role=role), workshop=workshop)
    return member, role


@override_settings(**SETTINGS, WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True)
class WageAndReportNotificationTests(TestCase):
    def setUp(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        self.f = WorkshopReportingApiTests()
        self.f.setUp()
        self.manager, self.manager_role = receiver("U07_FACTORY", "workshop_reporting.approve_wagescheme")
        self.director, self.director_role = receiver("U07_METAL", "workshop_reporting.view_wagescheme", workshop=self.f.workshop)
        self.report_reader, self.report_role = receiver("U07_REPORT", "workshop_reporting.view_workreport")
        for code, role in [("WAGE_SCHEME_SUBMITTED", self.manager_role), ("WAGE_SCHEME_DECIDED", self.director_role),
                           ("WORK_REPORT_SAVED", self.report_role), ("WORK_REPORT_CORRECTED", self.report_role),
                           ("WORK_REPORT_DELETED", self.report_role)]:
            create_rule(code, self.f.employee, [role.role_code])
        self.manager_client = APIClient()
        self.manager_client.force_authenticate(self.manager.user)

    def draft(self):
        response = self.f.client.post("/api/v1/workshop-reporting/wage-schemes/", self.f.scheme_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def submit(self, draft):
        response = self.f.client.post(f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=draft["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def decide(self, submitted, action="approve", client=None):
        return (client or self.manager_client).post(
            f"/api/v1/workshop-reporting/wage-schemes/{submitted.data['data']['id']}/{action}/",
            {"comment": "测试决定"}, format="json", HTTP_IF_MATCH=submitted["ETag"])

    def assert_recipient(self, code, member):
        event = NotificationEvent.objects.get(event_code=code)
        self.assertEqual(event.recipients.get().employee_id, member.pk)
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
        self.assertEqual(event.recipients.get().deliveries.get(channel="WECOM").status, "PENDING")
        return event

    def test_submit_approve_real_api_no_self_review_and_stale_version(self):
        draft = self.draft()
        self.assertFalse(NotificationEvent.objects.exists())
        submitted = self.submit(draft)
        pending = self.assert_recipient("WAGE_SCHEME_SUBMITTED", self.manager)
        self.assertEqual(self.decide(submitted, client=self.f.client).status_code, 403)
        approved = self.decide(submitted)
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assert_recipient("WAGE_SCHEME_DECIDED", self.director)
        payload = recipient_payload(pending.recipients.get(), self.manager.user)
        self.assertFalse(payload["target_accessible"])
        self.assertEqual(payload["title"], "通知已过期")
        self.assertEqual(self.decide(submitted).status_code, 412)
        self.assertEqual(NotificationEvent.objects.count(), 2)

    def test_return_resubmit_uses_new_revision_and_configuration(self):
        submitted = self.submit(self.draft())
        returned = self.decide(submitted, "return")
        self.assertEqual(returned.status_code, 200, returned.data)
        old = self.assert_recipient("WAGE_SCHEME_DECIDED", self.director)
        resubmitted = self.submit(returned)
        self.assertEqual(NotificationEvent.objects.filter(event_code="WAGE_SCHEME_SUBMITTED").count(), 2)
        self.assertFalse(recipient_payload(old.recipients.get(), self.director.user)["target_accessible"])
        self.assertEqual(resubmitted.data["data"]["status"], "PENDING_APPROVAL")

    def test_submit_rollback_removes_state_event_and_channels(self):
        draft = self.draft()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.submit(draft)
                self.assertEqual(NotificationDelivery.objects.count(), 2)
                raise RuntimeError("rollback")
        self.assertEqual(WageScheme.objects.get().status, "DRAFT")
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_report_replay_correction_and_deletion_do_not_leave_valid_old_quantity(self):
        approved = self.decide(self.submit(self.draft()))
        self.assertEqual(approved.status_code, 200, approved.data)
        data = approved.data["data"]
        payload = {"client_request_id": str(uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.f.schedule_product.pk), "scheme_id": data["id"],
            "scheme_revision": data["revision"], "lines": [{"scheme_line_id": data["lines"][0]["id"],
                "workshop_employee_id": str(self.f.worker.pk), "quantity": "2"}]}
        response = self.f.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        event = self.assert_recipient("WORK_REPORT_SAVED", self.report_reader)
        replay = self.f.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(NotificationEvent.objects.filter(event_code="WORK_REPORT_SAVED").count(), 1)
        report = WorkReport.objects.get()
        self.assertNotIn("quantity", event.context)  # 不把各工序/单位的次数混加为产品产量。
        self.assertEqual(target_for("WORK_REPORT_SAVED", report.pk)["params"], {"productionDate": str(report.production_date)})
        changed = {**payload, "lines": [{**payload["lines"][0], "quantity": "3"}]}
        updated = self.f.client.patch(f"/api/v1/workshop-reporting/work-reports/{report.pk}/", changed,
            format="json", HTTP_IF_MATCH=etag_for_instance(report))
        self.assertEqual(updated.status_code, 200, updated.data)
        corrected = self.assert_recipient("WORK_REPORT_CORRECTED", self.report_reader)
        self.assertTrue(recipient_payload(corrected.recipients.get(), self.report_reader.user)["target_accessible"])
        from apps.audit.models import AuditLog
        audit = AuditLog.objects.get(object_type="WORK_REPORT", object_id=report.pk, action="UPDATE")
        self.assertEqual(audit.before_data["revision"], 1)
        self.assertEqual(audit.after_data["revision"], 2)
        self.assertFalse(recipient_payload(event.recipients.get(), self.report_reader.user)["target_accessible"])
        self.assertEqual(NotificationEvent.objects.filter(event_code="WORK_REPORT_SAVED").count(), 1)
        report.refresh_from_db()
        deleted = self.f.client.delete(f"/api/v1/workshop-reporting/work-reports/{report.pk}/",
            {"reason": "测试删除"}, format="json", HTTP_IF_MATCH=etag_for_instance(report))
        self.assertIn(deleted.status_code, (200, 204), deleted.data)
        self.assertFalse(WorkReport.objects.exists())
        self.assertFalse(event_object_accessible("WORK_REPORT_SAVED", report.pk, self.report_reader.user))
        notice = self.assert_recipient("WORK_REPORT_DELETED", self.report_reader)
        self.assertEqual(notice.object_type, "workshop_reporting.WorkReportHistory")
        self.assertNotEqual(notice.object_id, str(report.pk))
        content = recipient_payload(notice.recipients.get(), self.report_reader.user)
        self.assertIn("原记录已删除", content["body"])
        self.assertIsNone(content["target"])
        self.assertFalse(content["target_accessible"])
        self.assertTrue(event_object_accessible("WORK_REPORT_DELETED", notice.object_id, self.report_reader.user,
            object_version=notice.object_version))
        self.assertFalse(recipient_payload(corrected.recipients.get(), self.report_reader.user)["target_accessible"])
        RoleActionGrant.objects.filter(role=self.report_role).delete()
        self.assertEqual(recipient_payload(notice.recipients.get(), self.report_reader.user)["body"], "该业务内容当前不可访问。")

    @override_settings(WORK_REPORT_DELETION_ENABLED=False)
    def test_disabled_deletion_stays_denied_and_does_not_invalidate_saved_message(self):
        approved = self.decide(self.submit(self.draft()))
        data = approved.data["data"]
        payload = {"client_request_id": str(uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.f.schedule_product.pk), "scheme_id": data["id"],
            "scheme_revision": data["revision"], "lines": [{"scheme_line_id": data["lines"][0]["id"],
                "workshop_employee_id": str(self.f.worker.pk), "quantity": "2"}]}
        saved = self.f.client.post("/api/v1/workshop-reporting/work-reports/", payload, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        report = WorkReport.objects.get()
        deleted = self.f.client.delete(f"/api/v1/workshop-reporting/work-reports/{report.pk}/",
            {"reason": "关闭时不允许删除"}, format="json", HTTP_IF_MATCH=etag_for_instance(report))
        self.assertEqual(deleted.status_code, 403, deleted.data)
        self.assertFalse(NotificationEvent.objects.filter(event_code="WORK_REPORT_DELETED").exists())
        self.assertTrue(WorkReport.objects.filter(pk=report.pk).exists())
        event = NotificationEvent.objects.get(event_code="WORK_REPORT_SAVED")
        self.assertTrue(recipient_payload(event.recipients.get(), self.report_reader.user)["target_accessible"])

    def test_module_manager_can_edit_others_draft_without_superuser(self):
        draft = self.draft()
        grant = RoleActionGrant.objects.get(role=self.manager_role)
        from django.contrib.auth.models import Permission
        grant.permission = Permission.objects.get(content_type__app_label="workshop_reporting", codename="change_wagescheme")
        grant.save()
        self.assertFalse(self.manager.user.is_superuser)
        response = self.manager_client.patch(f"/api/v1/workshop-reporting/wage-schemes/{draft.data['data']['id']}/",
            {"remark": "厂长合法代办"}, format="json", HTTP_IF_MATCH=draft["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
