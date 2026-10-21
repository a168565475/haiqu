import json
from http.client import IncompleteRead
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from apps.wecom.client import WeComClient, WeComError
from .test_client import Response


@override_settings(CACHES={"wecom": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "message-client-tests"}})
class WeComMessageClientTests(SimpleTestCase):
    def setUp(self):
        caches["wecom"].clear()
        self.addCleanup(caches["wecom"].clear)
        self.enterContext(patch("apps.wecom.client.decrypt_secret", return_value="test-private-secret"))
        self.open = self.enterContext(patch("apps.wecom.client.build_opener")).return_value.open
        self.client = WeComClient(SimpleNamespace(corp_id="ww_test", agent_id="1000010", secret_ciphertext="test-encrypted"))

    def responses(self, *responses):
        self.open.side_effect = [item if isinstance(item, Exception) else Response(item) for item in responses]

    def token(self, value="test-private-token"):
        return {"errcode": 0, "access_token": value, "expires_in": 7200}

    def test_send_posts_one_recipient_and_enables_provider_duplicate_check(self):
        self.responses(self.token(), {"errcode": 0, "msgid": "message-id"})
        self.assertEqual(self.client.send_text("Member.One", "内容\n下一行"), {"msgid": "message-id"})
        request = self.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(urlsplit(request.full_url).path, "/cgi-bin/message/send")
        payload = json.loads(request.data)
        self.assertEqual(payload, {"touser": "Member.One", "msgtype": "text", "agentid": 1000010,
                                  "text": {"content": "内容\n下一行"}, "enable_duplicate_check": 1,
                                  "duplicate_check_interval": 1800})

    def test_expired_token_retries_only_once_with_identical_json(self):
        for code in (40014, 42001):
            with self.subTest(code=code):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), {"errcode": code}, self.token("refreshed"), {"errcode": 0, "msgid": "id"})
                self.assertEqual(self.client.send_text("Member.One", "消息"), {"msgid": "id"})
                posts = [call.args[0] for call in self.open.call_args_list if call.args[0].get_method() == "POST"]
                self.assertEqual(len(posts), 2)
                self.assertEqual(posts[0].data, posts[1].data)

    def test_repeated_token_rejection_stops_without_third_send(self):
        self.responses(self.token(), {"errcode": 42001}, self.token("fresh"), {"errcode": 42001, "errmsg": "private-upstream"})
        with self.assertRaises(WeComError) as caught:
            self.client.send_text("Member.One", "消息")
        self.assertEqual(len(self.open.call_args_list), 4)
        self.assertNotIn("private-upstream", str(caught.exception))

    def test_post_network_http_or_malformed_response_is_uncertain_without_retry(self):
        from apps.wecom.client import WeComSendUncertain
        failures = [TimeoutError("test-private-token"), URLError("private-upstream"), IncompleteRead(b"partial"),
                    HTTPError("https://example.invalid/?token=test-private-token", 502, "private-upstream", {}, None),
                    b"bad json", {"errcode": 0}, {"errcode": 0, "msgid": "id", "invaliduser": []}, {"errcode": "0"}]
        for result in failures:
            with self.subTest(result=type(result).__name__):
                caches["wecom"].clear()
                self.open.reset_mock()
                self.responses(self.token(), result)
                with self.assertRaises(WeComSendUncertain) as caught:
                    self.client.send_text("Member.One", "消息")
                self.assertEqual(len(self.open.call_args_list), 2)
                self.assertNotIn("private", str(caught.exception))

    def test_token_fetch_failure_is_confirmed_no_message_sent(self):
        from apps.wecom.client import WeComSendUncertain
        self.responses(TimeoutError("private-token"))
        with self.assertRaises(WeComError) as caught:
            self.client.send_text("Member.One", "消息")
        self.assertNotIsInstance(caught.exception, WeComSendUncertain)
        self.assertEqual(len(self.open.call_args_list), 1)
        self.assertEqual(self.open.call_args.args[0].get_method(), "GET")

    def test_invalid_or_unlicensed_recipient_is_not_reported_accepted(self):
        for payload in ({"errcode": 81013}, {"errcode": 0, "invaliduser": "member.one", "msgid": "id"},
                        {"errcode": 0, "unlicenseduser": "MEMBER.ONE", "msgid": "id"}):
            with self.subTest(payload=payload):
                caches["wecom"].clear()
                self.responses(self.token(), {**payload, "errmsg": "private-upstream"})
                with self.assertRaises(WeComError) as caught:
                    self.client.send_text("Member.One", "消息")
                self.assertEqual(caught.exception.code, "RECIPIENT_REJECTED")
                self.assertNotIn("private-upstream", str(caught.exception))

    def test_rejects_broadcast_recipient_and_oversized_utf8_before_network(self):
        for user_id, body in (("@all", "消息"), ("one|two", "消息"), ("Member.One", "中" * 683), ("Member.One", " ")):
            with self.subTest(user_id=user_id):
                with self.assertRaises(WeComError):
                    self.client.send_text(user_id, body)
        self.open.assert_not_called()
