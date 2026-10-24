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

    def test_template_card_posts_visible_content_and_one_https_homepage(self):
        self.responses(self.token(), {"errcode": 0, "msgid": "card-id"})
        result = self.client.send_text_notice("Member.One", title="生产任务确认", body="任务单号：示例单号\n操作人：示例操作人",
                                             url="https://erp.example.com/")
        self.assertEqual(result, {"msgid": "card-id"})
        payload = json.loads(self.open.call_args.args[0].data)
        self.assertEqual(payload["msgtype"], "template_card")
        self.assertNotIn("text", payload)
        card = payload["template_card"]
        self.assertEqual(card["card_type"], "text_notice")
        self.assertEqual(card["main_title"]["title"], "生产任务确认")
        self.assertEqual(card["sub_title_text"], "任务单号：示例单号\n操作人：示例操作人")
        self.assertEqual(card["card_action"], {"type": 1, "url": "https://erp.example.com/"})
        self.assertEqual(card["jump_list"][0]["url"], card["card_action"]["url"])
        self.assertEqual(card["jump_list"][0]["title"], "查看详情")
        self.assertEqual(payload["enable_duplicate_check"], 1)

    def test_card_refreshes_only_rejected_token_and_keeps_payload_identical(self):
        self.responses(self.token(), {"errcode": 42001}, self.token("fresh"), {"errcode": 0, "msgid": "card-id"})
        self.client.send_text_notice("Member.One", title="标题", body="正文", url="https://erp.example.com/")
        posts = [call.args[0] for call in self.open.call_args_list if call.args[0].get_method() == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].data, posts[1].data)

    def test_invalid_card_inputs_never_reach_network(self):
        valid = {"user_id": "Member.One", "title": "标题", "body": "正文", "url": "https://erp.example.com/"}
        for changes in ({"user_id": "@all"}, {"user_id": "one|two"}, {"title": "长" * 201},
                        {"body": "长" * 683}, {"body": "\ud800"}, {"title": "\x00"},
                        {"url": "javascript:alert(1)"}, {"url": "https://user:pass@example.com/"},
                        {"url": "https://example.com/private"}, {"url": "https://example.com/?token=x"}):
            with self.subTest(fields=list(changes)):
                with self.assertRaises(WeComError):
                    self.client.send_text_notice(**{**valid, **changes})
        self.open.assert_not_called()

    def test_formal_card_links_to_the_personal_notification_without_test_label(self):
        url = "https://erp.example.com/?notification=00000000-0000-0000-0000-000000000001"
        self.responses(self.token(), {"errcode": 0, "msgid": "formal-card"})
        body = "单号：真实内容\n说明：" + "长" * 161
        self.client.send_text_notice("Member.One", title="正式通知", body=body, url=url, preview=False)
        card = json.loads(self.open.call_args.args[0].data)["template_card"]
        self.assertEqual(card["source"]["desc"], "HAIQU ERP")
        self.assertEqual(card["main_title"]["desc"], "业务通知")
        self.assertEqual(card["sub_title_text"], body)
        self.assertEqual(card["jump_list"], [{"type": 1, "title": "查看详情", "url": url}])

    def test_formal_card_rejects_missing_invalid_and_multiple_notification_ids(self):
        for query in ("", "?notification=bad", "?notification=", "?next=https://external.example/",
                      "?notification=00000000-0000-0000-0000-000000000001&notification=duplicate"):
            with self.subTest(query=query), self.assertRaises(WeComError):
                self.client.send_text_notice("Member.One", title="标题", body="正文",
                    url="https://erp.example.com/" + query, preview=False)
        self.open.assert_not_called()

    def test_card_timeout_is_uncertain_and_invalid_recipient_is_failed(self):
        from apps.wecom.client import WeComSendUncertain
        for result, error_type in ((TimeoutError("private"), WeComSendUncertain),
                                   ({"errcode": 0, "msgid": "card-id", "invaliduser": "Member.One"}, WeComError)):
            with self.subTest(error=error_type.__name__):
                caches["wecom"].clear(); self.open.reset_mock()
                self.responses(self.token(), result)
                with self.assertRaises(error_type):
                    self.client.send_text_notice("Member.One", title="标题", body="正文", url="https://erp.example.com/")
                self.assertEqual(len(self.open.call_args_list), 2)
