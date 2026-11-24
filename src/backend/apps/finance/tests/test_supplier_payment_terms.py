from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.finance.purchase_payable_services import create_payables_for_inbound
from apps.procurement.models import Supplier

from .test_supplier_ledger import SupplierLedgerFixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ALLOWED_HOSTS=["testserver"])
class SupplierPaymentTermTests(SupplierLedgerFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.grant("procurement", "view_supplier", "add_supplier", "change_supplier")
        self.grant("finance", "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable")
        self.supplier_url = f"/api/v1/suppliers/{self.supplier.pk}/"

    def change_term(self, months, effective_month, *, supplier_url=None):
        url = supplier_url or self.supplier_url
        return self.client.patch(url, {"payment_term": {
            "months": months, "effective_month": effective_month, "basis": "采购协议第 5 条",
        }}, format="json", HTTP_IF_MATCH=self.client.get(url)["ETag"])

    def test_supplier_history_and_existing_monthly_cycle(self):
        self.supplier.payment_cycle = "MONTHLY"
        self.supplier.save(update_fields=["payment_cycle"])
        initial = self.client.get(self.supplier_url).data["data"]
        self.assertEqual((initial["payment_cycle"], initial["payment_term_versions"]), ("MONTHLY", []))

        self.assertEqual(self.change_term(1, "2026-10").status_code, 200)
        change = self.change_term(3, "2026-11")
        self.assertEqual(change.status_code, 200, change.data)
        versions = change.data["data"]["payment_term_versions"]
        self.assertEqual([(term["months"], term["effective_month"]) for term in versions],
                         [(3, "2026-11"), (1, "2026-10")])
        self.assertEqual(versions[0]["recorded_by_name"], self.employee.display_name)
        self.assertTrue(versions[0]["recorded_at"])
        self.assertEqual(versions[0]["basis"], "采购协议第 5 条")
        audit = AuditLog.objects.filter(object_type="SUPPLIER", object_id=self.supplier.pk).latest("occurred_at")
        self.assertEqual(audit.after_data["payment_term"]["id"], versions[0]["id"])
        self.assertEqual(self.change_term(1, "2026-11").status_code, 400)
        self.assertEqual(self.change_term(2, "2026-12").status_code, 400)
        self.assertEqual(self.change_term(1, "2026-13").status_code, 400)

    def test_supplier_create_accepts_term_and_rejects_missing_basis(self):
        payload = {
            "supplier_type": "MATERIAL", "supplier_categories": ["TUBE"], "supplier_name": "账期新建测试",
            "payment_term": {"months": 1, "effective_month": "2026-10", "basis": " "},
        }
        url = "/api/v1/suppliers/"
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 400)
        payload["payment_term"]["basis"] = "新签协议"
        created = self.client.post(url, payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["payment_term_versions"][0]["months"], 1)
        payload["supplier_type"] = "FINISHED"
        payload["supplier_categories"] = ["FINISHED_GOODS"]
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 400)

    def test_payables_use_receipt_month_and_keep_snapshot_on_retry_and_late_confirmation(self):
        old, _, old_inbound = self.receive(1, day=date(2026, 9, 30))
        self.assertEqual(self.change_term(1, "2026-10").status_code, 200)
        start, _, _ = self.receive(2, day=date(2026, 10, 1))
        self.assertEqual(self.change_term(3, "2026-11").status_code, 200)
        end, _, end_inbound = self.receive(3, day=date(2026, 10, 31))
        november, _, _ = self.receive(4, day=date(2026, 11, 30))
        self.assertEqual(self.change_term(1, "2026-12").status_code, 200)
        december, _, _ = self.receive(5, day=date(2026, 12, 31))
        self.assertEqual(self.change_term(3, "2026-09").status_code, 200)
        october_three = Supplier.objects.create(
            supplier_number="GYS98002", supplier_name="三个月账期测试", supplier_type="MATERIAL",
            supplier_categories=["TUBE"],
        )
        url = f"/api/v1/suppliers/{october_three.pk}/"
        self.assertEqual(self.change_term(3, "2026-10", supplier_url=url).status_code, 200)
        cross_year, _, _ = self.receive(6, day=date(2026, 10, 31), supplier=october_three)

        self.assertEqual(create_payables_for_inbound(inbound_id=old_inbound.pk)[0].pk, old.pk)
        self.assertEqual(create_payables_for_inbound(inbound_id=end_inbound.pk)[0].pk, end.pk)
        priced_url, etag = self.price(end)
        with patch("apps.finance.purchase_payable_services.timezone", wraps=timezone) as clock:
            clock.now.return_value = datetime(2026, 12, 7, tzinfo=ZoneInfo("Asia/Shanghai"))
            confirmed = self.client.post(priced_url + "confirm/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        for payable, months, due_month in (
            (old, None, None), (start, 1, "2026-11"), (end, 1, "2026-11"),
            (november, 3, "2027-02"), (december, 1, "2027-01"), (cross_year, 3, "2027-01"),
        ):
            with self.subTest(payable=payable.number):
                data = self.client.get(f"/api/v1/finance/purchase-payables/{payable.pk}/").data["data"]
                self.assertEqual((data["payment_term_months"], data["due_month"]), (months, due_month))
                self.assertEqual(bool(data["payment_term_id"]), months is not None)
