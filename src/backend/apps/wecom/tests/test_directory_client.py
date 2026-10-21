from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from apps.wecom.client import WeComError
from apps.wecom.directory_client import WeComDirectoryClient
from apps.wecom.tests.test_client import Response


@override_settings(CACHES={"wecom": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "wecom-directory-unit1-20261021",
}})
class WeComDirectoryClientTests(SimpleTestCase):
    def setUp(self):
        caches["wecom"].clear()
        self.addCleanup(caches["wecom"].clear)
        self.enterContext(patch("apps.wecom.client.decrypt_secret", return_value="private-secret"))
        self.open = self.enterContext(patch("apps.wecom.client.build_opener")).return_value.open
        self.client = WeComDirectoryClient(SimpleNamespace(
            corp_id="ww_directory_test", agent_id="1000010", secret_ciphertext="test-encrypted",
        ))

    def responses(self, *payloads):
        self.open.side_effect = [
            item if isinstance(item, Exception) else Response(item) for item in payloads
        ]

    def token(self, value="private-access-token"):
        return {"errcode": 0, "access_token": value, "expires_in": 7200}

    def scope(self, **overrides):
        return {"errcode": 0, "agentid": 1000010, "allow_partys": {"partyid": [1]}, **overrides}

    def department_list(self, *rows):
        return {"errcode": 0, "department_id": list(rows) or [{"id": 1, "parentid": 0}]}

    def department(self, department_id=1, parent_id=0, **overrides):
        return {"errcode": 0, "department": {
            "id": department_id, "parentid": parent_id, "name": "测试部门", **overrides,
        }}

    def member(self, **overrides):
        return {"userid": "Member.One", "name": "测试员工", "department": [1],
                "main_department": 1, "status": 1, **overrides}

    def assert_error(self, operation, code):
        with self.assertRaises(WeComError) as raised:
            operation()
        error = raised.exception
        self.assertEqual(error.code, code)
        for secret in ("private-secret", "private-access-token", "raw upstream", "qyapi.weixin.qq.com"):
            self.assertNotIn(secret, str(error))
        return error

    def test_complete_directory_uses_read_only_endpoints_and_discards_private_fields(self):
        self.responses(self.token(), self.scope(), self.department_list(),
                       self.department(department_leader=["private-body"]), {
                           "errcode": 0, "userlist": [self.member(mobile="private-body", email="private-body")],
                       })
        self.assertEqual(self.client.read_directory(), {
            "corp_id": "ww_directory_test",
            "departments": [{"id": 1, "parentid": 0, "name": "测试部门"}],
            "members": [{"userid": "Member.One", "name": "测试员工", "department": [1],
                         "main_department": 1, "status": 1, "status_label": "已激活"}],
        })
        urls = [urlsplit(call.args[0].full_url) for call in self.open.call_args_list]
        self.assertEqual([url.path for url in urls], [
            "/cgi-bin/gettoken", "/cgi-bin/agent/get", "/cgi-bin/department/simplelist",
            "/cgi-bin/department/get", "/cgi-bin/user/list",
        ])
        self.assertEqual(parse_qs(urls[-1].query), {"department_id": ["1"], "access_token": ["private-access-token"]})
        self.assertEqual(parse_qs(urls[-2].query)["id"], ["1"])
        for call in self.open.call_args_list:
            self.assertEqual(call.args[0].get_method(), "GET")
            self.assertIsNone(call.args[0].data)
            self.assertEqual(call.kwargs["timeout"], 8)

    def test_account_states_are_retained_without_mapping_to_erp_employment(self):
        for status, label in ((1, "已激活"), (2, "已禁用"), (4, "未激活"), (5, "退出企业"), (9, "未知"), (None, "未知")):
            with self.subTest(status=status):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, "userlist": [self.member(status=status)]})
                member = self.client.get_department_members(1)[0]
                self.assertEqual((member["status"], member["status_label"]), (status, label))
                self.assertNotIn("employee_status", member)

    def test_missing_name_primary_department_and_status_are_not_invented(self):
        self.responses(self.token(), {"errcode": 0, "userlist": [{"userid": "one", "department": [2, 1]}]})
        self.assertEqual(self.client.get_department_members(1), [{
            "userid": "one", "name": "", "department": [1, 2], "main_department": None,
            "status": None, "status_label": "未知",
        }])

    def test_multi_department_member_is_deduplicated_by_case_insensitive_userid(self):
        self.responses(self.token(), self.scope(), self.department_list(
            {"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}),
            self.department(), self.department(2, 1, name="第二部门"),
            {"errcode": 0, "userlist": [self.member(department=[2, 1], main_department=2)]},
            {"errcode": 0, "userlist": [self.member(userid="member.one", department=[1, 2], main_department=2)]})
        result = self.client.read_directory()
        self.assertEqual(len(result["members"]), 1)
        self.assertEqual(result["members"][0]["userid"], "Member.One")
        self.assertEqual(result["members"][0]["department"], [1, 2])
        self.assertEqual(result["members"][0]["main_department"], 2)
        self.assertEqual(len(result["departments"]), 2)

    def test_same_name_with_different_userids_stays_separate(self):
        self.responses(self.token(), self.scope(), self.department_list(), self.department(),
                       {"errcode": 0, "userlist": [self.member(), self.member(userid="Member.Two")]})
        self.assertEqual(len(self.client.read_directory()["members"]), 2)

    def test_missing_member_in_either_declared_department_rejects_partial_directory(self):
        for rows in (([self.member(department=[1, 2])], []), ([], [self.member(department=[1, 2])])):
            with self.subTest(missing_first=not rows[0]):
                caches["wecom"].clear()
                self.responses(self.token(), self.scope(), self.department_list(
                    {"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}),
                    self.department(), self.department(2, 1),
                    {"errcode": 0, "userlist": rows[0]}, {"errcode": 0, "userlist": rows[1]})
                self.assert_error(self.client.read_directory, "DIRECTORY_CHANGED")

    def test_complete_memberships_do_not_depend_on_department_enumeration_order(self):
        self.responses(self.token(), self.scope(), self.department_list(
            {"id": 2, "parentid": 1}, {"id": 1, "parentid": 0}),
            self.department(2, 1), self.department(),
            {"errcode": 0, "userlist": [self.member(department=[1, 2])]},
            {"errcode": 0, "userlist": [self.member(department=[2, 1])]})
        result = self.client.read_directory()
        self.assertEqual([department["id"] for department in result["departments"]], [1, 2])
        self.assertEqual(len(result["members"]), 1)

    def test_scope_missing_root_is_rejected_before_reading_any_members(self):
        for parties in (None, {}, {"partyid": []}, {"partyid": [2]}, {"partyid": [True]}, {"partyid": [1, "2"]}):
            with self.subTest(parties=parties):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), self.scope(allow_partys=parties))
                self.assert_error(self.client.read_directory, "DIRECTORY_SCOPE_INCOMPLETE")
                self.assertEqual(self.open.call_count, 2)

    def test_wrong_or_disabled_application_is_rejected(self):
        for fields in ({"agentid": 2}, {"agentid": True}, {"close": 1}, {"close": False}):
            with self.subTest(fields=fields):
                caches["wecom"].clear()
                self.responses(self.token(), self.scope(**fields))
                self.assert_error(self.client.read_directory, "CONFIGURATION_ERROR")

    def test_incomplete_or_cyclic_department_tree_is_rejected(self):
        for rows in ([], [{"id": 2, "parentid": 0}], [{"id": 1, "parentid": 2}],
                     [{"id": 1, "parentid": 0}, {"id": 2, "parentid": 3}],
                     [{"id": 1, "parentid": 0}, {"id": 2, "parentid": 3}, {"id": 3, "parentid": 2}],
                     [{"id": 1, "parentid": 0}, {"id": 2, "parentid": 0}]):
            with self.subTest(rows=rows):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, "department_id": rows})
                self.assert_error(self.client.get_departments, "DIRECTORY_SCOPE_INCOMPLETE")

    def test_invalid_or_duplicate_department_ids_are_rejected(self):
        for rows in (None, [None], [{"id": True, "parentid": 0}], [{"id": 1}],
                     [{"id": 1, "parentid": False}], [{"id": 1, "parentid": 0}] * 2):
            with self.subTest(rows=rows):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, "department_id": rows})
                self.assert_error(self.client.get_departments, "INVALID_DIRECTORY_DATA")

    def test_department_detail_mismatch_or_missing_name_is_rejected(self):
        for fields in ({"id": 2}, {"id": True}, {"parentid": 1}, {"parentid": False},
                       {"name": None}, {"name": " "}, {"name": "bad\nname"}):
            with self.subTest(fields=fields):
                caches["wecom"].clear()
                self.responses(self.token(), self.department_list(), self.department(**fields))
                self.assert_error(self.client.get_departments, "INVALID_DIRECTORY_DATA")

    def test_invalid_member_fields_are_rejected(self):
        cases = [{"userid": ""}, {"userid": " one "}, {"userid": True}, {"name": None},
                 {"name": "bad\nname"}, {"department": None}, {"department": []},
                 {"department": [True]}, {"department": [1, 1]}, {"department": [2]},
                 {"main_department": 2}, {"main_department": True}, {"status": True},
                 {"status": "1"}, {"status": -1}, {"status": {}}, {"status": 2 ** 32}]
        for fields in cases:
            with self.subTest(fields=fields):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, "userlist": [self.member(**fields)]})
                self.assert_error(lambda: self.client.get_department_members(1), "INVALID_DIRECTORY_DATA")

    def test_missing_or_invalid_member_list_is_rejected(self):
        for fields in ({}, {"userlist": None}, {"userlist": [None]}, {"userlist": {}}):
            with self.subTest(fields=fields):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, **fields})
                self.assert_error(lambda: self.client.get_department_members(1), "INVALID_DIRECTORY_DATA")

    def test_duplicate_userid_within_one_department_is_rejected(self):
        self.responses(self.token(), {"errcode": 0, "userlist": [self.member(), self.member(userid="member.one")]})
        self.assert_error(lambda: self.client.get_department_members(1), "INVALID_DIRECTORY_DATA")

    def test_invalid_department_input_never_makes_a_network_request(self):
        for department_id in (True, False, 0, -1, "1", None, 2 ** 32):
            error = self.assert_error(lambda: self.client.get_department_members(department_id), "DIRECTORY_REQUEST_INVALID")
            self.assertEqual(error.status, 400)
        self.open.assert_not_called()

    def test_member_referencing_unread_department_rejects_complete_result(self):
        self.responses(self.token(), self.scope(), self.department_list(), self.department(),
                       {"errcode": 0, "userlist": [self.member(department=[1, 2])]})
        self.assert_error(self.client.read_directory, "DIRECTORY_SCOPE_INCOMPLETE")

    def test_contradictory_member_details_across_departments_are_rejected(self):
        for fields in ({"name": "另一个名字"}, {"status": 2}, {"department": [2], "main_department": 2}):
            with self.subTest(fields=fields):
                caches["wecom"].clear()
                changed = {**self.member(department=[1, 2]), **fields}
                self.responses(self.token(), self.scope(), self.department_list(
                    {"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}),
                    self.department(), self.department(2, 1),
                    {"errcode": 0, "userlist": [self.member(department=[1, 2])]},
                    {"errcode": 0, "userlist": [changed]})
                self.assert_error(self.client.read_directory, "DIRECTORY_CHANGED")

    def test_empty_department_is_valid_but_empty_company_is_not_a_success(self):
        self.responses(self.token(), {"errcode": 0, "userlist": []})
        self.assertEqual(self.client.get_department_members(1), [])
        self.responses(self.scope(), self.department_list(), self.department(), {"errcode": 0, "userlist": []})
        self.assert_error(self.client.read_directory, "EMPTY_DIRECTORY")

    def test_network_failure_after_first_department_does_not_return_partial_directory(self):
        self.responses(self.token(), self.scope(), self.department_list(
            {"id": 1, "parentid": 0}, {"id": 2, "parentid": 1}),
            self.department(), self.department(2, 1),
            {"errcode": 0, "userlist": [self.member()]}, URLError("raw upstream private-secret"))
        self.assert_error(self.client.read_directory, "UPSTREAM_UNAVAILABLE")
        self.assertEqual(self.open.call_count, 7)

    def test_upstream_permission_error_is_sanitized(self):
        self.responses(self.token(), {"errcode": 48001, "errmsg": "raw upstream private-secret"})
        self.assert_error(lambda: self.client.get_department_members(1), "CONFIGURATION_ERROR")
        self.assertEqual(self.open.call_count, 2)

    def test_token_expiry_retries_read_only_query_once(self):
        self.responses(self.token(), {"errcode": 42001}, self.token("fresh-token"),
                       {"errcode": 0, "userlist": [self.member()]})
        self.assertEqual(len(self.client.get_department_members(1)), 1)
        self.assertEqual(self.open.call_count, 4)
        url = urlsplit(self.open.call_args.args[0].full_url)
        self.assertEqual(parse_qs(url.query)["access_token"], ["fresh-token"])

    def test_read_failure_does_not_reuse_members_from_a_previous_call(self):
        self.responses(self.token(), self.scope(), self.department_list(), self.department(),
                       {"errcode": 0, "userlist": [self.member()]})
        self.assertEqual(len(self.client.read_directory()["members"]), 1)
        self.responses(self.scope(), self.department_list(), self.department(), {"errcode": 0, "userlist": []})
        self.assert_error(self.client.read_directory, "EMPTY_DIRECTORY")

    def test_inherited_login_member_check_still_rejects_inactive_members(self):
        for status in (2, 4, 5):
            with self.subTest(status=status):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, **self.member(status=status)})
                self.assert_error(lambda: self.client.get_member("Member.One"), "MEMBER_REJECTED")
