import copy
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.material_flow_calculations import pipe_plan
from apps.inventory.models import (MaterialInboundLine, MaterialInboundStatus, MaterialStockBalance,
                                   MaterialStockMovement, SemiFinishedStockBalance)
from apps.inventory.stock_services import credit_confirmed_inbound_line, inbound_batch_available_quantities
from apps.material_issues.models import OrderMaterialRequirement
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from ..models import (OutsourcingOrder, OutsourcingMaterialItem, OutsourcingDispatchLine,
                      OutsourcingFactoryAllocation, OutsourcingFactoryCraft,
                      OutsourcingRawReturn, OutsourcingRawReturnLine)
from . import test_outsourcing_source_bom_api as fixtures


class MaterialFlowFixture:
    def setUp(self):
        self.f = fixtures.OutsourcingWarehouseFlowApiTests(methodName="test_create_persists_nested_order_without_inventory_write")
        self.f.setUp()
        self.client = self.f.client
        f = self.f
        ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "S6-SET"})
        root_unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "S6-BAR"})
        category, _ = ProductCategory.objects.get_or_create(category_name="管材", defaults={"item_type": "MATERIAL"})
        self.raw_pipe = RawMaterialInformation.objects.create(material_number="S6-PIPE", item_type="MATERIAL", category=category,
            material_name="S6 前脚管原料", specification="25", material="铁", unit=root_unit)
        f.cutting.fabric_source_line = f.fabric
        f.cutting.fabric_meters_per_set = Decimal("1.5")
        f.cutting.save()
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=4, pieces_per_bar=6, order_quantity=100)
        f.profile.cutting_length_mm = 500
        f.profile.pieces_per_product = 4
        f.profile.pieces_per_bar = 6
        f.profile.raw_bar_length_m = plan["raw_bar_length_m"]
        f.profile.suggested_bar_count = plan["suggested_bar_count"]
        f.profile.suggested_purchase_meters = plan["suggested_purchase_meters"]
        f.profile.raw_values = {"source_inventory_material_id": str(self.raw_pipe.pk)}
        f.profile.save()
        self.pipe_batch = MaterialInboundLine.objects.create(inbound=f.material_inbound, raw_material_information=self.raw_pipe,
            zone=f.material_balance.zone, measurement_kind="PIPE", raw_bar_length_m="3.05", received_bar_count=100,
            accepted_bar_count=100, return_bar_count=0, received_quantity=305, accepted_quantity=305, return_quantity=0,
            source_unit_text_snapshot="米", purchased_quantity_snapshot=305)
        self.pipe_balance = credit_confirmed_inbound_line(line=self.pipe_batch, actor_employee=f.employee).balance

    def payload(self, kind="PIPE", amount="402"):
        f = self.f
        payload = f.spray_payload() if kind == "PIPE" else f.payload()
        product = payload["products"][0]
        output = Decimal(amount) if kind == "PIPE" else Decimal(amount) // Decimal("1.5")
        product["processing_items"][0]["quantity"] = str(output)
        allocation = product["processing_items"][0]["allocations"][0]
        allocation.update(input_quantity=amount, allocated_quantity=str(output))
        product["materials"][0]["planned_issue_quantity"] = amount
        return payload

    def create(self, kind="PIPE", amount="402"):
        response = self.f.create_order(self.payload(kind, amount))
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]["id"]

    def post(self, order_id, action, payload, expected=200, etag=None):
        detail = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200, detail.data)
        response = self.client.post(f"/api/v1/outsourcing-orders/{order_id}/{action}/", payload,
            format="json", HTTP_HOST="localhost", HTTP_IF_MATCH=etag or detail["ETag"])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def dispatch(self, order_id, kind="PIPE", amount="402"):
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        payload = {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.pipe_batch.pk if kind == "PIPE" else self.f.material_inbound_line.pk), "requested_quantity": amount}]}
        self.post(order_id, "confirm-dispatch", payload)
        return payload, OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)

    def entry(self, source, kind, amount):
        return {"allocation_id": str(source.material_item.allocation_id), "dispatch_line_id": None if kind == "OUTPUT_SCRAP" else str(source.pk),
                "kind": kind, "quantity": str(amount), "reason": "实物核对确认"}

    def reconcile(self, order_id, source, kind, amount, expected=200):
        payload = {"request_id": str(uuid.uuid4()), "entries": [self.entry(source, kind, amount)]}
        self.post(order_id, "confirm-reconciliation", payload, expected)
        return payload

    def return_goods(self, order_id, source, good, bad=0, raw_inputs=None, expected=200):
        f = self.f
        payload = {"request_id": str(uuid.uuid4()), "factory_id": str(f.factory.pk),
            "good_zone_id": str(f.semi_zone.pk), "defective_zone_id": str(f.defective_zone.pk),
            "received_by_employee_id": str(f.employee.pk), "return_date": str(timezone.localdate()),
            "lines": [{"allocation_id": str(source.material_item.allocation_id), "good_quantity": str(good),
                       "defective_quantity": str(bad), "defect_reason": "表面不良"}], "raw_inputs": raw_inputs or []}
        self.post(order_id, "confirm-return", payload, expected)
        return payload

    def raw_return(self, order_id, source, amount, expected=200):
        payload = {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk), "reason": "未使用整料退回",
                   "lines": [{"dispatch_line_id": str(source.pk), "quantity": str(amount)}]}
        self.post(order_id, "confirm-raw-return", payload, expected)
        return payload


class MaterialFlowApiTests(MaterialFlowFixture, APITestCase):
    def revoke(self, order_id, *, request_id=None, reason="发料作废，原料退回", expected=200, etag=None):
        payload = {"request_id": request_id or str(uuid.uuid4()), "reason": reason}
        response = self.post(order_id, "revoke-dispatched", payload, expected, etag=etag)
        return payload, response

    def test_zone_dispatch_splits_pipe_batches_and_revoke_restores_sources(self):
        self.pipe_balance.quantity = Decimal("30")
        self.pipe_balance.meter_quantity = Decimal("91.50")
        self.pipe_balance.save(update_fields=["quantity", "meter_quantity"])
        second_batch = MaterialInboundLine.objects.create(
            inbound=self.f.material_inbound, raw_material_information=self.raw_pipe,
            zone=self.pipe_batch.zone, measurement_kind="PIPE", raw_bar_length_m="3.05",
            received_bar_count=100, accepted_bar_count=100, return_bar_count=0,
            received_quantity=305, accepted_quantity=305, return_quantity=0,
            source_unit_text_snapshot="米", purchased_quantity_snapshot=305,
        )
        second_balance = credit_confirmed_inbound_line(line=second_batch, actor_employee=self.f.employee).balance
        order_id = self.create()
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        context = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/", HTTP_HOST="localhost")
        self.assertEqual(context.status_code, 200, context.data)
        row = context.data["data"]["materials"][0]
        self.assertEqual((row["internal_issued_quantity"], row["outsourcing_issued_quantity"]), ("0", "0"))
        self.assertGreaterEqual(Decimal(row["max_issue_quantity"]), Decimal("402"))
        self.assertEqual(len(row["zones"]), 1)
        payload = {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "zone_id": str(self.pipe_batch.zone_id), "requested_quantity": "402"}]}
        dispatched = self.post(order_id, "confirm-dispatch", payload)
        self.assertEqual(dispatched.data["data"]["dispatch"]["line_count"], 2)
        sources = list(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).order_by("inbound_line__created_at"))
        self.assertEqual({source.inbound_line_id: source.source_quantity for source in sources},
            {self.pipe_batch.pk: Decimal("30"), second_batch.pk: Decimal("37")})
        self.revoke(order_id)
        self.pipe_balance.refresh_from_db()
        second_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, second_balance.quantity), (Decimal("30"), Decimal("100")))
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=sources[0].requirement_id).outsourcing_issued_quantity, 0)

    def test_zone_dispatch_fabric_and_insufficient_stock_rolls_back(self):
        order_id = self.create("FABRIC", "100")
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        payload = {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "zone_id": str(uuid.uuid4()), "requested_quantity": "100"}]}
        self.post(order_id, "confirm-dispatch", payload, 400)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).exists())
        payload["request_id"] = str(uuid.uuid4())
        payload["lines"][0]["zone_id"] = str(self.f.material_balance.zone_id)
        self.post(order_id, "confirm-dispatch", payload)
        source = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
        self.assertEqual((source.inbound_line_id, source.zone_id, source.source_quantity),
            (self.f.material_inbound_line.pk, self.f.material_balance.zone_id, Decimal("100")))

    def test_create_rejects_price_finer_than_one_cent(self):
        payload = self.payload()
        payload["products"][0]["processing_items"][0]["allocations"][0]["unit_price"] = "2.5050"
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(OutsourcingOrder.objects.filter(client_request_id=payload["client_request_id"]).exists())

    def test_revoke_dispatched_pipe_restores_original_batch_and_allowance_once(self):
        order_id = self.create()
        listing = self.client.get("/api/v1/outsourcing-orders/", HTTP_HOST="localhost")
        self.assertTrue(next(row for row in listing.data["data"] if row["id"] == order_id)["can_delete"])
        _, source = self.dispatch(order_id)
        detail = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/", HTTP_HOST="localhost")
        self.assertTrue(detail.data["data"]["can_revoke_dispatched"])
        self.assertFalse(detail.data["data"]["can_delete"])
        listing = self.client.get("/api/v1/outsourcing-orders/", HTTP_HOST="localhost")
        self.assertTrue(next(row for row in listing.data["data"] if row["id"] == order_id)["can_revoke_dispatched"])
        payload, revoked = self.revoke(order_id, etag=detail["ETag"])
        self.assertEqual(revoked.data["data"]["status"], "CANCELLED")
        self.assertFalse(revoked.data["data"]["can_revoke_dispatched"])
        self.assertEqual(revoked.data["data"]["dispatch"]["line_count"], 1)
        self.pipe_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, self.pipe_balance.meter_quantity), (100, Decimal("305.00")))
        requirement = OrderMaterialRequirement.objects.get(pk=source.requirement_id)
        self.assertEqual(requirement.outsourcing_issued_quantity, 0)
        self.assertEqual(OutsourcingRawReturnLine.objects.filter(dispatch_line=source).count(), 1)
        movement = MaterialStockMovement.objects.get(source_type="OUTSOURCING_RAW_RETURN")
        self.assertEqual((movement.balance_id, movement.quantity, movement.meter_quantity),
                         (self.pipe_balance.pk, 67, Decimal("204.35")))
        self.assertEqual(movement.snapshot["inbound_line_id"], str(self.pipe_batch.pk))
        self.assertEqual(movement.snapshot["revocation_request_id"], payload["request_id"])
        self.assertEqual(AuditLog.objects.filter(object_type="OUTSOURCING_ORDER", object_id=order_id,
                                                 action="DISPATCH_REVOKED").count(), 1)
        self.revoke(order_id, request_id=payload["request_id"], etag=detail["ETag"])
        self.assertEqual(OutsourcingRawReturnLine.objects.filter(dispatch_line=source).count(), 1)
        self.revoke(order_id, expected=409)

    def test_revoke_after_partial_and_full_prior_raw_returns_only_restores_remaining(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.raw_return(order_id, source, 2)
        self.revoke(order_id)
        returned = list(OutsourcingRawReturnLine.objects.filter(dispatch_line=source).values_list("quantity", flat=True))
        self.assertEqual(sorted(returned), [Decimal("2"), Decimal("65")])
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=source.requirement_id).outsourcing_issued_quantity, 0)

        second = self.create(amount="6")
        _, second_source = self.dispatch(second, amount="6")
        self.raw_return(second, second_source, 1)
        before = MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").count()
        record_count = OutsourcingRawReturn.objects.filter(order_id=second).count()
        payload, _ = self.revoke(second)
        self.assertEqual(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").count(), before)
        self.assertEqual(OutsourcingRawReturn.objects.filter(order_id=second).count(), record_count)
        self.revoke(second, request_id=payload["request_id"])
        self.assertEqual(OutsourcingRawReturnLine.objects.filter(dispatch_line=second_source).count(), 1)

    def test_revoke_fabric_restores_original_inbound_batch_and_zone(self):
        order_id = self.create("FABRIC", "100")
        before = inbound_batch_available_quantities([self.f.material_inbound_line])[self.f.material_inbound_line.pk]
        _, source = self.dispatch(order_id, "FABRIC", "100")
        self.revoke(order_id)
        after = inbound_batch_available_quantities([self.f.material_inbound_line])[self.f.material_inbound_line.pk]
        self.assertEqual(after, before)
        movement = MaterialStockMovement.objects.get(source_type="OUTSOURCING_RAW_RETURN")
        self.assertEqual((movement.balance.zone_id, movement.quantity, movement.snapshot["inbound_line_id"]),
                         (source.zone_id, Decimal("100"), str(source.inbound_line_id)))
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=source.requirement_id).outsourcing_issued_quantity, 0)

    def test_revoke_is_blocked_by_raw_input_loss_return_and_legacy_snapshot(self):
        for kind in ("RAW_INPUT", "RAW_LOSS"):
            order_id = self.create(amount="6")
            _, source = self.dispatch(order_id, amount="6")
            self.reconcile(order_id, source, kind, 1)
            self.revoke(order_id, expected=409)
        legacy = self.create(amount="6")
        _, source = self.dispatch(legacy, amount="6")
        source.snapshot = {**source.snapshot, "schema_version": 1}
        source.save(update_fields=["snapshot"])
        self.revoke(legacy, expected=409)
        self.assertEqual(OutsourcingRawReturnLine.objects.count(), 0)

    def test_revoke_is_blocked_after_goods_return_or_output_scrap(self):
        returned_order = self.create(amount="6")
        _, returned_source = self.dispatch(returned_order, amount="6")
        self.return_goods(returned_order, returned_source, 1,
                          raw_inputs=[self.entry(returned_source, "RAW_INPUT", 1)])
        self.revoke(returned_order, expected=409)

        scrapped_order = self.create(amount="6")
        _, scrapped_source = self.dispatch(scrapped_order, amount="6")
        self.reconcile(scrapped_order, scrapped_source, "RAW_INPUT", 1)
        self.reconcile(scrapped_order, scrapped_source, "OUTPUT_SCRAP", 1)
        self.revoke(scrapped_order, expected=409)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())

    def test_revoke_request_id_conflicts_across_orders_and_with_changed_reason(self):
        first = self.create(amount="6")
        self.dispatch(first, amount="6")
        payload, _ = self.revoke(first)
        self.revoke(first, request_id=payload["request_id"], reason="另一原因", expected=409)
        second = self.create(amount="6")
        self.dispatch(second, amount="6")
        self.revoke(second, request_id=payload["request_id"], expected=409)
        self.assertEqual(OutsourcingOrder.objects.get(pk=second).status, "PROCESSING")
        self.assertEqual(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").count(), 1)

    def test_revoke_rejects_changed_original_inbound_status(self):
        order_id = self.create(amount="6")
        self.dispatch(order_id, amount="6")
        self.f.material_inbound.status = MaterialInboundStatus.PENDING_QUALITY
        self.f.material_inbound.save(update_fields=["status"])
        self.revoke(order_id, expected=409)
        self.assertEqual(OutsourcingOrder.objects.get(pk=order_id).status, "PROCESSING")
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())

    def test_revoke_rejects_disabled_original_zone(self):
        order_id = self.create(amount="6")
        self.dispatch(order_id, amount="6")
        self.f.material_balance.zone.status = "DISABLED"
        self.f.material_balance.zone.save(update_fields=["status"])
        self.revoke(order_id, expected=409)
        self.assertEqual(OutsourcingOrder.objects.get(pk=order_id).status, "PROCESSING")
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())

    def test_revoke_rejects_changed_material_unit_or_pipe_piece_snapshot(self):
        fabric = self.create("FABRIC", "100")
        _, fabric_source = self.dispatch(fabric, "FABRIC", "100")
        other_unit = ProductionUnit.objects.create(unit_name="异单位", unit_code="S6-OTHER-UNIT")
        fabric_source.raw_material.unit = other_unit
        fabric_source.raw_material.save(update_fields=["unit"])
        self.revoke(fabric, expected=409)

        pipe = self.create(amount="6")
        _, pipe_source = self.dispatch(pipe, amount="6")
        pipe_source.issued_piece_count = 5
        pipe_source.save(update_fields=["issued_piece_count"])
        detail = self.client.get(f"/api/v1/outsourcing-orders/{pipe}/", HTTP_HOST="localhost")
        self.assertFalse(detail.data["data"]["can_revoke_dispatched"])
        self.revoke(pipe, expected=409)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())

    def test_revoke_two_factories_restores_each_source_and_retains_two_records(self):
        second_factory = copy.copy(self.f.factory)
        second_factory.pk = None
        second_factory.factory_number = "S6-REVOCATION-FACTORY-TWO"
        second_factory.name = "撤销测试第二加工厂"
        second_factory.save()
        for link in self.f.factory.craft_links.all():
            OutsourcingFactoryCraft.objects.create(
                factory=second_factory, craft=link.craft, craft_name_snapshot=link.craft_name_snapshot,
            )
        payload = self.payload(amount="12")
        product = payload["products"][0]
        allocation = product["processing_items"][0]["allocations"][0]
        allocation.update(input_quantity="6", allocated_quantity="6")
        product["processing_items"][0]["allocations"].append({**allocation, "factory_id": str(second_factory.pk)})
        product["materials"][0]["planned_issue_quantity"] = "6"
        product["materials"].append({**product["materials"][0], "factory_id": str(second_factory.pk)})
        created = self.f.create_order(payload)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        materials = list(OutsourcingMaterialItem.objects.filter(
            allocation__processing_item__order_product__order_id=order_id
        ))
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [
            {"material_item_id": str(material.pk), "inbound_line_id": str(self.pipe_batch.pk),
             "requested_quantity": "6"} for material in materials
        ]})
        self.revoke(order_id)
        self.assertEqual(OutsourcingRawReturn.objects.filter(order_id=order_id).count(), 2)
        self.assertEqual(OutsourcingRawReturnLine.objects.filter(record__order_id=order_id).count(), 2)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)

    def test_revoke_rejects_p4_stale_etag_missing_etag_and_missing_permissions(self):
        order_id = self.create(amount="6")
        self.dispatch(order_id, amount="6")
        detail = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/", HTTP_HOST="localhost")
        payload = {"request_id": str(uuid.uuid4()), "reason": "退料作废"}
        url = f"/api/v1/outsourcing-orders/{order_id}/revoke-dispatched/"
        self.assertEqual(self.client.post(url, payload, format="json", HTTP_HOST="localhost").status_code, 428)
        self.revoke(order_id, expected=412, etag='"stale"')
        with patch("apps.material_issues.p4_services.has_original_direct_handoff", return_value=True):
            self.revoke(order_id, expected=409, etag=detail["ETag"])
        self.f.user.is_superuser = False
        self.f.user.save(update_fields=["is_superuser"])
        self.f.user.user_permissions.add(Permission.objects.get(codename="view_outsourcingorder"),
            Permission.objects.get(codename="view_all_productionschedule"),
            Permission.objects.get(codename="cancel_outsourcingorder"))
        self.assertEqual(self.client.post(url, payload, format="json", HTTP_HOST="localhost",
                                          HTTP_IF_MATCH=detail["ETag"]).status_code, 403)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())

    def test_revoke_failure_rolls_back_return_record_stock_and_status(self):
        order_id = self.create(amount="6")
        _, source = self.dispatch(order_id, amount="6")
        requirement = OrderMaterialRequirement.objects.get(pk=source.requirement_id)
        requirement.outsourcing_issued_quantity = 0
        requirement.save(update_fields=["outsourcing_issued_quantity"])
        self.revoke(order_id, expected=409)
        self.assertEqual(OutsourcingOrder.objects.get(pk=order_id).status, "PROCESSING")
        self.assertFalse(OutsourcingRawReturnLine.objects.filter(dispatch_line=source).exists())
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN").exists())
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 99)

    def test_pipe_create_dispatch_raw_return_goods_scrap_and_complete(self):
        order_id = self.create()
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)
        _, source = self.dispatch(order_id)
        self.pipe_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, self.pipe_balance.meter_quantity), (33, Decimal("100.65")))
        self.assertEqual((source.issued_piece_count, source.issued_quantity, source.issued_meters), (402, 67, Decimal("204.35")))
        self.raw_return(order_id, source, 2)
        requirement = OrderMaterialRequirement.objects.get(pk=source.requirement_id)
        self.assertEqual(requirement.outsourcing_issued_quantity, 390)
        self.reconcile(order_id, source, "RAW_INPUT", 65)
        self.return_goods(order_id, source, 380, 5)
        self.assertEqual(OutsourcingOrder.objects.get(pk=order_id).status, "PARTIAL_RETURN")
        self.post(order_id, "complete", {"request_id": str(uuid.uuid4())}, 400)
        self.reconcile(order_id, source, "OUTPUT_SCRAP", 5)
        self.post(order_id, "complete", {"request_id": str(uuid.uuid4())})
        self.assertEqual(OutsourcingOrder.objects.get(pk=order_id).status, "COMPLETED")
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 35)
        self.assertEqual(SemiFinishedStockBalance.objects.get(quality="AVAILABLE").quantity, 380)

    def test_fabric_partial_return_restores_original_batch_and_capacity(self):
        order_id = self.create("FABRIC", "100")
        _, source = self.dispatch(order_id, "FABRIC", "100")
        self.return_goods(order_id, source, 60, 6, [self.entry(source, "RAW_INPUT", 99)])
        self.raw_return(order_id, source, 1)
        self.post(order_id, "complete", {"request_id": str(uuid.uuid4())})
        available = inbound_batch_available_quantities([self.f.material_inbound_line])
        self.assertEqual(available[self.f.material_inbound_line.pk], 101)
        self.assertEqual(SemiFinishedStockBalance.objects.get(quality="AVAILABLE").unit.unit_name, "套")

    def test_fabric_less_than_one_set_can_be_returned_without_fictitious_output(self):
        order_id = self.create("FABRIC", "1")
        self.assertEqual(OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=order_id).allocated_quantity, 0)
        _, source = self.dispatch(order_id, "FABRIC", "1")
        self.raw_return(order_id, source, 1)
        self.post(order_id, "complete", {"request_id": str(uuid.uuid4())})
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_nonwhole_pipe_create_is_rejected(self):
        response = self.f.create_order(self.payload(amount="400"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(OutsourcingOrder.objects.exists())

    def test_fabric_missing_mapping_blocks_before_creation(self):
        self.f.cutting.fabric_source_line = None
        self.f.cutting.save()
        response = self.f.create_order(self.payload("FABRIC", "100"))
        self.assertEqual(response.status_code, 400, response.data)

    def test_missing_input_quantity_is_not_guessed(self):
        payload = self.payload()
        del payload["products"][0]["processing_items"][0]["allocations"][0]["input_quantity"]
        self.assertEqual(self.f.create_order(payload).status_code, 400)

    def test_pending_orders_do_not_consume_stock_or_allowance(self):
        self.create()
        self.create()
        self.assertFalse(OrderMaterialRequirement.objects.filter(outsourcing_issued_quantity__gt=0).exists())
        self.assertFalse(MaterialStockMovement.objects.filter(direction="OUT").exists())

    def test_shared_allowance_blocks_second_dispatch_and_rolls_back(self):
        first, second = self.create(), self.create()
        self.dispatch(first)
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=second)
        self.post(second, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "402"}]}, 409)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=second).exists())

    def test_dispatch_retry_same_payload_once_and_changed_payload_conflicts(self):
        order_id = self.create()
        payload, _ = self.dispatch(order_id)
        self.post(order_id, "confirm-dispatch", payload)
        changed = copy.deepcopy(payload)
        changed["lines"][0]["requested_quantity"] = "396"
        self.post(order_id, "confirm-dispatch", changed, 409)
        self.assertEqual(MaterialStockMovement.objects.filter(direction="OUT").count(), 1)

    def test_returned_input_cannot_also_be_consumed_or_lost(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.raw_return(order_id, source, 2)
        self.reconcile(order_id, source, "RAW_INPUT", 66, 409)
        self.reconcile(order_id, source, "RAW_LOSS", 66, 409)
        self.raw_return(order_id, source, "0.5", 400)

    def test_raw_return_retry_and_over_return(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        payload = self.raw_return(order_id, source, 2)
        self.post(order_id, "confirm-raw-return", payload)
        self.raw_return(order_id, source, 66, 409)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 35)

    def test_partial_goods_require_input_and_do_not_debit_raw_again(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.return_goods(order_id, source, 1, expected=409)
        payload = self.return_goods(order_id, source, 1, raw_inputs=[self.entry(source, "RAW_INPUT", 1)])
        self.post(order_id, "confirm-return", payload)
        self.return_goods(order_id, source, "0.5", expected=400)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 33)
        self.assertEqual(SemiFinishedStockBalance.objects.get(quality="AVAILABLE").quantity, 1)

    def test_defective_receipt_cannot_be_scrapped_again(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.return_goods(order_id, source, 0, 6, [self.entry(source, "RAW_INPUT", 1)])
        self.reconcile(order_id, source, "OUTPUT_SCRAP", 1, 409)

    def test_raw_loss_and_process_scrap_are_distinct_and_completion_retry_safe(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.reconcile(order_id, source, "RAW_LOSS", 67)
        payload = {"request_id": str(uuid.uuid4())}
        self.post(order_id, "complete", payload)
        self.post(order_id, "complete", payload)
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_expired_etag_rejects_new_operation(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.post(order_id, "confirm-raw-return", {"request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
            "reason": "退回", "lines": [{"dispatch_line_id": str(source.pk), "quantity": "1"}]}, 412, etag='"old"')

    def test_source_revision_change_blocks_dispatch(self):
        order_id = self.create()
        self.f.profile.notes = "来源改变"
        self.f.profile.save()
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "402"}]}, 409)

    def test_new_actions_require_dedicated_permissions(self):
        order_id = self.create()
        self.dispatch(order_id)
        self.f.user.is_superuser = False
        self.f.user.save()
        self.f.user.user_permissions.add(Permission.objects.get(codename="view_outsourcingorder"),
            Permission.objects.get(codename="view_all_productionschedule"))
        for action in ["confirm-raw-return", "confirm-reconciliation", "complete"]:
            response = self.client.post(f"/api/v1/outsourcing-orders/{order_id}/{action}/", {}, format="json", HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 403, response.data)

    def test_source_preview_and_reconciliation_are_read_only(self):
        counts = (OrderMaterialRequirement.objects.count(), MaterialStockMovement.objects.count())
        response = self.f.get_bom(self.f.spray)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"]["processing_items"][0]
        self.assertEqual(row["unit"], "支")
        self.assertEqual(Decimal(row["available_quantity"]), 408)
        self.assertEqual(counts, (OrderMaterialRequirement.objects.count(), MaterialStockMovement.objects.count()))

    def test_nonwhole_each_batch_rejects_even_if_total_whole(self):
        order_id = self.create()
        second = copy.copy(self.pipe_batch)
        second.pk = None
        second.save()
        credit_confirmed_inbound_line(line=second, actor_employee=self.f.employee)
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "3"}, {"material_item_id": str(material.pk),
            "inbound_line_id": str(second.pk), "requested_quantity": "399"}]}, 400)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)

    def test_fabric_three_one_meter_inputs_at_three_meters_per_set(self):
        self.f.cutting.fabric_meters_per_set = 3
        self.f.cutting.save()
        payload = self.payload("FABRIC", "3")
        payload["products"][0]["processing_items"][0]["quantity"] = "1"
        payload["products"][0]["processing_items"][0]["allocations"][0]["allocated_quantity"] = "1"
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        batches = [self.f.material_inbound_line]
        for _ in range(2):
            batch = copy.copy(self.f.material_inbound_line)
            batch.pk = None
            batch.save()
            credit_confirmed_inbound_line(line=batch, actor_employee=self.f.employee)
            batches.append(batch)
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'inbound_line_id': str(batch.pk), 'requested_quantity': '1'} for batch in batches]})
        sources = list(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id))
        self.assertEqual(len(sources), 3)
        # 三个实际批次各投入一米，合并后恰好一套，不能先分别算 1/3。
        self.post(order_id, "confirm-reconciliation", {"request_id": str(uuid.uuid4()),
            "entries": [self.entry(source, "RAW_INPUT", 1) for source in sources]})
        self.return_goods(order_id, sources[0], 1)
        self.post(order_id, "complete", {"request_id": str(uuid.uuid4())})

    def test_whole_pipe_dispatch_quantity_contract_is_consistent(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.assertEqual(source.source_quantity, source.material_quantity * source.conversion_factor)
        self.assertEqual(source.source_unit_snapshot, "根")
        self.assertEqual(source.issued_piece_count, 402)

    def test_batch_preselection_persists_without_debit_and_revalidates(self):
        # 无关的历史失效批次不得阻断新来源查询或预选保存。
        bad_batch = copy.copy(self.f.material_inbound_line)
        bad_batch.pk = None
        bad_raw = copy.copy(self.f.raw_material)
        bad_raw.pk = None
        bad_raw.material_number = 'S6-ARCHIVED-UNRELATED'
        bad_raw.archived_at = timezone.now()
        bad_raw.save()
        bad_batch.raw_material_information = bad_raw
        bad_batch.save()
        self.assertEqual(self.f.get_bom(self.f.spray).status_code, 200)
        payload = self.payload()
        payload['products'][0]['materials'][0]['planned_batches'] = [
            {'inbound_line_id': str(self.pipe_batch.pk), 'quantity': '402'}]
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data['data']['id']
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)
        context = self.client.get(f'/api/v1/outsourcing-orders/{order_id}/dispatch-context/', HTTP_HOST='localhost')
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(context.data['data']['materials'][0]['planned_batches'][0]['quantity'], '402.0000')
        self.dispatch(order_id)

    def test_wrong_length_preselection_and_dispatch_are_rejected(self):
        payload = self.payload()
        payload['products'][0]['materials'][0]['planned_batches'] = [
            {'inbound_line_id': str(self.f.material_inbound_line.pk), 'quantity': '402'}]
        self.assertEqual(self.f.create_order(payload).status_code, 400)
        order_id = self.create()
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'inbound_line_id': str(self.f.material_inbound_line.pk), 'requested_quantity': '402'}]}, 400)

    def test_session_csrf_cannot_be_bypassed(self):
        from rest_framework.test import APIClient
        order_id = self.create()
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.f.user)
        response = client.post(f'/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/', {}, format='json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 403)

    def test_multiple_factories_have_separate_raw_and_output_positions(self):
        second = copy.copy(self.f.factory)
        second.pk = None
        second.factory_number = 'S6-FACTORY-TWO'
        second.name = '第二加工厂'
        second.save()
        from ..models import OutsourcingFactoryCraft
        for link in self.f.factory.craft_links.all():
            OutsourcingFactoryCraft.objects.create(factory=second, craft=link.craft, craft_name_snapshot=link.craft_name_snapshot)
        payload = self.payload(amount='12')
        product = payload['products'][0]
        allocations = product['processing_items'][0]['allocations']
        allocations[0].update(input_quantity='6', allocated_quantity='6')
        allocations.append({**allocations[0], 'factory_id': str(second.pk)})
        product['materials'][0]['planned_issue_quantity'] = '6'
        product['materials'].append({**product['materials'][0], 'factory_id': str(second.pk)})
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data['data']['id']
        materials = list(OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order_id=order_id))
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id':str(material.pk),'inbound_line_id':str(self.pipe_batch.pk),'requested_quantity':'6'} for material in materials]})
        state = self.client.get(f'/api/v1/outsourcing-orders/{order_id}/reconciliation/', HTTP_HOST='localhost').data['data']
        self.assertEqual(len(state['outputs']), 2)
        self.assertEqual(len(state['raw_materials']), 2)
        foreign = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id, material_item__allocation__factory=second)
        self.raw_return(order_id, foreign, 1, expected=400)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 98)

    def test_dispatch_omitted_zero_quota_material_creates_no_source_or_stock_movement(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'S6-EACH'})
        category, _ = ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type': 'MATERIAL'})
        raw = RawMaterialInformation.objects.create(material_number='S6-HARDWARE-ZERO', item_type='MATERIAL',
            category=category, material_name='无库存铆钉', specification='M6', unit=unit)
        self.f.hardware.raw_values = {'source_inventory_material_id': str(raw.pk)}
        self.f.hardware.save()
        payload = self.payload(amount='6')
        payload['products'][0]['materials'].append({**payload['products'][0]['materials'][0],
            'bom_line_id': str(self.f.hardware.pk), 'planned_issue_quantity': '2'})
        created = self.f.create_order(payload)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data['data']['id']
        materials = list(OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order_id=order_id))
        pipe = next(item for item in materials if item.planned_piece_count)
        hardware = next(item for item in materials if not item.planned_piece_count)
        context = self.client.get(f'/api/v1/outsourcing-orders/{order_id}/dispatch-context/', HTTP_HOST='localhost')
        self.assertEqual(context.status_code, 200, context.data)
        quota = {row['material_item_id']: row['max_issue_quantity'] for row in context.data['data']['materials']}
        self.assertEqual(Decimal(quota[str(hardware.pk)]), 0)

        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(pipe.pk), 'zone_id': str(self.pipe_batch.zone_id), 'requested_quantity': '6'}]})
        self.assertEqual(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).count(), 1)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id,
            material_item=hardware).exists())
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 99)

    def test_dispatch_rejects_omitted_material_with_positive_quota(self):
        second = copy.copy(self.f.factory)
        second.pk = None
        second.factory_number = 'S6-FACTORY-REQUIRED'
        second.name = '另一加工厂'
        second.save()
        for link in self.f.factory.craft_links.all():
            OutsourcingFactoryCraft.objects.create(factory=second, craft=link.craft, craft_name_snapshot=link.craft_name_snapshot)
        payload = self.payload(amount='12')
        product = payload['products'][0]
        allocations = product['processing_items'][0]['allocations']
        allocations[0].update(input_quantity='6', allocated_quantity='6')
        allocations.append({**allocations[0], 'factory_id': str(second.pk)})
        product['materials'][0]['planned_issue_quantity'] = '6'
        product['materials'].append({**product['materials'][0], 'factory_id': str(second.pk)})
        created = self.f.create_order(payload)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data['data']['id']
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id,
            allocation__factory=self.f.factory)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'zone_id': str(self.pipe_batch.zone_id), 'requested_quantity': '6'}]}, 400)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).exists())

    def test_dispatch_cannot_exceed_material_plan(self):
        order_id = self.create(amount='6')
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'zone_id': str(self.pipe_batch.zone_id), 'requested_quantity': '12'}]}, 400)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).exists())

    def test_dispatch_can_issue_less_than_plan_without_extra_records(self):
        order_id = self.create(amount='12')
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'zone_id': str(self.pipe_batch.zone_id), 'requested_quantity': '6'}]})
        source = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
        self.assertEqual((source.issued_piece_count, source.source_quantity), (6, Decimal('1')))
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 99)

    def test_hardware_keeps_original_unit_and_must_be_accounted(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code':'S6-EACH'})
        category, _ = ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type':'MATERIAL'})
        raw = RawMaterialInformation.objects.create(material_number='S6-HARDWARE', item_type='MATERIAL', category=category,
            material_name='测试铆钉', specification='M6', unit=unit)
        self.f.hardware.raw_values = {'source_inventory_material_id':str(raw.pk)}
        self.f.hardware.save()
        batch = MaterialInboundLine.objects.create(inbound=self.f.material_inbound, raw_material_information=raw,
            zone=self.f.material_balance.zone, received_quantity=10, accepted_quantity=10, return_quantity=0,
            source_unit_text_snapshot='个', purchased_quantity_snapshot=10)
        credit_confirmed_inbound_line(line=batch, actor_employee=self.f.employee)
        payload = self.payload(amount='6')
        payload['products'][0]['materials'].append({**payload['products'][0]['materials'][0], 'bom_line_id':str(self.f.hardware.pk), 'planned_issue_quantity':'2'})
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data['data']['id']
        materials = list(OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order_id=order_id))
        self.post(order_id,'confirm-dispatch',{'request_id':str(uuid.uuid4()),'lines':[
            {'material_item_id':str(material.pk),'inbound_line_id':str(self.pipe_batch.pk if material.planned_piece_count else batch.pk),
             'requested_quantity':'6' if material.planned_piece_count else '2'} for material in materials]})
        source = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id, raw_material=self.raw_pipe)
        self.return_goods(order_id, source, 6, raw_inputs=[self.entry(source,'RAW_INPUT',1)])
        self.post(order_id,'complete',{'request_id':str(uuid.uuid4())},400)
        hardware_source = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id, raw_material=raw)
        self.assertEqual(hardware_source.unit.unit_name,'个')
        self.reconcile(order_id, hardware_source,'RAW_INPUT',2)
        self.post(order_id,'complete',{'request_id':str(uuid.uuid4())})

    def test_internal_issue_consumes_same_pipe_allowance(self):
        from apps.material_issues.pipe_requirements import sync_pipe_requirement
        order_id = self.create()
        requirement = sync_pipe_requirement(self.f.profile.pk)
        requirement.internal_issued_quantity = 12
        requirement.save()
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'inbound_line_id': str(self.pipe_batch.pk), 'requested_quantity': '402'}]}, 409)
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, transaction
from rest_framework.test import APITransactionTestCase, APIClient


class MaterialFlowConcurrencyTests(MaterialFlowFixture, APITransactionTestCase):
    def setUp(self):
        # 排产的延迟约束要求计划与产品在同一事务内建立。
        with transaction.atomic():
            super().setUp()

    def race(self, requests):
        barrier = Barrier(len(requests))
        def execute(row):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '15s'")
                    cursor.execute("SET statement_timeout = '30s'")
                client = APIClient()
                client.force_authenticate(self.f.user)
                order_id, action, payload, etag = row
                barrier.wait(timeout=10)
                response = client.post(f'/api/v1/outsourcing-orders/{order_id}/{action}/', payload,
                    format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
                return response.status_code
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return sorted(pool.map(execute, requests))

    def dispatch_request(self, order_id, amount='402', request_id=None):
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        etag = self.client.get(f'/api/v1/outsourcing-orders/{order_id}/', HTTP_HOST='localhost')['ETag']
        return (order_id, 'confirm-dispatch', {'request_id': request_id or str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'inbound_line_id': str(self.pipe_batch.pk), 'requested_quantity': amount}]}, etag)

    def test_two_dispatches_cannot_overspend_shared_allowance_or_stock(self):
        ids = [self.create(), self.create()]
        self.assertEqual(self.race([self.dispatch_request(order_id) for order_id in ids]), [200, 409])
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 33)

    def test_cross_order_same_dispatch_request_is_conflict_not_server_error(self):
        ids = [self.create(amount='6'), self.create(amount='6')]
        request_id = str(uuid.uuid4())
        self.assertEqual(self.race([self.dispatch_request(order_id, '6', request_id) for order_id in ids]), [200, 409])
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 99)

    def test_duplicate_return_request_credits_once(self):
        order_id = self.create(amount='6')
        _, source = self.dispatch(order_id, amount='6')
        etag = self.client.get(f'/api/v1/outsourcing-orders/{order_id}/', HTTP_HOST='localhost')['ETag']
        row = (order_id, 'confirm-raw-return', {'request_id': str(uuid.uuid4()), 'factory_id': str(self.f.factory.pk),
            'reason': '退回整料', 'lines': [{'dispatch_line_id': str(source.pk), 'quantity': '1'}]}, etag)
        self.assertEqual(self.race([row, row]), [200, 200])
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 100)
