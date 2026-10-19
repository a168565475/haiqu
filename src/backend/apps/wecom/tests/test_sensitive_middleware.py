from unittest.mock import patch

from django.db import OperationalError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.wecom.middleware import WeComOAuthSensitiveMiddleware, take_callback_parameters


@override_settings(DEBUG=True)
class WeComSensitiveMiddlewareTests(SimpleTestCase):
    def assert_private_parameters_absent(self, response):
        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertNotIn("PRIVATE_CALLBACK_STATE_702", body)
        self.assertNotIn("PRIVATE_CALLBACK_CODE_702", body)
        self.assertFalse(hasattr(response.wsgi_request, "_wecom_oauth_parameters"))

    def callback(self):
        client = APIClient()
        client.raise_request_exception = False
        return client.get("/api/auth/wecom/callback/", {
            "state": "PRIVATE_CALLBACK_STATE_702", "code": "PRIVATE_CALLBACK_CODE_702",
        })

    @patch("apps.wecom.selectors.schema_is_ready", side_effect=OperationalError("migration query failed"))
    def test_schema_database_exception_does_not_expose_oauth_parameters(self, readiness):
        self.assert_private_parameters_absent(self.callback())
        readiness.assert_called_once()

    @patch("django.contrib.auth.middleware.get_user", side_effect=OperationalError("identity query failed"))
    def test_earlier_session_identity_exception_does_not_expose_oauth_parameters(self, identity):
        self.assert_private_parameters_absent(self.callback())
        identity.assert_called()

    def test_middleware_retains_parameters_only_until_view_consumes_them(self):
        request = RequestFactory().get("/api/auth/wecom/callback/", {"state": "original-state", "code": "original-code"})
        observed = []

        def downstream(request):
            self.assertEqual(request.GET.dict(), {})
            self.assertEqual(request.META["QUERY_STRING"], "")
            observed.append(take_callback_parameters(request))
            return HttpResponse()

        WeComOAuthSensitiveMiddleware(downstream)(request)
        self.assertEqual(observed, [("original-state", "original-code")])
        self.assertFalse(hasattr(request, "_wecom_oauth_parameters"))

    def test_downstream_exception_propagates_and_private_storage_is_cleared(self):
        request = RequestFactory().get("/api/auth/wecom/callback/", {"state": "original-state", "code": "original-code"})

        def downstream(request):
            raise OperationalError("identity query failed")

        with self.assertRaisesMessage(OperationalError, "identity query failed"):
            WeComOAuthSensitiveMiddleware(downstream)(request)
        self.assertFalse(hasattr(request, "_wecom_oauth_parameters"))
