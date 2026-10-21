import io
import json
import traceback
from http.client import IncompleteRead
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from apps.attendance.client import AttendanceClient
from apps.wecom.client import WeComError


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.status = status


@override_settings(CACHES={"wecom": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "attendance-client-tests-20261019",
}})
class AttendanceClientTests(SimpleTestCase):
    # 2026-09-01 / 2026-09-30，Asia/Shanghai 零点；直接使用核算后的常量。
    START = 1788192000
    END = 1790697600

    def setUp(self):
        caches["wecom"].clear()
        self.addCleanup(caches["wecom"].clear)
        self.enterContext(patch("apps.wecom.client.decrypt_secret", return_value="private-secret"))
        self.open = self.enterContext(patch("apps.wecom.client.build_opener")).return_value.open
        self.client = AttendanceClient(SimpleNamespace(
            corp_id="ww_test", agent_id="1000010", secret_ciphertext="test-encrypted",
        ))

    def responses(self, *payloads):
        self.open.side_effect = [
            item if isinstance(item, Exception) else Response(item) for item in payloads
        ]

    def token(self, value="private-access-token"):
        return {"errcode": 0, "access_token": value, "expires_in": 7200}

    def assert_safe_error(self, operation, code="UPSTREAM_UNAVAILABLE"):
        with self.assertRaises(WeComError) as raised:
            operation()
        error = raised.exception
        self.assertEqual(error.code, code)
        text = "".join(traceback.format_exception_only(error))
        for value in ("private-secret", "private-access-token", "private-body", "qyapi.weixin.qq.com"):
            self.assertNotIn(value, text)
        if error.__context__ is not None:
            self.assertTrue(error.__suppress_context__)
        self.assertIsNone(error.__cause__)
        return error

    def scope(self, **overrides):
        return {"errcode": 0, "agentid": 1000010, "allow_partys": {"partyid": [1]},
                "allow_userinfos": {"user": [{"userid": "Member.One"}]},
                "allow_tags": {"tagid": []}, **overrides}

    def test_scope_returns_only_explicit_visibility_fields(self):
        self.responses(self.token(), self.scope(secret="private-secret", report_location_flag=1))
        self.assertEqual(self.client.get_scope(), {
            "allow_partys": {"partyid": [1]}, "allow_userinfos": {"user": [{"userid": "Member.One"}]},
            "allow_tags": {"tagid": []},
        })
        request = self.open.call_args.args[0]
        self.assertEqual(urlsplit(request.full_url).path, "/cgi-bin/agent/get")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["agentid"], ["1000010"])

    def test_empty_departments_are_empty_and_missing_departments_are_an_error(self):
        empty = self.scope(allow_partys={"partyid": []}, allow_userinfos={"user": []})
        self.responses(self.token(), empty)
        self.assertEqual(self.client.get_scope()["allow_partys"], {"partyid": []})
        payload = self.scope()
        del payload["allow_partys"]
        self.responses(payload)
        self.assert_safe_error(self.client.get_scope)

    def test_optional_visibility_fields_are_not_invented_when_absent(self):
        for missing in (("allow_userinfos",), ("allow_tags",), ("allow_userinfos", "allow_tags")):
            with self.subTest(missing=missing):
                caches["wecom"].clear()
                payload = self.scope()
                for field in missing:
                    del payload[field]
                self.responses(self.token(), payload)
                result = self.client.get_scope()
                self.assertEqual(result["allow_partys"], {"partyid": [1]})
                for field in missing:
                    self.assertNotIn(field, result)

    def test_scope_rejects_wrong_agent_and_invalid_visibility_values(self):
        for overrides in ({"agentid": 1}, {"agentid": True}, {"close": 1}):
            with self.subTest(overrides=overrides):
                caches["wecom"].clear()
                self.responses(self.token(), self.scope(**overrides))
                self.assert_safe_error(self.client.get_scope, "CONFIGURATION_ERROR")
        for overrides in ({"allow_partys": {"partyid": [True]}}, {"allow_tags": {"tagid": [0]}},
                          {"allow_userinfos": {"user": [{"userid": ""}]}}, {"allow_userinfos": {"user": {}}},
                          {"allow_tags": None}, {"allow_userinfos": []},
                          {"allow_tags": {}}, {"allow_userinfos": {}}, {"allow_partys": {}}):
            self.responses(self.scope(**overrides))
            self.assert_safe_error(self.client.get_scope)

    def test_department_list_uses_simple_endpoint_and_keeps_only_ids(self):
        self.responses(self.token(), {"errcode": 0, "department_id": [
            {"id": 1, "parentid": 0, "order": 1}, {"id": 2, "parentid": 1, "order": 2},
        ]})
        self.assertEqual(self.client.get_departments(), [{"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}])
        self.assertEqual(urlsplit(self.open.call_args.args[0].full_url).path, "/cgi-bin/department/simplelist")

    def test_member_list_requests_one_department_and_drops_sensitive_fields(self):
        self.responses(self.token(), {"errcode": 0, "userlist": [
            {"userid": "Member.One", "name": "张三", "department": [2], "mobile": "private-body"},
            {"userid": "Member.Two", "department": [2]},
        ]})
        self.assertEqual(self.client.get_department_members(2), [
            {"userid": "Member.One", "name": "张三", "department": [2]},
            {"userid": "Member.Two", "name": "", "department": [2]},
        ])
        url = urlsplit(self.open.call_args.args[0].full_url)
        self.assertEqual(url.path, "/cgi-bin/user/simplelist")
        self.assertEqual(parse_qs(url.query), {"department_id": ["2"], "access_token": ["private-access-token"]})

    def test_tag_members_return_explicit_users_and_departments(self):
        self.responses(self.token(), {"errcode": 0, "userlist": [{"userid": "Member.One", "name": "张三"}],
                                      "partylist": [2], "tagname": "一组"})
        self.assertEqual(self.client.get_tag_members(3), {
            "users": [{"userid": "Member.One", "name": "张三"}], "departments": [2],
        })
        url = urlsplit(self.open.call_args.args[0].full_url)
        self.assertEqual(url.path, "/cgi-bin/tag/get")
        self.assertEqual(parse_qs(url.query)["tagid"], ["3"])

    def test_directory_arrays_are_required_and_fields_are_typed(self):
        cases = [
            (self.client.get_departments, {"department_id": None}),
            (self.client.get_departments, {}),
            (self.client.get_departments, {"department_id": [{"id": True, "parentid": 0}]}),
            (self.client.get_departments, {"department_id": [{"id": 2}]}),
            (lambda: self.client.get_department_members(2), {}),
            (lambda: self.client.get_department_members(2), {"userlist": [{"userid": "one", "department": "2"}]}),
            (lambda: self.client.get_department_members(2), {"userlist": [{"userid": "one", "name": None, "department": [2]}]}),
            (lambda: self.client.get_tag_members(2), {"userlist": []}),
            (lambda: self.client.get_tag_members(2), {"userlist": [], "partylist": [False]}),
        ]
        for operation, payload in cases:
            with self.subTest(payload=payload):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, **payload})
                self.assert_safe_error(operation)

    def test_invalid_directory_ids_fail_before_any_request(self):
        for value in (True, 0, -1, "2", 2 ** 32, None):
            for method in (self.client.get_department_members, self.client.get_tag_members):
                with self.subTest(value=value, method=method.__name__):
                    self.assert_safe_error(lambda: method(value), "ATTENDANCE_REQUEST_INVALID")
        self.open.assert_not_called()

    def test_each_record_kind_posts_exact_read_only_payload(self):
        for kind, endpoint, array in (("raw", "getcheckindata", "checkindata"),
                                      ("daily", "getcheckin_daydata", "datas"),
                                      ("monthly", "getcheckin_monthdata", "datas")):
            with self.subTest(kind=kind):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, array: []})
                self.assertEqual(self.client.get_records(kind, self.START, self.END, ["Member.One"]), [])
                request = self.open.call_args.args[0]
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(urlsplit(request.full_url).path, "/cgi-bin/checkin/" + endpoint)
                expected = {"starttime": self.START, "endtime": self.END, "useridlist": ["Member.One"]}
                if kind == "raw":
                    expected["opencheckindatatype"] = 3
                self.assertEqual(json.loads(request.data), expected)
                self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_record_outer_arrays_cannot_be_missing_or_wrong_type(self):
        for kind, field in (("raw", "checkindata"), ("daily", "datas"), ("monthly", "datas")):
            for payload in ({}, {field: None}, {field: {}}, {field: ["bad"]}):
                with self.subTest(kind=kind, payload=payload):
                    caches["wecom"].clear()
                    self.responses(self.token(), {"errcode": 0, **payload})
                    self.assert_safe_error(lambda: self.client.get_records(kind, self.START, self.END, ["one"]))

    def test_valid_records_preserve_source_units_and_missing_optional_fields(self):
        fixtures = {
            "raw": {"userid": "one", "checkin_time": self.START + 1, "checkin_type": "上班打卡",
                    "exception_type": "时间异常;地点异常", "groupname": "规则一"},
            "daily": {"base_info": {"acctid": "one", "date": self.START, "day_type": 1},
                      "summary_info": {"regular_work_sec": 3600, "earliest_time": 38827},
                      "exception_infos": [{"exception": 1, "count": 1}]},
            "monthly": {"base_info": {"acctid": "one"}, "summary_info": {"work_days": 20},
                        "exception_infos": []},
        }
        for kind, row in fixtures.items():
            caches["wecom"].clear()
            self.responses(self.token(), {"errcode": 0, "checkindata" if kind == "raw" else "datas": [row]})
            self.assertEqual(self.client.get_records(kind, self.START, self.END, ["one"]), [row])

    def test_record_identifiers_dates_and_known_optional_fields_are_validated(self):
        cases = [
            ("raw", {"userid": "other", "checkin_time": self.START}),
            ("raw", {"userid": "one", "checkin_time": "1"}),
            ("raw", {"userid": "one", "checkin_time": self.START, "exception_type": []}),
            ("daily", {"base_info": {"acctid": "one"}}),
            ("daily", {"base_info": {"acctid": "one", "date": self.START}, "summary_info": []}),
            ("monthly", {"base_info": {"acctid": "one"}, "summary_info": {"work_days": True}}),
            ("monthly", {"base_info": {"acctid": "one"}, "exception_infos": None}),
            ("monthly", {"base_info": {"acctid": "one"}, "exception_infos": [{"exception": 7}]}),
            ("monthly", {"base_info": {"acctid": "one"}, "exception_infos": [{"exception": 1, "count": "1"}]}),
        ]
        for kind, row in cases:
            with self.subTest(kind=kind, row=row):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, "checkindata" if kind == "raw" else "datas": [row]})
                self.assert_safe_error(lambda: self.client.get_records(kind, self.START, self.END, ["one"]))

    def test_invalid_record_inputs_fail_before_request(self):
        cases = [
            ("other", self.START, self.END, ["one"]),
            ("raw", True, self.END, ["one"]), ("raw", self.START, self.START - 1, ["one"]),
            ("raw", self.START, self.START + 30 * 86400 + 1, ["one"]),
            ("raw", self.START, 2 ** 32, ["one"]), ("raw", self.START, self.END, []),
            ("raw", self.START, self.END, ["one"] * 101), ("raw", self.START, self.END, "one"),
            ("raw", self.START, self.END, [""]), ("raw", self.START, self.END, ["中" * 22]),
            ("raw", self.START, self.END, ["one\n"]),
            ("daily", self.START + 1, self.END, ["one"]),
            ("monthly", self.START, self.END + 1, ["one"]),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assert_safe_error(lambda: self.client.get_records(*args), "ATTENDANCE_REQUEST_INVALID")
        self.open.assert_not_called()

    def test_same_day_report_and_raw_30_day_boundary_are_allowed(self):
        self.responses(self.token(), {"errcode": 0, "datas": []}, {"errcode": 0, "checkindata": []})
        self.assertEqual(self.client.get_records("daily", self.START, self.START, ["one"]), [])
        self.assertEqual(self.client.get_records("raw", self.START, self.START + 30 * 86400, ["one"]), [])

    def test_post_refreshes_only_explicitly_invalid_token_once(self):
        for code in (40014, 42001):
            with self.subTest(code=code):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), {"errcode": code}, self.token("refreshed"), {"errcode": 0, "datas": []})
                self.assertEqual(self.client.get_records("daily", self.START, self.END, ["one"]), [])
                requests = [call.args[0] for call in self.open.call_args_list]
                self.assertEqual(len(requests), 4)
                self.assertEqual(requests[1].data, requests[3].data)
                self.assertEqual(parse_qs(urlsplit(requests[3].full_url).query)["access_token"], ["refreshed"])

    def test_repeated_token_rejection_stops_after_second_read(self):
        self.responses(self.token(), {"errcode": 42001}, self.token("fresh"), {"errcode": 42001, "errmsg": "private-body"})
        self.assert_safe_error(lambda: self.client.get_records("daily", self.START, self.END, ["one"]))
        self.assertEqual(len(self.open.call_args_list), 4)

    def test_transport_invalid_json_and_unexpected_envelopes_do_not_retry(self):
        failures = [TimeoutError("private-access-token"), URLError("private-body"), IncompleteRead(b"private-body"),
                    HTTPError("https://qyapi.weixin.qq.com/?access_token=private-access-token", 502, "private-body", {}, None),
                    b"private-body", b"\xff", {"errcode": "0"}, {"errcode": False}, [],
                    {"errcode": 999999, "errmsg": "private-body"}]
        for result in failures:
            with self.subTest(result=type(result).__name__):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), result)
                self.assert_safe_error(lambda: self.client.get_records("daily", self.START, self.END, ["one"]))
                self.assertEqual(len(self.open.call_args_list), 2)

    def test_oversized_and_non_200_response_are_safe_errors(self):
        for response in (Response(b"x" * (1024 * 1024 + 1)), Response({"errcode": 0, "datas": []}, 302)):
            caches["wecom"].clear()
            self.open.reset_mock()
            self.open.side_effect = [Response(self.token()), response]
            self.assert_safe_error(lambda: self.client.get_records("daily", self.START, self.END, ["one"]))
            self.assertEqual(len(self.open.call_args_list), 2)

    def test_official_permission_error_keeps_shared_safe_mapping(self):
        self.responses(self.token(), {"errcode": 48001, "errmsg": "private-body private-secret"})
        self.assert_safe_error(lambda: self.client.get_records("daily", self.START, self.END, ["one"]), "CONFIGURATION_ERROR")

    def test_rules_use_empty_read_only_post_and_return_group_array(self):
        group = {"groupid": 10, "grouptype": 1, "groupname": "日班", "checkindate": [
            {"workdays": [1, 2, 3, 4, 5], "checkintime": [{"work_sec": 32400, "off_work_sec": 64800}]},
        ]}
        self.responses(self.token(), {"errcode": 0, "group": [group]})
        self.assertEqual(self.client.get_rules(), [group])
        request = self.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(urlsplit(request.full_url).path, "/cgi-bin/checkin/getcorpcheckinoption")
        self.assertEqual(json.loads(request.data), {})

    def test_rules_missing_or_malformed_group_is_not_an_empty_success(self):
        for payload in ({}, {"group": None}, {"group": [{}]},
                        {"group": [{"groupid": 1, "grouptype": 9, "groupname": "日班"}]},
                        {"group": [{"groupid": 1, "grouptype": 1, "groupname": "n" * 151}]}):
            caches["wecom"].clear()
            self.responses(self.token(), {"errcode": 0, **payload})
            self.assert_safe_error(self.client.get_rules)

    def test_vacation_reads_use_official_endpoints_and_drop_unneeded_fields(self):
        self.responses(self.token(), {"errcode": 0, "lists": [{"id": 2, "name": "年假", "time_attr": 0,
            "duration_type": 1, "perday_duration": 86400, "quota_attr": {"type": 0, "private": "discard"}}]},
            {"errcode": 0, "lists": [{"id": 2, "vacationname": "年假", "leftduration": 0, "private": "discard"}]})
        config = self.client.get_vacation_config()
        self.assertEqual(urlsplit(self.open.call_args.args[0].full_url).path, "/cgi-bin/oa/vacation/getcorpconf")
        self.assertEqual(self.open.call_args.args[0].get_method(), "GET")
        self.assertEqual(config[0]["quota_type"], 0)
        self.assertNotIn("quota_attr", config[0])
        quota = self.client.get_vacation_quota("Member.One")
        request = self.open.call_args.args[0]
        self.assertEqual(urlsplit(request.full_url).path, "/cgi-bin/oa/vacation/getuservacationquota")
        self.assertEqual(json.loads(request.data), {"userid": "Member.One"})
        self.assertEqual(quota[0]["leftduration"], 0)
        self.assertIsNone(quota[0]["usedduration"])
        self.assertNotIn("private", quota[0])

    def test_vacation_permission_and_malformed_lists_are_explicit_errors(self):
        for method in (self.client.get_vacation_config, lambda: self.client.get_vacation_quota("one")):
            caches["wecom"].clear()
            self.responses(self.token(), {"errcode": 301062, "errmsg": "private-body"})
            self.assert_safe_error(method, "VACATION_PERMISSION_DENIED")
            for rows in (None, {}, [{"id": True}], [{"id": 1}, {"id": 1}], [{"id": 1, "leftduration": True}]):
                if method == self.client.get_vacation_config and rows == [{"id": 1, "leftduration": True}]:
                    continue
                self.responses({"errcode": 0, "lists": rows})
                self.assert_safe_error(method)

    def test_vacation_invalid_member_fails_before_request(self):
        for value in (None, "", " ", True, "a" * 65):
            self.assert_safe_error(lambda: self.client.get_vacation_quota(value), "ATTENDANCE_REQUEST_INVALID")
        self.open.assert_not_called()
