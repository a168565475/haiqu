"""全部最新BOM确认才通知；真实模型/权限/业务服务，企微网络仅验证未调用。"""
from copy import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.db import connections, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomLine, BomSection
from apps.boms.notification_events import (
    EVENT_CODE, current_task_bom_snapshot, register_task_boms_confirmed, snapshot_version,
)
from apps.boms.services import archive_bom, confirm_bom_product, create_bom, update_bom_lines, verify_bom
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.wecom.models import NotificationDelivery, NotificationEvent, NotificationRule
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import process_delivery, register_business_event

from .test_notifications import SETTINGS, create_rule
from .test_production_notifications import receiver, schedule_fixture


def request_for(fixture, bom):
    request = RequestFactory().post("/", HTTP_IF_MATCH=etag_for_instance(bom))
    request.user, request.employee = fixture.user, fixture.employee
    return request


def prepare_bom(fixture, bom):
    bom.status, bom.line_count, bom.section_count = "PENDING_CONFIRMATION", 1, 1
    bom.save()
    section = BomSection.objects.create(bom=bom, line_number=1, section_type="ACCESSORY", title="配件类")
    BomLine.objects.create(section=section, line_number=1, part_name="通知配件", specification="通知规格", unit="PCS")
    review_bom(fixture, bom)
    bom.refresh_from_db()
    return bom


def review_bom(fixture, bom):
    return confirm_bom_product(bom=bom, product=fixture.product, product_color=fixture.color,
                               color_code=fixture.color.color_code, actor_employee=fixture.employee)


def aggregation_fixture(*, two=True, saved_rule=True):
    f = schedule_fixture()
    f.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="boms"))
    f.boms = [prepare_bom(f, f.bom)]
    if two:
        second_line = copy(f.line)
        second_line.pk, second_line.line_number = uuid4(), 2
        second_line.save(force_insert=True)
        second = Bom.objects.create(bom_number="BOM-NOTIFY-SECOND", product_line=second_line,
            production_task=f.task, version_number=1, creation_method="BLANK", order_quantity=second_line.quantity,
            product_name_snapshot=second_line.product_name_snapshot, created_by_employee=f.employee)
        f.boms.append(prepare_bom(f, second))
    f.member, role = receiver(f.employee, "U06_BOM_PURCHASE", "boms.view_bom")
    f.role = role
    if saved_rule:
        create_rule(EVENT_CODE, f.employee, [role.role_code])
    return f


def verify(f, bom):
    bom.refresh_from_db()
    return verify_bom(bom=bom, quantity_confirmation_reason="", actor_employee=f.employee, request=request_for(f, bom))


@override_settings(**SETTINGS)
class TaskBomAggregationTests(APITestCase):
    def test_partial_and_missing_product_never_notify_all_latest_confirmed_once(self):
        f = aggregation_fixture()
        verify(f, f.boms[0])
        self.assertFalse(NotificationEvent.objects.exists())
        missing = copy(f.line)
        missing.pk, missing.line_number = uuid4(), 3
        missing.save(force_insert=True)
        verify(f, f.boms[1])
        self.assertFalse(NotificationEvent.objects.exists())
        third = Bom.objects.create(bom_number="BOM-NOTIFY-THIRD", product_line=missing,
            production_task=f.task, version_number=1, creation_method="BLANK", order_quantity=missing.quantity,
            created_by_employee=f.employee)
        prepare_bom(f, third)
        verify(f, third)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.event_code, EVENT_CODE)
        self.assertEqual(event.object_type, "production_tasks.ProductionTask")
        self.assertEqual(event.object_id, str(f.task.pk))
        self.assertEqual(len(event.context["bom_versions"]), 3)
        self.assertEqual(event.object_version, snapshot_version(event.context["bom_versions"]))
        self.assertEqual(event.recipients.get().employee_id, f.member.pk)
        self.assertEqual(NotificationDelivery.objects.count(), 2)
        self.assertEqual(event.target["route_name"], "boms")
        self.assertEqual(event.target["params"], {})
        self.assertIn("3 项产品明细最新BOM已全部确认", event.rendered_body)

    def test_single_product_api_etag_product_review_and_legacy_rule_are_compatible(self):
        f = aggregation_fixture(two=False)
        legacy = create_rule("BOM_CONFIRMED", f.employee, [f.role.role_code])
        old_body = legacy.body_template
        self.assertFalse(NotificationEvent.objects.exists())
        url = f"/api/v1/boms/{f.bom.pk}/verify/"
        self.assertEqual(f.client.post(url, {}, format="json").status_code, 428)
        self.assertEqual(f.client.post(url, {}, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        response = f.client.post(url, {}, format="json", HTTP_IF_MATCH=etag_for_instance(f.bom))
        self.assertEqual(response.status_code, 200, response.data)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.event_code, EVENT_CODE)
        self.assertEqual(event.context["product_count"], "1")
        legacy.refresh_from_db()
        self.assertEqual(legacy.body_template, old_body)
        self.assertFalse(NotificationEvent.objects.filter(event_code="BOM_CONFIRMED").exists())

    def test_rollback_leaves_last_bom_unconfirmed_and_no_message(self):
        f = aggregation_fixture()
        verify(f, f.boms[0])
        with self.assertRaisesRegex(RuntimeError, "rollback"), transaction.atomic():
            verify(f, f.boms[1])
            self.assertEqual(NotificationDelivery.objects.count(), 2)
            raise RuntimeError("rollback")
        f.boms[1].refresh_from_db()
        self.assertEqual(f.boms[1].status, "PENDING_CONFIRMATION")
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_repeat_combination_does_not_recompute_template_recipients_or_time(self):
        f = aggregation_fixture(two=False)
        verified = verify(f, f.bom)
        original = NotificationEvent.objects.get()
        rule = NotificationRule.objects.get(event_code=EVENT_CODE)
        rule.body_template, rule.version = "新模板 {{document_no}} {{product_count}} {{operator}} {{occurred_at}}", 2
        rule.save()
        duplicate = register_task_boms_confirmed(task_id=f.task.pk, actor_employee=f.member, confirmed_at=timezone.now())
        self.assertEqual(duplicate.pk, original.pk)
        self.assertEqual(duplicate.rule_version, 1)
        self.assertEqual(duplicate.context["occurred_at"], verified.confirmed_at.isoformat())
        self.assertEqual(NotificationDelivery.objects.count(), 2)

    def test_new_latest_draft_expires_old_then_new_confirmation_creates_new_combination(self):
        f = aggregation_fixture(two=False)
        verify(f, f.bom)
        original = NotificationEvent.objects.get()
        f.bom.refresh_from_db()
        newer = create_bom(product_line=f.line, creation_method="COPY", source_bom=f.bom, actor_employee=f.employee)
        self.assertIsNone(current_task_bom_snapshot(f.task.pk))
        original.refresh_from_db()
        self.assertEqual(original.status, "STALE")
        self.assertFalse(recipient_payload(original.recipients.get(), f.member.user)["target_accessible"])
        self.assertEqual(recipient_payload(original.recipients.get(), f.member.user)["title"], "通知已过期")
        review_bom(f, newer)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        verify(f, newer)
        current = NotificationEvent.objects.exclude(pk=original.pk).get()
        self.assertNotEqual(current.object_version, original.object_version)
        self.assertEqual(current.context["bom_versions"][0]["bom_id"], str(newer.pk))

    def test_same_bom_draft_and_reconfirmation_changes_confirmation_revision(self):
        f = aggregation_fixture(two=False)
        verify(f, f.bom)
        original = NotificationEvent.objects.get()
        f.bom.refresh_from_db()
        update_bom_lines(bom=f.bom, sections=[], actor_employee=f.employee, request=request_for(f, f.bom))
        original.refresh_from_db()
        self.assertEqual(original.status, "STALE")
        # 为重新确认准备有效用料夹具；草稿转换及确认均调用真实服务。
        section = BomSection.objects.create(bom=f.bom, line_number=1, section_type="ACCESSORY", title="配件类")
        BomLine.objects.create(section=section, line_number=1, part_name="重新确认配件", unit="PCS")
        Bom.objects.filter(pk=f.bom.pk).update(line_count=1)
        verify(f, f.bom)
        current = NotificationEvent.objects.exclude(pk=original.pk).get()
        self.assertEqual(current.context["bom_versions"][0]["version_number"], 1)
        self.assertNotEqual(current.object_version, original.object_version)

    def test_save_and_verify_service_uses_the_same_aggregate_trigger(self):
        f = aggregation_fixture(two=False)
        section = f.bom.sections.get()
        line = section.lines.get()
        sections = [{"id": section.pk, "section_type": "ACCESSORY", "title": section.title,
                     "lines": [{"id": line.pk, "part_name": line.part_name,
                                "specification": line.specification, "unit": "PCS"}]}]
        result = update_bom_lines(bom=f.bom, sections=sections, intent="verify",
            actor_employee=f.employee, request=request_for(f, f.bom))
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(NotificationEvent.objects.get().event_code, EVENT_CODE)

    def test_archive_latest_does_not_reactivate_previous_combination(self):
        f = aggregation_fixture(two=False)
        verify(f, f.bom)
        original = NotificationEvent.objects.get()
        f.bom.refresh_from_db()
        newer = create_bom(product_line=f.line, creation_method="COPY", source_bom=f.bom, actor_employee=f.employee)
        review_bom(f, newer)
        verify(f, newer)
        current = NotificationEvent.objects.exclude(pk=original.pk).get()
        newer.refresh_from_db()
        url = f"/api/v1/boms/{newer.pk}/archive/"
        result = f.client.post(url, {}, format="json", HTTP_IF_MATCH=etag_for_instance(newer))
        self.assertEqual(result.status_code, 200, result.data)
        original.refresh_from_db(); current.refresh_from_db()
        self.assertEqual(original.status, "STALE")
        self.assertEqual(current.status, "STALE")
        self.assertEqual(register_task_boms_confirmed(task_id=f.task.pk, actor_employee=f.employee,
            confirmed_at=timezone.now()).pk, original.pk)
        self.assertEqual(NotificationEvent.objects.count(), 2)
        self.assertFalse(recipient_payload(original.recipients.get(), f.member.user)["target_accessible"])

    def test_unsaved_configuration_records_missing_and_never_backfills(self):
        f = aggregation_fixture(two=False, saved_rule=False)
        verify(f, f.bom)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.status, "CONFIG_MISSING")
        create_rule(EVENT_CODE, f.employee, [f.role.role_code])
        repeated = register_task_boms_confirmed(task_id=f.task.pk, actor_employee=f.employee, confirmed_at=timezone.now())
        self.assertEqual(repeated.pk, event.pk)
        self.assertFalse(repeated.recipients.exists())

    def test_role_configuration_does_not_grant_bom_scope(self):
        f = aggregation_fixture(two=False)
        from apps.access_control.models import RoleActionGrant
        RoleActionGrant.objects.filter(role=f.role).update(scope="OWN")
        verify(f, f.bom)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.assertFalse(event.recipients.exists())

    def test_wrong_manifest_cannot_be_registered_as_complete_task(self):
        f = aggregation_fixture(two=False)
        verified = verify(f, f.bom)
        snapshot = current_task_bom_snapshot(f.task.pk)
        snapshot[0]["bom_id"] = str(uuid4())
        with self.assertRaises(Conflict):
            register_business_event(event_code=EVENT_CODE, idempotency_key="forged-combination",
                object_type="production_tasks.ProductionTask", object_id=f.task.pk,
                object_version=snapshot_version(snapshot), context={"document_no": f.task.task_number,
                    "product_count": 1, "operator": f.employee.display_name,
                    "occurred_at": verified.confirmed_at.isoformat(), "bom_versions": snapshot})
        self.assertEqual(NotificationEvent.objects.count(), 1)


@override_settings(**SETTINGS)
class TaskBomAggregationConcurrencyTests(TransactionTestCase):
    def test_concurrent_last_two_confirmations_register_one_complete_combination(self):
        f = aggregation_fixture()
        barrier = Barrier(2)

        def confirm(bom):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return verify(f, bom).status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(confirm, f.boms)), ["VERIFIED", "VERIFIED"])
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(len(NotificationEvent.objects.get().context["bom_versions"]), 2)
        self.assertEqual(NotificationDelivery.objects.count(), 2)

    def test_expired_event_is_not_sent_to_wecom(self):
        f = aggregation_fixture(two=False)
        verify(f, f.bom)
        delivery = NotificationDelivery.objects.get(channel="WECOM")
        f.bom.refresh_from_db()
        archive_bom(bom=f.bom, actor_employee=f.employee, request=request_for(f, f.bom))
        with patch("apps.wecom.notification_services.WeComClient.send_text") as sender:
            result = process_delivery(delivery)
        self.assertEqual(result.error_code, "EVENT_STALE")
        sender.assert_not_called()
