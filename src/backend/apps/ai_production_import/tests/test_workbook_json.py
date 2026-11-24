import io
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from apps.ai_production_import.errors import AiProductionImportError
from apps.ai_production_import.workbook_json import _scan_bytes, build_controlled_json


class Upload:
    def __init__(self, name, data):
        self.name = name
        self._stream = io.BytesIO(data)

    def read(self):
        return self._stream.read()


class WorkbookJsonTests(unittest.TestCase):
    def test_rejects_non_spreadsheet_extension(self):
        with self.assertRaises(AiProductionImportError) as context:
            build_controlled_json(Upload("payload.txt", b"abc"))
        self.assertEqual(context.exception.code, "UNSUPPORTED_FILE")

    def test_rejects_empty_upload(self):
        with self.assertRaises(AiProductionImportError) as context:
            build_controlled_json(Upload("empty.xlsx", b""))
        self.assertEqual(context.exception.code, "INPUT_SIZE_LIMIT")


class ScanPolicyTests(unittest.TestCase):
    def _scan_with(self, enabled, error_name=None):
        security = ModuleType("apps.imports.security")
        security.InfectedFile = type("InfectedFile", (Exception,), {})
        security.ScannerUnavailable = type("ScannerUnavailable", (Exception,), {})
        error = getattr(security, error_name)() if error_name else None
        security.scan_upload = Mock(side_effect=error)
        settings = SimpleNamespace(FILE_VIRUS_SCAN_ENABLED=enabled)
        with patch.dict(sys.modules, {"apps.imports.security": security}), patch("django.conf.settings", settings):
            _scan_bytes(b"test", ".xlsx")
        return security.scan_upload

    def test_disabled_scanner_blocks_ai_import(self):
        with self.assertRaises(AiProductionImportError) as context:
            self._scan_with(False)
        self.assertEqual(context.exception.code, "SCAN_UNAVAILABLE")

    def test_infected_file_blocks_ai_import(self):
        with self.assertRaises(AiProductionImportError) as context:
            self._scan_with(True, "InfectedFile")
        self.assertEqual(context.exception.code, "SCAN_INFECTED")

    def test_scanner_unavailable_blocks_ai_import(self):
        with self.assertRaises(AiProductionImportError) as context:
            self._scan_with(True, "ScannerUnavailable")
        self.assertEqual(context.exception.code, "SCAN_UNAVAILABLE")
