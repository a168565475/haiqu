"""隔离数据库回归：观察真实授权与 SQL，不调用企业微信投递。"""
from collections import Counter
from datetime import timedelta
import json
import re
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.core.audit import write_audit_log
from apps.organizations.models import EmployeeRoleAssignment
from apps.wecom import notification_services as services
from apps.wecom.models import (
    NotificationDelivery, NotificationEvent, NotificationRecipient, WeComBinding, WeComConfig,
)
from apps.wecom.notification_access import EVENT_OBJECT_PERMISSIONS
from apps.wecom.notification_catalog import get_event

from .test_notifications import (
    EVENT_CODE, SETTINGS, NotificationFixture, create_rule, employee, grant_role, sample_request,
)


def registration_query_counts(queries):
    patterns = {
        "binding_select": r'^SELECT\b.*\bFROM\s+"wecom_binding"',
        "recipient_insert": r'^INSERT\s+INTO\s+"wecom_notification_recipient"',
        "delivery_insert": r'^INSERT\s+INTO\s+"wecom_notification_delivery"',
    }
    return {
        name: sum(bool(re.search(pattern, item["sql"].lstrip(), re.IGNORECASE | re.DOTALL))
                  for item in queries)
        for name, pattern in patterns.items()
    }


@override_settings(**SETTINGS)
class NotificationRecipientBatchingTests(NotificationFixture, TestCase):
    def assign_role(self, member, role):
        return EmployeeRoleAssignment.objects.create(
            employee=member, role_profile=role, effective_from=timezone.now() - timedelta(minutes=1),
        )

    def test_selected_roles_keep_full_employee_authorization_and_check_allow_deny_once(self):
        # 所选角色本身无入库查看权；有效授权来自未选中的 self.role。
        first = grant_role(self.member, "BATCH_SELECTED_A", "samples.view_samplerequest")
        second = grant_role(self.member, "BATCH_SELECTED_B", "samples.view_samplerequest")
        denied = employee("BATCH_DENIED")
        self.assign_role(denied, first)
        self.assign_role(denied, second)
        self.rule.recipient_role_codes = [second.role_code, first.role_code]
        self.rule.save(update_fields=["recipient_role_codes"])

        with patch.object(services, "event_object_accessible", wraps=services.event_object_accessible) as access:
            event = self.register()

        self.assertEqual(event.status, "CREATED")
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, self.member.pk)
        self.assertEqual(recipient.role_codes, sorted([first.role_code, second.role_code]))
        self.assertNotIn(self.role.role_code, recipient.role_codes)
        checked_users = Counter(call.args[2].pk for call in access.call_args_list)
        self.assertEqual(checked_users, Counter({self.member.user_id: 1, denied.user_id: 1}))

    def test_binding_and_child_insert_counts_are_constant_for_one_and_eight_recipients(self):
        self.configure_wecom()
        for size in (1, 8):
            if size == 8:
                for index in range(2, 9):
                    member = employee(f"BATCH_MEMBER_{index}")
                    self.assign_role(member, self.role)
            with self.subTest(recipient_count=size):
                with CaptureQueriesContext(connection) as captured:
                    event = self.register(idempotency_key=f"batch-query-count-{size}")
                counts = registration_query_counts(captured.captured_queries)
                print("notification_batch_counts=" + json.dumps({"recipients": size, **counts}, sort_keys=True))
                self.assertEqual(event.recipients.count(), size)
                self.assertEqual(NotificationDelivery.objects.filter(recipient__event=event).count(), size * 2)
                self.assertEqual(counts, {"binding_select": 1, "recipient_insert": 1, "delivery_insert": 1})

    def test_bulk_rows_preserve_snapshots_timestamps_channels_and_unbound_recipients(self):
        unbound = employee("BATCH_UNBOUND")
        admin = employee("ADMIN")
        other_admin = employee("BATCH_OTHER_ADMIN")
        members = [self.member, unbound, admin, other_admin]
        for member in members[1:]:
            self.assign_role(member, self.role)
        for member in (admin, other_admin):
            member.user.is_superuser = True
            member.user.save(update_fields=["is_superuser"])
        config = WeComConfig.objects.create(corp_id="batch-test-corp", agent_id="1000008", enabled=False)
        binding_ids = {self.member.pk: "Batch.Member", admin.pk: "Batch.Admin"}
        for member in (self.member, admin):
            WeComBinding.objects.create(
                employee=member, corp_id=config.corp_id, user_id=binding_ids[member.pk],
                member_name=member.display_name, source="MANUAL", created_by_employee=self.member,
            )

        started = timezone.now()
        event = self.register()
        finished = timezone.now()
        recipients = {item.employee_id: item for item in event.recipients.prefetch_related("deliveries")}
        self.assertEqual(set(recipients), {member.pk for member in members})
        for member in members:
            with self.subTest(member_kind="admin" if member == admin else "other"):
                recipient = recipients[member.pk]
                self.assertEqual(recipient.employee_name, member.display_name)
                self.assertEqual(recipient.role_codes, [self.role.role_code])
                self.assertEqual(recipient.scope, self.rule.recipient_scope)
                self.assertEqual(recipient.eligibility_snapshot, {
                    "required_permissions": list(EVENT_OBJECT_PERMISSIONS[EVENT_CODE]),
                    "corp_id": config.corp_id, "agent_id": config.agent_id,
                })
                self.assertIsNone(recipient.read_at)
                deliveries = {item.channel: item for item in recipient.deliveries.all()}
                self.assertEqual(set(deliveries), {"IN_APP", "WECOM"})
                for row in [recipient, *deliveries.values()]:
                    self.assertIsNotNone(row.pk)
                    self.assertLessEqual(started, row.created_at)
                    self.assertLessEqual(row.created_at, finished)
                    self.assertLessEqual(started, row.updated_at)
                    self.assertLessEqual(row.updated_at, finished)
                for channel, delivery in deliveries.items():
                    self.assertEqual(delivery.idempotency_key, f"{event.pk}:{member.pk}:{channel}")
                    self.assertEqual(delivery.attempt_count, 0)
                    self.assertEqual(delivery.msgid, "")
                    self.assertIsNone(delivery.last_attempt_at)
                in_app, wecom = deliveries["IN_APP"], deliveries["WECOM"]
                self.assertEqual((in_app.status, in_app.error_code, in_app.user_id_snapshot), ("ACCEPTED", "", ""))
                self.assertLessEqual(started, in_app.finished_at)
                self.assertLessEqual(in_app.finished_at, finished)
                self.assertEqual(wecom.user_id_snapshot, binding_ids.get(member.pk, ""))
                if member == admin:
                    self.assertEqual((wecom.status, wecom.error_code), ("SKIPPED", "ADMIN_IN_APP_ONLY"))
                    self.assertLessEqual(started, wecom.finished_at)
                    self.assertLessEqual(wecom.finished_at, finished)
                else:
                    self.assertEqual((wecom.status, wecom.error_code), ("PENDING", ""))
                    self.assertIsNone(wecom.finished_at)

    def test_empty_recipients_do_not_query_bindings_or_insert_children(self):
        RoleActionGrant.objects.filter(role=self.role).delete()
        with CaptureQueriesContext(connection) as captured:
            event = self.register()
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.assertEqual(registration_query_counts(captured.captured_queries),
                         {"binding_select": 0, "recipient_insert": 0, "delivery_insert": 0})
        self.assertFalse(event.recipients.exists())
        self.assertFalse(NotificationDelivery.objects.filter(recipient__event=event).exists())

    def test_next_registration_rechecks_revoked_permission(self):
        with patch.object(services, "event_object_accessible", wraps=services.event_object_accessible) as access:
            first = self.register(idempotency_key="batch-before-revocation")
            RoleActionGrant.objects.filter(role=self.role).delete()
            second = self.register(idempotency_key="batch-after-revocation")
        self.assertEqual(Counter(call.args[2].pk for call in access.call_args_list), Counter({self.member.user_id: 2}))
        self.assertEqual(first.status, "CREATED")
        self.assertEqual(first.recipients.count(), 1)
        self.assertEqual(second.status, "NO_RECIPIENT")
        self.assertFalse(second.recipients.exists())
        self.assertFalse(NotificationDelivery.objects.filter(recipient__event=second).exists())

    def test_submitter_superuser_checks_once_with_role_and_keeps_roleless_fallback(self):
        self.member.user.is_superuser = True
        self.member.user.save(update_fields=["is_superuser"])
        role = grant_role(self.member, "BATCH_SUBMITTER_REVIEWER", "samples.review_sample_application")
        sample = sample_request(self.member, "BATCH_SUBMITTER_SAMPLE")
        sample.status = "DIRECTOR_REVIEW"
        sample.application_payload_hash = "batch-submitter-application"
        sample.save(update_fields=["status", "application_payload_hash"])
        audit = write_audit_log(object_type="SAMPLE_REQUEST", object_id=sample.pk,
                                action="APPLICATION_SUBMITTED", actor_employee=self.member)
        rule = create_rule("SAMPLE_SUBMITTED", self.member, [role.role_code], recipient_scope="SUBMITTER")
        context = {"submitter_id": str(self.member.pk), "object_version": str(audit.pk)}

        for has_selected_role in (True, False):
            if not has_selected_role:
                EmployeeRoleAssignment.objects.filter(employee=self.member, role_profile=role).update(
                    effective_to=timezone.now(),
                )
            with self.subTest(has_selected_role=has_selected_role):
                with patch.object(services, "event_object_accessible", wraps=services.event_object_accessible) as access:
                    selected = services._eligible_employees(get_event("SAMPLE_SUBMITTED"), rule, context, str(sample.pk))
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["employee"].pk, self.member.pk)
                self.assertEqual(selected[0]["roles"], [role.role_code] if has_selected_role else [])
                access.assert_called_once()

    def test_delivery_bulk_insert_failure_rolls_back_event_and_recipients(self):
        key = "batch-delivery-insert-failure"

        def fail_delivery_insert(*args, **kwargs):
            self.assertEqual(NotificationEvent.objects.filter(idempotency_key=key).count(), 1)
            self.assertEqual(NotificationRecipient.objects.filter(event__idempotency_key=key).count(), 1)
            raise IntegrityError("injected delivery bulk insert failure")

        with patch.object(NotificationDelivery.objects, "bulk_create", side_effect=fail_delivery_insert) as insert:
            with self.assertRaisesRegex(IntegrityError, "injected delivery bulk insert failure"):
                self.register(idempotency_key=key)
            insert.assert_called_once()
        self.assertFalse(NotificationEvent.objects.filter(idempotency_key=key).exists())
        self.assertFalse(NotificationRecipient.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())
