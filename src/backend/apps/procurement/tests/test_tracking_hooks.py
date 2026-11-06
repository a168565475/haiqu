from unittest.mock import patch

from django.db import transaction
from django.db.models.signals import post_save
from django.test import SimpleTestCase, TestCase, override_settings

from apps.production_tasks.models import ProductionTask

from . import test_purchase_order_api as order_tests


class TrackingSignalRegistrationTests(SimpleTestCase):
    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_task_signal_queues_refresh_without_database_read(self):
        with patch("django.db.transaction.on_commit") as on_commit:
            post_save.send(sender=ProductionTask, instance=ProductionTask(), created=False, raw=False, using="default")
        on_commit.assert_called_once()
        self.assertIs(on_commit.call_args.kwargs["robust"], True)

    @override_settings(PURCHASE_TRACKING_ENABLED=False)
    def test_disabled_feature_does_not_register_callback(self):
        with patch("django.db.transaction.on_commit") as on_commit:
            post_save.send(sender=ProductionTask, instance=ProductionTask(), created=False, raw=False, using="default")
        on_commit.assert_not_called()

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_raw_fixture_loading_does_not_produce_reminder(self):
        with patch("django.db.transaction.on_commit") as on_commit:
            post_save.send(sender=ProductionTask, instance=ProductionTask(), created=False, raw=True, using="default")
        on_commit.assert_not_called()


class TrackingCommitHookTests(TestCase):
    def setUp(self):
        order_tests.PurchaseOrderApiTests.setUp(self)
        self.task = order_tests.PurchaseOrderApiTests.make_task(self, "TRACK-HOOK")

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_task_change_registers_post_commit_refresh(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.task.status = "IN_PRODUCTION"
            self.task.save(update_fields=["status", "updated_at"])
        self.assertEqual(len(callbacks), 1)

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_callback_reads_only_after_commit(self):
        with patch("apps.procurement.tracking_hooks._recompute") as recompute:
            with self.captureOnCommitCallbacks(execute=True):
                self.task.save(update_fields=["updated_at"])
                recompute.assert_not_called()
            recompute.assert_called_once_with((str(self.task.pk),))

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_inner_transaction_rollback_discards_refresh(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    self.task.save(update_fields=["updated_at"])
                    raise ValueError("主动回滚")
        self.assertEqual(callbacks, [])

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_followers_bulk_add_refreshes_task(self):
        with patch("apps.procurement.tracking_hooks._recompute") as recompute:
            with self.captureOnCommitCallbacks(execute=True):
                self.task.followers.add(self.employee)
            recompute.assert_called_once_with((str(self.task.pk),))

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_followers_reverse_clear_keeps_removed_task_identity(self):
        with override_settings(PURCHASE_TRACKING_ENABLED=False):
            self.task.followers.add(self.employee)
        with patch("apps.procurement.tracking_hooks._recompute") as recompute:
            with self.captureOnCommitCallbacks(execute=True):
                self.employee.followed_production_tasks.clear()
            self.assertTrue(recompute.called)
            self.assertTrue(all(call.args[0] == (str(self.task.pk),) for call in recompute.call_args_list))
