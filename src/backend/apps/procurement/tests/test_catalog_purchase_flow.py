from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.material_flow_calculations import pipe_plan
from apps.boms.models import BomSectionType
from apps.inventory.models import PublicStockBalance, MaterialInboundLine, Warehouse, WarehouseZone
from apps.material_catalog.models import MaterialCatalog
from apps.reference_data.models import ProductionUnit
from ..models import PurchaseOrder, PurchaseReturnLine, SupplierPurchaseSheet
from . import test_purchase_order_api as order_tests
from . import test_purchase_groups as group_tests


class CatalogPurchaseFlowTests(APITestCase):
    make_task = order_tests.PurchaseOrderApiTests.make_task
    make_product_line = order_tests.PurchaseOrderApiTests.make_product_line
    make_bom = order_tests.PurchaseOrderApiTests.make_bom
    get_source = order_tests.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(order_tests.PurchaseOrderApiTests.create_payload)
    receive = group_tests.PurchaseGroupApiTests.receive
    detail = group_tests.PurchaseGroupApiTests.detail
    batch_payload = group_tests.PurchaseGroupApiTests.batch_payload

    def setUp(self):
        order_tests.PurchaseOrderApiTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["inventory", "production_tasks"]))
        self.task = self.make_task("CATALOG")
        self.product_line = self.make_product_line(self.task)
        self.bom, self.bom_line = self.make_bom(self.product_line, section_type=BomSectionType.PROFILE)
        self.root, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "PURCHASEROOT"})
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="采购新管材")
        self.saved = {"schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name, "scope": "BASE", "processing_state": "RAW",
            "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1"},
            "unit_id": str(self.root.pk), "unit_name": "根", "display_name": "采购新管材 / 根"}
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=10)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.raw_values = {"pipe_plan_version": 3}
        self.bom_line.material_catalog = self.catalog
        self.bom_line.material_selection_snapshot = self.saved
        self.bom_line.material_quantity = None
        self.bom_line.unit = "根"
        self.bom_line.save()
        warehouse = Warehouse.objects.create(warehouse_number="CATALOG-PUR-WH", warehouse_name="新原料仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="原料区")

    def create(self, quantity=None, bars=4):
        source = self.get_source(self.task)
        self.assertEqual(source.status_code, 200, source.data)
        data = source.data["data"]
        expected = Decimal(self.bom_line.suggested_purchase_meters)
        self.assertEqual(Decimal(data["lines"][0]["required_quantity"]), expected)
        payload = self.create_payload(self.task, data, supplier_id=str(self.supplier.pk), delivery_date=str(timezone.localdate()),
            actual_purchase_quantity=quantity, actual_bar_count=bars, unit_price="2")
        payload["currency_id"] = str(self.cny.pk)
        response = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        identifier = response.data["data"]["id"]
        confirmed = self.client.post(f"/api/v1/purchase-orders/{identifier}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return confirmed.data["data"]

    def test_ordinary_pipe_receiving_quality_return_and_print_preserve_root_meter_flow(self):
        batch = self.create()
        purchase = PurchaseOrder.objects.get(pk=batch["id"]).lines.get()
        self.assertEqual(purchase.source_unit_text, "米")
        self.assertEqual(purchase.actual_purchase_quantity, Decimal("12.20"))
        self.assertEqual(purchase.actual_purchase_meters, Decimal("12.20"))
        self.assertEqual(purchase.amount, Decimal("24.40"))
        self.catalog.name = "目录改名不回填采购"
        self.catalog.save()
        self.receive(batch, "12.20", returned="3.05", bar_count=4, return_bar_count=1)
        line = MaterialInboundLine.objects.get()
        self.assertEqual(line.material_selection_snapshot, self.saved)
        self.assertIsNone(line.raw_material_information_id)
        self.assertEqual(line.measurement_kind, "PIPE")
        self.assertEqual(line.accepted_quantity, Decimal("9.15"))
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.raw_bar_length_m), (3, Decimal("9.15"), Decimal("3.05")))
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal("3.05"))
        from ..selectors import purchase_return_amount
        self.assertEqual(purchase_return_amount(PurchaseReturnLine.objects.get().return_order), "6.1000")
        self.assertEqual((line.received_bar_count, line.return_bar_count, line.accepted_bar_count), (4, 1, 3))
        detail = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/details/").data["data"]["lines"][0]
        self.assertEqual((detail["received_bar_count"], detail["return_bar_count"], detail["accepted_bar_count"]), (4, 1, 3))
        printed = SupplierPurchaseSheet.objects.get().content_snapshot["lines"][0]
        self.assertEqual(Decimal(printed["quantity"]), Decimal("12.20"))
        self.assertEqual(printed["unit"], "米")
        self.assertNotIn("material_quantity", printed)
        self.assertEqual(printed["material_selection_snapshot"], self.saved)
        trace = self.client.get(f"/api/v1/material-inventory/{self.catalog.pk}/order-purchases/", {"identity_key": balance.identity_key})
        self.assertEqual(trace.status_code, 200, trace.data)
        self.assertEqual(len(trace.data["data"]), 1)
        self.assertEqual(trace.data["data"][0]["unit"], "米")
        self.assertEqual(Decimal(trace.data["data"][0]["actual_inbound_quantity"]), Decimal("9.15"))

    def test_group_batch_progress_keeps_original_meter_quantity(self):
        source = self.get_source(self.task).data["data"]
        created = self.client.post("/api/v1/purchase-groups/", {"production_task_id": str(self.task.pk), "bom_id": str(self.bom.pk),
            "source_revision": source["source_revision"]}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.group_id = created.data["data"]["id"]
        self.line_id = created.data["data"]["progress"]["lines"][0]["id"]
        payload = self.batch_payload("12.20")
        payload["lines"][0]["actual_bar_count"] = 4
        response = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data["data"]
        purchase = PurchaseOrder.objects.get(pk=batch["id"]).lines.get()
        self.assertEqual(purchase.material_selection_snapshot, self.saved)
        self.assertEqual(purchase.actual_purchase_quantity, Decimal("12.20"))
        self.assertEqual(purchase.amount, Decimal("24.40"))
        confirmed = self.client.post(f"/api/v1/purchase-orders/{batch['id']}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.receive(confirmed.data["data"], "12.20", bar_count=4, return_bar_count=0)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 4)
        progress = self.detail().data["data"]["progress"]["lines"][0]
        self.assertEqual(Decimal(progress["accepted_quantity"]), Decimal("12.20"))
        self.assertEqual(progress["progress_percent"], "100.0000")

    def test_historical_pipe_attribute_length_is_preserved(self):
        self.saved["attributes"]["length"] = "旧选料原长 3050 mm"
        self.bom_line.material_selection_snapshot = self.saved
        self.bom_line.save(update_fields=["material_selection_snapshot"])
        batch = self.create()
        self.receive(batch, "12.20", bar_count=4, return_bar_count=0)
        self.assertEqual(PurchaseOrder.objects.get(pk=batch["id"]).lines.get().material_selection_snapshot, self.saved)
        self.assertEqual(MaterialInboundLine.objects.get().material_selection_snapshot, self.saved)
        self.assertEqual(PublicStockBalance.objects.get().raw_bar_length_m, Decimal("3.05"))
        self.bom_line.refresh_from_db()
        self.assertEqual(self.bom_line.material_selection_snapshot, self.saved)

    def test_missing_excess_and_wrong_length_receipts_do_not_create_rows(self):
        batch = self.create()
        self.receive(batch, "3.05", bar_count=1, confirm=False)
        row = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": batch["id"]}).data["data"][0]
        self.assertEqual(row["remaining_bar_count"], 3)
        original_count = MaterialInboundLine.objects.count()
        for extra in [{}, {"received_bar_count": 4}, {"received_bar_count": "1.5"}, {"received_bar_count": 1, "raw_bar_length_m": "6"}]:
            response = self.client.post("/api/v1/material-inventory/receivings/", {"items": [{
                "purchase_order_line_id": row["id"], "zone_id": str(self.zone.pk),
                "expected_remaining_quantity": row["remaining_quantity"], **extra}]}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(MaterialInboundLine.objects.count(), original_count)

    def test_invalid_return_roots_roll_back_and_original_return_states_complete(self):
        batch = self.create()
        receipt = self.receive(batch, "12.20", bar_count=4, confirm=False).data["data"]
        row = receipt["lines"][0]
        url = f"/api/v1/material-inventory/quality-batches/{receipt['id']}/confirm/"
        for extra in [{}, {"return_bar_count": 5}, {"return_bar_count": "1.5"}]:
            response = self.client.post(url, {"items": [{"line_id": row["id"], "expected_received_quantity": "12.20", **extra}]}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(PublicStockBalance.objects.exists())
            self.assertFalse(PurchaseReturnLine.objects.exists())
        response = self.client.post(url, {"items": [{"line_id": row["id"], "expected_received_quantity": "12.20",
            "return_bar_count": 1}]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        record = PurchaseReturnLine.objects.get().return_order
        for action in ["confirm", "complete"]:
            detail = self.client.get(f"/api/v1/purchase-returns/{record.pk}/")
            self.assertEqual(detail.data["data"]["return_amount"], "6.1000")
            advanced = self.client.post(f"/api/v1/purchase-returns/{record.pk}/{action}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(advanced.status_code, 200, advanced.data)
        remaining = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": batch["id"]}).data["data"][0]
        self.assertEqual((remaining["remaining_bar_count"], Decimal(remaining["remaining_quantity"])), (1, Decimal("3.05")))
