"""卡片链接只读内容及企微安全回跳；外部企微网络为隔离测试替身。"""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import Employee
from apps.wecom.models import OAuthState
from apps.wecom.tests.test_notifications import INBOX_URL, SETTINGS, NotificationFixture


@override_settings(**SETTINGS)
class NotificationCardLinkTests(NotificationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.recipient = self.register().recipients.get()
        self.url = f"{INBOX_URL}{self.recipient.pk}/"
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.member.user)

    def test_opening_own_notification_returns_safe_content_without_marking_read(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(str(response.data["data"]["id"]), str(self.recipient.pk))
        self.assertIn(self.receipt.receipt_number, response.data["data"]["body"])
        self.assertTrue(response.data["data"]["target_accessible"])
        self.recipient.refresh_from_db()
        self.assertIsNone(self.recipient.read_at)
        self.assertEqual(self.client.get(INBOX_URL + "unread-count/").data["unread_count"], 1)
        self.assertIn("no-store", response["Cache-Control"])

    def test_other_employee_even_superuser_and_unknown_id_share_not_found(self):
        user = get_user_model().objects.create_superuser("card_link_other", "", "test-password")
        Employee.objects.create(user=user, employee_code="CARD_LINK_OTHER", display_name="其他管理员")
        self.client.force_login(user)
        own = self.client.get(self.url)
        absent = self.client.get(f"{INBOX_URL}{uuid4()}/")
        self.assertEqual(own.status_code, 404)
        self.assertEqual(absent.status_code, 404)
        self.assertEqual(own.data["error"]["message"], absent.data["error"]["message"])
        self.assertNotIn(self.receipt.receipt_number, str(own.data))

    def test_revoked_permission_masks_body_and_target(self):
        RoleActionGrant.objects.filter(role=self.role).delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["data"]["title"], "通知内容不可访问")
        self.assertIsNone(response.data["data"]["target"])
        self.assertFalse(response.data["data"]["target_accessible"])
        self.assertNotIn(self.receipt.receipt_number, response.data["data"]["body"])
        self.recipient.refresh_from_db()
        self.assertIsNone(self.recipient.read_at)

    def test_stale_notification_masks_body_without_marking_read(self):
        event = self.recipient.event
        event.status = "STALE"
        event.save(update_fields=["status"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["data"]["title"], "通知内容不可访问")
        self.assertIsNone(response.data["data"]["target"])
        self.assertNotIn(self.receipt.receipt_number, response.data["data"]["body"])
        self.recipient.refresh_from_db()
        self.assertIsNone(self.recipient.read_at)


@override_settings(**SETTINGS)
class WeComNotificationReturnTests(NotificationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.config, self.binding = self.configure_wecom()
        self.browser = APIClient()
        self.path = f"/?notification={uuid4()}"

    def start(self, browser=None):
        response = (browser or self.browser).get("/api/auth/wecom/start/", {"next": self.path})
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlsplit(response.url).query)["state"][0]

    @patch("apps.wecom.services.WeComClient")
    def test_oauth_returns_to_session_bound_notification_not_callback_input(self, client_class):
        client_class.return_value.get_identity.return_value = {"userid": self.binding.user_id, "corpid": self.config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": self.binding.user_id, "name": "通知成员", "status": 1}
        state = self.start()
        response = self.browser.get("/api/auth/wecom/callback/", {
            "state": state, "code": "card-test-code", "next": "https://attacker.example",
        })
        self.assertEqual(response.url, self.path)
        self.assertNotIn(OAuthState.objects.get().state_digest, self.browser.session.get("wecom_qr_redirects", {}))
        self.assertIn("reason=STATE_INVALID", self.browser.get("/api/auth/wecom/callback/", {
            "state": state, "code": "card-test-code",
        }).url)

    @patch("apps.wecom.services.WeComClient")
    def test_another_session_cannot_consume_notification_return_state(self, client_class):
        state = self.start()
        response = APIClient().get("/api/auth/wecom/callback/", {"state": state, "code": "card-test-code"})
        self.assertIn("reason=STATE_INVALID", response.url)
        self.assertIsNone(OAuthState.objects.get().consumed_at)
        client_class.assert_not_called()

    def test_start_rejects_external_looping_duplicate_and_unknown_parameters(self):
        for path in ("https://attacker.example", "//attacker.example", "/%2fattacker.example", "/%5cattacker.example",
                     "/login", "/api/auth/logout/", "/auth/wecom-error", "/admin/", "/../login"):
            with self.subTest(path=path):
                response = self.browser.get("/api/auth/wecom/start/", {"next": path})
                self.assertIn("reason=LOGIN_FAILED", response.url)
        for query in ({"next": [self.path, "https://attacker.example"]}, {"next": self.path, "redirect_uri": "/"}):
            self.assertIn("reason=LOGIN_FAILED", self.browser.get("/api/auth/wecom/start/", query).url)
        self.assertFalse(OAuthState.objects.exists())
