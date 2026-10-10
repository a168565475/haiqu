from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee

from ..models import EmailAccount, EmailAccountTestStatus
from ..services import (
    default_email_account_for_employee,
    decrypt_smtp_password,
    encrypt_smtp_password,
    send_via_email_account,
)


FERNET_KEY_A = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
FERNET_KEY_B = "ZmVkY2JhOTg3NjU0MzIxMGZlZGNiYTk4NzY1NDMyMTA="


@override_settings(EMAIL_ACCOUNT_FERNET_KEYS=[FERNET_KEY_A])
class EmailAccountApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="mail_account_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="MAIL_ACCOUNT_USER",
            display_name="邮件账户测试员",
        )
        self.other_user = user_model.objects.create_user(username="mail_account_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="MAIL_ACCOUNT_OTHER",
            display_name="其他邮件账户测试员",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        data = {
            "display_name": "工作邮箱",
            "sender_name": "测试业务员",
            "sender_email": "sender@example.test",
            "smtp_host": "smtp.example.test",
            "smtp_port": 587,
            "smtp_username": "sender@example.test",
            "smtp_password": "app-password",
            "smtp_security": "STARTTLS",
            "is_enabled": True,
        }
        data.update(overrides)
        return data

    def create_account(self, **overrides):
        response = self.client.post("/api/v1/email-accounts/", self.payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_account_is_scoped_to_active_employee_and_password_never_returns(self):
        created = self.create_account()

        self.assertTrue(created.data["data"]["password_configured"])
        self.assertNotIn("smtp_password", created.data["data"])
        self.assertNotIn("smtp_password_ciphertext", created.data["data"])
        self.assertEqual(self.client.get("/api/v1/email-accounts/").data["data"].__len__(), 1)

        self.client.force_authenticate(self.other_user)
        self.assertEqual(self.client.get("/api/v1/email-accounts/").data["data"], [])
        hidden = self.client.get(f"/api/v1/email-accounts/{created.data['data']['id']}/")
        self.assertEqual(hidden.status_code, 404)

    def test_only_one_enabled_default_account_is_allowed(self):
        first = self.create_account(display_name="主邮箱")
        second = self.create_account(display_name="备用邮箱", sender_email="backup@example.test")

        first_detail = self.client.get(f"/api/v1/email-accounts/{first.data['data']['id']}/")
        set_first = self.client.post(
            f"/api/v1/email-accounts/{first.data['data']['id']}/set-default/",
            {},
            format="json",
            HTTP_IF_MATCH=first_detail.headers["ETag"],
        )
        self.assertEqual(set_first.status_code, 200, set_first.data)

        second_detail = self.client.get(f"/api/v1/email-accounts/{second.data['data']['id']}/")
        set_second = self.client.post(
            f"/api/v1/email-accounts/{second.data['data']['id']}/set-default/",
            {},
            format="json",
            HTTP_IF_MATCH=second_detail.headers["ETag"],
        )
        self.assertEqual(set_second.status_code, 200, set_second.data)

        first_row = EmailAccount.objects.get(pk=first.data["data"]["id"])
        second_row = EmailAccount.objects.get(pk=second.data["data"]["id"])
        self.assertFalse(first_row.is_default)
        self.assertTrue(second_row.is_default)

        second_detail = self.client.get(f"/api/v1/email-accounts/{second_row.pk}/")
        disabled = self.client.patch(
            f"/api/v1/email-accounts/{second_row.pk}/",
            {"is_enabled": False},
            format="json",
            HTTP_IF_MATCH=second_detail.headers["ETag"],
        )
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertFalse(disabled.data["data"]["is_default"])

    def test_missing_default_account_blocks_quotation_sender_resolution(self):
        with self.assertRaisesMessage(Conflict, "未配置启用的默认邮件账户"):
            default_email_account_for_employee(self.employee)

    @patch("apps.email_accounts.api.views.send_test_email")
    def test_test_send_persists_status_without_storing_recipient(self, send_test):
        created = self.create_account()
        detail = self.client.get(f"/api/v1/email-accounts/{created.data['data']['id']}/")
        tested = self.client.post(
            f"/api/v1/email-accounts/{created.data['data']['id']}/test-send/",
            {"recipient": "designated-recipient@example.test"},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )

        self.assertEqual(tested.status_code, 200, tested.data)
        self.assertEqual(tested.data["data"]["last_test_status"], EmailAccountTestStatus.SUCCESS)
        send_test.assert_called_once()
        audit = AuditLog.objects.filter(object_type="EMAIL_ACCOUNT", action="TEST_SEND_SUCCEEDED").get()
        self.assertNotIn("designated-recipient@example.test", str(audit.after_data))
        self.assertNotIn("app-password", str(audit.after_data))

    @patch("apps.email_accounts.api.views.send_test_email", side_effect=Conflict("邮件服务未接受投递"))
    def test_failed_test_send_records_failure_status(self, _send_test):
        created = self.create_account()
        detail = self.client.get(f"/api/v1/email-accounts/{created.data['data']['id']}/")
        response = self.client.post(
            f"/api/v1/email-accounts/{created.data['data']['id']}/test-send/",
            {"recipient": "designated-recipient@example.test"},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )

        self.assertEqual(response.status_code, 409, response.data)
        account = EmailAccount.objects.get(pk=created.data["data"]["id"])
        self.assertEqual(account.last_test_status, EmailAccountTestStatus.FAILED)

    def test_password_supports_key_rotation(self):
        encrypted = encrypt_smtp_password("rotation-password")
        account = EmailAccount.objects.create(
            employee=self.employee,
            display_name="轮换测试",
            sender_email="rotation@example.test",
            smtp_host="smtp.example.test",
            smtp_port=465,
            smtp_username="rotation@example.test",
            smtp_password_ciphertext=encrypted,
            smtp_security="SSL",
        )
        with self.settings(EMAIL_ACCOUNT_FERNET_KEYS=[FERNET_KEY_B, FERNET_KEY_A]):
            self.assertEqual(decrypt_smtp_password(account), "rotation-password")

    @patch("apps.email_accounts.services.EmailMultiAlternatives")
    def test_html_message_includes_a_plain_text_alternative(self, email_message):
        created = self.create_account()
        account = EmailAccount.objects.get(pk=created.data["data"]["id"])
        html_body = "<p>Dear Buyer</p><p>Please find the quotation attached.<br>Thank you.</p>"
        email_message.return_value.send.return_value = 1

        send_via_email_account(
            account=account,
            recipient="buyer@example.test",
            subject="Quotation",
            body=html_body,
            html_body=html_body,
        )

        self.assertEqual(
            email_message.call_args.kwargs["body"],
            "Dear Buyer\nPlease find the quotation attached.\nThank you.",
        )
        email_message.return_value.attach_alternative.assert_called_once_with(html_body, "text/html")
