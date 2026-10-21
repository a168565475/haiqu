"""隔离数据库测试；只模拟企微网络，不模拟收件人或真实业务对象授权。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant, SalesTeam, SalesTeamMembership
from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.samples.models import SampleInventoryReceipt, SampleRequest
from apps.wecom import notification_selectors as selectors, notification_services as services
from apps.wecom.client import WeComError, WeComSendUncertain
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import NotificationDelivery, NotificationEvent, NotificationRecipient, NotificationRule, WeComBinding, WeComConfig
from apps.wecom.notification_access import EVENT_OBJECT_PERMISSIONS, event_object_accessible
from apps.wecom.notification_catalog import get_event


SETTINGS = dict(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True, SALES_ACCESS_ENABLED=True,
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()])
EVENT_CODE = "SAMPLE_INVENTORY_RECEIVED"
RULES_URL = "/api/v1/notifications/rules/"
INBOX_URL = "/api/v1/notifications/inbox/"


def employee(code):
    user = get_user_model().objects.create_user(username=code.lower())
    return Employee.objects.create(user=user, employee_code=code, display_name=code)


def grant_role(member, code, permission_code, scope="MODULE"):
    app, codename = permission_code.split(".")
    permission = Permission.objects.get(content_type__app_label=app, codename=codename)
    role = RoleProfile.objects.create(auth_group=Group.objects.create(name=code), role_code=code, display_name=code)
    EmployeeRoleAssignment.objects.create(employee=member, role_profile=role, effective_from=timezone.now() - timedelta(minutes=1))
    RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
    return role


def rule_data(event_code, role_codes, **updates):
    event = get_event(event_code)
    return {"name": event["display_name"], "title_template": event["default_title"],
        "body_template": event["default_body"], "recipient_role_codes": role_codes,
        "recipient_scope": event["supported_scopes"][0], "enabled": True, **updates}


def create_rule(event_code, actor, role_codes, **updates):
    return NotificationRule.objects.create(event_code=event_code, updated_by_employee=actor,
        allowed_variables=get_event(event_code)["allowed_variables"], **rule_data(event_code, role_codes, **updates))


def sample_request(owner, code):
    customer = CustomerAccount.objects.create(account_code=code, account_name="通知范围测试客户")
    CustomerAssignment.objects.create(customer_account=customer, employee=owner, assignment_role="PRIMARY_OWNER",
        effective_from=timezone.now() - timedelta(minutes=1), assigned_by_employee=owner)
    return SampleRequest.objects.create(customer_account=customer, owner_employee=owner,
        requested_by_employee=owner, request_number=code, requested_at=timezone.now())


class NotificationFixture:
    def setUp(self):
        super().setUp()
        self.member = employee("NOTIFY_MEMBER")
        self.role = grant_role(self.member, "NOTIFY_READER", "samples.view_sampleinventoryline")
        self.receipt = SampleInventoryReceipt.objects.create(receipt_number="NOTIFY_RECEIPT_1",
            submitted_by_employee=self.member, submitted_at=timezone.now())
        self.rule = create_rule(EVENT_CODE, self.member, [self.role.role_code])
        self.context = {"document_no": self.receipt.receipt_number, "operator": "测试提交人", "occurred_at": "2026-10-21 10:00:00"}
        self.arguments = dict(event_code=EVENT_CODE, idempotency_key="notify:receipt:1:v1",
            object_type="SAMPLE_INVENTORY_RECEIPT", object_id=str(self.receipt.pk), object_version="1", context=self.context)

    def register(self, **updates):
        return services.register_business_event(**{**self.arguments, **updates})

    def configure_wecom(self):
        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("unit04-test-only"))
        binding = WeComBinding.objects.create(employee=self.member, corp_id=config.corp_id,
            user_id="Notification.Member", member_name="通知测试成员", source="MANUAL", created_by_employee=self.member)
        return config, binding


@override_settings(**SETTINGS)
class NotificationServiceTests(NotificationFixture, TestCase):
    def test_replay_preserves_snapshot_and_changed_rules_only_affect_new_events(self):
        first = self.register()
        other = employee("NOTIFY_SECOND")
        other_role = grant_role(other, "NOTIFY_SECOND_READER", "samples.view_sampleinventoryline")
        self.rule.recipient_role_codes, self.rule.title_template, self.rule.version = [other_role.role_code], "新标题", 2
        self.rule.save()
        replay = self.register()
        later = self.register(idempotency_key="new-event", object_version="2")
        self.assertEqual(replay.pk, first.pk)
        self.assertEqual(replay.rule_version, 1)
        self.assertNotEqual(replay.rendered_title, "新标题")
        self.assertEqual(list(replay.recipients.values_list("employee_id", flat=True)), [self.member.pk])
        self.assertEqual(list(later.recipients.values_list("employee_id", flat=True)), [other.pk])
        self.assertEqual(later.rendered_title, "新标题")
        self.assertEqual(NotificationDelivery.objects.filter(recipient__event=first).count(), 2)

    def test_changed_payload_for_same_key_is_conflict(self):
        self.register()
        with self.assertRaises(Conflict):
            self.register(context={**self.context, "operator": "另一人"})
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(NotificationRecipient.objects.count(), 1)

    def test_business_rollback_removes_event_recipient_and_both_channels(self):
        with self.assertRaisesRegex(RuntimeError, "业务失败"):
            with transaction.atomic():
                self.register()
                self.assertEqual(NotificationDelivery.objects.count(), 2)
                raise RuntimeError("业务失败")
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertFalse(NotificationRecipient.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_same_employee_in_multiple_selected_roles_receives_one_message(self):
        second_role = grant_role(self.member, "NOTIFY_SECOND_ROLE", "samples.view_sampleinventoryline")
        self.rule.recipient_role_codes.append(second_role.role_code)
        self.rule.save()
        recipient = self.register().recipients.get()
        self.assertCountEqual(recipient.role_codes, [self.role.role_code, second_role.role_code])
        self.assertEqual(recipient.deliveries.count(), 2)

    def test_missing_disabled_empty_and_not_ready_states_are_explicit(self):
        self.rule.delete()
        self.assertEqual(self.register().status, "CONFIG_MISSING")
        self.rule = create_rule(EVENT_CODE, self.member, [self.role.role_code], enabled=False)
        self.assertEqual(self.register(idempotency_key="disabled").status, "DISABLED")
        self.rule.enabled = True
        self.rule.save()
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.assertEqual(self.register(idempotency_key="no-recipient").status, "NO_RECIPIENT")
        code = "SEMI_FINISHED_RECEIPT_SUBMITTED"
        create_rule(code, self.member, [self.role.role_code])
        self.assertEqual(self.register(event_code=code, idempotency_key="not-ready").status, "NOT_READY")
        self.assertFalse(NotificationRecipient.objects.exists())

    def test_submitter_scope_uses_real_object_authorization_and_does_not_broadcast(self):
        role = grant_role(self.member, "NOTIFY_SAMPLE_REVIEWER", "samples.review_sample_application")
        other = employee("NOTIFY_OTHER_REVIEWER")
        EmployeeRoleAssignment.objects.create(employee=other, role_profile=role, effective_from=timezone.now())
        sample = sample_request(self.member, "NOTIFY_SAMPLE_SUBMITTER")
        sample.status, sample.application_payload_hash = 'DIRECTOR_REVIEW', 'notification-test-application'
        sample.save()
        from apps.core.audit import write_audit_log
        audit = write_audit_log(object_type='SAMPLE_REQUEST', object_id=sample.pk, action='APPLICATION_SUBMITTED', actor_employee=self.member)
        create_rule("SAMPLE_SUBMITTED", self.member, [role.role_code], recipient_scope="SUBMITTER")
        args = dict(event_code="SAMPLE_SUBMITTED", object_type="samples.SampleRequest", object_id=str(sample.pk), object_version=str(audit.pk))
        event = self.register(**args, idempotency_key="submitter", context={**self.context, "submitter_id": str(self.member.pk)})
        self.assertEqual(list(event.recipients.values_list("employee_id", flat=True)), [self.member.pk])
        with self.assertRaises(Conflict):
            self.register(**args, idempotency_key="no-submitter")

    def test_missing_workshop_does_not_fall_back_to_role_broadcast(self):
        role = grant_role(self.member, "NOTIFY_DIRECTOR", "production_scheduling.view_productionschedule")
        create_rule("PRODUCTION_PLAN_CREATED", self.member, [role.role_code])
        # 仅隔离“缺少车间”分支，不把本例当真实对象权限验收。
        with patch("apps.wecom.notification_services.event_object_accessible", return_value=True) as access:
            event = self.register(event_code="PRODUCTION_PLAN_CREATED", idempotency_key="missing-workshop")
        self.assertEqual(event.status, "NO_RECIPIENT")
        access.assert_not_called()

    def test_context_rejects_unknown_fields_invalid_ids_and_missing_variables(self):
        invalid = [{**self.context, "target_deleted": False}, {**self.context, "external_url": "https://example.com"},
            {**self.context, "submitter_id": "not-a-uuid"}, {**self.context, "operator": ""}, {"document_no": "X"}]
        for context in invalid:
            with self.subTest(context=context), self.assertRaises(ValidationError):
                self.register(context=context)
        self.assertFalse(NotificationEvent.objects.exists())


@override_settings(**SETTINGS)
class NotificationObjectAccessTests(NotificationFixture, TestCase):
    def test_every_registered_selector_rejects_nonexistent_uuid_without_field_error(self):
        admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=admin, employee_code="NOTIFY_ADMIN", display_name="通知管理员")
        for code in EVENT_OBJECT_PERMISSIONS:
            with self.subTest(event_code=code):
                self.assertFalse(event_object_accessible(code, uuid4(), admin))

    def test_real_object_permission_and_account_are_rechecked_without_user_cache(self):
        user = self.member.user
        self.assertTrue(event_object_accessible(EVENT_CODE, self.receipt.pk, user))
        self.assertFalse(event_object_accessible(EVENT_CODE, "not-an-id", user))
        self.assertFalse(event_object_accessible("UNKNOWN", self.receipt.pk, user))
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        self.assertFalse(event_object_accessible(EVENT_CODE, self.receipt.pk, user))
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)
        self.assertTrue(event_object_accessible(EVENT_CODE, self.receipt.pk, user))
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.assertFalse(event_object_accessible(EVENT_CODE, self.receipt.pk, user))

    def test_real_sample_selector_obeys_own_team_and_current_customer_assignment(self):
        from apps.wecom.notification_access import _object_queryset, _request_for
        # 本例只验真实数据范围；完成状态/版本另由08真实业务服务用例覆盖。
        def accessible(sample):
            request = _request_for(self.member.user, self.member, 'samples.view_samplerequest')
            return _object_queryset('SAMPLE_COMPLETED', request, 'samples.view_samplerequest').filter(pk=sample.pk).exists()
        role = grant_role(self.member, "NOTIFY_SAMPLE_OWNER", "samples.view_samplerequest", "OWN")
        teammate, outsider = employee("NOTIFY_TEAMMATE"), employee("NOTIFY_OUTSIDER")
        own = sample_request(self.member, "NOTIFY_OWN_SAMPLE")
        team_sample = sample_request(teammate, "NOTIFY_TEAM_SAMPLE")
        outside_sample = sample_request(outsider, "NOTIFY_OUTSIDE_SAMPLE")
        self.assertTrue(accessible(own))
        self.assertFalse(accessible(team_sample))
        team = SalesTeam.objects.create(code="NOTIFY_TEAM", name="测试团队", manager=self.member)
        SalesTeamMembership.objects.create(team=team, employee=teammate, created_by_employee=self.member)
        RoleActionGrant.objects.filter(role=role).update(scope="TEAM")
        self.assertFalse(accessible(own))
        self.assertTrue(accessible(team_sample))
        self.assertFalse(accessible(outside_sample))
        SampleRequest.objects.filter(pk=team_sample.pk).update(archived_at=timezone.now())
        self.assertFalse(accessible(team_sample))

    def test_new_role_does_not_replace_snapshot_role(self):
        codes = [self.role.role_code]
        self.assertTrue(event_object_accessible(EVENT_CODE, self.receipt.pk, self.member.user, role_codes=codes))
        self.role.archived_at = timezone.now()
        self.role.save()
        grant_role(self.member, "NOTIFY_REPLACEMENT_ROLE", "samples.view_sampleinventoryline")
        self.assertTrue(event_object_accessible(EVENT_CODE, self.receipt.pk, self.member.user))
        self.assertFalse(event_object_accessible(EVENT_CODE, self.receipt.pk, self.member.user, role_codes=codes))

    def test_inbox_masks_real_deleted_object_and_revoked_permission(self):
        recipient = self.register().recipients.get()
        self.assertTrue(selectors.recipient_payload(recipient, self.member.user)["target_accessible"])
        self.receipt.delete()
        payload = selectors.recipient_payload(recipient, self.member.user)
        self.assertFalse(payload["target_accessible"])
        self.assertIsNone(payload["target"])
        self.assertNotIn(self.context["document_no"], payload["body"])
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.assertFalse(selectors.recipient_payload(recipient, self.member.user)["target_accessible"])


@override_settings(**SETTINGS)
class NotificationRuleApiTests(NotificationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.actor = Employee.objects.create(user=self.admin, employee_code="NOTIFY_ADMIN", display_name="通知管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.code = "PRODUCTION_TASK_CONFIRMED"
        self.url = RULES_URL + self.code + "/"
        self.data = rule_data(self.code, [self.role.role_code])

    def test_read_only_list_and_current_etag_on_create_update_disable(self):
        count = NotificationRule.objects.count()
        response = self.client.get(RULES_URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(NotificationRule.objects.count(), count)
        row = next(item for item in response.data["data"] if item["event_code"] == self.code)
        self.assertEqual(self.client.patch(self.url, self.data, format="json").status_code, 428)
        created = self.client.patch(self.url, self.data, format="json", HTTP_IF_MATCH=row["etag"])
        self.assertEqual(created.status_code, 200, created.data)
        self.assertEqual(created.data["data"]["version"], 1)
        self.assertEqual(self.client.patch(self.url, self.data, format="json", HTTP_IF_MATCH=row["etag"]).status_code, 412)
        updated = self.client.patch(self.url, {**self.data, "enabled": False}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertFalse(updated.data["data"]["enabled"])
        self.assertEqual(updated.data["data"]["version"], 2)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM_NOTIFICATION", action="RULE_UPDATE").count(), 2)

    def test_preview_uses_unsaved_optional_variables_without_writing_or_sending(self):
        payload = {**self.data, "title_template": "{{document_no}}",
            "body_template": "{{operator}} {{occurred_at}} {{product_name}}",
            "variables": {**self.context, "product_name": "编辑中的产品"}}
        before = NotificationRule.objects.count()
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            response = self.client.post(self.url + "preview/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["title"], self.context["document_no"])
        self.assertIn("编辑中的产品", response.data["data"]["body"])
        self.assertFalse(response.data["data"]["will_send"])
        self.assertEqual(NotificationRule.objects.count(), before)
        self.assertFalse(NotificationEvent.objects.exists())
        sender.assert_not_called()

    def test_preview_rejects_bad_variables_length_roles_and_scope(self):
        base = {**self.data, "variables": self.context}
        invalid = [{"body_template": "{{password}}"}, {"body_template": "{{document_no}"},
            {"variables": {**self.context, "operator": ""}}, {"variables": {"document_no": "X"}},
            {"variables": {**self.context, "secret": "forbidden"}},
            {"variables": {**self.context, "operator": "中" * 700}},
            {"recipient_role_codes": [self.role.role_code, self.role.role_code]},
            {"recipient_role_codes": ["UNKNOWN_ROLE"]}, {"recipient_scope": "SUBMITTER"}]
        for change in invalid:
            with self.subTest(change=change):
                result = self.client.post(self.url + "preview/", {**base, **change}, format="json")
                self.assertEqual(result.status_code, 400, result.data)

    def test_save_rejects_fixed_template_text_over_wecom_byte_limit_without_writing(self):
        response = self.client.get(RULES_URL)
        row = next(item for item in response.data["data"] if item["event_code"] == self.code)
        count = NotificationRule.objects.count()
        payload = {**self.data, "body_template": "中" * 1000 + " {{document_no}} {{operator}} {{occurred_at}}"}
        result = self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH=row["etag"])
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(NotificationRule.objects.count(), count)
        self.assertFalse(NotificationRule.objects.filter(event_code=self.code).exists())

    def test_recipient_cannot_manage_rules_and_writes_require_csrf(self):
        self.client.force_login(self.member.user)
        for method, url in [("get", RULES_URL), ("patch", self.url), ("post", self.url + "preview/"),
                            ("get", "/api/v1/notifications/deliveries/")]:
            with self.subTest(method=method, url=url):
                result = getattr(self.client, method)(url, self.data, format="json")
                self.assertEqual(result.status_code, 403, result.data)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.patch(self.url, self.data, format="json").status_code, 403)

    def test_inbox_is_personal_even_for_admin_and_read_is_idempotent(self):
        recipient = self.register().recipients.get()
        target, read = INBOX_URL + str(recipient.pk) + "/target/", INBOX_URL + str(recipient.pk) + "/read/"
        self.assertEqual(self.client.get(INBOX_URL).data["count"], 0)
        self.assertEqual(self.client.get(target).status_code, 404)
        self.assertEqual(self.client.post(read).status_code, 404)
        self.client.force_login(self.member.user)
        self.assertEqual(self.client.get(INBOX_URL).data["count"], 1)
        self.assertEqual(self.client.get(INBOX_URL + "unread-count/").data["unread_count"], 1)
        self.assertEqual(self.client.get(target).status_code, 200)
        first, second = self.client.post(read), self.client.post(read)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["data"]["read_at"], second.data["data"]["read_at"])
        self.assertEqual(self.client.get(INBOX_URL + "unread-count/").data["unread_count"], 0)
        self.assertEqual(self.client.get(INBOX_URL, {"page": "bad"}).status_code, 400)


@override_settings(**SETTINGS)
class NotificationDeliveryTests(NotificationFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.config, self.binding = self.configure_wecom()
        self.event = self.register()
        self.delivery = NotificationDelivery.objects.get(recipient__event=self.event, channel="WECOM")

    def test_send_is_outside_transaction_and_duplicate_dispatch_is_not_repeated(self):
        observed = []

        def send(user_id, text):
            observed.append(connection.in_atomic_block)
            return {"msgid": "unit04-message"}

        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=send) as sender:
            result = services.process_delivery(self.delivery)
            services.process_delivery(self.delivery)
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(observed, [False])
        sender.assert_called_once_with(self.binding.user_id, f"{self.event.rendered_title}\n\n{self.event.rendered_body}")
        self.assertIsNone(self.event.recipients.get().read_at)

    def test_send_is_rejected_inside_business_transaction(self):
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            with transaction.atomic(), self.assertRaisesRegex(RuntimeError, "事务提交"):
                services.process_delivery(self.delivery)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "PENDING")
        sender.assert_not_called()

    def test_failed_external_channel_keeps_in_app_and_requires_explicit_retry(self):
        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=WeComError("RECIPIENT_REJECTED", "测试拒绝")) as sender:
            failed = services.process_delivery(self.delivery)
            services.process_delivery(failed)
        self.assertEqual(failed.status, "FAILED")
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(NotificationDelivery.objects.get(recipient__event=self.event, channel="IN_APP").status, "ACCEPTED")
        self.assertEqual(NotificationRecipient.objects.filter(event=self.event).count(), 1)
        with patch("apps.wecom.notification_services.WeComClient.send_text", return_value={"msgid": "retry-ok"}) as sender:
            retried = services.process_delivery(failed, allow_failed=True)
        self.assertEqual(retried.status, "ACCEPTED")
        self.assertEqual(retried.attempt_count, 2)
        sender.assert_called_once()

    def test_uncertain_is_not_resent_without_explicit_opt_in(self):
        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=WeComSendUncertain()) as sender:
            uncertain = services.process_delivery(self.delivery)
            services.process_delivery(uncertain)
            services.process_delivery(uncertain, allow_failed=True)
        self.assertEqual(uncertain.status, "UNCERTAIN")
        self.assertEqual(sender.call_count, 1)
        with patch("apps.wecom.notification_services.WeComClient.send_text", return_value={"msgid": "checked-retry"}) as sender:
            result = services.process_delivery(uncertain, allow_uncertain=True)
        self.assertEqual(result.status, "ACCEPTED")
        sender.assert_called_once()

    def test_late_old_worker_result_cannot_overwrite_new_processing_attempt(self):
        def old_worker_response(user_id, text):
            # 隔离模拟：旧请求在途时被回收，另一个执行者已领取第二次尝试。
            current = NotificationDelivery.objects.get(pk=self.delivery.pk)
            self.assertEqual((current.status, current.attempt_count), ("PROCESSING", 1))
            NotificationDelivery.objects.filter(pk=current.pk).update(
                status="PROCESSING", attempt_count=2, msgid="new-attempt-placeholder", last_attempt_at=timezone.now())
            return {"msgid": "old-worker-msgid"}

        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=old_worker_response) as sender:
            result = services.process_delivery(self.delivery)
        self.assertEqual((result.status, result.attempt_count, result.msgid),
            ("PROCESSING", 2, "new-attempt-placeholder"))
        self.delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.msgid), ("PROCESSING", "new-attempt-placeholder"))
        sender.assert_called_once()

    def test_two_stale_uncertain_snapshots_allow_only_one_new_attempt(self):
        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=WeComSendUncertain()):
            initial = services.process_delivery(self.delivery)
        self.assertEqual((initial.status, initial.attempt_count), ("UNCERTAIN", 1))
        first_snapshot = NotificationDelivery.objects.get(pk=self.delivery.pk)
        second_snapshot = NotificationDelivery.objects.get(pk=self.delivery.pk)
        with patch("apps.wecom.notification_services.WeComClient.send_text", side_effect=WeComSendUncertain()) as sender:
            first_result = services.process_delivery(first_snapshot, allow_uncertain=True)
            second_result = services.process_delivery(second_snapshot, allow_uncertain=True)
        self.assertEqual((first_result.status, first_result.attempt_count), ("UNCERTAIN", 2))
        self.assertEqual((second_result.status, second_result.attempt_count), ("UNCERTAIN", 2))
        sender.assert_called_once()

    def test_command_defaults_to_dry_run_and_retry_requires_explicit_delivery_id(self):
        output = StringIO()
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            call_command("process_notification_deliveries", stdout=output)
            with self.assertRaises(CommandError):
                call_command("process_notification_deliveries", execute=True, retry_uncertain=True, stdout=StringIO())
        summary = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual((summary["mode"], summary["selected_count"], summary["checked_count"]), ("dry-run", 1, 0))
        self.assertFalse(summary["execution_finished"])
        self.delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.attempt_count), ("PENDING", 0))
        sender.assert_not_called()

    def test_command_execute_sends_only_explicit_delivery_and_reports_result(self):
        other_event = self.register(idempotency_key="other-command-candidate")
        other_delivery = NotificationDelivery.objects.get(recipient__event=other_event, channel="WECOM")
        output = StringIO()
        with patch("apps.wecom.notification_services.WeComClient.send_text", return_value={"msgid": "command-message"}) as sender:
            call_command("process_notification_deliveries", execute=True,
                delivery_id=[str(self.delivery.pk)], stdout=output)
        summary = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(summary["mode"], "execute")
        self.assertEqual(summary["selected"], [{"id": str(self.delivery.pk), "status": "PENDING"}])
        self.assertEqual(summary["checked_count"], 1)
        self.assertEqual(summary["result_status_counts"], {"ACCEPTED": 1})
        self.assertTrue(summary["execution_finished"])
        self.delivery.refresh_from_db()
        other_delivery.refresh_from_db()
        self.assertEqual((self.delivery.status, self.delivery.msgid), ("ACCEPTED", "command-message"))
        self.assertEqual((other_delivery.status, other_delivery.attempt_count), ("PENDING", 0))
        sender.assert_called_once_with(self.binding.user_id, f"{self.event.rendered_title}\n\n{self.event.rendered_body}")

    def test_restart_only_recovers_abandoned_processing_as_uncertain_without_send(self):
        NotificationDelivery.objects.filter(pk=self.delivery.pk).update(status="PROCESSING",
            last_attempt_at=timezone.now() - timedelta(minutes=6), attempt_count=1)
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            self.assertEqual(services.recover_abandoned_deliveries(), 1)
            self.assertEqual(services.recover_abandoned_deliveries(), 0)
            recovered = services.process_delivery(self.delivery)
        self.assertEqual(recovered.status, "UNCERTAIN")
        self.assertEqual(recovered.error_code, "PROCESS_INTERRUPTED")
        sender.assert_not_called()
        NotificationDelivery.objects.filter(pk=self.delivery.pk).update(status="PROCESSING", last_attempt_at=timezone.now())
        self.assertEqual(services.recover_abandoned_deliveries(), 0)

    def test_revoked_permission_blocks_retry(self):
        NotificationDelivery.objects.filter(pk=self.delivery.pk).update(status="FAILED", error_code="CONFIGURATION_ERROR")
        RoleActionGrant.objects.filter(role=self.role).delete()
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            result = services.process_delivery(self.delivery, allow_failed=True)
        self.assertEqual((result.status, result.error_code), ("FAILED", "RECIPIENT_NOT_ELIGIBLE"))
        self.assertEqual(result.attempt_count, 0)
        sender.assert_not_called()

    def test_pending_delivery_keeps_original_content_and_recipients_after_rule_change(self):
        other = employee("NOTIFY_REPLACEMENT")
        role = grant_role(other, "NOTIFY_REPLACEMENT_ROLE", "samples.view_sampleinventoryline")
        self.rule.title_template, self.rule.recipient_role_codes, self.rule.version = "新标题", [role.role_code], 2
        self.rule.save()
        with patch("apps.wecom.notification_services.WeComClient.send_text", return_value={"msgid": "original"}) as sender:
            result = services.process_delivery(self.delivery)
        self.assertEqual(result.status, "ACCEPTED")
        sender.assert_called_once_with(self.binding.user_id, f"{self.event.rendered_title}\n\n{self.event.rendered_body}")
        self.assertEqual(list(self.event.recipients.values_list("employee_id", flat=True)), [self.member.pk])

    def test_binding_application_and_corporation_changes_block_retry(self):
        cases = [("binding", {"user_id": "Changed.Member"}, "BINDING_OR_APPLICATION_CHANGED"),
            ("config", {"agent_id": "1000099"}, "BINDING_OR_APPLICATION_CHANGED"),
            ("binding", {"corp_id": "another-corp"}, "CORPORATION_MISMATCH")]
        for target, changes, expected in cases:
            with self.subTest(target=target, changes=changes):
                WeComBinding.objects.filter(pk=self.binding.pk).update(user_id=self.binding.user_id, corp_id=self.binding.corp_id)
                WeComConfig.objects.filter(pk=self.config.pk).update(agent_id=self.config.agent_id)
                model, pk = (WeComBinding, self.binding.pk) if target == "binding" else (WeComConfig, self.config.pk)
                model.objects.filter(pk=pk).update(**changes)
                NotificationDelivery.objects.filter(pk=self.delivery.pk).update(status="UNCERTAIN")
                with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
                    result = services.process_delivery(self.delivery, allow_uncertain=True)
                self.assertEqual((result.status, result.error_code), ("FAILED", expected))
                sender.assert_not_called()

    def test_deleted_object_or_disabled_account_never_sends(self):
        self.receipt.delete()
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            result = services.process_delivery(self.delivery)
        self.assertEqual(result.error_code, "RECIPIENT_NOT_ELIGIBLE")
        sender.assert_not_called()
        get_user_model().objects.filter(pk=self.member.user_id).update(is_active=False)
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            result = services.process_delivery(self.delivery, allow_failed=True)
        self.assertEqual(result.error_code, "RECIPIENT_INACTIVE")
        sender.assert_not_called()


@override_settings(**SETTINGS)
class NotificationConcurrencyTests(NotificationFixture, TransactionTestCase):
    def concurrent_register(self, changes):
        barrier = Barrier(2)

        def register(change):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    event = services.register_business_event(**{**self.arguments, **change})
                    return "created", str(event.pk)
                except Conflict:
                    return "conflict", None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(register, change) for change in changes]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_identical_key_creates_one_event_recipient_and_channel_pair(self):
        results = self.concurrent_register([{}, {}])
        self.assertEqual([status for status, _ in results], ["created", "created"])
        self.assertEqual(len({pk for _, pk in results}), 1)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(NotificationRecipient.objects.count(), 1)
        self.assertEqual(NotificationDelivery.objects.count(), 2)

    def test_concurrent_same_key_different_content_returns_one_conflict(self):
        results = self.concurrent_register([{}, {"context": {**self.context, "operator": "另一人"}}])
        self.assertCountEqual([status for status, _ in results], ["created", "conflict"])
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(NotificationRecipient.objects.count(), 1)
        self.assertEqual(NotificationDelivery.objects.count(), 2)
