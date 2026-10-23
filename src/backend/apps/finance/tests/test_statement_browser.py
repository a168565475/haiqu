"""U03独占PostgreSQL/正常Session登录的页面夹具；仅合成身份，不替代真实员工验收。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.organizations.models import Employee
from apps.access_control.models import RoleActionGrant
from apps.reference_data.models import ProductionUnit
from .test_statements import create_source, grant_statements


@skipUnless(os.getenv("FINANCE_U03_BROWSER") == "1", "仅U03独占浏览器验证启用")
@override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18750"],
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    CACHES={key: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u03-" + key}
            for key in ("default", "configuration", "wecom")})
class StatementBrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 18749

    def test_browser_session(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_finance_u03_01a16836")
        folder = Path("/app/_tmp/finance_u03_01a16836")
        folder.mkdir(parents=True, exist_ok=True)
        ready, done = folder / "browser-ready.json", folder / "browser-done.json"
        identities = []
        for code in ("FINANCE", "CASHIER", "FACTORY_MANAGER", "GENERAL_MANAGER", "NO_FINANCE"):
            password = secrets.token_urlsafe(24)
            user = get_user_model().objects.create_user("u03_" + code.lower(), password=password)
            employee = Employee.objects.create(user=user, employee_code="U03_" + code, display_name="隔离页面 " + code)
            if code != "NO_FINANCE":
                role = grant_statements(employee, code)
                for permission in Permission.objects.filter(content_type__app_label="finance", codename__in=("view_receipt", "add_receipt", "view_financeaccount")):
                    role.auth_group.permissions.add(permission)
                    RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            identities.append({"role": code, "username": user.username, "password": password})
        actor = Employee.objects.get(employee_code="U03_FINANCE")
        task = create_source(actor, quantities=(60, 3, 3, 5) + (10,) * 27, prices=("61.0900", "0.3350", "0.3350", "4.0000") + ("2.0000",) * 27)
        other = create_source(actor)
        unit = ProductionUnit.objects.create(unit_code="U03_SET", unit_name="隔离套")
        task.products.filter(line_number=4).update(unit=unit)
        try:
            ready.write_text(json.dumps({"isolated": True, "database": connection.settings_dict["NAME"], "identities": identities,
                "task_id": str(task.pk), "task_number": task.task_number, "other_task_id": str(other.pk), "other_task_number": other.task_number}), encoding="utf-8")
            deadline = time.monotonic() + 1800
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(1)
            self.assertTrue(done.exists(), "浏览器验证超时，测试库仍按测试结束销毁")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8")).get("passed"), "页面检查失败，见U03_browser证据")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
