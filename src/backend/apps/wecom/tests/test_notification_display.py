from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from apps.wecom.notification_catalog import get_event
from apps.wecom.notification_display import format_notification_value, render_notification_template, saved_notification_body
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import _render


@override_settings(TIME_ZONE="Asia/Shanghai")
class NotificationTimeDisplayTests(SimpleTestCase):
    def test_explicit_time_variables_convert_offset_and_cross_day(self):
        cases = [
            ("2026-11-02T00:50:49.571017+00:00", "2026-11-02 08:50:49"),
            ("2026-11-02T20:50:49Z", "2026-11-03 04:50:49"),
            ("2026-11-02T08:50:49+08:00", "2026-11-02 08:50:49"),
        ]
        for name in ("occurred_at", "confirmed_at"):
            for original, expected in cases:
                with self.subTest(name=name, original=original):
                    self.assertEqual(format_notification_value(name, original), expected)

    def test_local_naive_date_invalid_and_out_of_range_values_are_preserved(self):
        for value in ("2026-11-02 08:50:49", "2026-11-02T08:50:49", "2026-11-02", "示例时间",
                      "not-a-date", "2026-13-02T00:00:00Z", "9999-12-31T23:59:59-12:00"):
            with self.subTest(value=value):
                self.assertEqual(format_notification_value("occurred_at", value), value)

    def test_new_render_formats_only_registered_time_fields_without_mutating_context(self):
        stamp = "2026-11-02T00:50:49.571017+00:00"
        context = {"occurred_at": stamp, "object_version": stamp, "reason_summary": stamp, "receipt_date": "2026-11-02"}
        before = deepcopy(context)
        template = "时间：{{occurred_at}}\n版本：{{object_version}}\n说明：{{reason_summary}}\n日期：{{receipt_date}}"
        rendered = _render(template, tuple(context), context)
        self.assertEqual(rendered, f"时间：2026-11-02 08:50:49\n版本：{stamp}\n说明：{stamp}\n日期：2026-11-02")
        self.assertEqual(context, before)

    def test_legacy_delivery_matching_can_still_use_raw_values(self):
        definition = get_event("MATERIAL_RECEIPT_RECORDED")
        context = {"document_no": "DH-1", "operator": "操作人", "occurred_at": "2026-11-02T00:50:49.571017+00:00"}
        legacy = render_notification_template(definition["legacy_default_body"], context, format_times=False)
        self.assertEqual(_render(definition["legacy_default_body"], definition["allowed_variables"], context, format_times=False), legacy)
        self.assertIn("2026-11-02 08:50:49", _render(definition["default_body"], definition["allowed_variables"], context))

    def test_saved_default_and_legacy_bodies_format_only_template_time_positions(self):
        definition = get_event("BOM_CONFIRMED")
        stamp = "2026-11-02T00:50:49.571017+00:00"
        context = {"document_no": "BOM-1", "operator": "操作人", "product_name": "产品", "occurred_at": stamp, "object_version": stamp}
        before = deepcopy(context)
        for template in (definition["default_body"], definition["legacy_default_body"]):
            with self.subTest(template=template):
                body = render_notification_template(template, context, format_times=False)
                shown = saved_notification_body(body, definition, context)
                self.assertIn("2026-11-02 08:50:49", shown)
                self.assertEqual(shown.count(stamp), 1)
                self.assertEqual(body.count(stamp), 2)
        self.assertEqual(context, before)

    def test_saved_custom_body_or_missing_context_stays_unchanged(self):
        definition = get_event("MATERIAL_RECEIPT_RECORDED")
        context = {"document_no": "DH-1", "operator": "操作人", "occurred_at": "2026-11-02T00:50:49Z"}
        body = render_notification_template(definition["default_body"], context, format_times=False)
        for text, values in ((body + "\n自定义说明", context), ("备注：" + context["occurred_at"], context), (body, {}), (body, None)):
            with self.subTest(text=text, context=values):
                self.assertEqual(saved_notification_body(text, definition, values), text)

    def test_accessible_payload_formats_read_only_body(self):
        definition = get_event("PRODUCTION_TASK_CONFIRMED")
        context = {"document_no": "HT1", "operator": "操作人", "occurred_at": "2026-11-02T00:50:49Z"}
        original = render_notification_template(definition["default_body"], context, format_times=False)
        event = SimpleNamespace(event_code="PRODUCTION_TASK_CONFIRMED", rendered_title="生产任务确认", rendered_body=original,
                                target={"key": "production-task-detail"}, context=context)
        recipient = SimpleNamespace(pk=uuid4(), event=event, created_at=None, read_at=None)
        with patch("apps.wecom.notification_selectors.content_accessible", return_value=True), \
                patch("apps.wecom.notification_selectors.delivery_statuses", return_value={}):
            payload = recipient_payload(recipient, object())
        self.assertIn("2026-11-02 08:50:49", payload["body"])
        self.assertEqual(event.rendered_body, original)
        self.assertEqual(context["occurred_at"], "2026-11-02T00:50:49Z")
        self.assertTrue(payload["target_accessible"])

    def test_inaccessible_payload_does_not_format_or_expose_original_body(self):
        event = SimpleNamespace(event_code="PRODUCTION_TASK_CONFIRMED", rendered_title="原文", rendered_body="秘密内容",
                                target={"key": "production-task-detail"}, context={})
        recipient = SimpleNamespace(pk=uuid4(), event=event, created_at=None, read_at=None)
        with patch("apps.wecom.notification_selectors.content_accessible", return_value=False), \
                patch("apps.wecom.notification_selectors.delivery_statuses", return_value={}), \
                patch("apps.wecom.notification_selectors.saved_notification_body") as formatter:
            payload = recipient_payload(recipient, object())
        formatter.assert_not_called()
        self.assertEqual(payload["body"], "该业务内容当前不可访问。")
        self.assertIsNone(payload["target"])
