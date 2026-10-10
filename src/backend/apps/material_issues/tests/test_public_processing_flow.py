"""公共金工来源、原单回货和返工再外发的数量守恒。"""

import copy
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.inventory.models import (
    MaterialStockMovement, PublicStockBalance, PublicStockMovement,
    SemiFinishedStockBalance, SemiFinishedStockMovement,
)
from apps.inventory.public_stock_identity import build_pipe_stock_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.material_issues.models import (
    MaterialIssueLine, MetalProcessingExternalGoodReturn, MetalProcessingExternalOrder,
    MetalProcessingOriginalHandoff, MetalProcessingSource,
)
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.organizations.models import Employee
from apps.outsourcing.models import OutsourcingOrder, OutsourcingReturn, OutsourcingReturnLine

from .test_metal_processing import ProcessingFixture
from .test_metal_processing_p4 import MetalProcessingP4Fixture


class PublicProcessingFixture(MetalProcessingP4Fixture):
    def setUp(self):
        # 旧夹具的采购入库仅用于创建字典/来源；本链路实际领用单独的公共余额。
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False):
            ProcessingFixture.setUp(self)
        original_payload = self.f.spray_payload()
        item = original_payload["products"][0]["processing_items"][0]
        item["quantity"] = "12"
        item["allocations"][0].update(allocated_quantity="12", input_quantity="12")
        original_payload["products"][0]["materials"][0]["planned_issue_quantity"] = "12"
        response = self.f.create_order(original_payload)
        self.assertEqual(response.status_code, 201, response.data)
        self.original_order = response.data["data"]["id"]
        self.assertEqual(OutsourcingOrder.objects.get(pk=self.original_order).stock_mode, "PUBLIC_V2")
        self.write("completions", self.complete_payload(12))

    def issue_line(self, quantity=12, confirm=True):
        f = self.f
        f.profile.category, f.profile.material, f.profile.specification = "管材", "铁", "25*0.8*3050"
        f.profile.raw_values = {**f.profile.raw_values, "tube_shape": "圆管", "tube_diameter": "25",
            "tube_thickness": "0.8", "tube_coating_color": "黑色"}
        f.profile.save()
        identity = build_pipe_stock_identity(raw_material=self.raw_pipe, raw_bar_length_m="3.05", unit=self.raw_pipe.unit)
        self.raw_credit = credit_public_stock(identity=identity, zone=self.pipe_batch.zone, quantity=100,
            source_type="S5_PROCESSING_FIXTURE", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=f.employee)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True):
            response = self.client.get("/api/v1/material-issues/requirements/", {
                "production_task_id": str(self.task.pk), "product_line_id": str(f.product_line.pk),
                "workshop_id": str(self.workshop.pk)})
            self.assertEqual(response.status_code, 200, response.data)
            pipe = next(row for row in response.data["data"]["items"] if row.get("conversion_snapshot", {}).get("kind") == "PIPE")
            payload = {"client_request_id": str(uuid.uuid4()), "schedule_product_id": str(f.schedule_product.pk),
                "plan_category": "METAL", "production_task_id": str(self.task.pk), "product_line_id": str(f.product_line.pk),
                "workshop_id": str(self.workshop.pk), "recipient_workshop_employee_id": str(self.recipient.pk),
                "issue_at": timezone.now().isoformat(), "lines": [{"requirement_id": pipe["requirement_id"],
                "requested_quantity": str(quantity)}]}
            response = self.client.post("/api/v1/material-issues/", payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            issue_id = response.data["data"]["id"]
            if confirm:
                self.issue_action(issue_id, "submit")
                self.issue_action(issue_id, "confirm-issue", {"request_id": str(uuid.uuid4())})
        return MaterialIssueLine.objects.get(issue_id=issue_id)

    def good_context(self, handoff):
        response = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]["good_return_context"]

    def good_payload(self, pieces=3, **changes):
        return {"request_id": str(uuid.uuid4()), "good_pieces": pieces,
            "zone_id": str(self.f.semi_zone.pk), "received_by_employee_id": str(self.f.employee.pk),
            "return_date": str(timezone.localdate()), "remark": "实际完成喷塑", **changes}

    def good_original(self, handoff, pieces=3, **changes):
        context = self.good_context(handoff)
        return self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/",
            self.good_payload(pieces, **changes), etag=context["etag"])

    def external_detail(self, order):
        response = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def external_write(self, order, action, payload, expected=200):
        return self.post(f"/api/v1/metal-processing-external-orders/{order.pk}/{action}/", payload,
            expected=expected, etag=self.external_detail(order)["etag"])

    def dispatch_external(self, order):
        return self.external_write(order, "handoff", {"request_id": str(uuid.uuid4()),
            "handoff_date": str(timezone.localdate()), "handoff_pieces": order.allocated_pieces})

    def ledger_counts(self):
        return {model.__name__: model.objects.count() for model in (
            MaterialStockMovement, PublicStockMovement, SemiFinishedStockMovement, OutsourcingReturn,
            MetalProcessingExternalGoodReturn)}


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicProcessingFlowTests(PublicProcessingFixture, APITestCase):
    def test_public_source_proves_actual_pieces_bars_meters_without_batches(self):
        data = self.detail().data["data"]
        snapshot = data["source_snapshot"]
        self.assertEqual(snapshot["stock_mode"], "PUBLIC_V2")
        self.assertEqual((snapshot["issued_pieces"], snapshot["bar_count"], Decimal(snapshot["meters"])),
                         (12, 2, Decimal("6.10")))
        self.assertEqual(snapshot["batches"], [])
        self.assertEqual(len(snapshot["public_stock_allocations"]), 1)
        self.assertFalse(self.line.batch_allocations.exists())
        # 当前仓库数量变化不能改写已领加工来源。
        self.raw_credit.balance.quantity = 90
        self.raw_credit.balance.meter_quantity = Decimal("274.50")
        self.raw_credit.balance.save(update_fields=["quantity", "meter_quantity"])
        self.assertEqual(self.detail().data["data"]["source_snapshot"], snapshot)

    def test_public_source_rejects_allocation_or_movement_mismatch(self):
        row = self.line.public_stock_allocations.get()
        row.snapshot = {**row.snapshot, "identity_key": "0" * 64}
        row.save(update_fields=["snapshot"])
        data = self.detail().data["data"]
        self.assertFalse(data["can_register"])
        self.assertIsNone(data["etag"])

    def test_public_source_rejects_a_movement_from_another_issue(self):
        row = self.line.public_stock_allocations.get()
        row.movement.source_id = uuid.uuid4()
        row.movement.save(update_fields=["source_id"])
        data = self.detail().data["data"]
        self.assertFalse(data["can_register"])
        self.assertIsNone(data["etag"])

    def test_direct_handoff_and_good_return_do_not_debit_raw_twice(self):
        before = list(PublicStockMovement.objects.filter(direction="OUT").values())
        handoff = self.create_original_handoff(8)
        frozen = handoff.snapshot["public_output_identity"]
        self.assertEqual(frozen["identity_snapshot"]["color"], "黑色")
        self.f.profile.raw_values["tube_coating_color"] = "白色"
        self.f.profile.cutting_length_mm = 999
        self.f.profile.save()
        payload, context = self.good_payload(), self.good_context(handoff)
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        self.post(url, payload, etag=context["etag"])
        self.post(url, payload, etag=context["etag"])
        balance = PublicStockBalance.objects.get(stock_kind="SEMI")
        self.assertEqual(balance.identity_snapshot, frozen["identity_snapshot"])
        self.assertEqual(balance.quantity, 3)
        self.assertEqual(OutsourcingReturn.objects.count(), 1)
        returned = OutsourcingReturnLine.objects.get()
        self.assertIsNone(returned.semi_finished_balance_id)
        self.assertEqual(returned.public_stock_movement.balance_id, balance.pk)
        self.assertFalse(SemiFinishedStockBalance.objects.exists())
        self.assertEqual(list(PublicStockMovement.objects.filter(direction="OUT").values()), before)

    def test_handoff_rejects_mixed_document_modes_without_any_stock_write(self):
        OutsourcingOrder.objects.filter(pk=self.original_order).update(stock_mode="LEGACY")
        before = self.ledger_counts()
        self.write("handoffs", {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 8,
            "handoff_date": str(timezone.localdate())}, expected=409)
        self.assertEqual(self.ledger_counts(), before)
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_missing_old_public_bom_snapshot_never_uses_current_bom(self):
        # 模拟 S4 已领记录：有真实公共扣库凭证，但当时还没有输出物理属性冻结。
        self.line.conversion_snapshot.pop("public_bom_snapshot")
        self.line.save(update_fields=["conversion_snapshot"])
        row = self.line.public_stock_allocations.get()
        row.movement.snapshot["conversion"] = self.line.conversion_snapshot
        row.movement.save(update_fields=["snapshot"])
        source = MetalProcessingSource.objects.get(issue_line=self.line)
        source.source_snapshot = frozen_source(MaterialIssueLine.objects.get(pk=self.line.pk))
        source.source_hash = digest(source.source_snapshot)
        source.save(update_fields=["source_snapshot", "source_hash"])
        result = self.write("handoffs", {"request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 8,
            "handoff_date": str(timezone.localdate())}, expected=400)
        self.assertIn("快照", str(result.data))
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())

    def test_return_limits_invalid_zone_and_flow_gate_never_write_stock(self):
        handoff = self.create_original_handoff(8)
        context, before = self.good_context(handoff), self.ledger_counts()
        url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/"
        self.post(url, self.good_payload(9), expected=409, etag=context["etag"])
        self.post(url, self.good_payload(zone_id=str(self.f.defective_zone.pk)), expected=400, etag=context["etag"])
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            self.post(url, self.good_payload(), expected=400, etag=context["etag"])
        self.assertEqual(self.ledger_counts(), before)

    def test_public_credit_failure_rolls_back_return_document_and_order_status(self):
        handoff = self.create_original_handoff(8)
        context, before = self.good_context(handoff), self.ledger_counts()
        with patch("apps.material_issues.p4_services.credit_public_stock", side_effect=ValidationError("库存故障")):
            self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/",
                self.good_payload(), expected=400, etag=context["etag"])
        self.assertEqual(self.ledger_counts(), before)
        self.assertEqual(OutsourcingOrder.objects.get(pk=self.original_order).status, "PROCESSING")

    def test_unsprayed_rework_and_rehandoff_are_only_work_in_progress(self):
        before = self.ledger_counts()
        order = self.create_order(5)
        self.assertEqual(order.stock_mode, "PUBLIC_V2")
        original = order.original_return.original_handoff.snapshot["public_output_identity"]
        self.assertEqual(order.output_identity_snapshot, original)
        self.dispatch_external(order)
        self.assertEqual(self.ledger_counts(), before)
        self.f.profile.raw_values["tube_coating_color"] = "红色"
        self.f.profile.save()
        first = self.good_payload(3)
        etag = self.external_detail(order)["etag"]
        url = f"/api/v1/metal-processing-external-orders/{order.pk}/returns/"
        self.post(url, first, etag=etag)
        self.post(url, first, etag=etag)
        record = MetalProcessingExternalGoodReturn.objects.get()
        self.assertIsNotNone(record.public_stock_movement_id)
        self.assertEqual(record.public_stock_movement.balance.identity_snapshot, original["identity_snapshot"])
        self.assertEqual(PublicStockBalance.objects.get(stock_kind="SEMI").quantity, 3)
        self.external_write(order, "returns", self.good_payload(3), expected=409)
        self.good_original(order.original_return.original_handoff, 3)
        self.assertEqual(PublicStockBalance.objects.get(stock_kind="SEMI").quantity, 6)
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_public_semi_query_includes_other_order_source_but_excludes_other_color(self):
        order = self.create_order(5)
        other_task = copy.copy(self.task)
        other_task.pk = uuid.uuid4()
        other_task.task_number, other_task.contract_number = "S5-PUBLIC-OTHER", "S5-PUBLIC-OTHER"
        other_task.source_request_key = None
        other_task._state = copy.copy(other_task._state)
        other_task._state.adding = True
        other_task.save(force_insert=True)
        credit_public_stock(identity=order.output_identity_snapshot, zone=self.f.semi_zone, quantity=7,
            source_type="OTHER_ORDER_RETURN", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.f.employee, production_task=other_task)
        from apps.inventory.tests.test_public_stock_identity import PublicStockIdentityTests
        different = copy.deepcopy(order.output_identity_snapshot)
        different["identity_snapshot"]["color"] = "白色"
        different = PublicStockIdentityTests.rehash(different)
        credit_public_stock(identity=different, zone=self.f.semi_zone, quantity=13,
            source_type="OTHER_COLOR_RETURN", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.f.employee)
        response = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/semi-stock/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data["data"]["available_pieces"]), 7)
        self.assertEqual(len(response.data["data"]["zones"]), 1)

    def test_closed_external_order_late_return_keeps_original_difference_snapshot(self):
        order = self.create_order(5)
        self.dispatch_external(order)
        self.external_write(order, "returns", self.good_payload(2))
        closed = self.external_write(order, "close", {"request_id": str(uuid.uuid4()), "remark": "余量暂缺，备注结清"})
        frozen = closed.data["data"]["closure"]
        self.external_write(order, "returns", self.good_payload(1, remark=" "), expected=400)
        self.external_write(order, "returns", self.good_payload(3, remark="结清后到货补登记"))
        self.assertEqual(self.external_detail(order)["closure"], frozen)
        self.assertEqual(PublicStockBalance.objects.get(stock_kind="SEMI").quantity, 5)
        self.assertEqual(self.external_detail(order)["status"], "COMPLETED")

    def test_original_closure_and_late_unsprayed_and_good_return_keep_shared_limit(self):
        handoff = self.create_original_handoff(12)
        base = f"/api/v1/metal-processing-original-orders/{self.original_order}/"
        context = self.client.get(base).data["data"]
        closed = self.post(base + "close/", {"request_id": str(uuid.uuid4()), "remark": "差额暂缺，备注结清"},
                           etag=context["etag"]).data["data"]
        frozen = closed["closure"]
        self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/returns/",
            {"request_id": str(uuid.uuid4()), "returned_pieces": 2,
             "received_by_employee_id": str(self.f.employee.pk), "storage_location": "金工暂存",
             "return_date": str(timezone.localdate()), "remark": "结清后未喷塑件补登记"}, etag=self.source_etag())
        self.assertFalse(PublicStockBalance.objects.filter(stock_kind="SEMI").exists())
        self.good_original(handoff, 10, remark="结清后合格件补到")
        self.assertEqual(PublicStockBalance.objects.get(stock_kind="SEMI").quantity, 10)
        context = self.client.get(base).data["data"]
        self.assertEqual(context["closure"], frozen)
        self.assertEqual(context["original_order_status"], "COMPLETED")

    def test_external_return_rejects_missing_frozen_handoff_identity(self):
        order = self.create_order(5)
        self.dispatch_external(order)
        handoff = order.handoff
        handoff.snapshot.pop("public_output_identity")
        handoff.save(update_fields=["snapshot"])
        before = self.ledger_counts()
        self.external_write(order, "returns", self.good_payload(3), expected=409)
        self.assertEqual(self.ledger_counts(), before)

    def test_return_permission_and_source_visibility_are_preserved(self):
        handoff = self.create_original_handoff(8)
        context = self.good_context(handoff)
        outsider = get_user_model().objects.create_user(username="s5-no-return")
        Employee.objects.create(user=outsider, employee_code="S5-NO-RETURN", display_name="无回货权限")
        self.client.force_authenticate(outsider)
        before = self.ledger_counts()
        self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/", self.good_payload(),
            expected=403, etag=context["etag"])
        self.assertEqual(self.ledger_counts(), before)


class LegacyProcessingModeTests(MetalProcessingP4Fixture, APITestCase):
    def test_full_switch_does_not_reinterpret_legacy_source_or_write_legacy_semi(self):
        handoff = self.create_original_handoff(8)
        before = self.detail().data["data"]["source_snapshot"]
        self.assertNotIn("stock_mode", before)
        self.assertNotIn("schema_version", before)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            current = self.detail().data["data"]["source_snapshot"]
            self.assertEqual(current, before)
            context = self.client.get(f"/api/v1/metal-processing-handoffs/{handoff.pk}/").data["data"]["good_return_context"]
            self.assertFalse(context["can_return"])
            payload = {"request_id": str(uuid.uuid4()), "good_pieces": 1, "zone_id": str(self.f.semi_zone.pk),
                "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()), "remark": "旧单"}
            self.post(f"/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/", payload,
                expected=400, etag=context["etag"])
            self.write("close", {"request_id": str(uuid.uuid4()), "remark": "加工数量备注结清"})
        self.assertFalse(SemiFinishedStockMovement.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())
