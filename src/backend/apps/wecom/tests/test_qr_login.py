from datetime import timedelta
from http.cookies import SimpleCookie
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.login_records import login_account_id
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import OAuthState, WeComBinding, WeComConfig


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True)
class WeComQRLoginTests(TestCase):
    url = "/api/auth/wecom/qr/"

    def setUp(self):
        self.config = WeComConfig.objects.create(secret_ciphertext=encrypt_secret("qr-test-secret"), enabled=True)
        self.client = self.browser()

    def browser(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)
        client.credentials(HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        return client

    def start(self, client=None, next_path="/"):
        response = (client or self.client).post(self.url, {"next": next_path}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.data

    def cancel(self, state, client=None):
        return (client or self.client).delete(self.url, {"state": state}, format="json")

    def callback(self, state, client=None):
        return (client or self.client).get("/api/auth/wecom/callback/", {"state": state, "code": "qr-one-use-code"})

    def mock_member(self, client_class):
        client_class.return_value.get_identity.return_value = {"userid": "QR.Member", "corpid": self.config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "QR.Member", "name": "扫码成员", "status": 1}

    def existing_employee(self, *, active=True, created_account=False):
        account = get_user_model().objects.create_user("qr_existing", password="original-password", is_active=active)
        employee = Employee.objects.create(user=account, employee_code="QR_EXISTING", display_name="原有员工")
        WeComBinding.objects.create(corp_id=self.config.corp_id, user_id="QR.Member", employee=employee,
                                    member_name="扫码成员", source="MANUAL", created_account=created_account)
        return employee

    def test_initialize_returns_only_public_sdk_parameters_and_session_bound_expiry(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.data
        self.assertEqual(set(payload), {"login_type", "appid", "agentid", "redirect_uri", "state", "expires_at"})
        self.assertEqual(payload["login_type"], "CorpApp")
        self.assertEqual(payload["appid"], self.config.corp_id)
        self.assertEqual(payload["agentid"], self.config.agent_id)
        self.assertEqual(payload["redirect_uri"], self.config.erp_origin + "/api/auth/wecom/callback/")
        self.assertRegex(payload["state"], r"^[A-Za-z0-9_-]{43}$")
        row = OAuthState.objects.get()
        self.assertNotEqual(row.state_digest, payload["state"])
        self.assertNotEqual(row.session_digest, self.client.session.session_key)
        self.assertEqual(parse_datetime(payload["expires_at"]), row.expires_at)
        self.assertLessEqual(row.expires_at, timezone.now() + timedelta(minutes=5))
        self.assertIsNone(row.initiator_user_id)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("qr-test-secret", str(payload))
        self.assertFalse(Employee.objects.exists())

    def test_anonymous_post_and_delete_require_csrf(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        for method, data in ((anonymous.post, {}), (anonymous.delete, {"state": "A" * 43})):
            response = method(self.url, data, format="json")
            self.assertEqual(response.status_code, 403)
            self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(OAuthState.objects.exists())

    def test_get_is_not_allowed_and_does_not_create_challenge(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(OAuthState.objects.exists())

    def test_disabled_or_incomplete_configuration_returns_clear_error_without_challenge(self):
        for enabled, secret in ((False, self.config.secret_ciphertext), (True, "")):
            self.config.enabled, self.config.secret_ciphertext = enabled, secret
            self.config.save()
            response = self.client.post(self.url, {}, format="json")
            self.assertEqual(response.status_code, 503, response.content)
            self.assertIn("配置", str(response.data["detail"]))
        self.assertFalse(OAuthState.objects.exists())

    @patch("apps.wecom.selectors.schema_is_ready", return_value=False)
    def test_missing_schema_returns_unavailable_without_touching_challenges(self, schema):
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 503)
        self.assertFalse(OAuthState.objects.exists())

    def test_rejects_external_or_looping_next_and_unknown_fields(self):
        for next_path in ("https://attacker.example", "//attacker.example", "/\\attacker.example", "/%2fattacker.example",
                          "/%5cattacker.example", "/\nattacker.example", "/login", "/auth/wecom-error", "/api/auth/logout/", "/admin/"):
            with self.subTest(next_path=next_path):
                self.assertEqual(self.client.post(self.url, {"next": next_path}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"redirect_uri": "https://attacker.example"}, format="json").status_code, 400)
        self.assertFalse(OAuthState.objects.exists())

    @patch("apps.wecom.services.WeComClient")
    def test_cancel_is_idempotent_and_prevents_callback(self, client_class):
        challenge = self.start()
        self.assertEqual(self.cancel(challenge["state"]).status_code, 204)
        self.assertEqual(self.cancel(challenge["state"]).status_code, 204)
        self.assertIsNotNone(OAuthState.objects.get().consumed_at)
        self.assertIn("reason=STATE_INVALID", self.callback(challenge["state"]).url)
        client_class.assert_not_called()

    def test_cancel_unknown_state_is_idempotent_and_does_not_create_session(self):
        self.assertEqual(self.cancel("A" * 43).status_code, 204)
        self.assertFalse(OAuthState.objects.exists())
        self.assertNotIn("sessionid", self.client.cookies)

    def test_cancel_rejects_invalid_shape(self):
        for data in ({}, {"state": "bad"}, {"state": "A" * 44}, {"state": "A" * 43, "other": True}):
            self.assertEqual(self.client.delete(self.url, data, format="json").status_code, 400)

    @patch("apps.wecom.services.WeComClient")
    def test_foreign_browser_cannot_cancel_or_consume_state(self, client_class):
        self.mock_member(client_class)
        challenge = self.start()
        other = self.browser()
        self.assertEqual(self.cancel(challenge["state"], other).status_code, 204)
        self.assertIsNone(OAuthState.objects.get().consumed_at)
        self.assertIn("reason=STATE_INVALID", self.callback(challenge["state"], other).url)
        self.assertEqual(self.callback(challenge["state"]).url, "/auth/waiting-role")
        self.assertEqual(WeComBinding.objects.count(), 1)

    @patch("apps.wecom.services.WeComClient")
    def test_first_qr_login_creates_passwordless_employee_and_preserves_waiting_gate(self, client_class):
        self.mock_member(client_class)
        self.assertEqual(self.callback(self.start(next_path="/customers")["state"]).url, "/auth/waiting-role")
        employee = Employee.objects.get()
        self.assertFalse(employee.user.has_usable_password())
        self.assertFalse(employee.user.is_staff)
        self.assertFalse(employee.user.is_superuser)
        self.assertTrue(self.client.get("/api/auth/me/").data["user"]["waiting_for_role"])
        self.assertEqual(self.client.get("/api/v1/").status_code, 403)
        record = AuditLog.objects.get(object_type="AUTH_ACCOUNT", object_id=login_account_id(employee.user_id))
        self.assertEqual(record.after_data["method"], "WECOM")

    @patch("apps.wecom.services.WeComClient")
    def test_existing_member_reuses_account_and_returns_to_validated_business_path(self, client_class):
        self.mock_member(client_class)
        employee = self.existing_employee()
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="QR login role"),
                                          role_code="QR_LOGIN_ROLE", display_name="扫码业务角色")
        permission = Permission.objects.get(content_type__app_label="reference_data", codename="view_country")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.add(permission)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        state = self.start(next_path="/customers?tab=mine")["state"]
        self.assertEqual(self.callback(state).url, "/customers?tab=mine")
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(int(self.client.session["_auth_user_id"]), employee.user_id)
        self.assertTrue(employee.user.check_password("original-password"))
        self.assertIn("reason=STATE_INVALID", self.callback(state).url)
        self.assertEqual(AuditLog.objects.filter(object_type="AUTH_ACCOUNT", object_id=login_account_id(employee.user_id)).count(), 1)

    @patch("apps.wecom.services.WeComClient")
    def test_expired_or_reconfigured_challenge_does_not_contact_upstream(self, client_class):
        expired = self.start()["state"]
        OAuthState.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIn("reason=STATE_INVALID", self.callback(expired).url)
        state = self.start()["state"]
        self.config.agent_id = "1000020"
        self.config.save()
        self.assertIn("reason=CONFIGURATION_ERROR", self.callback(state).url)
        client_class.assert_not_called()

    @patch("apps.wecom.services.WeComClient")
    def test_password_login_after_qr_creation_prevents_old_qr_overwriting_identity(self, client_class):
        state = self.start()["state"]
        employee = self.existing_employee()
        login = self.client.post("/api/auth/login/", {"username": employee.user.username, "password": "original-password"}, format="json")
        self.assertEqual(login.status_code, 200, login.content)
        self.assertIn("reason=STATE_INVALID", self.callback(state).url)
        self.assertEqual(int(self.client.session["_auth_user_id"]), employee.user_id)
        client_class.assert_not_called()

    @patch("apps.wecom.services.WeComClient")
    def test_password_login_during_upstream_lookup_rejects_already_started_qr_callback(self, client_class):
        self.mock_member(client_class)
        state = self.start()["state"]
        employee = self.existing_employee()
        other_tab = APIClient(enforce_csrf_checks=True)
        other_tab.cookies = SimpleCookie(self.client.cookies.output(header="", sep=";"))
        other_tab.credentials(HTTP_X_CSRFTOKEN=other_tab.cookies["csrftoken"].value)

        def complete_password_login(user_id):
            response = other_tab.post("/api/auth/login/", {
                "username": employee.user.username, "password": "original-password",
            }, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            return {"userid": user_id, "name": "其他扫码成员", "status": 1}

        client_class.return_value.get_identity.return_value["userid"] = "Other.QR.Member"
        client_class.return_value.get_member.side_effect = complete_password_login
        response = self.callback(state)
        self.assertIn("reason=IDENTITY_MISMATCH", response.url)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(int(other_tab.session["_auth_user_id"]), employee.user_id)

    @patch("apps.wecom.services.WeComClient")
    def test_logout_during_upstream_lookup_does_not_recreate_session(self, client_class):
        self.mock_member(client_class)
        state = self.start()["state"]
        other_tab = APIClient(enforce_csrf_checks=True)
        other_tab.cookies = SimpleCookie(self.client.cookies.output(header="", sep=";"))
        other_tab.credentials(HTTP_X_CSRFTOKEN=other_tab.cookies["csrftoken"].value)

        def finish_logout(user_id):
            self.assertEqual(other_tab.post("/api/auth/logout/", {}, format="json").status_code, 200)
            return {"userid": user_id, "name": "扫码成员", "status": 1}

        client_class.return_value.get_member.side_effect = finish_logout
        response = self.callback(state)
        self.assertIn("reason=IDENTITY_MISMATCH", response.url)
        self.assertNotIn("sessionid", response.cookies)
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(WeComBinding.objects.exists())
        self.assertFalse(get_user_model().objects.exists())

    @patch("apps.wecom.services.WeComClient")
    def test_logged_in_account_is_not_silently_replaced_by_another_member(self, client_class):
        self.mock_member(client_class)
        employee = self.existing_employee()
        self.client.force_login(employee.user)
        state = self.start()["state"]
        client_class.return_value.get_identity.return_value["userid"] = "Other.Member"
        client_class.return_value.get_member.return_value["userid"] = "Other.Member"
        self.assertIn("reason=IDENTITY_MISMATCH", self.callback(state).url)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(int(self.client.session["_auth_user_id"]), employee.user_id)

    @patch("apps.wecom.services.WeComClient")
    def test_inactive_bound_account_cannot_be_reenabled_by_scan(self, client_class):
        self.mock_member(client_class)
        employee = self.existing_employee(active=False)
        self.assertIn("reason=ACCOUNT_INACTIVE", self.callback(self.start()["state"]).url)
        employee.user.refresh_from_db()
        self.assertFalse(employee.user.is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(DEBUG=True)
    @patch("apps.wecom.services.cancel_oauth_state", side_effect=RuntimeError("cancel failed"))
    def test_cancel_exception_does_not_expose_state_in_debug_page(self, cancel):
        self.client.raise_request_exception = False
        state = "PRIVATE_QR_STATE_" + "X" * 25 + "Z"
        self.assertEqual(len(state), 43)
        response = self.cancel(state)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(state, response.content.decode())
        self.assertIn("no-store", response["Cache-Control"])
