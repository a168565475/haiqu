"""仅显式启用的隔离数据库页面测试夹具；不连接主业务库、不替代真实员工验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.organizations.models import Employee
from apps.finance.models import FinanceAccount
from .test_accounts import currency, grant


@skipUnless(os.getenv("FINANCE_U01_BROWSER") == "1", "仅在U01独占浏览器验证时启用")
@override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18746"],
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u01-" + key}
            for key in ("default", "configuration", "wecom")})
class AccountBrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 18745

    def test_browser_session(self):
        if connection.settings_dict["NAME"] != "test_finance_u01_01a167cb":
            self.fail("浏览器测试必须在登记的独占测试库执行")
        folder = Path("/app/_tmp/finance_u01_01a167cb")
        folder.mkdir(parents=True, exist_ok=True)
        ready = folder / "browser-ready.json"
        done = folder / "browser-done.json"
        identities = []
        for code in ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER", "NO_FINANCE"):
            password = secrets.token_urlsafe(24)
            user = get_user_model().objects.create_user("u01_" + code.lower(), password=password)
            employee = Employee.objects.create(user=user, employee_code="U01_" + code, display_name="隔离页面 " + code)
            if code != "NO_FINANCE":
                grant(employee, code)
            identities.append({"role": code, "username": user.username, "password": password})
        actor = Employee.objects.get(employee_code="U01_FINANCE")
        for index in range(23):
            FinanceAccount.objects.create(code=f"QA-U01-{index:03}", account_type="银行账户", category="基本户",
                name=f"隔离合成账户 {index:03}", account_number=f"0000000000000000{index:03}", currency=currency("USD" if index == 1 else "CNY"),
                status="INACTIVE" if index == 2 else "ACTIVE", created_by_employee=actor, updated_by_employee=actor)
        try:
            ready.write_text(json.dumps({"isolated": True, "identities": identities}), encoding="utf-8")
            deadline = time.monotonic() + 900
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(1)
            self.assertTrue(done.exists(), "浏览器验证超时，独占测试库仍按测试结束销毁")
            result = json.loads(done.read_text(encoding="utf-8"))
            self.assertTrue(result.get("passed"), "浏览器检查未通过，详见脱敏页面报告")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
