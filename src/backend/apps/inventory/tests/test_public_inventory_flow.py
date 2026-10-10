import copy
import io
import uuid
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.procurement.models import PurchaseReturn, PurchaseReturnLine
from apps.procurement.tests import test_pipe_purchase_flow as pipe_fixture
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft

from ..models import MaterialInbound, MaterialInboundLine, MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone
from ..pipe_stock_services import credit_pipe_inbound
from ..public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity
from ..public_stock_services import credit_public_stock


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicInventoryFlowTests(APITestCase):
    receive = pipe_fixture.PipePurchaseFlowTests.receive
    quality = pipe_fixture.PipePurchaseFlowTests.quality

    def setUp(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            pipe_fixture.PipePurchaseFlowTests.setUp(self)

    def manual(self, *, roots=3, length="3.05", request_id=None):
        payload = {"client_request_id": str(request_id or uuid.uuid4()), "inbound_date": timezone.localdate().isoformat(),
                   "remark": "公共库存额外入库测试", "items": [{"raw_material_id": str(self.raw_material.pk),
                       "zone_id": self.zone_id, "received_bar_count": roots, "raw_bar_length_m": length}]}
        return self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")

    def finish_return(self):
        record = PurchaseReturn.objects.get()
        path = f"/api/v1/purchase-returns/{record.pk}/"
        for action in ("confirm", "complete"):
            etag = self.client.get(path)["ETag"]
            response = self.client.post(path + action + "/", {}, format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(response.status_code, 200, response.data)

    def semi(self):
        warehouse = Warehouse.objects.create(warehouse_number="PUBFLOWSEMI", warehouse_name="公共半成品仓", warehouse_type="SEMI_FINISHED")
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="一楼")
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="支", defaults={"unit_code": "PUBFLOWPIECE"})
        craft, _ = Craft.objects.get_or_create(outsourcing_code="POWDER_COATING", defaults={"name": "喷塑", "craft_type": "EXTERNAL"})
        self.bom_line.specification = "25*1.0*6140"
        self.bom_line.raw_values = {**self.bom_line.raw_values, "tube_shape": "圆管", "tube_diameter": "25",
                                    "tube_thickness": "1.0", "tube_coating_color": "黑色"}
        self.bom_line.save()
        identity = build_semi_finished_identity(bom_line=self.bom_line, completed_craft=craft, unit=unit)
        movement = credit_public_stock(identity=identity, zone=zone, quantity=25, source_type="TEST_PUBLIC_RETURN",
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        return movement.balance, craft

    def test_pending_receipt_freezes_identity_and_quality_posts_only_accepted(self):
        receipt = self.receive()
        self.assertEqual(receipt.status_code, 201, receipt.data)
        inbound = MaterialInbound.objects.get(pk=receipt.data["data"]["id"])
        self.assertEqual(inbound.stock_mode, "PUBLIC_V2")
        self.assertIn("public_stock_identity", inbound.lines.get().calculation_snapshot)
        self.assertFalse(PublicStockBalance.objects.exists())
        result = self.quality(receipt, returned=1)
        self.assertEqual(result.status_code, 200, result.data)
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity), (1, Decimal("3.05")))
        self.assertFalse(MaterialStockBalance.objects.exists())
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal("3.05"))

    def test_two_batches_share_balance_and_purchase_trace_stays_in_meters(self):
        first = self.receive()
        self.assertEqual(self.quality(first).status_code, 200)
        second = self.receive(2, remaining="6.1000")
        self.assertEqual(self.quality(second).status_code, 200)
        self.assertEqual(MaterialInbound.objects.count(), 2)
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        inventory = self.client.get("/api/v1/material-inventory/")
        self.assertEqual(inventory.status_code, 200, inventory.data)
        row = inventory.data["results"][0]
        self.assertEqual((row["inventory_quantity"], row["meter_quantity"], row["inbound_count"]), (4, Decimal("12.20"), 2))
        self.assertEqual(row["stock_mode"], "PUBLIC_V2")
        trace = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/")
        self.assertEqual(trace.status_code, 200, trace.data)
        self.assertEqual(Decimal(trace.data["data"][0]["actual_inbound_quantity"]), Decimal("12.20"))
        self.assertEqual(trace.data["data"][0]["unit"], "米")

    def test_rejected_material_is_not_credited_or_deducted_when_return_completes(self):
        receipt = self.receive()
        self.assertEqual(self.quality(receipt, returned=1).status_code, 200)
        self.finish_return()
        self.assertEqual(PublicStockBalance.objects.get().quantity, 1)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PurchaseReturn.objects.get().status, "COMPLETED")

    def test_all_rejected_has_no_stock_and_replenishment_creates_new_public_receipt(self):
        receipt = self.receive()
        self.assertEqual(self.quality(receipt, returned=2).status_code, 200)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertEqual(self.receive().status_code, 409)
        self.finish_return()
        replenished = self.receive()
        self.assertEqual(replenished.status_code, 201, replenished.data)
        self.assertEqual(self.quality(replenished).status_code, 200)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 2)

    def test_legacy_pending_receipt_is_blocked_without_mutation(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            receipt = self.receive()
        response = self.quality(receipt)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("PUBLIC_STOCK_LEGACY_DOCUMENT_BLOCKED", str(response.data))
        self.assertEqual(MaterialInbound.objects.get().status, "PENDING_QUALITY")
        self.assertFalse(MaterialStockMovement.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_public_pending_receipt_cannot_fall_back_to_legacy_when_disabled(self):
        receipt = self.receive()
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            response = self.quality(receipt)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("PUBLIC_STOCK_FLOW_DISABLED", str(response.data))
        self.assertEqual(MaterialInbound.objects.get().status, "PENDING_QUALITY")
        self.assertFalse(MaterialStockBalance.objects.exists())

    def test_tampered_frozen_identity_rolls_back_entire_quality_confirmation(self):
        receipt = self.receive()
        line = MaterialInboundLine.objects.get()
        snapshot = copy.deepcopy(line.calculation_snapshot)
        snapshot["public_stock_identity"]["identity_snapshot"]["raw_bar_length_m"] = "9.99"
        line.calculation_snapshot = snapshot
        line.save(update_fields=["calculation_snapshot"])
        response = self.quality(receipt, returned=1)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(MaterialInbound.objects.get().status, "PENDING_QUALITY")
        self.assertFalse(PurchaseReturn.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_missing_frozen_identity_is_not_guessed_from_current_bom(self):
        receipt = self.receive()
        line = MaterialInboundLine.objects.get()
        line.calculation_snapshot.pop("public_stock_identity")
        line.save(update_fields=["calculation_snapshot"])
        response = self.quality(receipt)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("PUBLIC_STOCK_IDENTITY_INCOMPLETE", str(response.data))
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_bom_changes_do_not_change_frozen_purchase_length(self):
        receipt = self.receive()
        self.bom_line.cutting_length_mm = 501
        self.bom_line.save(update_fields=["cutting_length_mm"])
        response = self.quality(receipt)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PublicStockBalance.objects.get().raw_bar_length_m, Decimal("3.05"))

    def test_manual_retry_and_direct_credit_retry_do_not_double_post(self):
        request_id = uuid.uuid4()
        first = self.manual(request_id=request_id)
        self.assertEqual(first.status_code, 201, first.data)
        retry = self.manual(request_id=request_id)
        self.assertEqual(retry.data["data"]["id"], first.data["data"]["id"])
        line = MaterialInboundLine.objects.get()
        credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            same = self.manual(request_id=request_id)
            self.assertEqual(same.status_code, 201, same.data)
            credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 3)
        self.assertEqual(self.manual(request_id=request_id, length="3.06").status_code, 409)

    def test_different_raw_lengths_remain_separate_with_exact_meter_total(self):
        self.assertEqual(self.manual(roots=2).status_code, 201)
        self.assertEqual(self.manual(roots=3, length="3.06").status_code, 201)
        self.assertEqual(PublicStockBalance.objects.count(), 2)
        summary = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        data = summary.data["data"]
        self.assertEqual(Decimal(data["current_quantity"]), 5)
        self.assertEqual(Decimal(data["meter_quantity"]), Decimal("15.28"))
        self.assertEqual(len(data["zones"]), 2)
        self.assertTrue(all(row["inbound_line_id"] is None for row in data["zones"]))

    def test_zero_quantity_public_raw_balance_is_hidden_from_inventory_list(self):
        self.assertEqual(self.manual(roots=1).status_code, 201)
        balance = PublicStockBalance.objects.get(stock_kind="RAW_PIPE")
        balance.quantity = 0
        balance.meter_quantity = 0
        balance.save(update_fields=["quantity", "meter_quantity", "updated_at"])

        response = self.client.get("/api/v1/material-inventory/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_opening_and_legacy_balance_are_not_counted_as_new_purchase(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            old_receipt = self.receive()
            self.assertEqual(self.quality(old_receipt).status_code, 200)
        old_balance = MaterialStockBalance.objects.get()
        identity = build_pipe_stock_identity(raw_material=self.raw_material, raw_bar_length_m="3.05", unit=self.raw_material.unit)
        credit_public_stock(identity=identity, zone=old_balance.zone, quantity=2, source_type="PUBLIC_STOCK_OPENING",
            source_id=old_balance.pk, source_line_id=old_balance.pk, actor_employee=self.employee)
        new_receipt = self.receive(2, remaining="6.1000")
        self.assertEqual(self.quality(new_receipt).status_code, 200)
        row = self.client.get("/api/v1/material-inventory/").data["results"][0]
        self.assertEqual(row["inventory_quantity"], 4)
        summary = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/summary/").data["data"]
        self.assertEqual(Decimal(summary["current_quantity"]), 4)
        self.assertEqual(Decimal(summary["cumulative_inbound_quantity"]), 4)

    def test_public_semi_uses_frozen_properties_and_does_not_expose_order_ownership(self):
        balance, craft = self.semi()
        self.bom_line.part_name = "修改后的部位"
        self.bom_line.specification = "99*99"
        self.bom_line.save(update_fields=["part_name", "specification"])
        response = self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI"})
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["results"][0]
        self.assertEqual(row["identity_key"], balance.identity_key)
        self.assertEqual(row["part_name"], "测试钢管")
        self.assertIn("切割 500mm", row["specification"])
        self.assertEqual(row["color"], "黑色")
        self.assertEqual(row["unit"], "支")
        self.assertEqual(row["completed_craft"], craft.name)
        self.assertEqual((row["completed_craft_code"], row["processing_status"], row["processing_status_label"]),
                         ("POWDER_COATING", "POWDER_COATING", "已喷塑"))
        self.assertEqual((row["tube_thickness"], row["cutting_length_mm"]), ("1", 500))
        self.assertEqual((row["material_number"], row["production_task_number"], row["product_name"]), ("", "", ""))
        self.assertNotIn("bom_line_id", row["identity_snapshot"])

    def test_public_semi_filter_and_receiving_options_keep_correct_warehouse_types(self):
        balance, _ = self.semi()
        filters = self.client.get("/api/v1/material-inventory/options/", {"scope": "filters"}).data["data"]
        self.assertEqual(filters["stock_mode"], "PUBLIC_V2")
        self.assertIn(str(balance.zone.warehouse_id), {str(row["id"]) for row in filters["warehouses"]})
        receiving = self.client.get("/api/v1/material-inventory/options/", {"scope": "receiving"}).data["data"]
        self.assertTrue(all(row["warehouse_type"] == "MATERIAL" for row in receiving["warehouses"]))
        response = self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI", "q": "测试钢管", "warehouse_id": str(balance.zone.warehouse_id)})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI", "processing_status": "POWDER_COATING"}).data["count"], 1)
        self.assertEqual(self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI", "processing_status": "METAL"}).data["count"], 0)
        self.assertEqual(self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI", "q": "修改后的部位"}).data["count"], 0)

    def test_zero_quantity_public_semi_balance_is_hidden_from_inventory_list(self):
        balance, _ = self.semi()
        balance.quantity = 0
        balance.save(update_fields=["quantity", "updated_at"])

        response = self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_public_semi_stock_blocks_disabling_warehouse_and_zone(self):
        balance, _ = self.semi()
        for path in (f"/api/v1/warehouses/{balance.zone.warehouse_id}/", f"/api/v1/warehouse-zones/{balance.zone_id}/"):
            etag = self.client.get(path)["ETag"]
            response = self.client.patch(path, {"status": "DISABLED"}, format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(response.status_code, 409, response.data)

    def test_ordinary_material_keeps_decimal_shared_balance(self):
        category = ProductCategory.objects.filter(item_type="MATERIAL", status="ACTIVE", archived_at__isnull=True).exclude(category_name="管材").first()
        material = RawMaterialInformation.objects.create(material_number="PUBFLOWOTHER", material_name="测试辅料",
            category=category, unit=self.product.unit, item_type="MATERIAL")
        payload = {"client_request_id": str(uuid.uuid4()), "inbound_date": timezone.localdate().isoformat(), "remark": "额外辅料",
                   "items": [{"raw_material_id": str(material.pk), "zone_id": self.zone_id, "received_quantity": "2.5000"}]}
        response = self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=material).quantity, Decimal("2.5"))
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertEqual(self.client.get("/api/v1/material-inventory/").data["count"], 1)

    def test_old_reconcile_apply_is_blocked_and_preview_does_not_repeat_public_receipt(self):
        self.assertEqual(self.manual().status_code, 201)
        with self.assertRaises(CommandError):
            call_command("reconcile_material_stock_ledger", apply=True, stdout=io.StringIO())
        output = io.StringIO()
        call_command("reconcile_material_stock_ledger", stdout=output)
        self.assertIn('"already_posted_count": 1', output.getvalue())
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_inventory_permission_is_still_required(self):
        self.semi()
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/v1/material-inventory/", {"stock_kind": "SEMI"}).status_code, 403)
