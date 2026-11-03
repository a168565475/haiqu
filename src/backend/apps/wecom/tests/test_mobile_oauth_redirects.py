from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import RequestFactory, SimpleTestCase

from apps.wecom import services, views
from apps.wecom.client import WeComError
from apps.wecom.credentials import CredentialError
from apps.wecom.serializers import QRStartSerializer


class MemorySession(dict):
    session_key = "mobile-oauth-unit-session"

    def save(self):
        pass


class MobileOAuthRedirectTests(SimpleTestCase):
    state = "A" * 43
    next_path = "/m/plan?plan=unit-plan&workshop=unit-workshop"

    def request(self, path="/api/auth/wecom/callback/", *, saved_next=None, **query):
        request = RequestFactory().get(path, query)
        request.user = SimpleNamespace(is_authenticated=False, pk=None)
        request.session = MemorySession()
        if saved_next is not None:
            request.session["wecom_qr_redirects"] = {
                services._digest(self.state): {"path": saved_next, "expires_at": 1},
            }
        return request

    def assert_destination(self, response, path, **query):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, path)
        self.assertEqual(parse_qs(urlsplit(response.url).query), {key: [value] for key, value in query.items()})
        self.assertIn("no-store", response["Cache-Control"])

    def test_mobile_business_next_is_preserved(self):
        for next_path in ("/m", "/m/", self.next_path, "/m/plan?id=one#report", "/customers?tab=mine"):
            with self.subTest(next_path=next_path):
                serializer = QRStartSerializer(data={"next": next_path})
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["next"], next_path)

    def test_external_and_authentication_next_are_rejected(self):
        for next_path in ("https://outside.example", "//outside.example", "/%2foutside.example",
                          "/%5coutside.example", "/m/../login", "/m/login", "/m/login/",
                          "/m/auth", "/m/auth/wecom-error", "/m/AUTH/waiting-role",
                          "/m/%61uth/waiting-role", "/login", "/api/auth/me/", "/auth/waiting-role"):
            with self.subTest(next_path=next_path):
                self.assertFalse(QRStartSerializer(data={"next": next_path}).is_valid())

    def test_start_missing_schema_returns_to_validated_mobile_next(self):
        request = self.request("/api/auth/wecom/start/", next=self.next_path)
        with patch("apps.wecom.selectors.schema_is_ready", return_value=False):
            response = views.oauth_start(request)
        self.assert_destination(response, "/m/auth/wecom-error", reason="CONFIGURATION_ERROR", next=self.next_path)

    def test_start_disabled_or_incomplete_config_preserves_mobile_next(self):
        for enabled, complete in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, complete=complete):
                request = self.request("/api/auth/wecom/start/", next=self.next_path)
                config = SimpleNamespace(_state=SimpleNamespace(adding=False), enabled=enabled)
                with patch("apps.wecom.selectors.schema_is_ready", return_value=True), \
                     patch("apps.wecom.selectors.get_config", return_value=config), \
                     patch("apps.wecom.selectors.configuration_complete", return_value=complete), \
                     patch("apps.wecom.services.oauth_url") as oauth_url:
                    response = views.oauth_start(request)
                oauth_url.assert_not_called()
                self.assert_destination(response, "/m/auth/wecom-error", reason="CONFIGURATION_ERROR", next=self.next_path)

    def test_start_passes_validated_next_to_existing_oauth_flow(self):
        request = self.request("/api/auth/wecom/start/", next=self.next_path)
        config = SimpleNamespace(_state=SimpleNamespace(adding=False), enabled=True)
        with patch("apps.wecom.selectors.schema_is_ready", return_value=True), \
             patch("apps.wecom.selectors.get_config", return_value=config), \
             patch("apps.wecom.selectors.configuration_complete", return_value=True), \
             patch("apps.wecom.services.oauth_url", return_value="https://open.weixin.qq.com/unit-test") as oauth_url:
            response = views.oauth_start(request)
        oauth_url.assert_called_once_with(request, config, self.next_path)
        self.assertEqual(response.url, "https://open.weixin.qq.com/unit-test")

    def test_start_invalid_or_duplicate_next_cannot_choose_mobile_error(self):
        for query in ({"next": "//outside.example"}, {"next": "/m/auth/wecom-error"},
                      {"next": ["/m/", "/customers"]}, {"next": "/m/", "unknown": "yes"}):
            request = self.request("/api/auth/wecom/start/", **query)
            with patch("apps.wecom.selectors.schema_is_ready", return_value=True):
                response = views.oauth_start(request)
            self.assert_destination(response, "/auth/wecom-error", reason="LOGIN_FAILED")

    def test_desktop_start_errors_keep_existing_query_contract(self):
        for next_path in ("/customers", "/mobile", "/m-other"):
            request = self.request("/api/auth/wecom/start/", next=next_path)
            with patch("apps.wecom.selectors.schema_is_ready", return_value=False):
                response = views.oauth_start(request)
            self.assert_destination(response, "/auth/wecom-error", reason="CONFIGURATION_ERROR")

    def callback_failure(self, failure, *, saved_next=None, state=None, query_next="/m/forged"):
        request = self.request(saved_next=saved_next, state=self.state if state is None else state,
                               code="unit-code", next=query_next)
        with patch("apps.wecom.selectors.schema_is_ready", return_value=True), \
             patch("apps.wecom.services.oauth_login", side_effect=failure), \
             patch("apps.wecom.services.audit_login_failure") as audit:
            response = views.oauth_callback(request)
        audit.assert_called_once()
        self.assertEqual(request.GET.dict(), {})
        return response

    def test_callback_errors_use_only_saved_mobile_next_and_public_reason(self):
        cases = ((services.OAuthFailure("BINDING_REQUIRED"), "BINDING_REQUIRED"),
                 (services.OAuthFailure("ACCOUNT_MISMATCH"), "IDENTITY_MISMATCH"),
                 (CredentialError(), "CONFIGURATION_ERROR"),
                 (WeComError("MEMBER_REJECTED", "private upstream details"), "MEMBER_REJECTED"),
                 (WeComError("UNKNOWN_UPSTREAM", "private upstream details"), "UPSTREAM_UNAVAILABLE"))
        for failure, reason in cases:
            with self.subTest(reason=reason):
                response = self.callback_failure(failure, saved_next=self.next_path)
                self.assert_destination(response, "/m/auth/wecom-error", reason=reason, next=self.next_path)
                self.assertNotIn("private", response.url)

    def test_unknown_foreign_or_malformed_state_cannot_use_query_next(self):
        for state, saved_next in ((self.state, None), ("B" * 43, self.next_path), ("invalid", self.next_path)):
            response = self.callback_failure(services.OAuthFailure("INVALID_STATE"), saved_next=saved_next, state=state)
            self.assert_destination(response, "/auth/wecom-error", reason="STATE_INVALID")

    def test_known_expired_state_returns_mobile_error_without_login(self):
        response = self.callback_failure(services.OAuthFailure("INVALID_STATE"), saved_next=self.next_path)
        self.assert_destination(response, "/m/auth/wecom-error", reason="STATE_INVALID", next=self.next_path)

    def test_invalid_stored_return_path_is_not_reused(self):
        for saved_next in ("//outside.example", "/m/auth/waiting-role", "/m/../login"):
            response = self.callback_failure(services.OAuthFailure("INVALID_STATE"), saved_next=saved_next)
            self.assert_destination(response, "/auth/wecom-error", reason="STATE_INVALID")

    def test_callback_missing_schema_preserves_only_session_bound_mobile_next(self):
        request = self.request(saved_next=self.next_path, state=self.state, code="unit-code", next="//outside.example")
        with patch("apps.wecom.selectors.schema_is_ready", return_value=False):
            response = views.oauth_callback(request)
        self.assert_destination(response, "/m/auth/wecom-error", reason="CONFIGURATION_ERROR", next=self.next_path)

    def test_desktop_callback_failure_keeps_existing_redirect(self):
        response = self.callback_failure(services.OAuthFailure("ACCOUNT_INACTIVE"), saved_next="/customers")
        self.assert_destination(response, "/auth/wecom-error", reason="ACCOUNT_INACTIVE")

    def test_invalid_state_is_rejected_before_upstream_or_account_access(self):
        request = self.request(saved_next=self.next_path)
        with patch("apps.wecom.services.consume_oauth_state", side_effect=services.OAuthFailure("INVALID_STATE")), \
             patch("apps.wecom.services.WeComClient") as upstream, \
             patch("apps.wecom.services.get_config") as config:
            with self.assertRaises(services.OAuthFailure):
                services.oauth_login(request, self.state, "unit-code")
        upstream.assert_not_called()
        config.assert_not_called()

    def test_success_and_waiting_role_preserve_existing_login_flow(self):
        for next_path, waiting, expected in ((self.next_path, False, self.next_path),
                                              (self.next_path, True, "/m/auth/waiting-role"),
                                              ("/customers", True, "/auth/waiting-role"),
                                              ("/customers", False, "/customers")):
            with self.subTest(next_path=next_path, waiting=waiting), ExitStack() as stack:
                request = self.request(saved_next=next_path)
                challenge = SimpleNamespace(state_digest=services._digest(self.state), config_etag="unit-etag", initiator_user_id=None)
                config = SimpleNamespace(_state=SimpleNamespace(adding=False), enabled=True, corp_id="unit-corp", pk=1)
                employee, user = SimpleNamespace(display_name="单元测试员工"), SimpleNamespace(pk=123)
                binding = SimpleNamespace(employee_id=456, user_id="unit-member", employee=SimpleNamespace(display_name="单元测试员工"))
                patches = {
                    "consume_oauth_state": {"return_value": challenge},
                    "get_config": {"return_value": config},
                    "configuration_complete": {"return_value": True},
                    "config_etag": {"return_value": "unit-etag"},
                    "transaction.atomic": {"side_effect": lambda: nullcontext()},
                    "_existing_binding": {"return_value": binding},
                    "_locked_employee_and_user": {"return_value": (employee, user)},
                    "_assert_employee_active": {}, "audit": {}, "django_login": {},
                    "waiting_for_role": {"return_value": waiting},
                }
                mocked = {name: stack.enter_context(patch("apps.wecom.services." + name, **options)) for name, options in patches.items()}
                stack.enter_context(patch("apps.core.login_records.record_successful_login"))
                stack.enter_context(patch("apps.wecom.services.WeComConfig.objects.select_for_update")).return_value.get.return_value = config
                session = stack.enter_context(patch("apps.wecom.services.Session.objects.select_for_update"))
                session.return_value.filter.return_value.first.return_value.get_decoded.return_value = {}
                upstream = stack.enter_context(patch("apps.wecom.services.WeComClient")).return_value
                upstream.get_identity.return_value = {"userid": "unit-member", "corpid": "unit-corp"}
                upstream.get_member.return_value = {"userid": "unit-member", "name": "单元测试员工", "status": 1}
                destination = services.oauth_login(request, self.state, "unit-code")
                if waiting and next_path.startswith("/m/"):
                    self.assertEqual(urlsplit(destination).path, expected)
                    self.assertEqual(parse_qs(urlsplit(destination).query), {"next": [next_path]})
                else:
                    self.assertEqual(destination, expected)
                mocked["django_login"].assert_called_once_with(request, user, backend="apps.core.auth.ErpModelBackend")
                mocked["_assert_employee_active"].assert_called_once_with(employee, user)
                self.assertEqual(request.session["wecom_qr_redirects"], {})
