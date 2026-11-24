import copy
import unittest

from apps.ai_production_import.client import _prepare_model_source
from apps.ai_production_import.date_fields import cell_date, normalize_date_fields


def source(serial="46305", **kwargs):
    cell = {"source_id": "date-cell", "ref": "K3", "type": "n", "text": serial,
            "num_format_id": "14", **kwargs}
    return {"source_index": {"date-cell": {}}, "sheets": [{"cells": [cell]}], "date1904": "0"}


def field(value, status="EXTRACTED"):
    return {"value": value, "status": status, "note": "原有说明", "source_ids": ["date-cell"]}


class DateFieldsTests(unittest.TestCase):
    def test_excel_serial_with_date_evidence_is_normalized_and_original_preserved(self):
        result = {"task": {"delivery_date": field(46305)}, "issues": []}
        original = copy.deepcopy(result)
        actual = normalize_date_fields(result, source())
        self.assertEqual(actual["task"]["delivery_date"]["value"], "2026-10-10")
        self.assertIn("46305", actual["task"]["delivery_date"]["note"])
        self.assertEqual(result, original)

    def test_model_input_keeps_serial_and_adds_normalized_date(self):
        payload, _ = _prepare_model_source(source(num_format='yyyy"年"m"月"d"日";@'))
        cell = payload["sheets"][0]["cells"][0]
        self.assertEqual(cell["text"], "46305")
        self.assertEqual(cell["normalized_date"], "2026-10-10")

    def test_chinese_slash_and_iso_dates(self):
        for value in ("2026年10月10日", "2026/10/10", "2026-10-10", "2026.10.10"):
            with self.subTest(value=value):
                actual = normalize_date_fields({"task": {"delivery_date": field(value)}}, source())
                self.assertEqual(actual["task"]["delivery_date"]["value"], "2026-10-10")

    def test_invalid_or_incomplete_dates_are_visible_issues_not_accepted(self):
        for value in ("2026-09-31", "11月10号", "2026-10-10或2026-11-10", 17004, True):
            with self.subTest(value=value):
                actual = normalize_date_fields({"task": {"delivery_date": field(value)}}, source())
                self.assertEqual(actual["task"]["delivery_date"]["status"], "UNREADABLE")
                self.assertIsNone(actual["task"]["delivery_date"]["value"])
                self.assertEqual(actual["issues"][0]["kind"], "DATE_FORMAT_INVALID")

    def test_numeric_value_without_date_format_is_not_interpreted_as_date(self):
        actual = normalize_date_fields({"task": {"delivery_date": field(46305)}}, source(num_format_id="0"))
        self.assertEqual(actual["task"]["delivery_date"]["status"], "UNREADABLE")

    def test_conflicts_and_missing_are_not_silently_resolved(self):
        for status in ("CONFLICT", "MISSING", "UNREADABLE"):
            result = {"task": {"delivery_date": field(None, status)}}
            self.assertEqual(normalize_date_fields(result, source()), result)

    def test_batches_and_additional_tasks_keep_their_own_dates(self):
        result = {"task": {"delivery_date": field("2026/10/10"), "delivery_batches": [
            {"delivery_date": field("2026年10月10日")}, {"delivery_date": field("2026年11月10日")}]},
            "additional_tasks": [{"task": {"delivery_date": field("2027/1/10")}}]}
        actual = normalize_date_fields(result, source())
        self.assertEqual(actual["task"]["delivery_date"]["value"], "2026-10-10")
        self.assertEqual(actual["task"]["delivery_batches"][1]["delivery_date"]["value"], "2026-11-10")
        self.assertEqual(actual["additional_tasks"][0]["task"]["delivery_date"]["value"], "2027-01-10")

    def test_workbook_epoch_and_excel_nonexistent_leap_day(self):
        workbook = source("44843")
        workbook["date1904"] = "1"
        self.assertEqual(cell_date(workbook["sheets"][0]["cells"][0], workbook), "2026-10-10")
        workbook = source("60")
        self.assertIsNone(cell_date(workbook["sheets"][0]["cells"][0], workbook))

    def test_date_formula_cache_is_used(self):
        workbook = source("", formula="DATE(2026,10,10)", cache="46305")
        self.assertEqual(cell_date(workbook["sheets"][0]["cells"][0], workbook), "2026-10-10")

    def test_time_and_duration_formats_do_not_become_calendar_dates(self):
        for number_format in ("hh:mm", "[h]:mm:ss"):
            with self.subTest(number_format=number_format):
                workbook = source("2", num_format=number_format)
                self.assertIsNone(cell_date(workbook["sheets"][0]["cells"][0], workbook))
                output = normalize_date_fields({"task": {"delivery_date": field(2)}}, workbook)
                self.assertEqual(output["task"]["delivery_date"]["status"], "UNREADABLE")

    def test_combined_calendar_and_time_format_retains_calendar_date(self):
        workbook = source("46305.5", num_format="yyyy-mm-dd hh:mm")
        self.assertEqual(cell_date(workbook["sheets"][0]["cells"][0], workbook), "2026-10-10")
