from datetime import date, datetime
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.finance.models import FinanceAccount
from apps.procurement.models import Supplier
from .test_supplier_ledger import SupplierLedgerFixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ALLOWED_HOSTS=["testserver"])
class SupplierSettlementTests(SupplierLedgerFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.grant("finance", "view_supplierledger", "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable",
                   "add_supplierpayment", "add_supplieroffset", "void_supplierpayment", "void_supplieroffset")
        self.account = FinanceAccount.objects.create(
            account_type="银行", code="LEDGER-TEST", category="基本户", name="测试付款账户", account_number="000001",
            currency=self.currency, created_by_employee=self.employee, updated_by_employee=self.employee,
        )

    def confirmed(self, index, *, confirm_day=2, **kwargs):
        payable, _, _ = self.receive(index, **kwargs)
        url, etag = self.price(payable)
        with patch("apps.finance.purchase_payable_services.timezone", wraps=timezone) as clock:
            clock.now.return_value = datetime(2026, 11, confirm_day, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
            result = self.client.post(url + "confirm/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(result.status_code, 200, result.data)
        return payable

    def payment(self, *, amount="300.00", nature="PREPAYMENT", request_id=None, replaces=None):
        source = self.get_data("payment-options/")["data"]
        account = next(item for item in source["accounts"] if item["id"] == str(self.account.pk))
        data = {"supplier_id": str(self.supplier.pk), "nature": nature, "paid_on": "2026-11-05",
                "account_id": str(self.account.pk), "payee": "测试收款人", "amount": amount, "voucher": "TEST-20261105"}
        if replaces:
            data["replaces_id"] = replaces
        with patch("apps.finance.supplier_settlement_serializers.timezone", wraps=timezone) as clock:
            clock.localdate.return_value = date(2026, 12, 31)
            return self.client.post(self.root + "payments/", data, format="json",
                                    HTTP_IF_MATCH=account["etag"], HTTP_IDEMPOTENCY_KEY=str(request_id or uuid4()))

    def offset(self, payment_id, allocations, *, day="2026-12-03", key=None, etag=None, replaces=None):
        if not etag:
            etag = self.client.get(self.root + f"payments/{payment_id}/")["ETag"]
        data = {"payment_id": payment_id, "offset_on": day,
                "allocations": [{"payable_id": str(payable.pk), "amount": amount} for payable, amount in allocations]}
        if replaces:
            data["replaces_id"] = replaces
        return self.client.post(self.root + "offsets/", data, format="json",
                                HTTP_IF_MATCH=etag, HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def correction(self, path):
        resource = self.client.get(self.root + path)
        self.assertEqual(resource.status_code, 200, resource.data)
        return self.client.post(self.root + path + "void/", {"reason": "原单录入错误"}, format="json",
                                HTTP_IF_MATCH=resource["ETag"])

    def test_monthly_worked_example_replay_and_corrections(self):
        payable = self.confirmed(1)
        payment_key = uuid4()
        created = self.payment(request_id=payment_key)
        self.assertEqual(created.status_code, 201, created.data)
        payment = created.data["data"]["id"]
        self.assertEqual(self.payment(request_id=payment_key).status_code, 200)
        self.assertEqual(self.payment(amount="301.00", request_id=payment_key).status_code, 409)
        offset_key = uuid4()
        epoch = created["ETag"]
        offset = self.offset(payment, [(payable, "300.00")], key=offset_key, etag=epoch)
        self.assertEqual(offset.status_code, 201, offset.data)
        offset_id = offset.data["data"]["id"]
        self.assertEqual(self.offset(payment, [(payable, "300.00")], key=offset_key, etag=epoch).status_code, 200)
        self.assertEqual(self.offset(payment, [(payable, "1.00")], etag=epoch).status_code, 412)
        fields = ("opening_amount", "current_amount", "paid_amount", "offset_amount", "closing_amount", "unused_prepayment")
        for month, values in {
            "2026-10": ("0.00", "1000.00", "0.00", "0.00", "1000.00", "0.00"),
            "2026-11": ("1000.00", "0.00", "300.00", "0.00", "1000.00", "300.00"),
            "2026-12": ("1000.00", "0.00", "0.00", "300.00", "700.00", "0.00"),
        }.items():
            summary = self.get_data(month=month)["data"][0]
            self.assertEqual(tuple(summary[field] for field in fields), values)
        self.assertEqual(self.get_data("entries/", month="2026-11", supplier_id=self.supplier.pk)["data"][0]["paid_amount"], "300.00")
        self.assertEqual(self.correction(f"payments/{payment}/").status_code, 409)
        corrected_offset = self.correction(f"offsets/{offset_id}/")
        self.assertEqual(corrected_offset.status_code, 200, corrected_offset.data)
        self.assertEqual(self.get_data(month="2026-12")["data"][0]["closing_amount"], "1000.00")
        new_offset = self.offset(payment, [(payable, "100.00")], replaces=offset_id)
        self.assertEqual(new_offset.status_code, 201, new_offset.data)
        self.assertEqual(new_offset.data["data"]["replaces_id"], offset_id)
        self.assertEqual(self.get_data(month="2026-12")["data"][0]["closing_amount"], "900.00")
        self.assertEqual(self.correction(f"offsets/{new_offset.data['data']['id']}/").status_code, 200)
        corrected_payment = self.correction(f"payments/{payment}/")
        self.assertEqual(corrected_payment.status_code, 200, corrected_payment.data)
        self.assertEqual(corrected_payment.data["data"]["void_reason"], "原单录入错误")
        self.assertEqual(self.get_data(month="2026-11")["data"][0]["unused_prepayment"], "0.00")
        replaced = self.payment(amount="250.00", replaces=payment)
        self.assertEqual(replaced.status_code, 201, replaced.data)
        self.assertEqual(replaced.data["data"]["replaces_id"], payment)
        self.assertEqual(self.payment(amount="251.00", replaces=payment).status_code, 409)
        self.assertEqual(AuditLog.objects.filter(object_type="SUPPLIER_PAYMENT", object_id=payment, action="VOID").count(), 1)

    def test_partial_multiple_sources_scope_and_over_allocation(self):
        first = self.confirmed(1, count=1)
        second = self.confirmed(2, count=1, confirm_day=10)
        other = Supplier.objects.create(supplier_number="GYS98002", supplier_name="其他供应商", supplier_type="MATERIAL")
        external = self.confirmed(3, supplier=other, count=1)
        created = self.payment(amount="900.00", nature="GOODS")
        self.assertEqual(created.status_code, 201, created.data)
        payment = created.data["data"]["id"]
        self.assertEqual(self.offset(payment, [(external, "1.00")]).status_code, 409)
        self.assertEqual(self.offset(payment, [(first, "501.00")]).status_code, 409)
        self.assertEqual(self.offset(payment, [(first, "1.00")], day="2026-11-04").status_code, 409)
        self.assertEqual(self.offset(payment, [(first, "300.00"), (second, "200.00")]).status_code, 201)
        self.assertEqual(self.offset(payment, [(first, "201.00")]).status_code, 409)
        early = self.offset(payment, [(second, "1.00")], day="2026-11-07")
        self.assertEqual((early.status_code, early.data["error"]["code"]), (409, "OFFSET_DATE_INVALID"))
        self.assertEqual(self.offset(payment, [(first, "200.00")]).status_code, 201)
        self.assertEqual(self.offset(payment, [(second, "201.00")]).status_code, 409)
        december = self.get_data("entries/", month="2026-12", supplier_id=self.supplier.pk)["data"]
        self.assertEqual(len(december), 3)
        self.assertEqual(self.get_data(month="2026-12", supplier_id=self.supplier.pk)["data"][0]["unused_prepayment"], "0.00")
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.post(self.root + "payments/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.post(self.root + "offsets/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.post(self.root + f"payments/{payment}/void/", {}, format="json").status_code, 403)
