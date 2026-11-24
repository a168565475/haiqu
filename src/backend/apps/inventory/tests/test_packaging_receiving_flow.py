from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import MaterialSectionGrant
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseReturn
from apps.procurement.tests import test_packaging_purchase as purchase_fixture
from apps.reference_data.models import ProductCategory

from ..models import MaterialInbound, MaterialStockMovement, Warehouse, WarehouseZone
from . import test_inventory_api as inventory_fixture


INVENTORY = "/api/v1/material-inventory/"
RETURNS = "/api/v1/purchase-returns/"
PACKAGING = purchase_fixture.PACKAGING


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=False)
class PackagingReceivingFlowTests(ScopedActorMixin, APITestCase):
    make_task = purchase_fixture.PackagingPurchaseTests.make_task
    make_product_line = purchase_fixture.PackagingPurchaseTests.make_product_line
    make_bom = purchase_fixture.PackagingPurchaseTests.make_bom
    grant_packaging = purchase_fixture.PackagingPurchaseTests.grant_packaging
    prepare = purchase_fixture.PackagingPurchaseTests.prepare
    confirm_quality = inventory_fixture.MaterialInventoryApiTests.confirm_quality

    def setUp(self):
        purchase_fixture.PackagingPurchaseTests.setUp(self)
        self.grant_packaging()
        category, _ = ProductCategory.objects.get_or_create(item_type="MATERIAL", category_name="包材")
        self.inventory_material.category = category
        self.inventory_material.save(update_fields=["category"])
        warehouse = Warehouse.objects.create(warehouse_number="PACKAGING-QA-WH", warehouse_name="包材验收仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="包材区")
        groups = self.prepare()
        fields = {"group_ids": [group["id"] for group in groups], "batch_session_id": str(uuid4())}
        current = self.client.get(PACKAGING + "batch-page/", fields)
        self.assertEqual(current.status_code, 200, current.data)
        delivery = (timezone.localdate() + timedelta(days=10)).isoformat()
        batch = {"batch_type": "NORMAL", "request_id": str(uuid4()), "currency_id": str(self.cny.pk), "lines": [
            {"purchase_group_line_id": row["progress"]["lines"][0]["id"], "actual_purchase_quantity": quantity,
             "unit_price": "2", "supplier_id": str(self.supplier.pk), "delivery_date": delivery}
            for row, quantity in zip(groups, ["500", "800"])
        ]}
        result = self.client.post(PACKAGING + "confirm-page/", {**fields, "batch": batch}, format="json",
                                  HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(result.status_code, 200, result.data)
        self.first, self.second = PurchaseOrder.objects.order_by("production_task_number_snapshot")

    def section_rows(self):
        response = self.client.get(INVENTORY + "procurement-inbound-orders/")
        self.assertEqual(response.status_code, 200, response.data)
        return {str(row["id"]): row for row in response.data["data"]}

    def test_confirmed_packages_receive_quality_and_return_by_original_task(self):
        self.scoped_actor()
        grant = self.grant("inventory.receive_material", "MATERIAL")
        material_scope = MaterialSectionGrant.objects.create(grant=grant, sections=["HARDWARE"])
        first_line, second_line = self.first.lines.get(), self.second.lines.get()
        body = {"material_section": "D", "items": [{
            "purchase_order_line_id": str(first_line.pk), "zone_id": str(self.zone.pk),
            "received_quantity": "240", "expected_remaining_quantity": "500",
        }]}
        self.assertEqual(self.section_rows(), {})
        response = self.client.post(INVENTORY + "receivings/", body, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        material_scope.sections = ["PACKAGING"]
        material_scope.save(update_fields=["sections"])
        rows = self.section_rows()
        self.assertEqual(rows[str(self.first.pk)]["receiving_sections"], [{"id": "D", "name": "包材"}])
        self.assertEqual(rows[str(self.first.pk)]["workflow_status"], "PENDING_RECEIPT")
        self.assertEqual(self.first.status, "SUBMITTED")
        eligible = self.client.get(INVENTORY + "eligible-lines/", {"purchase_order_id": self.first.pk, "material_section": "D"})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(str(eligible.data["data"][0]["id"]), str(first_line.pk))
        received = self.client.post(INVENTORY + "receivings/", body, format="json")
        self.assertEqual(received.status_code, 201, received.data)
        inbound = MaterialInbound.objects.get(pk=received.data["data"]["id"])
        self.assertEqual(inbound.material_section, "D")
        self.assertEqual(inbound.purchase_order_id, self.first.pk)
        replay = self.client.post(INVENTORY + "receivings/", body, format="json")
        self.assertEqual(replay.status_code, 409, replay.data)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertFalse(inbound.purchase_payables.exists())
        self.assertFalse(MaterialStockMovement.objects.exists())
        rows = self.section_rows()
        self.assertEqual(rows[str(self.first.pk)]["pending_quality_count"], 1)
        self.assertEqual(rows[str(self.second.pk)]["pending_quality_count"], 0)
        self.assertEqual(rows[str(self.second.pk)]["received_quantity"], "0.0000")

        quality = get_user_model().objects.create_user("packaging-quality")
        self.scope_user = quality
        self.scope_employee = Employee.objects.create(user=quality, employee_code="QA-PACKAGING-QUALITY", display_name="包材品质验收")
        self.grant("inventory.quality_confirm_material")
        record = self.client.get(INVENTORY + f"purchase-receipt-records/{inbound.pk}/")
        self.assertEqual(record.status_code, 200, record.data)
        self.assertEqual(record.data["data"]["material_section_display"], "包材")
        confirmed = self.confirm_quality(received, return_quantity="40")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        repeat_quality = self.confirm_quality(received, return_quantity="40")
        self.assertEqual(repeat_quality.status_code, 409, repeat_quality.data)
        line = inbound.lines.get()
        self.assertEqual((line.accepted_quantity, line.return_quantity), (Decimal("200"), Decimal("40")))
        self.assertEqual(MaterialStockMovement.objects.get(source_line_id=line.pk).quantity, Decimal("200"))
        payable = inbound.purchase_payables.get().lines.get()
        self.assertEqual(payable.accepted_quantity, Decimal("200"))
        self.assertFalse(MaterialInbound.objects.filter(lines__purchase_order_line=second_line).exists())
        returned = PurchaseReturn.objects.get(inbound=inbound)
        self.assertEqual(returned.purchase_order_id, self.first.pk)
        self.assertEqual(returned.lines.get().quantity, Decimal("40"))

        self.client.force_authenticate(self.user)
        for order, total in ((self.first, 1), (self.second, 0)):
            result = self.client.get(RETURNS, {"purchase_scope": "PACKAGING", "q": order.production_task_number_snapshot})
            self.assertEqual(result.status_code, 200, result.data)
            self.assertEqual(result.data["meta"]["total"], total)
        detail = self.client.get(RETURNS + f"{returned.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["purchase_scope"], "PACKAGING")
        for operation in ("confirm", "complete"):
            detail = self.client.post(RETURNS + f"{returned.pk}/{operation}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["status"], "COMPLETED")

    def test_full_packaging_delivery_reports_returns_separately(self):
        self.scoped_actor()
        self.grant("inventory.receive_material")
        self.grant("inventory.quality_confirm_material")
        line = self.first.lines.get()
        received = self.client.post(INVENTORY + "receivings/", {
            "material_section": "D", "items": [{
                "purchase_order_line_id": str(line.pk), "zone_id": str(self.zone.pk),
                "received_quantity": "500", "expected_remaining_quantity": "500",
            }],
        }, format="json")
        self.assertEqual(received.status_code, 201, received.data)
        inspected = self.confirm_quality(received, return_quantity="40")
        self.assertEqual(inspected.status_code, 200, inspected.data)

        self.client.force_authenticate(self.user)
        tracking = self.client.get("/api/v1/purchase-tracking/arrivals/", {
            "purchase_scope": "PACKAGING", "production_task_id": self.first.production_task_id,
        })
        self.assertEqual(tracking.status_code, 200, tracking.data)
        [row] = tracking.data["data"]
        self.assertEqual(Decimal(row["received_quantity"]), Decimal("500"))
        self.assertEqual(Decimal(row["return_quantity"]), Decimal("40"))
        self.assertEqual(Decimal(row["unreceived_quantity"]), Decimal("0"))
