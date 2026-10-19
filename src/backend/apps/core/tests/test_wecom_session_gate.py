from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.core.middleware import ErpSessionAccessMiddleware


class WeComSessionGateTests(SimpleTestCase):
    def request(self, path, *, authenticated=True):
        request = RequestFactory().get(path)
        request.user = SimpleNamespace(is_authenticated=authenticated)
        request.request_id = "test-request"
        return request

    def test_waiting_account_keeps_session_but_cannot_read_business_or_schema(self):
        middleware = ErpSessionAccessMiddleware(lambda request: HttpResponse("business"))
        for path in ("/api/v1/countries/", "/api/v1/customers/", "/api/schema/", "/admin/"):
            with self.subTest(path=path), patch("apps.core.middleware.can_access_erp", return_value=True), patch(
                "apps.core.middleware.waiting_for_role", create=True, return_value=True
            ), patch("apps.core.middleware.django_logout") as logout:
                response = middleware(self.request(path))
                self.assertEqual(response.status_code, 403)
                self.assertIn(b"WECOM_ROLE_REQUIRED", response.content)
                logout.assert_not_called()

    def test_waiting_account_can_query_session_logout_and_restart_wecom(self):
        middleware = ErpSessionAccessMiddleware(lambda request: HttpResponse("allowed"))
        for path in ("/api/auth/me/", "/api/auth/logout/", "/api/auth/login/",
                     "/api/auth/wecom/start/", "/api/auth/wecom/callback/", "/api/health/"):
            with self.subTest(path=path), patch("apps.core.middleware.can_access_erp", return_value=True), patch(
                "apps.core.middleware.waiting_for_role", create=True, return_value=True
            ), patch("apps.core.middleware.django_logout") as logout:
                self.assertEqual(middleware(self.request(path)).status_code, 200)
                logout.assert_not_called()

    def test_existing_password_account_preserves_existing_business_behavior(self):
        middleware = ErpSessionAccessMiddleware(lambda request: HttpResponse("allowed"))
        with patch("apps.core.middleware.can_access_erp", return_value=True), patch(
            "apps.core.middleware.waiting_for_role", create=True, return_value=False
        ):
            self.assertEqual(middleware(self.request("/api/v1/countries/")).status_code, 200)

    def test_inactive_employee_still_uses_existing_logout_rule(self):
        middleware = ErpSessionAccessMiddleware(lambda request: HttpResponse("allowed"))
        with patch("apps.core.middleware.can_access_erp", return_value=False), patch(
            "apps.core.middleware.waiting_for_role", create=True
        ) as waiting, patch("apps.core.middleware.django_logout") as logout:
            request = self.request("/api/auth/me/")
            middleware(request)
            logout.assert_called_once_with(request)
            waiting.assert_not_called()

    def test_anonymous_request_does_not_query_wecom_tables(self):
        middleware = ErpSessionAccessMiddleware(lambda request: HttpResponse("allowed"))
        with patch("apps.core.middleware.waiting_for_role", create=True) as waiting:
            middleware(self.request("/api/v1/countries/", authenticated=False))
            waiting.assert_not_called()
