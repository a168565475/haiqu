"""单元四独占页面验收入口；不代替真实企业微信 OAuth 验收。"""
import json
import os
from pathlib import Path
import secrets
import time
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.models import WeComBinding, WeComConfig
from apps.wecom.selectors import waiting_for_role


TEST_DATABASE = "test_haiqu_employee_login_u4_20261021_a15c89"
TEST_PERMISSION = "reference_data.view_referencedictionary"


@skipUnless(os.environ.get("WECOM_LOGIN_U4_BROWSER") == "1", "仅显式启用的单元四独占页面验收使用此入口。")
@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "0.0.0.0", "testserver"],
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:18595"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18595"],
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    SESSION_COOKIE_DOMAIN=None, CSRF_COOKIE_DOMAIN=None,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComLoginAuthorizationBrowserTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 8000

    def test_serve_login_authorization_browser_fixture(self):
        self.assertEqual(connection.settings_dict["NAME"], TEST_DATABASE)
        control = Path("/qa-control").resolve()
        self.assertTrue(control.is_dir(), "请挂载本任务登记的 control 目录。")
        ready_path, finished_path = control / "ready.json", control / "finished"
        self.assertFalse(ready_path.exists(), "ready.json 已存在，须先核对归属。")
        self.assertFalse(finished_path.exists(), "finished 已存在，须先核对归属。")
        self.assertTrue(Permission.objects.filter(
            content_type__app_label="reference_data", codename="view_referencedictionary",
        ).exists())
        password = secrets.token_urlsafe(28)
        admin = get_user_model().objects.create_superuser("admin", "", password)
        Employee.objects.create(user=admin, employee_code="QA_LOGIN_U4_ADMIN", display_name="单元四隔离管理员")
        account = get_user_model().objects.create_user("wecom_login_u4_existing", password=password)
        employee = Employee.objects.create(user=account, employee_code="QA_LOGIN_U4_EXISTING", display_name="单元四隔离员工")
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="ERP_ROLE:QA_LOGIN_U4"),
            role_code="QA_LOGIN_U4", display_name="单元四隔离授权角色",
        )
        config = WeComConfig.objects.create(enabled=False)
        binding = WeComBinding.objects.create(
            corp_id=config.corp_id, user_id="isolated.unit4.member", member_name=employee.display_name,
            employee=employee, source="MANUAL", created_account=False,
        )
        self.assertTrue(waiting_for_role(account))
        self.assertFalse(role.action_grants.exists() or role.auth_group.permissions.exists())
        self.assertFalse(config.secret_ciphertext or config.callback_token_ciphertext or config.callback_aes_key_ciphertext)
        initial_counts = {"employees": Employee.objects.count(), "accounts": get_user_model().objects.count(),
                          "bindings": WeComBinding.objects.count()}
        initial_password = account.password
        run_id = str(uuid4())
        ready_created = False
        # 客户端构造及标准库 HTTP 出站均禁止；浏览器仅使用独占库的真实 Session/CSRF/API。
        with patch("apps.wecom.client.WeComClient.__init__", side_effect=AssertionError("页面验收禁止企业微信外呼。")) as upstream, \
             patch("http.client.HTTPConnection.request", side_effect=AssertionError("页面验收禁止后端出站请求。")) as outbound:
            try:
                with ready_path.open("x", encoding="utf-8") as stream:
                    ready_created = True
                    json.dump({
                        "run_id": run_id, "database": TEST_DATABASE, "expires_at": time.time() + 600,
                        "web_origin": "http://127.0.0.1:18595", "backend_origin": "http://127.0.0.1:18594",
                        "accounts": {"admin": {"username": admin.username, "password": password},
                                     "employee": {"username": account.username, "password": password}},
                        "target": {
                            "employee_id": str(employee.pk), "account_id": account.pk,
                            "employee_etag": etag_for_instance(employee), "role_id": str(role.pk),
                            "role_etag": etag_for_instance(role), "permission": TEST_PERMISSION,
                            "employee_roles_path": f"/api/v1/access/employees/{employee.pk}/roles/",
                            "role_grants_path": f"/api/v1/access/roles/{role.pk}/grants/",
                            "business_path": "/api/v1/reference-data/dictionary-items/",
                        },
                    }, stream, ensure_ascii=False)
                deadline = time.monotonic() + 600
                while not finished_path.is_file():
                    if time.monotonic() >= deadline:
                        self.fail("单元四页面验收等待 finished 超过 600 秒；未视为通过。")
                    time.sleep(0.25)
                self.assertFalse(finished_path.is_symlink())
                result = json.loads(finished_path.read_text(encoding="utf-8"))
                self.assertEqual(result.get("run_id"), run_id)
                self.assertEqual(result.get("database"), TEST_DATABASE)
                self.assertIs(result.get("passed"), True, "页面脚本失败；请读取脱敏 page_checks.json。")
                self.assertGreater(result.get("checks", 0), 0)
                upstream.assert_not_called()
                outbound.assert_not_called()
                self.assertEqual(Employee.objects.count(), initial_counts["employees"])
                self.assertEqual(get_user_model().objects.count(), initial_counts["accounts"])
                self.assertEqual(WeComBinding.objects.count(), initial_counts["bindings"])
                self.assertEqual(EmployeeRoleAssignment.objects.filter(
                    employee=employee, role_profile=role, effective_to__isnull=True,
                ).count(), 1)
                self.assertFalse(role.action_grants.exists() or role.auth_group.permissions.exists())
                self.assertTrue(waiting_for_role(account))
                binding.refresh_from_db()
                employee.refresh_from_db()
                account.refresh_from_db()
                self.assertFalse(binding.created_account)
                self.assertEqual(binding.employee_id, employee.pk)
                self.assertEqual(employee.user_id, account.pk)
                self.assertEqual(account.password, initial_password)
                self.assertEqual(AuditLog.objects.filter(action="EMPLOYEE_ROLES_REPLACE", object_id=employee.pk).count(), 1)
                self.assertEqual(AuditLog.objects.filter(action="ROLE_GRANTS_REPLACE", object_id=role.pk).count(), 2)
            finally:
                if ready_created:
                    for resource in (ready_path, finished_path):
                        if resource.exists():
                            self.assertFalse(resource.is_symlink(), "控制文件变为符号链接，停止删除。")
                            self.assertEqual(resource.resolve().parent, control)
                            resource.unlink()
