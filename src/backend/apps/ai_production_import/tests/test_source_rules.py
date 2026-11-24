import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.ai_production_import.errors import AiProductionImportError
from apps.ai_production_import.source_rules import confirmed_source_rules


class SourceRuleTests(SimpleTestCase):
    def rules(self, entries, source):
        with patch("apps.ai_production_import.source_rules.Path") as path:
            file = path.return_value.__truediv__.return_value
            file.is_file.return_value = True
            file.stat.return_value = SimpleNamespace(st_size=100)
            file.read_text.return_value = json.dumps(entries)
            return confirmed_source_rules(source)

    def test_exact_file_version_and_task_body_identity_are_both_required(self):
        rule = {"id": "example", "source_sha256": "a" * 64, "task_number": "HT100"}
        source = {"source_sha256": "a" * 64, "original_name": "HT100.xlsx",
                  "sheets": [{"cells": [{"text": "任务 HT100"}]}]}
        self.assertEqual(self.rules([rule], source), [rule])
        for text in ("HT1000", "HT100-2", "表中没有该任务"):
            source["sheets"][0]["cells"][0]["text"] = text
            self.assertEqual(self.rules([rule], source), [])
        source["sheets"][0]["cells"][0]["text"] = "HT100"
        source["source_sha256"] = "b" * 64
        self.assertEqual(self.rules([rule], source), [])

    def test_missing_local_rule_file_is_allowed_but_invalid_file_is_reported(self):
        with patch("apps.ai_production_import.source_rules.Path") as path:
            file = path.return_value.__truediv__.return_value
            file.is_file.return_value = False
            self.assertEqual(confirmed_source_rules({}), [])
        with self.assertRaises(AiProductionImportError) as raised:
            self.rules({"wrong": "shape"}, {})
        self.assertEqual(raised.exception.code, "AI_SOURCE_RULES_INVALID")
