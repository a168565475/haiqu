"""专属测试库的消息页面夹具；外部发送为明确模拟，不代表企微送达验收。"""

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
from django.utils import timezone

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom import models
from apps.wecom.credentials import encrypt_secret


@skipUnless(os.environ.get("WECOM_MESSAGE_BROWSER_QA") == "1", "仅显式启用的消息页面隔离测试。")
@override_settings(
    ACCESS_MANAGEMENT_ENABLED=True,
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()],
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "0.0.0.0", "testserver"],
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:8080", "http://127.0.0.1:18592"],
    CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:8080", "http://127.0.0.1:18592"],
)
class WeComMessageBrowserFixtureTests(LiveServerTestCase):
    host = "0.0.0.0"
    port = 8000

    def test_serve_isolated_message_fixture(self):
        from apps.wecom.client import WeComError, WeComSendUncertain

        database = "test_haiqu_wecom_messages_page_20261019_01a1519b"
        self.assertEqual(connection.settings_dict["NAME"], database)
        control = Path("/qa-control").resolve()
        self.assertTrue(control.is_dir(), "必须挂载本任务已登记的控制目录。")
        ready, finished = control / "ready.json", control / "finished"
        self.assertFalse(ready.exists() or finished.exists(), "控制文件已存在，须先核对资源归属。")
        password = os.environ.get("WECOM_MESSAGE_QA_PASSWORD", "")
        self.assertGreaterEqual(len(password), 24, "使用进程内临时测试密码，禁止写入报告或控制文件。")

        admin = get_user_model().objects.create_superuser("admin", "", password)
        actor = Employee.objects.create(user=admin, employee_code="QA_MSG_ADMIN", display_name="隔离消息管理员")
        member = get_user_model().objects.create_user("wecom_message_qa_member", password=password)
        employee = Employee.objects.create(user=member, employee_code="QA_MSG_MEMBER", display_name="隔离消息测试员工")
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="ERP_ROLE:QA_MSG_MEMBER"),
            role_code="QA_MSG_MEMBER", display_name="隔离空权限角色",
        )
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now(), assigned_by_employee=actor)
        config = models.WeComConfig.objects.create(
            corp_id="ww0000000000000000", agent_id="1", erp_origin="https://erp.example.invalid",
            enabled=True, secret_ciphertext=encrypt_secret("isolated-message-fixture-not-a-real-secret"),
        )
        binding = models.WeComBinding.objects.create(
            corp_id=config.corp_id, user_id="Isolated.Message.Member", member_name="隔离消息测试成员",
            employee=employee, source="AUTO", created_account=True,
        )
        self.assertFalse(models.WeComMessageTemplate.objects.exists())
        self.assertFalse(models.WeComMessageAttempt.objects.exists())
        self.assertFalse(role.action_grants.exists() or role.auth_group.permissions.exists())

        def isolated_send(user_id, body):
            self.assertEqual(user_id, binding.user_id)
            self.assertIn(employee.display_name, body)
            if "【隔离验收-受理】" in body:
                return {"msgid": "isolated-accepted-message"}
            if "【隔离验收-失败】" in body:
                raise WeComError("RECIPIENT_REJECTED", "隔离夹具模拟明确拒绝。")
            if "【隔离验收-未知】" in body:
                raise WeComSendUncertain()
            raise AssertionError("不在本次隔离发送场景内的内容。")

        ready_created = False
        with patch("apps.wecom.message_services.WeComClient.send_text", side_effect=isolated_send) as send, \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("隔离测试禁止真实外呼。")) as network:
            try:
                with ready.open("x", encoding="utf-8") as stream:
                    ready_created = True
                    json.dump({"kind": "wecom-message-isolated", "database": database, "port": self.port,
                        "accounts": {"admin": admin.username, "member": member.username},
                        "binding_id": str(binding.pk), "employee_name": employee.display_name,
                        "user_id": binding.user_id, "erp_origin": config.erp_origin}, stream, ensure_ascii=False)
                deadline = time.monotonic() + 360
                while time.monotonic() < deadline:
                    if finished.is_file():
                        break
                    time.sleep(0.25)
                else:
                    self.fail("页面验收未在 360 秒内结束；不视为通过。")
                self.assertEqual(finished.read_text(encoding="utf-8"), "PASS")
                network.assert_not_called()
                self.assertEqual(send.call_count, 3)
                self.assertEqual(models.WeComMessageTemplate.objects.count(), 1)
                self.assertCountEqual(models.WeComMessageAttempt.objects.values_list("status", flat=True),
                                      ["ACCEPTED", "FAILED", "UNCERTAIN"])
                self.assertEqual(models.WeComBinding.objects.count(), 1)
                self.assertEqual(Employee.objects.count(), 2)
                self.assertEqual(get_user_model().objects.count(), 2)
            finally:
                if ready_created:
                    for item in (ready, finished):
                        if item.exists():
                            self.assertFalse(item.is_symlink(), "控制文件变为链接，停止清理。")
                            self.assertEqual(item.resolve().parent, control)
                            item.unlink()
