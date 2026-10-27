"""07领料及两类真实委外对象，重点检查来源/车间授权及重试。"""
from uuid import uuid4
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.wecom.models import NotificationEvent
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_selectors import recipient_payload
from apps.workshop_config.models import Workshop

from .test_notifications import SETTINGS, create_rule
from .test_workshop_notifications import receiver


@override_settings(**SETTINGS)
class IssueNotificationTests(TestCase):
    def setUp(self):
        from apps.material_issues.tests.test_material_issue_api import MaterialIssueApiTests
        self.f = MaterialIssueApiTests()
        self.f.setUp()
        # 原夹具创建计划已产生06事件；本类只断言领料事件，不清理该历史快照。
        self.warehouse, self.role = receiver("U07_WAREHOUSE", "material_issues.review_materialissue")
        create_rule("MATERIAL_ISSUE_SUBMITTED", self.f.employee, [self.role.role_code])

    def test_submit_real_api_leaves_stock_unchanged_and_rejects_cross_workshop(self):
        from apps.inventory.models import MaterialStockMovement
        created = self.f._create_issue("10")
        issue_id = created.data["data"]["id"]
        self.assertFalse(NotificationEvent.objects.filter(event_code="MATERIAL_ISSUE_SUBMITTED").exists())
        before = MaterialStockMovement.objects.count()
        submitted = self.f.client.post(f"/api/v1/material-issues/{issue_id}/submit/", {},
            format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        event = NotificationEvent.objects.get(event_code="MATERIAL_ISSUE_SUBMITTED")
        self.assertEqual(event.recipients.get().employee_id, self.warehouse.pk)
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
        self.assertEqual(before, MaterialStockMovement.objects.count())
        replay = self.f.client.post(f"/api/v1/material-issues/{issue_id}/submit/", {},
            format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(replay.status_code, 412, replay.data)
        self.assertEqual(NotificationEvent.objects.filter(event_code="MATERIAL_ISSUE_SUBMITTED").count(), 1)
        other_workshop = Workshop.objects.get_or_create(name="车缝车间")[0]
        other, _ = receiver("U07_OTHER_DIRECTOR", "material_issues.review_materialissue", workshop=other_workshop)
        client = APIClient()
        client.force_authenticate(other.user)
        rejected = client.post(f"/api/v1/material-issues/{issue_id}/return/", {"reason": "跨车间"},
            format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertIn(rejected.status_code, (403, 404), rejected.data)
        warehouse_client = APIClient()
        warehouse_client.force_authenticate(self.warehouse.user)
        returned = warehouse_client.post(f"/api/v1/material-issues/{issue_id}/return/", {"reason": "修改数量"},
            format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertFalse(recipient_payload(event.recipients.get(), self.warehouse.user)["target_accessible"])


@override_settings(**SETTINGS, TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeCreationNotificationTests(TestCase):
    def setUp(self):
        from apps.outsourcing.tests.test_tube_orders_api import TubeOrdersApiTests
        self.f = TubeOrdersApiTests()
        self.f.setUp()
        self.warehouse, self.warehouse_role = receiver("U07_TUBE_STOCK", "outsourcing.confirm_dispatch_outsourcingorder")
        RoleActionGrant.objects.filter(role=self.warehouse_role).update(scope="STOCK")
        self.metal, self.metal_role = receiver("U07_TUBE_METAL", "outsourcing.confirm_dispatch_outsourcingorder", workshop=self.f.workshop)
        sewing = Workshop.objects.get_or_create(name="车缝车间")[0]
        self.sewing, self.sewing_role = receiver("U07_TUBE_SEWING", "outsourcing.confirm_dispatch_outsourcingorder", workshop=sewing)
        create_rule("TUBE_OUTSOURCING_ORDER_CREATED", self.f.employee,
            [self.warehouse_role.role_code, self.metal_role.role_code, self.sewing_role.role_code])

    def test_stock_source_only_notifies_stock_handler_and_replay_is_single(self):
        data = self.f.order_payload()
        created = self.f.post_order(data)
        event = NotificationEvent.objects.get(event_code="TUBE_OUTSOURCING_ORDER_CREATED")
        self.assertEqual(event.object_type, "outsourcing.TubeOutsourcingOrder")
        self.assertEqual(event.object_id, created.data["data"]["id"])
        self.assertEqual(event.recipients.get().employee_id, self.warehouse.pk)
        self.assertEqual(event.target["route_name"], "warehouse-outsourcing-tube-detail")
        self.assertEqual(event.target["params"], {"id": created.data["data"]["id"]})
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            self.assertFalse(recipient_payload(event.recipients.get(), self.warehouse.user)["target_accessible"])
        self.assertFalse(event_object_accessible("OUTSOURCING_ORDER_CREATED", event.object_id, self.warehouse.user))
        self.f.post_order(data, expected=200)
        self.assertEqual(NotificationEvent.objects.filter(event_code="TUBE_OUTSOURCING_ORDER_CREATED").count(), 1)
        role_grant = RoleActionGrant.objects.get(role=self.warehouse_role)
        role_grant.delete()
        self.assertFalse(recipient_payload(event.recipients.get(), self.warehouse.user)["target_accessible"])
        client = APIClient()
        client.force_authenticate(self.warehouse.user)
        target_response = client.get(reverse("notification-target", kwargs={"recipient_id": event.recipients.get().pk}))
        self.assertEqual(target_response.status_code, 404, target_response.data)

    def test_direct_metal_uses_warehouse_page_and_preserves_dispatch_resource_scope(self):
        response = self.f.post_order(self.f.order_payload("METAL"))
        event = NotificationEvent.objects.get(event_code="TUBE_OUTSOURCING_ORDER_CREATED")
        self.assertEqual(event.recipients.get().employee_id, self.metal.pk)
        self.assertEqual(event.target["route_name"], "warehouse-outsourcing-tube-detail")
        self.assertEqual(event.target["params"], {"id": response.data["data"]["id"]})
        self.assertTrue(recipient_payload(event.recipients.get(), self.metal.user)["target_accessible"])
        client = APIClient()
        client.force_authenticate(self.warehouse.user)
        action_url = reverse("tube-outsourcing-order-confirm-dispatch", kwargs={"pk": response.data["data"]["id"]})
        result = client.post(action_url,
            {"client_request_id": str(uuid4()), "actual_dispatch_date": "2026-10-21"},
            format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(result.status_code, 404, result.data)
        self.assertIn("error", result.data)  # 来自真实动作的对象范围拒绝，不是访问了不存在的URL。

    def test_old_target_resolves_warehouse_page_without_rewriting_notification(self):
        for source, member in (
            ("RAW_PIPE", self.warehouse),
            ("METAL", self.metal),
        ):
            with self.subTest(source=source):
                created = self.f.post_order(self.f.order_payload(source))
                order_id = created.data["data"]["id"]
                event = NotificationEvent.objects.get(event_code="TUBE_OUTSOURCING_ORDER_CREATED", object_id=order_id)
                old_target = {**event.target, "route_name": "workshop-outsourcing-tube-detail", "params": {"orderId": order_id}}
                event.target = old_target
                event.save(update_fields=["target"])
                client = APIClient()
                client.force_authenticate(member.user)
                result = client.get(reverse("notification-target", kwargs={"recipient_id": event.recipients.get().pk}))
                self.assertEqual(result.status_code, 200, result.data)
                self.assertEqual(result.data["data"]["target"]["route_name"], "warehouse-outsourcing-tube-detail")
                self.assertEqual(result.data["data"]["target"]["params"], {"id": order_id})
                event.refresh_from_db()
                self.assertEqual(event.target, old_target)

    def test_create_rollback_keeps_no_order_event_or_reservation(self):
        from apps.outsourcing.models import TubeOutsourcingOrder
        data = self.f.order_payload()
        before = NotificationEvent.objects.count()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.f.post_order(data)
                raise RuntimeError("rollback")
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        self.assertEqual(NotificationEvent.objects.count(), before)


@override_settings(**SETTINGS, TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class SewingCreationNotificationTests(TestCase):
    def test_sewing_creation_and_old_notification_target_use_warehouse_page(self):
        from apps.outsourcing.tests.test_cutting_tube_orders import CuttingTubeOrdersTests

        fixture = CuttingTubeOrdersTests()
        fixture.setUp()
        fixture.report()
        member, role = receiver("U07_SEWING_DISPATCH", "outsourcing.confirm_dispatch_outsourcingorder",
            workshop=fixture.sewing_workshop)
        create_rule("TUBE_OUTSOURCING_ORDER_CREATED", fixture.employee, [role.role_code])
        response = fixture.create(fixture.payload())
        order_id = response.data["data"]["id"]
        event = NotificationEvent.objects.get(event_code="TUBE_OUTSOURCING_ORDER_CREATED", object_id=order_id)
        self.assertEqual(event.target["route_name"], "warehouse-outsourcing-tube-detail")
        self.assertEqual(event.target["params"], {"id": order_id})
        self.assertEqual(event.recipients.get().employee_id, member.pk)
        old_target = {**event.target, "route_name": "workshop-outsourcing-tube-detail", "params": {"orderId": order_id}}
        event.target = old_target
        event.save(update_fields=["target"])
        client = APIClient()
        client.force_authenticate(member.user)
        result = client.get(reverse("notification-target", kwargs={"recipient_id": event.recipients.get().pk}))
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"]["target"]["route_name"], "warehouse-outsourcing-tube-detail")
        self.assertEqual(result.data["data"]["target"]["params"], {"id": order_id})
        event.refresh_from_db()
        self.assertEqual(event.target, old_target)


@override_settings(**SETTINGS)
class HistoricalRegularNotificationTests(TestCase):
    def setUp(self):
        from apps.outsourcing.tests.test_outsourcing_source_bom_api import OutsourcingOrderWriteApiTests
        self.f = OutsourcingOrderWriteApiTests()
        self.f.setUp()
        self.warehouse, self.role = receiver("U07_REGULAR_STOCK", "outsourcing.confirm_dispatch_outsourcingorder")
        RoleActionGrant.objects.filter(role=self.role).update(scope="STOCK")
        self.metal, self.metal_role = receiver("U07_REGULAR_METAL", "outsourcing.confirm_dispatch_outsourcingorder",
            workshop=Workshop.objects.get_or_create(name="金工车间")[0])
        create_rule("OUTSOURCING_ORDER_CREATED", self.f.employee, [self.role.role_code, self.metal_role.role_code])

    def test_historical_regular_object_notification_uses_warehouse_route(self):
        from apps.outsourcing.models import OutsourcingOrder
        from apps.wecom.workshop_notifications import outsourcing_created

        payload = self.f.current_fabric_payload()
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order = OutsourcingOrder.objects.get(pk=response.data["data"]["id"])
        with patch("apps.wecom.workshop_notifications.timezone.localtime", return_value=order.created_at):
            outsourcing_created(order, self.f.employee)
        event = NotificationEvent.objects.get(event_code="OUTSOURCING_ORDER_CREATED")
        self.assertEqual(event.object_type, "outsourcing.OutsourcingOrder")
        self.assertEqual(event.target["route_name"], "warehouse-outsourcing-detail")
        self.assertEqual(event.target["params"], {"orderId": response.data["data"]["id"]})
        self.assertEqual(event.recipients.get().employee_id, self.warehouse.pk)
        self.assertFalse(event_object_accessible("TUBE_OUTSOURCING_ORDER_CREATED", event.object_id, self.warehouse.user))
        with patch("apps.wecom.workshop_notifications.timezone.localtime", return_value=order.created_at):
            outsourcing_created(order, self.f.employee)
        self.assertEqual(NotificationEvent.objects.filter(event_code="OUTSOURCING_ORDER_CREATED").count(), 1)
        old_target = {**event.target, "route_name": "workshop-outsourcing-detail"}
        event.target = old_target
        event.save(update_fields=["target"])
        client = APIClient()
        client.force_authenticate(self.warehouse.user)
        result = client.get(reverse("notification-target", kwargs={"recipient_id": event.recipients.get().pk}))
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"]["target"]["route_name"], "warehouse-outsourcing-detail")
        self.assertEqual(result.data["data"]["target"]["params"], {"orderId": response.data["data"]["id"]})
        event.refresh_from_db()
        self.assertEqual(event.target, old_target)
