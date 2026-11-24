import json
import os
import secrets
import time
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.finance.models import FinanceAccount
from apps.organizations.models import Employee, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from . import test_supplier_settlements as settlement_fixtures
from .test_supplier_ledger import SupplierLedgerFixture


QA_DATABASE = "test_supplier_payment_u02_browser_20261119"
CONTROL = Path("/run/supplier-payment-u02")


@skipUnless(os.getenv("SUPPLIER_PAYMENT_BROWSER") == "1", "仅供供应商付款独占页面验收")
@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18774"],
    MODULE_ACCESS_ENABLED=True,
    SALES_ACCESS_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
)
class SupplierPaymentBrowserTests(SupplierLedgerFixture, LiveServerTestCase):
    client_class = APIClient
    host = "0.0.0.0"
    port = 18773
    confirmed = settlement_fixtures.SupplierSettlementTests.confirmed

    def cashier_role(self):
        group = Group.objects.create(name="qa-supplier-payment-cashier")
        role = RoleProfile.objects.create(role_code="QA_SUPPLIER_PAYMENT_CASHIER", display_name="隔离出纳", auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=self.cashier.employee_profile, role_profile=role, effective_from=timezone.now())
        for code in ("view_supplierpayment", "add_supplierpayment"):
            permission = Permission.objects.get(content_type__app_label="finance", codename=code)
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            group.permissions.add(permission)

    def test_ordinary_finance_and_cashier_complete_shared_payment_flow(self):
        self.assertEqual(connection.settings_dict["NAME"], QA_DATABASE)
        ready, done = CONTROL / "ready.json", CONTROL / "done.json"
        self.assertTrue(CONTROL.is_dir() and not (ready.exists() or done.exists()))
        self.grant("finance", "view_supplierpayment", "add_supplierpaymentapplication", "withdraw_supplierpaymentapplication",
                   "view_supplierledger", "add_supplieroffset", "view_purchasepayable", "change_purchasepayable",
                   "confirm_purchasepayable")
        self.cashier_role()
        other = get_user_model().objects.create_user("qa_supplier_payment_no_access")
        Employee.objects.create(user=other, employee_code="QA_SUPPLIER_PAYMENT_NO_ACCESS", display_name="隔离无付款权限员工")
        self.supplier.supplier_name = "隔离验收用华东材料制造与供应有限公司"
        self.supplier.save(update_fields=["supplier_name"])
        department = OrganizationUnit.objects.create(unit_code="QA_PAYMENT_FINANCE", unit_name="隔离财务部")
        self.employee.organization_assignments.create(organization_unit=department, is_primary=True, effective_from=timezone.now())
        first = self.confirmed(1, day=date(2026, 8, 12), count=1)
        second = self.confirmed(2, day=date(2026, 8, 20), count=1)
        self.confirmed(3, day=date(2026, 9, 1), count=1)
        self.receive(4)
        FinanceAccount.objects.create(
            account_type="银行", code="QA-SUPPLIER-PAYMENT", category="基本户", name="隔离公司付款账户",
            account_number="000009", currency=self.currency, created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        identities = {}
        for label, user in (("finance", self.user), ("cashier", self.cashier), ("viewer", other)):
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            user.save(update_fields=["password"])
            identities[label] = {"username": user.username, "password": password}
        today = timezone.localdate()
        try:
            ready.write_text(json.dumps({
                "database": QA_DATABASE, "identities": identities, "today": today.isoformat(),
                "supplier_name": self.supplier.supplier_name, "supplier_id": str(self.supplier.pk), "payable_number": first.number,
                "race_payable_id": str(second.pk),
            }), encoding="utf-8")
            deadline = time.monotonic() + 300
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), "等待供应商付款页面验收超时")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8"))["passed"], "供应商付款页面验收失败")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
