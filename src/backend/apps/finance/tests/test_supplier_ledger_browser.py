import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.finance.models import FinanceAccount
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from .test_supplier_ledger import SupplierLedgerFixture


if os.getenv("SUPPLIER_LEDGER_ACCEPTANCE_BROWSER") == "1":
    UNIT = 4
else:
    UNIT = 3 if os.getenv("SUPPLIER_LEDGER_SETTLEMENT_BROWSER") == "1" else 2
QA_ROOT = f"/app/_tmp/supplier-ledger-u0{UNIT}-20261119"
QA_DATABASE = f"test_supplier_ledger_u0{UNIT}_20261119"


@skipUnless(os.getenv("SUPPLIER_LEDGER_BROWSER") == "1", "仅用于供应商往来独占页面验收")
@override_settings(
    ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18764"],
    ACCESS_MANAGEMENT_ENABLED=True,
    MODULE_ACCESS_ENABLED=True,
    SALES_ACCESS_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
    CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": f"supplier-ledger-{key}"}
            for key in ("default", "configuration", "wecom")},
    MEDIA_ROOT=f"{QA_ROOT}/media",
)
class SupplierLedgerBrowserTests(SupplierLedgerFixture, LiveServerTestCase):
    client_class = APIClient
    host = "0.0.0.0"
    port = 18763

    def test_ordinary_role_read_only_page(self):
        self.assertEqual(connection.settings_dict["NAME"], QA_DATABASE)
        folder = Path(QA_ROOT)
        ready, done = folder / "ready.json", folder / "done.json"
        self.assertTrue(folder.is_dir() and not (ready.exists() or done.exists()))
        self.grant("finance", "view_supplierledger", "view_purchasepayable", "change_purchasepayable", "confirm_purchasepayable")
        self.grant("procurement", "view_purchaseorder")
        self.grant("inventory", "view_material_receipt")
        self.grant("production_tasks", "view_productiontask")
        confirmed, _, inbound = self.receive(1)
        pending, _, _ = self.receive(2, count=1)
        url, etag = self.price(confirmed)
        with patch("apps.finance.purchase_payable_services.timezone", wraps=timezone) as clock:
            clock.now.return_value = datetime(2026, 11, 2, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
            result = self.client.post(url + "confirm/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(result.status_code, 200, result.data)
        write_grants = RoleActionGrant.objects.filter(
            role=self.role, permission__codename__in=["change_purchasepayable", "confirm_purchasepayable"],
        )
        self.role.auth_group.permissions.remove(*write_grants.values_list("permission_id", flat=True))
        write_grants.delete()
        if UNIT >= 3:
            self.grant("finance", "add_supplieroffset", "void_supplieroffset", "void_supplierpayment")
            cashier_role = RoleProfile.objects.create(
                role_code="LEDGER_CASHIER_TEST", display_name="往来测试出纳",
                auth_group=Group.objects.create(name="ledger-cashier-test"),
            )
            for code in ("view_supplierledger", "add_supplierpayment"):
                permission = Permission.objects.get(content_type__app_label="finance", codename=code)
                RoleActionGrant.objects.create(role=cashier_role, permission=permission, scope="MODULE")
                cashier_role.auth_group.permissions.add(permission)
            EmployeeRoleAssignment.objects.create(
                employee=self.cashier.employee_profile, role_profile=cashier_role, effective_from=timezone.now(),
            )
            FinanceAccount.objects.create(
                account_type="银行", code="LEDGER-BROWSER", category="基本户", name="隔离付款账户", account_number="000003",
                currency=self.currency, created_by_employee=self.employee, updated_by_employee=self.employee,
            )
        identities = {}
        for label, user in (("finance", self.user), ("cashier", self.cashier)):
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            user.save(update_fields=["password"])
            identities[label] = {"username": user.username, "password": password}
        try:
            ready.write_text(json.dumps({
                "database": connection.settings_dict["NAME"], "identities": identities,
                "supplier_id": str(self.supplier.pk), "supplier_name": self.supplier.supplier_name,
                "inbound_number": inbound.inbound_number, "pending_number": pending.number,
                "confirmed_number": confirmed.number, "confirmed_id": str(confirmed.pk),
                "inbound_id": str(inbound.pk),
            }), encoding="utf-8")
            deadline = time.monotonic() + 360
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), "等待页面检查超时")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8"))["passed"], "页面检查失败")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
