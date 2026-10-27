import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.inventory.models import SemiFinishedStockBalance, WarehouseZone
from apps.organizations.models import Employee
from apps.outsourcing.models import OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingReturn, OutsourcingReturnLine
from apps.material_issues.models import (
    MetalProcessingExternalClosure, MetalProcessingExternalGoodReturn,
    MetalProcessingExternalOrder, MetalProcessingExternalOrderStatus,
    MetalProcessingOriginalHandoff, MetalProcessingRework,
    MetalProcessingUnsprayedReturn,
)
from apps.outsourcing.tests.test_material_flow import MaterialFlowFixture

from .test_metal_processing import ProcessingFixture


class MetalProcessingP4Fixture(ProcessingFixture):
    def setUp(self):
        super().setUp()
        original_payload = self.f.spray_payload()
        original_payload["products"][0]["processing_items"][0]["quantity"] = "402"
        original_payload["products"][0]["processing_items"][0]["allocations"][0]["allocated_quantity"] = "402"
        original_payload["products"][0]["processing_items"][0]["allocations"][0]["input_quantity"] = "402"
        original_payload["products"][0]["materials"][0]["planned_issue_quantity"] = "402"
        original_response = self.f.create_order(original_payload)
        self.assertEqual(original_response.status_code, 201, original_response.data)
        self.original_order = original_response.data["data"]["id"]
        self.write("completions", self.complete_payload(12))

    def post(self, url, payload, expected=200, etag=None):
        response = self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag or '"invalid"')
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def source_etag(self):
        return self.detail()["ETag"]

    def create_original_handoff(self, pieces=8):
        response = self.post(
            f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
            {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
             "factory_id": str(self.f.factory.pk), "handoff_pieces": pieces,
             "handoff_date": str(timezone.localdate())}, etag=self.source_etag(),
        )
        self.assertEqual(response.data["data"]["dispatched_pieces"], pieces)
        return MetalProcessingOriginalHandoff.objects.get(source__issue_line=self.line)

    def create_rework(self, pieces=5):
        handoff = self.create_original_handoff()
        returned = self.post(
            f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "returned_pieces": pieces,
             "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存架 B-03",
             "return_date": str(timezone.localdate()), "remark": "未喷塑退回"}, etag=self.source_etag(),
        )
        self.assertEqual(returned.data["data"]["inventory_effect"], "NONE")
        record = MetalProcessingUnsprayedReturn.objects.get(pk=returned.data["data"]["id"])
        rework = self.post(
            f"/api/v1/metal-processing-unsprayed-returns/{record.pk}/rework/",
            {"request_id": str(uuid.uuid4()), "completed_pieces": pieces,
             "completion_date": str(timezone.localdate())}, etag='"ignored"',
        )
        return record, MetalProcessingRework.objects.get(pk=rework.data["data"]["id"])

    def create_order(self, pieces=5):
        _returned, rework = self.create_rework(pieces)
        response = self.post(
            f"/api/v1/metal-processing-reworks/{rework.pk}/orders/",
            {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
             "craft_id": str(self.f.spray.pk), "allocated_pieces": pieces}, etag='"ignored"', expected=201,
        )
        return MetalProcessingExternalOrder.objects.get(pk=response.data["data"]["id"])


# P4 旧完成登记夹具不含 D1 工价报工；显式验证保留旧流程，不受运行环境开关影响。
@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingP4ApiTests(MetalProcessingP4Fixture, APITestCase):
    def original_good_context(self, handoff):
        response = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("good_return_context", response.data["data"])
        return response.data["data"]["good_return_context"]

    def original_good_payload(self, pieces=3, **changes):
        return {"request_id": str(uuid.uuid4()), "good_pieces": pieces,
                "zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
                "return_date": str(timezone.localdate()), "remark": "原单合格回货", **changes}

    def test_original_direct_good_return_uses_actual_handoff_without_raw_dispatch(self):
        from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, SemiFinishedStockMovement
        from apps.outsourcing.models import OutsourcingDispatch, OutsourcingReconciliation
        handoff = self.create_original_handoff(8)
        raw_before = {model.__name__: list(model.objects.order_by("pk").values())
                      for model in (MaterialStockBalance, MaterialStockMovement)}
        context = self.original_good_context(handoff)
        self.assertEqual(context["original_order_status"], "PROCESSING")
        self.assertEqual((context["handoff_pieces"], context["remaining_return_pieces"]), (8, 8))
        payload = self.original_good_payload(3)
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        result = self.post(url, payload, etag=context["etag"]).data["data"]
        self.assertEqual((result["returned_good_pieces"], result["remaining_return_pieces"]), (3, 5))
        self.assertEqual(result["original_order_status"], "PARTIAL_RETURN")
        self.assertEqual(result["good_returns"][0]["good_pieces"], 3)
        self.assertRegex(OutsourcingReturn.objects.get().return_number,
            rf"^WH{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        self.post(url, payload, etag=context["etag"])
        self.assertEqual(OutsourcingReturn.objects.count(), 1)
        self.assertEqual(SemiFinishedStockMovement.objects.count(), 1)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 3)
        self.assertFalse(OutsourcingDispatch.objects.exists())
        self.assertFalse(OutsourcingReconciliation.objects.exists())
        self.assertEqual(raw_before, {model.__name__: list(model.objects.order_by("pk").values())
                                     for model in (MaterialStockBalance, MaterialStockMovement)})

    def test_direct_handoff_legacy_actions_are_explicitly_locked(self):
        self.create_original_handoff(8)
        detail = self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(detail.data["data"].get("direct_handoff"))
        for name in ("can_cancel", "can_delete", "can_edit", "can_confirm_dispatch", "can_confirm_return", "can_return_raw", "can_reconcile", "can_complete"):
            self.assertFalse(detail.data["data"][name], name)
        # 历史直接交接仍可能显示待外发；门禁不能只依赖新状态。
        OutsourcingOrder.objects.filter(pk=self.original_order).update(status="PENDING_DISPATCH")
        detail = self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/")
        response = self.client.post(f"/api/v1/outsourcing-orders/{self.original_order}/cancel/",
            {"reason": "不能取消已交接实物"}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("直接交接", str(response.data))
        response = self.client.delete(f"/api/v1/outsourcing-orders/{self.original_order}/", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("直接交接", str(response.data))

    def test_original_good_return_aggregates_multiple_handoffs_and_both_return_routes(self):
        first = self.create_original_handoff(5)
        self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
            {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
             "factory_id": str(self.f.factory.pk), "handoff_pieces": 7, "handoff_date": str(timezone.localdate())},
            etag=self.source_etag())
        context = self.original_good_context(first)
        self.assertEqual(context["handoff_pieces"], 12)
        url = f"/api/v1/metal-processing-handoffs/{first.pk}/good-returns/"
        context = self.post(url, self.original_good_payload(6), etag=context["etag"]).data["data"]
        # 本次回货可大于所选单次交接5，使用同allocation累计12上限。
        self.post(f"/api/v1/metal-processing-handoffs/{first.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "returned_pieces": 2, "received_by_employee_id": str(self.f.employee.pk),
             "storage_location": "金工暂存", "return_date": str(timezone.localdate())}, etag=self.source_etag())
        self.post(url, self.original_good_payload(1), expected=412, etag=context["etag"])
        fresh = self.original_good_context(first)
        self.assertEqual((fresh["returned_good_pieces"], fresh["returned_unsprayed_pieces"], fresh["remaining_return_pieces"]), (6, 2, 4))
        self.post(url, self.original_good_payload(5), expected=409, etag=fresh["etag"])
        final = self.post(url, self.original_good_payload(4), etag=fresh["etag"]).data["data"]
        self.assertEqual(final["remaining_return_pieces"], 0)
        self.assertFalse(final["can_return"])
        self.assertEqual(final["original_order_status"], "PARTIAL_RETURN")
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 10)
        self.post(url, self.original_good_payload(1), expected=409, etag=final["etag"])

    def test_original_good_return_after_source_close_and_legacy_pending_order(self):
        handoff = self.create_original_handoff(8)
        closed = self.write("close", {"request_id": str(uuid.uuid4()), "remark": "金工来源结清"}).data["data"]["closure"]
        OutsourcingOrder.objects.filter(pk=self.original_order).update(status="PENDING_DISPATCH")
        context = self.original_good_context(handoff)
        self.assertEqual(OutsourcingOrder.objects.get(pk=self.original_order).status, "PENDING_DISPATCH")
        result = self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/",
            self.original_good_payload(8), etag=context["etag"]).data["data"]
        self.assertEqual(result["original_order_status"], "PARTIAL_RETURN")
        self.assertEqual(self.detail().data["data"]["closure"], closed)

    def test_original_good_return_rejects_invalid_inputs_stale_and_missing_version(self):
        handoff = self.create_original_handoff(8)
        context = self.original_good_context(handoff)
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        for pieces in (0, -1, "1.1", "1.0", True):
            self.post(url, self.original_good_payload(pieces), expected=400, etag=context["etag"])
        for fields in ({"zone_id": str(self.f.defective_zone.pk)}, {"good_pieces": 9}, {"raw_inputs": []}):
            self.post(url, self.original_good_payload(**fields), expected=409 if fields.get("good_pieces") else 400, etag=context["etag"])
        self.post(url, self.original_good_payload(), expected=412, etag='"stale"')
        response = self.client.post(url, self.original_good_payload(), format="json")
        self.assertEqual(response.status_code, 428, response.data)
        self.assertFalse(OutsourcingReturn.objects.exists())
        self.assertFalse(SemiFinishedStockBalance.objects.exists())
        payload = self.original_good_payload()
        self.post(url, payload, etag=context["etag"])
        payload["good_pieces"] = 4
        self.post(url, payload, expected=409, etag=context["etag"])

    def test_original_good_return_has_exact_permission_and_independent_data_scope(self):
        handoff = self.create_original_handoff(8)
        context = self.original_good_context(handoff)
        user = get_user_model().objects.create_user(username="original-good-only")
        Employee.objects.create(user=user, employee_code="ORIGINAL-GOOD", display_name="原单回货员")
        user.user_permissions.add(*Permission.objects.filter(codename__in=[
            "view_metalprocessingsource", "view_all_materialissue", "view_all_productionschedule"]))
        self.client.force_authenticate(user)
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        self.assertFalse(self.original_good_context(handoff)["can_return"])
        self.post(url, self.original_good_payload(), expected=403, etag=context["etag"])
        user.user_permissions.add(Permission.objects.get(content_type__app_label="outsourcing", codename="confirm_return_outsourcingorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.assertFalse(user.has_perm("outsourcing.view_outsourcingorder"))
        self.post(url, self.original_good_payload(), etag=context["etag"])
        user.user_permissions.remove(Permission.objects.get(codename="view_all_productionschedule"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.post(url, self.original_good_payload(), expected=404, etag=context["etag"])

    def test_original_good_return_requires_session_csrf_and_rejects_cross_route_replay(self):
        from django.middleware.csrf import _get_new_csrf_string
        handoff = self.create_original_handoff(8)
        context = self.original_good_context(handoff)
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        client = APIClient(enforce_csrf_checks=True)
        payload = self.original_good_payload(3)
        self.assertEqual(client.post(url, payload, format="json").status_code, 401)
        client.force_login(self.f.user)
        self.assertEqual(client.post(url, payload, format="json", HTTP_IF_MATCH=context["etag"]).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies["csrftoken"] = csrf
        response = client.post(url, payload, format="json", HTTP_IF_MATCH=context["etag"], HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.data)
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        MaterialFlowFixture.post(self, self.original_order, "confirm-return", {
            "request_id": payload["request_id"], "factory_id": str(self.f.factory.pk),
            "good_zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
            "return_date": str(timezone.localdate()), "lines": [{"allocation_id": str(allocation.pk),
                "good_quantity": "3", "defective_quantity": "0"}]}, expected=409)
        self.assertEqual(OutsourcingReturn.objects.count(), 1)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 3)

    def test_original_good_return_freezes_identity_and_blocks_incompatible_peer(self):
        from apps.boms.models import BomLine
        handoff = self.create_original_handoff(8)
        frozen = handoff.snapshot["stock_identity"].copy()
        BomLine.objects.filter(pk=frozen["bom_line_id"]).update(part_name="后改部位名", unit="米",
            raw_values={"color": "后改颜色"})
        context = self.original_good_context(handoff)
        self.assertEqual(context["part_name"], frozen["part_name"])
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        self.post(url, self.original_good_payload(3), etag=context["etag"])
        balance = SemiFinishedStockBalance.objects.get()
        self.assertEqual((str(balance.unit_id), balance.color_snapshot, str(balance.bom_line_id)),
                         (frozen["unit_id"], frozen["color"], frozen["bom_line_id"]))
        other = MetalProcessingOriginalHandoff.objects.create(source=handoff.source, original_order=handoff.original_order,
            factory=handoff.factory, handoff_pieces=2, handoff_date=handoff.handoff_date,
            actor_employee=self.f.employee, request_id=uuid.uuid4(), request_payload_hash="b" * 64,
            snapshot={**handoff.snapshot, "stock_identity": {**frozen, "color": "另一颜色"}})
        context = self.original_good_context(other)
        self.assertFalse(context["can_return"])
        self.assertIn("不同冻结", str(context["blockers"]))
        self.post(f"/api/v1/metal-processing-handoffs/{other.pk}/good-returns/", self.original_good_payload(1),
            expected=409, etag=context["etag"])
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 3)

    def test_legacy_raw_endpoints_cannot_mutate_direct_handoff_order(self):
        from apps.outsourcing.models import OutsourcingMaterialItem
        handoff = self.create_original_handoff(8)
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        material = OutsourcingMaterialItem.objects.get(allocation=allocation)
        before = self.unchanged_ledgers()
        actions = {
            "confirm-dispatch": {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk), "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "6"}]},
            "confirm-return": {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                "good_zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
                "return_date": str(timezone.localdate()), "lines": [{"allocation_id": str(allocation.pk), "good_quantity": "1", "defective_quantity": "0"}]},
            "confirm-raw-return": {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk), "reason": "不可退成原料",
                "lines": [{"dispatch_line_id": str(uuid.uuid4()), "quantity": "1"}]},
            "confirm-reconciliation": {"request_id": str(uuid.uuid4()), "entries": [{"allocation_id": str(allocation.pk),
                "dispatch_line_id": None, "kind": "OUTPUT_SCRAP", "quantity": "1", "reason": "不能从旧入口处置"}]},
            "complete": {"request_id": str(uuid.uuid4())},
        }
        for action, payload in actions.items():
            response = MaterialFlowFixture.post(self, self.original_order, action, payload, expected=409)
            self.assertIn("直接交接", str(response.data), action)
        for action in ("dispatch-context", "reconciliation"):
            response = self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/{action}/")
            self.assertEqual(response.status_code, 409, response.data)
        response = self.client.patch(f"/api/v1/outsourcing-orders/{self.original_order}/", {}, format="json")
        self.assertIn(response.status_code, (403, 405))
        self.assertEqual(before, self.unchanged_ledgers())

    def test_return_rework_and_split_new_orders_without_restoring_raw_source(self):
        handoff = self.create_original_handoff(8)
        returned = self.post(
            f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "returned_pieces": 8,
             "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存架 B-03",
             "return_date": str(timezone.localdate())}, etag=self.source_etag(),
        )
        record = MetalProcessingUnsprayedReturn.objects.get(pk=returned.data["data"]["id"])
        rework = self.post(
            f"/api/v1/metal-processing-unsprayed-returns/{record.pk}/rework/",
            {"request_id": str(uuid.uuid4()), "completed_pieces": 8,
             "completion_date": str(timezone.localdate())}, etag='"ignored"',
        )
        rework_id = rework.data["data"]["id"]
        self.post(f"/api/v1/metal-processing-reworks/{rework_id}/orders/",
                  {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                   "craft_id": str(self.f.spray.pk), "allocated_pieces": 3}, etag='"ignored"', expected=201)
        self.post(f"/api/v1/metal-processing-reworks/{rework_id}/orders/",
                  {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                   "craft_id": str(self.f.spray.pk), "allocated_pieces": 5}, etag='"ignored"', expected=201)
        self.assertEqual(MetalProcessingExternalOrder.objects.filter(rework_id=rework_id).count(), 2)
        prefix = f"WF{timezone.localdate():%y%m%d}"
        original_number = OutsourcingOrder.objects.get(pk=self.original_order).order_number
        self.assertRegex(original_number, rf"^{prefix}[0-9]{{3,}}$")
        first_sequence = int(original_number[len(prefix):])
        self.assertSetEqual(set(MetalProcessingExternalOrder.objects.filter(rework_id=rework_id)
            .values_list('order_number', flat=True)),
            {f"{prefix}{first_sequence + offset:03d}" for offset in (1, 2)})
        source = self.line.processing_source
        source.refresh_from_db()
        self.assertEqual((source.completed_pieces, source.dispatched_pieces), (12, 8))
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_new_order_handoff_good_return_close_post_close_and_auto_complete(self):
        order = self.create_order(5)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        handoff = self.post(
            f"/api/v1/metal-processing-external-orders/{order.pk}/handoff/",
            {"request_id": str(uuid.uuid4()), "handoff_pieces": 5,
             "handoff_date": str(timezone.localdate())}, etag=detail.data["data"]["etag"],
        )
        self.assertEqual(handoff.data["data"]["status"], MetalProcessingExternalOrderStatus.PROCESSING)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        returned = self.post(
            f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "good_pieces": 3, "zone_id": str(self.f.semi_zone.pk),
             "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())},
            etag=detail.data["data"]["etag"],
        )
        self.assertEqual(returned.data["data"]["returned_good_pieces"], 3)
        semi_stock = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/semi-stock/")
        self.assertEqual(semi_stock.status_code, 200, semi_stock.data)
        self.assertFalse(semi_stock.data["data"]["batch_selection"])
        self.assertIn("zones", semi_stock.data["data"])
        self.assertFalse(semi_stock.data["data"]["whole_bar_required"])
        self.assertTrue(semi_stock.data["data"]["integer_required"])
        self.assertEqual(semi_stock.data["data"]["available_pieces"], "3.0000")
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        closed = self.post(
            f"/api/v1/metal-processing-external-orders/{order.pk}/close/",
            {"request_id": str(uuid.uuid4()), "remark": "少回货差额已核对"}, etag=detail.data["data"]["etag"],
        )
        self.assertEqual(closed.data["data"]["status"], MetalProcessingExternalOrderStatus.CLOSED)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        extra = self.post(
            f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "good_pieces": 1, "zone_id": str(self.f.semi_zone.pk),
             "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()),
             "remark": "加工厂补回一支"}, etag=detail.data["data"]["etag"],
        )
        self.assertEqual(extra.data["data"]["status"], MetalProcessingExternalOrderStatus.CLOSED)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        final = self.post(
            f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "good_pieces": 1, "zone_id": str(self.f.semi_zone.pk),
             "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()),
             "remark": "加工厂补回最后一支"}, etag=detail.data["data"]["etag"],
        )
        self.assertEqual(final.data["data"]["status"], MetalProcessingExternalOrderStatus.COMPLETED)
        self.assertEqual(MetalProcessingExternalGoodReturn.objects.filter(order=order).count(), 3)
        return_numbers = list(MetalProcessingExternalGoodReturn.objects.filter(order=order)
            .values_list('return_number', flat=True))
        self.assertEqual(len(set(return_numbers)), 3)
        for number in return_numbers:
            self.assertRegex(number, rf"^WH{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        self.assertEqual(MetalProcessingExternalClosure.objects.filter(order=order).count(), 1)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 5)

    def test_return_after_close_requires_reason_and_over_limit_is_blocked(self):
        order = self.create_order(5)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/handoff/",
                  {"request_id": str(uuid.uuid4()), "handoff_pieces": 5, "handoff_date": str(timezone.localdate())},
                  etag=detail.data["data"]["etag"])
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/close/",
                  {"request_id": str(uuid.uuid4()), "remark": "差额结清"}, etag=detail.data["data"]["etag"])
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
                  {"request_id": str(uuid.uuid4()), "good_pieces": 1, "zone_id": str(self.f.semi_zone.pk),
                   "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())},
                  expected=400, etag=detail.data["data"]["etag"])

    def test_create_permission_is_sufficient_without_unrelated_add_permission(self):
        _returned, rework = self.create_rework()
        user = self.f.user
        user.is_superuser = False
        user.save(update_fields=["is_superuser"])
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="material_issues",
            codename__in=["view_all_materialissue", "create_metalprocessingexternalorder"],
        ))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.post(f"/api/v1/metal-processing-reworks/{rework.pk}/orders/",
                  {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                   "craft_id": str(self.f.spray.pk), "allocated_pieces": 5}, expected=201)

    def test_closed_source_cannot_create_another_original_handoff(self):
        self.write("close", {"request_id": str(uuid.uuid4()), "remark": "剩余完成件结清"})
        self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
                  {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
                   "factory_id": str(self.f.factory.pk), "handoff_pieces": 1,
                   "handoff_date": str(timezone.localdate())}, expected=409, etag=self.source_etag())
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_semi_stock_stays_piece_based_after_bom_edit(self):
        order = self.create_order()
        conversion = order.source.source_snapshot["conversion_snapshot"]
        from apps.boms.models import BomLine
        BomLine.objects.filter(pk=conversion["bom_line_id"]).update(pieces_per_bar=3, raw_bar_length_m="1.55")
        response = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/semi-stock/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["data"]["whole_bar_required"])
        self.assertTrue(response.data["data"]["integer_required"])
        self.assertNotIn("pieces_per_bar", response.data["data"])
        self.assertNotIn("raw_bar_length_m", response.data["data"])

    def test_original_handoff_rejects_factory_not_assigned_to_matching_part(self):
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        allocation.processing_item.bom_line_id = self.f.hardware.pk
        allocation.processing_item.save(update_fields=["bom_line"])
        self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
                  {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
                   "factory_id": str(self.f.factory.pk), "handoff_pieces": 1,
                   "handoff_date": str(timezone.localdate())}, expected=400, etag=self.source_etag())
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_original_handoff_rejects_completed_order(self):
        OutsourcingOrder.objects.filter(pk=self.original_order).update(status="COMPLETED")
        self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
                  {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
                   "factory_id": str(self.f.factory.pk), "handoff_pieces": 1,
                   "handoff_date": str(timezone.localdate())}, expected=409, etag=self.source_etag())
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_original_handoff_cannot_exceed_matching_factory_allocation(self):
        OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order_id=self.original_order).update(allocated_quantity=6)
        self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/",
                  {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
                   "factory_id": str(self.f.factory.pk), "handoff_pieces": 8,
                   "handoff_date": str(timezone.localdate())}, expected=409, etag=self.source_etag())
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_unsprayed_return_is_limited_by_original_order_good_returns(self):
        handoff = self.create_original_handoff(8)
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        returned = OutsourcingReturn.objects.create(
            order_id=self.original_order, return_number="P4-ORIGINAL-RETURN", factory=self.f.factory, client_request_id=uuid.uuid4(),
            request_payload_hash="a" * 64, zone=self.f.semi_zone, received_by_employee=self.f.employee,
            confirmed_by_employee=self.f.employee, confirmed_at=timezone.now(),
        )
        balance = SemiFinishedStockBalance.objects.create(
            production_task=self.task, product_line=self.f.product_line,
            bom_line=allocation.processing_item.bom_line, completed_craft=self.f.spray,
            unit=allocation.processing_item.unit, zone=self.f.semi_zone,
            quality="AVAILABLE", quantity=5,
        )
        OutsourcingReturnLine.objects.create(return_record=returned, allocation=allocation, returned_quantity=5,
                                             quality="AVAILABLE", semi_finished_balance=balance)
        payload = {"request_id": str(uuid.uuid4()), "returned_pieces": 4,
                   "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存架",
                   "return_date": str(timezone.localdate())}
        self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/", payload,
                  expected=409, etag=self.source_etag())
        self.assertFalse(MetalProcessingUnsprayedReturn.objects.exists())
        payload.update(request_id=str(uuid.uuid4()), returned_pieces=3)
        self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/", payload, etag=self.source_etag())

    def test_options_use_p4_view_permission_and_keep_original_order_scope(self):
        user = get_user_model().objects.create_user(username="p4-view-only")
        Employee.objects.create(user=user, employee_code="P4-VIEW-ONLY", display_name="管材查询员")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="material_issues", codename="view_metalprocessingsource"))
        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/metal-processing-sources/options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["factories"])
        self.assertEqual(response.data["data"]["original_orders"], [])
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="production_scheduling", codename="view_all_productionschedule"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        response = self.client.get("/api/v1/metal-processing-sources/options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.original_order, [row["id"] for row in response.data["data"]["original_orders"]])
        self.assertEqual(self.client.get("/api/v1/outsourcing-orders/options/").status_code, 403)

    def test_original_return_after_source_close_keeps_closure_snapshot_and_raw_ledgers(self):
        handoff = self.create_original_handoff()
        before = self.unchanged_ledgers()
        closed = self.write("close", {"request_id": str(uuid.uuid4()), "remark": "金工来源结清"}).data["data"]
        response = self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/",
                  {"request_id": str(uuid.uuid4()), "returned_pieces": 5,
                   "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存架",
                   "return_date": str(timezone.localdate())}, etag=self.source_etag())
        self.assertEqual(response.data["data"]["returned_pieces"], 5)
        current = self.detail().data["data"]
        self.assertEqual(current["status"], "CLOSED")
        self.assertEqual(current["closure"], closed["closure"])
        self.assertEqual(current["available_pieces"], 0)
        self.assertEqual(before, self.unchanged_ledgers())

    def test_new_order_stale_version_and_idempotent_return_do_not_duplicate_stock(self):
        order = self.create_order(5)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/").data["data"]
        handoff = self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/handoff/",
                  {"request_id": str(uuid.uuid4()), "handoff_pieces": 5, "handoff_date": str(timezone.localdate())},
                  etag=detail["etag"]).data["data"]
        payload = {"request_id": str(uuid.uuid4()), "good_pieces": 3, "zone_id": str(self.f.semi_zone.pk),
                   "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())}
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/", payload,
                  expected=412, etag=detail["etag"])
        self.assertFalse(SemiFinishedStockBalance.objects.exists())
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/", payload, etag=handoff["etag"])
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/", payload, etag=handoff["etag"])
        self.assertEqual(MetalProcessingExternalGoodReturn.objects.count(), 1)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 3)
        payload["good_pieces"] = 4
        self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/", payload,
                  expected=409, etag=handoff["etag"])

    def test_new_order_over_return_and_fractional_input_are_rejected_without_stock(self):
        order = self.create_order(5)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/").data["data"]
        handoff = self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/handoff/",
                  {"request_id": str(uuid.uuid4()), "handoff_pieces": 5, "handoff_date": str(timezone.localdate())},
                  etag=detail["etag"]).data["data"]
        for value, status in ((0, 400), ("1.1", 400), (True, 400), (6, 409)):
            self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
                      {"request_id": str(uuid.uuid4()), "good_pieces": value, "zone_id": str(self.f.semi_zone.pk),
                       "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())},
                      expected=status, etag=handoff["etag"])
        self.assertFalse(MetalProcessingExternalGoodReturn.objects.exists())
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_raw_dispatched_order_cannot_also_receive_direct_handoff(self):
        from apps.outsourcing.models import OutsourcingDispatchLine, OutsourcingMaterialItem
        response = self.f.create_order(self.payload("PIPE", "12"))
        self.assertEqual(response.status_code, 201, response.data)
        self.original_order = response.data["data"]["id"]
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=self.original_order)
        MaterialFlowFixture.post(self, self.original_order, "confirm-dispatch",
            {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
             "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "12"}]})
        before = self.unchanged_ledgers()
        response = self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/", {
            "request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 8,
            "handoff_date": str(timezone.localdate())}, expected=409, etag=self.source_etag())
        self.assertIn("交接", str(response.data))
        self.assertFalse(OutsourcingReturn.objects.exists())
        from apps.outsourcing.models import OutsourcingReconciliation
        self.assertFalse(OutsourcingReconciliation.objects.filter(order_id=self.original_order).exists())
        self.assertFalse(SemiFinishedStockBalance.objects.exists())
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())
        self.assertEqual(before, self.unchanged_ledgers())

    def simulate_unapplied_p4(self):
        # 本测试事务回滚时恢复表名和迁移登记，不操作任何正式库或迁移文件。
        MigrationRecorder(connection).migration_qs.filter(
            app="material_issues", name="0007_metalprocessingoriginalhandoff_and_more",
        ).delete()
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE metal_processing_original_handoff RENAME TO qa_p4_unapplied_original_handoff")

    def test_p3_source_detail_remains_available_before_p4_migration(self):
        self.simulate_unapplied_p4()
        response = self.detail()
        self.assertEqual(response.data["data"]["completed_pieces"], 12)
        self.assertIn("ETag", response)
        self.assertNotIn("original_handoffs", response.data["data"])

    def test_legacy_good_return_remains_available_before_p4_migration(self):
        from apps.outsourcing.models import OutsourcingDispatchLine, OutsourcingMaterialItem
        response = self.f.create_order(self.payload("PIPE", "12"))
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        MaterialFlowFixture.post(self, order_id, "confirm-dispatch", {
            "request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
             "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "12"}],
        })
        dispatch_line = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
        self.simulate_unapplied_p4()
        MaterialFlowFixture.post(self, order_id, "confirm-return", {
            "request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
            "good_zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
            "return_date": str(timezone.localdate()), "raw_inputs": [self.entry(dispatch_line, "RAW_INPUT", "1")],
            "lines": [{"allocation_id": str(material.allocation_id), "good_quantity": "4", "defective_quantity": "0"}],
        })
        self.assertEqual(OutsourcingReturn.objects.filter(order_id=order_id).count(), 1)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 4)


class OriginalClosureFixture(MetalProcessingP4Fixture):
    def prepare_original(self, plan=12, handed=12):
        response = self.f.create_order(self.payload("PIPE", str(plan)))
        self.assertEqual(response.status_code, 201, response.data)
        self.original_order = response.data["data"]["id"]
        return self.create_original_handoff(handed) if handed else None

    def closure_context(self):
        response = self.client.get(f"/api/v1/metal-processing-original-orders/{self.original_order}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["ETag"], response.data["data"]["etag"])
        return response.data["data"]

    def original_write(self, action, payload, expected=200, etag=None):
        return self.post(f"/api/v1/metal-processing-original-orders/{self.original_order}/{action}/", payload,
                         expected=expected, etag=etag or self.closure_context()["etag"]).data["data"]

    def good_original(self, handoff, pieces, remark="", expected=200, payload=None):
        context = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]["good_return_context"]
        data = payload or {"request_id": str(uuid.uuid4()), "good_pieces": pieces,
            "zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
            "return_date": str(timezone.localdate()), "remark": remark}
        return self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/", data,
                         etag=context["etag"], expected=expected)

    def unsprayed_original(self, handoff, pieces, remark="", expected=200):
        detail = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]
        return self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/", {
            "request_id": str(uuid.uuid4()), "returned_pieces": pieces,
            "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存",
            "return_date": str(timezone.localdate()), "remark": remark}, etag=detail["source_etag"], expected=expected)

    def other_part_handoff(self, original_handoff):
        # 独立部位的完整冻结来源夹具；先真实领料，再在首次加工登记前准备第二部位身份。
        import copy
        from apps.material_issues.models import OrderMaterialRequirement
        line = self.issue_line(12)
        bom_line = copy.copy(self.f.profile)
        bom_line.pk, bom_line.component_identity, bom_line.line_number = uuid.uuid4(), uuid.uuid4(), 90
        bom_line.part_name = "后脚管"
        bom_line._state.adding = True
        bom_line.save()
        requirement = OrderMaterialRequirement.objects.get(pk=line.requirement_id)
        requirement.pk, requirement.component_identity = uuid.uuid4(), bom_line.component_identity
        requirement._state.adding = True
        requirement.save()
        line.requirement = requirement
        line.conversion_snapshot = {**line.conversion_snapshot, "bom_line_id": str(bom_line.pk),
            "component_identity": str(bom_line.component_identity), "part_name": "后脚管"}
        line.save(update_fields=["requirement", "conversion_snapshot", "updated_at"])
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        item = copy.copy(allocation.processing_item)
        item.pk, item.bom_line, item.component_key, item.line_number = uuid.uuid4(), bom_line, str(bom_line.pk), 90
        item.component_snapshot = {**item.component_snapshot, "part_name": "后脚管"}
        item._state.adding = True
        item.save()
        allocation.pk, allocation.processing_item = uuid.uuid4(), item
        allocation._state.adding = True
        allocation.save()
        self.write("completions", self.complete_payload(12), line=line)
        result = self.write("handoffs", {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 12, "handoff_date": str(timezone.localdate())}, line=line)
        return MetalProcessingOriginalHandoff.objects.get(pk=result.data["data"]["operation_id"])


@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingOriginalClosureTests(OriginalClosureFixture, APITestCase):
    def test_pending_plan_blocks_finish_and_close_until_explicit_cancel(self):
        handoff = self.prepare_original(plan=18)
        before = self.unchanged_ledgers()
        first = self.closure_context()
        self.assertEqual((first["totals"]["planned_pieces"], first["totals"]["pending_handoff_pieces"]), (18, 6))
        payload = {"request_id": str(uuid.uuid4()), "remark": "少量未回"}
        self.post(f"/api/v1/metal-processing-original-orders/{self.original_order}/close/", payload,
                  expected=409, etag=first["etag"])
        self.good_original(handoff, 12)
        returned = self.closure_context()
        self.assertEqual(returned["original_order_status"], "PARTIAL_RETURN")
        self.assertEqual(returned["totals"]["remaining_return_pieces"], 0)
        cancellation = {"request_id": str(uuid.uuid4()), "allocation_id": returned["parts"][0]["allocation_id"],
                        "remark": "取消本行未交的6支"}
        saved = self.original_write("cancel-pending", cancellation)
        self.assertEqual(saved["original_order_status"], "COMPLETED")
        self.assertEqual(saved["totals"]["pending_handoff_pieces"], 0)
        self.assertEqual(saved["totals"]["cancelled_pending_pieces"], 6)
        self.assertEqual(saved["pending_cancellations"][0]["cancelled_pieces"], 6)
        allocation = OutsourcingFactoryAllocation.objects.get(pk=cancellation["allocation_id"])
        self.assertEqual(allocation.allocated_quantity, 18)
        self.assertIsNotNone(OutsourcingOrder.objects.get(pk=self.original_order).completed_at)
        self.original_write("cancel-pending", cancellation, etag=returned["etag"])
        self.assertEqual(len(self.closure_context()["pending_cancellations"]), 1)
        # 原料台账与来源用量没有因显式取消产生变化；合格半成品来自前面的回货。
        after = self.unchanged_ledgers()
        for model in before:
            if "semifinished" not in model.lower():
                self.assertEqual(before[model], after[model], model)

    def test_closure_freezes_snapshot_and_both_late_returns_share_remaining(self):
        from apps.inventory.models import MaterialStockBalance, MaterialStockMovement
        from apps.material_issues.models import MetalProcessingSource
        handoff = self.prepare_original()
        self.good_original(handoff, 4)
        self.unsprayed_original(handoff, 2)
        raw_before = {model.__name__: list(model.objects.order_by("pk").values()) for model in (MaterialStockBalance, MaterialStockMovement)}
        source_before = list(MetalProcessingSource.objects.order_by("pk").values())
        context = self.closure_context()
        payload = {"request_id": str(uuid.uuid4()), "remark": "核对差额6支，备注结清"}
        closed = self.original_write("close", payload)
        self.assertEqual(closed["original_order_status"], "CLOSED")
        frozen = closed["closure"]
        self.assertEqual(frozen["quantity_snapshot"]["totals"]["remaining_return_pieces"], 6)
        self.assertEqual(frozen["actor_name"], self.f.employee.display_name)
        self.original_write("close", payload, etag=context["etag"])
        self.good_original(handoff, 1, "   ", expected=400)
        self.unsprayed_original(handoff, 1, " \n ", expected=400)
        detail = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]
        self.assertEqual(detail["original_order_status"], "CLOSED")
        self.assertEqual(detail["original_order_closure"], frozen)
        self.assertTrue(detail["good_return_context"]["post_closure"])
        self.good_original(handoff, 4, "找到并补回4支")
        self.unsprayed_original(handoff, 3, "不能与合格补回重复计数", expected=409)
        self.assertEqual(self.closure_context()["original_order_status"], "CLOSED")
        self.unsprayed_original(handoff, 2, "另2支未喷塑补退")
        completed = self.closure_context()
        self.assertEqual(completed["original_order_status"], "COMPLETED")
        self.assertEqual(completed["closure"], frozen)
        self.assertEqual(completed["totals"]["remaining_return_pieces"], 0)
        self.assertEqual([(row["kind"], row["pieces"]) for row in completed["post_closure_returns"]], [("UNSPRAYED", 2), ("GOOD", 4)])
        self.good_original(handoff, 1, "完成禁追加", expected=409)
        self.unsprayed_original(handoff, 1, "完成禁追加", expected=409)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 8)
        self.assertEqual(raw_before, {model.__name__: list(model.objects.order_by("pk").values()) for model in (MaterialStockBalance, MaterialStockMovement)})
        self.assertEqual(source_before, list(MetalProcessingSource.objects.order_by("pk").values()))

    def test_all_parts_must_return_independently_and_closure_keeps_each_difference(self):
        first = self.prepare_original()
        second = self.other_part_handoff(first)
        self.good_original(first, 12)
        context = self.closure_context()
        self.assertEqual(context["original_order_status"], "PARTIAL_RETURN")
        self.assertEqual(sorted(row["remaining_return_pieces"] for row in context["parts"]), [0, 12])
        self.good_original(first, 1, expected=409)
        closed = self.original_write("close", {"request_id": str(uuid.uuid4()), "remark": "后脚管差额12支"})
        self.assertEqual(sorted(row["remaining_return_pieces"] for row in closed["closure"]["quantity_snapshot"]["parts"]), [0, 12])
        self.good_original(second, 10, "后脚管补回10")
        self.unsprayed_original(second, 2, "后脚管剩余2支未喷塑退回")
        completed = self.closure_context()
        self.assertEqual(completed["original_order_status"], "COMPLETED")
        self.assertEqual(completed["closure"], closed["closure"])
        self.assertEqual(sorted(row.quantity for row in SemiFinishedStockBalance.objects.all()), [10, 12])

    def test_zero_handoff_never_closes_or_completes(self):
        self.prepare_original(handed=0)
        context = self.closure_context()
        self.assertEqual(context["original_order_status"], "PENDING_DISPATCH")
        self.assertFalse(context["can_close"])
        self.assertFalse(context["parts"][0]["can_cancel_pending"])
        self.post(f"/api/v1/metal-processing-original-orders/{self.original_order}/close/", {
            "request_id": str(uuid.uuid4()), "remark": "不能用0等于0完成"}, expected=409, etag=context["etag"])
        self.assertIsNone(OutsourcingOrder.objects.get(pk=self.original_order).completed_at)

    def test_normal_full_return_finishes_without_a_closure(self):
        handoff = self.prepare_original()
        self.good_original(handoff, 6)
        self.unsprayed_original(handoff, 6)
        context = self.closure_context()
        self.assertEqual(context["original_order_status"], "COMPLETED")
        self.assertIsNone(context["closure"])
        self.assertEqual(context["post_closure_returns"], [])

    def test_closed_order_locks_legacy_actions_and_preserves_handoff_reference(self):
        self.prepare_original()
        before = list(MetalProcessingOriginalHandoff.objects.filter(original_order_id=self.original_order)
            .order_by("pk").values_list("pk", "handoff_pieces"))
        self.original_write("close", {"request_id": str(uuid.uuid4()), "remark": "仍未回货，备注结清"})
        detail = self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/").data["data"]
        self.assertEqual(detail["status"], "CLOSED")
        for name in ("can_cancel", "can_delete", "can_edit", "can_confirm_dispatch", "can_confirm_return", "can_return_raw", "can_reconcile", "can_complete"):
            self.assertFalse(detail[name], name)
        self.post(f"/api/v1/outsourcing-orders/{self.original_order}/complete/", {"request_id": str(uuid.uuid4())},
                  expected=409, etag=self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/")["ETag"])
        after = list(MetalProcessingOriginalHandoff.objects.filter(original_order_id=self.original_order)
            .order_by("pk").values_list("pk", "handoff_pieces"))
        self.assertEqual(before, after)

    def test_closure_validation_permission_scope_csrf_etag_and_retry(self):
        from django.middleware.csrf import _get_new_csrf_string
        self.prepare_original()
        url = f"/api/v1/metal-processing-original-orders/{self.original_order}/close/"
        context = self.closure_context()
        payload = {"request_id": str(uuid.uuid4()), "remark": "合法结清原因"}
        for invalid in ("", " \n ", "字" * 1001):
            self.post(url, {**payload, "remark": invalid}, expected=400, etag=context["etag"])
        self.post(url, {**payload, "remaining_pieces": 0}, expected=400, etag=context["etag"])
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 428)
        self.post(url, payload, expected=412, etag='"stale"')
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post(url, payload, format="json").status_code, 401)
        client.force_login(self.f.user)
        self.assertEqual(client.post(url, payload, format="json", HTTP_IF_MATCH=context["etag"]).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies["csrftoken"] = csrf
        response = client.post(url, payload, format="json", HTTP_IF_MATCH=context["etag"], HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.data)
        self.post(url, {**payload, "remark": "同请求改内容"}, expected=409, etag=context["etag"])
        user = get_user_model().objects.create_user(username="original-closure-user")
        Employee.objects.create(user=user, employee_code="ORIGINAL-CLOSE", display_name="原单收尾员")
        user.user_permissions.add(*Permission.objects.filter(codename__in=["view_metalprocessingsource", "view_all_materialissue", "view_all_productionschedule"]))
        self.client.force_authenticate(user)
        self.post(url, payload, expected=403, etag=context["etag"])
        user.user_permissions.add(Permission.objects.get(content_type__app_label="outsourcing", codename="complete_outsourcingorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.post(url, payload, expected=409, etag=context["etag"])
        user.user_permissions.remove(Permission.objects.get(codename="view_all_materialissue"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.post(url, payload, expected=404, etag=context["etag"])

    def test_cancel_requires_explicit_reason_scope_and_blocks_further_handoff(self):
        self.prepare_original(plan=18)
        context = self.closure_context()
        url = f"/api/v1/metal-processing-original-orders/{self.original_order}/cancel-pending/"
        payload = {"request_id": str(uuid.uuid4()), "allocation_id": context["parts"][0]["allocation_id"], "remark": "取消未交6支"}
        self.post(url, {**payload, "remark": "  "}, expected=400, etag=context["etag"])
        self.post(url, {**payload, "allocation_id": str(uuid.uuid4())}, expected=400, etag=context["etag"])
        self.post(url, {**payload, "cancelled_pieces": 7}, expected=400, etag=context["etag"])
        saved = self.original_write("cancel-pending", payload)
        self.assertEqual(saved["totals"]["effective_planned_pieces"], 12)
        self.assertEqual(saved["original_order_status"], "PROCESSING")
        self.write("completions", self.complete_payload(6))
        self.write("handoffs", {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 6, "handoff_date": str(timezone.localdate())}, expected=409)
        closed = self.original_write("close", {"request_id": str(uuid.uuid4()), "remark": "未回12支备注结清"})
        self.assertEqual(closed["closure"]["quantity_snapshot"]["totals"]["cancelled_pending_pieces"], 6)

    def test_unapplied_closure_migration_has_explicit_readiness_and_blocks_new_writes(self):
        from apps.audit.models import AuditLog
        self.prepare_original(plan=18)
        MigrationRecorder(connection).migration_qs.filter(app="outsourcing", name="0006_direct_handoff_closed_status").delete()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE outsourcing_order DROP CONSTRAINT outs_order_status_valid")
            cursor.execute("ALTER TABLE outsourcing_order ADD CONSTRAINT outs_order_status_valid CHECK (status IN ('PENDING_DISPATCH','PROCESSING','PARTIAL_RETURN','COMPLETED','CANCELLED'))")
        before = (self.unchanged_ledgers(), AuditLog.objects.count(), OutsourcingOrder.objects.get(pk=self.original_order).version)
        context = self.closure_context()
        self.assertFalse(context["schema_ready"])
        self.assertFalse(context["can_close"])
        self.assertFalse(context["parts"][0]["can_cancel_pending"])
        for action, payload in (("close", {"request_id": str(uuid.uuid4()), "remark": "尚未升级"}),
                                ("cancel-pending", {"request_id": str(uuid.uuid4()), "remark": "尚未升级", "allocation_id": context["parts"][0]["allocation_id"]})):
            self.post(f"/api/v1/metal-processing-original-orders/{self.original_order}/{action}/", payload, expected=409, etag=context["etag"])
        self.assertEqual(before, (self.unchanged_ledgers(), AuditLog.objects.count(), OutsourcingOrder.objects.get(pk=self.original_order).version))

    def test_unapplied_p4_table_does_not_break_legacy_pending_delete(self):
        self.prepare_original(handed=0)
        MigrationRecorder(connection).migration_qs.filter(app="material_issues", name="0007_metalprocessingoriginalhandoff_and_more").delete()
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE metal_processing_original_handoff RENAME TO qa_p4_unapplied_original_handoff")
        self.assertEqual(self.client.get(f"/api/v1/metal-processing-original-orders/{self.original_order}/").status_code, 409)
        detail = self.client.get(f"/api/v1/outsourcing-orders/{self.original_order}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        response = self.client.delete(f"/api/v1/outsourcing-orders/{self.original_order}/", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(OutsourcingOrder.objects.filter(pk=self.original_order).exists())

    def test_failed_closure_audit_leaves_order_unchanged(self):
        from unittest.mock import patch
        self.prepare_original()
        before = self.closure_context()
        with patch("apps.material_issues.original_order_services.write_audit_log", side_effect=RuntimeError("写审计失败")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/v1/metal-processing-original-orders/{self.original_order}/close/", {
                    "request_id": str(uuid.uuid4()), "remark": "失败须回滚"}, format="json", HTTP_IF_MATCH=before["etag"])
        self.assertEqual(self.closure_context(), before)


class P4AllocationFixture(MetalProcessingP4Fixture):
    def allocation_orders(self):
        self.write("completions", self.complete_payload(12))
        handoff = self.create_original_handoff(24)
        returned = self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/", {
            "request_id": str(uuid.uuid4()), "returned_pieces": 24,
            "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存架",
            "return_date": str(timezone.localdate())}, etag=self.source_etag()).data["data"]
        rework = self.post(f"/api/v1/metal-processing-unsprayed-returns/{returned['id']}/rework/", {
            "request_id": str(uuid.uuid4()), "completed_pieces": 24,
            "completion_date": str(timezone.localdate())}).data["data"]
        orders = []
        for pieces in (8, 12):
            orders.append(self.post(f"/api/v1/metal-processing-reworks/{rework['id']}/orders/", {
                "request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                "craft_id": str(self.f.spray.pk), "allocated_pieces": pieces}, expected=201).data["data"])
        return orders

    def allocation_url(self, order):
        return f"/api/v1/metal-processing-external-orders/{order['id']}/allocation/"

    def allocation_detail(self, order):
        response = self.client.get(f"/api/v1/metal-processing-external-orders/{order['id']}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]


@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingP4AllocationTests(P4AllocationFixture, APITestCase):
    def test_adjustment_releases_own_allocation_and_keeps_stock_and_source_unchanged(self):
        from apps.audit.models import AuditLog
        from apps.material_issues.models import MetalProcessingCompletion, MetalProcessingSource
        first, _other = self.allocation_orders()
        first = self.allocation_detail(first)
        context = first["allocation_context"]
        self.assertEqual((context["rework_completed_pieces"], context["other_allocated_pieces"],
                          context["max_allocatable_pieces"], context["remaining_allocatable_pieces"]), (24, 12, 12, 4))
        self.assertTrue(context["can_adjust"])
        self.assertTrue(context["issue_number"])
        before = self.unchanged_ledgers()
        quantities = {model.__name__: list(model.objects.order_by("pk").values())
                      for model in (MetalProcessingSource, MetalProcessingCompletion, MetalProcessingRework)}
        result = self.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 10},
                           etag=first["etag"]).data["data"]
        self.assertEqual(result["allocated_pieces"], 10)
        self.assertEqual(result["allocation_context"]["remaining_allocatable_pieces"], 2)
        self.assertEqual(result["version"], first["version"] + 1)
        for key in ("source_id", "rework_id", "original_return_id", "factory_id", "craft_id", "handoff_pieces", "returned_good_pieces"):
            self.assertEqual(first[key], result[key], key)
        history = result["allocation_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["before_pieces"], history[0]["after_pieces"]), (8, 10))
        self.assertEqual(history[0]["actor_name"], self.f.employee.display_name)
        self.assertEqual(history[0]["actor_employee_id"], str(self.f.employee.pk))
        self.assertTrue(history[0]["created_at"])
        self.assertEqual(AuditLog.objects.get(pk=history[0]["id"]).before_data["allocated_pieces"], 8)
        self.assertEqual(before, self.unchanged_ledgers())
        self.assertEqual(quantities, {model.__name__: list(model.objects.order_by("pk").values())
                                    for model in (MetalProcessingSource, MetalProcessingCompletion, MetalProcessingRework)})
        decreased = self.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 6},
                             etag=result["etag"]).data["data"]
        self.assertEqual(decreased["allocation_context"]["remaining_allocatable_pieces"], 6)
        self.assertEqual([(row["before_pieces"], row["after_pieces"]) for row in decreased["allocation_history"]], [(10, 6), (8, 10)])

    def test_adjustment_rejects_invalid_extra_fields_and_stale_or_missing_version(self):
        first, _other = self.allocation_orders()
        url = self.allocation_url(first)
        for value in (0, -1, "1.0", 1.5, True, None, 10**14):
            self.post(url, {"request_id": str(uuid.uuid4()), "allocated_pieces": value}, expected=400, etag=first["etag"])
        for key in ("factory_id", "craft_id", "source_id", "rework_id", "handoff_pieces", "remark"):
            self.post(url, {"request_id": str(uuid.uuid4()), "allocated_pieces": 10, key: "forbidden"}, expected=400, etag=first["etag"])
        payload = {"request_id": str(uuid.uuid4()), "allocated_pieces": 10}
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 428)
        self.post(url, payload, expected=412, etag='"stale"')
        self.post(url, {**payload, "allocated_pieces": 13}, expected=409, etag=first["etag"])
        self.assertEqual(self.allocation_detail(first)["allocation_history"], [])
        self.assertEqual(self.allocation_detail(first)["allocated_pieces"], 8)

    def test_adjustment_is_idempotent_but_cannot_reuse_request_for_changed_body_or_order(self):
        first, other = self.allocation_orders()
        payload = {"request_id": str(uuid.uuid4()), "allocated_pieces": 10}
        url = self.allocation_url(first)
        saved = self.post(url, payload, etag=first["etag"]).data["data"]
        self.post(url, payload, etag=first["etag"])
        self.post(url, {**payload, "allocated_pieces": 11}, expected=409, etag=saved["etag"])
        self.post(self.allocation_url(other), payload, expected=409, etag=other["etag"])
        current = self.allocation_detail(first)
        self.assertEqual(current["version"], saved["version"])
        self.assertEqual(len(current["allocation_history"]), 1)

    def test_handoff_uses_saved_allocation_and_locks_further_adjustment(self):
        first, _other = self.allocation_orders()
        changed = self.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 10},
                            etag=first["etag"]).data["data"]
        handoff_url = f"/api/v1/metal-processing-external-orders/{first['id']}/handoff/"
        payload = {"request_id": str(uuid.uuid4()), "handoff_pieces": 8, "handoff_date": str(timezone.localdate())}
        self.post(handoff_url, payload, expected=412, etag=first["etag"])
        self.post(handoff_url, payload, expected=400, etag=changed["etag"])
        handoff = self.post(handoff_url, {**payload, "handoff_pieces": 10}, etag=changed["etag"]).data["data"]
        self.assertFalse(handoff["allocation_context"]["can_adjust"])
        self.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 12},
                  expected=409, etag=handoff["etag"])
        # 历史状态字段被错误留在待交接也不能绕过已交实物门禁。
        MetalProcessingExternalOrder.objects.filter(pk=first["id"]).update(status="PENDING_HANDOFF")
        current = self.allocation_detail(first)
        self.assertFalse(current["allocation_context"]["can_adjust"])
        self.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 12},
                  expected=409, etag=current["etag"])

    def test_adjustment_permission_scope_and_cross_actor_replay(self):
        first, _other = self.allocation_orders()
        payload = {"request_id": str(uuid.uuid4()), "allocated_pieces": 10}
        self.post(self.allocation_url(first), payload, etag=first["etag"])
        user = get_user_model().objects.create_user(username="p4-allocation-editor")
        Employee.objects.create(user=user, employee_code="P4-ALLOC-EDITOR", display_name="分配调整员")
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_issues",
            codename__in=["view_metalprocessingsource", "view_all_materialissue", "create_metalprocessingexternalorder"]))
        self.client.force_authenticate(user)
        self.assertFalse(self.allocation_detail(first)["allocation_context"]["can_adjust"])
        self.post(self.allocation_url(first), payload, expected=403, etag=first["etag"])
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_issues", codename="change_metalprocessingexternalorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        current = self.allocation_detail(first)
        self.assertTrue(current["allocation_context"]["can_adjust"])
        self.post(self.allocation_url(first), payload, expected=409, etag=current["etag"])
        own_payload = {"request_id": str(uuid.uuid4()), "allocated_pieces": 11}
        self.post(self.allocation_url(first), own_payload, etag=current["etag"])
        user.user_permissions.remove(Permission.objects.get(content_type__app_label="material_issues", codename="view_all_materialissue"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.post(self.allocation_url(first), own_payload, expected=404, etag=current["etag"])

    def test_adjustment_requires_session_csrf(self):
        from django.middleware.csrf import _get_new_csrf_string
        first, _other = self.allocation_orders()
        url = self.allocation_url(first)
        payload = {"request_id": str(uuid.uuid4()), "allocated_pieces": 10}
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post(url, payload, format="json").status_code, 401)
        client.force_login(self.f.user)
        self.assertEqual(client.post(url, payload, format="json", HTTP_IF_MATCH=first["etag"]).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies["csrftoken"] = csrf
        response = client.post(url, payload, format="json", HTTP_IF_MATCH=first["etag"], HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.data)

    def test_failed_audit_rolls_back_allocation_and_version(self):
        from unittest.mock import patch
        first, _other = self.allocation_orders()
        with patch("apps.material_issues.p4_services.write_audit_log", side_effect=RuntimeError("审计写入失败")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.allocation_url(first), {"request_id": str(uuid.uuid4()), "allocated_pieces": 10},
                                 format="json", HTTP_IF_MATCH=first["etag"])
        current = self.allocation_detail(first)
        self.assertEqual((current["allocated_pieces"], current["version"], current["allocation_history"]), (8, 1, []))


@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingP4AllocationConcurrencyTests(P4AllocationFixture, APITransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        with transaction.atomic():
            super().setUp()

    def concurrent_posts(self, requests):
        user_id, barrier = self.f.user.pk, Barrier(2)

        def worker(item):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=10)
                url, etag, payload = item
                response = client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, requests))

    def test_two_orders_cannot_concurrently_exceed_shared_rework_completion(self):
        from django.db.models import Sum
        first, other = self.allocation_orders()
        results = self.concurrent_posts([
            (self.allocation_url(order), order["etag"], {"request_id": str(uuid.uuid4()), "allocated_pieces": pieces})
            for order, pieces in ((first, 12), (other, 16))])
        self.assertEqual(sorted(code for code, _ in results), [200, 409], results)
        self.assertEqual(MetalProcessingExternalOrder.objects.aggregate(total=Sum("allocated_pieces"))["total"], 24)

    def test_adjustment_and_creation_share_capacity_lock(self):
        from django.db.models import Sum
        first, _other = self.allocation_orders()
        results = self.concurrent_posts([
            (self.allocation_url(first), first["etag"], {"request_id": str(uuid.uuid4()), "allocated_pieces": 12}),
            (f"/api/v1/metal-processing-reworks/{first['rework_id']}/orders/", '"ignored"',
             {"request_id": str(uuid.uuid4()), "allocated_pieces": 4,
              "factory_id": str(self.f.factory.pk), "craft_id": str(self.f.spray.pk)})])
        self.assertEqual(sum(code in (200, 201) for code, _ in results), 1, results)
        self.assertEqual(sum(code == 409 for code, _ in results), 1, results)
        self.assertEqual(MetalProcessingExternalOrder.objects.aggregate(total=Sum("allocated_pieces"))["total"], 24)

    def test_adjustment_and_handoff_cannot_use_different_saved_quantities(self):
        first, _other = self.allocation_orders()
        results = self.concurrent_posts([
            (self.allocation_url(first), first["etag"], {"request_id": str(uuid.uuid4()), "allocated_pieces": 10}),
            (f"/api/v1/metal-processing-external-orders/{first['id']}/handoff/", first["etag"],
             {"request_id": str(uuid.uuid4()), "handoff_pieces": 8, "handoff_date": str(timezone.localdate())})])
        self.assertEqual(sorted(code for code, _ in results), [200, 412], results)
        current = self.allocation_detail(first)
        self.assertIn((current["allocated_pieces"], current["handoff_pieces"]), ((10, 0), (8, 8)))


@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingOriginalClosureConcurrencyTests(OriginalClosureFixture, APITransactionTestCase):
    serialized_rollback = True
    concurrent_posts = MetalProcessingP4AllocationConcurrencyTests.concurrent_posts

    def setUp(self):
        with transaction.atomic():
            super().setUp()

    def test_pending_cancel_and_actual_handoff_share_order_lock(self):
        self.prepare_original(plan=18)
        self.write("completions", self.complete_payload(6))
        context = self.closure_context()
        results = self.concurrent_posts([
            (f"/api/v1/metal-processing-original-orders/{self.original_order}/cancel-pending/", context["etag"],
             {"request_id": str(uuid.uuid4()), "allocation_id": context["parts"][0]["allocation_id"], "remark": "取消未交6"}),
            (f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/", self.source_etag(),
             {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order, "factory_id": str(self.f.factory.pk),
              "handoff_pieces": 6, "handoff_date": str(timezone.localdate())})])
        self.assertEqual(sum(code == 200 for code, _ in results), 1, results)
        self.assertTrue(all(code in (200, 409, 412) for code, _ in results), results)
        current = self.closure_context()
        self.assertEqual(current["totals"]["pending_handoff_pieces"], 0)
        self.assertEqual(current["totals"]["handoff_pieces"] + current["totals"]["cancelled_pending_pieces"], 18)

    def test_original_close_and_final_return_cannot_commit_stale_snapshot(self):
        handoff = self.prepare_original()
        context = self.closure_context()
        good = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]["good_return_context"]
        results = self.concurrent_posts([
            (f"/api/v1/metal-processing-original-orders/{self.original_order}/close/", context["etag"],
             {"request_id": str(uuid.uuid4()), "remark": "差额12结清"}),
            (f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/", good["etag"],
             {"request_id": str(uuid.uuid4()), "good_pieces": 12, "zone_id": str(self.f.semi_zone.pk),
              "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())})])
        self.assertEqual(sorted(code for code, _ in results), [200, 412], results)
        current = self.closure_context()
        if current["original_order_status"] == "CLOSED":
            self.assertEqual(current["closure"]["quantity_snapshot"]["totals"]["remaining_return_pieces"], 12)
            self.assertFalse(SemiFinishedStockBalance.objects.exists())
        else:
            self.assertEqual(current["original_order_status"], "COMPLETED")
            self.assertIsNone(current["closure"])
            self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 12)

    def test_late_good_and_unsprayed_returns_share_limit_after_closure(self):
        handoff = self.prepare_original()
        closed = self.original_write("close", {"request_id": str(uuid.uuid4()), "remark": "差额12结清"})
        detail = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]
        results = self.concurrent_posts([
            (f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/", detail["good_return_context"]["etag"],
             {"request_id": str(uuid.uuid4()), "good_pieces": 8, "zone_id": str(self.f.semi_zone.pk),
              "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()), "remark": "补回8支"}),
            (f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/", detail["source_etag"],
             {"request_id": str(uuid.uuid4()), "returned_pieces": 8, "received_by_employee_id": str(self.f.employee.pk),
              "return_date": str(timezone.localdate()), "storage_location": "金工暂存", "remark": "补退8支"})])
        self.assertEqual(sum(code == 200 for code, _ in results), 1, results)
        self.assertTrue(all(code in (200, 409, 412) for code, _ in results), results)
        current = self.closure_context()
        self.assertEqual(current["totals"]["remaining_return_pieces"], 4)
        self.assertEqual(current["closure"], closed["closure"])
        self.assertEqual(current["original_order_status"], "CLOSED")


@override_settings(TUBE_OUTSOURCING_ENABLED=False)
class MetalProcessingP4LockOrderTests(MetalProcessingP4Fixture, APITransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        with transaction.atomic():
            super().setUp()

    def test_original_good_and_unsprayed_returns_from_different_sources_share_actual_limit(self):
        first = self.create_original_handoff(8)
        second_line = self.issue_line(12)
        self.write("completions", self.complete_payload(12), line=second_line)
        second = self.write("handoffs", {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 8, "handoff_date": str(timezone.localdate())},
            line=second_line).data["data"]["operation_id"]
        good_context = self.client.get(f"/api/v1/metal-processing-handoffs/{first.pk}/").data["data"]["good_return_context"]
        source_etag = self.detail(second_line)["ETag"]
        requests = [
            (f"/api/v1/metal-processing-handoffs/{first.pk}/good-returns/", good_context["etag"],
             {"request_id": str(uuid.uuid4()), "good_pieces": 10, "zone_id": str(self.f.semi_zone.pk),
              "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())}),
            (f"/api/v1/metal-processing-handoffs/{second}/returns/", source_etag,
             {"request_id": str(uuid.uuid4()), "returned_pieces": 8, "received_by_employee_id": str(self.f.employee.pk),
              "storage_location": "暂存架", "return_date": str(timezone.localdate())}),
        ]
        barrier = Barrier(2)
        user_id = self.f.user.pk

        def worker(item):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=10)
                url, etag, payload = item
                response = client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, requests))
        self.assertEqual(sum(code == 200 for code, _ in results), 1, results)
        self.assertTrue(all(code in (200, 409, 412) for code, _ in results), results)
        context = self.client.get(f"/api/v1/metal-processing-handoffs/{first.pk}/").data["data"]["good_return_context"]
        self.assertEqual(context["handoff_pieces"], 16)
        self.assertLessEqual(context["returned_good_pieces"] + context["returned_unsprayed_pieces"], 16)
        self.assertEqual(sum(row.quantity for row in SemiFinishedStockBalance.objects.all()), context["returned_good_pieces"])

    def test_good_return_waiting_for_task_does_not_hold_warehouse_zone(self):
        """真实数据库等待时，任务持锁方仍可锁库区，不产生领料与回货逆序环。"""
        from apps.production_tasks.models import ProductionTask

        order = self.create_order(5)
        detail = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/").data["data"]
        handoff = self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/handoff/",
                  {"request_id": str(uuid.uuid4()), "handoff_pieces": 5, "handoff_date": str(timezone.localdate())},
                  etag=detail["etag"]).data["data"]
        user_id = self.f.user.pk
        payload = {"request_id": str(uuid.uuid4()), "good_pieces": 3, "zone_id": str(self.f.semi_zone.pk),
                   "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate())}
        application_name = f"p4-lock-order-{uuid.uuid4().hex[:12]}"

        def return_worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SELECT set_config('application_name', %s, false)", [application_name])
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                response = client.post(f"/api/v1/metal-processing-external-orders/{order.pk}/returns/",
                    payload, format="json", HTTP_IF_MATCH=handoff["etag"])
                return response.status_code, response.data
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                ProductionTask.objects.select_for_update().get(pk=self.task.pk)
                pending = pool.submit(return_worker)
                deadline = time.monotonic() + 5
                while True:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_stat_clear_snapshot()")
                        cursor.execute("SELECT wait_event_type, query FROM pg_stat_activity WHERE application_name = %s", [application_name])
                        waiting = cursor.fetchone()
                    if waiting and waiting[0] == "Lock" and '"production_task"' in waiting[1]:
                        break
                    self.assertLess(time.monotonic(), deadline, f"回货未按预期等待任务锁：{waiting}")
                    time.sleep(0.01)
                WarehouseZone.objects.select_for_update(nowait=True).get(pk=self.f.semi_zone.pk)
            status, body = pending.result(timeout=10)
        self.assertEqual(status, 200, body)
        self.assertEqual(SemiFinishedStockBalance.objects.get().quantity, 3)
