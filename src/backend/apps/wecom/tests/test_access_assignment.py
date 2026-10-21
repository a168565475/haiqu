"""隔离数据库集成回归：仅企业微信官方接口使用 Mock，不代替真实企微验收。"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.access_control.selectors import current_assignments
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig


@override_settings(
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()],
    ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComAccessAssignmentTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "IsolatedRoleTest843!")
        self.admin_employee = Employee.objects.create(
            user=self.admin, employee_code="ACCESS_WECOM_ADMIN", display_name="隔离测试管理员",
        )
        self.role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="ERP_ROLE:WECOM_ASSIGNMENT_TEST"),
            role_code="WECOM_ASSIGNMENT_TEST", display_name="隔离测试空权限角色",
        )
        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("isolated-oauth-secret"))
        upstream = patch("apps.wecom.services.WeComClient", autospec=True)
        self.upstream = upstream.start().return_value
        self.addCleanup(upstream.stop)
        self.upstream.get_identity.return_value = {"userid": "Role.Test.Member", "corpid": config.corp_id}
        self.upstream.get_member.return_value = {"userid": "Role.Test.Member", "name": "隔离企微角色员工", "status": 1}
        self.member_client = APIClient(enforce_csrf_checks=True)
        self.admin_client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.admin_client.get("/api/auth/me/").status_code, 200)
        response = self.admin_client.post("/api/auth/login/", {
            "username": "admin", "password": "IsolatedRoleTest843!",
        }, format="json", HTTP_X_CSRFTOKEN=self.csrf_token())
        self.assertEqual(response.status_code, 200, response.data)

    def csrf_token(self):
        return self.admin_client.cookies[settings.CSRF_COOKIE_NAME].value

    def oauth_login(self, code):
        start = self.member_client.get("/api/auth/wecom/start/")
        self.assertEqual(start.status_code, 302)
        state = parse_qs(urlparse(start.url).query)["state"][0]
        response = self.member_client.get("/api/auth/wecom/callback/", {"state": state, "code": code})
        self.assertEqual(response.status_code, 302)
        return response

    def test_oauth_employee_can_be_found_and_assigned_without_replacing_the_session(self):
        Employee.objects.bulk_create([
            Employee(employee_code=f"ACCESS_WECOM_FILLER_{number:02d}", display_name=f"隔离分页员工{number}")
            for number in range(20)
        ])
        employee_count, user_count = Employee.objects.count(), get_user_model().objects.count()
        self.assertEqual(self.oauth_login("first-test-code").url, "/auth/waiting-role")
        binding = WeComBinding.objects.select_related("employee__user").get()
        employee, user = binding.employee, binding.employee.user
        self.assertEqual(Employee.objects.count(), employee_count + 1)
        self.assertEqual(get_user_model().objects.count(), user_count + 1)
        self.assertTrue(binding.created_account)
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee=employee).exists())
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="AUTO_CREATE").count(), 1)

        session_key = self.member_client.session.session_key
        before = self.member_client.get("/api/auth/me/").json()
        self.assertTrue(before["authenticated"])
        self.assertTrue(before["user"]["waiting_for_role"])
        self.assertEqual(before["user"]["employee"]["id"], str(employee.pk))
        first_page = self.admin_client.get("/api/v1/access/employees/", {"page_size": 20})
        self.assertEqual(first_page.status_code, 200)
        self.assertNotIn(str(employee.pk), [row["id"] for row in first_page.json()["data"]])
        second_page = self.admin_client.get("/api/v1/access/employees/", {"page_size": 20, "page": 2})
        self.assertEqual(second_page.status_code, 200)
        row = next(row for row in second_page.json()["data"] if row["id"] == str(employee.pk))
        self.assertEqual(row["username"], user.username)
        self.assertEqual(row["role_ids"], [])
        assigned = self.admin_client.put(f"/api/v1/access/employees/{employee.pk}/roles/", {
            "role_ids": [str(self.role.pk)],
        }, format="json", HTTP_IF_MATCH=row["etag"], HTTP_X_CSRFTOKEN=self.csrf_token())
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(assigned.json()["role_ids"], [str(self.role.pk)])
        assignment = current_assignments(employee).get()
        self.assertEqual(assignment.role_profile_id, self.role.pk)
        self.assertEqual(assignment.assigned_by_employee_id, self.admin_employee.pk)

        after = self.member_client.get("/api/auth/me/").json()
        self.assertTrue(after["authenticated"])
        self.assertTrue(after["user"]["waiting_for_role"])
        self.assertEqual(after["user"]["id"], user.pk)
        self.assertEqual(after["user"]["permissions"], [])
        self.assertEqual(after["user"]["effective_access"]["actions"], {})
        self.assertEqual(self.member_client.session.session_key, session_key)
        self.assertEqual(self.member_client.get("/api/v1/").status_code, 403)
        granted = self.admin_client.put(f"/api/v1/access/roles/{self.role.pk}/grants/", {
            "grants": [{"permission": "reference_data.view_country", "scope": "MODULE"}],
        }, format="json", HTTP_IF_MATCH=etag_for_instance(self.role), HTTP_X_CSRFTOKEN=self.csrf_token())
        self.assertEqual(granted.status_code, 200, granted.data)
        authorized = self.member_client.get("/api/auth/me/").json()
        self.assertFalse(authorized["user"]["waiting_for_role"])
        self.assertIn("reference_data.view_country", authorized["user"]["permissions"])
        self.assertIn("reference_data.view_country", authorized["user"]["effective_access"]["actions"])
        self.assertEqual(self.member_client.session.session_key, session_key)
        self.assertEqual(self.oauth_login("repeat-test-code").url, "/")
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, employee.pk)
        employee.refresh_from_db()
        self.assertEqual(employee.user_id, user.pk)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), employee_count + 1)
        self.assertEqual(get_user_model().objects.count(), user_count + 1)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.get_all_permissions(), {"reference_data.view_country"})
        self.assertEqual(RoleActionGrant.objects.filter(role=self.role).count(), 1)
        self.assertEqual(self.upstream.get_identity.call_count, 2)
        self.assertEqual(self.upstream.get_member.call_count, 2)
        self.assertEqual(AuditLog.objects.filter(object_type="WECOM", action="AUTO_CREATE").count(), 1)

    def test_role_assignment_rejects_missing_csrf_and_stale_etag_without_unlocking_member(self):
        self.assertEqual(self.oauth_login("protected-assignment-code").url, "/auth/waiting-role")
        employee = WeComBinding.objects.get().employee
        url = f"/api/v1/access/employees/{employee.pk}/roles/"
        current = self.admin_client.get(url)
        self.assertEqual(current.status_code, 200)
        payload = {"role_ids": [str(self.role.pk)]}
        missing_csrf = self.admin_client.put(url, payload, format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(missing_csrf.status_code, 403)
        stale = self.admin_client.put(url, payload, format="json", HTTP_IF_MATCH='"stale"', HTTP_X_CSRFTOKEN=self.csrf_token())
        self.assertEqual(stale.status_code, 412)
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee=employee).exists())
        self.assertTrue(self.member_client.get("/api/auth/me/").json()["user"]["waiting_for_role"])
        self.assertFalse(AuditLog.objects.filter(object_type="ACCESS_EMPLOYEE", action="EMPLOYEE_ROLES_REPLACE").exists())
