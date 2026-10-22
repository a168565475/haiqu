"""常驻投递隔离测试；网络模拟不代表真实企业微信送达。"""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.wecom import notification_services
from apps.wecom.client import WeComError
from apps.wecom.models import NotificationDelivery, WeComConfig
from apps.wecom.tests.test_notifications import NotificationFixture, SETTINGS


COMMAND = "apps.wecom.management.commands.process_notification_deliveries"


class NotificationWorkerArgumentTests(SimpleTestCase):
    def test_watch_requires_execute_and_rejects_targeted_retries(self):
        cases = [{"watch": True}, {"watch": True, "execute": True,
            "delivery_id": ["12345678-1234-1234-1234-123456789012"]},
            {"watch": True, "execute": True, "retry_failed": True},
            {"watch": True, "execute": True, "retry_uncertain": True}]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command("process_notification_deliveries", stdout=StringIO(), **options)

    def test_interval_rejects_invalid_bounds_and_types(self):
        for interval in [0, -1, 3601, True, 1.5]:
            with self.subTest(interval=interval), self.assertRaises(CommandError):
                call_command("process_notification_deliveries", interval=interval, stdout=StringIO())


@override_settings(**SETTINGS)
class NotificationWorkerTests(NotificationFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.config, self.binding = self.configure_wecom()
        self.event = self.register()
        self.delivery = NotificationDelivery.objects.get(recipient__event=self.event, channel="WECOM")

    def run_one_cycle(self, **options):
        output = StringIO()
        with patch(f"{COMMAND}.time.sleep", side_effect=KeyboardInterrupt):
            call_command("process_notification_deliveries", execute=True, watch=True,
                stdout=output, **options)
        return output.getvalue()

    def test_missing_disabled_or_incomplete_configuration_preserves_pending(self):
        for state in ["disabled", "incomplete", "missing"]:
            with self.subTest(state=state):
                if state == "missing":
                    WeComConfig.objects.filter(pk=self.config.pk).delete()
                else:
                    WeComConfig.objects.filter(pk=self.config.pk).update(
                        enabled=state != "disabled", secret_ciphertext="" if state == "incomplete" else self.config.secret_ciphertext)
                with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
                    output = self.run_one_cycle()
                self.delivery.refresh_from_db()
                self.assertEqual((self.delivery.status, self.delivery.attempt_count), ("PENDING", 0))
                self.assertIsNone(self.delivery.last_attempt_at)
                self.assertIn("WAITING_CONFIGURATION", output)
                sender.assert_not_called()

    def test_configuration_saved_while_running_resumes_existing_pending(self):
        WeComConfig.objects.filter(pk=self.config.pk).update(enabled=False)
        sleeps = []

        def pause(interval):
            sleeps.append(interval)
            if len(sleeps) == 1:
                WeComConfig.objects.filter(pk=self.config.pk).update(enabled=True)
            else:
                raise KeyboardInterrupt

        output = StringIO()
        with patch(f"{COMMAND}.time.sleep", side_effect=pause), patch(
            "apps.wecom.notification_services.WeComClient.send_text", return_value={"msgid": "worker-resumed"}
        ) as sender:
            call_command("process_notification_deliveries", execute=True, watch=True, interval=1, stdout=output)
        self.delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.attempt_count), ("ACCEPTED", 1))
        self.assertEqual(sleeps, [1, 1])
        self.assertIn("CONFIGURATION_READY", output.getvalue())
        sender.assert_called_once()

    def test_failed_record_does_not_stop_batch_or_retry_old_results(self):
        other = self.register(idempotency_key="worker-second-pending")
        second = NotificationDelivery.objects.get(recipient__event=other, channel="WECOM")
        preserved = []
        for status in ["FAILED", "UNCERTAIN", "ACCEPTED"]:
            event = self.register(idempotency_key=f"worker-existing-{status}")
            delivery = NotificationDelivery.objects.get(recipient__event=event, channel="WECOM")
            NotificationDelivery.objects.filter(pk=delivery.pk).update(status=status, attempt_count=1)
            preserved.append((delivery, status))
        with patch("apps.wecom.notification_services.WeComClient.send_text",
            side_effect=[WeComError("RECIPIENT_REJECTED", "隔离测试拒绝"), {"msgid": "worker-second"}]
        ) as sender:
            self.run_one_cycle()
        self.delivery.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((self.delivery.status, second.status), ("FAILED", "ACCEPTED"))
        self.assertEqual(sender.call_count, 2)
        for delivery, status in preserved:
            delivery.refresh_from_db()
            self.assertEqual((delivery.status, delivery.attempt_count), (status, 1))

    def test_abandoned_processing_becomes_uncertain_without_resend(self):
        NotificationDelivery.objects.filter(pk=self.delivery.pk).update(
            status="PROCESSING", attempt_count=1, last_attempt_at=timezone.now() - timedelta(minutes=6))
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            self.run_one_cycle(recover_processing=True)
        self.delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.attempt_count, self.delivery.error_code),
            ("UNCERTAIN", 1, "PROCESS_INTERRUPTED"))
        sender.assert_not_called()

    def test_no_recipient_event_is_not_rebuilt_after_rule_changes(self):
        NotificationDelivery.objects.filter(pk=self.delivery.pk).update(status="ACCEPTED")
        self.rule.recipient_role_codes = ["UNASSIGNED_WORKER_ROLE"]
        self.rule.save(update_fields=["recipient_role_codes"])
        event = self.register(idempotency_key="worker-no-recipient")
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.rule.recipient_role_codes = [self.role.role_code]
        self.rule.save(update_fields=["recipient_role_codes"])
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            self.run_one_cycle()
        event.refresh_from_db()
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.assertFalse(event.recipients.exists())
        sender.assert_not_called()

    def test_configuration_changed_after_poll_preserves_pending_before_send(self):
        WeComConfig.objects.filter(pk=self.config.pk).update(enabled=False)
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            deferred = notification_services.process_delivery(self.delivery, defer_unconfigured=True)
            self.assertEqual((deferred.status, deferred.attempt_count), ("PENDING", 0))
            failed = notification_services.process_delivery(deferred)
        self.assertEqual((failed.status, failed.error_code), ("FAILED", "CONFIGURATION_ERROR"))
        sender.assert_not_called()

    def test_unexpected_failure_is_reported_and_propagates(self):
        output = StringIO()
        with patch(f"{COMMAND}.process_delivery", side_effect=RuntimeError("worker-test-error")), \
                self.assertRaisesRegex(RuntimeError, "worker-test-error"):
            call_command("process_notification_deliveries", execute=True, watch=True, stdout=output)
        self.assertIn('"execution_finished": false', output.getvalue())
        self.delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.attempt_count), ("PENDING", 0))
