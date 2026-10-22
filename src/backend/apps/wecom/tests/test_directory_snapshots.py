from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, OrganizationUnit
from apps.wecom.client import WeComError
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping, WeComDirectorySnapshot


DIRECTORY = "/api/v1/wecom/employee-directory/"
MAPPINGS = "/api/v1/wecom/department-mappings/"


@override_settings(
    WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class DirectorySnapshotTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.admin, employee_code="SNAPSHOT_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("snapshot-secret"))
        self.unit = OrganizationUnit.objects.create(unit_code="SNAPSHOT_DEPT", unit_name="既有部门")
        self.source = {"corp_id": self.config.corp_id, "departments": [{"id": 1, "parentid": 0, "name": "来源部门"}],
                       "members": [{"userid": "Member.One", "name": "来源姓名", "department": [1],
                                    "main_department": 1, "status": 1, "status_label": "已激活"}]}
        self.upstream_patch = patch("apps.wecom.directory_services.WeComDirectoryClient")
        self.upstream = self.upstream_patch.start()
        self.addCleanup(self.upstream_patch.stop)
        self.upstream.return_value.read_directory.side_effect = lambda: deepcopy(self.source)

    def refresh(self):
        response = self.client.post(DIRECTORY + "refresh/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def sync(self, preview):
        return self.client.post(DIRECTORY + "sync/", {
            "preview_token": preview.data["data"]["preview_token"], "user_ids": ["Member.One"],
        }, format="json", HTTP_IF_MATCH=preview["ETag"])

    def test_missing_snapshot_returns_local_departments_without_external_call(self):
        for remove_config in (False, True):
            if remove_config:
                self.config.delete()
            response = self.client.get(MAPPINGS)
            self.assertEqual(response.status_code, 200, response.data)
            data = response.data["data"]
            self.assertIn(str(self.unit.pk), [unit["id"] for unit in data["organizations"]])
            self.assertEqual(data["snapshot"]["status"], "CONFIG_UNAVAILABLE" if remove_config else "MISSING")
            self.assertFalse(data["snapshot"]["can_submit"])
            self.assertEqual(data["preview_token"], "")
            self.assertEqual(data["departments"], [])
        self.upstream.assert_not_called()
        self.assertFalse(WeComDirectorySnapshot.objects.exists())

    def test_success_persists_only_source_and_restores_with_current_employee_state(self):
        self.refresh()
        snapshot = WeComDirectorySnapshot.objects.get()
        self.assertEqual(snapshot.directory, self.source)
        self.assertEqual(snapshot.expires_at - snapshot.fetched_at, timedelta(hours=24))
        self.assertEqual(Employee.objects.count(), 1)
        self.assertFalse(WeComBinding.objects.exists())
        candidate = Employee.objects.create(employee_code="SNAPSHOT_CANDIDATE", display_name="来源姓名")
        self.upstream.reset_mock()
        restored = self.client.get(DIRECTORY)
        self.assertEqual(restored.status_code, 200, restored.data)
        member = restored.data["data"]["members"][0]
        self.assertEqual(member["action"], "REVIEW")
        self.assertEqual(member["candidates"][0]["id"], str(candidate.pk))
        self.assertTrue(restored.data["data"]["snapshot"]["can_submit"])
        self.upstream.assert_not_called()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.directory, self.source)

    def test_cache_restore_recalculates_binding_and_inactive_status(self):
        self.refresh()
        employee = Employee.objects.create(employee_code="SNAPSHOT_BOUND", display_name="ERP姓名", status="LEFT")
        WeComBinding.objects.create(corp_id=self.config.corp_id, user_id="Member.One", member_name="原姓名",
                                    employee=employee, source="MANUAL")
        data = self.client.get(DIRECTORY).data["data"]
        self.assertEqual(data["members"][0]["action"], "EXISTING")
        self.assertEqual(data["members"][0]["employee"]["status"], "LEFT")
        self.assertEqual(data["members"][0]["employee"]["display_name"], "ERP姓名")

    def test_same_snapshot_feeds_mapping_list_with_persistent_mapping_and_current_etag(self):
        self.refresh()
        mapping = WeComDepartmentMapping.objects.create(corp_id=self.config.corp_id, wecom_department_id=1,
            wecom_department_name="来源旧名", organization_unit=self.unit)
        self.unit.unit_name = "ERP更名部门"
        self.unit.save()
        self.upstream.reset_mock()
        with patch("apps.wecom.department_mapping_services.WeComDirectoryClient") as mapping_upstream:
            response = self.client.get(MAPPINGS)
            self.assertEqual(response.status_code, 200, response.data)
            data = response.data["data"]
            current = data["departments"][0]["mapping"]
            self.assertEqual(current["id"], str(mapping.pk))
            self.assertEqual(current["organization_unit_id"], str(self.unit.pk))
            self.assertEqual(current["organization_name"], "ERP更名部门")
            self.assertEqual(current["organization_etag"], etag_for_instance(self.unit))
            self.assertNotIn("members", data)
            mapping_upstream.assert_not_called()
        self.upstream.assert_not_called()

    def test_failed_refresh_preserves_previous_snapshot_and_mapping(self):
        self.refresh()
        old = WeComDirectorySnapshot.objects.values().get()
        self.upstream.return_value.read_directory.side_effect = WeComError("PRIVATE", "secret upstream detail")
        response = self.client.post(DIRECTORY + "refresh/", {}, format="json")
        self.assertEqual(response.status_code, 502, response.data)
        self.assertNotIn("secret upstream detail", str(response.data))
        self.assertEqual(WeComDirectorySnapshot.objects.values().get(), old)
        self.assertEqual(self.client.get(DIRECTORY).data["data"]["snapshot"]["status"], "VALID")

    def test_expired_snapshot_is_visible_without_token_and_cannot_be_submitted(self):
        preview = self.refresh()
        WeComDirectorySnapshot.objects.update(fetched_at=timezone.now() - timedelta(days=2),
                                             expires_at=timezone.now() - timedelta(days=1))
        self.upstream.reset_mock()
        response = self.client.get(DIRECTORY)
        self.assertEqual(response.data["data"]["snapshot"]["status"], "EXPIRED")
        self.assertEqual(response.data["data"]["preview_token"], "")
        self.assertEqual(len(response.data["data"]["members"]), 1)
        self.assertEqual(self.sync(preview).status_code, 412)
        self.upstream.assert_not_called()
        self.assertFalse(WeComBinding.objects.exists())

    def test_config_change_hides_old_source_and_keeps_local_options(self):
        preview = self.refresh()
        self.config.agent_id = "changed"
        self.config.save()
        response = self.client.get(MAPPINGS)
        self.assertEqual(response.data["data"]["snapshot"]["status"], "CONFIG_CHANGED")
        self.assertEqual(response.data["data"]["departments"], [])
        self.assertTrue(response.data["data"]["organizations"])
        self.assertEqual(self.sync(preview).status_code, 412)
        self.config.corp_id = "other-corp"
        self.config.save()
        data = self.client.get(DIRECTORY).data["data"]
        self.assertEqual(data["snapshot"]["status"], "MISSING")
        self.assertEqual(data["members"], [])

    def test_new_successful_refresh_invalidates_previous_preview_even_if_source_unchanged(self):
        first = self.refresh()
        self.refresh()
        self.assertEqual(self.sync(first).status_code, 412)
        self.assertFalse(WeComBinding.objects.exists())
        self.source["members"][0]["name"] = "最新读取姓名"
        self.refresh()
        self.assertEqual(WeComDirectorySnapshot.objects.get().directory, self.source)

    def test_late_refresh_cannot_replace_a_newer_saved_result(self):
        self.refresh()
        newer = deepcopy(self.source)
        newer["members"][0]["name"] = "另一读取已保存的新结果"

        def finish_newer_request_first():
            WeComDirectorySnapshot.objects.update(directory=newer, fetched_at=timezone.now())
            return deepcopy(self.source)

        self.upstream.return_value.read_directory.side_effect = finish_newer_request_first
        response = self.client.post(DIRECTORY + "refresh/", {}, format="json")
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(WeComDirectorySnapshot.objects.get().directory, newer)

    def test_restoring_snapshot_rechecks_current_actor_status(self):
        self.refresh()
        self.upstream.reset_mock()
        Employee.objects.filter(user=self.admin).update(status="INACTIVE")
        for path in (DIRECTORY, MAPPINGS):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.upstream.assert_not_called()

    def test_schema_gate_is_safe_before_main_database_migration(self):
        with patch("apps.wecom.directory_snapshots.MigrationRecorder.Migration.objects.filter") as query:
            query.return_value.exists.return_value = False
            for path in (DIRECTORY, MAPPINGS):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503, response.data)
        self.upstream.assert_not_called()

    def test_refresh_requires_session_csrf_and_rejects_unknown_fields(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for path in (DIRECTORY, MAPPINGS):
            self.assertEqual(client.post(path + "refresh/", {}, format="json").status_code, 403)
            self.assertEqual(self.client.post(path + "refresh/", {"unsupported": 1}, format="json").status_code, 400)
        self.upstream.assert_not_called()


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DirectorySnapshotMigrationTests(TransactionTestCase):
    def test_actual_pre_snapshot_schema_blocks_directory_but_preserves_existing_lists(self):
        admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=admin, employee_code="SNAPSHOT_SCHEMA_ADMIN", display_name="管理员")
        client = APIClient()
        client.force_login(admin)
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        old_targets = [("wecom", "0004_wecom_department_mapping")]
        plan = [(migration.app_label, migration.name, backwards)
                for migration, backwards in executor.migration_plan(old_targets)]
        self.assertEqual(plan, [("wecom", "0005_directory_snapshot", True)])
        try:
            executor.migrate(old_targets)
            self.assertNotIn(WeComDirectorySnapshot._meta.db_table, connection.introspection.table_names())
            for path in (DIRECTORY, MAPPINGS):
                response = client.get(path)
                self.assertEqual(response.status_code, 503, response.data)
            for path in ("/api/v1/access/employees/", "/api/v1/access/departments/"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, response.data)
        finally:
            MigrationExecutor(connection).migrate(final_targets)
