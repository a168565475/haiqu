from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.schedule import rule_options


class ScheduleRuleTests(SimpleTestCase):
    def group(self, **extra):
        return {"groupid": 8, "groupname": "固定班", "grouptype": 1,
                "checkindate": [{"workdays": [1, 2, 3, 4, 5],
                                 "checkintime": [{"work_sec": 28800, "off_work_sec": 61200}]}], **extra}

    def options(self, group):
        return rule_options([group], date(2026, 9, 1), "test-corp")["rules"][0]

    def test_fixed_week_and_special_dates_preserve_explicit_rest(self):
        stamp = lambda day: int(datetime(2026, 9, day, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        result = self.options(self.group(
            spe_workdays=[{"timestamp": stamp(6), "checkintime": [{"work_sec": 32400, "off_work_sec": 64800}]}],
            spe_offdays=[{"timestamp": stamp(7)}],
            range={"userid": ["must-not-leak"]}, loc_infos=[{"lat": 1}],
        ))
        self.assertTrue(result["can_import"])
        self.assertEqual(len(result["days"]), 30)
        days = {row["date"]: row for row in result["days"]}
        self.assertEqual(days["2026-09-05"]["kind"], "REST")
        self.assertEqual(days["2026-09-06"]["periods"], [{"start_sec": 32400, "end_sec": 64800}])
        self.assertEqual(days["2026-09-07"]["kind"], "REST")
        self.assertNotIn("must-not-leak", str(result))
        self.assertNotIn("loc_infos", result)

    def test_sunday_zero_is_workday_when_explicit(self):
        group = self.group(checkindate=[{"workdays": [0], "checkintime": [{"work_sec": 28800, "off_work_sec": 61200}]}])
        days = self.options(group)["days"]
        self.assertEqual(days[5]["kind"], "WORK")
        self.assertEqual(days[0]["kind"], "REST")

    def test_biweekly_uses_official_monday_anchor(self):
        group = self.group(checkindate=[{"biweekly": {"enable_weekday_recurrence": True,
            "odd_workdays": [1], "even_workdays": [2]},
            "checkintime": [{"work_sec": 28800, "off_work_sec": 61200}]}])
        days = self.options(group)["days"]
        for row in days:
            day = date.fromisoformat(row["date"])
            week = (day - date(2024, 1, 1)).days // 7 + 1
            weekday = 1 if week % 2 else 2
            self.assertEqual(row["kind"] == "WORK", day.isoweekday() == weekday)

    def test_ambiguous_schedule_free_and_missing_weekdays_are_not_invented(self):
        for group in [self.group(grouptype=2), self.group(grouptype=3),
                      self.group(checkindate=[{"checkintime": [{"work_sec": 1, "off_work_sec": 2}]}])]:
            with self.subTest(group=group):
                option = self.options(group)
                self.assertFalse(option["can_import"])
                self.assertEqual(option["days"], [])
                self.assertTrue(option["reason"])

    def test_multiple_periods_preserved_without_lunch_deduction(self):
        group = self.group(checkindate=[{"workdays": [1, 2, 3, 4, 5], "checkintime": [
            {"work_sec": 28800, "off_work_sec": 43200}, {"work_sec": 46800, "off_work_sec": 61200}]}])
        option = self.options(group)
        self.assertEqual(len(option["days"][0]["periods"]), 2)
        self.assertNotIn("lunch", str(option))

    def test_holidays_warn_and_do_not_claim_historical_rules(self):
        option = self.options(self.group(sync_holidays=True))
        self.assertTrue(any("节假日" in value for value in option["warnings"]))
        self.assertTrue(any("当前" in value for value in option["warnings"]))

    def test_overnight_and_conflicting_special_day_require_manual_setting(self):
        group = self.group(checkindate=[{"workdays": [1], "checkintime": [{"work_sec": 72000, "off_work_sec": 28800}]}])
        self.assertFalse(self.options(group)["can_import"])
