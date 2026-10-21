from datetime import date
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceSchedule
from apps.attendance.schedule import empty_days
from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComConfig


URL = "/api/v1/attendance/schedule/?month=2026-09"
RULES_URL = "/api/v1/attendance/rules/?month=2026-09"


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], MODULE_ACCESS_ENABLED=False)
class ScheduleAPITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("schedule-admin", "", "test-only")
        self.employee = Employee.objects.create(user=self.user, employee_code="ATT-SCHED", display_name="测试管理员")
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-only"))
        self.client = APIClient()
        self.client.force_login(self.user)

    def payload(self):
        days = empty_days(date(2026, 9, 1))
        days[0] = {"date": "2026-09-01", "kind": "WORK", "periods": [{"start_sec": 28800, "end_sec": 61200}]}
        days[1] = {"date": "2026-09-02", "kind": "REST", "periods": []}
        return {"days": days, "import_token": None}

    def test_attendance_permissions_are_registered_as_module_with_chinese_labels(self):
        from apps.access_control.catalog import MODULE_NAMES, PERMISSION_CODES, module_for, permission_map, scopes_for, validate_grants
        from apps.access_control.presentation import presentation
        names = {"attendance.view_attendance": "查看考勤", "attendance.sync_attendance": "同步考勤",
                 "attendance.manage_schedule": "设置月度上班时间"}
        permissions = permission_map()
        self.assertEqual(MODULE_NAMES["attendance"], "考勤管理")
        for code, name in names.items():
            with self.subTest(code=code):
                self.assertIn(code, PERMISSION_CODES)
                self.assertIn(code, permissions)
                self.assertEqual(module_for(code), "attendance")
                self.assertEqual(scopes_for(code), ("MODULE",))
                self.assertEqual(presentation(code, permissions[code], "attendance")["label"], f"企业微信考勤 · {name}")
                self.assertEqual(validate_grants([{"permission": code, "scope": "MODULE"}]), [(permissions[code], "MODULE")])

    def test_get_does_not_create_and_writes_require_current_etag(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["data"]["configured"])
        self.assertEqual(AttendanceSchedule.objects.count(), 0)
        first_etag = response["ETag"]
        self.assertEqual(self.client.put(URL, self.payload(), format="json").status_code, 428)
        response = self.client.put(URL, self.payload(), format="json", HTTP_IF_MATCH=first_etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response["ETag"], first_etag)
        self.assertEqual(AttendanceSchedule.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_type="ATTENDANCE_SCHEDULE").count(), 1)
        self.assertEqual(self.client.put(URL, self.payload(), format="json", HTTP_IF_MATCH=first_etag).status_code, 412)

    def test_view_and_sync_permissions_do_not_allow_schedule_changes_or_rule_reads(self):
        viewer = get_user_model().objects.create_user("schedule-viewer")
        Employee.objects.create(user=viewer, employee_code="ATT-VIEW", display_name="测试查看者")
        viewer.user_permissions.add(*Permission.objects.filter(content_type__app_label="attendance", codename__in=["view_attendance", "sync_attendance"]))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.get(RULES_URL).status_code, 403)
        self.assertEqual(self.client.put(URL, self.payload(), format="json").status_code, 403)

    def test_csrf_is_enforced(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.put(URL, self.payload(), format="json").status_code, 403)

    def test_wrong_month_duplicates_overlap_and_extra_fields_are_rejected(self):
        etag = self.client.get(URL)["ETag"]
        invalid = []
        payload = self.payload(); payload["days"][0]["date"] = "2026-10-01"; invalid.append(payload)
        payload = self.payload(); payload["days"][0] = payload["days"][1]; invalid.append(payload)
        payload = self.payload(); payload["days"][0]["periods"].append({"start_sec": 32400, "end_sec": 63000}); invalid.append(payload)
        payload = self.payload(); payload["days"][1]["periods"] = [{"start_sec": 1, "end_sec": 2}]; invalid.append(payload)
        payload = self.payload(); payload["lunch"] = "not-supported"; invalid.append(payload)
        payload = self.payload(); payload["days"][0]["employee_id"] = "not-supported"; invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.put(URL, payload, format="json", HTTP_IF_MATCH=etag).status_code, 400)
        self.assertFalse(AttendanceSchedule.objects.exists())

    @patch("apps.attendance.schedule_views.AttendanceClient")
    def test_rule_import_is_a_draft_and_source_cannot_be_forged_or_reused_for_other_month(self, client):
        client.return_value.get_rules.return_value = [{"groupid": 1, "groupname": "来源规则", "grouptype": 1,
            "checkindate": [{"workdays": [1, 2, 3, 4, 5], "checkintime": [{"work_sec": 28800, "off_work_sec": 61200}]}],
            "range": {"userid": ["private-user"]}, "loc_infos": [{"lat": 100}]}]
        response = self.client.get(RULES_URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("private-user", str(response.data))
        self.assertFalse(AttendanceSchedule.objects.exists())
        option = response.data["data"]["rules"][0]
        etag = self.client.get(URL)["ETag"]
        payload = {"days": option["days"], "import_token": option["import_token"]}
        bad = {**payload, "import_token": payload["import_token"] + "tampered"}
        self.assertEqual(self.client.put(URL, bad, format="json", HTTP_IF_MATCH=etag).status_code, 400)
        self.assertEqual(self.client.put(URL, payload, format="json", HTTP_IF_MATCH=etag).status_code, 200)
        other = "/api/v1/attendance/schedule/?month=2026-08"
        from apps.attendance.schedule import empty_days
        payload["days"] = empty_days(date(2026, 8, 1))
        self.assertEqual(self.client.put(other, payload, format="json", HTTP_IF_MATCH=self.client.get(other)["ETag"]).status_code, 400)
