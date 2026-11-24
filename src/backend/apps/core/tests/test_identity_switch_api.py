"""Real Session/CSRF regressions for the single-level admin identity flow.

These helpers are also used by the PostgreSQL TransactionTestCase module.  They
never force-authenticate a request or replace the identity-switch service.
"""

import re
from datetime import timedelta
from http.cookies import SimpleCookie
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import override_settings
from django.utils import timezone
from django.views.debug import get_exception_reporter_filter
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee, EmployeeStatus
from apps.preferences.models import SavedView


PASSWORD = "IdentitySwitchTestPassword123!"
FLOW_SETTINGS = {
    "ACCESS_MANAGEMENT_ENABLED": False,
    "SALES_ACCESS_ENABLED": False,
    "MODULE_ACCESS_ENABLED": False,
    "ACCESS_RESOURCE_SCOPES_ENABLED": False,
    "SESSION_SAVE_EVERY_REQUEST": False,
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
}


def copy_browser(client):
    """Copy the browser cookie jar, not its connection or authentication state."""
    other = APIClient(enforce_csrf_checks=True)
    other.cookies = SimpleCookie()
    for name, morsel in client.cookies.items():
        other.cookies[name] = morsel.value
    return other


class IdentitySwitchFixtures:
    def create_identities(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", PASSWORD)
        self.employee = self.make_employee("SWITCH_ALICE", "alice.switch", "切换员工甲")
        self.other_employee = self.make_employee("SWITCH_BOB", "bob.switch", "切换员工乙")
        self.client = APIClient(enforce_csrf_checks=True)

    def make_employee(self, code, username=None, display_name=None, **employee_fields):
        user = get_user_model().objects.create_user(username or code.lower(), password=PASSWORD)
        return Employee.objects.create(
            user=user, employee_code=code, display_name=display_name or code, **employee_fields
        )

    @property
    def return_cookie_name(self):
        return settings.SESSION_COOKIE_NAME + "_admin_return_auth"

    def csrf(self, client=None):
        client = client or self.client
        if settings.CSRF_COOKIE_NAME not in client.cookies:
            response = client.get("/api/auth/me/")
            self.assertEqual(response.status_code, 200, response.content)
        return client.cookies[settings.CSRF_COOKIE_NAME].value

    def post_json(self, path, data, *, version=None, client=None, csrf=True):
        client = client or self.client
        headers = {}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.csrf(client)
        if version is not None:
            headers["HTTP_X_IDENTITY_VERSION"] = version
        return client.post(path, data, format="json", **headers)

    def login(self, user=None, *, client=None):
        user = user or self.admin
        response = self.post_json(
            "/api/auth/login/", {"username": user.username, "password": PASSWORD}, client=client
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["authenticated"])
        self.assertEqual(response.data["user"]["id"], user.pk)
        return response

    def assert_switch_state(self, response, *, active, can_return, user=None):
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.data), {"authenticated", "user", "account_switch"})
        state = response.data["account_switch"]
        self.assertEqual(set(state), {"active", "can_return", "identity_version"})
        self.assertIs(state["active"], active)
        self.assertIs(state["can_return"], can_return)
        self.assertIsInstance(state["identity_version"], str)
        self.assertTrue(state["identity_version"])
        if user is not None:
            self.assertTrue(response.data["authenticated"])
            self.assertEqual(response.data["user"]["id"], user.pk)
        return state["identity_version"]

    def version(self, client=None):
        response = (client or self.client).get("/api/auth/me/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.data["account_switch"]["identity_version"]

    def switch(self, employee=None, *, version=None, client=None):
        client = client or self.client
        employee = employee or self.employee
        return self.post_json(
            "/api/auth/switch/", {"employee_id": str(employee.pk)},
            version=version if version is not None else self.version(client), client=client,
        )

    def return_admin(self, *, version=None, client=None):
        client = client or self.client
        return self.post_json(
            "/api/auth/return-admin/", {},
            version=version if version is not None else self.version(client), client=client,
        )

    def enter_flow(self):
        self.login()
        self.root_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.switch()
        self.assert_switch_state(response, active=True, can_return=True, user=self.employee.user)
        return response

    def grant_saved_views(self, employee):
        employee.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="preferences", codename__in=["view_savedview", "add_savedview"]
        ))
        return SavedView.objects.create(
            employee=employee, module_code="CUSTOMER", view_name=employee.employee_code,
        )

    def saved_view_ids(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return {str(row["id"]) for row in response.data["data"]}

    def session_snapshot(self):
        return {key: (data, expires) for key, data, expires in
                Session.objects.values_list("session_key", "session_data", "expire_date")}

    def last_login_snapshot(self):
        return dict(get_user_model().objects.values_list("pk", "last_login"))

    def browser_cookie_snapshot(self, browser=None):
        return {name: cookie.value for name, cookie in (browser or self.client).cookies.items()}

    def assert_no_authentication_cookies(self, response):
        for name in (settings.SESSION_COOKIE_NAME, self.return_cookie_name, settings.CSRF_COOKIE_NAME):
            self.assertNotIn(name, response.cookies, (name, response.status_code))

    def flow_secret_values(self):
        from apps.core.identity_switch_services import NONCE

        control_key = self.client.cookies[self.return_cookie_name].value
        root_data = Session.objects.get(session_key=self.root_key).get_decoded()
        control = Session.objects.get(session_key=control_key).get_decoded()
        return {
            "root": self.root_key,
            "current": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "control": control_key,
            "root_nonce": root_data[NONCE],
            "control_nonce": control["nonce"],
        }

    def assert_debug_failure_redacts_flow(self, response, secrets, accept):
        self.assertEqual(response.status_code, 500, response.content)
        expected_type = "text/html" if accept == "text/html" else "text/plain"
        self.assertEqual(response["Content-Type"].split(";")[0], expected_type)
        body = response.content.decode()
        self.assertIn("RuntimeError", body)  # A real technical report, not a generic 500.
        context_repr = repr(response.wsgi_request._identity_context)
        for label, value in secrets.items():
            self.assertIsInstance(value, str, label)
            self.assertTrue(value, label)
            self.assertNotIn(value, body, label)
            self.assertNotIn(value, context_repr, label)
        reporter_filter = get_exception_reporter_filter(response.wsgi_request)
        self.assertTrue(reporter_filter.is_active(response.wsgi_request))
        safe_cookies = reporter_filter.get_safe_cookies(response.wsgi_request)
        for name in (settings.SESSION_COOKIE_NAME, self.return_cookie_name):
            self.assertEqual(safe_cookies[name], reporter_filter.cleansed_substitute)
        self.assertEqual(safe_cookies["reporter_public"], "visible-public-marker")
        self.assert_no_authentication_cookies(response)
        return reporter_filter

    def apply_all_response_cookies(self, response, browser):
        # Simulate arrival of the entire old HTTP response, including the CSRF
        # cookie, rather than conveniently discarding its identity cookies.
        for name, cookie in reversed(list(response.cookies.items())):
            if cookie["max-age"] == "0":
                browser.cookies.pop(name, None)
            else:
                browser.cookies[name] = cookie.value

    def assert_current_or_rejected(self, browser, expected_user, version):
        me = browser.get("/api/auth/me/")
        if me.status_code == 200:
            actual_user = me.json().get("user")
            if actual_user is None:
                self.assertFalse(me.json()["authenticated"])
            else:
                self.assertIsNotNone(expected_user, "Old cookies resurrected a logged-out user")
                self.assertEqual(actual_user["id"], expected_user.pk)
        else:
            self.assertIn(me.status_code, (403, 409), me.content)
        business = browser.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version)
        if expected_user is None or me.status_code != 200 or me.json().get("user") is None:
            self.assertIn(business.status_code, (401, 403, 409), business.content)
        else:
            self.assertIn(business.status_code, (200, 403, 409), business.content)
        if expected_user is None or not expected_user.is_superuser:
            privileged = browser.get("/api/v1/wecom/config/", HTTP_X_IDENTITY_VERSION=version)
            self.assertIn(privileged.status_code, (401, 403, 409), privileged.content)


@override_settings(**FLOW_SETTINGS)
class IdentitySwitchApiTests(IdentitySwitchFixtures, APITestCase):
    def setUp(self):
        self.create_identities()

    def test_me_keeps_original_shape_for_anonymous_and_ordinary_employee(self):
        self.assertEqual(self.client.get("/api/auth/me/").data, {"authenticated": False, "user": None})
        response = self.login(self.employee.user)
        self.assertEqual(set(response.data), {"authenticated", "user"})
        self.assertEqual(set(self.client.get("/api/auth/me/").data), {"authenticated", "user"})

    # 本用例验证未启用确认角色策略时，仅字面 admin 可切换的旧规则。
    @override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False)
    def test_only_exact_active_admin_superuser_can_initiate_or_list(self):
        impostor = get_user_model().objects.create_superuser("other.superuser", "", PASSWORD)
        ordinary_admin = self.make_employee("ORDINARY_ADMIN", "admin.employee")
        for user in (self.employee.user, impostor, ordinary_admin.user):
            with self.subTest(username=user.username):
                browser = APIClient(enforce_csrf_checks=True)
                self.login(user, client=browser)
                self.assertEqual(browser.get("/api/auth/switch-targets/").status_code, 403)
                response = self.post_json("/api/auth/switch/", {"employee_id": str(self.employee.pk)},
                                          version="not-admin", client=browser)
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version="not-admin",
                                                client=browser).status_code, 403)
        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertEqual(anonymous.get("/api/auth/switch-targets/").status_code, 403)
        self.assertEqual(self.post_json("/api/auth/switch/", {"employee_id": str(self.employee.pk)},
                                       version="anonymous", client=anonymous).status_code, 403)
        # The literal username alone is insufficient, even with an active employee.
        self.admin.is_superuser = False
        self.admin.save(update_fields=["is_superuser"])
        Employee.objects.create(user=self.admin, employee_code="LITERAL_ADMIN", display_name="普通admin")
        browser = APIClient(enforce_csrf_checks=True)
        self.login(self.admin, client=browser)
        self.assertEqual(browser.get("/api/auth/switch-targets/").status_code, 403)
        self.assertEqual(self.post_json("/api/auth/switch/", {"employee_id": str(self.employee.pk)},
                                       version="literal-admin", client=browser).status_code, 403)

    def test_admin_me_and_targets_share_a_stable_opaque_version(self):
        self.login()
        me = self.client.get("/api/auth/me/")
        version = self.assert_switch_state(me, active=False, can_return=False, user=self.admin)
        targets = self.client.get("/api/auth/switch-targets/")
        self.assertEqual(targets.status_code, 200, targets.content)
        self.assertEqual(set(targets.data), {"results", "identity_version", "departments", "roles", "has_more"})
        self.assertEqual(targets.data["identity_version"], version)
        self.assertEqual(self.version(), version)
        row = next(row for row in targets.json()["results"] if row["employee_id"] == str(self.employee.pk))
        self.assertEqual(row, {
            "employee_id": str(self.employee.pk), "user_id": self.employee.user_id,
            "username": self.employee.user.username, "employee_code": self.employee.employee_code,
            "display_name": self.employee.display_name, "departments": [], "roles": [],
        })

    def test_targets_filter_all_ineligible_employee_and_user_states_and_search(self):
        self.make_employee("EXCLUDED_INACTIVE", status=EmployeeStatus.INACTIVE)
        self.make_employee("EXCLUDED_LEFT", status=EmployeeStatus.LEFT)
        self.make_employee("EXCLUDED_ARCHIVE", archived_at=timezone.now())
        Employee.objects.create(employee_code="EXCLUDED_NOACCOUNT", display_name="无账号")
        for code, flags in (
            ("EXCLUDED_DISABLED", {"is_active": False}),
            ("EXCLUDED_SUPER", {"is_superuser": True}),
            ("EXCLUDED_STAFF", {"is_staff": True}),
        ):
            employee = self.make_employee(code)
            get_user_model().objects.filter(pk=employee.user_id).update(**flags)
        Employee.objects.create(user=self.admin, employee_code="EXCLUDED_ADMIN", display_name="管理员")
        self.login()
        response = self.client.get("/api/auth/switch-targets/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual({row["employee_id"] for row in response.json()["results"]},
                         {str(self.employee.pk), str(self.other_employee.pk)})
        version = self.version()
        for excluded in Employee.objects.exclude(pk__in=(self.employee.pk, self.other_employee.pk)):
            with self.subTest(excluded=excluded.employee_code):
                rejected = self.post_json("/api/auth/switch/", {"employee_id": str(excluded.pk)}, version=version)
                self.assertIn(rejected.status_code, (404, 409), rejected.content)
                self.assertEqual(self.version(), version)
        for query in ("alice.SWITCH", "switch_alice", "员工甲", "  SWITCH_ALICE  "):
            with self.subTest(query=query):
                response = self.client.get("/api/auth/switch-targets/", {"q": query})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual([row["employee_id"] for row in response.json()["results"]], [str(self.employee.pk)])
        self.assertEqual(self.client.get("/api/auth/switch-targets/", {"q": "no-such-person"}).data["results"], [])

    def test_switch_and_return_require_explicit_csrf_including_anonymous_request(self):
        self.login()
        version = self.version()
        response = self.post_json("/api/auth/switch/", {"employee_id": str(self.employee.pk)},
                                  version=version, csrf=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.version(), version)
        self.enter_flow()
        version = self.version()
        response = self.post_json("/api/auth/return-admin/", {}, version=version, csrf=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.version(), version)
        anonymous = APIClient(enforce_csrf_checks=True)
        for path, data in (("/api/auth/switch/", {"employee_id": str(self.employee.pk)}),
                           ("/api/auth/return-admin/", {})):
            self.assertEqual(self.post_json(path, data, version=version, client=anonymous, csrf=False).status_code, 403)

    def test_missing_csrf_me_recovery_allows_original_uuid_switch_return_and_logout(self):
        def session_state():
            # SAVE_EVERY_REQUEST may re-sign unchanged data with a new timestamp.
            return {row.session_key: (row.get_decoded(), row.expire_date) for row in Session.objects.all()}

        for save_every in (False, True):
            with self.subTest(save_every=save_every), override_settings(SESSION_SAVE_EVERY_REQUEST=save_every):
                self.client = APIClient(enforce_csrf_checks=True)
                entered = self.enter_flow()
                version = entered.data["account_switch"]["identity_version"]
                original_payload = {"employee_id": str(self.other_employee.pk)}
                steps = (
                    ("/api/auth/switch/", original_payload, self.employee.user, True),
                    ("/api/auth/return-admin/", {}, self.other_employee.user, True),
                    ("/api/auth/logout/", {}, self.admin, False),
                )
                for path, payload, current_user, active in steps:
                    with self.subTest(path=path):
                        self.client.cookies.pop(settings.CSRF_COOKIE_NAME)
                        cookies = self.browser_cookie_snapshot()
                        sessions = session_state()
                        last_logins = self.last_login_snapshot()
                        # No helper-triggered /me: the original write must really
                        # fail CSRF before the explicit recovery read.
                        denied = self.post_json(path, payload, version=version, csrf=False)
                        self.assertEqual(denied.status_code, 403, denied.content)
                        self.assert_no_authentication_cookies(denied)
                        self.assertEqual(session_state(), sessions)
                        recovered = self.client.get("/api/auth/me/")
                        self.assertEqual(self.assert_switch_state(
                            recovered, active=active, can_return=active, user=current_user,
                        ), version)
                        self.assertIn(settings.CSRF_COOKIE_NAME, recovered.cookies)
                        self.assertTrue(recovered.cookies[settings.CSRF_COOKIE_NAME].value)
                        self.assertNotIn(settings.SESSION_COOKIE_NAME, recovered.cookies)
                        self.assertNotIn(self.return_cookie_name, recovered.cookies)
                        self.assertEqual({name: cookie.value for name, cookie in self.client.cookies.items()
                                          if name != settings.CSRF_COOKIE_NAME}, cookies)
                        self.assertEqual(session_state(), sessions)
                        self.assertEqual(self.last_login_snapshot(), last_logins)
                        self.assertIn("Cookie", recovered.get("Vary", ""))
                        self.assertIn("no-store", recovered["Cache-Control"])
                        # Same UUID/body and identity version, now with the newly
                        # issued CSRF token; no implicit business retry exists.
                        completed = self.post_json(path, payload, version=version)
                        if path == "/api/auth/logout/":
                            self.assertEqual(completed.status_code, 200, completed.content)
                            self.assertEqual(completed.data, {"authenticated": False, "user": None})
                        else:
                            version = self.assert_switch_state(
                                completed, active=path == "/api/auth/switch/",
                                can_return=path == "/api/auth/switch/",
                                user=self.other_employee.user if path == "/api/auth/switch/" else self.admin,
                            )
                self.assertEqual(self.client.get("/api/auth/me/").data, {"authenticated": False, "user": None})

    @override_settings(
        CSRF_COOKIE_NAME="identity_recovery_csrf", CSRF_COOKIE_DOMAIN="example.test",
        CSRF_COOKIE_PATH="/api/", CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True,
        CSRF_COOKIE_SAMESITE="Strict", CSRF_COOKIE_AGE=300,
    )
    def test_missing_csrf_me_recovery_preserves_configured_cookie_attributes(self):
        entered = self.enter_flow()
        version = entered.data["account_switch"]["identity_version"]
        self.client.cookies.pop(settings.CSRF_COOKIE_NAME)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(self.assert_switch_state(
            response, active=True, can_return=True, user=self.employee.user,
        ), version)
        cookie = response.cookies[settings.CSRF_COOKIE_NAME]
        self.assertTrue(cookie.value)
        self.assertEqual(cookie["domain"], settings.CSRF_COOKIE_DOMAIN)
        self.assertEqual(cookie["path"], settings.CSRF_COOKIE_PATH)
        self.assertEqual(cookie["samesite"], settings.CSRF_COOKIE_SAMESITE)
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(int(cookie["max-age"]), settings.CSRF_COOKIE_AGE)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertNotIn(self.return_cookie_name, response.cookies)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_present_csrf_reads_and_delayed_me_response_keep_all_cookie_protections(self):
        entered = self.enter_flow()
        version = entered.data["account_switch"]["identity_version"]
        delayed = self.client.get("/api/auth/me/")
        self.assert_no_authentication_cookies(delayed)
        # Present-but-empty/malformed cookies are deliberately not the missing
        # cookie recovery case, even if Django internally replaces their value.
        for token in (self.csrf(), "", "malformed-csrf"):
            for path in ("/api/auth/me/", "/api/auth/switch-targets/"):
                with self.subTest(token=token, path=path):
                    browser = copy_browser(self.client)
                    browser.cookies[settings.CSRF_COOKIE_NAME] = token
                    cookies = self.browser_cookie_snapshot(browser)
                    response = browser.get(path)
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assert_no_authentication_cookies(response)
                    self.assertEqual(self.browser_cookie_snapshot(browser), cookies)
        switched = self.switch(self.other_employee, version=version)
        current_version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        cookies = self.browser_cookie_snapshot()
        self.apply_all_response_cookies(delayed, self.client)
        self.assertEqual(self.browser_cookie_snapshot(), cookies)
        self.assertEqual(self.version(), current_version)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_missing_csrf_other_reads_and_head_me_do_not_recover_cookie(self):
        entered = self.enter_flow()
        version = entered.data["account_switch"]["identity_version"]
        self.client.cookies.pop(settings.CSRF_COOKIE_NAME)
        cookies = self.browser_cookie_snapshot()
        for method, path, expected_status in (("get", "/api/auth/switch-targets/", 200),
                                              ("head", "/api/auth/me/", 405), ("get", "/api/v1/", 200)):
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, HTTP_X_IDENTITY_VERSION=version)
                self.assertEqual(response.status_code, expected_status, response.content)
                self.assert_no_authentication_cookies(response)
                self.assertEqual(self.browser_cookie_snapshot(), cookies)
        recovered = self.client.get("/api/auth/me/")
        self.assertEqual(recovered.status_code, 200, recovered.content)
        self.assertIn(settings.CSRF_COOKIE_NAME, recovered.cookies)

    def test_failed_me_with_missing_csrf_does_not_issue_any_authentication_cookie(self):
        self.client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
        self.enter_flow()
        self.client.cookies.pop(settings.CSRF_COOKIE_NAME)
        cookies = self.browser_cookie_snapshot()
        sessions = self.session_snapshot()
        with patch("apps.core.views.user_payload", side_effect=RuntimeError("Intentional CSRF recovery payload failure")):
            failed = self.client.get("/api/auth/me/")
        self.assertEqual(failed.status_code, 500, failed.content)
        self.assert_no_authentication_cookies(failed)
        self.assertEqual(self.browser_cookie_snapshot(), cookies)
        self.assertEqual(self.session_snapshot(), sessions)

    def test_stale_and_invalid_context_me_with_missing_csrf_remain_fail_closed(self):
        entered = self.enter_flow()
        version = entered.data["account_switch"]["identity_version"]
        stale = copy_browser(self.client)
        switched = self.switch(self.other_employee, version=version)
        current_version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        invalid = copy_browser(self.client)
        invalid.cookies[self.return_cookie_name] = self.root_key
        sessions = self.session_snapshot()
        for browser, status, code in ((stale, 409, "IDENTITY_VERSION_CONFLICT"),
                                      (invalid, 403, "IDENTITY_CONTEXT_INVALID")):
            with self.subTest(code=code):
                browser.cookies.pop(settings.CSRF_COOKIE_NAME)
                cookies = self.browser_cookie_snapshot(browser)
                response = browser.get("/api/auth/me/")
                self.assertEqual(response.status_code, status, response.content)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assert_no_authentication_cookies(response)
                self.assertEqual(self.browser_cookie_snapshot(browser), cookies)
                self.assertEqual(self.session_snapshot(), sessions)
        self.assertEqual(self.version(), current_version)

    def test_switch_validates_uuid_required_fields_and_target_eligibility(self):
        self.login()
        version = self.version()
        for data in ({}, {"employee_id": "bad"}, {"employee_id": 1}, {"employee_id": None},
                     {"employee_id": []}, {"employee_id": ""},
                     {"employee_id": str(self.employee.pk), "user_id": self.employee.user_id},
                     [str(self.employee.pk)]):
            with self.subTest(data=data):
                response = self.post_json("/api/auth/switch/", data, version=version)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.version(), version)
        invalid_employee = self.make_employee("INVALID_TARGET", status=EmployeeStatus.LEFT)
        for employee_id in (str(uuid4()), str(invalid_employee.pk)):
            response = self.post_json("/api/auth/switch/", {"employee_id": employee_id}, version=version)
            self.assertIn(response.status_code, (404, 409), response.content)
            self.assertEqual(self.version(), version)

    def test_return_accepts_only_empty_json_and_keeps_flow_on_validation_error(self):
        self.enter_flow()
        version = self.version()
        for data in ({"user_id": self.admin.pk}, {"employee_id": str(self.employee.pk)}, [], ["admin"]):
            with self.subTest(data=data):
                response = self.post_json("/api/auth/return-admin/", data, version=version)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.version(), version)
        self.assert_switch_state(self.return_admin(version=version), active=False, can_return=False, user=self.admin)

    def test_switch_establishes_real_employee_session_scope_and_no_admin_privilege(self):
        mine = self.grant_saved_views(self.employee)
        self.grant_saved_views(self.other_employee)
        response = self.enter_flow()
        version = response.data["account_switch"]["identity_version"]
        payload = response.data["user"]
        self.assertEqual(payload["username"], self.employee.user.username)
        self.assertEqual(str(payload["employee"]["id"]), str(self.employee.pk))
        self.assertFalse(payload["is_superuser"])
        self.assertEqual(payload["data_scope"], "ASSIGNED_AND_GRANTED")
        self.assertNotIn("auth.change_user", payload["permissions"])
        self.assertNotIn("organizations.manage_organization", payload["permissions"])
        session = self.client.session
        self.assertEqual(session[SESSION_KEY], str(self.employee.user_id))
        self.assertEqual(session[BACKEND_SESSION_KEY], "apps.core.auth.ErpModelBackend")
        self.assertEqual(session[HASH_SESSION_KEY], self.employee.user.get_session_auth_hash())
        self.assertNotEqual(session.session_key, self.root_key)
        self.employee.user.refresh_from_db()
        self.assertFalse(self.employee.user.is_superuser)
        self.assertFalse(self.employee.user.is_staff)
        response = self.client.get("/api/v1/saved-views/", HTTP_X_IDENTITY_VERSION=version)
        self.assertEqual(self.saved_view_ids(response), {str(mine.pk)})
        response = self.client.get("/api/v1/wecom/config/", HTTP_X_IDENTITY_VERSION=version)
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 200)

    def test_proof_cookie_is_protected_authless_and_never_reuses_root_as_current(self):
        self.enter_flow()
        self.assertIn(self.return_cookie_name, self.client.cookies)
        proof = self.client.cookies[self.return_cookie_name]
        self.assertTrue(proof["httponly"])
        self.assertEqual(bool(proof["secure"]), bool(settings.SESSION_COOKIE_SECURE))
        self.assertEqual(proof["samesite"], settings.SESSION_COOKIE_SAMESITE)
        self.assertEqual(proof["path"], settings.SESSION_COOKIE_PATH)
        self.assertNotEqual(proof.value, self.root_key)
        self.assertNotEqual(proof.value, self.client.session.session_key)
        control = Session.objects.get(session_key=proof.value).get_decoded()
        self.assertTrue(control)
        for key in (SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY):
            self.assertNotIn(key, control)
        self.assertEqual(Session.objects.get(session_key=self.root_key).get_decoded()[SESSION_KEY], str(self.admin.pk))
        response = self.return_admin()
        self.assert_switch_state(response, active=False, can_return=False, user=self.admin)
        self.assertNotEqual(self.client.session.session_key, self.root_key)
        self.assertEqual(self.client.session[HASH_SESSION_KEY], self.admin.get_session_auth_hash())

    def test_missing_stale_versions_block_switch_business_and_return(self):
        self.login()
        original = self.version()
        for version, status in ((None, 428), ("stale-version", 409)):
            response = self.post_json("/api/auth/switch/", {"employee_id": str(self.employee.pk)}, version=version)
            self.assertEqual(response.status_code, status, response.content)
        response = self.switch(version=original)
        current = self.assert_switch_state(response, active=True, can_return=True, user=self.employee.user)
        self.assertNotEqual(current, original)
        for headers, status in (({}, 428), ({"HTTP_X_IDENTITY_VERSION": original}, 409)):
            self.assertEqual(self.client.get("/api/v1/", **headers).status_code, status)
        for path, data in (("/api/auth/switch/", {"employee_id": str(self.other_employee.pk)}),
                           ("/api/auth/return-admin/", {})):
            for version, status in ((None, 428), (original, 409)):
                with self.subTest(path=path, version=version):
                    self.assertEqual(self.post_json(path, data, version=version).status_code, status)
        self.assertEqual(self.version(), current)
        self.assertEqual(self.client.get("/api/auth/switch-targets/").status_code, 200)
        returned = self.return_admin(version=current)
        new_version = self.assert_switch_state(returned, active=False, can_return=False, user=self.admin)
        self.assertNotIn(new_version, (original, current))
        # Returning does not remove the chain's version gate.
        self.assertEqual(self.client.get("/api/v1/").status_code, 428)
        self.assertEqual(self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=current).status_code, 409)
        # This fixture admin deliberately has no Employee.  Preserve the real
        # business API's HasActiveEmployee rule; use Django admin to prove the
        # returned identity and its new version are usable.
        business = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=new_version)
        self.assertEqual(business.status_code, 403, business.content)
        usable = self.client.get("/admin/", HTTP_X_IDENTITY_VERSION=new_version)
        self.assertEqual(usable.status_code, 200, usable.content)

    def test_active_flow_replaces_target_and_same_employee_always_rotates_version(self):
        self.enter_flow()
        root_keys = {session.session_key for session in Session.objects.all()
                     if session.get_decoded().get(SESSION_KEY) == str(self.admin.pk)}
        control_key = self.client.cookies[self.return_cookie_name].value
        versions = {self.version()}
        for employee in (self.employee, self.other_employee, self.other_employee, self.employee):
            response = self.switch(employee)
            version = self.assert_switch_state(response, active=True, can_return=True, user=employee.user)
            self.assertNotIn(version, versions)
            versions.add(version)
            self.assertEqual(self.client.cookies[self.return_cookie_name].value, control_key)
            self.assertEqual({session.session_key for session in Session.objects.all()
                              if session.get_decoded().get(SESSION_KEY) == str(self.admin.pk)}, root_keys)
            self.assertEqual(self.client.get("/api/auth/switch-targets/").data["identity_version"], version)
        self.assert_switch_state(self.return_admin(), active=False, can_return=False, user=self.admin)

    def test_target_invalidation_preserves_return_proof_but_never_executes_business(self):
        cases = ("inactive", "left", "archive", "inactive-user", "unlinked", "password", "session-deleted")
        original_password = self.employee.user.password
        for case in cases:
            with self.subTest(case=case):
                Employee.objects.filter(pk=self.employee.pk).update(
                    status=EmployeeStatus.ACTIVE, archived_at=None, user_id=self.employee.user_id)
                get_user_model().objects.filter(pk=self.employee.user_id).update(password=original_password, is_active=True)
                self.client = APIClient(enforce_csrf_checks=True)
                self.enter_flow()
                version = self.version()
                if case in ("inactive", "left"):
                    Employee.objects.filter(pk=self.employee.pk).update(
                        status=EmployeeStatus.INACTIVE if case == "inactive" else EmployeeStatus.LEFT)
                elif case == "archive":
                    Employee.objects.filter(pk=self.employee.pk).update(archived_at=timezone.now())
                elif case == "inactive-user":
                    get_user_model().objects.filter(pk=self.employee.user_id).update(is_active=False)
                elif case == "unlinked":
                    Employee.objects.filter(pk=self.employee.pk).update(user=None)
                elif case == "password":
                    self.employee.user.set_password("ChangedTargetPassword123!")
                    self.employee.user.save(update_fields=["password"])
                else:
                    Session.objects.filter(session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value).delete()
                response = self.client.get("/api/auth/me/")
                self.assertFalse(response.data["authenticated"])
                self.assertIsNone(response.data["user"])
                self.assertEqual(self.assert_switch_state(response, active=True, can_return=True), version)
                with patch("apps.core.api.views.Response", side_effect=AssertionError("business view executed")):
                    # Patch the existing view's response construction, not its URL.
                    business = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version)
                    self.assertIn(business.status_code, (401, 403), business.content)
                self.assert_switch_state(self.return_admin(version=version), active=False, can_return=False, user=self.admin)

    # 改名失效属于旧策略语义；确认角色策略的行为由独立测试覆盖。
    @override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False)
    def test_original_admin_invalidation_forbids_return(self):
        original_password = self.admin.password
        for case in ("inactive", "demoted", "renamed", "password", "root-deleted", "root-expired"):
            with self.subTest(case=case):
                get_user_model().objects.filter(pk=self.admin.pk).update(
                    username="admin", is_active=True, is_superuser=True, password=original_password)
                self.admin.refresh_from_db()
                self.client = APIClient(enforce_csrf_checks=True)
                self.enter_flow()
                version = self.version()
                if case == "inactive":
                    get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
                elif case == "demoted":
                    get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
                elif case == "renamed":
                    get_user_model().objects.filter(pk=self.admin.pk).update(username="former.admin")
                elif case == "password":
                    self.admin.set_password("ChangedAdminPassword123!")
                    self.admin.save(update_fields=["password"])
                elif case == "root-deleted":
                    Session.objects.filter(session_key=self.root_key).delete()
                else:
                    Session.objects.filter(session_key=self.root_key).update(expire_date=timezone.now() - timedelta(seconds=1))
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version).status_code, 403)
                self.assertEqual(self.client.get("/api/auth/switch-targets/").status_code, 403)

    def test_old_root_cookie_and_missing_control_never_fall_back_to_admin(self):
        self.enter_flow()
        version = self.version()
        old_root = copy_browser(self.client)
        old_root.cookies[settings.SESSION_COOKIE_NAME] = self.root_key
        old_root.cookies.pop(self.return_cookie_name, None)
        old_me = old_root.get("/api/auth/me/")
        if old_me.status_code == 200:
            self.assertFalse(old_me.data["authenticated"])
        else:
            self.assertIn(old_me.status_code, (403, 409), old_me.content)
        self.assertNotEqual(old_root.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 200)
        self.assertIn(self.post_json("/api/auth/return-admin/", {}, version=version,
                                     client=old_root).status_code, (403, 409))
        missing_control = copy_browser(self.client)
        missing_control.cookies.pop(self.return_cookie_name, None)
        self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version,
                                       client=missing_control).status_code, 403)
        me = missing_control.get("/api/auth/me/")
        if me.status_code == 200:
            self.assertTrue(me.data["user"] is None or me.data["user"]["id"] != self.admin.pk)
        else:
            self.assertIn(me.status_code, (403, 409), me.content)
        # Presenting the root with a valid control is not a browser-current admin either.
        root_and_control = copy_browser(self.client)
        root_and_control.cookies[settings.SESSION_COOKIE_NAME] = self.root_key
        me = root_and_control.get("/api/auth/me/")
        if me.status_code == 200:
            self.assertTrue(me.data["user"] is None or me.data["user"]["id"] != self.admin.pk)
        else:
            self.assertIn(me.status_code, (403, 409), me.content)

    def test_deleted_control_does_not_turn_original_root_into_normal_admin(self):
        self.enter_flow()
        version = self.version()
        old_root = copy_browser(self.client)
        old_root.cookies[settings.SESSION_COOKIE_NAME] = self.root_key
        old_root.cookies.pop(self.return_cookie_name, None)
        Session.objects.filter(session_key=self.client.cookies[self.return_cookie_name].value).delete()
        for browser in (self.client, old_root):
            with self.subTest(root=browser is old_root):
                me = browser.get("/api/auth/me/")
                if me.status_code == 200:
                    self.assertTrue(me.data["user"] is None or me.data["user"]["id"] != self.admin.pk)
                else:
                    self.assertIn(me.status_code, (403, 409), me.content)
                self.assertNotEqual(browser.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 200)
                self.assertIn(self.post_json("/api/auth/return-admin/", {}, version=version,
                                             client=browser).status_code, (403, 409))

    def test_logout_destroys_return_capability_and_replayed_control_is_forbidden(self):
        self.enter_flow()
        old_browser = copy_browser(self.client)
        version = self.version()
        response = self.post_json("/api/auth/logout/", {}, version=version)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get("/api/auth/me/").data, {"authenticated": False, "user": None})
        self.assertFalse(self.client.cookies.get(self.return_cookie_name) and self.client.cookies[self.return_cookie_name].value)
        self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version, client=old_browser).status_code, 403)
        self.login(self.employee.user)
        self.assertEqual(set(self.client.get("/api/auth/me/").data), {"authenticated", "user"})

    def test_logout_without_version_is_csrf_protected_even_after_target_invalidation(self):
        # Lead-confirmed escape hatch: explicit logout is version-exempt, unlike
        # business traffic and the switch/return actions.
        for invalidate in (False, True):
            with self.subTest(invalidate=invalidate):
                Employee.objects.filter(pk=self.employee.pk).update(status=EmployeeStatus.ACTIVE)
                self.client = APIClient(enforce_csrf_checks=True)
                self.enter_flow()
                old_browser = copy_browser(self.client)
                old_version = self.version()
                if invalidate:
                    Employee.objects.filter(pk=self.employee.pk).update(status=EmployeeStatus.INACTIVE)
                denied = self.post_json("/api/auth/logout/", {}, csrf=False)
                self.assertEqual(denied.status_code, 403, denied.content)
                response = self.post_json("/api/auth/logout/", {})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(self.client.get("/api/auth/me/").data, {"authenticated": False, "user": None})
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=old_version,
                                               client=old_browser).status_code, 403)

    def test_explicit_password_relogin_even_same_identity_revokes_old_flow(self):
        for login_user in (self.employee.user, self.other_employee.user, self.admin):
            with self.subTest(username=login_user.username):
                self.client = APIClient(enforce_csrf_checks=True)
                self.enter_flow()
                old_browser = copy_browser(self.client)
                old_version = self.version()
                old_control = self.client.cookies[self.return_cookie_name].value
                self.login(login_user)
                me = self.client.get("/api/auth/me/")
                self.assertEqual(me.data["user"]["id"], login_user.pk)
                if login_user.pk == self.admin.pk:
                    self.assert_switch_state(me, active=False, can_return=False, user=self.admin)
                else:
                    self.assertEqual(set(me.data), {"authenticated", "user"})
                self.assertFalse(self.client.cookies.get(self.return_cookie_name) and self.client.cookies[self.return_cookie_name].value)
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=old_version,
                                               client=old_browser).status_code, 403)
                self.client.cookies[self.return_cookie_name] = old_control
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=old_version).status_code, 403)

    @override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()])
    @patch("apps.wecom.services.WeComClient")
    def test_explicit_wecom_same_employee_login_revokes_old_return_capability(self, client_class):
        from apps.wecom.credentials import encrypt_secret
        from apps.wecom.models import WeComBinding, WeComConfig

        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("identity-test-secret"))
        WeComBinding.objects.create(employee=self.employee, corp_id=config.corp_id,
                                    user_id="Identity.Switch.Member", member_name="切换员工甲", source="MANUAL")
        client_class.return_value.get_identity.return_value = {"userid": "Identity.Switch.Member", "corpid": config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "Identity.Switch.Member", "name": "切换员工甲", "status": 1}
        self.enter_flow()
        challenge = self.post_json("/api/auth/wecom/qr/", {})
        self.assertEqual(challenge.status_code, 200, challenge.content)
        old_browser = copy_browser(self.client)
        version = self.version()
        callback = self.client.get("/api/auth/wecom/callback/", {"state": challenge.data["state"], "code": "identity-code"})
        self.assertEqual(callback.status_code, 302, callback.content)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.employee.user_id))
        self.assertFalse(self.client.cookies.get(self.return_cookie_name) and self.client.cookies[self.return_cookie_name].value)
        self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version, client=old_browser).status_code, 403)

    def test_django_admin_explicit_login_revokes_old_return_capability(self):
        self.enter_flow()
        old_browser = copy_browser(self.client)
        version = self.version()
        response = self.client.post("/admin/login/?next=/admin/", {
            "username": self.admin.username, "password": PASSWORD, "next": "/admin/",
            "csrfmiddlewaretoken": self.csrf(),
        }, HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.admin.pk))
        self.assertFalse(self.client.cookies.get(self.return_cookie_name) and self.client.cookies[self.return_cookie_name].value)
        self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version, client=old_browser).status_code, 403)

    def test_anonymous_django_admin_first_login_uses_real_form_csrf_and_opens_admin(self):
        self.assertFalse(self.client.cookies)
        self.assertFalse(Session.objects.exists())
        form = self.client.get("/admin/login/?next=/admin/")
        self.assertEqual(form.status_code, 200, form.content)
        self.assertIn(settings.CSRF_COOKIE_NAME, self.client.cookies)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form.content.decode())
        self.assertIsNotNone(token, form.content)
        # No API login, force-authentication, or test-client session creation:
        # this is genuinely the first login without a pre-existing Session row.
        self.assertFalse(Session.objects.exists())
        response = self.client.post("/admin/login/?next=/admin/", {
            "username": self.admin.username, "password": PASSWORD, "next": "/admin/",
            "csrfmiddlewaretoken": token.group(1),
        })
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(response["Location"], "/admin/")
        self.assertEqual(self.client.session[SESSION_KEY], str(self.admin.pk))
        self.assertEqual(self.client.session[BACKEND_SESSION_KEY], "apps.core.auth.ErpModelBackend")
        self.assertEqual(self.client.session[HASH_SESSION_KEY], self.admin.get_session_auth_hash())
        self.assertFalse(Employee.objects.filter(user=self.admin).exists())
        home = self.client.get("/admin/")
        self.assertEqual(home.status_code, 200, home.content)

    def test_explicit_admin_relogin_response_version_can_switch_without_me_refresh(self):
        self.enter_flow()
        old_version = self.version()
        old_browser = copy_browser(self.client)
        old_session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        relogin = self.login(self.admin)
        response_version = self.assert_switch_state(relogin, active=False, can_return=False, user=self.admin)
        self.assertNotEqual(response_version, old_version)
        self.assertNotEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, old_session)
        self.assertFalse(Employee.objects.filter(user=self.admin).exists())
        # Pass the login response's token explicitly: neither post_json's CSRF
        # helper (cookie already present) nor switch() may fetch /auth/me/ here.
        switched = self.post_json("/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                                  version=response_version)
        self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        denied = self.post_json("/api/auth/return-admin/", {}, version=old_version, client=old_browser)
        self.assertEqual(denied.status_code, 403, denied.content)

    def test_password_login_audit_fault_rolls_back_signal_sessions_and_last_login(self):
        for save_every in (False, True):
            for fault_class, expected_status in ((RuntimeError, 500), (ValidationError, 400)):
                with self.subTest(save_every=save_every, fault=fault_class.__name__), override_settings(
                    SESSION_SAVE_EVERY_REQUEST=save_every
                ):
                    self.client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
                    self.enter_flow()
                    old_version = self.version()
                    old_root = self.root_key
                    old_current = self.client.cookies[settings.SESSION_COOKIE_NAME].value
                    old_control = self.client.cookies[self.return_cookie_name].value
                    sessions = self.session_snapshot()
                    last_logins = self.last_login_snapshot()
                    cookies = self.browser_cookie_snapshot()

                    def fail_after_real_signal(request, user, method):
                        self.assertEqual(method, "PASSWORD")
                        self.assertEqual(user.pk, self.employee.user_id)
                        self.assertNotEqual(request.session.session_key, old_current)
                        self.assertFalse(Session.objects.filter(session_key__in=(old_root, old_control)).exists())
                        raise fault_class("Intentional post-login audit failure")

                    with patch("apps.core.views.record_successful_login", side_effect=fail_after_real_signal) as audit:
                        failed = self.post_json("/api/auth/login/", {
                            "username": self.employee.user.username, "password": PASSWORD,
                        })
                    audit.assert_called_once()
                    self.assertEqual(failed.status_code, expected_status, failed.content)
                    self.assert_no_authentication_cookies(failed)
                    self.assertEqual(self.browser_cookie_snapshot(), cookies)
                    self.assertEqual(self.session_snapshot(), sessions)
                    self.assertEqual(self.last_login_snapshot(), last_logins)
                    self.assertEqual(self.version(), old_version)
                    self.assertEqual(self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version).status_code, 200)
                    self.assert_switch_state(self.return_admin(version=old_version), active=False, can_return=False, user=self.admin)

    @override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], SESSION_SAVE_EVERY_REQUEST=True)
    @patch("apps.wecom.services.WeComClient")
    def test_wecom_post_signal_failure_redirect_does_not_commit_new_session(self, client_class):
        from apps.wecom.credentials import encrypt_secret
        from apps.wecom.models import WeComBinding, WeComConfig
        from apps.wecom.services import OAuthFailure

        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("rollback-wecom-secret"))
        WeComBinding.objects.create(employee=self.employee, corp_id=config.corp_id,
                                    user_id="Identity.Rollback.Member", member_name="切换员工甲", source="MANUAL")
        client_class.return_value.get_identity.return_value = {"userid": "Identity.Rollback.Member", "corpid": config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "Identity.Rollback.Member", "name": "切换员工甲", "status": 1}
        self.enter_flow()
        challenge = self.post_json("/api/auth/wecom/qr/", {})
        self.assertEqual(challenge.status_code, 200, challenge.content)
        old_version = self.version()
        business_baseline = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
        self.assertEqual(business_baseline.status_code, 403, business_baseline.content)
        self.assertEqual(business_baseline.json()["error"]["code"], "WECOM_ROLE_REQUIRED")
        old_root = self.root_key
        old_current = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        old_control = self.client.cookies[self.return_cookie_name].value
        sessions = self.session_snapshot()
        last_logins = self.last_login_snapshot()
        cookies = self.browser_cookie_snapshot()

        def fail_after_real_signal(request, user, method):
            self.assertEqual(method, "WECOM")
            self.assertEqual(user.pk, self.employee.user_id)
            self.assertNotEqual(request.session.session_key, old_current)
            self.assertFalse(Session.objects.filter(session_key__in=(old_root, old_control)).exists())
            raise OAuthFailure("MEMBER_REJECTED")

        with patch("apps.core.login_records.record_successful_login", side_effect=fail_after_real_signal) as audit:
            failed = self.client.get("/api/auth/wecom/callback/", {"state": challenge.data["state"], "code": "rollback-code"})
        audit.assert_called_once()
        self.assertEqual(failed.status_code, 302, failed.content)
        self.assertEqual(failed["Location"], "/auth/wecom-error?reason=MEMBER_REJECTED")
        self.assert_no_authentication_cookies(failed)
        self.assertEqual(self.browser_cookie_snapshot(), cookies)
        self.assertEqual(self.session_snapshot(), sessions)
        self.assertEqual(self.last_login_snapshot(), last_logins)
        me = self.client.get("/api/auth/me/")
        self.assertEqual(self.assert_switch_state(me, active=True, can_return=True, user=self.employee.user), old_version)
        recovered_business = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
        self.assertEqual(recovered_business.status_code, business_baseline.status_code, recovered_business.content)
        self.assertEqual(recovered_business.json()["error"]["code"], business_baseline.json()["error"]["code"])
        self.assert_switch_state(self.return_admin(version=old_version), active=False, can_return=False, user=self.admin)

    def test_original_browser_close_policy_and_absolute_deadline_survive_all_transitions(self):
        # Both sources of browser-close policy, ordinary persistence, and an
        # explicit persistent expiry overriding a global browser-close default.
        scenarios = ((False, None, False), (False, 0, True),
                     (True, None, True), (True, 300, False))
        for global_close, expiry, expected_close in scenarios:
            for save_every in (False, True):
                with self.subTest(global_close=global_close, expiry=expiry, save_every=save_every), override_settings(
                    SESSION_EXPIRE_AT_BROWSER_CLOSE=global_close,
                    SESSION_SAVE_EVERY_REQUEST=save_every,
                ):
                    self.client = APIClient(enforce_csrf_checks=True)
                    login = self.login()
                    version = login.data["account_switch"]["identity_version"]
                    self.root_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
                    original = SessionStore(session_key=self.root_key)
                    if expiry is not None:
                        original.set_expiry(expiry)
                        original.save()
                    self.assertIs(original.get_expire_at_browser_close(), expected_close)
                    deadline = Session.objects.get(session_key=self.root_key).expire_date
                    previous_ages = {}
                    for step in range(3):
                        response = self.return_admin(version=version) if step == 2 else self.switch(version=version)
                        version = self.assert_switch_state(
                            response, active=step != 2, can_return=step != 2,
                            user=self.admin if step == 2 else self.employee.user,
                        )
                        current_key = response.cookies[settings.SESSION_COOKIE_NAME].value
                        control_key = response.cookies[self.return_cookie_name].value
                        self.assertEqual(current_key, response.wsgi_request.session.session_key)
                        control = Session.objects.get(session_key=control_key).get_decoded()
                        self.assertIs(control["browser_close"], expected_close)
                        expiries = list(Session.objects.filter(
                            session_key__in=(self.root_key, control_key, current_key),
                        ).values_list("expire_date", flat=True))
                        self.assertEqual(expiries, [deadline] * 3)
                        for name in (settings.SESSION_COOKIE_NAME, self.return_cookie_name):
                            cookie = response.cookies[name]
                            self.assertTrue(cookie.value)
                            self.assertEqual(cookie["path"], settings.SESSION_COOKIE_PATH)
                            self.assertEqual(cookie["domain"], settings.SESSION_COOKIE_DOMAIN or "")
                            self.assertEqual(cookie["samesite"], settings.SESSION_COOKIE_SAMESITE)
                            self.assertTrue(cookie["httponly"])
                            if expected_close:
                                self.assertEqual(cookie["max-age"], "")
                                self.assertEqual(cookie["expires"], "")
                                self.assertNotIn("max-age=", cookie.OutputString().lower())
                                self.assertNotIn("expires=", cookie.OutputString().lower())
                            else:
                                age = int(cookie["max-age"])
                                self.assertGreater(age, 0)
                                self.assertTrue(cookie["expires"])
                                self.assertLessEqual(age, previous_ages.get(name, age))
                                previous_ages[name] = age
                        me = self.client.get("/api/auth/me/")
                        self.assertEqual(me.status_code, 200, me.content)
                        self.assertNotIn(settings.SESSION_COOKIE_NAME, me.cookies)
                        self.assertNotIn(self.return_cookie_name, me.cookies)
                        self.assertEqual(list(Session.objects.filter(
                            session_key__in=(self.root_key, control_key, current_key),
                        ).values_list("expire_date", flat=True)), [deadline] * 3)

    def test_debug_html_and_text_payload_failures_hide_flow_secrets_and_keep_return(self):
        for cookie_name in (settings.SESSION_COOKIE_NAME, "identity_debug_session"):
            for accept in ("text/html", "application/json"):
                with self.subTest(cookie_name=cookie_name, accept=accept), override_settings(
                    DEBUG=True, DEBUG_PROPAGATE_EXCEPTIONS=False,
                    SESSION_COOKIE_NAME=cookie_name, SESSION_SAVE_EVERY_REQUEST=True,
                ):
                    self.client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
                    switched = self.enter_flow()
                    old_version = switched.data["account_switch"]["identity_version"]
                    self.client.cookies["reporter_public"] = "visible-public-marker"
                    secrets = self.flow_secret_values()
                    sessions = self.session_snapshot()
                    last_logins = self.last_login_snapshot()
                    cookies = self.browser_cookie_snapshot()
                    with patch("apps.core.views.user_payload", side_effect=RuntimeError("Intentional DEBUG payload failure")):
                        failed = self.client.get("/api/auth/me/", HTTP_ACCEPT=accept)
                    self.assert_debug_failure_redacts_flow(failed, secrets, accept)
                    self.assertEqual(self.session_snapshot(), sessions)
                    self.assertEqual(self.last_login_snapshot(), last_logins)
                    self.assertEqual(self.browser_cookie_snapshot(), cookies)
                    me = self.client.get("/api/auth/me/")
                    self.assertEqual(self.assert_switch_state(me, active=True, can_return=True, user=self.employee.user), old_version)
                    business = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
                    self.assertEqual(business.status_code, 200, business.content)
                    self.assert_switch_state(self.return_admin(version=old_version), active=False, can_return=False, user=self.admin)

    @override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()])
    @patch("apps.wecom.services.WeComClient")
    def test_debug_wecom_callback_replaced_filter_hides_flow_secrets_and_rolls_back(self, client_class):
        from apps.core.identity_switch_services import NONCE
        from apps.wecom.credentials import encrypt_secret
        from apps.wecom.middleware import WeComExceptionReporterFilter
        from apps.wecom.models import WeComBinding, WeComConfig

        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("debug-wecom-secret"))
        WeComBinding.objects.create(employee=self.employee, corp_id=config.corp_id,
                                    user_id="Identity.Debug.Member", member_name="切换员工甲", source="MANUAL")
        client_class.return_value.get_identity.return_value = {"userid": "Identity.Debug.Member", "corpid": config.corp_id}
        client_class.return_value.get_member.return_value = {"userid": "Identity.Debug.Member", "name": "切换员工甲", "status": 1}
        for cookie_name in (settings.SESSION_COOKIE_NAME, "identity_debug_session"):
            for accept in ("text/html", "application/json"):
                with self.subTest(cookie_name=cookie_name, accept=accept), override_settings(
                    DEBUG=True, DEBUG_PROPAGATE_EXCEPTIONS=False,
                    SESSION_COOKIE_NAME=cookie_name, SESSION_SAVE_EVERY_REQUEST=True,
                ):
                    self.client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
                    switched = self.enter_flow()
                    old_version = switched.data["account_switch"]["identity_version"]
                    challenge = self.post_json("/api/auth/wecom/qr/", {})
                    self.assertEqual(challenge.status_code, 200, challenge.content)
                    business_baseline = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
                    self.assertEqual(business_baseline.status_code, 403, business_baseline.content)
                    self.assertEqual(business_baseline.json()["error"]["code"], "WECOM_ROLE_REQUIRED")
                    self.client.cookies["reporter_public"] = "visible-public-marker"
                    secrets = self.flow_secret_values()
                    sessions = self.session_snapshot()
                    last_logins = self.last_login_snapshot()
                    cookies = self.browser_cookie_snapshot()

                    @sensitive_variables()
                    def fail_after_real_signal(request, user, method):
                        self.assertEqual(method, "WECOM")
                        self.assertEqual(user.pk, self.employee.user_id)
                        secrets["failed_current"] = request.session.session_key
                        secrets["failed_nonce"] = request.session[NONCE]
                        self.assertNotEqual(secrets["failed_current"], secrets["current"])
                        self.assertFalse(Session.objects.filter(session_key__in=(secrets["root"], secrets["control"])).exists())
                        raise RuntimeError("Intentional DEBUG WeCom login-record failure")

                    with patch("apps.core.login_records.record_successful_login", side_effect=fail_after_real_signal) as audit:
                        failed = self.client.get("/api/auth/wecom/callback/", {
                            "state": challenge.data["state"], "code": "debug-callback-code",
                        }, HTTP_ACCEPT=accept)
                    audit.assert_called_once()
                    reporter_filter = self.assert_debug_failure_redacts_flow(failed, secrets, accept)
                    self.assertIsInstance(reporter_filter, WeComExceptionReporterFilter)
                    self.assertEqual(self.session_snapshot(), sessions)
                    self.assertEqual(self.last_login_snapshot(), last_logins)
                    self.assertEqual(self.browser_cookie_snapshot(), cookies)
                    me = self.client.get("/api/auth/me/")
                    self.assertEqual(self.assert_switch_state(me, active=True, can_return=True, user=self.employee.user), old_version)
                    business = self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
                    self.assertEqual(business.status_code, business_baseline.status_code, business.content)
                    self.assertEqual(business.json()["error"]["code"], business_baseline.json()["error"]["code"])
                    self.assert_switch_state(self.return_admin(version=old_version), active=False, can_return=False, user=self.admin)

    @override_settings(
        SESSION_COOKIE_NAME="__Secure-identity_custom_session", SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_DOMAIN="example.test", SESSION_COOKIE_PATH="/", SESSION_COOKIE_SAMESITE="Strict",
    )
    def test_custom_return_auth_cookie_attributes_and_legacy_name_never_authorizes(self):
        switched = self.enter_flow()
        old_version = switched.data["account_switch"]["identity_version"]
        expected_name = settings.SESSION_COOKIE_NAME + "_admin_return_auth"
        legacy_name = settings.SESSION_COOKIE_NAME + "_admin_return"
        self.assertEqual(self.return_cookie_name, expected_name)
        self.assertIn(expected_name, switched.cookies)
        self.assertNotIn(legacy_name, switched.cookies)
        proof = switched.cookies[expected_name]
        self.assertTrue(proof["httponly"])
        self.assertTrue(proof["secure"])
        self.assertEqual(proof["domain"], settings.SESSION_COOKIE_DOMAIN)
        self.assertEqual(proof["path"], settings.SESSION_COOKIE_PATH)
        self.assertEqual(proof["samesite"], settings.SESSION_COOKIE_SAMESITE)
        legacy_browser = copy_browser(self.client)
        legacy_browser.cookies.pop(expected_name)
        legacy_browser.cookies[legacy_name] = proof.value
        forbidden = self.return_admin(version=old_version, client=legacy_browser)
        self.assertEqual(forbidden.status_code, 403, forbidden.content)
        self.assert_no_authentication_cookies(forbidden)
        returned = self.return_admin(version=old_version)
        self.assert_switch_state(returned, active=False, can_return=False, user=self.admin)
        self.assertNotIn(legacy_name, returned.cookies)
        logged_out = self.post_json("/api/auth/logout/", {})
        self.assertEqual(logged_out.status_code, 200, logged_out.content)
        self.assertNotIn(legacy_name, logged_out.cookies)
        cleared = logged_out.cookies[expected_name]
        self.assertEqual(cleared.value, "")
        self.assertEqual(cleared["max-age"], 0)
        self.assertEqual(cleared["domain"], settings.SESSION_COOKIE_DOMAIN)
        self.assertEqual(cleared["path"], settings.SESSION_COOKIE_PATH)
        self.assertEqual(cleared["samesite"], settings.SESSION_COOKIE_SAMESITE)
        self.assertTrue(cleared["secure"])  # Django preserves __Secure- on deletion.

    def test_switch_and_return_payload_fault_rolls_back_and_same_request_can_retry(self):
        for save_every in (False, True):
            for phase in ("initial-switch", "replace-switch", "return"):
                with self.subTest(save_every=save_every, phase=phase), override_settings(
                    SESSION_SAVE_EVERY_REQUEST=save_every
                ):
                    self.client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
                    if phase == "initial-switch":
                        self.login()
                        previous_user = self.admin
                    else:
                        self.enter_flow()
                        previous_user = self.employee.user
                    old_version = self.version()
                    sessions = self.session_snapshot()
                    last_logins = self.last_login_snapshot()
                    cookies = self.browser_cookie_snapshot()
                    path = "/api/auth/return-admin/" if phase == "return" else "/api/auth/switch/"
                    payload = {} if phase == "return" else {"employee_id": str(self.other_employee.pk)}
                    with patch("apps.core.views.user_payload", side_effect=RuntimeError("Intentional identity payload failure")) as render:
                        failed = self.post_json(path, payload, version=old_version)
                    render.assert_called_once()
                    self.assertEqual(failed.status_code, 500, failed.content)
                    self.assert_no_authentication_cookies(failed)
                    self.assertEqual(self.browser_cookie_snapshot(), cookies)
                    self.assertEqual(self.session_snapshot(), sessions)
                    self.assertEqual(self.last_login_snapshot(), last_logins)
                    me = self.client.get("/api/auth/me/")
                    self.assertEqual(me.data["user"]["id"], previous_user.pk)
                    self.assertEqual(self.version(), old_version)
                    retried = self.post_json(path, payload, version=old_version)
                    self.assert_switch_state(retried, active=phase != "return", can_return=phase != "return",
                                             user=self.admin if phase == "return" else self.other_employee.user)

    def test_old_successful_switch_response_all_cookies_cannot_restore_employee_after_return(self):
        old_switch = self.enter_flow()
        employee_version = self.version()
        returned = self.return_admin(version=employee_version)
        admin_version = self.assert_switch_state(returned, active=False, can_return=False, user=self.admin)
        current_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        control_key = self.client.cookies[self.return_cookie_name].value
        snapshot = self.session_snapshot()
        replayed = copy_browser(self.client)
        self.apply_all_response_cookies(old_switch, replayed)
        self.assert_current_or_rejected(replayed, self.admin, employee_version)
        self.assertEqual(self.session_snapshot(), snapshot)
        control = Session.objects.get(session_key=control_key).get_decoded()
        self.assertEqual(control["current"], current_key)
        self.assertEqual(control["current_user_id"], str(self.admin.pk))
        self.assertEqual(self.version(), admin_version)
        usable = self.client.get("/admin/", HTTP_X_IDENTITY_VERSION=admin_version)
        self.assertEqual(usable.status_code, 200, usable.content)

    def test_old_successful_return_response_all_cookies_cannot_restore_admin_after_new_switch(self):
        self.enter_flow()
        old_return = self.return_admin()
        returned_version = self.assert_switch_state(old_return, active=False, can_return=False, user=self.admin)
        switched = self.switch(self.other_employee, version=returned_version)
        version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        replayed = copy_browser(self.client)
        self.apply_all_response_cookies(old_return, replayed)
        self.assert_current_or_rejected(replayed, self.other_employee.user, returned_version)
        self.assertEqual(self.client.get("/api/auth/me/").data["user"]["id"], self.other_employee.user_id)
        self.assertEqual(self.client.get("/api/v1/wecom/config/", HTTP_X_IDENTITY_VERSION=version).status_code, 403)

    def test_successful_switch_and_return_response_cookie_replays_cannot_resurrect_logout(self):
        old_switch = self.enter_flow()
        employee_version = self.version()
        old_return = self.return_admin()
        returned_version = self.assert_switch_state(old_return, active=False, can_return=False, user=self.admin)
        response = self.post_json("/api/auth/logout/", {})
        self.assertEqual(response.status_code, 200, response.content)
        remaining = self.session_snapshot()
        for historical, version in ((old_return, returned_version), (old_switch, employee_version)):
            replayed = copy_browser(self.client)
            self.apply_all_response_cookies(historical, replayed)
            self.assert_current_or_rejected(replayed, None, version)
            self.assertIn(self.post_json("/api/auth/return-admin/", {}, version=version,
                                         client=replayed).status_code, (403, 409))
        self.assertEqual(self.session_snapshot(), remaining)
        self.assertEqual(self.client.get("/api/auth/me/").data, {"authenticated": False, "user": None})

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_absolute_root_control_and_current_expiries_never_slide(self):
        self.login()
        self.root_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        start = timezone.now()
        deadline = start + timedelta(hours=1)
        root = SessionStore(session_key=self.root_key)
        root.set_expiry(deadline)
        root.save()
        self.assertEqual(Session.objects.get(session_key=self.root_key).expire_date, deadline)
        switched = self.switch()
        version = self.assert_switch_state(switched, active=True, can_return=True, user=self.employee.user)
        control_key = self.client.cookies[self.return_cookie_name].value

        def assert_deadlines():
            current = self.client.cookies[settings.SESSION_COOKIE_NAME].value
            for key in (self.root_key, control_key, current):
                self.assertEqual(Session.objects.get(session_key=key).expire_date, deadline)
            control = Session.objects.get(session_key=control_key).get_decoded()
            self.assertEqual(control["current"], current)

        assert_deadlines()
        for minute, employee in ((10, self.employee), (20, self.other_employee)):
            with patch("django.utils.timezone.now", return_value=start + timedelta(minutes=minute)):
                self.assertEqual(self.version(), version)
                self.assertEqual(self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 200)
                assert_deadlines()
                response = self.switch(employee, version=version)
                version = self.assert_switch_state(response, active=True, can_return=True, user=employee.user)
                assert_deadlines()
                self.assertLessEqual(int(response.cookies[self.return_cookie_name]["max-age"]), 3600 - minute * 60)
        with patch("django.utils.timezone.now", return_value=start + timedelta(minutes=30)):
            returned = self.return_admin(version=version)
            version = self.assert_switch_state(returned, active=False, can_return=False, user=self.admin)
            assert_deadlines()
            usable = self.client.get("/admin/", HTTP_X_IDENTITY_VERSION=version)
            self.assertEqual(usable.status_code, 200, usable.content)
            assert_deadlines()
        with patch("django.utils.timezone.now", return_value=deadline + timedelta(seconds=1)):
            expired = self.client.get("/admin/", HTTP_X_IDENTITY_VERSION=version)
            self.assertIn(expired.status_code, (302, 401, 403, 409), expired.content)
            if expired.status_code == 302:
                self.assertTrue(expired["Location"].startswith("/admin/login/"), expired["Location"])

    def test_malformed_existing_root_marker_never_falls_back_to_normal_admin(self):
        from apps.core.identity_switch_services import MARKER

        malformed_markers = ("broken", {}, {"root": "bad", "control": "bad"},
                             {"root": "a" * 32}, {"control": "b" * 32}, None)
        for malformed in malformed_markers:
            with self.subTest(marker=malformed):
                self.client = APIClient(enforce_csrf_checks=True)
                self.enter_flow()
                old_version = self.version()
                root_browser = copy_browser(self.client)
                root_browser.cookies[settings.SESSION_COOKIE_NAME] = self.root_key
                root_browser.cookies.pop(self.return_cookie_name, None)
                root = SessionStore(session_key=self.root_key)
                root[MARKER] = malformed
                root.save()
                self.assert_current_or_rejected(root_browser, None, old_version)
                self.assertIn(self.post_json("/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                                             version=old_version, client=root_browser).status_code, (403, 409))

    def test_mismatched_control_cookie_never_authorizes_return_or_root_admin_fallback(self):
        self.enter_flow()
        first_browser = copy_browser(self.client)
        first_root = self.root_key
        first_version = self.version()
        self.client = APIClient(enforce_csrf_checks=True)
        self.enter_flow()
        second_browser = copy_browser(self.client)
        second_root = self.root_key
        second_version = self.version()
        pairs = ((first_browser, first_root, first_version, second_browser),
                 (second_browser, second_root, second_version, first_browser))
        for browser, root, version, other in pairs:
            with self.subTest(root=root == first_root):
                mixed = copy_browser(browser)
                mixed.cookies[self.return_cookie_name] = other.cookies[self.return_cookie_name].value
                self.assertEqual(self.post_json("/api/auth/return-admin/", {}, version=version, client=mixed).status_code, 403)
                self.assertEqual(self.post_json("/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                                                version=version, client=mixed).status_code, 403)
                mixed_root = copy_browser(mixed)
                mixed_root.cookies[settings.SESSION_COOKIE_NAME] = root
                self.assert_current_or_rejected(mixed_root, None, version)
                # A failed mixed-capability request must not revoke the genuine
                # chain in either independent browser.
                self.assertEqual(self.version(browser), version)
                self.assert_switch_state(self.return_admin(version=version, client=browser),
                                         active=False, can_return=False, user=self.admin)

    def test_switch_and_return_add_no_dedicated_audit_records(self):
        self.login()
        audit_ids = set(AuditLog.objects.values_list("pk", flat=True))
        self.assertTrue(audit_ids)  # Real explicit login keeps its existing audit.
        self.assertEqual(self.switch().status_code, 200)
        self.assertEqual(self.switch(self.other_employee).status_code, 200)
        self.assertEqual(self.return_admin().status_code, 200)
        self.assertEqual(set(AuditLog.objects.values_list("pk", flat=True)), audit_ids)
