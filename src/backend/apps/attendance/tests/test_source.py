from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.attendance.source import build_record_steps, calendar_day, normalize_record
from apps.wecom.client import WeComError


class SourceTests(SimpleTestCase):
    def test_scope_requires_explicit_root_not_optional_fields(self):
        from apps.attendance import services
        run = SimpleNamespace(scope={})
        for departments in ([], [2]):
            with self.assertRaises(WeComError):
                services._store_result(run, {"phase": "scope"}, {"allow_partys": {"partyid": departments}})
            self.assertEqual(run.scope, {})
        scope = {"allow_partys": {"partyid": [1]}}
        services._store_result(run, {"phase": "scope"}, scope)
        self.assertEqual(run.scope, scope)

    def test_overview_dates_require_actual_daily_or_raw_records(self):
        from apps.attendance.selectors import overview
        monthly = {"kind": "monthly", "user_id": "u1", "date": date(2026, 9, 1), "payload__department_name": ""}
        records = Mock()
        run = SimpleNamespace(records=records, finished_at=None, scanned_members=1)
        period = SimpleNamespace(active_run=run, current_run=None)
        with patch("apps.attendance.selectors.period_for", return_value=("corp", period)):
            records.values.return_value = [monthly]
            self.assertIsNone(overview("2026-09")["source_start"])
            self.assertIsNone(overview("2026-09")["source_end"])
            records.values.return_value = [monthly,
                {**monthly, "kind": "daily", "date": date(2026, 9, 16)},
                {**monthly, "kind": "raw", "date": date(2026, 9, 18)}]
            result = overview("2026-09")
            self.assertEqual(result["source_start"], date(2026, 9, 16))
            self.assertEqual(result["source_end"], date(2026, 9, 18))

    def test_31_day_raw_ranges_are_disjoint_and_bounded(self):
        steps = build_record_steps("2026-10", [f"u{i}" for i in range(21)])
        raw = [step for step in steps if step["kind"] == "raw"]
        self.assertEqual(len(raw), 4)
        self.assertEqual(raw[0]["endtime"] + 1, raw[1]["starttime"])
        self.assertLessEqual(raw[0]["endtime"] - raw[0]["starttime"], 30 * 86400)
        self.assertTrue(all(len(step["userids"]) <= 20 for step in steps))

    def test_raw_chunk_keeps_31st_midnight_and_month_last_second(self):
        from apps.attendance import services
        from apps.attendance.models import AttendanceMonth, AttendanceRecord, AttendanceSyncRun
        from apps.attendance.source import BEIJING
        step = [item for item in build_record_steps("2026-10", ["u1"]) if item["kind"] == "raw"][1]
        self.assertEqual(datetime.fromtimestamp(step["starttime"], BEIJING).isoformat(), "2026-10-31T00:00:00+08:00")
        self.assertEqual(datetime.fromtimestamp(step["endtime"], BEIJING).isoformat(), "2026-10-31T23:59:59+08:00")
        run = AttendanceSyncRun(period=AttendanceMonth(corp_id="corp", month="2026-10"), completed_steps=0)
        with patch.object(AttendanceRecord.objects, "bulk_create") as save:
            services._store_result(run, step, [{"userid": "u1", "checkin_time": stamp}
                                              for stamp in (step["starttime"], step["endtime"])])
            self.assertEqual(len(save.call_args.args[0]), 2)
            self.assertTrue(all(row.date == date(2026, 10, 31) for row in save.call_args.args[0]))
            save.reset_mock()
            for stamp in (step["starttime"] - 1, step["endtime"] + 1):
                with self.assertRaises(WeComError):
                    services._store_result(run, step, [{"userid": "u1", "checkin_time": stamp}])
            save.assert_not_called()

    def test_missing_is_not_zero_and_private_fields_are_not_copied(self):
        row = normalize_record("daily", {"base_info": {"acctid": "u1", "date": 1788192000},
            "summary_info": {}, "phone": "private", "location_title": "private"}, {"u1"}, "2026-09")
        self.assertIsNone(row["payload"]["checkin_count"])
        self.assertIsNone(row["payload"]["exceptions"])
        self.assertNotIn("phone", row["payload"])
        self.assertEqual(row["payload"]["department_name"], "")

    def test_boolean_count_and_unknown_user_are_rejected(self):
        for user_id, count in (("u1", True), ("outsider", 1)):
            with self.assertRaises(WeComError):
                normalize_record("daily", {"base_info": {"acctid": user_id, "date": 1788192000},
                    "summary_info": {"checkin_count": count}}, {"u1"}, "2026-09")

    def test_absence_fields_keep_units_zero_missing_and_only_whitelisted_data(self):
        source = {"base_info": {"acctid": "u1", "date": 1788192000},
            "sp_items": [{"type": 1, "count": 0, "duration": 43200, "time_type": 0,
                          "vacation_id": 2, "name": "年假", "private_reason": "不可保存"},
                         {"type": 999, "name": "来源新增项"}],
            "ot_info": {"ot_status": 2, "ot_duration": 3600, "exception_duration": [120],
                        "private_note": "不可保存"}}
        payload = normalize_record("daily", source, {"u1"}, "2026-09")["payload"]
        self.assertEqual(payload["sp_items"][0]["duration"], 43200)
        self.assertEqual(payload["sp_items"][0]["count"], 0)
        self.assertNotIn("private_reason", payload["sp_items"][0])
        self.assertEqual(payload["sp_items"][1]["type"], 999)
        self.assertIsNone(payload["sp_items"][1]["duration"])
        self.assertEqual(payload["ot_info"]["ot_duration"], 3600)
        self.assertIsNone(payload["ot_info"]["workday_over_as_money"])
        self.assertNotIn("private_note", payload["ot_info"])
        for extra, expected in (({}, None), ({"sp_items": []}, [])):
            value = normalize_record("monthly", {"base_info": {"acctid": "u1"}, **extra}, {"u1"}, "2026-09")["payload"]
            self.assertEqual(value["sp_items"], expected)
            self.assertIsNone(value["overwork_info"])

    def test_absence_fields_reject_malformed_values_without_inventing_zero(self):
        for extra in ({"sp_items": {}}, {"sp_items": [{"type": True}]},
                      {"sp_items": [{"type": 1, "duration": -1}]},
                      {"ot_info": {"ot_status": True}}, {"ot_info": {"exception_duration": [True]}}):
            with self.subTest(extra=extra), self.assertRaises(WeComError):
                normalize_record("daily", {"base_info": {"acctid": "u1", "date": 1788192000}, **extra}, {"u1"}, "2026-09")

    def test_calendar_preserves_multiple_exceptions_and_unknown(self):
        day = calendar_day(date(2026, 9, 1), [{"checkin_count": 2,
            "exceptions": [{"type": 1, "count": 1}, {"type": 2, "count": 1}]}], [], date(2026, 10, 1))
        self.assertEqual(day["states"], ["late", "early"])
        self.assertEqual(calendar_day(date(2026, 9, 1), [], [{"id": "raw"}], date(2026, 10, 1))["states"],
                         ["recorded", "unknown"])

    def test_calendar_never_calls_incomplete_or_multiple_reports_normal(self):
        for rows in ([{"checkin_count": 1, "exceptions": None}],
                     [{"checkin_count": 1, "exceptions": []}] * 2):
            self.assertNotIn("normal", calendar_day(date(2026, 9, 1), rows, [], date(2026, 10, 1))["states"])
        self.assertEqual(calendar_day(date(2026, 10, 20), [], [], date(2026, 10, 19))["states"], ["future"])

    def test_explicit_empty_exception_list_is_zero_but_missing_list_is_unknown(self):
        from apps.attendance.selectors import _exception_count
        self.assertEqual(_exception_count({"exceptions": []}, 1), 0)
        self.assertEqual(_exception_count({"exceptions": [{"type": 3, "count": 1}]}, 1), 0)
        self.assertIsNone(_exception_count({"exceptions": None}, 1))
        self.assertIsNone(_exception_count({"exceptions": [{"type": 1, "count": 1}] * 2}, 1))

    def test_missing_report_fields_do_not_erase_other_report_exceptions(self):
        result = calendar_day(date(2026, 9, 1), [
            {"checkin_count": 2, "exceptions": [{"type": 1, "count": 1}]},
            {"checkin_count": 1, "exceptions": None},
        ], [], date(2026, 10, 1))
        self.assertEqual(result["states"], ["late", "unknown"])
        self.assertEqual(result["exceptions"], [{"type": 1, "count": 1}])

    def test_roster_name_longer_than_storage_contract_fails_before_database(self):
        from types import SimpleNamespace
        from apps.attendance.services import _merge_members
        with self.assertRaises(WeComError):
            _merge_members(SimpleNamespace(roster={}), [{"userid": "u1", "name": "n" * 151}])
