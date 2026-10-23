"""显式启用的隔离页面夹具；不用管理员会话，不访问主业务库。"""
import json
import os
import secrets
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.access_control.models import RoleActionGrant
from .goods_test_support import GoodsFixture


@skipUnless(os.environ.get("FINANCE_U05_BROWSER") == "1", "仅U05独占隔离页面检查启用")
@override_settings(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18754"],
    CACHES={name: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "finance-u05-" + name}
        for name in ("default", "configuration", "wecom")})
class GoodsBrowserTests(GoodsFixture, LiveServerTestCase):
    host = "0.0.0.0"
    port = 18753

    def test_browser_session(self):
        self.assertEqual(connection.settings_dict["NAME"], "test_finance_u05_01a16836")
        folder = Path("/app/_tmp/finance_u05_01a16836")
        self.assertTrue(folder.is_dir(), "必须先登记并创建本单元临时根")
        role = self.grant()
        permission = Permission.objects.get(content_type__app_label="finance", codename="view_financeaccount")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.add(permission)
        password = secrets.token_urlsafe(24)
        self.user.set_password(password)
        self.user.save(update_fields=["password"])
        deposit = self.create(kind="DEPOSIT", cash="200.00")
        pure = self.new_statement(amount="300.00")
        pure_deposit = self.create(statement=pure, kind="DEPOSIT", cash="300.00")
        many = self.new_statement(amount="10000.00")
        for _ in range(23):
            self.create(statement=many, kind="DEPOSIT", cash="10.00")
        empty = self.new_statement()
        ready, done = folder / "browser-ready.json", folder / "browser-done.json"
        self.assertFalse(ready.exists() or done.exists(), "拒绝复用归属不明的浏览器控制文件")
        try:
            ready.write_text(json.dumps({"isolated": True, "database": connection.settings_dict["NAME"],
                "identity": {"username": self.user.username, "password": password},
                "statement_id": str(self.statement.pk), "deposit_id": str(deposit.pk), "deposit_number": deposit.number,
                "pure_statement_id": str(pure.pk), "pure_deposit_number": pure_deposit.number,
                "many_statement_id": str(many.pk), "empty_statement_id": str(empty.pk),
                "account_code": self.account.code, "account_number": self.account.account_number}), encoding="utf-8")
            deadline = time.monotonic() + 900
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(1)
            self.assertTrue(done.exists(), "页面检查超时，仍须销毁本单元测试库")
            self.assertTrue(json.loads(done.read_text(encoding="utf-8")).get("passed"), "页面检查未通过，见U05_browser报告")
        finally:
            ready.unlink(missing_ok=True)
            done.unlink(missing_ok=True)
