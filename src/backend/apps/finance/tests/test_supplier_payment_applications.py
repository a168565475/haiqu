from datetime import date
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.finance.models import FinanceAccount
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from . import test_supplier_settlements as settlement_fixtures
from .test_supplier_ledger import SupplierLedgerFixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ALLOWED_HOSTS=["testserver"])
class SupplierPaymentApplicationTests(SupplierLedgerFixture, APITestCase):
    applications = "/api/v1/finance/supplier-payment-applications/"
    payments = "/api/v1/finance/supplier-payments/"
    confirmed = settlement_fixtures.SupplierSettlementTests.confirmed
    offset = settlement_fixtures.SupplierSettlementTests.offset
    correction = settlement_fixtures.SupplierSettlementTests.correction

    def setUp(self):
        super().setUp()
        self.grant("finance", "view_supplierpayment", "add_supplierpaymentapplication", "withdraw_supplierpaymentapplication",
                   "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable", "add_supplierpayment")
        self.account = FinanceAccount.objects.create(
            account_type="银行", code="APPLY-TEST", category="基本户", name="测试付款账户", account_number="000010",
            currency=self.currency, created_by_employee=self.employee, updated_by_employee=self.employee,
        )

    def apply(self, lines, *, key=None):
        return self.client.post(self.applications, {
            "supplier_id": str(self.supplier.pk), "applied_on": "2026-11-06",
            "payee": "原供应商收款抬头", "note": "材料货款",
            "lines": [{"payable_id": str(payable.pk), "amount": amount} for payable, amount in lines],
        }, format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def register(self, amount, *, application=None, day="2026-12-03", key=None, replaces=None):
        options = self.client.get(self.payments + "payment-options/").data["data"]
        account = next(row for row in options["accounts"] if row["id"] == str(self.account.pk))
        data = {
            "supplier_id": str(self.supplier.pk), "account_id": account["id"], "nature": "GOODS",
            "paid_on": day, "payee": "原供应商收款抬头", "amount": amount, "voucher": "TEST-RECEIPT",
        }
        if application:
            data["application_id"] = application
        if replaces:
            data["replaces_id"] = replaces
        with patch("apps.finance.supplier_settlement_serializers.timezone", wraps=timezone) as clock:
            clock.localdate.return_value = date(2026, 12, 31)
            return self.client.post(self.payments, data, format="json", HTTP_IF_MATCH=account["etag"],
                                    HTTP_IDEMPOTENCY_KEY=str(key or uuid4()))

    def eligible(self):
        response = self.client.get(self.applications + "eligible-payables/", {"supplier_id": self.supplier.pk})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_inbound_months_and_original_payable_occupation(self):
        august = self.confirmed(1, day=date(2026, 8, 12), count=1)
        september = self.confirmed(2, day=date(2026, 9, 1), count=1)
        pending, _, _ = self.receive(3)
        foreign = self.confirmed(4, currency="USD")
        self.assertEqual([row["month"] for row in self.eligible()], ["2026-08", "2026-09"])
        self.assertEqual(self.apply([(pending, "1.00")]).status_code, 409)
        self.assertEqual(self.apply([(foreign, "1.00")]).status_code, 409)
        self.assertEqual(self.apply([(august, "1.001")]).status_code, 400)
        self.assertEqual(self.apply([(august, "1.00"), (august, "1.00")]).status_code, 400)
        key = uuid4()
        created = self.apply([(august, "200.00"), (september, "500.00")], key=key)
        self.assertEqual(created.status_code, 201, created.data)
        application = created.data["data"]
        self.assertEqual((application["amount"], application["paid_amount"], application["remaining_amount"]),
                         ("700.00", "0.00", "700.00"))
        self.assertEqual([row["month"] for row in application["lines"]], ["2026-08", "2026-09"])
        self.assertEqual(self.apply([(august, "200.00"), (september, "500.00")], key=key).data["data"]["id"], application["id"])
        self.assertEqual(self.apply([(august, "201.00")], key=key).status_code, 409)
        self.assertEqual(self.apply([(august, "300.01")]).status_code, 409)
        self.assertEqual(self.apply([(september, "0.01")]).status_code, 409)
        self.assertEqual([row["requestable_amount"] for row in self.eligible()], ["300.00", "0.00"])
        self.assertEqual(self.client.get(self.applications, {"month": "2026-11"}).data["meta"]["total"], 1)
        self.assertEqual(self.client.get(self.applications, {"month": "2026-08"}).data["data"], [])

    def test_payment_is_shared_and_only_assigned_offset_reduces_debt(self):
        first = self.confirmed(1, count=1)
        other = self.confirmed(2, count=1)
        created = self.apply([(first, "300.00")])
        self.assertEqual(created.status_code, 201, created.data)
        app_id = created.data["data"]["id"]
        key = uuid4()
        posted = self.register("120.00", application=app_id, key=key)
        self.assertEqual(posted.status_code, 201, posted.data)
        payment_id = posted.data["data"]["id"]
        self.assertEqual(self.register("120.00", application=app_id, key=key).data["data"]["id"], payment_id)
        self.assertEqual(self.register("180.01", application=app_id).status_code, 409)
        self.assertEqual(self.eligible()[0]["payables"][0]["occupied_amount"], "300.00")
        self.assertEqual(self.client.get(self.payments, {"month": "2026-11"}).data["data"], [])
        self.assertEqual([row["id"] for row in self.client.get(self.payments, {"month": "2026-12"}).data["data"]], [payment_id])
        detail = self.client.get(self.applications + app_id + "/").data["data"]
        self.assertEqual((detail["paid_amount"], detail["remaining_amount"]), ("120.00", "180.00"))
        self.assertEqual(detail["payments"][0]["id"], payment_id)

        self.grant("finance", "view_supplierledger", "add_supplieroffset")
        summary = self.get_data(month="2026-12")["data"][0]
        self.assertEqual((summary["paid_amount"], summary["closing_amount"]), ("120.00", "1000.00"))
        ledger_payment = self.get_data("entries/", month="2026-12", supplier_id=self.supplier.pk)["data"][0]
        self.assertEqual(ledger_payment["document_id"], payment_id)
        options = self.get_data("offset-payables/", payment_id=payment_id)["data"]
        self.assertEqual([row["id"] for row in options], [str(first.pk)])
        self.assertEqual(self.offset(payment_id, [(other, "1.00")]).status_code, 409)
        allocated = self.offset(payment_id, [(first, "120.00")])
        self.assertEqual(allocated.status_code, 201, allocated.data)
        row = next(item for item in self.eligible()[0]["payables"] if item["id"] == str(first.pk))
        self.assertEqual((row["current_balance"], row["occupied_amount"], row["requestable_amount"]),
                         ("380.00", "180.00", "200.00"))
        summary = self.get_data(month="2026-12")["data"][0]
        self.assertEqual((summary["paid_amount"], summary["offset_amount"], summary["closing_amount"]), ("120.00", "120.00", "880.00"))
        direct = self.register("10.00")
        self.assertEqual(direct.status_code, 201, direct.data)
        self.assertIsNone(direct.data["data"]["application_id"])

    def test_withdrawal_releases_unexecuted_amount_and_keeps_payment_history(self):
        payable = self.confirmed(1, count=1)
        created = self.apply([(payable, "400.00")])
        app_id = created.data["data"]["id"]
        detail_url = self.applications + app_id + "/"
        payment_id = self.register("150.00", application=app_id).data["data"]["id"]
        fresh = self.client.get(detail_url)
        self.assertEqual(self.client.post(detail_url + "withdraw/", {"reason": "撤回余款"}, format="json",
                                          HTTP_IF_MATCH=created["ETag"]).status_code, 412)
        pending = self.client.post(detail_url + "withdraw/", {"reason": "撤回余款"}, format="json", HTTP_IF_MATCH=fresh["ETag"])
        self.assertEqual(pending.status_code, 409, pending.data)
        self.grant("finance", "view_supplierledger", "add_supplieroffset", "void_supplieroffset", "void_supplierpayment")
        result = self.offset(payment_id, [(payable, "150.00")])
        self.assertEqual(result.status_code, 201, result.data)
        withdrawn = self.client.post(detail_url + "withdraw/", {"reason": "撤回余款"}, format="json",
                                     HTTP_IF_MATCH=self.client.get(detail_url)["ETag"])
        self.assertEqual(withdrawn.status_code, 200, withdrawn.data)
        self.assertEqual((withdrawn.data["data"]["amount"], withdrawn.data["data"]["paid_amount"],
                          withdrawn.data["data"]["remaining_amount"]), ("400.00", "150.00", "0.00"))
        self.assertEqual(self.eligible()[0]["requestable_amount"], "350.00")
        self.assertEqual(self.register("0.01", application=app_id).status_code, 409)
        offset_id = result.data["data"]["id"]
        self.assertEqual(self.correction(f"offsets/{offset_id}/").status_code, 200)
        self.assertEqual(self.eligible()[0]["requestable_amount"], "350.00")
        self.assertEqual(self.correction(f"payments/{payment_id}/").status_code, 200)
        history = self.client.get(self.payments, {"month": "2026-12"}).data["data"]
        self.assertEqual([(row["id"], row["status"]) for row in history], [(payment_id, "VOID")])
        self.assertEqual(self.eligible()[0]["requestable_amount"], "500.00")
        corrected = self.register("100.00", replaces=payment_id)
        self.assertEqual(corrected.status_code, 201, corrected.data)
        self.assertEqual(corrected.data["data"]["application_id"], app_id)
        allocated = self.offset(corrected.data["data"]["id"], [(payable, "100.00")])
        self.assertEqual(allocated.status_code, 201, allocated.data)
        self.assertEqual(self.eligible()[0]["requestable_amount"], "400.00")

    def test_independent_offset_does_not_make_the_same_usable_balance_available_to_two_applications(self):
        payable = self.confirmed(1, count=1)
        first = self.apply([(payable, "200.00")]).data["data"]["id"]
        second = self.apply([(payable, "300.00")]).data["data"]["id"]
        direct = self.register("250.00").data["data"]["id"]
        self.grant("finance", "view_supplierledger", "add_supplieroffset")
        result = self.offset(direct, [(payable, "250.00")])
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(self.register("200.00", application=first).status_code, 409)
        available = self.register("50.00", application=second)
        self.assertEqual(available.status_code, 201, available.data)
        self.assertEqual(self.register("0.01", application=second).status_code, 409)

    def test_independent_offset_preserves_the_amount_needed_for_already_registered_application_payment(self):
        payable = self.confirmed(1, count=1)
        application = self.apply([(payable, "300.00")]).data["data"]["id"]
        linked = self.register("300.00", application=application).data["data"]["id"]
        direct = self.register("300.00").data["data"]["id"]
        self.grant("finance", "view_supplierledger", "add_supplieroffset")
        options = self.get_data("offset-payables/", payment_id=direct)["data"]
        self.assertEqual([row["available_amount"] for row in options], ["200.00"])
        self.assertEqual(self.offset(direct, [(payable, "200.01")]).status_code, 409)
        self.assertEqual(self.offset(direct, [(payable, "200.00")]).status_code, 201)
        self.assertEqual(self.offset(linked, [(payable, "300.00")]).status_code, 201)
        self.assertEqual(self.eligible(), [])

    def test_independent_menu_view_and_business_actions(self):
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get(self.payments).status_code, 403)
        self.assertEqual(self.client.get(self.applications).status_code, 403)
        role = RoleProfile.objects.create(role_code="SUPPLIER_PAYMENT_CASHIER", display_name="付款出纳",
                                          auth_group=Group.objects.create(name="supplier-payment-cashier"))
        EmployeeRoleAssignment.objects.create(employee=self.cashier.employee_profile, role_profile=role, effective_from=timezone.now())
        for code in ("view_supplierpayment", "add_supplierpayment"):
            permission = Permission.objects.get(content_type__app_label="finance", codename=code)
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            role.auth_group.permissions.add(permission)
        self.assertEqual(self.client.get(self.payments).status_code, 200)
        self.assertEqual(self.client.get(self.applications).status_code, 200)
        self.assertEqual(self.client.get(self.payments + "payment-options/").status_code, 200)
        self.assertEqual(self.client.post(self.applications, {}).status_code, 403)
        self.assertEqual(self.client.get(self.applications + "eligible-payables/", {"supplier_id": self.supplier.pk}).status_code, 403)
        self.assertEqual(self.client.get(self.root).status_code, 403)
