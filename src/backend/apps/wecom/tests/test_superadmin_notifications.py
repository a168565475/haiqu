"""真实对象验证管理员原提交人回执；仅模拟企微网络，不发送真实消息。"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.wecom.credentials import encrypt_secret
from apps.organizations.models import EmployeeRoleAssignment
from apps.wecom.models import NotificationEvent, WeComBinding, WeComConfig
from apps.wecom.notification_catalog import get_event
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import _eligible_employees, process_delivery, register_business_event

from .test_notifications import SETTINGS, create_rule, employee, grant_role, sample_request
from apps.inventory.tests.test_assembly_receipts import AssemblyFixture
from apps.inventory.tests.test_pending_receipt_deletion import DeletePermissionFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture


EVENT = "SAMPLE_SUBMITTED"


class SuperadminSubmitterFixture:
    def setUp(self):
        super().setUp()
        self.admin = employee("NOTIFY_SUBMITTER_ADMIN")
        self.admin.user.is_superuser = True
        self.admin.user.save(update_fields=["is_superuser"])
        self.other_admin = employee("NOTIFY_OTHER_ADMIN")
        self.other_admin.user.is_superuser = True
        self.other_admin.user.save(update_fields=["is_superuser"])
        self.member = employee("NOTIFY_ROLE_REVIEWER")
        self.role = grant_role(self.member, "NOTIFY_SUBMITTER_REVIEWER", "samples.review_sample_application")
        self.rule = create_rule(EVENT, self.admin, [self.role.role_code], recipient_scope="SUBMITTER")
        self.sample = sample_request(self.admin, "NOTIFY_ADMIN_SAMPLE")
        self.sample.status = "DIRECTOR_REVIEW"
        self.sample.application_payload_hash = "superadmin-notification-test"
        self.sample.save()
        audit = write_audit_log(object_type="SAMPLE_REQUEST", object_id=self.sample.pk,
            action="APPLICATION_SUBMITTED", actor_employee=self.admin)
        self.context = {"document_no": self.sample.request_number, "operator": self.admin.display_name,
            "occurred_at": audit.occurred_at.isoformat(), "submitter_id": str(self.admin.pk)}
        self.arguments = dict(event_code=EVENT, idempotency_key="superadmin-submitter",
            object_type=self.sample._meta.label, object_id=self.sample.pk,
            object_version=str(audit.pk), context=self.context)

    def eligible_for(self, recipient):
        snapshot = SimpleNamespace(recipient_role_codes=recipient.role_codes, recipient_scope=recipient.scope)
        return _eligible_employees(get_event(EVENT), snapshot, recipient.event.context,
            recipient.event.object_id, employee_id=recipient.employee_id)


@override_settings(**SETTINGS)
class SuperadminSubmitterNotificationTests(SuperadminSubmitterFixture, TestCase):
    def test_admin_without_role_receives_only_own_submitter_notice_and_can_read_it(self):
        event = register_business_event(**self.arguments)
        self.assertEqual(event.status, "CREATED")
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, self.admin.pk)
        self.assertEqual(recipient.role_codes, [])
        self.assertEqual(recipient.deliveries.get(channel="IN_APP").status, "ACCEPTED")
        self.assertTrue(recipient_payload(recipient, self.admin.user)["target_accessible"])
        self.assertEqual([row["employee"].pk for row in self.eligible_for(recipient)], [self.admin.pk])
        self.assertFalse(event.recipients.filter(employee=self.other_admin).exists())

    def test_context_cannot_replace_actual_submitter_with_another_admin(self):
        with self.assertRaises(Conflict):
            register_business_event(**{**self.arguments,
                "context": {**self.context, "submitter_id": str(self.other_admin.pk)}})

    def test_other_recipient_id_cannot_reuse_submitter_exception(self):
        event = register_business_event(**self.arguments)
        recipient = event.recipients.get()
        snapshot = SimpleNamespace(recipient_role_codes=[], recipient_scope="SUBMITTER")
        self.assertEqual(_eligible_employees(get_event(EVENT), snapshot, event.context,
            event.object_id, employee_id=self.other_admin.pk), [])

    def test_role_member_scope_does_not_add_admin_without_selected_role(self):
        self.rule.recipient_scope = "ROLE_MEMBERS"
        self.rule.save(update_fields=["recipient_scope"])
        event = register_business_event(**self.arguments)
        self.assertEqual(list(event.recipients.values_list("employee_id", flat=True)), [self.member.pk])

    def test_admin_losing_superuser_or_account_access_cannot_read_or_send_snapshot(self):
        event = register_business_event(**self.arguments)
        recipient = event.recipients.get()
        for changes in ({"is_superuser": False}, {"is_superuser": True, "is_active": False}):
            with self.subTest(changes=changes):
                get_user_model().objects.filter(pk=self.admin.user_id).update(**changes)
                self.assertFalse(recipient_payload(recipient, self.admin.user)["target_accessible"])
                self.assertEqual(self.eligible_for(recipient), [])

    def test_current_object_still_must_be_accessible(self):
        event = register_business_event(**self.arguments)
        recipient = event.recipients.get()
        self.sample.status = "PENDING_COMPLETION"
        self.sample.save(update_fields=["status"])
        self.assertFalse(recipient_payload(recipient, self.admin.user)["target_accessible"])
        self.assertEqual(self.eligible_for(recipient), [])

    def test_ordinary_submitter_still_requires_role_permission_after_registration(self):
        self.sample.requested_by_employee = self.member
        self.sample.save(update_fields=["requested_by_employee"])
        event = register_business_event(**{**self.arguments,
            "context": {**self.context, "submitter_id": str(self.member.pk)}})
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, self.member.pk)
        self.assertTrue(recipient_payload(recipient, self.member.user)["target_accessible"])
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.assertFalse(recipient_payload(recipient, self.member.user)["target_accessible"])
        self.assertEqual(self.eligible_for(recipient), [])


@override_settings(**SETTINGS)
class SuperadminSubmitterDeliveryTests(SuperadminSubmitterFixture, TransactionTestCase):
    def test_bound_admin_without_role_passes_same_post_commit_delivery_checks(self):
        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-superadmin-only"))
        binding = WeComBinding.objects.create(employee=self.admin, corp_id=config.corp_id,
            user_id="Notify.Superadmin", member_name="测试管理员", source="MANUAL", created_by_employee=self.admin)
        event = register_business_event(**self.arguments)
        delivery = event.recipients.get().deliveries.get(channel="WECOM")
        with patch("apps.wecom.notification_services.WeComClient.send_text_notice", return_value={"msgid": "test-admin-receipt"}) as sender:
            result = process_delivery(delivery)
        self.assertEqual(result.status, "ACCEPTED")
        sender.assert_called_once_with(binding.user_id, title=event.rendered_title,
            body=event.rendered_body, url=f"{config.erp_origin}/?notification={delivery.recipient_id}", preview=False)


class InventorySuperadminNotificationAssertions:
    def prepare_notification_roles(self, submitted_code, confirmed_code, permission):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee=self.employee).exists())
        warehouse = self.warehouse_with_template()
        self.assertFalse(warehouse.has_perm("production_tasks.view_productiontask"))
        director = employee("NOTIFY_INVENTORY_DIRECTOR")
        role = grant_role(director, "NOTIFY_INVENTORY_DIRECTOR", permission)
        create_rule(submitted_code, self.employee, ["WAREHOUSE_KEEPER"])
        create_rule(confirmed_code, self.employee, [role.role_code], recipient_scope="SUBMITTER")
        self.client.force_authenticate(self.user)
        return warehouse

    def assert_warehouse_notice(self, event_code, receipt_id, warehouse):
        event = NotificationEvent.objects.get(event_code=event_code, object_id=receipt_id)
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee.user_id, warehouse.pk)
        self.assertTrue(recipient_payload(recipient, warehouse)["target_accessible"])

    def assert_original_admin_receipt_notice(self, event_code, receipt_id):
        event = NotificationEvent.objects.get(event_code=event_code, object_id=receipt_id)
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, self.employee.pk)
        self.assertEqual(recipient.role_codes, [])
        self.assertEqual(event.context["submitter_id"], str(self.employee.pk))
        self.assertTrue(recipient_payload(recipient, self.user)["target_accessible"])
        snapshot = SimpleNamespace(recipient_role_codes=[], recipient_scope="SUBMITTER")
        candidates = _eligible_employees(get_event(event_code), snapshot, event.context,
            event.object_id, employee_id=self.employee.pk)
        self.assertEqual([row["employee"].pk for row in candidates], [self.employee.pk])


@override_settings(**SETTINGS, TUBE_OUTSOURCING_ENABLED=True,
                   PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class SemiReceiptSuperadminNotificationTests(InventorySuperadminNotificationAssertions,
        DeletePermissionFixture, D1Fixture, APITestCase):
    def test_admin_submission_notifies_warehouse_then_actual_confirmation_notifies_admin(self):
        warehouse = self.prepare_notification_roles("SEMI_FINISHED_RECEIPT_SUBMITTED",
            "INTERNAL_SEMI_RECEIPT_CONFIRMED", "inventory.view_internalsemifinishedreceipt")
        etag = self.d1_preview()["etag"]
        created = self.d1_post(etag=etag)
        receipt_id = created.data["data"]["receipt_id"]
        self.assert_warehouse_notice("SEMI_FINISHED_RECEIPT_SUBMITTED", receipt_id, warehouse)
        self.client.force_authenticate(warehouse)
        confirmed = self.client.post(f"/api/v1/semi-finished-receipts/{receipt_id}/confirm/",
            format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assert_original_admin_receipt_notice("INTERNAL_SEMI_RECEIPT_CONFIRMED", receipt_id)


@override_settings(**SETTINGS)
class AssemblyReceiptSuperadminNotificationTests(InventorySuperadminNotificationAssertions,
        DeletePermissionFixture, AssemblyFixture, APITestCase):
    def setUp(self):
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            self.prepare()

    def test_admin_submission_notifies_warehouse_then_actual_confirmation_notifies_admin(self):
        warehouse = self.prepare_notification_roles("ASSEMBLY_FINISHED_RECEIPT_SUBMITTED",
            "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED", "inventory.view_finishedgoodsreceipt")
        created = self.post(self.payload(received_quantity=3))
        self.assertEqual(created.status_code, 201, created.data)
        receipt_id = created.data["data"]["id"]
        self.assert_warehouse_notice("ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", receipt_id, warehouse)
        self.client.force_authenticate(warehouse)
        confirmed = self.client.post(f"/api/v1/assembly-finished-receipts/{receipt_id}/confirm/", format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assert_original_admin_receipt_notice("ASSEMBLY_FINISHED_RECEIPT_CONFIRMED", receipt_id)
