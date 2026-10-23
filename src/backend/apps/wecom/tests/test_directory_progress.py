from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import caches
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from django.utils import timezone

from apps.access_control.models import RoleActionGrant
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom import directory_progress as progress
from apps.wecom.models import WeComConfig, WeComDirectorySnapshot
from apps.wecom.tests.test_directory_client import WeComDirectoryClientTests


TEST_CACHE = {"wecom": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "directory-progress-tests"},
              "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
ROOT = "/api/v1/wecom/employee-directory/"


@override_settings(CACHES=TEST_CACHE)
class DirectoryProgressTests(SimpleTestCase):
    def test_failure_keeps_actual_count_and_request_context_is_reset(self):
        request = SimpleNamespace(user=SimpleNamespace(pk=11), headers={"X-Directory-Progress": str(uuid4())})
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with progress.track(request, 4):
                progress.advance("保存员工")
                raise RuntimeError("rollback")
        data = progress.read(request, request.headers["X-Directory-Progress"])
        self.assertEqual((data["status"], data["completed"], data["total"]), ("FAILED", 1, 4))
        self.assertIsNone(progress.current.get())
        caches["wecom"].delete(progress.cache_key(11, request.headers["X-Directory-Progress"]))


class DirectorySourceProgressTests(WeComDirectoryClientTests):
    def test_progress_advances_only_after_real_department_responses(self):
        request = SimpleNamespace(user=SimpleNamespace(pk=12), headers={"X-Directory-Progress": str(uuid4())})
        self.responses(self.token(), self.scope(), self.department_list(), self.department(),
                       {"errcode": 0, "userlist": [self.member()]})
        states = []
        original = progress.Progress.write
        def capture(value):
            states.append(dict(value.data))
            original(value)
        with patch.object(progress.Progress, "write", capture), progress.track(request, 3):
            self.client.read_directory()
        self.assertEqual([row["completed"] for row in states], [0, 2, 3, 4, 7])
        self.assertTrue(all(row["total"] == 7 for row in states))
        self.assertTrue(all(row["completed"] < row["total"] for row in states[:-1]))
        self.assertEqual(states[-1]["status"], "SUCCESS")


@override_settings(CACHES=TEST_CACHE, ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DirectoryProgressAPITests(TestCase):
    def setUp(self):
        caches["wecom"].clear()
        self.addCleanup(caches["wecom"].clear)
        self.user = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.user, employee_code="PROGRESS_ADMIN", display_name="进度管理员")
        self.client = APIClient()
        self.client.force_login(self.user)
        self.config = WeComConfig.objects.create(enabled=True)
        self.source = {"corp_id": self.config.corp_id, "departments": [{"id": 1, "parentid": 0, "name": "公司"}],
                       "members": [{"userid": "one", "name": "员工", "department": [1], "main_department": 1,
                                    "status": 1, "status_label": "已激活"}]}

    def refresh(self, request_id):
        with patch("apps.wecom.directory_services.read_source", return_value=self.source):
            return self.client.post(ROOT + "refresh/", {}, HTTP_X_DIRECTORY_PROGRESS=str(request_id))

    def test_success_owner_isolation_duplicate_id_and_permission_recheck(self):
        request_id = uuid4()
        self.assertEqual(self.refresh(request_id).status_code, 200)
        url = ROOT + f"progress/{request_id}/"
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["data"], {"status": "SUCCESS", "completed": 3, "total": 3, "phase": "已完成"})
        self.assertEqual(self.refresh(request_id).status_code, 409)
        other = get_user_model().objects.create_user("progress-manager", "", "test-password")
        employee = Employee.objects.create(user=other, employee_code="PROGRESS_OTHER", display_name="另一管理员")
        group = Group.objects.create(name="进度查询管理角色")
        role = RoleProfile.objects.create(auth_group=group, role_code="PROGRESS_MANAGER", display_name="进度管理")
        permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_accounts")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        self.user.is_superuser = False
        self.user.is_staff = False
        self.user.save()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(url).status_code, [401, 403])

    def test_failed_refresh_keeps_previous_snapshot_and_does_not_complete(self):
        self.assertEqual(self.refresh(uuid4()).status_code, 200)
        original = WeComDirectorySnapshot.objects.get(corp_id=self.config.corp_id)
        request_id = uuid4()
        from apps.core.api.exceptions import Conflict
        with patch("apps.wecom.directory_services.read_source", side_effect=Conflict("读取失败")):
            self.assertEqual(self.client.post(ROOT + "refresh/", {}, HTTP_X_DIRECTORY_PROGRESS=str(request_id)).status_code, 409)
        data = self.client.get(ROOT + f"progress/{request_id}/").data["data"]
        self.assertEqual(data["status"], "FAILED")
        self.assertLess(data["completed"], data["total"])
        self.assertEqual(WeComDirectorySnapshot.objects.get(pk=original.pk).updated_at, original.updated_at)

    def test_invalid_progress_id_is_rejected_before_source_read(self):
        with patch("apps.wecom.directory_services.read_source") as source:
            response = self.client.post(ROOT + "refresh/", {}, HTTP_X_DIRECTORY_PROGRESS="not-a-uuid")
        self.assertEqual(response.status_code, 400)
        source.assert_not_called()
