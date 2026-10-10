from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.debug_timing import ProductionReadTimingMiddleware


@override_settings(DEBUG=True)
class ProductionReadTimingTests(TestCase):
    def request(self, path="/api/v1/production-tasks/", method="get", superuser=True):
        request = getattr(RequestFactory(), method)(path)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=superuser)
        return request

    def test_developer_header_counts_queries_and_preserves_existing_metric(self):
        def respond(request):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return HttpResponse(headers={"Server-Timing": "other;dur=1"})
        response = ProductionReadTimingMiddleware(respond)(self.request())
        header = response["Server-Timing"]
        self.assertTrue(header.startswith("other;dur=1, app;dur="))
        self.assertIn("db;dur=", header)
        self.assertIn('queries;desc="1"', header)
        self.assertNotIn("SELECT", header)

    @override_settings(DEBUG=False)
    def test_production_does_not_wrap_database_execution(self):
        with patch.object(connection, "execute_wrapper") as wrapper:
            response = ProductionReadTimingMiddleware(lambda request: HttpResponse())(self.request())
        wrapper.assert_not_called()
        self.assertNotIn("Server-Timing", response)

    def test_other_paths_and_writes_are_not_instrumented(self):
        for request in [self.request("/api/v1/customers/"), self.request(method="post")]:
            with patch.object(connection, "execute_wrapper") as wrapper:
                response = ProductionReadTimingMiddleware(lambda request: HttpResponse())(request)
            wrapper.assert_not_called()
            self.assertNotIn("Server-Timing", response)

    def test_non_admin_and_anonymous_do_not_receive_header(self):
        request = self.request(superuser=False)
        middleware = ProductionReadTimingMiddleware(lambda request: HttpResponse())
        self.assertNotIn("Server-Timing", middleware(request))
        request.user = SimpleNamespace(is_authenticated=False, is_superuser=False)
        self.assertNotIn("Server-Timing", middleware(request))

    def test_application_exceptions_propagate(self):
        def respond(request):
            raise ValueError("test failure")
        with self.assertRaisesMessage(ValueError, "test failure"):
            ProductionReadTimingMiddleware(respond)(self.request())

    def test_quality_reads_receive_timing_but_confirmation_does_not(self):
        middleware = ProductionReadTimingMiddleware(lambda request: HttpResponse())
        base = '/api/v1/material-inventory/quality-batches/'
        detail = base + '30e90576-ff14-45ad-b94e-87c5a915f409/'
        for path in [base, detail]:
            self.assertIn('Server-Timing', middleware(self.request(path)))
        self.assertNotIn('Server-Timing', middleware(self.request(detail + 'confirm/')))
        self.assertNotIn('Server-Timing', middleware(self.request(detail, method='post')))

    def test_bom_read_paths_receive_timing_but_editor_actions_do_not(self):
        middleware = ProductionReadTimingMiddleware(lambda request: HttpResponse())
        for path in ['/api/v1/boms/', '/api/v1/boms/stats/', '/api/v1/boms/options/', '/api/v1/boms/30e90576-ff14-45ad-b94e-87c5a915f409/']:
            self.assertIn('Server-Timing', middleware(self.request(path)))
        self.assertNotIn('Server-Timing', middleware(self.request('/api/v1/boms/hardware-materials/')))

    def test_purchase_read_paths_receive_timing_but_business_actions_do_not(self):
        middleware = ProductionReadTimingMiddleware(lambda request: HttpResponse())
        for suffix in ['', 'stats/', 'options/', 'filter-options/', '30e90576-ff14-45ad-b94e-87c5a915f409/']:
            self.assertIn('Server-Timing', middleware(self.request('/api/v1/purchase-orders/' + suffix)))
        self.assertNotIn('Server-Timing', middleware(self.request('/api/v1/purchase-orders/30e90576-ff14-45ad-b94e-87c5a915f409/confirm/')))
