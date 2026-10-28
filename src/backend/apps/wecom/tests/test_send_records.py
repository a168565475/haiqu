"""隔离数据库中的只读记录接口测试，不调用企业微信或创建真实业务单据。"""
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.organizations.models import Employee
from apps.wecom.models import (
    NotificationDelivery, NotificationEvent, NotificationPreviewAttempt, NotificationRecipient,
    WeComBinding, WeComMessageAttempt, WeComMessageTemplate,
)
from apps.wecom.notification_catalog import get_event
from apps.wecom.send_record_selectors import send_record_payload, send_records_queryset
from .test_notifications import employee, grant_role


URL = "/api/v1/notifications/send-records/"
EVENT_CODE = "PRODUCTION_TASK_CONFIRMED"
SOURCES = ("BUSINESS", "RULE_PREVIEW", "MESSAGE_TEST")


class SendRecordAnonymousTests(SimpleTestCase):
    def test_all_sources_require_login(self):
        for source in SOURCES:
            with self.subTest(source=source):
                self.assertEqual(APIClient().get(URL, {"source": source}).status_code, 401)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True, SALES_ACCESS_ENABLED=True)
class SendRecordTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", None)
        self.actor = Employee.objects.create(user=self.admin, employee_code="RECORD_ADMIN", display_name="记录管理员")
        self.member = employee("RECORD_MEMBER")
        self.binding = WeComBinding.objects.create(employee=self.member, corp_id="record-corp",
            user_id="Record.Member", member_name="当前企微姓名", source="MANUAL")
        self.template = WeComMessageTemplate.objects.create(name="当前模板名称", body="当前模板正文",
            updated_by_employee=self.actor)
        self.client = APIClient()
        self.client.force_login(self.admin)

    def business_record(self, **changes):
        event = NotificationEvent.objects.create(event_code=EVENT_CODE, idempotency_key=str(uuid4()),
            object_type="production_tasks.ProductionTask", object_id=str(uuid4()), rule_version=1,
            template_name="历史通知模板", rendered_title="历史业务标题", rendered_body="历史业务内容\n第二行")
        recipient = NotificationRecipient.objects.create(event=event, employee=self.member,
            employee_name="通知时姓名", scope="ROLE_MEMBERS")
        return NotificationDelivery.objects.create(recipient=recipient, channel="WECOM",
            idempotency_key=str(uuid4()), **changes)

    def preview_record(self, actor=None, **changes):
        return NotificationPreviewAttempt.objects.create(preview_id=uuid4(), event_code=EVENT_CODE,
            requested_by_employee=actor or self.actor, binding=self.binding, request_hash="preview-request",
            payload_hash="preview-payload", recipient_name="试发时姓名", corp_id=self.binding.corp_id,
            agent_id="1", user_id=self.binding.user_id, rendered_title="历史试发标题",
            rendered_body="历史试发内容\n第二行", **changes)

    def message_record(self, **changes):
        return WeComMessageAttempt.objects.create(template=self.template, binding=self.binding,
            requested_by_employee=self.actor, idempotency_key=uuid4(), request_hash="message-request",
            payload_hash="message-payload", template_name="历史消息模板", recipient_name="测试时姓名",
            corp_id=self.binding.corp_id, agent_id="1", user_id=self.binding.user_id,
            rendered_body="历史测试内容\n第二行", **changes)

    def test_default_source_contains_only_wecom_business_records_and_saved_content(self):
        sent_at, finished_at = timezone.now() - timedelta(minutes=2), timezone.now() - timedelta(minutes=1)
        record = self.business_record(status="ACCEPTED", attempt_count=2,
            last_attempt_at=sent_at, finished_at=finished_at)
        NotificationDelivery.objects.create(recipient=record.recipient, channel="IN_APP",
            idempotency_key=str(uuid4()), status="ACCEPTED")
        self.preview_record(status="ACCEPTED")
        self.message_record(status="ACCEPTED")
        self.member.display_name = "改名后的员工"
        self.member.save(update_fields=["display_name"])

        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["count"], response.data["page"], response.data["page_size"]), (1, 1, 20))
        row = response.data["data"][0]
        self.assertEqual((row["id"], row["source"], row["recipient_name"]),
                         (str(record.pk), "BUSINESS", "通知时姓名"))
        self.assertEqual((row["event_code"], row["event_name"]), (EVENT_CODE, get_event(EVENT_CODE)["display_name"]))
        self.assertEqual((row["title"], row["body"]), ("历史业务标题", "历史业务内容\n第二行"))
        self.assertEqual((row["status"], row["attempt_count"]), ("ACCEPTED", 2))
        self.assertEqual(parse_datetime(row["sent_at"]), sent_at)
        self.assertEqual(parse_datetime(row["finished_at"]), finished_at)
        self.assertNotIn("user_id", row)
        self.assertNotIn("corp_id", row)
        self.assertIn("no-store", response["Cache-Control"])

    def test_unsent_and_skipped_business_records_have_no_send_time(self):
        pending = self.business_record()
        skipped = self.business_record(status="SKIPPED", error_code="ADMIN_IN_APP_ONLY", finished_at=timezone.now())
        rows = {row["id"]: row for row in self.client.get(URL).data["data"]}
        for record in (pending, skipped):
            self.assertIsNone(rows[str(record.pk)]["sent_at"])
            self.assertEqual(rows[str(record.pk)]["attempt_count"], 0)
        self.assertEqual(rows[str(skipped.pk)]["error_code"], "ADMIN_IN_APP_ONLY")

    def test_manual_sources_return_their_saved_content_and_request_time(self):
        preview = self.preview_record(status="ACCEPTED", finished_at=timezone.now())
        message = self.message_record(status="FAILED", error_code="RECIPIENT_REJECTED", finished_at=timezone.now())
        for source, record, name, title, body in (
            ("RULE_PREVIEW", preview, "试发时姓名", "历史试发标题", "历史试发内容\n第二行"),
            ("MESSAGE_TEST", message, "测试时姓名", "历史消息模板", "历史测试内容\n第二行"),
        ):
            with self.subTest(source=source):
                response = self.client.get(URL, {"source": source})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["count"], 1)
                row = response.data["data"][0]
                self.assertEqual((row["id"], row["recipient_name"], row["title"], row["body"]),
                                 (str(record.pk), name, title, body))
                self.assertEqual((row["status"], row["error_code"], row["attempt_count"]),
                                 (record.status, record.error_code, 1))
                self.assertEqual(parse_datetime(row["sent_at"]), record.created_at)
                self.assertEqual(parse_datetime(row["finished_at"]), record.finished_at)
        row = self.client.get(URL, {"source": "MESSAGE_TEST"}).data["data"][0]
        self.assertEqual((row["event_code"], row["event_name"]), ("", "人工消息测试"))

    def test_source_permissions_cannot_be_bypassed_by_switching_source(self):
        self.business_record()
        self.preview_record()
        self.message_record()
        notification_manager = employee("RECORD_NOTIFICATION_MANAGER")
        grant_role(notification_manager, "RECORD_NOTIFY_MANAGE", "access_control.manage_notifications")
        wecom_manager = employee("RECORD_WECOM_MANAGER")
        grant_role(wecom_manager, "RECORD_WECOM_MANAGE", "access_control.manage_wecom")
        both_manager = employee("RECORD_BOTH_MANAGER")
        grant_role(both_manager, "RECORD_BOTH_NOTIFY", "access_control.manage_notifications")
        grant_role(both_manager, "RECORD_BOTH_WECOM", "access_control.manage_wecom")
        for member, expected in (
            (self.member, (403, 403, 403)),
            (notification_manager, (200, 403, 403)),
            (wecom_manager, (403, 403, 200)),
            (both_manager, (200, 403, 200)),
        ):
            self.client.force_login(member.user)
            for source, status in zip(SOURCES, expected):
                with self.subTest(member=member.employee_code, source=source):
                    response = self.client.get(URL, {"source": source})
                    data = response.json()
                    self.assertEqual(response.status_code, status, data)
                    if status == 403:
                        self.assertNotIn("data", data)
                        self.assertNotIn("历史", response.content.decode())

    def test_rule_previews_remain_limited_to_requesting_employee(self):
        mine = self.preview_record()
        another = employee("RECORD_OTHER_SENDER")
        theirs = self.preview_record(actor=another)
        response = self.client.get(URL, {"source": "RULE_PREVIEW"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(mine.pk))
        self.assertEqual(list(send_records_queryset("RULE_PREVIEW", another.pk).values_list("pk", flat=True)),
                         [theirs.pk])

    def test_missing_or_inactive_employee_cannot_read_records(self):
        no_employee = get_user_model().objects.create_superuser("record-no-employee", "", None)
        self.client.force_login(no_employee)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.actor.archived_at = timezone.now()
        self.actor.save(update_fields=["archived_at"])
        self.client.force_login(self.admin)
        for source in SOURCES:
            with self.subTest(source=source):
                self.assertEqual(self.client.get(URL, {"source": source}).status_code, 403)

    def test_business_status_filter_and_stable_newest_first_pagination(self):
        created_at = timezone.now() - timedelta(minutes=5)
        first = self.business_record(id=UUID(int=1), status="FAILED", error_code="NO_WECOM_BINDING")
        second = self.business_record(id=UUID(int=2), status="FAILED", error_code="RECIPIENT_NOT_ELIGIBLE")
        latest = self.business_record(status="ACCEPTED")
        NotificationDelivery.objects.filter(pk__in=[first.pk, second.pk]).update(created_at=created_at)
        response = self.client.get(URL, {"page_size": 1})
        self.assertEqual(response.data["data"][0]["id"], str(latest.pk))
        pages = [self.client.get(URL, {"status": "FAILED", "page_size": 1, "page": page}).data
                 for page in (1, 2, 3)]
        self.assertEqual([page["count"] for page in pages], [2, 2, 2])
        self.assertEqual([pages[0]["data"][0]["id"], pages[1]["data"][0]["id"]], [str(second.pk), str(first.pk)])
        self.assertEqual(pages[2]["data"], [])

    def test_manual_timeout_status_filter_matches_display_without_mutating_records(self):
        for source, factory, model in (
            ("RULE_PREVIEW", self.preview_record, NotificationPreviewAttempt),
            ("MESSAGE_TEST", self.message_record, WeComMessageAttempt),
        ):
            with self.subTest(source=source):
                old, current = factory(), factory()
                model.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=2))
                uncertain = self.client.get(URL, {"source": source, "status": "UNCERTAIN"}).data
                processing = self.client.get(URL, {"source": source, "status": "PROCESSING"}).data
                self.assertEqual(uncertain["count"], 1)
                self.assertEqual((uncertain["data"][0]["id"], uncertain["data"][0]["status"]),
                                 (str(old.pk), "UNCERTAIN"))
                self.assertEqual(processing["count"], 1)
                self.assertEqual(processing["data"][0]["id"], str(current.pk))
                old.refresh_from_db()
                self.assertEqual(old.status, "PROCESSING")

    def test_invalid_source_status_and_page_parameters_are_rejected(self):
        for params in (
            {"source": "ALL"}, {"status": "DELIVERED"}, {"page": 0}, {"page": "invalid"},
            {"page_size": 0}, {"page_size": 51}, {"source": "RULE_PREVIEW", "status": "PENDING"},
            {"source": "MESSAGE_TEST", "status": "SKIPPED"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(URL, params).status_code, 400)

    def test_unknown_historical_event_code_is_displayed_without_failing(self):
        record = self.business_record()
        NotificationEvent.objects.filter(pk=record.recipient.event_id).update(event_code="RETIRED_EVENT")
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"][0]["event_name"], "RETIRED_EVENT")

    def test_listing_neither_writes_records_nor_sends_messages(self):
        self.business_record()
        self.preview_record()
        self.message_record()
        with patch("apps.wecom.client.WeComClient._send_message") as send:
            with CaptureQueriesContext(connection) as queries:
                for source in SOURCES:
                    response = self.client.get(URL, {"source": source})
                    self.assertEqual(response.status_code, 200, response.data)
            send.assert_not_called()
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(writes, [])

    def test_business_rows_load_related_content_in_one_page_query(self):
        for _ in range(3):
            self.business_record()
        with self.assertNumQueries(2):
            queryset = send_records_queryset("BUSINESS", self.actor.pk)
            rows = [send_record_payload(record, "BUSINESS") for record in queryset[:20]]
            count = queryset.count()
        self.assertEqual((len(rows), count), (3, 3))

    def test_empty_sources_return_empty_pages(self):
        for source in SOURCES:
            with self.subTest(source=source):
                response = self.client.get(URL, {"source": source})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, {"data": [], "count": 0, "page": 1, "page_size": 20})

    def test_manual_records_report_unavailable_when_source_schema_is_missing(self):
        for source, selector in (
            ("RULE_PREVIEW", "apps.wecom.notification_preview_selectors.schema_ready"),
            ("MESSAGE_TEST", "apps.wecom.message_selectors.schema_is_ready"),
        ):
            with self.subTest(source=source), patch(selector, return_value=False):
                self.assertEqual(self.client.get(URL, {"source": source}).status_code, 503)
