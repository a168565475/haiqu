from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.credentials import CredentialError, decrypt_secret, encrypt_secret
from apps.wecom.models import OAuthState, WeComBinding, WeComConfig
from apps.wecom.selectors import waiting_for_role


TEST_KEY = Fernet.generate_key().decode()


@override_settings(WECOM_FERNET_KEYS=[TEST_KEY], ACCESS_MANAGEMENT_ENABLED=True)
class WeComIntegrationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.admin_employee = Employee.objects.create(user=self.admin, employee_code="WC_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)

    def config(self, **kwargs):
        return WeComConfig.objects.create(secret_ciphertext=encrypt_secret("test-secret"), enabled=True, **kwargs)

    def employee(self, code="WC_EXISTING", user=True):
        account = get_user_model().objects.create_user(code.lower(), password="old-password") if user else None
        return Employee.objects.create(user=account, employee_code=code, display_name="真实员工")

    def binding(self, employee, created=False, user_id="Member.One"):
        return WeComBinding.objects.create(corp_id=WeComConfig().corp_id, user_id=user_id, employee=employee,
                                           member_name="真实成员", source="MANUAL", created_account=created)

    def start(self, client=None):
        client = client or self.client
        response = client.get("/api/auth/wecom/start/")
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["scope"], ["snsapi_base"])
        return query["state"][0]

    def callback(self, state, client=None):
        return (client or self.client).get("/api/auth/wecom/callback/", {"state": state, "code": "one-use-code"})

    def mock_member(self, client_class, user_id="Member.One", name="真实成员", status=1):
        instance = client_class.return_value
        instance.get_identity.return_value = {"userid": user_id, "corpid": WeComConfig().corp_id}
        instance.get_member.return_value = {"userid": user_id, "name": name, "status": status}
        return instance

    def test_default_config_get_does_not_create_database_row(self):
        response = self.client.get("/api/v1/wecom/config/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["ETag"], '"wecom-unconfigured"')
        self.assertFalse(response.data["data"]["enabled"])
        self.assertEqual(response.data["data"]["corp_id"], "ww08890a52e3ab432d")
        self.assertEqual(WeComConfig.objects.count(), 0)

    def test_config_patch_requires_etag_and_rejects_stale_etag(self):
        url = "/api/v1/wecom/config/"
        self.assertEqual(self.client.patch(url, {"enabled": False}, format="json").status_code, 428)
        self.assertEqual(self.client.patch(url, {}, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)

    def test_config_and_oauth_fail_closed_when_rotation_drops_required_old_key(self):
        self.config()
        with override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()]):
            response = self.client.get("/api/v1/wecom/config/")
            self.assertTrue(response.data["data"]["encryption_ready"])
            self.assertFalse(response.data["data"]["configuration_complete"])
            self.assertIn("reason=CONFIGURATION_ERROR", self.client.get("/api/auth/wecom/start/").url)

    def test_config_credentials_are_encrypted_and_never_returned_or_audited(self):
        response = self.client.patch("/api/v1/wecom/config/", {
            "secret": "secret-value", "callback_token": "callbackToken123", "callback_aes_key": "A" * 43,
        }, format="json", HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 200, response.data)
        config = WeComConfig.objects.get()
        self.assertEqual(decrypt_secret(config.secret_ciphertext), "secret-value")
        self.assertEqual(decrypt_secret(config.callback_token_ciphertext), "callbackToken123")
        for value in ("secret-value", "callbackToken123", config.secret_ciphertext, config.callback_token_ciphertext):
            self.assertNotIn(value, str(response.data))
            self.assertNotIn(value, str(list(AuditLog.objects.filter(object_type="WECOM").values())))
        old_ciphertext = config.secret_ciphertext
        updated = self.client.patch("/api/v1/wecom/config/", {"secret": ""}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(WeComConfig.objects.get().secret_ciphertext, old_ciphertext)

    @override_settings(WECOM_FERNET_KEYS=[])
    def test_missing_encryption_key_fails_closed(self):
        response = self.client.patch("/api/v1/wecom/config/", {"secret": "secret-value"}, format="json",
                                     HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(WeComConfig.objects.exists())

    @override_settings(DEBUG=True)
    @patch("apps.wecom.services.encrypt_secret", side_effect=RuntimeError("encryption failed"))
    def test_debug_error_report_redacts_configuration_credentials(self, encrypt):
        self.client.raise_request_exception = False
        response = self.client.patch("/api/v1/wecom/config/", {
            "secret": "VERY_PRIVATE_SECRET_701", "callback_token": "PRIVATECALLBACK701", "callback_aes_key": "Z" * 43,
        }, format="json", HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 500)
        for value in ("VERY_PRIVATE_SECRET_701", "PRIVATECALLBACK701", "Z" * 43):
            self.assertNotIn(value, response.content.decode())
        self.assertFalse(WeComConfig.objects.exists())

    @override_settings(DEBUG=True)
    @patch("apps.wecom.services.WeComClient")
    def test_debug_error_report_redacts_oauth_query_and_variables(self, client_class):
        self.config()
        anonymous = APIClient()
        state = self.start(anonymous)
        client_class.return_value.get_identity.side_effect = RuntimeError("upstream adapter failed")
        anonymous.raise_request_exception = False
        response = anonymous.get("/api/auth/wecom/callback/", {"state": state, "code": "VERY_PRIVATE_CODE_701"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(state, response.content.decode())
        self.assertNotIn("VERY_PRIVATE_CODE_701", response.content.decode())

    def test_origin_only_accepts_https_origin_without_path_or_credentials(self):
        for origin in ("http://erp.example.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=1"):
            response = self.client.patch("/api/v1/wecom/config/", {"erp_origin": origin}, format="json",
                                         HTTP_IF_MATCH='"wecom-unconfigured"')
            self.assertEqual(response.status_code, 400, origin)

    def test_enable_requires_login_credentials_but_not_callback_credentials(self):
        response = self.client.patch("/api/v1/wecom/config/", {"enabled": True}, format="json",
                                     HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 400)
        response = self.client.patch("/api/v1/wecom/config/", {"enabled": True, "secret": "test-secret"}, format="json",
                                     HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["configuration_complete"])
        self.assertFalse(response.data["data"]["has_callback_token"])

    def test_corp_change_with_existing_bindings_is_rejected(self):
        config = self.config()
        self.binding(self.employee())
        response = self.client.patch("/api/v1/wecom/config/", {"corp_id": "wwanothercorp"}, format="json",
                                     HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 409)

    def test_management_rejects_non_admin_and_requires_csrf(self):
        employee = self.employee()
        self.client.force_login(employee.user)
        self.assertEqual(self.client.get("/api/v1/wecom/config/").status_code, 403)
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.patch("/api/v1/wecom/config/", {}, format="json", HTTP_IF_MATCH='"wecom-unconfigured"')
        self.assertEqual(response.status_code, 403)

    @patch("apps.wecom.services.WeComClient")
    def test_connection_check_updates_status_and_requires_current_etag(self, client_class):
        config = self.config()
        client_class.return_value.check_connection.return_value = {"ok": True}
        response = self.client.post("/api/v1/wecom/config/check/", {}, format="json", HTTP_IF_MATCH=etag_for_instance(config))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["last_check_status"], "SUCCESS")
        self.assertNotEqual(response["ETag"], etag_for_instance(config))

    @patch("apps.wecom.services.WeComClient")
    def test_manual_binding_preserves_account_password_and_roles(self, client_class):
        self.config()
        self.mock_member(client_class)
        employee = self.employee()
        group = Group.objects.create(name="Existing group")
        employee.user.groups.add(group)
        response = self.client.post("/api/v1/wecom/bindings/", {
            "user_id": "Member.One", "employee_id": str(employee.pk), "confirmed": True,
        }, format="json", HTTP_IF_MATCH=etag_for_instance(employee))
        self.assertEqual(response.status_code, 201, response.data)
        employee.refresh_from_db()
        self.assertTrue(employee.user.check_password("old-password"))
        self.assertTrue(employee.user.groups.filter(pk=group.pk).exists())
        self.assertFalse(WeComBinding.objects.get().created_account)
        self.assertFalse(waiting_for_role(employee.user))

    @patch("apps.wecom.services.WeComClient")
    def test_manual_binding_employee_without_account_creates_unusable_password(self, client_class):
        self.config()
        self.mock_member(client_class)
        employee = self.employee(user=False)
        response = self.client.post("/api/v1/wecom/bindings/", {
            "user_id": "Member.One", "employee_id": str(employee.pk), "confirmed": True,
        }, format="json", HTTP_IF_MATCH=etag_for_instance(employee))
        self.assertEqual(response.status_code, 201, response.data)
        employee.refresh_from_db()
        self.assertFalse(employee.user.has_usable_password())
        self.assertTrue(waiting_for_role(employee.user))

    @patch("apps.wecom.services.WeComClient")
    def test_binding_conflict_does_not_overwrite_employee(self, client_class):
        self.config()
        self.mock_member(client_class)
        first = self.employee()
        binding = self.binding(first)
        second = self.employee("WC_OTHER")
        response = self.client.post("/api/v1/wecom/bindings/", {
            "user_id": "member.one", "employee_id": str(second.pk), "confirmed": True,
        }, format="json", HTTP_IF_MATCH=etag_for_instance(second))
        self.assertEqual(response.status_code, 409)
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, first.pk)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="MANUAL_BIND_FAILED").count(), 1)

    def test_database_rejects_case_variant_identity_and_duplicate_employee(self):
        first = self.employee()
        self.binding(first)
        other = self.employee("WC_OTHER")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.binding(other, user_id="member.one")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.binding(first, user_id="Other")

    def test_waiting_status_uses_fresh_active_role_assignment(self):
        employee = self.employee()
        self.binding(employee, created=True)
        self.assertTrue(waiting_for_role(employee.user))
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="WeCom role"), role_code="WECOM_TEST", display_name="测试角色")
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                                                            effective_from=timezone.now() - timedelta(days=1))
        self.assertFalse(waiting_for_role(employee.user))
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assertTrue(waiting_for_role(employee.user))
        self.assertFalse(waiting_for_role(self.admin))

    def test_waiting_gate_is_preserved_after_password_reset_and_changes_with_roles(self):
        employee = self.employee()
        self.binding(employee, created=True)
        employee.user.set_password("New-password-1!")
        employee.user.save()
        browser = APIClient()
        response = browser.post("/api/auth/login/", {"username": employee.user.username, "password": "New-password-1!"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["user"]["waiting_for_role"])
        response = browser.get("/api/v1/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "WECOM_ROLE_REQUIRED")
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="Gate role"), role_code="WECOM_GATE", display_name="门禁角色")
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                                                            effective_from=timezone.now() - timedelta(hours=1))
        self.assertEqual(browser.get("/api/v1/").status_code, 200)
        self.assertFalse(browser.get("/api/auth/me/").data["user"]["waiting_for_role"])
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assertEqual(browser.get("/api/v1/").status_code, 403)
        self.assertTrue(browser.get("/api/auth/me/").data["authenticated"])

    @patch("apps.wecom.selectors.schema_is_ready", return_value=False)
    def test_unmigrated_module_keeps_existing_auth_and_returns_explicit_unavailable(self, ready):
        self.assertFalse(waiting_for_role(self.admin))
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["authenticated"])
        self.assertFalse(response.data["user"]["waiting_for_role"])
        self.assertEqual(self.client.get("/api/v1/wecom/config/").status_code, 503)
        self.assertIn("reason=CONFIGURATION_ERROR", self.client.get("/api/auth/wecom/start/").url)
        self.assertIn("reason=CONFIGURATION_ERROR", self.callback("invalid").url)

    @patch("apps.wecom.services.WeComClient")
    def test_manual_binding_preserves_effective_role_history(self, client_class):
        self.config()
        self.mock_member(client_class)
        employee = self.employee()
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="Old role"), role_code="OLD_WECOM_ROLE", display_name="原角色")
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                                                            effective_from=timezone.now() - timedelta(days=1))
        response = self.client.post("/api/v1/wecom/bindings/", {
            "user_id": "Member.One", "employee_id": str(employee.pk), "confirmed": True,
        }, format="json", HTTP_IF_MATCH=etag_for_instance(employee))
        self.assertEqual(response.status_code, 201)
        assignment.refresh_from_db()
        self.assertEqual(assignment.employee_id, employee.pk)
        self.assertIsNone(assignment.effective_to)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(employee=employee).count(), 1)

    def test_disabled_start_does_not_create_oauth_state(self):
        response = self.client.get("/api/auth/wecom/start/")
        self.assertIn("reason=CONFIGURATION_ERROR", response.url)
        self.assertFalse(OAuthState.objects.exists())

    def test_start_rejects_external_next_and_stores_only_digests(self):
        self.config()
        state = self.start()
        row = OAuthState.objects.get()
        self.assertNotEqual(row.state_digest, state)
        response = self.client.get("/api/auth/wecom/start/", {"next": "https://attacker.example"})
        self.assertIn("reason=LOGIN_FAILED", response.url)

    @patch("apps.wecom.services.WeComClient")
    def test_oauth_state_is_session_bound_and_single_use(self, client_class):
        self.config()
        self.mock_member(client_class)
        anonymous = APIClient()
        state = self.start(anonymous)
        foreign = APIClient()
        self.assertIn("reason=STATE_INVALID", self.callback(state, foreign).url)
        self.assertFalse(WeComBinding.objects.exists())
        self.assertEqual(self.callback(state, anonymous).url, "/auth/waiting-role")
        self.assertIn("reason=STATE_INVALID", self.callback(state, anonymous).url)
        self.assertEqual(client_class.return_value.get_identity.call_count, 1)

    @patch("apps.wecom.services.WeComClient")
    def test_expired_state_never_contacts_upstream(self, client_class):
        self.config()
        state = self.start()
        OAuthState.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIn("reason=STATE_INVALID", self.callback(state).url)
        client_class.assert_not_called()

    @patch("apps.wecom.services.WeComClient")
    def test_first_oauth_login_creates_once_and_never_matches_by_name(self, client_class):
        self.config()
        self.mock_member(client_class, name="真实员工")
        existing = self.employee()
        anonymous = APIClient()
        response = self.callback(self.start(anonymous), anonymous)
        self.assertEqual(response.url, "/auth/waiting-role")
        binding = WeComBinding.objects.get()
        self.assertNotEqual(binding.employee_id, existing.pk)
        self.assertFalse(binding.employee.user.has_usable_password())
        self.assertFalse(binding.employee.user.is_staff)
        self.assertFalse(binding.employee.user.is_superuser)
        self.assertEqual(self.callback(self.start(anonymous), anonymous).url, "/auth/waiting-role")
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="AUTO_CREATE").count(), 1)

    @patch("apps.wecom.services.WeComClient")
    def test_logged_in_a_returning_b_is_rejected_before_creating_records(self, client_class):
        self.config()
        self.mock_member(client_class)
        state = self.start()
        count = Employee.objects.count()
        response = self.callback(state)
        self.assertIn("reason=IDENTITY_MISMATCH", response.url)
        self.assertEqual(Employee.objects.count(), count)
        self.assertFalse(WeComBinding.objects.exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)

    @patch("apps.wecom.services.WeComClient")
    def test_member_validity_rejects_inactive_empty_name_and_other_corp(self, client_class):
        self.config()
        anonymous = APIClient()
        instance = self.mock_member(client_class)
        for member in ({"userid": "Member.One", "name": "", "status": 1},
                       {"userid": "Member.One", "name": "员工", "status": 2},
                       {"userid": "Other", "name": "员工", "status": 1}):
            instance.get_member.return_value = member
            response = self.callback(self.start(anonymous), anonymous)
            self.assertIn("reason=MEMBER_REJECTED", response.url)
        self.mock_member(client_class)
        instance.get_identity.return_value["corpid"] = "other-corp"
        self.assertIn("reason=MEMBER_REJECTED", self.callback(self.start(anonymous), anonymous).url)
        self.assertFalse(WeComBinding.objects.exists())

    @patch("apps.wecom.services.WeComClient")
    def test_disabled_employee_cannot_be_reactivated_by_oauth(self, client_class):
        self.config()
        self.mock_member(client_class)
        employee = self.employee()
        self.binding(employee)
        employee.status = "INACTIVE"
        employee.save()
        anonymous = APIClient()
        self.assertIn("reason=LOGIN_FAILED", self.callback(self.start(anonymous), anonymous).url)
        employee.refresh_from_db()
        self.assertEqual(employee.status, "INACTIVE")
        self.assertNotIn("_auth_user_id", anonymous.session)

    @patch("apps.wecom.services.write_audit_log", side_effect=RuntimeError("audit failed"))
    @patch("apps.wecom.services.WeComClient")
    def test_audit_failure_rolls_back_user_employee_and_binding(self, client_class, audit):
        self.config()
        self.mock_member(client_class)
        anonymous = APIClient()
        state = self.start(anonymous)
        user_count, employee_count = get_user_model().objects.count(), Employee.objects.count()
        with self.assertRaisesMessage(RuntimeError, "audit failed"):
            self.callback(state, anonymous)
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(Employee.objects.count(), employee_count)
        self.assertFalse(WeComBinding.objects.exists())

    @patch("apps.wecom.services._create_binding", side_effect=IntegrityError("unrelated constraint"))
    @patch("apps.wecom.services.WeComClient")
    def test_unrelated_integrity_error_is_not_treated_as_successful_duplicate(self, client_class, create_binding):
        self.config()
        self.mock_member(client_class)
        anonymous = APIClient()
        state = self.start(anonymous)
        user_count, employee_count = get_user_model().objects.count(), Employee.objects.count()
        with self.assertRaisesMessage(IntegrityError, "unrelated constraint"):
            self.callback(state, anonymous)
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(Employee.objects.count(), employee_count)
        self.assertFalse(WeComBinding.objects.exists())

    def test_lists_validate_pagination_and_filter_status(self):
        employee = self.employee()
        self.binding(employee, created=True)
        response = self.client.get("/api/v1/wecom/bindings/", {"status": "waiting", "search": "Member"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["role_status"], "waiting")
        self.assertEqual(self.client.get("/api/v1/wecom/bindings/", {"page": "bad"}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/wecom/bindings/", {"status": "unexpected"}).status_code, 400)


class WeComCredentialTests(SimpleTestCase):
    @override_settings(WECOM_FERNET_KEYS=[TEST_KEY])
    def test_round_trip_and_invalid_ciphertext(self):
        self.assertEqual(decrypt_secret(encrypt_secret("private-value")), "private-value")
        with self.assertRaises(CredentialError):
            decrypt_secret("invalid")

    def test_key_rotation_reads_old_key_and_writes_new_key(self):
        old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(WECOM_FERNET_KEYS=[old_key]):
            old_value = encrypt_secret("private-value")
        with override_settings(WECOM_FERNET_KEYS=[new_key, old_key]):
            self.assertEqual(decrypt_secret(old_value), "private-value")
            new_value = encrypt_secret("new-value")
        self.assertEqual(Fernet(new_key.encode()).decrypt(new_value.encode()), b"new-value")
