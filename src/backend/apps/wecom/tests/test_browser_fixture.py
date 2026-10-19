"""隔离浏览器集成测试入口；不代表真实企业微信身份链路验收。"""

import json
import os
from pathlib import Path
import time
from unittest import skipUnless
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import LiveServerTestCase, override_settings

from apps.core.audit import write_audit_log
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.models import WeComBinding, WeComConfig
from apps.wecom.selectors import waiting_for_role


@skipUnless(os.environ.get("WECOM_BROWSER_QA") == "1", "仅显式启用的独占浏览器测试使用此入口。")
@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True,
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()],
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "0.0.0.0", "testserver"],
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:8080", "http://127.0.0.1:18591"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:8080", "http://127.0.0.1:18591"],
)
class WeComBrowserFixtureTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 8000

    def test_serve_isolated_browser_fixture(self):
        # 此库已由主任务登记；防止错误的运行配置向其他数据库写入测试账号。
        self.assertEqual(connection.settings_dict["NAME"], "test_haiqu_wecom_page_20261019_01a1519b")
        control = Path("/qa-control").resolve()
        self.assertTrue(control.is_dir(), "请先挂载本任务已登记的 /qa-control 控制目录。")
        ready_path, finished_path = control / "ready.json", control / "finished"
        self.assertFalse(ready_path.exists(), "ready.json 已存在，必须先核对上次资源归属。")
        self.assertFalse(finished_path.exists(), "finished 已存在，必须先核对上次资源归属。")

        password = "WeComQaOnly-2026!"
        admin = get_user_model().objects.create_superuser("admin", "", password)
        admin_employee = Employee.objects.create(user=admin, employee_code="QA_WECOM_ADMIN", display_name="隔离测试管理员")
        waiting_user = get_user_model().objects.create_user("wecom_qa_waiting", password=password)
        waiting_employee = Employee.objects.create(user=waiting_user, employee_code="QA_WECOM_WAITING", display_name="隔离测试待授权员工")
        # 仅用于隔离页面测试的分页前置记录；不得导入业务库或冒充通讯录同步。
        for index in range(16):
            Employee.objects.create(employee_code=f"QA_WECOM_PAGE_{index + 1:02d}", display_name=f"隔离分页员工 {index + 1:02d}")
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="ERP_ROLE:QA_WECOM_EMPTY"),
            role_code="QA_WECOM_EMPTY", display_name="隔离验收空权限角色",
            description="仅用于独占测试库的角色入口验收，不包含业务操作授权。",
        )
        config = WeComConfig.objects.create(enabled=False)
        binding = WeComBinding.objects.create(
            corp_id=config.corp_id, user_id="isolated.qa.member", member_name="隔离测试成员",
            employee=waiting_employee, source="AUTO", created_account=True,
        )
        write_audit_log(
            object_type="WECOM", object_id=binding.pk, action="BROWSER_FIXTURE", actor_employee=admin_employee,
            after_data={"user_id": binding.user_id, "employee_name": waiting_employee.display_name,
                        "result": "SUCCESS", "message": "隔离浏览器集成测试数据，不是真实企业微信身份。"},
        )
        self.assertTrue(waiting_for_role(waiting_user))
        self.assertFalse(role.action_grants.exists() or role.auth_group.permissions.exists())
        self.assertFalse(config.secret_ciphertext or config.callback_token_ciphertext or config.callback_aes_key_ciphertext)
        initial_counts = {"employees": Employee.objects.count(), "accounts": get_user_model().objects.count(), "bindings": WeComBinding.objects.count()}

        ready_created = False
        # 浏览器使用真实测试库、Session/CSRF/API；任何企微客户端构造均使本测试失败，禁止真实外呼。
        with patch("apps.wecom.services.WeComClient", side_effect=AssertionError("隔离浏览器测试禁止调用真实企业微信。")) as upstream:
            try:
                with ready_path.open("x", encoding="utf-8") as ready_file:
                    ready_created = True
                    json.dump({"port": self.port, "accounts": {
                        "admin": {"username": admin.username, "password": password},
                        "waiting": {"username": waiting_user.username, "password": password},
                    }, "role_entry": {
                        "employee_id": str(waiting_employee.pk), "employee_code": waiting_employee.employee_code,
                        "employee_name": waiting_employee.display_name, "account_id": waiting_user.pk,
                        "binding_id": str(binding.pk), "wecom_user_id": binding.user_id,
                        "role_id": str(role.pk), "role_name": role.display_name, "initial_counts": initial_counts,
                    }}, ready_file, ensure_ascii=False)
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    if finished_path.is_file():
                        break
                    time.sleep(0.25)
                else:
                    self.fail("隔离浏览器测试等待 finished 超过 300 秒；未视为验收通过。")
                upstream.assert_not_called()
                self.assertEqual(Employee.objects.count(), initial_counts["employees"])
                self.assertEqual(get_user_model().objects.count(), initial_counts["accounts"])
                self.assertEqual(WeComBinding.objects.count(), initial_counts["bindings"])
                self.assertEqual(EmployeeRoleAssignment.objects.filter(employee=waiting_employee, role_profile=role, effective_to__isnull=True).count(), 1)
                self.assertFalse(waiting_for_role(waiting_user))
                self.assertFalse(role.action_grants.exists() or role.auth_group.permissions.exists())
                binding.refresh_from_db()
                self.assertEqual(binding.employee_id, waiting_employee.pk)
                waiting_employee.refresh_from_db()
                self.assertEqual(waiting_employee.user_id, waiting_user.pk)
            finally:
                if ready_created:
                    for path in (ready_path, finished_path):
                        if path.exists():
                            self.assertFalse(path.is_symlink(), "控制文件变为符号链接，停止该资源清理。")
                            self.assertEqual(path.resolve().parent, control)
                            path.unlink()
