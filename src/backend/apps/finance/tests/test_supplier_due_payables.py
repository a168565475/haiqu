from datetime import date, datetime
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.finance.models import FinanceAccount
from apps.procurement.models import Supplier

from . import test_supplier_payment_applications as application_fixtures
from . import test_supplier_settlements as settlement_fixtures
from .test_supplier_ledger import SupplierLedgerFixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ALLOWED_HOSTS=["testserver"])
class SupplierDuePayableTests(SupplierLedgerFixture, APITestCase):
    applications = "/api/v1/finance/supplier-payment-applications/"
    payments = "/api/v1/finance/supplier-payments/"
    due = payments + "due-payables/"
    details = payments + "due-payable-details/"
    confirmed = settlement_fixtures.SupplierSettlementTests.confirmed
    payment = settlement_fixtures.SupplierSettlementTests.payment
    offset = settlement_fixtures.SupplierSettlementTests.offset
    apply = application_fixtures.SupplierPaymentApplicationTests.apply
    register = application_fixtures.SupplierPaymentApplicationTests.register

    def setUp(self):
        super().setUp()
        self.grant("procurement", "view_supplier", "change_supplier")
        self.grant("finance", "view_supplierpayment", "add_supplierpaymentapplication",
                   "withdraw_supplierpaymentapplication", "view_supplierledger", "add_supplierpayment",
                   "add_supplieroffset", "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable")
        self.account = FinanceAccount.objects.create(
            account_type="银行", code="DUE-TEST", category="基本户", name="测试付款账户",
            account_number="000011", currency=self.currency, created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )

    def set_term(self, effective="2026-09", *, months=1, supplier=None):
        url = f"/api/v1/suppliers/{(supplier or self.supplier).pk}/"
        response = self.client.patch(url, {"payment_term": {
            "months": months, "effective_month": effective, "basis": "采购协议第 5 条",
        }}, format="json", HTTP_IF_MATCH=self.client.get(url)["ETag"])
        self.assertEqual(response.status_code, 200, response.data)

    def rows(self, url, **params):
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_due_summary_and_detail_are_current_and_use_the_same_originals(self):
        old = self.confirmed(1, day=date(2026, 8, 31), count=1)
        self.set_term()
        previous = self.confirmed(2, day=date(2026, 9, 30), count=1)
        future = self.confirmed(3, day=date(2026, 11, 1), count=1)
        late, _, _ = self.receive(4, day=date(2026, 10, 31), count=2)
        self.confirmed(5, day=date(2026, 10, 31), currency="USD")
        other_supplier = Supplier.objects.create(supplier_number="GYS98002", supplier_name="其他材料商",
                                                 supplier_type="MATERIAL", supplier_categories=["TUBE"])
        self.set_term(supplier=other_supplier)
        self.confirmed(6, day=date(2026, 10, 31), supplier=other_supplier, count=1)

        summary = self.rows(self.due, month="2026-11", supplier_id=self.supplier.pk)
        row, = summary
        self.assertEqual((row["overdue_amount"], row["current_due_amount"], row["due_total"]), ("500.00", "0.00", "500.00"))
        self.assertEqual(len(self.rows(self.due, month="2026-11", page_size=20)), 2)

        url, etag = self.price(late)
        with patch("apps.finance.purchase_payable_services.timezone", wraps=timezone) as clock:
            clock.now.return_value = datetime(2026, 12, 7, tzinfo=ZoneInfo("Asia/Shanghai"))
            response = self.client.post(url + "confirm/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 200, response.data)
        row, = self.rows(self.due, month="2026-12", supplier_id=self.supplier.pk)
        self.assertEqual((row["overdue_amount"], row["current_due_amount"], row["due_total"]),
                         ("1500.00", "500.00", "2000.00"))
        self.assertEqual(self.rows(self.due, month="2026-08"), [])
        detail = self.rows(self.details, month="2026-11", supplier_id=self.supplier.pk)
        self.assertEqual([item["id"] for item in detail], [str(previous.pk), str(late.pk)])
        self.assertEqual([(item["inbound_date"], item["due_month"], item["requestable_amount"]) for item in detail],
                         [("2026-09-30", "2026-10", "500.00"), ("2026-10-31", "2026-11", "1000.00")])
        eligible = self.applications + "eligible-payables/"
        focused = self.rows(eligible, supplier_id=self.supplier.pk, due_through_month="2026-11")
        self.assertEqual([payable["id"] for month in focused for payable in month["payables"]],
                         [str(previous.pk), str(late.pk)])
        all_rows = self.rows(eligible, supplier_id=self.supplier.pk)
        payables = {payable["id"]: payable for month in all_rows for payable in month["payables"]}
        self.assertIsNone(payables[str(old.pk)]["payment_term_months"])
        self.assertEqual(payables[str(future.pk)]["due_month"], "2026-12")
        self.assertEqual(self.apply([(old, "100.00")]).status_code, 201)

    def test_due_amount_reuses_offsets_requests_and_paid_but_unallocated_holds(self):
        self.set_term()
        payable = self.confirmed(1, count=20)
        paid = self.payment(amount="2000.00")
        self.assertEqual(paid.status_code, 201, paid.data)
        row, = self.rows(self.due, supplier_id=self.supplier.pk, month="2026-11")
        self.assertEqual(row["due_total"], "10000.00")
        allocated = self.offset(paid.data["data"]["id"], [(payable, "2000.00")])
        self.assertEqual(allocated.status_code, 201, allocated.data)
        first = self.apply([(payable, "3000.00")])
        self.assertEqual(first.status_code, 201, first.data)
        self.set_term("2026-11", months=3)
        saved_application = self.client.get(f"{self.applications}{first.data['data']['id']}/").data["data"]
        self.assertEqual((saved_application["amount"], saved_application["lines"][0]["amount"]),
                         ("3000.00", "3000.00"))
        row, = self.rows(self.details, supplier_id=self.supplier.pk, month="2026-11")
        self.assertEqual((row["current_balance"], row["occupied_amount"], row["requestable_amount"]),
                         ("8000.00", "3000.00", "5000.00"))
        self.assertEqual(self.apply([(payable, "5000.01")]).status_code, 409)
        second = self.apply([(payable, "5000.00")])
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(self.rows(self.due, supplier_id=self.supplier.pk, month="2026-11"), [])
        second_url = f"{self.applications}{second.data['data']['id']}/"
        withdrawn = self.client.post(second_url + "withdraw/", {"reason": "暂不申请"},
                                     format="json", HTTP_IF_MATCH=second["ETag"])
        self.assertEqual(withdrawn.status_code, 200, withdrawn.data)
        paid = self.register("1000.00", application=first.data["data"]["id"])
        self.assertEqual(paid.status_code, 201, paid.data)
        row, = self.rows(self.due, supplier_id=self.supplier.pk, month="2026-11")
        self.assertEqual(row["due_total"], "5000.00")
        allocated = self.offset(paid.data["data"]["id"], [(payable, "1000.00")])
        self.assertEqual(allocated.status_code, 201, allocated.data)
        row, = self.rows(self.details, supplier_id=self.supplier.pk, month="2026-11")
        self.assertEqual((row["current_balance"], row["occupied_amount"], row["requestable_amount"]),
                         ("7000.00", "2000.00", "5000.00"))

    def test_read_only_permission_and_filter_validation(self):
        self.set_term()
        payable = self.confirmed(1)
        codes = ["add_supplierpaymentapplication", "view_purchasepayable", "change_supplier"]
        grants = RoleActionGrant.objects.filter(role=self.role, permission__codename__in=codes)
        self.role.auth_group.permissions.remove(*[row.permission_id for row in grants])
        grants.delete()
        self.assertEqual(len(self.rows(self.due, month="2026-11")), 1)
        self.assertEqual(len(self.rows(self.details, month="2026-11", supplier_id=self.supplier.pk)), 1)
        self.assertEqual(self.apply([(payable, "1.00")]).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/finance/purchase-payables/{payable.pk}/").status_code, 403)
        denied = self.client.patch(f"/api/v1/suppliers/{self.supplier.pk}/", {}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get(self.details, {"month": "2026-11"}).status_code, 400)
        self.assertEqual(self.client.get(self.due, {"month": "2026-13"}).status_code, 400)
        self.assertEqual(self.client.get(self.due, {"page_size": 7}).status_code, 400)
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get(self.due).status_code, 403)
        self.assertEqual(self.client.get(self.details, {"supplier_id": self.supplier.pk}).status_code, 403)
