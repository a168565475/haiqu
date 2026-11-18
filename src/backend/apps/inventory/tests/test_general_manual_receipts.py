"""一般入库的批量提交契约；使用隔离 PostgreSQL 和真实库存服务。"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.material_catalog.models import MaterialCatalog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit

from ..models import MaterialInbound, MaterialInboundLine, PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class GeneralManualReceiptTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="general_manual_receipt")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="GENERAL_RECEIPT", display_name="一般入库测试员工",
        )
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label__in=["inventory", "material_catalog"],
        ))
        self.client.force_authenticate(self.user)
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name="PCS", defaults={"unit_code": "GMPCS"})
        self.root_unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "GMROOT"})
        self.catalog = MaterialCatalog.objects.create(
            category_key="HARDWARE", template_key="HARDWARE", name="批量入库五金",
        )
        self.zones = []
        for index in (1, 2):
            warehouse = Warehouse.objects.create(
                warehouse_number=f"GM{index}", warehouse_name=f"一般入库材料仓{index}", warehouse_type="MATERIAL",
            )
            self.zones.append(WarehouseZone.objects.create(warehouse=warehouse, zone_name="主库区"))

    def item(self, *, zone=None, quantity="2.5000", specification="M8"):
        return {
            "material_catalog_id": str(self.catalog.pk),
            "zone_id": str((zone or self.zones[0]).pk),
            "received_quantity": quantity,
            "material_selection": {
                "catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE",
                "processing_state": "RAW", "unit_id": str(self.unit.pk),
                "attributes": {"specification": specification},
            },
        }

    def payload(self, *items):
        return {
            "client_request_id": str(uuid4()), "inbound_date": timezone.localdate().isoformat(),
            "remark": "一般入库批量登记", "items": list(items),
        }

    def post(self, payload):
        return self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")

    def assert_no_inventory_written(self):
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(MaterialInboundLine.objects.exists())
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_three_rows_make_one_receipt_and_keep_warehouse_balances_separate(self):
        response = self.post(self.payload(
            self.item(), self.item(quantity="3.0000"), self.item(zone=self.zones[1], quantity="4.0000"),
        ))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["source_type"], "MANUAL")
        inbound = MaterialInbound.objects.get()
        self.assertEqual(inbound.status, "CONFIRMED")
        self.assertIsNone(inbound.purchase_order_id)
        self.assertEqual(inbound.lines.count(), 3)
        self.assertEqual(PublicStockMovement.objects.count(), 3)
        balances = {balance.zone_id: balance.quantity for balance in PublicStockBalance.objects.all()}
        self.assertEqual(balances, {self.zones[0].pk: Decimal("5.5"), self.zones[1].pk: Decimal("4")})

    def test_same_catalog_with_different_specifications_keeps_distinct_stock(self):
        response = self.post(self.payload(self.item(), self.item(specification="M10", quantity="7.0000")))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialInbound.objects.get().lines.count(), 2)
        balances = list(PublicStockBalance.objects.order_by("quantity"))
        self.assertEqual([balance.quantity for balance in balances], [Decimal("2.5"), Decimal("7")])
        self.assertNotEqual(balances[0].identity_key, balances[1].identity_key)

    def test_invalid_later_zone_rolls_back_all_rows_and_catalog_changes(self):
        self.zones[1].status = "DISABLED"
        self.zones[1].save(update_fields=["status"])
        old_version = self.catalog.updated_at
        response = self.post(self.payload(self.item(), self.item(zone=self.zones[1], specification="M10")))
        self.assertEqual(response.status_code, 409, response.data)
        self.assert_no_inventory_written()
        self.catalog.refresh_from_db()
        self.assertEqual(self.catalog.updated_at, old_version)
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_multirow_retry_returns_original_receipt_without_double_credit(self):
        payload = self.payload(self.item(), self.item(zone=self.zones[1], quantity="4.0000"))
        first = self.post(payload)
        self.assertEqual(first.status_code, 201, first.data)
        retry = self.post(payload)
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertEqual(retry.data["data"]["id"], first.data["data"]["id"])
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(sum(PublicStockBalance.objects.values_list("quantity", flat=True)), Decimal("6.5"))

    def test_changing_second_row_of_same_request_is_rejected_without_extra_credit(self):
        payload = self.payload(self.item(), self.item(zone=self.zones[1], quantity="4.0000"))
        self.assertEqual(self.post(payload).status_code, 201)
        changed = deepcopy(payload)
        changed["items"][1]["received_quantity"] = "9.0000"
        response = self.post(changed)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(sum(PublicStockBalance.objects.values_list("quantity", flat=True)), Decimal("6.5"))

    def test_readonly_inventory_user_cannot_submit_batch(self):
        reader = get_user_model().objects.create_user(username="general_receipt_reader")
        Employee.objects.create(user=reader, employee_code="GENERAL_READER", display_name="库存只读测试员工")
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="inventory", codename="view_materialinbound"))
        self.client.force_authenticate(reader)
        response = self.post(self.payload(self.item(), self.item(quantity="4.0000")))
        self.assertEqual(response.status_code, 403, response.data)
        self.assert_no_inventory_written()

    def test_session_submit_without_csrf_is_rejected_before_stock_write(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post("/api/v1/material-inventory/manual-receipts/", self.payload(self.item()), format="json")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn("CSRF", str(response.data))
        self.assert_no_inventory_written()

    def test_pipe_rows_keep_actual_lengths_and_exact_root_meter_balances(self):
        self.catalog.category_key = self.catalog.template_key = "TUBE"
        self.catalog.save()
        items = []
        for roots, length in ((2, "3.05"), (3, "6.00")):
            item = self.item()
            item.pop("received_quantity")
            item.update(received_bar_count=roots, raw_bar_length_m=length, received_weight_kg=str(Decimal(roots) * Decimal("2.5")))
            item["material_selection"]["unit_id"] = str(self.root_unit.pk)
            item["material_selection"]["attributes"] = {
                "material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000",
            }
            items.append(item)
        response = self.post(self.payload(*items))
        self.assertEqual(response.status_code, 201, response.data)
        balances = list(PublicStockBalance.objects.order_by("raw_bar_length_m"))
        self.assertEqual([(balance.quantity, balance.meter_quantity) for balance in balances], [
            (Decimal("2"), Decimal("6.10")), (Decimal("3"), Decimal("18.00")),
        ])
        self.assertEqual(MaterialInbound.objects.get().lines.count(), 2)
        self.assertEqual([balance.weight_quantity for balance in balances], [Decimal("5"), Decimal("7.5")])

    def test_invalid_later_quantity_does_not_save_valid_first_row(self):
        response = self.post(self.payload(self.item(), self.item(quantity="0")))
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_no_inventory_written()
