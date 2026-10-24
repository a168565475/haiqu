"""admin 仅收站内通知；隔离数据库测试不代表真实企业微信发送验收。"""
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings

from apps.wecom import notification_services as services
from apps.wecom.models import NotificationDelivery, WeComBinding

from .test_notifications import NotificationFixture, SETTINGS


@override_settings(**SETTINGS)
class AdminInAppRegistrationTests(NotificationFixture, TestCase):
    def test_only_exact_superuser_admin_skips_wecom_channel(self):
        cases = [
            ("admin", True, "SKIPPED"),
            ("other-admin", True, "PENDING"),
            ("admin", False, "PENDING"),
        ]
        for index, (username, is_superuser, expected_status) in enumerate(cases):
            with self.subTest(username=username, is_superuser=is_superuser):
                self.member.user.username = username
                self.member.user.is_superuser = is_superuser
                self.member.user.save(update_fields=["username", "is_superuser"])
                event = self.register(idempotency_key=f"admin-channel-{index}")
                recipient = event.recipients.get()
                self.assertEqual(recipient.employee_id, self.member.pk)
                self.assertEqual(recipient.deliveries.count(), 2)
                self.assertIsNone(recipient.read_at)
                in_app = recipient.deliveries.get(channel="IN_APP")
                self.assertEqual(in_app.status, "ACCEPTED")
                self.assertIsNotNone(in_app.finished_at)
                wecom = recipient.deliveries.get(channel="WECOM")
                self.assertEqual(wecom.status, expected_status)
                self.assertEqual(wecom.attempt_count, 0)
                self.assertIsNone(wecom.last_attempt_at)
                self.assertEqual(wecom.error_code, "ADMIN_IN_APP_ONLY" if expected_status == "SKIPPED" else "")
                if expected_status == "SKIPPED":
                    self.assertIsNotNone(wecom.finished_at)
                else:
                    self.assertIsNone(wecom.finished_at)
        self.assertFalse(WeComBinding.objects.filter(employee=self.member).exists())


@override_settings(**SETTINGS)
class AdminInAppLegacyDeliveryTests(NotificationFixture, TransactionTestCase):
    def test_old_admin_pending_is_skipped_without_send_and_keeps_in_app_and_binding(self):
        self.member.user.username = "admin"
        self.member.user.is_superuser = True
        self.member.user.save(update_fields=["username", "is_superuser"])
        config, binding = self.configure_wecom()
        config.enabled = False
        config.save(update_fields=["enabled"])
        binding_before = WeComBinding.objects.filter(pk=binding.pk).values().get()
        event = self.register()
        recipient = event.recipients.get()
        # 表示变更前已经排队的历史记录；保留实际业务对象和接收人资格。
        NotificationDelivery.objects.filter(recipient=recipient, channel="WECOM").update(
            status="PENDING", error_code="", finished_at=None,
        )
        pending = NotificationDelivery.objects.get(recipient=recipient, channel="WECOM")
        with patch("apps.wecom.notification_services.WeComClient.send_text_notice") as sender:
            result = services.process_delivery(pending)
            replay = services.process_delivery(pending)
        sender.assert_not_called()
        self.assertEqual((result.status, result.error_code, result.attempt_count),
                         ("SKIPPED", "ADMIN_IN_APP_ONLY", 0))
        self.assertIsNotNone(result.finished_at)
        self.assertIsNone(result.last_attempt_at)
        self.assertEqual((replay.status, replay.error_code, replay.attempt_count, replay.finished_at),
                         (result.status, result.error_code, result.attempt_count, result.finished_at))
        self.assertEqual(NotificationDelivery.objects.get(recipient=recipient, channel="IN_APP").status, "ACCEPTED")
        self.assertEqual(event.recipients.count(), 1)
        recipient.refresh_from_db()
        self.assertEqual(recipient.employee_id, self.member.pk)
        self.assertIsNone(recipient.read_at)
        self.assertEqual(WeComBinding.objects.filter(pk=binding.pk).values().get(), binding_before)
