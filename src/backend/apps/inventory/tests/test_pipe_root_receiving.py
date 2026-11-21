from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.finance.purchase_payable_models import PurchasePayableLine
from apps.finance.purchase_payable_serializers import PurchasePayableLineSerializer
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.models import MaterialInbound, MaterialInboundLine, PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_services import credit_public_stock, debit_public_stock
from apps.material_catalog.models import MaterialCatalog
from apps.procurement.models import PurchaseReturnLine
from apps.reference_data.models import ProductionUnit
from . import test_inbound_loading as fixtures


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PipeRootReceivingTests(APITestCase):
    make_order = fixtures.InboundLoadingTests.make_order

    def setUp(self):
        fixtures.InboundLoadingTests.setUp(self)
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "ROOT"})
        catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="收货测试管")
        line = self.line
        line.material_catalog = catalog
        line.material_selection_snapshot = {"schema_version": 1, "catalog_id": str(catalog.pk),
            "catalog_version": catalog.updated_at.isoformat(), "category_key": "TUBE", "template_key": "TUBE",
            "name": catalog.name, "scope": "BASE", "processing_state": "RAW", "processing_stage": "RAW",
            "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1"},
            "unit_id": str(unit.pk), "unit_name": "根", "display_name": catalog.name}
        line.source_unit_text = "KG"
        line.suggested_bar_count = line.actual_bar_count = 5
        line.raw_bar_length_m = Decimal("6")
        line.suggested_purchase_meters = line.actual_purchase_meters = 30
        line.raw_bar_weight_kg = Decimal("2.4000")
        line.suggested_purchase_weight_kg = line.actual_purchase_weight_kg = line.actual_purchase_quantity = 12
        line.calculation_snapshot = {"measurement_unit": "kg", "raw_bar_weight_kg": "2.4"}
        line.save()

    def receive(self, roots, remaining, **extra):
        return self.client.post(self.root + "receipts/", {"items": [{"purchase_order_line_id": str(self.line.pk),
            "zone_id": str(self.zone.pk), "received_bar_count": roots, "expected_remaining_quantity": remaining,
            **extra}]}, format="json", HTTP_HOST="localhost")

    def inspect(self, receipt, returned):
        self.assertEqual(receipt.status_code, 201, receipt.data)
        batch = receipt.data["data"]
        line = batch["lines"][0]
        response = self.client.post(self.root + f"quality-batches/{batch['id']}/confirm/", {"items": [{
            "line_id": line["id"], "expected_received_quantity": line["received_bar_count"],
            "return_bar_count": returned, "quality_remark": "核对根数",
        }]}, format="json", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return MaterialInboundLine.objects.get(pk=line["id"])

    def test_partial_receipts_stock_roots_but_price_order_kilograms(self):
        # 本批订单12公斤折算5根，每根结算2.4公斤，与标准管重不同。
        self.line.raw_bar_weight_kg = Decimal("2.5152")
        self.line.suggested_purchase_weight_kg = Decimal("12.5760")
        self.line.calculation_snapshot = {**self.line.calculation_snapshot, "raw_bar_weight_kg": "2.5152"}
        self.line.save(update_fields=["raw_bar_weight_kg", "suggested_purchase_weight_kg", "calculation_snapshot"])
        self.assertEqual(self.receive(6, 5).status_code, 400)
        self.assertEqual(self.receive(4, 5, received_weight_kg="10").status_code, 400)
        first = self.receive(4, 5)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["data"]["total_received_quantity"], "4.0000")
        self.assertIsNone(first.data["data"]["total_received_weight_kg"])
        self.assertEqual(self.receive(2, 1).status_code, 400)
        line = self.inspect(first, 0)
        self.assertEqual((line.accepted_bar_count, line.accepted_quantity, line.accepted_weight_kg), (4, 24, None))
        payable = PurchasePayableLine.objects.get(material_inbound_line=line)
        self.assertEqual(payable.accepted_quantity, Decimal("9.6"))
        data = PurchasePayableLineSerializer(payable).data
        self.assertEqual(Decimal(data["settlement_quantity"]), Decimal("9.6"))
        self.assertEqual(data["receipt_bar_counts"], {"received": 4, "returned": 0})
        self.user.user_permissions.add(*Permission.objects.filter(
            codename__in=["view_purchasepayable", "change_purchasepayable"]))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        url = f"/api/v1/finance/purchase-payables/{payable.payable_id}/"
        detail = self.client.get(url, HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200, detail.data)
        pricing = self.client.patch(url + "pricing/", {"lines": [{
            "id": str(payable.pk), "unit_price": "3", "price_unit": "KG"}]}, format="json",
            HTTP_HOST="localhost", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(pricing.status_code, 200, pricing.data)
        self.assertEqual(Decimal(pricing.data["data"]["amount"]), Decimal("28.80"))
        balance = PublicStockBalance.objects.get()
        trace = self.client.get(self.root + f"{self.line.material_catalog_id}/order-purchases/",
                                {"identity_key": balance.identity_key}, HTTP_HOST="localhost")
        self.assertEqual(trace.status_code, 200, trace.data)
        self.assertEqual(trace.data["data"][0]["bar_counts"], {"ordered": 5, "accepted": 4, "pending": 1})
        last = self.inspect(self.receive(1, 1), 0)
        self.assertEqual(PurchasePayableLine.objects.get(material_inbound_line=last).accepted_quantity, Decimal("2.4"))
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (5, 30, None))
        self.assertEqual(PublicStockMovement.objects.filter(weight_quantity__isnull=True).count(), 2)

    def test_quality_return_counts_only_accepted_roots(self):
        line = self.inspect(self.receive(5, 5), 1)
        returned = PurchaseReturnLine.objects.get(inbound_line=line)
        self.assertEqual(returned.quantity, 1)
        self.assertEqual(PurchasePayableLine.objects.get(material_inbound_line=line).accepted_quantity, Decimal("9.6"))
        self.assertIsNone(line.return_weight_kg)
        self.assertEqual(self.receive(1, 1).status_code, 409)
        self.user.user_permissions.add(*Permission.objects.filter(
            codename__in=["confirm_purchasereturn", "complete_purchasereturn", "submit_purchaseorder", "view_productiontask"]))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        url = f"/api/v1/purchase-returns/{returned.return_order_id}/"
        for step in ("confirm", "complete"):
            detail = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(detail.status_code, 200, detail.data)
            response = self.client.post(url + step + "/", {}, format="json", HTTP_HOST="localhost", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(response.status_code, 200, response.data)
        replacement = self.inspect(self.receive(1, 1), 0)
        self.assertEqual(PurchasePayableLine.objects.get(material_inbound_line=replacement).accepted_quantity, Decimal("2.4"))

    def test_rounding_is_allocated_over_all_partial_deliveries(self):
        self.line.raw_bar_weight_kg = Decimal("3.5")
        self.line.suggested_purchase_weight_kg = Decimal("17.5")
        self.line.calculation_snapshot["raw_bar_weight_kg"] = "3.5"
        self.line.actual_purchase_quantity = self.line.actual_purchase_weight_kg = Decimal("10")
        self.line.actual_bar_count, self.line.actual_purchase_meters = 3, 18
        self.line.save()
        settled = []
        for remaining in (3, 2, 1):
            line = self.inspect(self.receive(1, remaining), 0)
            settled.append(PurchasePayableLine.objects.get(material_inbound_line=line).accepted_quantity)
        self.assertEqual(settled, [Decimal("3.3333"), Decimal("3.3334"), Decimal("3.3333")])

    def test_existing_weighed_delivery_keeps_kilogram_limit_for_its_purchase_line(self):
        batch = MaterialInbound.objects.create(inbound_number="OLD-PIPE-KG", purchase_order=self.order,
            status="PENDING_QUALITY", received_by_employee=self.employee)
        MaterialInboundLine.objects.create(inbound=batch, purchase_order_line=self.line, zone=self.zone,
            material_catalog=self.line.material_catalog, material_selection_snapshot=self.line.material_selection_snapshot,
            measurement_kind="PIPE", raw_bar_length_m=6, bar_weight_kg=Decimal("2.4"),
            received_bar_count=1, accepted_bar_count=1, return_bar_count=0, received_weight_kg=Decimal("2.5"),
            accepted_weight_kg=Decimal("2.5"), return_weight_kg=0, received_quantity=6, accepted_quantity=6,
            return_quantity=0, source_unit_text_snapshot="KG", purchased_quantity_snapshot=12)
        result = self.client.post(self.root + "receipts/", {"items": [{"purchase_order_line_id": str(self.line.pk),
            "zone_id": str(self.zone.pk), "expected_remaining_quantity": "9.5", "received_weight_kg": "4"}]},
            format="json", HTTP_HOST="localhost")
        self.assertEqual(result.status_code, 201, result.data)
        latest = MaterialInboundLine.objects.get(inbound_id=result.data["data"]["id"])
        self.assertEqual((latest.received_bar_count, latest.received_weight_kg), (1, 4))
        self.assertNotIn("receipt_quantity_mode", latest.calculation_snapshot)

    def test_counted_receipt_can_share_existing_weighed_stock(self):
        identity = build_catalog_stock_identity(material_catalog_id=self.line.material_catalog_id,
            material_selection_snapshot=self.line.material_selection_snapshot, raw_bar_length_m=self.line.raw_bar_length_m)
        def weighed_receipt(roots, weight):
            return credit_public_stock(identity=identity, zone=self.zone, quantity=roots,
                weight_quantity=Decimal(weight), source_type="MATERIAL_INBOUND",
                source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
        original = weighed_receipt(2, "5.1000")
        self.inspect(self.receive(4, 5), 0)
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (6, 36, None))
        movement = PublicStockMovement.objects.get(snapshot__receipt_quantity_mode="ROOTS")
        self.assertEqual((movement.before_weight_quantity, movement.after_weight_quantity), (Decimal("5.1"), None))
        self.assertEqual(original.weight_quantity, Decimal("5.1"))
        weighed = weighed_receipt(1, "2.7")
        self.assertEqual((weighed.weight_quantity, weighed.after_weight_quantity), (Decimal("2.7"), None))
        issued = debit_public_stock(balance_id=balance.pk, quantity=3, source_type="MATERIAL_ISSUE",
            source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
        self.assertEqual((issued.after_quantity, issued.after_meter_quantity), (4, 24))
