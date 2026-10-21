"""07已确认增量：真实损耗记录、返回岗位及事务；全部限独占测试库。"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.outsourcing.models import OutsourcingRawReturn, TubeOutsourcingReceiptLine
from apps.wecom.models import NotificationEvent
from apps.wecom.notification_selectors import recipient_payload

from .test_notifications import SETTINGS, create_rule
from .test_workshop_notifications import receiver


@override_settings(**SETTINGS, PUBLIC_STOCK_FLOW_ENABLED=False)
class RegularLossAndWarehouseReturnTests(TestCase):
    def setUp(self):
        from apps.outsourcing.tests.test_material_flow import MaterialFlowApiTests
        self.f = MaterialFlowApiTests()
        self.f.setUp()
        self.manager, self.role = receiver("U07_LOSS_MANAGER", "outsourcing.view_outsourcingorder")
        create_rule("OUTSOURCING_LOSS_RECORDED", self.f.f.employee, [self.role.role_code])

    def test_persisted_loss_and_scrap_keep_units_replay_and_rollback(self):
        order_id = self.f.create()
        _, source = self.f.dispatch(order_id)
        self.assertFalse(NotificationEvent.objects.filter(event_code="OUTSOURCING_LOSS_RECORDED").exists())
        payload = {"request_id": str(uuid4()), "entries": [self.f.entry(source, "RAW_INPUT", "1"),
            self.f.entry(source, "RAW_LOSS", "1"), self.f.entry(source, "OUTPUT_SCRAP", "1")]}
        self.f.post(order_id, "confirm-reconciliation", payload)
        events = NotificationEvent.objects.filter(event_code="OUTSOURCING_LOSS_RECORDED")
        self.assertEqual(events.count(), 2)  # 投入不是损耗，根与支不得混加。
        self.assertEqual(set(event.context["unit"] for event in events), {"根", "支"})
        for event in events:
            self.assertEqual(event.object_type, "outsourcing.OutsourcingReconciliationEntry")
            self.assertEqual(event.recipients.get().employee_id, self.manager.pk)
            self.assertEqual(event.recipients.get().deliveries.count(), 2)
            self.assertEqual(event.target["params"], {"orderId": str(order_id)})
        self.f.post(order_id, "confirm-reconciliation", payload)
        self.assertEqual(events.all().count(), 2)
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.f.reconcile(order_id, source, "RAW_LOSS", "1")
                self.assertEqual(events.all().count(), 3)
                raise RuntimeError("rollback")
        self.assertEqual(events.all().count(), 2)
        RoleActionGrant.objects.filter(role=self.role).delete()
        self.assertFalse(recipient_payload(events.first().recipients.get(), self.manager.user)["target_accessible"])

    def test_warehouse_existing_raw_return_button_api_and_stock_with_minimal_grant(self):
        order_id = self.f.create()
        _, source = self.f.dispatch(order_id)
        warehouse, role = receiver("U07_RAW_RETURN_KEEPER", "outsourcing.view_outsourcingorder")
        RoleActionGrant.objects.filter(role=role).update(scope="STOCK")
        client = APIClient()
        client.force_authenticate(warehouse.user)
        url = f"/api/v1/outsourcing-orders/{order_id}/"
        before = client.get(url)
        self.assertEqual(before.status_code, 200, before.data)
        self.assertFalse(before.data["data"]["can_return_raw"])
        data = {"request_id": str(uuid4()), "factory_id": str(self.f.f.factory.pk), "reason": "未使用整料退回",
            "lines": [{"dispatch_line_id": str(source.pk), "quantity": "1"}]}
        rejected = client.post(url + "confirm-raw-return/", data, format="json", HTTP_IF_MATCH=before["ETag"])
        self.assertEqual(rejected.status_code, 403, rejected.data)
        permission = Permission.objects.get(content_type__app_label="outsourcing", codename="return_raw_outsourcingorder")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.set(role.action_grants.values_list("permission_id", flat=True))
        # 正常Session每次请求重新加载User；不让force_authenticate保留上一请求的权限缓存。
        client.force_authenticate(get_user_model().objects.get(pk=warehouse.user.pk))
        detail = client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(detail.data["data"]["can_return_raw"])
        self.f.pipe_balance.refresh_from_db()
        quantity_before = self.f.pipe_balance.quantity
        returned = client.post(url + "confirm-raw-return/", data, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(returned.status_code, 200, returned.data)
        self.f.pipe_balance.refresh_from_db()
        self.assertEqual(self.f.pipe_balance.quantity, quantity_before + 1)
        replay = client.post(url + "confirm-raw-return/", data, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.f.pipe_balance.refresh_from_db()
        self.assertEqual(self.f.pipe_balance.quantity, quantity_before + 1)
        self.assertEqual(OutsourcingRawReturn.objects.count(), 1)
        self.assertFalse(NotificationEvent.objects.filter(event_code="OUTSOURCING_LOSS_RECORDED").exists())
        self.assertFalse(warehouse.user.has_perm("outsourcing.confirm_dispatch_outsourcingorder"))


@override_settings(**SETTINGS, TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeShortageNotificationTests(TestCase):
    def setUp(self):
        from apps.outsourcing.tests.test_tube_receipts_api import TubeReceiptsApiTests
        self.f = TubeReceiptsApiTests()
        self.f.setUp()
        self.manager, self.role = receiver("U07_TUBE_DIFF_MANAGER", "outsourcing.view_outsourcingorder")
        create_rule("TUBE_OUTSOURCING_SHORTAGE_RECORDED", self.f.employee, [self.role.role_code])
        self.warehouse, _ = receiver("U07_TUBE_RETURN_KEEPER", "outsourcing.confirm_return_outsourcingorder")
        self.client = APIClient()
        self.client.force_authenticate(self.warehouse.user)

    def test_real_shortage_final_receipt_independent_of_dispatch_source_and_idempotent(self):
        for source_kind in ("RAW_PIPE", "METAL"):
            with self.subTest(source_kind=source_kind):
                order = self.f.dispatched(source_kind, "20")
                payload = self.f.receipt_payload(order, "18", "少回2支")
                saved = self.f.receive_final(order, payload, client=self.client)
                self.assertEqual(saved.status_code, 201, saved.data)
                line = TubeOutsourcingReceiptLine.objects.get(receipt__order_id=order["id"])
                event = NotificationEvent.objects.get(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED", object_id=str(line.pk))
                self.assertEqual(event.context["quantity"], "2")
                self.assertEqual(event.context["unit"], "支")
                self.assertEqual(event.recipients.get().employee_id, self.manager.pk)
                self.assertEqual(event.target["params"], {"orderId": order["id"]})
                self.assertTrue(recipient_payload(event.recipients.get(), self.manager.user)["target_accessible"])
                self.f.receive_final(order, payload, client=self.client, expected=200)
                self.assertEqual(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED",
                    object_id=str(line.pk)).count(), 1)
                changed = {**payload, "remark": "同请求换内容"}
                self.f.receive_final(order, changed, client=self.client, expected=409)
        self.assertEqual(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED").count(), 2)

    def test_full_receipt_does_not_notify_and_failed_transaction_does_not_keep_shortage(self):
        order = self.f.dispatched("RAW_PIPE", "20")
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.f.receive_final(order, self.f.receipt_payload(order, "18", "少回"), client=self.client)
                self.assertTrue(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED").exists())
                raise RuntimeError("rollback")
        self.assertFalse(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED").exists())
        self.f.receive_final(order, self.f.receipt_payload(order, "20", ""), client=self.client)
        self.assertFalse(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_SHORTAGE_RECORDED").exists())
