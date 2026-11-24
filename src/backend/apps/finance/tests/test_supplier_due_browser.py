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
from apps.finance.supplier_payment_application_models import SupplierPaymentApplication
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.procurement.models import SupplierPaymentTerm

from . import test_supplier_settlements as settlement_fixtures
from .test_supplier_ledger import SupplierLedgerFixture


QA_DATABASE = "test_due_browser_01a1f204"
CONTROL = Path("/run/supplier-due-qa")


@skipUnless(os.getenv("SUPPLIER_DUE_BROWSER") == "1", "仅供供应商到期货款隔离页面验收")
@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18854"],
    MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
)
class SupplierDueBrowserTests(SupplierLedgerFixture, LiveServerTestCase):
    client_class = APIClient
    host = "0.0.0.0"
    port = 18853
    confirmed = settlement_fixtures.SupplierSettlementTests.confirmed

    def grant_browser_role(self, user, code, app, codenames):
        group = Group.objects.create(name=code)
        role = RoleProfile.objects.create(role_code=code, display_name=code, auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=user.employee_profile, role_profile=role, effective_from=timezone.now())
        permissions = Permission.objects.filter(content_type__app_label=app, codename__in=codenames)
        self.assertEqual(permissions.count(), len(codenames))
        for permission in permissions:
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            group.permissions.add(permission)

    def test_procurement_finance_and_readonly_roles(self):
        self.assertEqual(connection.settings_dict["NAME"], QA_DATABASE)
        ready, done = CONTROL / "ready.json", CONTROL / "done.json"
        self.assertTrue(CONTROL.is_dir() and not (ready.exists() or done.exists()))
        procurement = get_user_model().objects.create_user("qa_supplier_due_procurement")
        buyer = Employee.objects.create(user=procurement, employee_code="DUE_QA_BUYER", display_name="隔离采购员")
        self.grant_browser_role(procurement, "QA_DUE_PROCUREMENT", "procurement", ["view_supplier", "change_supplier"])
        self.grant_browser_role(self.cashier, "QA_DUE_READ_ONLY", "finance", ["view_supplierpayment"])
        self.grant("finance", "view_supplierpayment", "add_supplierpaymentapplication", "view_purchasepayable",
                   "change_purchasepayable", "confirm_purchasepayable", "view_supplierledger")

        self.supplier.supplier_name = "隔离验收用华东金属五金材料加工与供应有限公司"
        self.supplier.payment_cycle = "MONTHLY"
        self.supplier.save(update_fields=["supplier_name", "payment_cycle"])
        unknown = self.confirmed(1, day=date(2026, 8, 31), count=1)
        SupplierPaymentTerm.objects.create(
            supplier=self.supplier, months=1, effective_month=date(2026, 9, 1),
            basis="隔离协议第一版", recorded_by_employee=buyer,
        )
        self.confirmed(2, day=date(2026, 9, 30), count=1)
        current = self.confirmed(3, day=date(2026, 10, 31), count=1)
        self.confirmed(4, day=date(2026, 11, 1), count=1)

        identities = {}
        for label, user in (("procurement", procurement), ("finance", self.user), ("viewer", self.cashier)):
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            user.save(update_fields=["password"])
            identities[label] = {"username": user.username, "password": password}
        try:
            ready.write_text(json.dumps({
                "database": QA_DATABASE, "identities": identities, "today": timezone.localdate().isoformat(),
                "supplier_name": self.supplier.supplier_name, "supplier_id": str(self.supplier.pk),
                "payable_id": str(current.pk), "payable_number": current.number, "unknown_number": unknown.number,
            }), encoding="utf-8")
            deadline = time.monotonic() + 300
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), "等待到期货款页面验收超时")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8"))["passed"], "到期货款页面验收失败")
            application = SupplierPaymentApplication.objects.get(supplier=self.supplier)
            self.assertEqual(application.lines.get().payable_id, current.pk)
            self.assertEqual(str(application.amount), "100.00")
            self.assertEqual(list(self.supplier.payment_term_versions.values_list("months", flat=True)), [3, 1])
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
