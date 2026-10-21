import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.wecom import models
from apps.wecom.credentials import encrypt_secret


TEMPLATE_URL = "/api/v1/wecom/message-template/"
SEND_URL = "/api/v1/wecom/message-tests/"
ATTEMPTS_URL = "/api/v1/wecom/message-attempts/"


class WeComMessageAnonymousTests(SimpleTestCase):
    def test_message_endpoints_require_authenticated_administrator(self):
        client = APIClient()
        for method, url in (("get", TEMPLATE_URL), ("post", SEND_URL), ("get", ATTEMPTS_URL)):
            with self.subTest(url=url):
                response = getattr(client, method)(url)
                self.assertEqual(response.status_code, 401)


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True)
class WeComMessageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.actor = Employee.objects.create(user=self.admin, employee_code="MSG_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.config = models.WeComConfig.objects.create(secret_ciphertext=encrypt_secret("message-test-secret"))
        user = get_user_model().objects.create_user("message-member")
        self.employee = Employee.objects.create(user=user, employee_code="MSG_MEMBER", display_name="测试员工")
        self.binding = models.WeComBinding.objects.create(employee=self.employee, corp_id=self.config.corp_id,
            user_id="Message.Member", member_name="测试成员", source="AUTO", created_account=True)

    def save_template(self, body="{{接收人}}：{{消息内容}}\n{{发送时间}}\n{{系统地址}}"):
        response = self.client.get(TEMPLATE_URL)
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(TEMPLATE_URL, {"name": "测试通知", "body": body}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response["ETag"]

    def send(self, etag, *, key=None, **changes):
        data = {"binding_id": str(self.binding.pk), "message_content": "测试消息", "idempotency_key": str(key or uuid.uuid4())}
        data.update(changes)
        return self.client.post(SEND_URL, data, format="json", HTTP_IF_MATCH=etag)

    def test_default_template_is_read_only_and_saving_requires_etag(self):
        response = self.client.get(TEMPLATE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["data"]["is_saved"])
        self.assertEqual(response.data["data"]["name"], "通用通知")
        self.assertEqual(models.WeComMessageTemplate.objects.count(), 0)
        self.assertEqual(self.client.patch(TEMPLATE_URL, {"name": "x", "body": "内容"}, format="json").status_code, 428)
        self.assertEqual(self.client.patch(TEMPLATE_URL, {"name": "x", "body": "内容"}, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        etag = self.save_template()
        self.assertNotEqual(etag, response["ETag"])
        self.assertTrue(self.client.get(TEMPLATE_URL).data["data"]["is_saved"])
        self.assertEqual(models.WeComMessageTemplate.objects.count(), 1)

    def test_template_rejects_unknown_malformed_variables_and_blank_or_long_input(self):
        etag = self.client.get(TEMPLATE_URL)["ETag"]
        invalid = [{"name": " ", "body": "正文"}, {"name": "名" * 51, "body": "正文"},
                   {"name": "通知", "body": " "}, {"name": "通知", "body": "{{密码}}"},
                   {"name": "通知", "body": "{{接收人}"}, {"name": "通知", "body": "{{{接收人}}}"},
                   {"name": "通知", "body": "{{ 接收人 }}"}, {"name": "通知", "body": "正文\x00"}]
        for data in invalid:
            with self.subTest(data=data):
                self.assertEqual(self.client.patch(TEMPLATE_URL, data, format="json", HTTP_IF_MATCH=etag).status_code, 400)
        self.assertFalse(models.WeComMessageTemplate.objects.exists())

    def test_non_admin_and_csrf_are_rejected_on_all_message_actions(self):
        self.client.force_login(self.employee.user)
        for method, url in (("get", TEMPLATE_URL), ("patch", TEMPLATE_URL), ("post", SEND_URL), ("get", ATTEMPTS_URL)):
            self.assertEqual(getattr(self.client, method)(url, {}, format="json").status_code, 403)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.patch(TEMPLATE_URL, {"name": "x", "body": "x"}, format="json").status_code, 403)
        self.assertEqual(csrf.post(SEND_URL, {}, format="json").status_code, 403)

    def test_messages_unmigrated_does_not_block_existing_config(self):
        with patch("apps.wecom.message_selectors.schema_is_ready", return_value=False):
            self.assertEqual(self.client.get(TEMPLATE_URL).status_code, 503)
            self.assertEqual(self.client.get("/api/v1/wecom/config/").status_code, 200)

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "test-message-id"})
    def test_send_uses_saved_template_and_binding_and_keeps_safe_audit(self, send_text):
        etag = self.save_template()
        response = self.send(etag)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["recipient_name"], "测试员工")
        self.assertIsNotNone(data["finished_at"])
        self.assertNotIn("body", data)
        self.assertNotIn("msgid", data)
        attempt = models.WeComMessageAttempt.objects.get()
        self.assertEqual(attempt.user_id, "Message.Member")
        self.assertIn("测试员工：测试消息", attempt.rendered_body)
        self.assertIn("https://erp.cnhitree.com", attempt.rendered_body)
        send_text.assert_called_once_with("Message.Member", attempt.rendered_body)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="MESSAGE_ACCEPTED").count(), 1)
        audit = str(list(AuditLog.objects.filter(object_type="WECOM").values("before_data", "after_data")))
        self.assertNotIn("message-test-secret", audit)
        self.assertNotIn(self.config.secret_ciphertext, audit)

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "test-id"})
    def test_same_request_replays_even_after_template_changes(self, send_text):
        etag = self.save_template()
        key = uuid.uuid4()
        first = self.send(etag, key=key)
        self.save_template("已修改：{{消息内容}}")
        second = self.send(etag, key=key)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data, first.data)
        self.assertEqual(models.WeComMessageAttempt.objects.count(), 1)
        self.assertEqual(send_text.call_count, 1)
        self.assertEqual(self.send(etag, key=key, message_content="另一条").status_code, 409)

    @patch("apps.wecom.message_services.WeComClient.send_text")
    def test_send_rejects_unsaved_stale_missing_binding_inactive_and_other_corp(self, send_text):
        initial = self.client.get(TEMPLATE_URL)["ETag"]
        self.assertEqual(self.send(initial).status_code, 409)
        etag = self.save_template()
        self.assertEqual(self.send('"stale"').status_code, 412)
        self.assertEqual(self.send(etag, binding_id=str(uuid.uuid4())).status_code, 404)
        self.binding.corp_id = "another-corporation"
        self.binding.save()
        self.assertEqual(self.send(etag).status_code, 409)
        self.binding.corp_id = self.config.corp_id
        self.binding.save()
        self.employee.user.is_active = False
        self.employee.user.save()
        self.assertEqual(self.send(etag).status_code, 409)
        self.employee.user.is_active = True
        self.employee.user.save()
        self.employee.archived_at = timezone.now()
        self.employee.save()
        self.assertEqual(self.send(etag).status_code, 409)
        self.assertFalse(models.WeComMessageAttempt.objects.exists())
        send_text.assert_not_called()

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "boundary-id"})
    def test_rendered_utf8_size_is_checked_without_replacing_variables_in_user_text(self, send_text):
        etag = self.save_template("{{消息内容}}")
        self.assertEqual(self.send(etag, message_content="中" * 683).status_code, 400)
        self.assertFalse(models.WeComMessageAttempt.objects.exists())
        response = self.send(etag, message_content="中" * 682 + "ab")
        self.assertEqual(response.status_code, 200)
        response = self.send(etag, message_content="原文{{系统地址}}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(models.WeComMessageAttempt.objects.latest("created_at").rendered_body, "原文{{系统地址}}")

    @patch("apps.wecom.message_services.WeComClient.send_text")
    def test_uncertain_result_is_persisted_and_never_resent_on_replay(self, send_text):
        from apps.wecom.client import WeComSendUncertain
        send_text.side_effect = WeComSendUncertain()
        etag = self.save_template()
        key = uuid.uuid4()
        response = self.send(etag, key=key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "UNCERTAIN")
        self.assertEqual(self.send(etag, key=key).data, response.data)
        self.assertEqual(send_text.call_count, 1)
        self.assertEqual(self.send(etag).status_code, 409)

    @patch("apps.wecom.message_services.WeComClient.send_text")
    def test_explicit_upstream_rejection_is_failed_with_safe_message(self, send_text):
        from apps.wecom.client import WeComError
        send_text.side_effect = WeComError("RECIPIENT_REJECTED", "固定安全说明")
        etag = self.save_template()
        response = self.send(etag)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "FAILED")
        self.assertIsNotNone(response.data["data"]["finished_at"])

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "test-id"})
    def test_accepted_upstream_but_failed_local_finalization_is_not_resent(self, send_text):
        from django.db import DatabaseError
        etag = self.save_template()
        key = uuid.uuid4()
        with patch("apps.wecom.message_services.finish_attempt", side_effect=DatabaseError("local write failed")):
            self.client.raise_request_exception = False
            self.assertEqual(self.send(etag, key=key).status_code, 500)
        self.client.raise_request_exception = True
        replay = self.send(etag, key=key)
        self.assertEqual(replay.status_code, 200)
        self.assertIn(replay.data["data"]["status"], ("PROCESSING", "UNCERTAIN"))
        self.assertEqual(send_text.call_count, 1)

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "test-id"})
    def test_attempt_lookup_by_key_is_paginated_and_omits_internal_snapshots(self, send_text):
        key = uuid.uuid4()
        self.send(self.save_template(), key=key)
        response = self.client.get(ATTEMPTS_URL, {"idempotency_key": str(key), "page_size": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["idempotency_key"], str(key))
        self.assertNotIn("rendered_body", response.data["data"][0])
        self.assertEqual(self.client.get(ATTEMPTS_URL, {"idempotency_key": "bad"}).status_code, 400)
        self.assertEqual(self.client.get(ATTEMPTS_URL, {"page_size": 101}).status_code, 400)

    @patch("apps.wecom.message_services.WeComClient.send_text", return_value={"msgid": "test-id"})
    def test_abandoned_processing_attempt_is_shown_uncertain_without_get_writing_database(self, send_text):
        key = uuid.uuid4()
        etag = self.save_template()
        self.send(etag, key=key)
        models.WeComMessageAttempt.objects.update(status="PROCESSING", finished_at=None,
                                                  created_at=timezone.now() - timedelta(minutes=2))
        response = self.client.get(ATTEMPTS_URL, {"idempotency_key": str(key)})
        self.assertEqual(response.data["data"][0]["status"], "UNCERTAIN")
        self.assertEqual(models.WeComMessageAttempt.objects.get().status, "PROCESSING")
        self.assertEqual(self.send(etag, key=key).data["data"]["status"], "UNCERTAIN")
        self.assertEqual(send_text.call_count, 1)


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True)
class WeComMessageConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.admin, employee_code="MSG_CONCURRENT_ADMIN", display_name="管理员")
        config = models.WeComConfig.objects.create(secret_ciphertext=encrypt_secret("message-test-secret"))
        user = get_user_model().objects.create_user("concurrent-message-member")
        employee = Employee.objects.create(user=user, employee_code="MSG_CONCURRENT_MEMBER", display_name="测试员工")
        binding = models.WeComBinding.objects.create(employee=employee, corp_id=config.corp_id,
            user_id="Message.Member", member_name="测试成员", source="MANUAL")
        self.client = APIClient()
        self.client.force_login(self.admin)
        initial = self.client.get(TEMPLATE_URL)["ETag"]
        response = self.client.patch(TEMPLATE_URL, {"name": "通知", "body": "{{消息内容}}"}, format="json", HTTP_IF_MATCH=initial)
        self.etag = response["ETag"]
        self.data = {"binding_id": str(binding.pk), "message_content": "并发消息", "idempotency_key": str(uuid.uuid4())}

    def test_concurrent_requests_share_one_committed_attempt_without_holding_transaction_during_send(self):
        started, finish = Event(), Event()
        observed_transactions = []

        def external_send(user_id, body):
            observed_transactions.append(connection.in_atomic_block)
            started.set()
            if not finish.wait(timeout=15):
                raise TimeoutError("test barrier timed out")
            return {"msgid": "concurrent-id"}

        def request():
            close_old_connections()
            try:
                client = APIClient()
                client.force_login(get_user_model().objects.get(pk=self.admin.pk))
                return client.post(SEND_URL, self.data, format="json", HTTP_IF_MATCH=self.etag)
            finally:
                connections.close_all()

        with patch("apps.wecom.message_services.WeComClient.send_text", side_effect=external_send) as sender:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(request)
                try:
                    self.assertTrue(started.wait(timeout=15))
                    duplicate = self.client.post(SEND_URL, self.data, format="json", HTTP_IF_MATCH=self.etag)
                    self.assertEqual(duplicate.status_code, 200, duplicate.data)
                    self.assertEqual(duplicate.data["data"]["status"], "PROCESSING")
                    other_key = {**self.data, "idempotency_key": str(uuid.uuid4())}
                    self.assertEqual(self.client.post(SEND_URL, other_key, format="json", HTTP_IF_MATCH=self.etag).status_code, 409)
                    self.assertEqual(models.WeComMessageAttempt.objects.count(), 1)
                finally:
                    finish.set()
                accepted = future.result(timeout=20)
            self.assertEqual(accepted.status_code, 200, accepted.data)
            self.assertEqual(accepted.data["data"]["status"], "ACCEPTED")
            self.assertEqual(accepted.data["data"]["id"], duplicate.data["data"]["id"])
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(observed_transactions, [False])
