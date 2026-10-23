"""U04独占库页面夹具；合成普通身份正常密码登录，不是主库真实员工验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.finance.models import FinanceAccount
from apps.organizations.models import Employee
from .receipt_fixtures import ReceiptFixtureMixin, grant_receipts
from .test_statements import create_source, request_body


@skipUnless(os.getenv("FINANCE_U04_BROWSER") == "1", "仅U04独占浏览器验证启用")
@override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18752"],
    CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u04-" + key}
        for key in ("default", "configuration", "wecom")})
class ReceiptBrowserTests(ReceiptFixtureMixin, LiveServerTestCase):
    host = "0.0.0.0"
    port = 18751

    def test_browser_session(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_finance_u04_20261023")
        control = Path("/app/_tmp/finance_u04_20261023")
        ready, done = control / "browser-ready.json", control / "browser-done.json"
        password = secrets.token_urlsafe(24); self.user.set_password(password); self.user.save()
        self.client.force_login(self.user)
        identities = [{"role": "FINANCE", "username": self.user.username, "password": password}]
        for code in ("CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER", "NO_FINANCE"):
            password = secrets.token_urlsafe(24)
            user = get_user_model().objects.create_user("u04_" + code.lower(), password=password)
            employee = Employee.objects.create(user=user, employee_code="U04_" + code, display_name="隔离页面 " + code)
            if code != "NO_FINANCE": grant_receipts(employee, code)
            identities.append({"role": code, "username": user.username, "password": password})
        for index in range(22):
            FinanceAccount.objects.create(account_type="银行账户", code=f"U04_{index:03}", category="基本户", name=f"隔离账户 {index:03}",
                account_number=f"00000000000000000{index:03}", currency=self.task.currency,
                created_by_employee=self.actor, updated_by_employee=self.actor)
        other_task = create_source(self.actor, quantities=(1,), prices=("1000.0000",))
        other = self.client.post("/api/v1/finance/statements/", request_body(other_task), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(other.status_code, 201, other.data)
        try:
            ready.write_text(json.dumps({"isolated": True, "database": connection.settings_dict["NAME"], "identities": identities,
                "statement_id": str(self.statement.pk), "statement_number": self.statement.number, "task_id": str(self.task.pk),
                "task_number": self.task.task_number, "other_statement_id": other.data["data"]["id"],
                "account_id": str(self.account.pk), "account_number": self.account.account_number}), encoding="utf-8")
            deadline = time.monotonic() + 1800
            while not done.exists() and time.monotonic() < deadline: time.sleep(1)
            self.assertTrue(done.exists(), "页面验收超时，测试库仍按结束销毁")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8")).get("passed"), "页面验收失败，详见U04_browser证据")
        finally:
            ready.unlink(missing_ok=True); done.unlink(missing_ok=True)
