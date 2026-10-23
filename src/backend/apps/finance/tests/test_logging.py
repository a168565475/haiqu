import logging
from django.test import SimpleTestCase
from apps.finance.logging import FinanceAccessLogFilter


class FinanceLogTests(SimpleTestCase):
    def test_account_search_redacted_without_touching_other_paths(self):
        record = logging.LogRecord("django.server", logging.INFO, "", 0, '"%s" %s',
                                   ("GET /api/v1/finance/accounts/?q=0000000000000000101&page=1 HTTP/1.1", 200), None)
        self.assertTrue(FinanceAccessLogFilter().filter(record))
        self.assertEqual(record.getMessage(), '"GET /api/v1/finance/accounts/ HTTP/1.1" 200')
        other = logging.LogRecord("django.server", logging.INFO, "", 0, "GET /api/health/?check=1", (), None)
        FinanceAccessLogFilter().filter(other)
        self.assertEqual(other.getMessage(), "GET /api/health/?check=1")
