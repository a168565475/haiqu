import uuid
from datetime import date, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APIRequestFactory

from apps.attendance import selectors, services
from apps.attendance.models import AttendanceMonth, AttendanceRecord, AttendanceSyncRun
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from apps.wecom.client import WeComError
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], MODULE_ACCESS_ENABLED=False)
class AttendanceSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("attendance_admin", "", "test-password")
        self.employee = Employee.objects.create(user=self.user, employee_code="AT_ADMIN", display_name="管理员")
        self.config = WeComConfig.objects.create(corp_id="ww-test", enabled=True, secret_ciphertext=encrypt_secret("test-only"))
        self.client = APIClient()
        self.client.force_login(self.user)
        self.upstream_patch = patch("apps.attendance.services.AttendanceClient")
        self.upstream = self.upstream_patch.start().return_value
        self.addCleanup(self.upstream_patch.stop)
        self.upstream.get_scope.return_value = {"allow_partys": {"partyid": [1]},
            "allow_userinfos": {"user": []}, "allow_tags": {"tagid": []}}
        self.upstream.get_departments.return_value = [{"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}]
        self.upstream.get_department_members.side_effect = lambda department: (
            [{"userid": "Unbound.One", "name": "未绑定成员", "department": [1]}] if department == 1 else
            [{"userid": "Bound.Two", "name": "已绑定成员", "department": [2]}])
        self.upstream.get_records.side_effect = self.source_rows

    @staticmethod
    def source_rows(kind, start, end, users):
        if kind == "raw":
            return [{"userid": "Unbound.One", "checkin_time": start + 3600,
                     "checkin_type": "上班打卡", "exception_type": "", "groupname": "来源规则",
                     "location_title": "不能保存", "photo": "不能保存"}]
        base = {"acctid": "Unbound.One", "date": 1788192000, "name": "来源姓名", "departs_name": "历史部门",
                "rule_info": {"groupname": "来源规则", "schedulename": "来源班次"}}
        summary = {"checkin_count": 0, "work_days": 22, "standard_work_sec": 28800, "regular_work_sec": 0}
        return [{"base_info": base, "summary_info": summary, "exception_infos": [{"exception": 3, "count": 1}]}]

    def start(self, key=None, month="2026-09"):
        response = self.client.post("/api/v1/attendance/sync-runs/", {"month": month,
            "idempotency_key": str(key or uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def step(self, run, expected=200):
        response = self.client.post(f"/api/v1/attendance/sync-runs/{run['id']}/step/", {},
                                    format="json", HTTP_IF_MATCH=run["etag"])
        self.assertEqual(response.status_code, expected, response.data)
        return response.data.get("data")

    def finish(self, run):
        for _ in range(20):
            if run["status"] in {"SUCCESS", "FAILED", "INVALIDATED"}:
                break
            run = self.step(run)
        self.assertEqual(run["status"], "SUCCESS", run)
        return run

    def request(self, run):
        request = APIRequestFactory().post("/", {}, HTTP_IF_MATCH=etag_for_instance(run))
        request.user = get_user_model().objects.get(pk=self.user.pk)
        return request

    def test_snapshot_includes_unbound_members_and_preserves_missing_vs_zero(self):
        WeComBinding.objects.create(corp_id="ww-test", user_id="Bound.Two", member_name="绑定来源",
                                   employee=self.employee, source="MANUAL")
        completed = self.finish(self.start())
        self.assertEqual(completed["scanned_members"], 2)
        rows = self.client.get("/api/v1/attendance/records/monthly/", {"month": "2026-09"}).data["data"]
        self.assertEqual(len(rows), 2)
        by_user = {row["user_id"]: row for row in rows}
        self.assertEqual(by_user["unbound.one"]["department_name"], "历史部门")
        self.assertIsNone(by_user["unbound.one"]["employee_id"])
        self.assertEqual(by_user["bound.two"]["employee_id"], str(self.employee.pk))
        self.assertEqual(by_user["bound.two"]["record_status"], "NOT_RETURNED")
        self.assertIsNone(by_user["bound.two"]["work_days"])
        daily = self.client.get("/api/v1/attendance/records/daily/", {"month": "2026-09"}).data["data"]
        self.assertEqual(daily[0]["checkin_count"], 0)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertFalse(any("location_title" in record.payload for record in AttendanceRecord.objects.all()))

    def test_failed_replacement_preserves_previous_snapshot_and_idempotency(self):
        old = self.finish(self.start())
        new = self.start()
        self.assertNotEqual(new["id"], old["id"])
        self.upstream.get_scope.side_effect = WeComError("UPSTREAM_UNAVAILABLE", "secret URL must not appear")
        new = self.step(new)
        self.assertEqual(new["status"], "FAILED")
        self.assertNotIn("secret", new["error_message"])
        self.assertEqual(str(AttendanceMonth.objects.get().active_run_id), old["id"])
        self.assertEqual(self.start()["id"], new["id"])

    def test_repeated_success_does_not_duplicate_visible_records(self):
        first = self.finish(self.start())
        repeated = self.step(first)
        self.assertEqual(repeated["id"], first["id"])
        self.finish(self.start())
        self.assertEqual(selectors.overview("2026-09")["raw_count"], 1)
        self.assertEqual(AttendanceRecord.objects.filter(kind="raw").count(), 2)

    def test_idempotency_key_cannot_move_to_other_month(self):
        key = uuid.uuid4()
        first = self.start(key)
        self.assertEqual(self.start(key)["id"], first["id"])
        response = self.client.post("/api/v1/attendance/sync-runs/",
            {"month": "2026-08", "idempotency_key": str(key)}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_if_match_required_and_stale_rejected(self):
        run = self.start()
        url = f"/api/v1/attendance/sync-runs/{run['id']}/step/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 428)
        newer = self.step(run)
        self.step(run, 412)
        self.assertEqual(newer["completed_steps"], 1)

    def test_scope_without_root_never_syncs_partial_enterprise(self):
        self.upstream.get_scope.return_value = {"allow_partys": {"partyid": [2]}}
        run = self.step(self.start())
        self.assertEqual(run["error_code"], "SCOPE_INCOMPLETE")
        self.assertEqual(run["completed_steps"], 0)
        self.upstream.get_departments.assert_not_called()

    def test_explicit_root_scope_works_without_optional_users_and_tags(self):
        self.upstream.get_scope.return_value = {"allow_partys": {"partyid": [1]}}
        completed = self.finish(self.start())
        self.assertEqual(AttendanceSyncRun.objects.get(pk=completed["id"]).scope, self.upstream.get_scope.return_value)
        self.assertEqual(completed["scanned_members"], 2)

    def test_configuration_disabled_during_call_invalidates_without_writing(self):
        run = self.start()
        def disable():
            self.config.enabled = False
            self.config.save()
            return {"allow_partys": {"partyid": [1]}, "allow_userinfos": {"user": []}, "allow_tags": {"tagid": []}}
        self.upstream.get_scope.side_effect = disable
        result = self.step(run)
        self.assertEqual(result["status"], "INVALIDATED")
        self.assertEqual(result["completed_steps"], 0)
        self.assertIsNone(AttendanceMonth.objects.get().active_run_id)

    def test_network_call_has_no_extra_transaction(self):
        run = self.start()
        baseline = len(connection.atomic_blocks)
        def scope():
            self.assertEqual(len(connection.atomic_blocks), baseline)
            return {"allow_partys": {"partyid": [1]}, "allow_userinfos": {"user": []}, "allow_tags": {"tagid": []}}
        self.upstream.get_scope.side_effect = scope
        self.step(run)

    def test_expired_worker_cannot_overwrite_new_lease(self):
        data = self.start()
        run = AttendanceSyncRun.objects.get(pk=data["id"])
        config, first, first_step = services._claim(self.request(run), run.pk)
        with self.assertRaises(Conflict):
            services._claim(self.request(first), first.pk)
        AttendanceSyncRun.objects.filter(pk=run.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        run.refresh_from_db()
        _, second, second_step = services._claim(self.request(run), run.pk)
        result = self.upstream.get_scope.return_value
        with self.assertRaises(Conflict):
            services._finish(self.request(first), first, first_step, result)
        services._finish(self.request(second), second, second_step, result)
        run.refresh_from_db()
        self.assertEqual(run.completed_steps, 1)

    def test_revoked_permission_after_network_response_is_not_committed(self):
        run = self.start()
        def revoke():
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
            return self.upstream.get_scope.return_value
        self.upstream.get_scope.side_effect = revoke
        self.step(run, 403)
        saved = AttendanceSyncRun.objects.get(pk=run["id"])
        self.assertEqual(saved.status, "INVALIDATED")
        self.assertEqual(saved.completed_steps, 0)

    def test_view_permission_does_not_allow_sync_and_sync_alone_is_insufficient(self):
        with patch("apps.attendance.services.module_policy.has_permission", side_effect=lambda request, code: code.endswith("view_attendance")):
            self.assertEqual(self.client.get("/api/v1/attendance/overview/", {"month": "2026-09"}).status_code, 200)
            response = self.client.post("/api/v1/attendance/sync-runs/", {"month": "2026-09", "idempotency_key": str(uuid.uuid4())}, format="json")
            self.assertEqual(response.status_code, 403)
        with patch("apps.attendance.services.module_policy.has_permission", side_effect=lambda request, code: code.endswith("sync_attendance")):
            self.assertEqual(self.client.get("/api/v1/attendance/overview/", {"month": "2026-09"}).status_code, 403)

    def test_filters_reject_wrong_month_and_non_applicable_status(self):
        self.assertEqual(self.client.get("/api/v1/attendance/records/daily/", {"month": "2026-09", "date": "2026-08-31"}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/attendance/records/raw/", {"month": "2026-09", "status": "NOT_RETURNED"}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/attendance/records/monthly/", {"month": "2026-09", "date": "2026-09-01"}).status_code, 400)

    def test_department_options_and_filters_use_distinct_complete_paths(self):
        paths = ["总部/生产部", "分厂/生产部", "总部/生产部一组"]
        combined = " 总部/生产部 ; 分厂/生产部；总部/生产部 ;； "

        def department_rows(kind, start, end, users):
            source = self.source_rows(kind, start, end, users)
            if kind == "raw":
                return source
            row = source[0]
            return [
                {**row, "base_info": {**row["base_info"], "departs_name": combined}},
                {**row, "base_info": {**row["base_info"], "acctid": "Bound.Two", "departs_name": paths[2]}},
            ]

        self.upstream.get_records.side_effect = department_rows
        self.finish(self.start())
        overview = self.client.get("/api/v1/attendance/overview/", {"month": "2026-09"})
        self.assertEqual(overview.status_code, 200, overview.data)
        self.assertEqual(overview.data["data"]["departments"], sorted(paths))
        for kind in ("daily", "monthly"):
            for department, user_id in zip(paths, ("unbound.one", "unbound.one", "bound.two")):
                with self.subTest(kind=kind, department=department):
                    response = self.client.get(f"/api/v1/attendance/records/{kind}/",
                        {"month": "2026-09", "department": department})
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["count"], 1)
                    self.assertEqual(response.data["data"][0]["user_id"], user_id)
                    self.assertEqual(response.data["data"][0]["department_name"],
                                     combined if user_id == "unbound.one" else paths[2])
            for partial in ("生产部", "总部", "总部/生产"):
                self.assertEqual(self.client.get(f"/api/v1/attendance/records/{kind}/",
                    {"month": "2026-09", "department": partial}).data["count"], 0)
        self.assertEqual(self.client.get("/api/v1/attendance/records/raw/",
            {"month": "2026-09", "department": paths[0]}).data["count"], 0)

    def test_missing_and_blank_departments_produce_no_options_or_matches(self):
        def empty_department_rows(kind, start, end, users):
            source = self.source_rows(kind, start, end, users)
            if kind == "daily":
                source[0]["base_info"].pop("departs_name")
            elif kind == "monthly":
                source[0]["base_info"]["departs_name"] = " ;；  "
            return source

        self.upstream.get_records.side_effect = empty_department_rows
        self.finish(self.start())
        self.assertEqual(self.client.get("/api/v1/attendance/overview/",
            {"month": "2026-09"}).data["data"]["departments"], [])
        for kind in ("raw", "daily", "monthly"):
            self.assertEqual(self.client.get(f"/api/v1/attendance/records/{kind}/",
                {"month": "2026-09", "department": "生产部"}).data["count"], 0)

    def test_session_write_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/v1/attendance/sync-runs/", {"month": "2026-09", "idempotency_key": str(uuid.uuid4())}, format="json").status_code, 403)

    def test_unsynced_overview_has_explicit_empty_state(self):
        payload = self.client.get("/api/v1/attendance/overview/", {"month": "2026-09"}).data["data"]
        self.assertFalse(payload["has_data"])
        self.assertIsNone(payload["last_synced_at"])
        self.assertEqual(payload["scanned_members"], 0)

    def test_unbound_member_calendar_preserves_zero_and_source_exception(self):
        self.finish(self.start())
        payload = self.client.get("/api/v1/attendance/calendar/", {"month": "2026-09", "user_id": "Unbound.One"}).data["data"]
        self.assertEqual(len(payload["days"]), 30)
        self.assertEqual(payload["days"][0]["states"], ["missing", "zero"])
        self.assertEqual(payload["days"][1]["states"], ["unknown"])

    def test_calendar_rest_plan_preserves_source_exceptions(self):
        from apps.attendance.models import AttendanceSchedule
        from apps.attendance.schedule import empty_days
        self.finish(self.start())
        days = empty_days(date(2026, 9, 1))
        days[0]["kind"] = "REST"
        AttendanceSchedule.objects.create(corp_id="ww-test", month=date(2026, 9, 1), days=days)
        response = self.client.get("/api/v1/attendance/calendar/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 200, response.data)
        day = response.data["data"]["days"][0]
        self.assertEqual(day["states"], ["missing", "zero", "rest"])
        self.assertEqual(day["schedule"], {"date": "2026-09-01", "kind": "REST", "periods": []})

    def test_invalid_row_rolls_back_whole_step_and_retry_does_not_duplicate(self):
        run = self.start()
        while run["phase"] != "records":
            run = self.step(run)
        def invalid(kind, start, end, users):
            valid = self.source_rows(kind, start, end, users)
            return valid + [{**valid[0], "userid": "outside-enterprise"}]
        self.upstream.get_records.side_effect = invalid
        failed = self.step(run)
        self.assertEqual(failed["error_code"], "INVALID_SOURCE_DATA")
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        AttendanceSyncRun.objects.filter(pk=failed["id"]).update(retry_after=None)
        self.upstream.get_records.side_effect = self.source_rows
        completed = self.finish(self.step(failed))
        self.assertEqual(completed["status"], "SUCCESS")
        self.assertEqual(AttendanceRecord.objects.filter(kind="raw").count(), 1)

    def test_changed_config_restarts_and_late_old_run_cannot_publish(self):
        data = self.start()
        old = AttendanceSyncRun.objects.get(pk=data["id"])
        _, claimed, step = services._claim(self.request(old), old.pk)
        self.config.agent_id = "1000011"
        self.config.save()
        replacement = self.start()
        self.assertNotEqual(replacement["id"], data["id"])
        with self.assertRaises(Conflict):
            services._finish(self.request(claimed), claimed, step, self.upstream.get_scope.return_value)
        old.refresh_from_db()
        self.assertEqual(old.status, "INVALIDATED")
        self.assertEqual(str(AttendanceMonth.objects.get().current_run_id), replacement["id"])
        self.assertIsNone(AttendanceMonth.objects.get().active_run_id)

    def test_multiple_same_member_daily_rows_are_preserved_without_summing(self):
        self.upstream.get_records.side_effect = lambda kind, start, end, users: (
            self.source_rows(kind, start, end, users) * (2 if kind == "daily" else 1))
        self.finish(self.start())
        self.assertEqual(AttendanceRecord.objects.filter(kind="daily").count(), 2)
        result = selectors.member_calendar("2026-09", "unbound.one")["days"][0]
        self.assertIsNone(result["checkin_count"])
        self.assertIn("missing", result["states"])
        self.assertIn("unknown", result["states"])

    def test_returned_and_binding_filters_apply_to_success_snapshot_only(self):
        WeComBinding.objects.create(corp_id="ww-test", user_id="Bound.Two", member_name="已绑定成员",
                                   employee=self.employee, source="MANUAL")
        self.finish(self.start())
        query = {"month": "2026-09", "binding": "BOUND", "status": "NOT_RETURNED"}
        result = self.client.get("/api/v1/attendance/records/monthly/", query).data
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["user_id"], "bound.two")
        self.assertEqual(self.client.get("/api/v1/attendance/records/raw/",
            {"month": "2026-09", "binding": "BOUND"}).data["count"], 0)

    def test_failed_roster_step_does_not_save_partial_in_memory_members(self):
        run = self.start()
        run = self.step(self.step(run))
        self.upstream.get_department_members.side_effect = None
        self.upstream.get_department_members.return_value = [
            {"userid": "good", "name": "不可部分保存", "department": [1]},
            {"userid": "long", "name": "n" * 151, "department": [1]},
        ]
        failed = self.step(run)
        self.assertEqual(failed["status"], "FAILED")
        saved = AttendanceSyncRun.objects.get(pk=run["id"])
        self.assertEqual(saved.roster, {})
        self.assertEqual(saved.completed_steps, 2)

    def test_absence_api_keeps_daily_sources_and_does_not_replace_exceptions(self):
        def source(kind, start, end, users):
            rows = self.source_rows(kind, start, end, users)
            if kind == "raw":
                return rows
            rows[0]["sp_items"] = [{"type": 1, "vacation_id": 2, "count": 1,
                "duration": 43200, "time_type": 0, "name": "年假"}]
            if kind == "daily":
                rows[0]["ot_info"] = {"ot_status": 2, "ot_duration": 3600, "exception_duration": [120]}
                return rows * 2
            rows[0]["overwork_info"] = {"workday_over_sec": 0, "workdays_over_as_money": 0}
            return rows
        self.upstream.get_records.side_effect = source
        self.finish(self.start())
        day = self.client.get("/api/v1/attendance/calendar/", {"month": "2026-09", "user_id": "Unbound.One"}).data["data"]["days"][0]
        self.assertIn("missing", day["states"])
        self.assertEqual(len(day["source_summaries"]), 2)
        self.assertNotEqual(day["source_summaries"][0]["record_id"], day["source_summaries"][1]["record_id"])
        self.assertEqual(day["source_summaries"][0]["sp_items"][0]["duration"], 43200)
        self.assertIsNone(day["source_summaries"][0]["ot_info"]["workday_over_as_money"])
        monthly = self.client.get("/api/v1/attendance/records/monthly/", {"month": "2026-09"}).data["data"]
        row = next(value for value in monthly if value["record_status"] == "RETURNED")
        self.assertEqual(row["overwork_info"]["workday_over_sec"], 0)
        self.assertIsNone(row["overwork_info"]["holidays_over_sec"])

    def test_legacy_snapshots_and_not_returned_members_keep_null_supplements(self):
        self.finish(self.start())
        for record in AttendanceRecord.objects.exclude(kind="raw"):
            for key in ("sp_items", "ot_info", "overwork_info"):
                record.payload.pop(key, None)
            record.save(update_fields=["payload"])
        for kind, overtime in (("daily", "ot_info"), ("monthly", "overwork_info")):
            response = self.client.get(f"/api/v1/attendance/records/{kind}/", {"month": "2026-09"})
            self.assertEqual(response.status_code, 200)
            for row in response.data["data"]:
                self.assertIsNone(row["sp_items"])
                self.assertIsNone(row[overtime])

    def test_current_vacation_allows_unbound_snapshot_member_and_does_not_write(self):
        from django.test.utils import CaptureQueriesContext
        self.finish(self.start())
        self.upstream.get_vacation_config.return_value = [{"id": 2, "name": "年假", "time_attr": 0,
            "duration_type": 1, "quota_type": 0, "perday_duration": 86400}]
        self.upstream.get_vacation_quota.return_value = [{"id": 2, "name": "年假", "leftduration": 0,
            "assignduration": None, "real_assignduration": None, "usedduration": None},
            {"id": 99, "name": "未知配置假种", "leftduration": 3600}]
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/attendance/vacation/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertTrue(data["is_current"])
        self.assertNotIn("month", data)
        self.assertIsNotNone(data["fetched_at"])
        self.assertEqual(data["items"][0]["leftduration"], 0)
        self.assertIsNone(data["items"][0]["usedduration"])
        self.assertEqual(data["items"][0]["quota_type"], 0)
        self.assertIsNone(data["items"][1]["time_attr"])
        self.upstream.get_vacation_quota.assert_called_once_with("unbound.one")
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))

    def test_vacation_rejects_outside_snapshot_and_missing_view_permission_before_call(self):
        self.finish(self.start())
        for query in ({"month": "2026-09", "user_id": "outsider"}, {"month": "2026-08", "user_id": "Unbound.One"}):
            self.assertEqual(self.client.get("/api/v1/attendance/vacation/", query).status_code, 404)
        with patch("apps.attendance.services.module_policy.has_permission", return_value=False):
            self.assertEqual(self.client.get("/api/v1/attendance/vacation/",
                {"month": "2026-09", "user_id": "Unbound.One"}).status_code, 403)
        self.upstream.get_vacation_config.assert_not_called()
        self.upstream.get_vacation_quota.assert_not_called()

    def test_vacation_view_permission_suffices_and_upstream_failure_is_not_empty_success(self):
        self.finish(self.start())
        self.upstream.get_vacation_config.return_value = []
        self.upstream.get_vacation_quota.return_value = []
        with patch("apps.attendance.services.module_policy.has_permission", side_effect=lambda request, code: code == "attendance.view_attendance"):
            response = self.client.get("/api/v1/attendance/vacation/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["items"], [])
        self.upstream.get_vacation_quota.side_effect = WeComError("VACATION_PERMISSION_DENIED", "应用没有假期读取权限。")
        response = self.client.get("/api/v1/attendance/vacation/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("items", response.data)

    def test_vacation_rechecks_permission_and_configuration_after_network(self):
        self.finish(self.start())
        self.upstream.get_vacation_config.return_value = []
        def disable_user(user_id):
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
            return []
        self.upstream.get_vacation_quota.side_effect = disable_user
        self.assertEqual(self.client.get("/api/v1/attendance/vacation/",
            {"month": "2026-09", "user_id": "Unbound.One"}).status_code, 403)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=True)
        def disable_config(user_id):
            self.config.enabled = False
            self.config.save()
            return []
        self.upstream.get_vacation_quota.side_effect = disable_config
        self.assertEqual(self.client.get("/api/v1/attendance/vacation/",
            {"month": "2026-09", "user_id": "Unbound.One"}).status_code, 409)

    def test_vacation_missing_configuration_is_explicit_before_and_after_network(self):
        self.finish(self.start())
        self.upstream.get_vacation_config.return_value = []
        def remove_config(user_id):
            self.config.delete()
            return []
        self.upstream.get_vacation_quota.side_effect = remove_config
        response = self.client.get("/api/v1/attendance/vacation/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 409)
        self.upstream.get_vacation_config.reset_mock()
        self.upstream.get_vacation_quota.reset_mock()
        response = self.client.get("/api/v1/attendance/vacation/", {"month": "2026-09", "user_id": "Unbound.One"})
        self.assertEqual(response.status_code, 409)
        self.upstream.get_vacation_config.assert_not_called()
        self.upstream.get_vacation_quota.assert_not_called()
