"""隔离PostgreSQL验证；仅替换企微网络，禁止真实外发。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from apps.core.api.concurrency import PreconditionFailed
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from apps.wecom.client import WeComError, WeComSendUncertain
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import NotificationPreviewAttempt, NotificationRule, NotificationEvent, WeComConfig, WeComBinding, WeComMessageAttempt
from apps.wecom.notification_catalog import all_events
from apps.wecom import notification_preview_services as service
from apps.wecom.notification_preview_selectors import attempt_payload
from apps.wecom.notification_serializers import NotificationPreviewSendSerializer
from apps.wecom.selectors import config_etag
from .test_notifications import SETTINGS, employee, grant_role, rule_data


ROOT = "/api/v1/notifications/"
CODE = "PRODUCTION_TASK_CONFIRMED"


class NotificationPreviewInputTests(SimpleTestCase):
    def test_nested_draft_accepts_valid_fields_and_rejects_unknown_input(self):
        data = {"preview_token": "signed", "binding_id": "00000000-0000-0000-0000-000000000001",
                "config_etag": "config-v1", "draft": {"name": "预览", "title_template": "标题",
                    "body_template": "正文", "recipient_role_codes": [], "recipient_scope": "ROLE_MEMBERS",
                    "enabled": False, "variables": {}}}
        serializer = NotificationPreviewSendSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer = NotificationPreviewSendSerializer(data={**data, "draft": {**data["draft"], "user_id": "@all"}})
        self.assertFalse(serializer.is_valid())

    def test_missing_draft_fields_and_recipient_array_are_rejected(self):
        data = {"preview_token": "signed", "binding_id": ["00000000-0000-0000-0000-000000000001"],
                "config_etag": "config-v1", "draft": {"variables": {}}}
        serializer = NotificationPreviewSendSerializer(data=data)
        self.assertFalse(serializer.is_valid())


class PreviewFixture:
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("admin", "", None)
        self.actor = Employee.objects.create(user=self.admin, employee_code="PREVIEW_ADMIN", display_name="预览管理员")
        self.member = employee("PREVIEW_MEMBER")
        self.role = grant_role(self.member, "PREVIEW_TARGET", "production_tasks.view_productiontask")
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("isolated-preview-secret"))
        self.binding = WeComBinding.objects.create(employee=self.member, corp_id=self.config.corp_id,
            user_id="Preview.Member", member_name="隔离测试员工", source="MANUAL")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.draft = {**rule_data(CODE, [self.role.role_code]),
            "variables": {"document_no": "示例单号", "operator": "示例操作人", "occurred_at": "示例时间"}}

    def preview(self):
        response = self.client.post(f"{ROOT}rules/{CODE}/preview/", self.draft, format="json",
                                    HTTP_IF_MATCH='"notification-rule-unsaved"')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def data(self, preview=None):
        return {"preview_token": (preview or self.preview())["preview_token"], "binding_id": str(self.binding.pk),
                "config_etag": config_etag(self.config), "draft": self.draft}

    def request(self, user=None):
        request = APIRequestFactory().post(f"{ROOT}rules/{CODE}/preview-send/")
        request.user = user or self.admin
        return request


@override_settings(**SETTINGS)
class NotificationPreviewTests(PreviewFixture, TestCase):
    def test_catalog_definitions_cover_all_events_without_changing_string_arrays(self):
        events = all_events()
        self.assertEqual(len(events), 35)
        for event in events:
            with self.subTest(event=event["event_code"]):
                definitions = event["variable_definitions"]
                self.assertEqual([row["name"] for row in definitions], event["allowed_variables"])
                self.assertTrue(set(event["required_variables"]) <= set(event["allowed_variables"]))
                self.assertTrue(all(row["label"] != row["name"] and row["example"] for row in definitions))
        self.assertFalse(Permission.objects.filter(content_type__app_label="wecom", content_type__model="notificationpreviewattempt").exists())

    def test_preview_is_read_only_and_does_not_require_new_table(self):
        with (patch("apps.wecom.notification_preview_selectors.schema_ready", return_value=False),
              patch("apps.wecom.notification_preview_services.schema_ready", return_value=False),
              CaptureQueriesContext(connection) as queries):
            response = self.client.get(ROOT + "rules/")
            self.assertEqual(response.status_code, 200)
            preview = self.preview()
            options = self.client.get(ROOT + "preview-recipients/")
            self.assertFalse(options.data["schema_ready"])
            self.assertIn("尚未启用", options.data["message"])
            send = self.client.post(f"{ROOT}rules/{CODE}/preview-send/", self.data(preview), format="json")
            self.assertEqual(send.status_code, 409)
        self.assertFalse(any('FROM "wecom_notification_preview_attempt"' in row["sql"] for row in queries))
        self.assertFalse(NotificationRule.objects.exists())
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertFalse(NotificationPreviewAttempt.objects.exists())
        self.assertFalse(preview["will_send"])

    def test_candidates_filter_current_corporation_employee_and_account_without_identity_leak(self):
        foreign = employee("FOREIGN")
        WeComBinding.objects.create(employee=foreign, corp_id="different", user_id="Other", member_name="其他", source="MANUAL")
        inactive = employee("INACTIVE")
        inactive.user.is_active = False; inactive.user.save(update_fields=["is_active"])
        WeComBinding.objects.create(employee=inactive, corp_id=self.config.corp_id, user_id="Inactive", member_name="停用", source="MANUAL")
        result = self.client.get(ROOT + "preview-recipients/").data
        self.assertEqual(result["count"], 1)
        self.assertEqual(set(result["data"][0]), {"binding_id", "employee_name", "employee_code"})
        self.assertEqual(result["data"][0]["binding_id"], str(self.binding.pk))
        self.assertEqual(self.client.get(ROOT + "preview-recipients/?search=没有此人").data["count"], 0)
        self.config.enabled = False; self.config.save(update_fields=["enabled"])
        result = self.client.get(ROOT + "preview-recipients/").data
        self.assertFalse(result["available"]); self.assertEqual(result["data"], [])

    def test_both_permissions_and_csrf_are_required(self):
        for name, permission in [("NOTIFY_ONLY", "access_control.manage_notifications"), ("WECOM_ONLY", "access_control.manage_wecom")]:
            member = employee(name)
            grant_role(member, name, permission)
            self.client.force_login(member.user)
            self.assertEqual(self.client.get(ROOT + "preview-recipients/").status_code, 403)
            self.assertEqual(self.client.post(f"{ROOT}rules/{CODE}/preview-send/", {}, format="json").status_code, 403)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(f"{ROOT}rules/{CODE}/preview-send/", {}, format="json").status_code, 403)

    def test_tampered_expired_draft_and_actor_credentials_are_rejected(self):
        preview = self.preview()
        data = self.data(preview)
        with self.assertRaises(ValidationError):
            service.prepare_attempt(self.request(), CODE, {**data, "preview_token": "broken"})
        with self.assertRaises(Conflict):
            service.prepare_attempt(self.request(), CODE, {**data, "draft": {**self.draft, "name": "变化"}})
        with self.assertRaises(PermissionDenied):
            service.prepare_attempt(self.request(), "BOM_CONFIRMED", data)
        with patch("django.core.signing.time.time", return_value=time.time() - 601):
            expired = self.preview()
        with self.assertRaises(ValidationError):
            service.prepare_attempt(self.request(), CODE, self.data(expired))
        self.assertFalse(NotificationPreviewAttempt.objects.exists())

    def test_rule_config_and_binding_are_rechecked_before_first_send(self):
        data = self.data()
        with self.assertRaises(PreconditionFailed):
            service.prepare_attempt(self.request(), CODE, {**data, "config_etag": '"old"'})
        self.member.user.is_active = False; self.member.user.save(update_fields=["is_active"])
        with self.assertRaises(Conflict):
            service.prepare_attempt(self.request(), CODE, data)
        self.member.user.is_active = True; self.member.user.save(update_fields=["is_active"])
        self.binding.corp_id = "foreign"; self.binding.save(update_fields=["corp_id"])
        with self.assertRaises(Conflict):
            service.prepare_attempt(self.request(), CODE, data)
        NotificationRule.objects.create(event_code=CODE, updated_by_employee=self.actor,
            allowed_variables=[], **{k: v for k, v in self.draft.items() if k != "variables"})
        with self.assertRaises(PreconditionFailed):
            service.prepare_attempt(self.request(), CODE, data)
        self.assertFalse(NotificationPreviewAttempt.objects.exists())

    def test_first_attempt_idempotency_and_pending_payload_prevent_repeat(self):
        data = self.data()
        first, client = service.prepare_attempt(self.request(), CODE, data)
        self.assertIsNotNone(client)
        repeated, client = service.prepare_attempt(self.request(), CODE, data)
        self.assertEqual(repeated.pk, first.pk); self.assertIsNone(client)
        with self.assertRaises(Conflict):
            service.prepare_attempt(self.request(), CODE, {**data, "config_etag": '"different"'})
        reopened, client = service.prepare_attempt(self.request(), CODE, self.data())
        self.assertEqual(reopened.pk, first.pk); self.assertIsNone(client)
        self.assertEqual(NotificationPreviewAttempt.objects.count(), 1)
        NotificationPreviewAttempt.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(seconds=61))
        first.refresh_from_db()
        self.assertEqual(attempt_payload(first)["status"], "UNCERTAIN")
        self.assertEqual(first.status, "PROCESSING")

    def test_result_is_personal_and_contains_no_userid_body_or_msgid(self):
        data = self.data()
        attempt, _ = service.prepare_attempt(self.request(), CODE, data)
        result = self.client.get(f"{ROOT}preview-attempts/{attempt.preview_id}/")
        self.assertEqual(result.status_code, 200)
        self.assertFalse({"user_id", "rendered_body", "msgid", "corp_id"} & set(result.data["data"]))
        other = employee("OTHER_MANAGER")
        grant_role(other, "OTHER_NOTIFY", "access_control.manage_notifications")
        grant_role(other, "OTHER_WECOM", "access_control.manage_wecom")
        self.client.force_login(other.user)
        self.assertEqual(self.client.get(f"{ROOT}preview-attempts/{attempt.preview_id}/").status_code, 404)
        with self.assertRaises(PermissionDenied):
            service.prepare_attempt(self.request(other.user), CODE, data)


@override_settings(**SETTINGS)
class NotificationPreviewSendingTests(PreviewFixture, TransactionTestCase):
    def test_exact_visible_content_is_sent_once_and_not_wrapped_in_generic_template(self):
        preview = self.preview()
        data = self.data(preview)
        def accepted(user_id, content):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(content, preview["title"] + "\n\n" + preview["body"])
            self.assertEqual(user_id, self.binding.user_id)
            return {"msgid": "isolated-message"}
        with patch("apps.wecom.client.WeComClient.send_text", side_effect=accepted) as send:
            first = self.client.post(f"{ROOT}rules/{CODE}/preview-send/", data, format="json")
            second = self.client.post(f"{ROOT}rules/{CODE}/preview-send/", data, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["data"]["status"], "ACCEPTED")
        self.assertEqual(first.data["data"]["id"], second.data["data"]["id"])
        self.assertEqual(send.call_count, 1)
        self.assertFalse(NotificationEvent.objects.exists()); self.assertFalse(WeComMessageAttempt.objects.exists())

    def test_uncertain_and_failed_are_distinct_and_never_automatically_resent(self):
        for status, error in [("UNCERTAIN", WeComSendUncertain()), ("FAILED", WeComError("RECIPIENT_REJECTED", "拒绝"))]:
            self.draft["title_template"] = "示例" + status
            data = self.data()
            with patch("apps.wecom.client.WeComClient.send_text", side_effect=error) as send:
                first = service.send_preview(self.request(), CODE, data)
                again = service.send_preview(self.request(), CODE, data)
            self.assertEqual(first.status, status); self.assertEqual(again.pk, first.pk)
            self.assertEqual(send.call_count, 1)

    def test_concurrent_clicks_share_one_attempt_and_one_network_call(self):
        data = self.data()
        entered, release = Event(), Event()
        def network(*args):
            entered.set()
            if not release.wait(20):
                raise RuntimeError("isolated send wait timed out")
            return {"msgid": "isolated-concurrent"}
        def run():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.admin.pk)
                return service.send_preview(self.request(user), CODE, data)
            finally:
                connections.close_all()
        with patch("apps.wecom.client.WeComClient.send_text", side_effect=network) as send, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            try:
                self.assertTrue(entered.wait(15))
                second = pool.submit(run).result(timeout=15)
                self.assertEqual(second.status, "PROCESSING")
            finally:
                release.set()
            done = first.result(timeout=15)
        self.assertEqual(done.pk, second.pk)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(NotificationPreviewAttempt.objects.count(), 1)
