import io
import json
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener as real_build_opener
from urllib.response import addinfourl

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from apps.wecom.client import WeComClient, WeComError
from apps.wecom.credentials import CredentialError


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        super().__init__(body)
        self.status = status


@override_settings(CACHES={"wecom": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "wecom-client-tests-20261019",
}})
class WeComClientTests(SimpleTestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            corp_id="ww_test_corp", agent_id=1000001,
            secret_ciphertext="encrypted-test-secret",
        )
        caches["wecom"].clear()
        self.addCleanup(caches["wecom"].clear)
        self.decrypt = self.enterContext(patch(
            "apps.wecom.client.decrypt_secret", return_value="private-secret",
        ))
        self.build_opener = self.enterContext(patch("apps.wecom.client.build_opener"))
        self.open = self.build_opener.return_value.open
        self.client = WeComClient(self.config)

    def responses(self, *responses):
        self.open.side_effect = [
            item if isinstance(item, Exception) else Response(item)
            for item in responses
        ]

    def token(self, value="private-access-token", expires_in=7200):
        return {"errcode": 0, "errmsg": "ok", "access_token": value, "expires_in": expires_in}

    def requests(self):
        return [urlsplit(call.args[0].full_url) for call in self.open.call_args_list]

    def assert_safe_error(self, operation, code="UPSTREAM_UNAVAILABLE"):
        with self.assertRaises(WeComError) as raised:
            operation()
        error = raised.exception
        self.assertEqual(error.code, code)
        rendered = "".join(traceback.format_exception_only(error))
        for private in ("private-secret", "private-access-token", "sensitive-code", "raw upstream", "qyapi.weixin.qq.com"):
            self.assertNotIn(private, rendered)
        self.assertEqual(str(error), error.message)
        if error.__context__ is not None:
            self.assertTrue(error.__suppress_context__)
        self.assertIsNone(error.__cause__)
        return error

    def test_identity_uses_current_endpoint_and_lowercase_userid(self):
        self.responses(self.token(), {"errcode": 0, "userid": "zhangsan", "errmsg": "ok"})
        self.assertEqual(self.client.get_identity("sensitive-code"), {
            "userid": "zhangsan", "corpid": "ww_test_corp",
        })
        token_request, identity_request = self.requests()
        self.assertEqual(token_request.path, "/cgi-bin/gettoken")
        self.assertEqual(identity_request.path, "/cgi-bin/auth/getuserinfo")
        self.assertEqual(parse_qs(identity_request.query)["code"], ["sensitive-code"])
        for request, call in zip(self.requests(), self.open.call_args_list):
            self.assertEqual((request.scheme, request.hostname), ("https", "qyapi.weixin.qq.com"))
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 10)

    def test_external_identity_and_other_corporation_are_rejected(self):
        for payload in ({"openid": "outside"}, {"userid": "zhangsan", "corpid": "another"}, {"UserId": "old-contract"}):
            with self.subTest(payload=payload):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, **payload})
                self.assert_safe_error(lambda: self.client.get_identity("sensitive-code"), "MEMBER_REJECTED")

    def test_member_returns_only_required_real_member_fields(self):
        self.responses(self.token(), {
            "errcode": 0, "userid": "zhangsan", "name": "张三", "status": 1,
            "mobile": "not-needed", "email": "private@example.test",
        })
        self.assertEqual(self.client.get_member("zhangsan"), {"userid": "zhangsan", "name": "张三", "status": 1})
        self.assertEqual(self.requests()[-1].path, "/cgi-bin/user/get")

    def test_member_inactive_missing_name_mismatch_and_hidden_are_rejected(self):
        invalid = [
            {"userid": "zhangsan", "name": "张三", "status": status}
            for status in (2, 4, 5, None, True)
        ] + [
            {"userid": "zhangsan", "status": 1},
            {"userid": "zhangsan", "name": "  ", "status": 1},
            {"userid": "other", "name": "张三", "status": 1},
            {"errcode": 60011, "errmsg": "raw upstream"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": 0, **payload})
                self.assert_safe_error(lambda: self.client.get_member("zhangsan"), "MEMBER_REJECTED")

    def test_connection_requires_matching_agent_id(self):
        self.responses(self.token(), {"errcode": 0, "agentid": 1000001, "name": "海趣 ERP"})
        self.assertEqual(self.client.check_connection(), {"agentid": 1000001, "name": "海趣 ERP"})
        self.assertEqual(self.requests()[-1].path, "/cgi-bin/agent/get")
        self.assertEqual(parse_qs(self.requests()[-1].query)["agentid"], ["1000001"])
        self.responses({"errcode": 0, "agentid": 1000002})
        self.assert_safe_error(self.client.check_connection, "CONFIGURATION_ERROR")

    def test_token_is_shared_between_instances_but_isolated_by_configuration(self):
        self.responses(self.token(), {"errcode": 0, "userid": "one"}, {"errcode": 0, "userid": "two"})
        self.client.get_identity("code-one")
        self.assertEqual(WeComClient(self.config).get_identity("code-two")["userid"], "two")
        for field, value in (("corp_id", "other-corp"), ("agent_id", 1000002), ("secret_ciphertext", "rotated-ciphertext")):
            config = SimpleNamespace(**vars(self.config))
            setattr(config, field, value)
            self.responses(self.token("another-token"), {"errcode": 0, "userid": "three"})
            self.assertEqual(WeComClient(config).get_identity("code-three")["userid"], "three")
        self.assertEqual(sum(item.path.endswith("/gettoken") for item in self.requests()), 4)

    def test_token_expires_before_official_expiry(self):
        with patch("time.time", return_value=1000):
            self.responses(self.token(), {"errcode": 0, "userid": "one"})
            self.client.get_identity("one")
        with patch("time.time", return_value=8130):
            self.responses({"errcode": 0, "userid": "two"})
            self.client.get_identity("two")
        with patch("time.time", return_value=8141):
            self.responses(self.token("refreshed"), {"errcode": 0, "userid": "three"})
            self.client.get_identity("three")
        self.assertEqual(sum(item.path.endswith("/gettoken") for item in self.requests()), 2)

    def test_only_invalid_token_errors_are_retried_once(self):
        for invalid_token in (40014, 42001):
            with self.subTest(code=invalid_token):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), {"errcode": invalid_token}, self.token("refreshed"), {"errcode": invalid_token, "errmsg": "raw upstream"})
                self.assert_safe_error(lambda: self.client.get_identity("sensitive-code"))
                self.assertEqual(len(self.requests()), 4)

    def test_token_refresh_retries_identity_with_new_token(self):
        self.responses(self.token(), {"errcode": 42001}, self.token("fresh-token"), {"errcode": 0, "userid": "zhangsan"})
        self.assertEqual(self.client.get_identity("sensitive-code")["userid"], "zhangsan")
        self.assertEqual(parse_qs(self.requests()[-1].query)["access_token"], ["fresh-token"])

    def test_network_failure_never_replays_oauth_code(self):
        for network_error in (TimeoutError("private-secret"), URLError("raw upstream private-access-token")):
            with self.subTest(error=type(network_error).__name__):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), network_error)
                self.assert_safe_error(lambda: self.client.get_identity("sensitive-code"))
                self.assertEqual(len(self.requests()), 2)

    def test_invalid_code_is_rejected_without_retry(self):
        self.responses(self.token(), {"errcode": 40029, "errmsg": "raw upstream sensitive-code"})
        self.assert_safe_error(lambda: self.client.get_identity("sensitive-code"), "MEMBER_REJECTED")
        self.assertEqual(len(self.requests()), 2)

    def test_http_error_and_redirect_do_not_expose_request_or_follow_redirect(self):
        for status in (302, 307, 500):
            with self.subTest(status=status):
                caches["wecom"].clear()
                self.open.reset_mock()
                error = HTTPError("https://qyapi.weixin.qq.com/?secret=private-secret", status, "raw upstream", {"Location": "https://outside.test"}, None)
                self.responses(error)
                self.assert_safe_error(self.client.check_connection)
                self.assertEqual(len(self.requests()), 1)
        handlers = self.build_opener.call_args.args
        redirect = next(handler for handler in handlers if hasattr(handler, "redirect_request"))
        self.assertIsNone(redirect.redirect_request(None, None, 302, "redirect", {}, "https://outside.test"))

    def test_malformed_json_oversized_and_wrong_type_responses_fail_closed(self):
        for payload in (b"not json private-secret", b"\xff", [], None, {"errcode": "0"}, {"errcode": True}, b" " * (1024 * 1024 + 1)):
            with self.subTest(payload_type=type(payload).__name__):
                caches["wecom"].clear()
                self.responses(payload)
                self.assert_safe_error(self.client.check_connection)

    def test_malformed_token_response_is_not_cached(self):
        for payload in ({"expires_in": 7200}, {"access_token": "private-access-token", "expires_in": 0}, {"access_token": "private-access-token", "expires_in": True}, {"access_token": 123, "expires_in": 7200}):
            with self.subTest(payload=payload):
                self.responses({"errcode": 0, **payload})
                self.assert_safe_error(self.client.check_connection)

    def test_invalid_configuration_fails_without_network(self):
        for field, value in (("corp_id", ""), ("agent_id", 0), ("agent_id", True), ("secret_ciphertext", "")):
            with self.subTest(field=field, value=value):
                config = SimpleNamespace(**vars(self.config))
                setattr(config, field, value)
                self.assert_safe_error(lambda: WeComClient(config).check_connection(), "CONFIGURATION_ERROR")
        self.assertEqual(len(self.requests()), 0)

    def test_invalid_inputs_fail_without_network(self):
        for value in ("", None, 123, "x" * 513):
            with self.subTest(value_type=type(value).__name__):
                self.assert_safe_error(lambda: self.client.get_identity(value), "MEMBER_REJECTED")
        for value in ("", None, "x" * 65):
            self.assert_safe_error(lambda: self.client.get_member(value), "MEMBER_REJECTED")
        self.assertEqual(len(self.requests()), 0)

    def test_cache_failure_is_safe_and_does_not_fall_back_to_uncached_requests(self):
        with patch.object(caches["wecom"], "get", side_effect=ConnectionError("private-secret")):
            self.assert_safe_error(self.client.check_connection)
        self.assertEqual(len(self.requests()), 0)

    def test_invalid_application_credentials_are_configuration_error(self):
        self.responses({"errcode": 40001, "errmsg": "raw upstream private-secret"})
        self.assert_safe_error(self.client.check_connection, "CONFIGURATION_ERROR")

    def test_real_urllib_redirect_chain_never_sends_second_request(self):
        self.client.opener = real_build_opener(*self.build_opener.call_args.args)
        response = addinfourl(io.BytesIO(b""), {"Location": "https://outside.test/collect"}, "https://qyapi.weixin.qq.com", code=302)
        response.msg = "Found"
        with patch("urllib.request.HTTPSHandler.https_open", return_value=response) as transport:
            self.assert_safe_error(self.client.check_connection)
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(response.closed)

    def test_invalid_unicode_input_and_response_fail_closed(self):
        self.assert_safe_error(lambda: self.client.get_identity("\ud800"), "MEMBER_REJECTED")
        self.responses(self.token(), {"errcode": 0, "userid": "\ud800"})
        self.assert_safe_error(lambda: self.client.get_identity("code"), "MEMBER_REJECTED")

    def test_deeply_nested_json_is_a_safe_upstream_failure(self):
        self.responses(b"[" * 2000 + b"]" * 2000)
        self.assert_safe_error(self.client.check_connection)

    def test_decryption_failure_is_safe_and_never_contacts_upstream(self):
        self.decrypt.side_effect = CredentialError()
        self.assert_safe_error(self.client.check_connection, "CONFIGURATION_ERROR")
        self.assertEqual(len(self.requests()), 0)

    def test_cache_write_failure_prevents_further_api_requests(self):
        self.responses(self.token())
        with patch.object(caches["wecom"], "set", side_effect=ConnectionError("private-access-token")):
            self.assert_safe_error(self.client.check_connection)
        self.assertEqual(len(self.requests()), 1)

    def test_numeric_string_agent_id_matches_real_configuration_contract(self):
        self.config.agent_id = "1000010"
        self.responses(self.token(), {"errcode": 0, "agentid": 1000010, "name": "海趣 ERP"})
        self.assertEqual(WeComClient(self.config).check_connection(), {"agentid": 1000010, "name": "海趣 ERP"})
        self.assertEqual(parse_qs(self.requests()[-1].query)["agentid"], ["1000010"])

    def test_agent_id_rejects_noncanonical_or_unbounded_values_before_network(self):
        for agent_id in (True, 1.0, "", " 1000010", "1000010 ", "01", "-1", "1e6", "١٢٣", "1" * 5000, 10 ** 30):
            with self.subTest(value_type=type(agent_id).__name__):
                self.config.agent_id = agent_id
                self.assert_safe_error(lambda: WeComClient(self.config).check_connection(), "CONFIGURATION_ERROR")
        self.assertEqual(len(self.requests()), 0)

    def test_member_id_comparison_ignores_case_and_preserves_official_id(self):
        self.responses(self.token(), {"errcode": 0, "userid": "ZhangSan", "name": "张三", "status": 1})
        self.assertEqual(self.client.get_member("zhangsan"), {"userid": "ZhangSan", "name": "张三", "status": 1})

    def test_known_configuration_failures_have_actionable_safe_messages(self):
        for official_code, keyword in ((60020, "可信 IP"), (40001, "Secret"), (40091, "Secret"), (40013, "CorpID"), (40056, "AgentID"), (50001, "可信域名"), (48001, "权限"), (48002, "权限"), (50003, "禁用"), (301002, "应用")):
            with self.subTest(official_code=official_code):
                caches["wecom"].clear()
                self.responses(self.token(), {"errcode": official_code, "errmsg": "raw upstream private-secret"})
                error = self.assert_safe_error(self.client.check_connection, "CONFIGURATION_ERROR")
                self.assertIn(keyword, error.message)

    def test_token_endpoint_trusted_ip_failure_is_actionable(self):
        self.responses({"errcode": 60020, "errmsg": "raw upstream private-secret"})
        error = self.assert_safe_error(self.client.check_connection, "CONFIGURATION_ERROR")
        self.assertIn("可信 IP", error.message)

    def test_member_outside_visible_scope_uses_safe_specific_reason(self):
        self.responses(self.token(), {"errcode": 60021, "errmsg": "raw upstream private-secret"})
        error = self.assert_safe_error(lambda: self.client.get_member("zhangsan"), "MEMBER_REJECTED")
        self.assertIn("可见范围", error.message)
