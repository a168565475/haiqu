"""单元六独占数据库的真实员工页面验收；不调用企业微信、不模拟接口响应。"""
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
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.organizations.models import (
    Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from apps.wecom.models import WeComBinding, WeComConfig


TEST_DATABASE = "test_haiqu_employee_menu_u6_20261021_a15c89"


@skipUnless(os.environ.get("EMPLOYEE_MENU_U6_BROWSER") == "1", "仅单元六独占库显式启用页面夹具。")
@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
    MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "0.0.0.0", "testserver"],
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:18599"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:18599"],
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SESSION_COOKIE_DOMAIN=None, CSRF_COOKIE_DOMAIN=None,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class EmployeeMenuBrowserTests(LiveServerTestCase):
    serialized_rollback = True
    host = "0.0.0.0"
    port = 8000

    def test_employee_menu_real_session_browser(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.settings_dict["NAME"], TEST_DATABASE)
        self.assertFalse(WeComConfig.objects.exists())
        control = Path("/qa-control").resolve()
        self.assertTrue(control.is_dir())
        ready_path, finished_path = control / "ready.json", control / "finished"
        self.assertFalse(ready_path.exists())
        self.assertFalse(finished_path.exists())
        password = secrets.token_urlsafe(28)
        accounts = {}
        for key, codes in (
            ("manager", ["access_control.manage_accounts", "organizations.manage_organization", "access_control.manage_access"]),
            ("accounts", ["access_control.manage_accounts"]),
            ("organization", ["organizations.manage_organization"]),
            ("attendance", ["attendance.view_attendance"]),
            ("wecom", ["access_control.manage_wecom"]),
            ("ordinary", ["reference_data.view_referencedictionary"]),
        ):
            user = get_user_model().objects.create_user(f"employee_u6_{key}", password=password)
            employee = Employee.objects.create(user=user, employee_code=f"QA_U6_{key.upper()}", display_name=f"隔离{key}")
            role = RoleProfile.objects.create(auth_group=Group.objects.create(name=f"ERP_ROLE:QA_U6_{key}"),
                                              role_code=f"QA_U6_{key.upper()}", display_name=f"隔离{key}")
            for code in codes:
                app, codename = code.split(".")
                permission = Permission.objects.get(content_type__app_label=app, codename=codename)
                role.auth_group.permissions.add(permission)
                RoleActionGrant.objects.create(role=role, permission=permission,
                                               scope="MODULE" if "manage_" in codename else "ALL")
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
            accounts[key] = {"username": user.username, "password": password, "id": user.pk}
        first = Employee.objects.create(employee_code="QA_U6_SOURCE_A", display_name="单元六同名员工")
        second = Employee.objects.create(employee_code="QA_U6_SOURCE_B", display_name=first.display_name)
        Employee.objects.create(employee_code="QA_U6_LEFT", display_name="单元六离职员工", status="LEFT")
        Employee.objects.create(employee_code="QA_U6_ARCHIVED", display_name="单元六归档员工", archived_at=timezone.now())
        root = OrganizationUnit.objects.get(unit_code="HAIQU")
        department = OrganizationUnit.objects.create(parent=root, unit_code="QA_U6_DEPARTMENT", unit_name="单元六验收部门")
        baseline = {model._meta.label: model.objects.count() for model in (
            Employee, get_user_model(), EmployeeRoleAssignment, WeComBinding, WeComConfig,
        )}
        run_id, ready_created = str(uuid4()), False
        with patch("apps.wecom.client.WeComClient.__init__", side_effect=AssertionError("验收禁止企业微信外呼")) as upstream, \
             patch("http.client.HTTPConnection.request", side_effect=AssertionError("验收禁止后端出站请求")) as outbound:
            try:
                with ready_path.open("x", encoding="utf-8") as stream:
                    ready_created = True
                    json.dump({"run_id": run_id, "database": TEST_DATABASE, "expires_at": time.time() + 900,
                               "web_origin": "http://127.0.0.1:18599", "backend_origin": "http://127.0.0.1:18598",
                               "accounts": accounts, "target": {
                                   "employee_id": str(first.pk), "employee_code": first.employee_code,
                                   "employee_name": first.display_name, "second_code": second.employee_code,
                                   "department_id": str(department.pk), "department_name": department.unit_name,
                               }}, stream, ensure_ascii=False)
                deadline = time.monotonic() + 900
                while not finished_path.is_file():
                    if time.monotonic() >= deadline:
                        self.fail("页面验收等待结束信号超过 900 秒；不视为通过。")
                    time.sleep(0.25)
                self.assertFalse(finished_path.is_symlink())
                result = json.loads(finished_path.read_text(encoding="utf-8"))
                self.assertEqual(result.get("run_id"), run_id)
                self.assertEqual(result.get("database"), TEST_DATABASE)
                self.assertIs(result.get("passed"), True)
                self.assertGreaterEqual(result.get("checks", 0), 20)
                upstream.assert_not_called()
                outbound.assert_not_called()
                for model in (Employee, get_user_model(), EmployeeRoleAssignment, WeComBinding, WeComConfig):
                    self.assertEqual(model.objects.count(), baseline[model._meta.label])
                assignment = EmployeeOrganizationAssignment.objects.get(employee=first, effective_to__isnull=True)
                self.assertEqual(assignment.organization_unit_id, department.pk)
                self.assertTrue(assignment.is_primary)
                self.assertEqual(assignment.position_title, "单元六验收岗位")
                self.assertFalse(second.organization_assignments.exists())
                first.refresh_from_db()
                self.assertIsNone(first.user_id)
                self.assertEqual(first.display_name, "单元六同名员工")
                self.assertFalse(first.role_assignments.exists())
                self.assertEqual(AuditLog.objects.filter(action="EMPLOYEE_DEPARTMENTS_REPLACE", object_id=first.pk).count(), 1)
            finally:
                if ready_created:
                    for resource in (ready_path, finished_path):
                        if resource.exists():
                            self.assertFalse(resource.is_symlink())
                            self.assertEqual(resource.resolve().parent, control)
                            resource.unlink()
