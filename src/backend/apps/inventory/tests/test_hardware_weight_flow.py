"""五金件数/公斤数完整业务回归；仅由隔离 PostgreSQL 测试运行器执行。"""
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import BomLine
from apps.boms.services import create_bom
from apps.boms.tests import test_hardware_weight_api as hardware_fixture
from apps.boms.tests import test_material_flow_bom as bom_fixture
from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.models import MaterialIssue
from apps.organizations.models import Employee
from apps.finance.purchase_payable_models import PurchasePayable, PurchasePayableLine
from apps.finance.purchase_payable_services import create_payables_for_inbound
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseReturnLine, SupplierPurchaseSheet
from apps.procurement.selectors import purchase_return_amount
from apps.procurement.tests import test_purchase_order_api as purchase_fixture
from apps.production_scheduling.services import create_schedule
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_config.tests.factories import production_employee
from apps.inventory.models import (
    MaterialInboundLine, MaterialStockBalance, MaterialStockMovement,
    PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone,
)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class HardwareWeightFlowTests(APITestCase):
    make_task = purchase_fixture.PurchaseOrderApiTests.make_task
    make_product_line = purchase_fixture.PurchaseOrderApiTests.make_product_line
    get_source = purchase_fixture.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(purchase_fixture.PurchaseOrderApiTests.create_payload)
    get = bom_fixture.MaterialFlowBomTests.get
    save = bom_fixture.MaterialFlowBomTests.save
    verify = bom_fixture.MaterialFlowBomTests.verify
    payload = hardware_fixture.HardwareWeightApiTests.payload
    rivet_input = hardware_fixture.HardwareWeightApiTests.rivet_input
    washer_input = hardware_fixture.HardwareWeightApiTests.washer_input
    save_hardware = hardware_fixture.HardwareWeightApiTests.save_hardware

    def setUp(self):
        purchase_fixture.PurchaseOrderApiTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=[
            "boms", "material_catalog", "inventory", "material_issues", "production_tasks", "production_scheduling",
        ]))
        self.reviewer_user = get_user_model().objects.create_user(username="hardware_weight_reviewer")
        self.reviewer = Employee.objects.create(user=self.reviewer_user, employee_code="HW_WEIGHT_REVIEWER",
            display_name="五金重量验收仓库审核员")
        self.reviewer_user.user_permissions.set(Permission.objects.filter(content_type__app_label="material_issues"))
        self.reviewer_client = APIClient()
        self.reviewer_client.force_authenticate(self.reviewer_user)
        self.supplier.supplier_categories = ["HARDWARE"]
        self.supplier.save(update_fields=["supplier_categories"])
        self.task = self.make_task("HARDWARE-WEIGHT")
        self.task.followers.add(self.reviewer)
        self.product_line = self.make_product_line(self.task, quantity=1000)
        self.bom = create_bom(product_line=self.product_line, creation_method="BLANK", actor_employee=self.employee)
        self.catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="重量验收铆钉")
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "HW-FLOW-PIECE"})
        warehouse = Warehouse.objects.create(warehouse_number="HW-FLOW-WH", warehouse_name="五金重量验收仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="五金区")

    def prepare_bom(self, *, washer, catalog, native_kg=False):
        kind = "PLAIN_WASHER" if washer else "RIVET_GB873_STEEL"
        specification, size = ("M6", "12×6.4×1.6") if washer else ("Φ4-40", "4×40")
        self.expected_unit_weight = Decimal("0.00101645" if washer else "0.00396000")
        if native_kg:
            self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name="KG", defaults={"unit_code": "HW-FLOW-KG"})
        elif washer:
            self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name="片", defaults={"unit_code": "HW-FLOW-WASHER"})
        self.catalog.name = "重量验收垫片" if washer else "重量验收铆钉"
        self.catalog.save(update_fields=["name"])
        payload = self.payload(material="65Mn", specification=specification, size=size,
            unit_consumption="1", weight_input={"kind": kind, "material": "65Mn", "specification": specification})
        if not catalog:
            category, _ = ProductCategory.objects.get_or_create(item_type="MATERIAL", category_name="五金")
            self.raw_material = RawMaterialInformation.objects.create(material_number="HW-FLOW-RAW",
                material_name=self.catalog.name, category=category, item_type="MATERIAL", material="65Mn",
                specification=specification, unit=self.piece_unit)
            payload.pop("material_catalog_id")
            payload.pop("material_selection")
            payload["source_inventory_material_id"] = str(self.raw_material.pk)
        saved = self.save_hardware(payload)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.bom_line = BomLine.objects.get(section__bom=self.bom, section__title="五金件")
        self.assertEqual(Decimal(self.bom_line.raw_values["unit_material_weight_kg"]), self.expected_unit_weight)
        self.assertEqual(self.bom_line.unit, self.piece_unit.unit_name)
        verified = self.verify()
        self.assertEqual(verified.status_code, 200, verified.data)
        self.bom_line.refresh_from_db()
        self.bom_values_before_purchase = deepcopy(self.bom_line.raw_values)

    def create_purchase_and_sheet(self):
        source = self.get_source(self.task)
        self.assertEqual(source.status_code, 200, source.data)
        data = source.data["data"]
        self.assertTrue(data["can_create"], data)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["source_unit_text"], "KG")
        expected_quantity = (Decimal("1000") if self.piece_unit.unit_name == "KG" else
            (self.expected_unit_weight * 1000).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        self.assertEqual(Decimal(data["lines"][0]["required_quantity"]), expected_quantity)
        payload = self.create_payload(self.task, data, supplier_id=str(self.supplier.pk),
            delivery_date=str(timezone.localdate()), actual_purchase_quantity="4", unit_price="2")
        payload["currency_id"] = str(self.cny.pk)
        created = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.order_id = created.data["data"]["id"]
        self.purchase_line_id = created.data["data"]["lines"][0]["id"]
        order_url = f"/api/v1/purchase-orders/{self.order_id}/"
        update = {"lines": [{"id": self.purchase_line_id, "supplier_id": str(self.supplier.pk),
            "delivery_date": str(timezone.localdate()), "actual_purchase_quantity": "5", "unit_price": "2"}]}
        stale = self.client.patch(order_url, update, format="json", HTTP_IF_MATCH='"stale"')
        self.assertEqual(stale.status_code, 412, stale.data)
        edited = self.client.patch(order_url, update, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(Decimal(edited.data["data"]["lines"][0]["amount"]), Decimal("10"))
        confirmed = self.client.post(order_url + "confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        options = self.client.get(order_url + "sheet-options/")
        self.assertEqual(options.status_code, 200, options.data)
        generated = self.client.post(order_url + "generate-sheets/", {"assignments": [{
            "supplier_id": str(self.supplier.pk), "template_version_id": options.data["data"]["templates"][0]["version_id"],
        }]}, format="json")
        self.assertEqual(generated.status_code, 201, generated.data)
        self.sheet_id = generated.data["data"][0]["id"]
        sheet_url = f"/api/v1/supplier-purchase-sheets/{self.sheet_id}/"
        detail = self.client.get(sheet_url)
        self.assertEqual(detail.status_code, 200, detail.data)
        original = deepcopy(detail.data["data"]["content_snapshot"])
        row = original["lines"][0]
        self.assertEqual(row["unit"].upper(), "KG")
        self.assertEqual((Decimal(row["quantity"]), Decimal(row["unit_price"]), Decimal(row["amount"])),
                         (Decimal("5"), Decimal("2"), Decimal("10")))
        for field, bad in (("quantity", "100"), ("unit", "个"), ("unit_price", "99")):
            tampered = deepcopy(original)
            tampered["lines"][0][field] = bad
            tampered["lines"][0].pop("measurement_kind", None)
            tampered["lines"][0].pop("calculation_snapshot", None)
            rejected = self.client.patch(sheet_url, {"content": tampered}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertEqual(SupplierPurchaseSheet.objects.get(pk=self.sheet_id).content_snapshot, original)
        published = self.client.post(sheet_url + "publish/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(published.status_code, 200, published.data)
        self.bom_line.refresh_from_db()
        self.assertEqual(self.bom_line.raw_values, self.bom_values_before_purchase)

    def receive_and_inspect(self, *, catalog, forged_counts=False):
        native_kg = self.piece_unit.unit_name == "KG"
        eligible = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": self.order_id})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        row = eligible.data["data"][0]
        item = {"purchase_order_line_id": self.purchase_line_id, "zone_id": str(self.zone.pk),
            "expected_remaining_quantity": row["remaining_quantity"], "received_weight_kg": "4.5"}
        if forged_counts:
            item["received_piece_count"] = 999999
        receipt = self.client.post("/api/v1/material-inventory/receipts/", {"items": [item]}, format="json")
        self.assertEqual(receipt.status_code, 201, receipt.data)
        inbound = MaterialInboundLine.objects.get()
        received_quantity = (Decimal("4.5") if native_kg else
            (Decimal("4.5") / self.expected_unit_weight).to_integral_value(rounding=ROUND_FLOOR))
        self.assertEqual((inbound.received_quantity, inbound.received_weight_kg), (received_quantity, Decimal("4.5")))
        if native_kg:
            self.assertIsNone(receipt.data["data"]["lines"][0]["received_piece_count"])
        else:
            self.assertEqual(Decimal(str(receipt.data["data"]["lines"][0]["received_piece_count"])), received_quantity)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(MaterialStockBalance.objects.exists())
        quality_url = f"/api/v1/material-inventory/quality-batches/{receipt.data['data']['id']}/confirm/"
        quality_item = {"line_id": str(inbound.pk), "expected_received_quantity": "4.5",
            "return_weight_kg": "0.6", "quality_remark": "按冻结单重向下折算参考件数"}
        if forged_counts:
            quality_item["return_piece_count"] = 999999
        invalid_item = {**quality_item, "return_weight_kg": "4.6"}
        invalid = self.client.post(quality_url, {"items": [invalid_item]}, format="json")
        self.assertEqual(invalid.status_code, 400, invalid.data)
        confirmed = self.client.post(quality_url, {"items": [quality_item]}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        inbound.refresh_from_db()
        accepted_quantity = (Decimal("3.9") if native_kg else
            (Decimal("3.9") / self.expected_unit_weight).to_integral_value(rounding=ROUND_FLOOR))
        self.accepted_quantity = accepted_quantity
        self.assertEqual((inbound.accepted_quantity, inbound.accepted_weight_kg), (accepted_quantity, Decimal("3.9")))
        self.assertEqual((inbound.return_quantity, inbound.return_weight_kg),
                         (received_quantity - accepted_quantity, Decimal("0.6")))
        self.assertEqual(inbound.received_quantity, inbound.accepted_quantity + inbound.return_quantity)
        payable = PurchasePayable.objects.get(material_inbound_id=inbound.inbound_id)
        payable_line = PurchasePayableLine.objects.get(payable=payable)
        self.assertEqual(payable_line.accepted_quantity, Decimal("3.9"))
        self.assertEqual(payable_line.source_unit_text_snapshot, "KG")
        repeated = create_payables_for_inbound(inbound_id=inbound.inbound_id, actor_employee=self.employee)
        self.assertEqual([row.pk for row in repeated], [payable.pk])
        self.assertEqual(PurchasePayableLine.objects.filter(payable=payable).count(), 1)
        balance_class = PublicStockBalance if catalog else MaterialStockBalance
        self.balance = balance_class.objects.get()
        self.assertEqual((self.balance.quantity, self.balance.weight_quantity), (accepted_quantity, Decimal("3.9")))
        self.assertEqual(self.balance.unit_id, self.piece_unit.pk)
        returned = PurchaseReturnLine.objects.get()
        self.assertEqual(returned.quantity, Decimal("0.6"))
        self.assertEqual(Decimal(purchase_return_amount(returned.return_order)), Decimal("1.2"))
        for action in ("confirm", "complete"):
            url = f"/api/v1/purchase-returns/{returned.return_order_id}/"
            detail = self.client.get(url)
            response = self.client.post(url + action + "/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(response.status_code, 200, response.data)
        self.balance.refresh_from_db()
        self.assertEqual((self.balance.quantity, self.balance.weight_quantity), (accepted_quantity, Decimal("3.9")))
        remaining = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": self.order_id})
        self.assertEqual(remaining.status_code, 200, remaining.data)
        self.assertEqual(Decimal(remaining.data["data"][0]["remaining_quantity"]), Decimal("1.1"))

    def issue_pieces(self, *, catalog):
        native_kg = self.piece_unit.unit_name == "KG"
        workshop = Workshop.objects.get(name="金工车间", status="ACTIVE")
        recipient = production_employee(workshop=workshop, position="领料员", name="五金重量验收领料员", status="ACTIVE")
        craft = Craft.objects.create(name="五金重量验收工艺", craft_type="INTERNAL", workshop=workshop,
            plan_category="METAL", status="ACTIVE", created_by_employee=self.employee, updated_by_employee=self.employee)
        today = timezone.localdate()
        schedule = create_schedule(validated_data={"client_request_id": uuid4(), "production_task_id": self.task.pk,
            "source_revision_hash": "", "items": [{"product_line_id": self.product_line.pk, "planned_quantity": 1000,
                "craft_ids": {craft.pk}, "material_inbound_date": today, "metal_return_date": today,
                "sewing_return_date": today, "finished_inbound_date": today}]}, actor_employee=self.employee)
        schedule_product = schedule.products.get(product_line=self.product_line, removed_at__isnull=True)
        scope = {"production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk),
            "workshop_id": str(workshop.pk), "plan_category": "METAL"}
        requirements = self.client.get("/api/v1/material-issues/requirements/", scope)
        self.assertEqual(requirements.status_code, 200, requirements.data)
        rows = requirements.data["data"]["items"]
        self.assertEqual(len(rows), 1, requirements.data)
        self.assertEqual(rows[0]["unit"], self.piece_unit.unit_name)
        self.assertEqual(Decimal(rows[0]["required_quantity"]), 1000)
        body = {**scope, "client_request_id": str(uuid4()), "schedule_product_id": str(schedule_product.pk),
            "recipient_workshop_employee_id": str(recipient.pk), "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": rows[0]["requirement_id"], "requested_quantity": "1.3" if native_kg else "300"}]}
        created = self.client.post("/api/v1/material-issues/", body, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        issue_url = f"/api/v1/material-issues/{created.data['data']['id']}/"
        submitted = self.client.post(issue_url + "submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        request = {"request_id": str(uuid4())}
        self.assertFalse(self.reviewer_user.is_superuser)
        self.assertFalse(self.reviewer_user.is_staff)
        stale = self.reviewer_client.post(issue_url + "confirm-issue/", request, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)
        issued = self.reviewer_client.post(issue_url + "confirm-issue/", request, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(issued.status_code, 200, issued.data)
        self.assertEqual(MaterialIssue.objects.get(pk=created.data["data"]["id"]).lines.get().unit_snapshot, self.piece_unit.unit_name)
        self.balance.refresh_from_db()
        issued_quantity = Decimal("1.3") if native_kg else Decimal("300")
        issued_weight = (Decimal("1.3") if native_kg else
            (Decimal("3.9") * issued_quantity / self.accepted_quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        self.assertEqual((self.balance.quantity, self.balance.weight_quantity),
                         (self.accepted_quantity - issued_quantity, Decimal("3.9") - issued_weight))
        movement_class = PublicStockMovement if catalog else MaterialStockMovement
        movement = movement_class.objects.get(source_type="MATERIAL_ISSUE", direction="OUT")
        self.assertEqual((movement.quantity, movement.weight_quantity), (issued_quantity, issued_weight))

    def run_flow(self, *, washer, catalog, native_kg=False, forged_counts=False):
        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=catalog, PUBLIC_STOCK_ISSUES_ENABLED=catalog):
            self.prepare_bom(washer=washer, catalog=catalog, native_kg=native_kg)
            self.create_purchase_and_sheet()
            self.receive_and_inspect(catalog=catalog, forged_counts=forged_counts)
            self.issue_pieces(catalog=catalog)

    def test_catalog_rivet_weight_flow_preserves_piece_count(self):
        self.run_flow(washer=False, catalog=True)

    def test_catalog_washer_weight_flow_preserves_piece_count(self):
        self.run_flow(washer=True, catalog=True)

    def test_legacy_rivet_weight_flow_preserves_piece_count(self):
        self.run_flow(washer=False, catalog=False)

    def test_legacy_washer_weight_flow_preserves_piece_count(self):
        self.run_flow(washer=True, catalog=False)

    def test_catalog_native_kg_is_not_converted_to_pieces(self):
        self.run_flow(washer=False, catalog=True, native_kg=True)

    def test_legacy_native_kg_is_not_converted_to_pieces(self):
        self.run_flow(washer=True, catalog=False, native_kg=True)

    def test_client_piece_counts_cannot_override_weight_floor(self):
        self.run_flow(washer=False, catalog=True, forged_counts=True)

    def test_sub_piece_weight_return_is_generated_and_filterable(self):
        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True):
            self.prepare_bom(washer=False, catalog=True)
            self.create_purchase_and_sheet()
            eligible = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": self.order_id})
            self.assertEqual(eligible.status_code, 200, eligible.data)
            receipt = self.client.post("/api/v1/material-inventory/receipts/", {"items": [{
                "purchase_order_line_id": self.purchase_line_id, "zone_id": str(self.zone.pk),
                "expected_remaining_quantity": eligible.data["data"][0]["remaining_quantity"],
                "received_weight_kg": "3.9650",
            }]}, format="json")
            self.assertEqual(receipt.status_code, 201, receipt.data)
            inbound = MaterialInboundLine.objects.get()
            self.assertEqual(inbound.received_quantity, Decimal("1001"))
            confirmed = self.client.post(
                f"/api/v1/material-inventory/quality-batches/{receipt.data['data']['id']}/confirm/",
                {"items": [{"line_id": str(inbound.pk), "expected_received_quantity": "3.9650",
                    "return_weight_kg": "0.0001", "quality_remark": "不足一件仍按实称公斤退货"}]},
                format="json",
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.data)
            inbound.refresh_from_db()
            self.assertEqual((inbound.return_quantity, inbound.return_weight_kg), (Decimal("0"), Decimal("0.0001")))
            self.assertEqual((inbound.accepted_quantity, inbound.accepted_weight_kg), (Decimal("1001"), Decimal("3.9649")))
            returned = PurchaseReturnLine.objects.get()
            self.assertEqual(returned.quantity, Decimal("0.0001"))
            self.assertEqual(returned.return_order.status, "QUALITY_GENERATED")
            for status, expected_ids in (("NONE", []), ("QUALITY_GENERATED", [self.order_id]), ("MISSING", [])):
                response = self.client.get("/api/v1/purchase-orders/", {"return_status": status})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual([row["id"] for row in response.data["data"]], expected_ids)

    def run_zero_reference_flow(self, *, catalog):
        from apps.inventory.public_stock_services import debit_public_stock
        from apps.inventory.stock_services import debit_material_stock

        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=catalog, PUBLIC_STOCK_ISSUES_ENABLED=catalog):
            self.prepare_bom(washer=not catalog, catalog=catalog)
            self.create_purchase_and_sheet()
            balance_class = PublicStockBalance if catalog else MaterialStockBalance
            movement_class = PublicStockMovement if catalog else MaterialStockMovement
            for index, (received, returned, cumulative_weight) in enumerate((
                    ("0.0001", "0", "0.0001"), ("0.0100", "0.0099", "0.0002"), ("0.0100", "0", "0.0102"))):
                eligible = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": self.order_id})
                self.assertEqual(eligible.status_code, 200, eligible.data)
                receipt = self.client.post("/api/v1/material-inventory/receipts/", {"items": [{
                    "purchase_order_line_id": self.purchase_line_id, "zone_id": str(self.zone.pk),
                    "expected_remaining_quantity": eligible.data["data"][0]["remaining_quantity"],
                    "received_weight_kg": received,
                }]}, format="json")
                self.assertEqual(receipt.status_code, 201, receipt.data)
                inbound = MaterialInboundLine.objects.get(inbound_id=receipt.data["data"]["id"])
                confirmed = self.client.post(
                    f"/api/v1/material-inventory/quality-batches/{receipt.data['data']['id']}/confirm/",
                    {"items": [{"line_id": str(inbound.pk), "expected_received_quantity": received,
                        "return_weight_kg": returned}]}, format="json")
                self.assertEqual(confirmed.status_code, 200, confirmed.data)
                inbound.refresh_from_db()
                accepted_weight = Decimal(received) - Decimal(returned)
                expected_count = (accepted_weight / self.expected_unit_weight).to_integral_value(rounding=ROUND_FLOOR)
                self.assertEqual((inbound.accepted_quantity, inbound.accepted_weight_kg), (expected_count, accepted_weight))
                payable_line = PurchasePayableLine.objects.get(material_inbound_line=inbound)
                self.assertEqual((payable_line.accepted_quantity, payable_line.source_unit_text_snapshot), (accepted_weight, "KG"))
                balance = balance_class.objects.get()
                self.assertEqual((balance.quantity, balance.weight_quantity), (expected_count, Decimal(cumulative_weight)))
                inventory = self.client.get("/api/v1/material-inventory/")
                self.assertEqual(inventory.status_code, 200, inventory.data)
                self.assertEqual(inventory.data["count"], 1)
                self.assertEqual((Decimal(inventory.data["results"][0]["inventory_quantity"]),
                    Decimal(inventory.data["results"][0]["weight_quantity"])), (expected_count, Decimal(cumulative_weight)))
                if index == 0:
                    # 数据库也拒绝缺失五金冻结标志的零数量，不能靠 SQL 的 NULL 放行。
                    movement = movement_class.objects.get(source_line_id=inbound.pk)
                    for invalid_snapshot in ({}, ["measurement_kind"], "measurement_kind", {"measurement_kind": None}):
                        with self.subTest(snapshot=invalid_snapshot):
                            with self.assertRaises(IntegrityError), transaction.atomic():
                                MaterialInboundLine.objects.filter(pk=inbound.pk).update(calculation_snapshot=invalid_snapshot)
                            with self.assertRaises(IntegrityError), transaction.atomic():
                                movement_class.objects.filter(pk=movement.pk).update(snapshot=invalid_snapshot)
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        movement_class.objects.filter(pk=movement.pk).update(direction="OUT")
                    with self.assertRaises(ValidationError):
                        kwargs = {"quantity": Decimal(0), "source_type": "MATERIAL_ISSUE", "source_id": uuid4(),
                            "source_line_id": uuid4(), "actor_employee": self.reviewer, "production_task": self.task}
                        if catalog:
                            debit_public_stock(balance_id=balance.pk, **kwargs)
                        else:
                            debit_material_stock(raw_material=self.raw_material, unit=self.piece_unit, zone=self.zone, **kwargs)
                for returned_line in PurchaseReturnLine.objects.filter(inbound_line=inbound):
                    self.assertEqual(returned_line.quantity, Decimal(returned))
                    for action in ("confirm", "complete"):
                        url = f"/api/v1/purchase-returns/{returned_line.return_order_id}/"
                        detail = self.client.get(url)
                        response = self.client.post(url + action + "/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
                        self.assertEqual(response.status_code, 200, response.data)
            remaining = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": self.order_id})
            self.assertEqual(remaining.status_code, 200, remaining.data)
            self.assertEqual(Decimal(remaining.data["data"][0]["remaining_quantity"]), Decimal("4.9898"))

    def test_catalog_zero_reference_keeps_actual_weight_and_is_not_issuable(self):
        self.run_zero_reference_flow(catalog=True)

    def test_legacy_zero_reference_keeps_actual_weight_and_is_not_issuable(self):
        self.run_zero_reference_flow(catalog=False)

    def test_historical_kg_missing_received_weight_keeps_progress_and_unknown_weight(self):
        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True):
            self.prepare_bom(washer=False, catalog=True, native_kg=True)
            self.create_purchase_and_sheet()
            self.receive_and_inspect(catalog=True)
            # 模拟历史批次缺少到货重量；保留已知合格重量，不补造未知值。
            MaterialInboundLine.objects.update(received_weight_kg=None)
            for unit in ("KG", "千克", "公斤"):
                with self.subTest(unit=unit):
                    PurchaseOrderLine.objects.filter(pk=self.purchase_line_id).update(source_unit_text=unit)
                    response = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
                    self.assertEqual(response.status_code, 200, response.data)
                    row = response.data["data"][0]
                    self.assertTrue(row["weight_unit"])
                    self.assertIsNone(row["received_weight_quantity"])
                    self.assertEqual(row["workflow_status"], "PARTIAL_RECEIVED")

    def test_ordinary_employee_permissions_and_session_csrf_remain_required(self):
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        preview = "/api/v1/boms/hardware-weight-preview/"
        self.assertEqual(client.post(preview, self.rivet_input(), format="json").status_code, 403)
        token = "h" * 32
        client.cookies[settings.CSRF_COOKIE_NAME] = token
        self.assertEqual(client.post(preview, self.rivet_input(), format="json", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        for url in ("/api/v1/purchase-orders/", "/api/v1/material-inventory/receipts/", "/api/v1/material-issues/"):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(PurchaseOrder.objects.exists())
        self.assertFalse(MaterialInboundLine.objects.exists())
        self.assertFalse(MaterialIssue.objects.exists())
