from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee, EmployeeStatus


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
        self.assertEqual(login_response.data["user"]["employee"]["status"], EmployeeStatus.ACTIVE)

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
