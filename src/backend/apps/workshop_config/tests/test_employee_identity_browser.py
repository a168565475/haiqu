"""单元五独占 PostgreSQL 页面夹具；真实浏览器通过 Session/CSRF 访问 LiveServer。"""
import json
import os
from pathlib import Path
import secrets
import time
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.organizations.models import Employee, EmployeeRoleAssignment, EmployeeOrganizationAssignment, OrganizationUnit

from ..models import Workshop, WorkshopEmployee


TEST_DATABASE = "test_haiqu_employee_workshop_u5_20261021_a15c89"


@skipUnless(os.environ.get("WORKSHOP_EMPLOYEE_U5_BROWSER") == "1", "仅显式启用的单元五独占页面验收使用此入口。")
@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
    MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True, SALES_ACCESS_ENABLED=False,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "0.0.0.0", "testserver"],
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:18597"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18597"],
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    SESSION_COOKIE_DOMAIN=None, CSRF_COOKIE_DOMAIN=None,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WorkshopEmployeeIdentityBrowserTests(LiveServerTestCase):
    serialized_rollback = True
    host = "0.0.0.0"
    port = 8000

    def test_serve_employee_identity_browser_fixture(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.settings_dict["NAME"], TEST_DATABASE)
        control = Path("/qa-control").resolve()
        self.assertTrue(control.is_dir(), "请挂载单元五登记的 control 目录。")
        ready_path, finished_path = control / "ready.json", control / "finished"
        self.assertFalse(ready_path.exists(), "ready.json 已存在，须先核对归属。")
        self.assertFalse(finished_path.exists(), "finished 已存在，须先核对归属。")
        permissions = Permission.objects.filter(content_type__app_label="workshop_config", codename__in=[
            "view_workshopemployee", "add_workshopemployee", "change_workshopemployee",
        ])
        self.assertEqual(permissions.count(), 3)
        password = secrets.token_urlsafe(28)
        accounts = {}
        for key, codes in (
            ("manager", ["view_workshopemployee", "add_workshopemployee", "change_workshopemployee"]),
            ("reader", ["view_workshopemployee"]),
        ):
            user = get_user_model().objects.create_user(f"workshop_u5_{key}", password=password)
            user.user_permissions.set(permissions.filter(codename__in=codes))
            Employee.objects.create(user=user, employee_code=f"QA_U5_{key.upper()}", display_name=f"单元五隔离{key}")
            accounts[key] = {"username": user.username, "password": password, "id": user.pk}
        first = Employee.objects.create(employee_code="QA_U5_SOURCE_A", display_name="单元五同名员工")
        second = Employee.objects.create(employee_code="QA_U5_SOURCE_B", display_name=first.display_name)
        production, _ = OrganizationUnit.objects.get_or_create(unit_code="DEPT_PRODUCTION", defaults={"unit_name": "生产部"})
        for source in (first, second):
            EmployeeOrganizationAssignment.objects.create(employee=source, organization_unit=production, effective_from=timezone.now())
        workshop = Workshop.objects.get(name="装配车间")
        legacy = WorkshopEmployee.objects.create(
            workshop=workshop, position="单元五历史岗位", name="单元五历史姓名", is_supervisor=False,
        )
        baseline = {"employees": Employee.objects.count(), "accounts": get_user_model().objects.count(),
                    "roles": EmployeeRoleAssignment.objects.count(), "workshop_employees": WorkshopEmployee.objects.count()}
        run_id, ready_created = str(uuid4()), False
        # 拒绝后端外呼，不替换任何浏览器或业务接口响应。
        with patch("apps.wecom.client.WeComClient.__init__", side_effect=AssertionError("单元五页面验收禁止企业微信外呼。")) as upstream, \
             patch("http.client.HTTPConnection.request", side_effect=AssertionError("单元五页面验收禁止后端出站请求。")) as outbound:
            try:
                with ready_path.open("x", encoding="utf-8") as stream:
                    ready_created = True
                    json.dump({
                        "run_id": run_id, "database": TEST_DATABASE, "expires_at": time.time() + 600,
                        "web_origin": "http://127.0.0.1:18597", "backend_origin": "http://127.0.0.1:18596",
                        "accounts": accounts,
                        "target": {
                            "workshop_id": str(workshop.pk), "workshop_name": workshop.name,
                            "first": {"id": str(first.pk), "code": first.employee_code, "name": first.display_name},
                            "second": {"id": str(second.pk), "code": second.employee_code, "name": second.display_name},
                            "legacy_id": str(legacy.pk), "legacy_name": legacy.name,
                            "new_position": "单元五新增岗位",
                        },
                    }, stream, ensure_ascii=False)
                deadline = time.monotonic() + 600
                while not finished_path.is_file():
                    if time.monotonic() >= deadline:
                        self.fail("单元五页面验收等待 finished 超过 600 秒；未视为通过。")
                    time.sleep(0.25)
                self.assertFalse(finished_path.is_symlink())
                result = json.loads(finished_path.read_text(encoding="utf-8"))
                self.assertEqual(result.get("run_id"), run_id)
                self.assertEqual(result.get("database"), TEST_DATABASE)
                self.assertIs(result.get("passed"), True, "页面脚本失败；请读取脱敏 page_checks.json。")
                self.assertGreaterEqual(result.get("checks", 0), 15)
                upstream.assert_not_called()
                outbound.assert_not_called()
                self.assertEqual(Employee.objects.count(), baseline["employees"])
                self.assertEqual(get_user_model().objects.count(), baseline["accounts"])
                self.assertEqual(EmployeeRoleAssignment.objects.count(), baseline["roles"])
                self.assertEqual(WorkshopEmployee.objects.count(), baseline["workshop_employees"] + 1)
                first.refresh_from_db()
                second.refresh_from_db()
                legacy.refresh_from_db()
                self.assertIsNone(first.user_id)
                self.assertIsNone(second.user_id)
                self.assertEqual((first.status, second.status), ("ACTIVE", "ACTIVE"))
                self.assertEqual(legacy.employee_id, second.pk)
                self.assertEqual(legacy.name, "单元五历史姓名")
                self.assertEqual(legacy.position, "单元五历史岗位")
                created = WorkshopEmployee.objects.get(employee=first, position="单元五新增岗位")
                self.assertEqual(created.workshop_id, workshop.pk)
                self.assertEqual(created.name, first.display_name)
                self.assertTrue(created.is_supervisor)
                self.assertEqual(created.status, "ACTIVE")
            finally:
                if ready_created:
                    for resource in (ready_path, finished_path):
                        if resource.exists():
                            self.assertFalse(resource.is_symlink(), "控制文件变为符号链接，停止删除。")
                            self.assertEqual(resource.resolve().parent, control)
                            resource.unlink()
