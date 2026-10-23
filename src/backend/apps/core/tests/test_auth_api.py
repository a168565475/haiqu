from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment, EmployeeStatus, RoleProfile
from apps.audit.models import AuditLog
from apps.core.login_records import login_account_id


class AuthenticationApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="test_admin",
            password="StrongTestPassword123!",
            first_name="测试",
            last_name="管理员",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="TEST_ADMIN",
            display_name="测试管理员",
        )
        self.inactive_user = user_model.objects.create_user(
            username="inactive_user",
            password="StrongTestPassword123!",
            is_active=False,
        )
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf_token(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)
        return self.client.cookies["csrftoken"].value

    def test_me_returns_anonymous_state_and_csrf_cookie(self):
        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"authenticated": False, "user": None})
        self.assertIn("csrftoken", self.client.cookies)

    def test_login_requires_csrf_token(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "test_admin", "password": "StrongTestPassword123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(DEV_AUTO_LOGIN_ENABLED=False)
    def test_development_auto_login_is_disabled_without_explicit_configuration(self):
        token = self.csrf_token()

        response = self.client.post(
            "/api/auth/development-auto-login/",
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(
        DEV_AUTO_LOGIN_ENABLED=True,
        DEV_AUTO_LOGIN_USERNAME="test_admin",
        DEV_AUTO_LOGIN_ALLOWED_HOSTS=["testserver"],
    )
    def test_development_auto_login_cannot_create_session_even_with_old_flags(self):
        token = self.csrf_token()

        response = self.client.post(
            "/api/auth/development-auto-login/",
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 404, response.data)
        self.assertNotIn("sessionid", self.client.cookies)

    def test_logout_requires_csrf_and_preserves_session(self):
        token = self.csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login_response.status_code, 200)

        logout_response = self.client.post("/api/auth/logout/", format="json")
        self.assertEqual(logout_response.status_code, 403)

        me_response = self.client.get("/api/auth/me/")
        self.assertTrue(me_response.data["authenticated"])

    def test_login_me_and_logout_session_flow(self):
        token = self.csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": "test_admin", "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.data["authenticated"])
        self.assertEqual(login_response.data["user"]["username"], "test_admin")
        self.assertEqual(login_response.data["user"]["display_name"], "测试 管理员")
        self.assertFalse(login_response.data["user"]["is_superuser"])
        self.assertEqual(login_response.data["user"]["employee"]["status"], EmployeeStatus.ACTIVE)
        log = AuditLog.objects.get(object_type="AUTH_ACCOUNT", object_id=login_account_id(self.user.pk))
        self.assertEqual(log.action, "LOGIN_SUCCESS")
        self.assertEqual(log.after_data, {"user_id": self.user.pk, "username": self.user.username, "method": "PASSWORD"})
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

        me_response = self.client.get("/api/auth/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.data["authenticated"])

        rotated_token = self.client.cookies["csrftoken"].value
        logout_response = self.client.post(
            "/api/auth/logout/",
            format="json",
            HTTP_X_CSRFTOKEN=rotated_token,
        )
        self.assertEqual(logout_response.status_code, 200)

        anonymous_response = self.client.get("/api/auth/me/")
        self.assertEqual(anonymous_response.data, {"authenticated": False, "user": None})
        self.assertEqual(AuditLog.objects.filter(object_type="AUTH_ACCOUNT").count(), 1)

    def test_each_explicit_successful_login_is_counted_once(self):
        for expected in (1, 2):
            response = self.client.post("/api/auth/login/", {"username": self.user.username, "password": "StrongTestPassword123!"},
                format="json", HTTP_X_CSRFTOKEN=self.csrf_token())
            self.assertEqual(response.status_code, 200)
            self.client.get("/api/auth/me/")
            self.assertEqual(AuditLog.objects.filter(object_type="AUTH_ACCOUNT", object_id=login_account_id(self.user.pk)).count(), expected)

    def test_login_record_failure_rolls_back_last_login_and_session(self):
        from unittest.mock import patch
        with patch("apps.core.views.record_successful_login", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                self.client.post("/api/auth/login/", {"username": self.user.username, "password": "StrongTestPassword123!"},
                    format="json", HTTP_X_CSRFTOKEN=self.csrf_token())
        self.user.refresh_from_db()
        self.assertIsNone(self.user.last_login)
        self.assertFalse(AuditLog.objects.filter(object_type="AUTH_ACCOUNT").exists())
        self.assertFalse(Session.objects.exists())

    def test_login_rejects_wrong_password_and_inactive_user(self):
        token = self.csrf_token()

        for payload in (
            {"username": "test_admin", "password": "wrong-password"},
            {"username": "unknown_user", "password": "wrong-password"},
            {"username": "inactive_user", "password": "StrongTestPassword123!"},
        ):
            with self.subTest(username=payload["username"]):
                response = self.client.post(
                    "/api/auth/login/",
                    payload,
                    format="json",
                    HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data, {"detail": "用户名或密码错误"})
        self.assertFalse(AuditLog.objects.filter(object_type="AUTH_ACCOUNT").exists())

    def test_login_rejects_user_without_active_employee(self):
        user_model = get_user_model()
        rejected_users = []

        user_without_employee = user_model.objects.create_user(
            username="no_employee",
            password="StrongTestPassword123!",
        )
        rejected_users.append(user_without_employee)

        for username, employee_code, employee_status, archived_at in (
            ("inactive_employee", "INACTIVE_EMP", EmployeeStatus.INACTIVE, None),
            ("left_employee", "LEFT_EMP", EmployeeStatus.LEFT, None),
            ("archived_employee", "ARCHIVED_EMP", EmployeeStatus.ACTIVE, timezone.now()),
        ):
            user = user_model.objects.create_user(
                username=username,
                password="StrongTestPassword123!",
            )
            Employee.objects.create(
                user=user,
                employee_code=employee_code,
                display_name=username,
                status=employee_status,
                archived_at=archived_at,
            )
            rejected_users.append(user)

        token = self.csrf_token()
        for user in rejected_users:
            with self.subTest(username=user.username):
                response = self.client.post(
                    "/api/auth/login/",
                    {"username": user.username, "password": "StrongTestPassword123!"},
                    format="json",
                    HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data, {"detail": "用户名或密码错误"})

        self.assertNotIn("sessionid", self.client.cookies)

    def test_superuser_without_employee_can_login(self):
        user_model = get_user_model()
        superuser = user_model.objects.create_superuser(
            username="recovery_admin",
            password="StrongTestPassword123!",
            email="admin@example.com",
        )
        token = self.csrf_token()

        response = self.client.post(
            "/api/auth/login/",
            {"username": superuser.username, "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["authenticated"])
        self.assertIsNone(response.data["user"]["employee"])
        self.assertIsNone(AuditLog.objects.get(object_type="AUTH_ACCOUNT", object_id=login_account_id(superuser.pk)).actor_employee_id)

    def test_existing_session_is_revoked_when_employee_becomes_inactive(self):
        token = self.csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login_response.status_code, 200)

        self.employee.status = EmployeeStatus.INACTIVE
        self.employee.save(update_fields=["status", "updated_at"])

        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.data, {"authenticated": False, "user": None})
        self.assertEqual(Session.objects.count(), 0)

    def test_existing_session_is_revoked_when_employee_is_archived(self):
        token = self.csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login_response.status_code, 200)

        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=["archived_at", "updated_at"])

        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.data, {"authenticated": False, "user": None})
        self.assertEqual(Session.objects.count(), 0)

    def test_active_employee_role_assignment_grants_group_permissions(self):
        permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="view_customeraccount",
        )
        group = Group.objects.create(name="测试业务员角色")
        group.permissions.add(permission)
        role = RoleProfile.objects.create(
            auth_group=group,
            role_code="TEST_SALES_ROLE",
            display_name="测试业务员角色",
        )
        EmployeeRoleAssignment.objects.create(
            employee=self.employee,
            role_profile=role,
            effective_from=timezone.now() - timedelta(minutes=1),
        )

        token = self.csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": self.user.username, "password": "StrongTestPassword123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("customers.view_customeraccount", login_response.data["user"]["permissions"])
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).has_perm("customers.view_customeraccount"))

    def test_expired_employee_role_assignment_does_not_grant_permissions(self):
        permission = Permission.objects.get(
            content_type__app_label="customers",
            codename="view_customeraccount",
        )
        group = Group.objects.create(name="测试过期角色")
        group.permissions.add(permission)
        role = RoleProfile.objects.create(
            auth_group=group,
            role_code="TEST_EXPIRED_ROLE",
            display_name="测试过期角色",
        )
        now = timezone.now()
        EmployeeRoleAssignment.objects.create(
            employee=self.employee,
            role_profile=role,
            effective_from=now - timedelta(days=2),
            effective_to=now - timedelta(days=1),
        )

        fresh_user = get_user_model().objects.get(pk=self.user.pk)
        self.assertFalse(fresh_user.has_perm("customers.view_customeraccount"))

    def test_login_validates_required_fields(self):
        token = self.csrf_token()
        response = self.client.post(
            "/api/auth/login/",
            {"username": "", "password": ""},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.data)
        self.assertIn("password", response.data)
