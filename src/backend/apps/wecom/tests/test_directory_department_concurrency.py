from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.access_control.organization_services import replace_employee_departments
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.wecom import directory_services
from apps.wecom.credentials import encrypt_secret
from apps.wecom.directory_services import preview_directory, sync_directory
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping


ROOT = "/api/v1/wecom/employee-directory/"


@override_settings(
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"], DEV_AUTO_LOGIN_ENABLED=False,
)
class DirectoryDepartmentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.admin, employee_code="DEPT_CONCURRENT_ADMIN", display_name="管理员")
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-secret"))
        self.root, _ = OrganizationUnit.objects.get_or_create(unit_code="HAIQU", defaults={"unit_name": "公司"})
        self.unit = OrganizationUnit.objects.create(unit_code="DEPT_CONCURRENT_SYNC", unit_name="同步部门", parent=self.root)
        self.manual_unit = OrganizationUnit.objects.create(unit_code="DEPT_CONCURRENT_MANUAL", unit_name="人工维护部门", parent=self.root)
        WeComDepartmentMapping.objects.create(
            corp_id=self.config.corp_id, wecom_department_id=1,
            wecom_department_name="企业微信部门", organization_unit=self.unit,
        )
        self.member = {
            "userid": "Concurrent.Department", "name": "并发部门员工", "department": [1],
            "main_department": 1, "status": 1, "status_label": "已激活",
        }
        self.directory = {
            "corp_id": self.config.corp_id,
            "departments": [{"id": 1, "parentid": 0, "name": "企业微信部门"}], "members": [self.member],
        }
        client_patch = patch("apps.wecom.directory_services.WeComDirectoryClient")
        self.upstream = client_patch.start().return_value
        self.addCleanup(client_patch.stop)
        self.upstream.read_directory.side_effect = lambda: deepcopy(self.directory)
        self.preview, self.etag = preview_directory(self.request(), apply_departments=True)

    def request(self, etag=None):
        request = RequestFactory().post(ROOT + "sync/", HTTP_IF_MATCH=etag or getattr(self, "etag", ""))
        request.user = self.admin
        return request

    def sync_data(self):
        return {
            "preview_token": self.preview["preview_token"], "user_ids": [self.member["userid"]],
            "confirmed_new_user_ids": [], "apply_departments": True,
        }

    def thread_run(self, function):
        close_old_connections()
        try:
            # 测试线程发生锁顺序回归时及时失败，避免长时间占用独占测试库。
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
            return function()
        finally:
            connections.close_all()

    def test_two_department_syncs_create_one_account_binding_and_assignment(self):
        barrier = Barrier(2)

        def synchronized_source():
            barrier.wait(timeout=15)
            return deepcopy(self.directory)

        self.upstream.read_directory.side_effect = synchronized_source
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.thread_run, lambda: sync_directory(self.request(), self.sync_data())) for _ in range(2)]
            results = [future.result(timeout=40)[0] for future in futures]
        self.assertCountEqual([row["result"] for row in results], ["CREATED", "EXISTING"])
        self.assertCountEqual([row["department_status"] for row in results], ["APPLIED", "PRESERVED"])
        self.assertEqual(len({row["employee_id"] for row in results}), 1)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        assignment = EmployeeOrganizationAssignment.objects.get()
        self.assertEqual(assignment.organization_unit_id, self.unit.pk)
        self.assertTrue(assignment.is_primary)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_CREATE").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_DEPARTMENTS_FILL").count(), 1)

    def test_manual_assignment_committing_while_sync_waits_for_root_lock_is_preserved(self):
        user = get_user_model().objects.create_user("department_existing")
        employee = Employee.objects.create(user=user, employee_code="DEPT_CONCURRENT_EXISTING", display_name="原员工")
        WeComBinding.objects.create(
            corp_id=self.config.corp_id, user_id=self.member["userid"], member_name=self.member["name"],
            employee=employee, source="MANUAL", created_account=False,
        )
        self.preview, self.etag = preview_directory(self.request(), apply_departments=True)
        entering_root_lock = Event()
        original_lock = directory_services.lock_department_context

        def signal_root_lock(*args, **kwargs):
            entering_root_lock.set()
            return original_lock(*args, **kwargs)

        with patch("apps.wecom.directory_services.lock_department_context", side_effect=signal_root_lock):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    OrganizationUnit.objects.select_for_update().get(pk=self.root.pk)
                    future = pool.submit(self.thread_run, lambda: sync_directory(self.request(), self.sync_data()))
                    self.assertTrue(entering_root_lock.wait(timeout=15), "同步未进入根组织锁步骤")
                    replace_employee_departments(self.request(etag_for_instance(employee)), employee.pk, [{
                        "department_id": self.manual_unit.pk, "is_primary": True, "position_title": "人工岗位",
                    }])
                    before = list(EmployeeOrganizationAssignment.objects.filter(employee=employee).values())
                result = future.result(timeout=40)[0]
        self.assertEqual(result["result"], "EXISTING")
        self.assertEqual(result["department_status"], "PRESERVED")
        self.assertEqual(list(EmployeeOrganizationAssignment.objects.filter(employee=employee).values()), before)
        self.assertEqual(EmployeeOrganizationAssignment.objects.get().organization_unit_id, self.manual_unit.pk)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="EMPLOYEE_DEPARTMENTS_REPLACE").count(), 1)
        self.assertFalse(AuditLog.objects.filter(action="DIRECTORY_DEPARTMENTS_FILL").exists())

    def test_actual_pre_mapping_schema_allows_default_sync_and_blocks_department_mode(self):
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        old_targets = [("wecom", "0003_notificationevent_notificationrecipient_and_more")]
        plan = [(migration.app_label, migration.name, backwards)
                for migration, backwards in executor.migration_plan(old_targets)]
        if plan != [("wecom", "0004_wecom_department_mapping", True)]:
            self.skipTest("迁移依赖已变化，不能在本测试中撤销其他迁移。")
        client = APIClient()
        client.force_login(self.admin)
        target = Employee.objects.create(employee_code="DEPT_UNMIGRATED_TARGET", display_name="待匹配员工")
        table_name = WeComDepartmentMapping._meta.db_table
        try:
            executor.migrate(old_targets)
            self.assertNotIn(table_name, connection.introspection.table_names())
            response = client.get(ROOT)
            self.assertEqual(response.status_code, 200, response.data)
            default_preview = response.data["data"]
            response = client.post(ROOT + "sync/", {
                "preview_token": default_preview["preview_token"], "user_ids": [self.member["userid"]],
            }, format="json", HTTP_IF_MATCH=response["ETag"])
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"][0]["result"], "CREATED")
            self.assertNotIn("department_status", response.data["data"][0])
            self.assertFalse(EmployeeOrganizationAssignment.objects.exists())
            self.assertEqual(client.get(ROOT, {"apply_departments": "true"}).status_code, 503)
            self.assertEqual(client.get("/api/v1/wecom/department-mappings/").status_code, 503)
            response = client.post(ROOT + "sync/", self.sync_data(), format="json", HTTP_IF_MATCH=self.etag)
            self.assertEqual(response.status_code, 503, response.data)
            response = client.post(ROOT + "match/", {
                "preview_token": self.preview["preview_token"], "user_id": self.member["userid"],
                "employee_id": str(target.pk), "employee_etag": etag_for_instance(target),
                "confirmed": True, "apply_departments": True,
            }, format="json", HTTP_IF_MATCH=self.etag)
            self.assertEqual(response.status_code, 503, response.data)
            self.assertEqual(WeComBinding.objects.count(), 1)
        finally:
            MigrationExecutor(connection).migrate(final_targets)
        self.assertIn(table_name, connection.introspection.table_names())
        self.assertIn(("wecom", "0004_wecom_department_mapping"), MigrationExecutor(connection).loader.applied_migrations)
