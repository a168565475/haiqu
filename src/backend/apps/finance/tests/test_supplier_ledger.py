from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.customers.models import CustomerAccount
from apps.finance.purchase_payable_services import create_payables_for_inbound
from apps.inventory.models import MaterialInbound, MaterialInboundLine, Warehouse, WarehouseZone
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.procurement.models import PurchaseOrderLine, Supplier
from apps.procurement.tests import test_loading_read_api as purchase_fixtures
from apps.reference_data.models import Currency


class SupplierLedgerFixture:
    root = "/api/v1/finance/supplier-ledger/"
    make_order = purchase_fixtures.PurchaseOrderLoadingReadTests.make_order

    def setUp(self):
        self.user = get_user_model().objects.create_user("supplier_ledger_reader")
        self.employee = Employee.objects.create(user=self.user, employee_code="LEDGER_READER", display_name="往来测试员工")
        self.cashier = get_user_model().objects.create_user("supplier_ledger_cashier")
        Employee.objects.create(user=self.cashier, employee_code="LEDGER_CASHIER", display_name="往来测试出纳")
        self.role = RoleProfile.objects.create(
            role_code="LEDGER_FINANCE_TEST", display_name="往来测试财务",
            auth_group=Group.objects.create(name="ledger-finance-test"),
        )
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=self.role, effective_from=timezone.now())
        self.customer = CustomerAccount.objects.create(
            account_code="LEDGER_TEST", account_name="往来测试客户", primary_country_code="CN",
        )
        self.currency, _ = Currency.objects.get_or_create(code="CNY", defaults={
            "numeric_code": "156", "chinese_name": "人民币", "english_name": "Yuan",
        })
        self.supplier = Supplier.objects.create(
            supplier_number="GYS98001", supplier_name="原供应商名", supplier_type="MATERIAL", supplier_categories=["TUBE"],
        )
        self.warehouse = Warehouse.objects.create(warehouse_number="LEDGER-WH", warehouse_name="测试材料仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="测试库区")
        self.client.force_authenticate(self.user)

    def grant(self, app, *codenames):
        for codename in codenames:
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            RoleActionGrant.objects.get_or_create(role=self.role, permission=permission, scope="MODULE")
            self.role.auth_group.permissions.add(permission)

    def receive(self, index, *, day=date(2026, 10, 31), supplier=None, count=2, currency="CNY", actor=None):
        supplier = supplier or self.supplier
        actor = actor or self.employee
        order = self.make_order(index, actor)
        order.currency_code_snapshot = currency
        order.save(update_fields=["currency_code_snapshot"])
        inbound = MaterialInbound.objects.create(
            inbound_number=f"CLRK-LEDGER-{index}", purchase_order=order, inbound_date=day,
            status="CONFIRMED", received_by_employee=actor,
        )
        for number in range(1, count + 1):
            source = PurchaseOrderLine.objects.create(
                purchase_order=order, line_number=number, quantity_parse_status="READY", supplier=supplier,
            )
            MaterialInboundLine.objects.create(
                inbound=inbound, purchase_order_line=source, zone=self.zone, material_snapshot=f"钢管 {number}",
                specification_snapshot="φ25 × 1.2 mm", source_unit_text_snapshot="KG",
                received_quantity=110, return_quantity=10, accepted_quantity=100, accepted_weight_kg=Decimal("125.0000"),
                purchased_quantity_snapshot=200,
            )
        payable, = create_payables_for_inbound(inbound_id=inbound.pk, actor_employee=actor)
        return payable, order, inbound

    def get_data(self, path="", **query):
        response = self.client.get(self.root + path, query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def price(self, payable):
        url = f"/api/v1/finance/purchase-payables/{payable.pk}/"
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        response = self.client.patch(url + "pricing/", {
            "tax_mode": "含税", "freight_mode": "含运费", "lines": [
                {"line_id": str(line.pk), "unit_price": "4.0000", "price_unit_text": "KG"}
                for line in payable.lines.all()
            ],
        }, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return url, response["ETag"]


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ALLOWED_HOSTS=["testserver"])
class SupplierLedgerTests(SupplierLedgerFixture, APITestCase):
    def test_cross_month_confirmation_uses_inbound_date_and_saved_line_amounts(self):
        self.grant("finance", "view_supplierledger", "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable")
        payable, order, inbound = self.receive(1)
        self.assertEqual(create_payables_for_inbound(inbound_id=inbound.pk)[0].pk, payable.pk)
        october = self.get_data(month="2026-10")
        self.assertEqual(len(october["data"]), 1)
        self.assertEqual(october["meta"]["page_size"], 50)
        self.assertEqual(october["data"][0]["pending_count"], 1)
        entries = self.get_data("entries/", month="2026-10", supplier_id=self.supplier.pk)["data"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(row["amount"] is None and row["status"] == "WAITING_PRICE" for row in entries))
        self.assertEqual(entries[0]["payable_id"], str(payable.pk))
        self.assertIsNone(entries[0]["purchase_order_id"])
        self.assertIsNone(entries[0]["inbound_id"])
        self.assertIsNone(entries[0]["production_task_id"])

        url, etag = self.price(payable)
        self.assertEqual(self.get_data(month="2026-10")["data"][0]["current_amount"], "0.00")
        priced = self.get_data("entries/", month="2026-10", supplier_id=self.supplier.pk)["data"][0]
        self.assertEqual((priced["amount"], priced["quantity"], priced["unit_price"]), (None, "125.0000", "4.0000"))
        with patch("apps.finance.purchase_payable_services.timezone", wraps=timezone) as clock:
            clock.now.return_value = datetime(2026, 11, 2, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
            response = self.client.post(url + "confirm/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 200, response.data)

        self.supplier.supplier_name = "更名且停用的供应商"
        self.supplier.is_disabled = True
        self.supplier.save()
        october = self.get_data(month="2026-10", supplier_id=self.supplier.pk)["data"][0]
        self.assertEqual((october["supplier_name"], october["opening_amount"], october["current_amount"], october["pending_count"]),
                         ("更名且停用的供应商", "0.00", "1000.00", 0))
        november = self.get_data(month="2026-11")["data"][0]
        self.assertEqual((november["opening_amount"], november["current_amount"]), ("1000.00", "0.00"))
        self.assertEqual(self.get_data("entries/", month="2026-11", supplier_id=self.supplier.pk)["data"], [])
        rows = self.get_data("entries/", month="2026-10", supplier_id=self.supplier.pk)["data"]
        self.assertEqual([row["amount"] for row in rows], ["500.00", "500.00"])
        self.assertEqual((rows[0]["inbound_date"], rows[0]["confirmed_date"], rows[0]["confirmed_by"]),
                         ("2026-10-31", "2026-11-02", self.employee.display_name))
        self.assertEqual(self.get_data("suppliers/")["data"][0]["id"], str(self.supplier.pk))

        self.grant("procurement", "view_purchaseorder")
        self.grant("inventory", "view_material_receipt")
        self.grant("production_tasks", "view_productiontask")
        entry = self.get_data("entries/", month="2026-10", supplier_id=self.supplier.pk)["data"][0]
        self.assertEqual((entry["purchase_order_id"], entry["inbound_id"], entry["production_task_id"]),
                         (str(order.pk), str(inbound.pk), str(order.production_task_id)))
        receipts = self.client.get("/api/v1/material-inventory/receipts/", {"inbound_id": inbound.pk})
        self.assertEqual(receipts.status_code, 200, receipts.data)
        self.assertEqual([row["id"] for row in receipts.data["data"]], [str(inbound.pk)])

    def test_cny_scope_pagination_and_independent_menu_permission(self):
        self.grant("finance", "view_supplierledger")
        identity = self.client.get("/api/auth/me/").data["user"]
        self.assertIn("finance.view_supplierledger", identity["permissions"])
        self.assertNotIn("finance.view_purchasepayable", identity["permissions"])
        other = Supplier.objects.create(
            supplier_number="GYS98002", supplier_name="外币来源", supplier_type="MATERIAL", supplier_categories=["TUBE"],
        )
        self.receive(1, count=1)
        self.receive(2, supplier=other, currency="USD", count=1)
        page = self.get_data(month="2026-10", page=1, page_size=20)
        self.assertEqual(page["meta"]["total"], 1)
        self.assertEqual(page["meta"]["page_size"], 20)
        self.assertEqual(page["data"], self.get_data(month="2026-10", supplier_id=self.supplier.pk)["data"])
        self.assertEqual(self.get_data(month="2026-10", supplier_id=other.pk)["data"], [])
        self.assertEqual(self.client.get(self.root + "entries/", {"supplier_id": other.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.root + "entries/", {"supplier_id": uuid4()}).status_code, 404)
        for query in ({"month": "2026-13"}, {"month": "0000-01"}, {"page_size": 25}, {"supplier_id": "invalid"}):
            self.assertEqual(self.client.get(self.root, query).status_code, 400)
        self.client.force_authenticate(self.cashier)
        for path in ("", "entries/", "suppliers/"):
            self.assertEqual(self.client.get(self.root + path, {"supplier_id": self.supplier.pk}).status_code, 403)
