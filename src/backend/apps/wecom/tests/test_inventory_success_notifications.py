"""07续做：隔离PostgreSQL真实库存服务/API；不代替正式身份及企微投递验收。"""
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import EmployeeRoleAssignment
from apps.core.api.exceptions import Conflict
from apps.inventory.models import AssemblyReceiptSource, FinishedGoodsOutbound, FinishedGoodsReceipt, InternalSemiFinishedReceipt
from apps.inventory.notification_events import current_inventory_object, inventory_event_version
from apps.wecom.models import NotificationDelivery, NotificationEvent
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_catalog import target_for
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import register_business_event

from .test_notifications import SETTINGS, create_rule, employee, grant_role


SEMI = "INTERNAL_SEMI_RECEIPT_CONFIRMED"
ASSEMBLY = "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED"
OUTBOUND = "FINISHED_GOODS_OUTBOUND_CONFIRMED"


class InventoryNotificationAssertions:
    def prepare_operator_plan_read(self):
        self.f.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="production_scheduling"))
        self.f.user = get_user_model().objects.get(pk=self.f.user.pk)
        self.f.client.force_authenticate(self.f.user)

    def prepare_receiver(self, code, permission):
        self.member = employee(code)
        self.role = grant_role(self.member, code, permission)
        self.role.auth_group.permissions.add(RoleActionGrant.objects.get(role=self.role).permission)
        self.member.user.groups.add(self.role.auth_group)
        self.reader = APIClient()
        self.reader.force_authenticate(get_user_model().objects.get(pk=self.member.user_id))
        create_rule(self.event_code, self.f.employee, [self.role.role_code])

    def event(self, obj):
        event = NotificationEvent.objects.get(event_code=self.event_code)
        self.assertEqual(str(event.object_id), str(obj.pk))
        self.assertEqual(event.object_type, obj._meta.label)
        self.assertEqual(event.object_version, inventory_event_version(self.event_code, obj))
        recipient = event.recipients.get()
        self.assertEqual(recipient.employee_id, self.member.pk)
        self.assertEqual(recipient.deliveries.get(channel="IN_APP").status, "ACCEPTED")
        self.assertEqual(recipient.deliveries.get(channel="WECOM").status, "PENDING")
        self.assertTrue(recipient_payload(recipient, self.member.user)["target_accessible"])
        return event

    def revoke(self, event):
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.role.auth_group.permissions.clear()
        payload = recipient_payload(event.recipients.get(), self.member.user)
        self.assertFalse(payload["target_accessible"])
        self.assertIsNone(payload["target"])
        self.assertNotIn(event.context["document_no"], payload["body"])
        self.reader.force_authenticate(get_user_model().objects.get(pk=self.member.user_id))


@override_settings(**SETTINGS, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   TUBE_OUTSOURCING_ENABLED=False)
class SemiReceiptSuccessNotificationTests(InventoryNotificationAssertions, TestCase):
    event_code = SEMI

    def setUp(self):
        from apps.inventory.tests.test_internal_receipt_sewing import InternalSewingReceiptTests
        self.f = InternalSewingReceiptTests()
        self.f.setUp()
        self.prepare_operator_plan_read()
        self.f.task.status = "IN_PRODUCTION"
        self.f.task.save(update_fields=["status"])
        self.prepare_receiver("IO_WAREHOUSE", "inventory.view_internalsemifinishedreceipt")

    def payload(self):
        return dict(request_id=str(uuid4()), schedule_product_id=str(self.f.schedule_product.pk), plan_category="SEWING",
            zone_id=str(self.f.semi_zone.pk), receipt_date=str(timezone.localdate()), remark="隔离通知验收",
            lines=[dict(bom_line_id=str(self.f.parts[0].pk), quantity="7")])

    def test_preview_failure_success_replay_and_real_receipt_identity(self):
        etag = self.f.preview()["etag"]
        self.assertFalse(NotificationEvent.objects.filter(event_code=SEMI).exists())
        invalid = self.payload()
        invalid["lines"][0]["quantity"] = "501"
        self.assertEqual(self.f.client.post(self.f.url, invalid, format="json", HTTP_IF_MATCH=etag).status_code, 400)
        self.assertFalse(NotificationEvent.objects.filter(event_code=SEMI).exists())
        payload = self.payload()
        first = self.f.client.post(self.f.url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(first.status_code, 201, first.data)
        receipt = InternalSemiFinishedReceipt.objects.get()
        event = self.event(receipt)
        self.assertNotIn("quantity", event.context)
        self.assertEqual(event.target, target_for(SEMI, receipt.pk))
        self.assertEqual(event.target["params"], {})
        movement_id = receipt.lines.get().stock_movement_id
        self.assertNotEqual(receipt.pk, movement_id)
        self.assertFalse(event_object_accessible(SEMI, movement_id, self.member.user))
        self.assertEqual(self.reader.get(self.f.url).status_code, 200)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            self.assertEqual(self.reader.get(self.f.url).status_code, 200)
            self.assertTrue(event_object_accessible(SEMI, receipt.pk, self.member.user, object_version=event.object_version))
        self.assertEqual(self.reader.get(self.f.url + str(movement_id) + "/").status_code, 200)
        self.assertEqual(self.reader.get(self.f.url + str(receipt.pk) + "/").status_code, 404)
        self.assertEqual(self.f.client.post(self.f.url, payload, format="json", HTTP_IF_MATCH=etag).status_code, 200)
        payload["lines"][0]["quantity"] = "8"
        self.assertEqual(self.f.client.post(self.f.url, payload, format="json", HTTP_IF_MATCH=etag).status_code, 409)
        self.assertEqual(NotificationEvent.objects.filter(event_code=SEMI).count(), 1)
        self.revoke(event)
        self.assertEqual(self.reader.get(self.f.url).status_code, 403)

    def test_outer_transaction_rolls_back_stock_receipt_and_both_channels(self):
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.assertEqual(self.f.receive(7).status_code, 201)
                self.assertEqual(NotificationDelivery.objects.count(), 2)
                raise RuntimeError("rollback")
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertFalse(NotificationEvent.objects.filter(event_code=SEMI).exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_confirmation_keeps_submitter_and_confirmed_actor_for_submitter_scope(self):
        from apps.wecom.models import NotificationRule
        rule = NotificationRule.objects.get(event_code=SEMI)
        rule.recipient_scope = "SUBMITTER"
        rule.save(update_fields=["recipient_scope", "updated_at"])
        EmployeeRoleAssignment.objects.create(employee=self.f.employee, role_profile=self.role,
            effective_from=timezone.now() - timedelta(minutes=1))
        self.f.employee.user.groups.add(self.role.auth_group)

        self.assertEqual(self.f.receive(7).status_code, 201)
        receipt = InternalSemiFinishedReceipt.objects.get()
        event = NotificationEvent.objects.get(event_code=SEMI)
        self.assertEqual(event.context["submitter_id"], str(self.f.employee.pk))
        self.assertEqual(event.context["confirmed_by"], self.f.employee.display_name)
        self.assertEqual(event.context["confirmed_at"], receipt.created_at.isoformat())
        self.assertEqual(list(event.recipients.values_list("employee_id", flat=True)), [self.f.employee.pk])

        with self.assertRaises(Conflict):
            register_business_event(event_code=SEMI, idempotency_key="forged-submitter",
                object_type=receipt._meta.label, object_id=receipt.pk,
                object_version=event.object_version,
                context={"document_no": receipt.receipt_number, "operator": self.f.employee.display_name,
                    "occurred_at": receipt.created_at.isoformat(), "status": "已入库",
                    "submitter_id": str(self.member.pk)})

    def test_changed_success_proof_masks_old_content_and_rejects_forged_registration(self):
        self.assertEqual(self.f.receive(7).status_code, 201)
        receipt = InternalSemiFinishedReceipt.objects.get()
        event = self.event(receipt)
        with self.assertRaises(Conflict):
            register_business_event(event_code=SEMI, idempotency_key="forged-movement", object_type=receipt._meta.label,
                object_id=receipt.lines.get().stock_movement_id, object_version=event.object_version)
        InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).update(receipt_number="CHANGED")
        payload = recipient_payload(event.recipients.get(), self.member.user)
        self.assertEqual(payload["title"], "通知已过期")
        self.assertIsNone(payload["target"])


@override_settings(**SETTINGS, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class MetalReceiptSuccessNotificationTests(InventoryNotificationAssertions, TestCase):
    event_code = SEMI

    @override_settings(TUBE_OUTSOURCING_ENABLED=False)
    def test_legacy_metal_success_and_replay(self):
        from apps.inventory.tests.test_internal_receipt_api import InternalReceiptApiTests
        from apps.inventory.tests.test_public_stock_services import PublicStockFixture
        self.f = InternalReceiptApiTests()
        PublicStockFixture.setUp(self.f)
        self.prepare_operator_plan_read()
        # 夹具计算使用v3，显式保存版本；领料提交与确认使用两个真实隔离身份。
        self.f.raw_material.color_snapshot = "本色"
        self.f.raw_material.save(update_fields=["color_snapshot"])
        self.f.bom_line.raw_values.update(source_raw_material_id=str(self.f.raw_material.pk), pipe_plan_version=3)
        self.f.bom_line.specification = "20*28*0.8"
        self.f.bom_line.save()
        self.f.credit(200, identity=self.f.pipe(str(self.f.bom_line.raw_bar_length_m)))
        response = self.f.client.get("/api/v1/material-issues/requirements/", dict(
            production_task_id=str(self.f.task.pk), product_line_id=str(self.f.product_line.pk), workshop_id=str(self.f.workshop.pk)))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["blockers"], [])
        requirement = response.data["data"]["items"][0]
        created = self.f.client.post("/api/v1/material-issues/", dict(client_request_id=str(uuid4()),
            schedule_product_id=str(self.f.schedule_product.pk), plan_category="METAL", production_task_id=str(self.f.task.pk),
            product_line_id=str(self.f.product_line.pk), workshop_id=str(self.f.workshop.pk),
            recipient_workshop_employee_id=str(self.f.recipient.pk), issue_at=timezone.now().isoformat(),
            lines=[dict(requirement_id=requirement["requirement_id"], requested_quantity="1002")]), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        issue_url = f'/api/v1/material-issues/{created.data["data"]["id"]}/'
        submitted = self.f.client.post(issue_url + "submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        warehouse = employee("IO_MATERIAL_REVIEWER")
        review_role = grant_role(warehouse, "IO_MATERIAL_REVIEWER", "material_issues.review_materialissue")
        review_role.auth_group.permissions.add(RoleActionGrant.objects.get(role=review_role).permission)
        warehouse.user.groups.add(review_role.auth_group)
        reviewer = APIClient()
        reviewer.force_authenticate(get_user_model().objects.get(pk=warehouse.user_id))
        confirmed = reviewer.post(issue_url + "confirm-issue/", {"request_id": str(uuid4())},
            format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.prepare_receiver("IO_OLD_METAL", "inventory.view_internalsemifinishedreceipt")
        data, etag = self.f.payload(), self.f.preview()["etag"]
        self.assertEqual(self.f.receive(payload=data, etag=etag).status_code, 201)
        self.event(InternalSemiFinishedReceipt.objects.get())
        self.assertEqual(self.f.receive(payload=data, etag=etag).status_code, 200)
        self.assertEqual(NotificationEvent.objects.filter(event_code=SEMI).count(), 1)

    @override_settings(TUBE_OUTSOURCING_ENABLED=True)
    def test_tube_metal_early_branch_success_replay_failure_and_rollback(self):
        from apps.inventory.tests.test_tube_d1_receipts import TubeD1ReceiptTests
        self.f = TubeD1ReceiptTests()
        self.f.setUp()
        self.prepare_receiver("IO_TUBE_METAL", "inventory.view_internalsemifinishedreceipt")
        self.f.d1_post(self.f.d1_payload("101"), expected=400)
        self.assertFalse(NotificationEvent.objects.filter(event_code=SEMI).exists())
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                data, etag = self.f.d1_payload(), self.f.d1_preview()["etag"]
                self.f.d1_post(data, etag=etag)
                self.event(InternalSemiFinishedReceipt.objects.get())
                self.f.d1_post(data, etag=etag, expected=200)
                self.assertEqual(NotificationEvent.objects.filter(event_code=SEMI).count(), 1)
                raise RuntimeError("rollback")
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertFalse(NotificationEvent.objects.filter(event_code=SEMI).exists())


@override_settings(**SETTINGS)
class AssemblyReceiptSuccessNotificationTests(InventoryNotificationAssertions, TestCase):
    event_code = ASSEMBLY

    def setUp(self):
        from apps.inventory.tests.test_assembly_receipts import AssemblyReceiptTests
        self.f = AssemblyReceiptTests()
        self.f.setUp()
        self.prepare_receiver("IO_ASSEMBLY_WAREHOUSE", "inventory.view_finishedgoodsreceipt")

    def test_success_replay_readonly_page_apis_and_revoke(self):
        data, etag = self.f.payload(), self.f.preview()["etag"]
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertEqual(self.f.post(data, etag).status_code, 201)
        receipt = FinishedGoodsReceipt.objects.get()
        event = self.event(receipt)
        self.assertTrue(AssemblyReceiptSource.objects.filter(receipt=receipt).exists())
        self.assertEqual(event.target["route_name"], "finished-goods-inventory")
        self.assertEqual(event.target["params"], {})
        self.assertNotIn("query", event.target)
        self.assertEqual(self.f.post(data, etag).status_code, 200)
        data["received_quantity"] = 1
        self.assertEqual(self.f.post(data, etag).status_code, 409)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        for url in ["/api/v1/finished-goods-inventory/", "/api/v1/finished-goods-records/",
                    "/api/v1/finished-goods-inventory/options/?scope=filters",
                    f"/api/v1/finished-goods-records/{receipt.pk}/"]:
            response = self.reader.get(url)
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.reader.post("/api/v1/assembly-finished-receipts/", {}, format="json").status_code, 403)
        self.assertEqual(self.reader.post("/api/v1/finished-goods-inventory/outbounds/", {}, format="json").status_code, 403)
        self.revoke(event)
        self.assertEqual(self.reader.get("/api/v1/finished-goods-records/").status_code, 403)

    def test_failure_and_outer_rollback_leave_no_receipt_source_event_or_delivery(self):
        response = self.f.post(self.f.payload(quantity_per_box=1))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(NotificationEvent.objects.exists())
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.assertEqual(self.f.post().status_code, 201)
                self.event(FinishedGoodsReceipt.objects.get())
                raise RuntimeError("rollback")
        for model in (FinishedGoodsReceipt, AssemblyReceiptSource, NotificationEvent, NotificationDelivery):
            self.assertFalse(model.objects.exists())

    def test_missing_read_permission_filters_receiver_and_generic_receipt_is_not_assembly(self):
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.role.auth_group.permissions.clear()
        self.assertEqual(self.f.post().status_code, 201)
        event = NotificationEvent.objects.get(event_code=ASSEMBLY)
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.assertFalse(event.recipients.exists())
        from apps.inventory.tests.test_inventory_api import FinishedGoodsInventoryApiTests
        payload = FinishedGoodsInventoryApiTests.receipt_payload(self.f, received_quantity=1, expected_received_total=10,
            quantity_per_box=None)
        response = self.f.client.post("/api/v1/finished-goods-inventory/receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        generic = FinishedGoodsReceipt.objects.exclude(pk=event.object_id).get()
        self.assertIsNone(current_inventory_object(ASSEMBLY, generic.pk))
        self.assertEqual(NotificationEvent.objects.count(), 1)

    def test_stock_consumption_does_not_expire_successful_inbound_fact(self):
        self.assertEqual(self.f.post().status_code, 201)
        receipt = FinishedGoodsReceipt.objects.get()
        event = self.event(receipt)
        data = dict(responsible_employee_id=str(self.f.employee.pk), shipment_date=str(timezone.localdate()),
            items=[dict(receipt_id=str(receipt.pk), expected_remaining_quantity=10, outbound_quantity=2, quantity_per_box=3)])
        response = self.f.client.post("/api/v1/finished-goods-inventory/outbounds/", data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        receipt.refresh_from_db()
        self.assertEqual(receipt.remaining_quantity, 8)
        self.assertEqual(inventory_event_version(ASSEMBLY, receipt), event.object_version)
        self.assertTrue(recipient_payload(event.recipients.get(), self.member.user)["target_accessible"])


@override_settings(**SETTINGS)
class OutboundSuccessNotificationTests(InventoryNotificationAssertions, TestCase):
    event_code = OUTBOUND

    def setUp(self):
        from apps.inventory.tests.test_finished_outbound import FinishedOutboundTests
        self.f = FinishedOutboundTests()
        self.f.setUp()
        self.prepare_receiver("IO_FACTORY", "inventory.view_finishedgoodsoutbound")

    def test_actual_debit_stale_resubmit_fixed_detail_and_revoked_reader(self):
        data = self.f.payload()
        self.assertFalse(NotificationEvent.objects.exists())
        response = self.f.client.post(self.f.url, data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        outbound = FinishedGoodsOutbound.objects.get()
        self.assertEqual(FinishedGoodsReceipt.objects.get().remaining_quantity, 4)
        event = self.event(outbound)
        self.assertEqual(event.target["params"], {"outboundId": str(outbound.pk)})
        self.assertNotIn("quantity", event.context)
        self.assertEqual(self.reader.get(self.f.url + str(outbound.pk) + "/").status_code, 200)
        self.assertEqual(self.f.client.post(self.f.url, data, format="json").status_code, 409)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.revoke(event)
        self.assertEqual(self.reader.get(self.f.url + str(outbound.pk) + "/").status_code, 403)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
    def test_public_flow_uses_same_hook_and_rolls_back_debit_with_notification(self):
        data = self.f.payload()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                response = self.f.client.post(self.f.url, data, format="json")
                self.assertEqual(response.status_code, 201, response.data)
                self.event(FinishedGoodsOutbound.objects.get())
                raise RuntimeError("rollback")
        self.assertEqual(FinishedGoodsReceipt.objects.get().remaining_quantity, 6)
        for model in (FinishedGoodsOutbound, NotificationEvent, NotificationDelivery):
            self.assertFalse(model.objects.exists())

    def test_invalid_stock_and_sample_source_never_emit_outbound_success(self):
        data = self.f.payload()
        data["items"][0]["outbound_quantity"] = 7
        self.assertEqual(self.f.client.post(self.f.url, data, format="json").status_code, 400)
        # 仅隔离库边界夹具：样品库存应被原出库服务拒绝，不能混成装配入库。
        receipt = FinishedGoodsReceipt.objects.get()
        FinishedGoodsReceipt.objects.filter(pk=receipt.pk).update(source_type="SAMPLE_INVENTORY")
        self.assertIsNone(current_inventory_object(ASSEMBLY, receipt.pk))
        data["items"][0]["outbound_quantity"] = 2
        self.assertEqual(self.f.client.post(self.f.url, data, format="json").status_code, 409)
        self.assertFalse(FinishedGoodsOutbound.objects.exists())
        self.assertFalse(NotificationEvent.objects.exists())
