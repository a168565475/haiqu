from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.access_control.resource_scopes import resource_ids
from apps.audit.models import AuditLog
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig
from apps.wecom.selectors import binding_payload, bindings_queryset, waiting_for_role


BUSINESS_PERMISSION = "reference_data.view_country"
MANAGEMENT_PERMISSIONS = (
    "organizations.manage_organization", "access_control.manage_accounts", "access_control.manage_access",
    "access_control.manage_wecom", "access_control.manage_notifications",
)


@override_settings(
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
    MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComLoginAuthorizationTests(TestCase):
    def setUp(self):
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("login-test-secret"))
        client_patch = patch("apps.wecom.services.WeComClient")
        self.upstream = client_patch.start().return_value
        self.addCleanup(client_patch.stop)
        self.upstream.get_identity.return_value = {"userid": "Login.Member", "corpid": self.config.corp_id}
        self.upstream.get_member.return_value = {"userid": "Login.Member", "name": "企业微信姓名", "status": 1}

    def employee(self, code="LOGIN_EXISTING", name="ERP 维护姓名", **fields):
        account = get_user_model().objects.create_user(code.lower(), password="old-password")
        return Employee.objects.create(user=account, employee_code=code, display_name=name, **fields)

    def bound(self, code="LOGIN_EXISTING", *, created=False, user_id="Login.Member", **fields):
        employee = self.employee(code, **fields)
        WeComBinding.objects.create(
            corp_id=self.config.corp_id, user_id=user_id, member_name="原绑定姓名", employee=employee,
            source="AUTO" if created else "MANUAL", created_account=created,
        )
        return employee

    def permission(self, code):
        app_label, codename = code.split(".", 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def role(self, employee, permission=None, *, scope="MODULE", legacy=False, start=None, end=None, archived=False):
        group = Group.objects.create(name=f"登录测试角色 {employee.pk}")
        role = RoleProfile.objects.create(
            auth_group=group, role_code=f"LOGIN_{employee.pk.hex.upper()}", display_name="登录测试角色",
            archived_at=timezone.now() if archived else None,
        )
        assignment = EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=start or timezone.now() - timedelta(hours=1),
            effective_to=end,
        )
        if permission:
            value = self.permission(permission)
            group.permissions.add(value)
            if not legacy:
                RoleActionGrant.objects.create(role=role, permission=value, scope=scope)
        return role, assignment

    def browser(self):
        browser = APIClient(enforce_csrf_checks=True)
        self.assertEqual(browser.get("/api/auth/me/").status_code, 200)
        return browser

    def oauth(self, browser, entry="workbench"):
        if entry == "qr":
            start = browser.post("/api/auth/wecom/qr/", {"next": "/"}, format="json",
                                 HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value)
            self.assertEqual(start.status_code, 200, start.data)
            state = start.data["state"]
        else:
            start = browser.get("/api/auth/wecom/start/")
            self.assertEqual(start.status_code, 302)
            state = parse_qs(urlparse(start.url).query)["state"][0]
        response = browser.get("/api/auth/wecom/callback/", {"state": state, "code": "login-test-code"})
        self.assertEqual(response.status_code, 302)
        return response

    def assert_waiting_session(self, browser, session_key):
        response = browser.get("/api/v1/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "WECOM_ROLE_REQUIRED")
        state = browser.get("/api/auth/me/")
        self.assertEqual(state.status_code, 200)
        self.assertTrue(state.data["authenticated"])
        self.assertTrue(state.data["user"]["waiting_for_role"])
        self.assertEqual(browser.session.session_key, session_key)

    def test_bound_accounts_without_permission_wait_regardless_of_how_account_was_created(self):
        for created in (False, True):
            with self.subTest(created_account=created):
                employee = self.bound(f"LOGIN_CREATED_{int(created)}", created=created, user_id=f"Created.{created}")
                self.assertTrue(waiting_for_role(employee.user))
                browser = self.browser()
                browser.force_login(employee.user)
                self.assert_waiting_session(browser, browser.session.session_key)

    def test_empty_role_does_not_unlock_either_wecom_entry(self):
        employee = self.bound()
        self.role(employee)
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                self.assertEqual(self.oauth(browser, entry).url, "/auth/waiting-role")
                self.assert_waiting_session(browser, browser.session.session_key)

    def test_future_expired_and_archived_roles_do_not_unlock_login(self):
        now = timezone.now()
        cases = (
            {"start": now + timedelta(days=1)},
            {"start": now - timedelta(days=2), "end": now - timedelta(days=1)},
            {"archived": True},
        )
        for index, fields in enumerate(cases):
            with self.subTest(fields=fields):
                employee = self.bound(f"LOGIN_ROLE_{index}", user_id=f"Role.{index}")
                self.role(employee, BUSINESS_PERMISSION, **fields)
                self.assertTrue(waiting_for_role(employee.user))

    def test_non_erp_permission_does_not_unlock_login_from_any_grant_source(self):
        employee = self.bound()
        permission = self.permission("auth.change_user")
        employee.user.user_permissions.add(permission)
        group = Group.objects.create(name="原生非业务权限组")
        group.permissions.add(permission)
        employee.user.groups.add(group)
        self.role(employee, "auth.change_user")
        self.assertTrue(waiting_for_role(employee.user))
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/auth/waiting-role")

    def test_valid_business_action_unlocks_both_entries_and_keeps_module_permissions(self):
        employee = self.bound()
        self.role(employee, BUSINESS_PERMISSION)
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                self.assertEqual(self.oauth(browser, entry).url, "/")
                self.assertFalse(browser.get("/api/auth/me/").data["user"]["waiting_for_role"])
                self.assertEqual(browser.get("/api/v1/reference-data/countries/").status_code, 200)
                self.assertEqual(browser.get("/api/v1/wecom/config/").status_code, 403)

    def test_valid_management_role_unlocks_both_entries(self):
        employee = self.bound()
        self.role(employee, "access_control.manage_accounts")
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                self.assertEqual(self.oauth(browser, entry).url, "/")
                self.assertFalse(browser.get("/api/auth/me/").data["user"]["waiting_for_role"])

    def test_direct_business_permission_remains_compatible(self):
        employee = self.bound()
        employee.user.user_permissions.add(self.permission(BUSINESS_PERMISSION))
        self.assertFalse(waiting_for_role(employee.user))
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/")
        self.assertEqual(browser.get("/api/v1/reference-data/countries/").status_code, 200)

    def test_native_group_business_permission_remains_compatible(self):
        employee = self.bound()
        group = Group.objects.create(name="历史业务权限组")
        group.permissions.add(self.permission(BUSINESS_PERMISSION))
        employee.user.groups.add(group)
        self.assertFalse(waiting_for_role(employee.user))

    def test_current_legacy_role_group_business_permission_remains_compatible(self):
        employee = self.bound()
        role, assignment = self.role(employee, BUSINESS_PERMISSION, legacy=True)
        self.assertFalse(role.action_grants.exists())
        self.assertFalse(waiting_for_role(employee.user))
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assertTrue(waiting_for_role(employee.user))

    def test_direct_management_permissions_do_not_unlock_login(self):
        employee = self.bound()
        employee.user.user_permissions.add(*(self.permission(code) for code in MANAGEMENT_PERMISSIONS))
        self.assertTrue(waiting_for_role(employee.user))

    def test_native_group_management_permissions_do_not_unlock_login(self):
        employee = self.bound()
        group = Group.objects.create(name="管理权限直授组")
        group.permissions.add(*(self.permission(code) for code in MANAGEMENT_PERMISSIONS))
        employee.user.groups.add(group)
        self.assertTrue(waiting_for_role(employee.user))

    def test_legacy_role_management_permissions_do_not_replace_module_grants(self):
        employee = self.bound()
        role, _ = self.role(employee)
        role.auth_group.permissions.add(*(self.permission(code) for code in MANAGEMENT_PERMISSIONS))
        self.assertTrue(waiting_for_role(employee.user))

    def test_management_grant_with_non_module_scope_does_not_unlock_login(self):
        employee = self.bound()
        self.role(employee, "access_control.manage_accounts", scope="OWN")
        self.assertTrue(waiting_for_role(employee.user))

    def test_invalid_business_scope_cannot_unlock_through_projected_role_group_permission(self):
        employee = self.bound()
        self.role(employee, BUSINESS_PERMISSION, scope="OWN")
        self.assertTrue(waiting_for_role(employee.user))

    def test_invalid_role_scope_cannot_unlock_through_implied_export_permission(self):
        employee = self.bound()
        role, _ = self.role(employee, "quotations.view_quotation", scope="MODULE")
        role.auth_group.permissions.add(self.permission("quotations.export_quotation"))
        self.assertTrue(waiting_for_role(employee.user))

    @override_settings(ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_empty_resource_selection_keeps_login_allowed_and_data_scope_empty(self):
        for index, (code, scope) in enumerate((
            ("workshop_reporting.view_workreport", "WORKSHOP"),
            ("outsourcing.view_outsourcingorder", "CRAFT"),
        )):
            with self.subTest(scope=scope):
                employee = self.bound(f"LOGIN_RESOURCE_{index}", user_id=f"Resource.{index}")
                role, _ = self.role(employee, code, scope=scope)
                self.assertFalse(role.action_grants.get().resource_selections.exists())
                self.assertFalse(waiting_for_role(employee.user))
                self.assertEqual(resource_ids(SimpleNamespace(user=employee.user), code, scope), set())

    def test_role_revocation_blocks_existing_session_without_logging_user_out(self):
        employee = self.bound()
        _, assignment = self.role(employee, BUSINESS_PERMISSION)
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/")
        session_key = browser.session.session_key
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assert_waiting_session(browser, session_key)

    def test_revoking_all_actions_blocks_same_session_and_regrant_unlocks_it(self):
        employee = self.bound()
        role, _ = self.role(employee, BUSINESS_PERMISSION)
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/")
        session_key = browser.session.session_key
        role.action_grants.all().delete()
        role.auth_group.permissions.clear()
        self.assert_waiting_session(browser, session_key)
        permission = self.permission(BUSINESS_PERMISSION)
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.add(permission)
        self.assertFalse(browser.get("/api/auth/me/").data["user"]["waiting_for_role"])
        self.assertEqual(browser.get("/api/v1/reference-data/countries/").status_code, 200)
        self.assertEqual(browser.session.session_key, session_key)

    def test_direct_permission_revocation_is_visible_without_replacing_session(self):
        employee = self.bound()
        employee.user.user_permissions.add(self.permission(BUSINESS_PERMISSION))
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/")
        session_key = browser.session.session_key
        employee.user.user_permissions.clear()
        self.assert_waiting_session(browser, session_key)

    def test_unbound_password_account_preserves_existing_login_behavior(self):
        employee = self.employee()
        browser = self.browser()
        response = browser.post("/api/auth/login/", {
            "username": employee.user.username, "password": "old-password",
        }, format="json", HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["user"]["waiting_for_role"])
        self.assertEqual(browser.get("/api/v1/").status_code, 200)

    def test_bound_password_account_also_waits_for_effective_permission(self):
        employee = self.bound(created=False)
        browser = self.browser()
        response = browser.post("/api/auth/login/", {
            "username": employee.user.username, "password": "old-password",
        }, format="json", HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["user"]["waiting_for_role"])
        self.assert_waiting_session(browser, browser.session.session_key)

    def test_active_superuser_keeps_existing_global_authorization(self):
        employee = self.bound()
        employee.user.is_superuser = True
        employee.user.save()
        self.assertFalse(waiting_for_role(employee.user))
        browser = self.browser()
        self.assertEqual(self.oauth(browser).url, "/")

    def assert_same_name_requires_manual_binding(self, *, name=" ａｌｉｃｅ　 ＬＩ ", **fields):
        existing = self.employee(name=name, **fields)
        self.upstream.get_member.return_value["name"] = "Alice Li"
        before = (Employee.objects.count(), get_user_model().objects.count(), WeComBinding.objects.count())
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                response = self.oauth(browser, entry)
                self.assertEqual(parse_qs(urlparse(response.url).query).get("reason"), ["BINDING_REQUIRED"])
                self.assertNotIn("_auth_user_id", browser.session)
                self.assertNotIn("Alice", response.url)
                self.assertNotIn(str(existing.pk), response.url)
                self.assertEqual((Employee.objects.count(), get_user_model().objects.count(), WeComBinding.objects.count()), before)
        self.assertTrue(existing.user.check_password("old-password"))
        self.assertFalse(AuditLog.objects.filter(action="AUTO_CREATE").exists())

    def test_normalized_same_name_requires_manual_binding_for_both_entries(self):
        self.assert_same_name_requires_manual_binding()

    def test_same_name_former_employee_is_not_automatically_recreated(self):
        self.assert_same_name_requires_manual_binding(name="ALICE LI", status="LEFT")

    def test_same_name_archived_employee_is_not_automatically_recreated(self):
        self.assert_same_name_requires_manual_binding(name="Alice  Li", archived_at=timezone.now())

    def test_distinct_first_login_creates_one_passwordless_identity_then_waits(self):
        self.employee(name="其他姓名")
        before = (Employee.objects.count(), get_user_model().objects.count())
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                self.assertEqual(self.oauth(browser, entry).url, "/auth/waiting-role")
        self.assertEqual((Employee.objects.count(), get_user_model().objects.count()), (before[0] + 1, before[1] + 1))
        binding = WeComBinding.objects.select_related("employee__user").get()
        self.assertFalse(binding.employee.user.has_usable_password())
        self.assertFalse(binding.employee.user.is_staff)
        self.assertFalse(binding.employee.user.is_superuser)
        self.assertEqual(AuditLog.objects.filter(action="AUTO_CREATE").count(), 1)

    def test_precreated_identity_is_reused_without_overwriting_erp_details(self):
        employee = self.bound(created=True, phone="13800000000", email="erp@example.test")
        employee.user.set_unusable_password()
        employee.user.save()
        self.role(employee, BUSINESS_PERMISSION)
        before_employee = Employee.objects.values().get(pk=employee.pk)
        before_binding = WeComBinding.objects.values().get(employee=employee)
        counts = (Employee.objects.count(), get_user_model().objects.count(), WeComBinding.objects.count())
        self.upstream.get_identity.return_value["userid"] = "login.member"
        self.upstream.get_member.return_value["userid"] = "login.member"
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                self.assertEqual(self.oauth(browser, entry).url, "/")
                self.assertEqual(int(browser.session["_auth_user_id"]), employee.user_id)
        self.assertEqual(Employee.objects.values().get(pk=employee.pk), before_employee)
        self.assertEqual(WeComBinding.objects.values().get(employee=employee), before_binding)
        self.assertEqual((Employee.objects.count(), get_user_model().objects.count(), WeComBinding.objects.count()), counts)
        self.assertFalse(AuditLog.objects.filter(action="AUTO_CREATE").exists())

    def test_inactive_bound_employee_has_distinct_error_and_no_authenticated_session(self):
        employee = self.bound(status="INACTIVE")
        for entry in ("workbench", "qr"):
            with self.subTest(entry=entry):
                browser = self.browser()
                response = self.oauth(browser, entry)
                self.assertEqual(parse_qs(urlparse(response.url).query).get("reason"), ["ACCOUNT_INACTIVE"])
                self.assertNotIn("_auth_user_id", browser.session)
        employee.refresh_from_db()
        self.assertEqual(employee.status, "INACTIVE")

    def test_binding_list_status_matches_login_gate_for_all_account_origins(self):
        admin = get_user_model().objects.create_superuser("admin", "", "admin-password")
        Employee.objects.create(user=admin, employee_code="LOGIN_LIST_ADMIN", display_name="管理员")
        manual = self.bound("LOGIN_LIST_MANUAL", user_id="List.Manual")
        empty = self.bound("LOGIN_LIST_EMPTY", created=True, user_id="List.Empty")
        self.role(empty)
        authorized = self.bound("LOGIN_LIST_ACTIVE", user_id="List.Active")
        authorized.user.user_permissions.add(self.permission(BUSINESS_PERMISSION))
        role_authorized = self.bound("LOGIN_LIST_ROLE", user_id="List.Role")
        self.role(role_authorized, "access_control.manage_accounts")
        legacy_authorized = self.bound("LOGIN_LIST_LEGACY", user_id="List.Legacy")
        self.role(legacy_authorized, BUSINESS_PERMISSION, legacy=True)
        invalid_scope = self.bound("LOGIN_LIST_BAD_SCOPE", user_id="List.InvalidScope")
        self.role(invalid_scope, BUSINESS_PERMISSION, scope="OWN")
        navigation = self.bound("LOGIN_LIST_NON_ERP", user_id="List.NonERP")
        navigation.user.user_permissions.add(self.permission("auth.change_user"))
        inactive = self.bound("LOGIN_LIST_INACTIVE", user_id="List.Inactive", status="INACTIVE")
        browser = APIClient()
        browser.force_login(admin)
        response = browser.get("/api/v1/wecom/bindings/", {"page_size": 50})
        self.assertEqual(response.status_code, 200, response.data)
        states = {row["user_id"]: row["role_status"] for row in response.data["data"]}
        self.assertEqual(states, {
            "List.Manual": "waiting", "List.Empty": "waiting", "List.Active": "active",
            "List.Role": "active", "List.Legacy": "active", "List.InvalidScope": "waiting",
            "List.NonERP": "waiting", "List.Inactive": "inactive",
        })
        with self.assertNumQueries(1):
            payloads = [binding_payload(binding) for binding in bindings_queryset()]
        self.assertEqual({row["user_id"]: row["role_status"] for row in payloads}, states)
        for employee in (manual, empty, authorized, role_authorized, legacy_authorized, invalid_scope, navigation):
            binding = employee.wecom_binding
            self.assertEqual(states[binding.user_id] == "waiting", waiting_for_role(employee.user))
        for status, expected in (
            ("waiting", {"List.Manual", "List.Empty", "List.InvalidScope", "List.NonERP"}),
            ("active", {"List.Active", "List.Role", "List.Legacy"}), ("inactive", {inactive.wecom_binding.user_id}),
        ):
            with self.subTest(status=status):
                response = browser.get("/api/v1/wecom/bindings/", {"status": status, "page_size": 50})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual({row["user_id"] for row in response.data["data"]}, expected)

    @override_settings(ACCESS_MANAGEMENT_ENABLED=False, SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
    def test_feature_flag_rollback_preserves_gate_and_existing_business_authorization(self):
        waiting = self.bound("LOGIN_ROLLBACK_WAITING", user_id="Rollback.Waiting")
        legacy = self.bound("LOGIN_ROLLBACK_LEGACY", user_id="Rollback.Legacy")
        legacy.user.user_permissions.add(self.permission(BUSINESS_PERMISSION))
        workshop = self.bound("LOGIN_ROLLBACK_WORKSHOP", user_id="Rollback.Workshop")
        self.role(workshop, "workshop_reporting.view_workreport", scope="WORKSHOP")
        for employee, expected_waiting in ((waiting, True), (legacy, False), (workshop, False)):
            self.assertEqual(waiting_for_role(employee.user), expected_waiting)
            self.upstream.get_identity.return_value["userid"] = employee.wecom_binding.user_id
            self.upstream.get_member.return_value["userid"] = employee.wecom_binding.user_id
            for entry in ("workbench", "qr"):
                with self.subTest(employee=employee.employee_code, entry=entry):
                    browser = self.browser()
                    self.assertEqual(self.oauth(browser, entry).url, "/auth/waiting-role" if expected_waiting else "/")
                    self.assertEqual(browser.get("/api/auth/me/").data["user"]["waiting_for_role"], expected_waiting)
