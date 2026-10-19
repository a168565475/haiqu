from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.wecom.credentials import decrypt_secret, encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig


TEST_CREDENTIALS = {"secret": "test-reveal-secret-801", "callback_token": "TestRevealToken801", "callback_aes_key": "R" * 43}


@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True,
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()],
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComConfigRevealTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.admin_employee = Employee.objects.create(user=self.admin, employee_code="REVEAL_ADMIN", display_name="测试管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)

    def config(self, **kwargs):
        return WeComConfig.objects.create(**{field + "_ciphertext": encrypt_secret(value) for field, value in TEST_CREDENTIALS.items()}, **kwargs)

    def assert_not_cached(self, response):
        directives = response.get("Cache-Control", "")
        self.assertIn("no-store", directives)
        self.assertIn("private", directives)

    def assert_credentials(self, response, values=TEST_CREDENTIALS):
        self.assertEqual(response.status_code, 200)
        for field, value in values.items():
            self.assertEqual(response.data["data"].get(field), value)
        self.assertEqual(response.data["data"].get("credential_read_errors"), [])
        self.assert_not_cached(response)

    def test_admin_get_returns_actual_saved_credentials(self):
        config = self.config()
        response = self.client.get("/api/v1/wecom/config/")
        self.assert_credentials(response)
        for field in TEST_CREDENTIALS:
            self.assertNotIn(getattr(config, field + "_ciphertext"), response.content.decode())

    def test_unconfigured_response_has_empty_credential_strings_without_creating_row(self):
        response = self.client.get("/api/v1/wecom/config/")
        self.assert_credentials(response, {field: "" for field in TEST_CREDENTIALS})
        self.assertEqual(response["ETag"], '"wecom-unconfigured"')
        self.assertFalse(WeComConfig.objects.exists())

    def test_patch_and_following_get_return_values_but_storage_and_audit_remain_protected(self):
        response = self.client.patch("/api/v1/wecom/config/", TEST_CREDENTIALS, format="json", HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assert_credentials(response)
        self.assert_credentials(self.client.get("/api/v1/wecom/config/"))
        config = WeComConfig.objects.get()
        audits = str(list(AuditLog.objects.filter(object_type="WECOM").values("before_data", "after_data")))
        for field, plaintext in TEST_CREDENTIALS.items():
            ciphertext = getattr(config, field + "_ciphertext")
            self.assertNotEqual(ciphertext, plaintext)
            self.assertEqual(decrypt_secret(ciphertext), plaintext)
            self.assertNotIn(plaintext, audits)
            self.assertNotIn(ciphertext, audits)

    def test_anonymous_ordinary_inactive_and_waiting_accounts_cannot_read_credentials(self):
        self.config()
        ordinary = get_user_model().objects.create_user("reveal_ordinary")
        ordinary_employee = Employee.objects.create(user=ordinary, employee_code="REVEAL_USER", display_name="普通员工")
        inactive = get_user_model().objects.create_user("reveal_inactive", is_active=False)
        Employee.objects.create(user=inactive, employee_code="REVEAL_INACTIVE", display_name="停用账号")
        left = get_user_model().objects.create_user("reveal_left")
        Employee.objects.create(user=left, employee_code="REVEAL_LEFT", display_name="离职员工", status="LEFT")
        waiting = get_user_model().objects.create_user("reveal_waiting")
        waiting_employee = Employee.objects.create(user=waiting, employee_code="REVEAL_WAITING", display_name="等待授权")
        WeComBinding.objects.create(corp_id=WeComConfig().corp_id, user_id="test.waiting", member_name="测试成员",
                                     employee=waiting_employee, source="AUTO", created_account=True)
        for user, expected in ((None, 401), (ordinary, 403), (inactive, 401), (left, 401), (waiting, 403)):
            with self.subTest(username=user.username if user else "anonymous"):
                browser = APIClient()
                if user:
                    browser.force_login(user)
                response = browser.get("/api/v1/wecom/config/")
                self.assertEqual(response.status_code, expected)
                self.assert_not_cached(response)
                for value in TEST_CREDENTIALS.values():
                    self.assertNotIn(value, response.content.decode())
        ordinary_employee.refresh_from_db()
        self.assertEqual(ordinary_employee.user_id, ordinary.pk)

    def test_validation_etag_csrf_and_method_errors_are_not_cached(self):
        config = self.config()
        url = "/api/v1/wecom/config/"
        responses = [
            (self.client.patch(url, {}, format="json"), 428),
            (self.client.patch(url, {}, format="json", HTTP_IF_MATCH='"stale"'), 412),
            (self.client.patch(url, {"callback_token": "invalid token"}, format="json", HTTP_IF_MATCH=etag_for_instance(config)), 400),
            (self.client.put(url, {}, format="json"), 405),
        ]
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        responses.append((csrf_client.patch(url, {}, format="json", HTTP_IF_MATCH=etag_for_instance(config)), 403))
        for response, expected in responses:
            self.assertEqual(response.status_code, expected)
            self.assert_not_cached(response)

    def test_each_failed_decryption_marks_only_the_unreadable_field(self):
        config = self.config()
        for field in TEST_CREDENTIALS:
            with self.subTest(field=field):
                ciphertext_field = field + "_ciphertext"
                original = getattr(config, ciphertext_field)
                setattr(config, ciphertext_field, "invalid-private-ciphertext")
                config.save()
                response = self.client.get("/api/v1/wecom/config/")
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.data["data"][field])
                self.assertEqual(response.data["data"]["credential_read_errors"], [field])
                self.assertTrue(response.data["data"]["has_" + field])
                for readable_field, value in TEST_CREDENTIALS.items():
                    if readable_field != field:
                        self.assertEqual(response.data["data"][readable_field], value)
                self.assert_not_cached(response)
                self.assertNotIn("invalid-private-ciphertext", response.content.decode())
                setattr(config, ciphertext_field, original)
                config.save()

    def test_missing_decryption_key_does_not_prevent_disabling_the_entry(self):
        config = self.config(enabled=True)
        before = {field: getattr(config, field + "_ciphertext") for field in TEST_CREDENTIALS}
        with override_settings(WECOM_FERNET_KEYS=[]):
            response = self.client.patch("/api/v1/wecom/config/", {"enabled": False}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["data"]["enabled"])
        self.assertEqual(response.data["data"]["credential_read_errors"], list(TEST_CREDENTIALS))
        self.assert_not_cached(response)
        config.refresh_from_db()
        self.assertFalse(config.enabled)
        for field, ciphertext in before.items():
            self.assertIsNone(response.data["data"][field])
            self.assertEqual(getattr(config, field + "_ciphertext"), ciphertext)

    def test_replacing_unreadable_credentials_restores_the_configuration(self):
        config = self.config(enabled=True, last_check_status="SUCCESS", last_checked_at=timezone.now())
        for field in TEST_CREDENTIALS:
            setattr(config, field + "_ciphertext", "invalid-private-ciphertext")
        config.save()
        response = self.client.patch("/api/v1/wecom/config/", TEST_CREDENTIALS, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assert_credentials(response)
        self.assertTrue(response.data["data"]["configuration_complete"])
        self.assertTrue(response.data["data"]["enabled"])
        self.assertEqual(response.data["data"]["last_check_status"], "NOT_CHECKED")
        config.refresh_from_db()
        audits = str(list(AuditLog.objects.filter(object_type="WECOM").values("before_data", "after_data")))
        for field, value in TEST_CREDENTIALS.items():
            ciphertext = getattr(config, field + "_ciphertext")
            self.assertEqual(decrypt_secret(ciphertext), value)
            self.assertNotEqual(ciphertext, value)
            self.assertNotIn(value, audits)
            self.assertNotIn(ciphertext, audits)
        self.assertNotIn("invalid-private-ciphertext", audits)

    @patch("apps.wecom.services.WeComClient")
    def test_unreadable_callback_credentials_do_not_block_web_connection_check(self, client_class):
        config = self.config()
        config.callback_token_ciphertext = "invalid-private-token"
        config.callback_aes_key_ciphertext = "invalid-private-aes-key"
        config.save()
        response = self.client.post("/api/v1/wecom/config/check/", {}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 200)
        self.assert_not_cached(response)
        client_class.return_value.check_connection.assert_called_once_with()
        self.assertEqual(response.data["data"]["secret"], TEST_CREDENTIALS["secret"])
        self.assertIsNone(response.data["data"]["callback_token"])
        self.assertIsNone(response.data["data"]["callback_aes_key"])
        self.assertEqual(response.data["data"]["credential_read_errors"], ["callback_token", "callback_aes_key"])
        self.assertEqual(response.data["data"]["last_check_status"], "SUCCESS")
        self.assertTrue(response.data["data"]["configuration_complete"])
        self.assertNotIn("invalid-private", response.content.decode())

    @patch("apps.wecom.services.WeComClient")
    def test_unreadable_secret_blocks_connection_check_with_uncached_safe_conflict(self, client_class):
        config = self.config()
        config.secret_ciphertext = "invalid-private-secret"
        config.save()
        response = self.client.post("/api/v1/wecom/config/check/", {}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 409)
        self.assert_not_cached(response)
        client_class.assert_not_called()
        self.assertNotIn("invalid-private-secret", response.content.decode())

    def test_resubmitting_unchanged_plaintext_preserves_check_status_and_ciphertext(self):
        checked_at = timezone.now()
        config = self.config(last_check_status="SUCCESS", last_check_message="固定安全测试结果", last_checked_at=checked_at)
        before = {field: getattr(config, field + "_ciphertext") for field in TEST_CREDENTIALS}
        response = self.client.patch("/api/v1/wecom/config/", TEST_CREDENTIALS, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assert_credentials(response)
        config.refresh_from_db()
        self.assertEqual(config.last_check_status, "SUCCESS")
        self.assertEqual(config.last_checked_at, checked_at)
        for field, ciphertext in before.items():
            self.assertEqual(getattr(config, field + "_ciphertext"), ciphertext)

    def test_only_changed_login_credentials_invalidate_connection_result(self):
        config = self.config(last_check_status="SUCCESS", last_checked_at=timezone.now())
        response = self.client.patch("/api/v1/wecom/config/", {"callback_token": "ChangedCallback801"}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["last_check_status"], "SUCCESS")
        response = self.client.patch("/api/v1/wecom/config/", {"secret": "changed-test-secret-801"}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"].get("secret"), "changed-test-secret-801")
        self.assertEqual(response.data["data"]["last_check_status"], "NOT_CHECKED")
        self.assertIsNone(response.data["data"]["last_checked_at"])

    @patch("apps.wecom.services.WeComClient")
    def test_connection_check_response_reveals_values_without_auditing_them(self, client_class):
        config = self.config()
        client_class.return_value.check_connection.return_value = {"ok": True}
        response = self.client.post("/api/v1/wecom/config/check/", {}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assert_credentials(response)
        self.assertEqual(response.data["data"]["last_check_status"], "SUCCESS")
        audits = str(list(AuditLog.objects.filter(object_type="WECOM").values("before_data", "after_data")))
        for value in TEST_CREDENTIALS.values():
            self.assertNotIn(value, audits)

    @override_settings(DEBUG=True)
    @patch("apps.wecom.views.ConfigResponseSerializer", side_effect=RuntimeError("response serializer failed"))
    def test_response_failure_is_not_cached_and_debug_does_not_expose_decrypted_values(self, serializer):
        self.config()
        self.client.raise_request_exception = False
        response = self.client.get("/api/v1/wecom/config/")
        self.assertEqual(response.status_code, 500)
        self.assert_not_cached(response)
        for value in TEST_CREDENTIALS.values():
            self.assertNotIn(value, response.content.decode())

    @override_settings(DEBUG=True)
    @patch("django.contrib.auth.middleware.get_user", side_effect=OperationalError("identity query failed"))
    def test_early_auth_failure_is_not_cached_or_allowed_to_expose_submitted_credentials(self, identity):
        self.client.raise_request_exception = False
        response = self.client.patch("/api/v1/wecom/config/", TEST_CREDENTIALS, format="json")
        self.assertEqual(response.status_code, 500)
        self.assert_not_cached(response)
        for value in TEST_CREDENTIALS.values():
            self.assertNotIn(value, response.content.decode())
