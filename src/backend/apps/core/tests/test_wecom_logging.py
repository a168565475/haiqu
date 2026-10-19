import logging

from django.test import SimpleTestCase


class WeComLogFilterTests(SimpleTestCase):
    def test_callback_parameters_are_removed_from_development_access_log(self):
        from apps.core.logging import WeComAccessLogFilter

        record = logging.LogRecord("django.server", logging.INFO, "", 0, '"%s" %s %s',
                                   ("GET /api/auth/wecom/callback/?code=sample-code&state=sample-state HTTP/1.1", "302", "0"), None)
        self.assertTrue(WeComAccessLogFilter().filter(record))
        self.assertEqual(record.getMessage(), '"GET /api/auth/wecom/callback/ HTTP/1.1" 302 0')

    def test_other_access_logs_are_preserved(self):
        from apps.core.logging import WeComAccessLogFilter

        record = logging.LogRecord("django.server", logging.INFO, "", 0, '"%s" %s %s',
                                   ("GET /api/v1/customers/?page=2 HTTP/1.1", "200", "10"), None)
        before = record.getMessage()
        self.assertTrue(WeComAccessLogFilter().filter(record))
        self.assertEqual(record.getMessage(), before)
