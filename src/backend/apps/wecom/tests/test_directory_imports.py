from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
import time
from threading import Event
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.api.concurrency import PreconditionFailed
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit
from apps.wecom.credentials import encrypt_secret
from apps.wecom.directory_imports import import_directory_copy
from apps.wecom.directory_snapshots import READ_ONLY_IMPORT_ETAG, SNAPSHOT_TTL, load, require_version
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping, WeComDirectorySnapshot
from apps.wecom.selectors import get_config


DIRECTORY = "/api/v1/wecom/employee-directory/"
MAPPINGS = "/api/v1/wecom/department-mappings/"
ORIGIN = "https://source.example.com"


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
                   DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DirectoryReadOnlyImportTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        Employee.objects.create(user=self.admin, employee_code="IMPORT_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.corp_id = get_config().corp_id
        self.fetched_at = timezone.now() - timedelta(minutes=1)
        self.envelope = {"schema": "wecom-directory-readonly-copy-v1", "source_origin": ORIGIN,
            "fetched_at": self.fetched_at.isoformat(), "source_config_etag": '"' + "a" * 64 + '"',
            "directory": {"corp_id": self.corp_id, "departments": [{"id": 1, "parentid": 0, "name": "来源部门"}],
                "members": [{"userid": "Member.One", "name": "来源姓名", "department": [1],
                             "main_department": None, "status": None, "status_label": "未知"}]}}

    def import_copy(self, envelope=None, **kwargs):
        return import_directory_copy(envelope or self.envelope, database_name=connection.settings_dict["NAME"],
            expected_corp_id=self.corp_id, expected_source_origin=ORIGIN, **kwargs)

    def business_counts(self):
        return tuple(model.objects.count() for model in (get_user_model(), Employee, OrganizationUnit,
            EmployeeOrganizationAssignment, EmployeeRoleAssignment, WeComBinding, WeComDepartmentMapping, WeComConfig))

    def test_command_imports_envelope_from_stdin_and_defaults_to_no_write(self):
        before = self.business_counts()
        options = {"database_name": connection.settings_dict["NAME"], "corp_id": self.corp_id, "source_origin": ORIGIN}
        for apply in (False, True):
            output = StringIO()
            with patch("sys.stdin", StringIO(json.dumps(self.envelope))):
                call_command("import_wecom_directory_preview", apply=apply, stdout=output, **options)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["applied"], apply)
            self.assertEqual(summary["member_count"], 1)
            self.assertFalse(summary["can_submit"])
            self.assertNotIn("来源姓名", output.getvalue())
            self.assertEqual(WeComDirectorySnapshot.objects.count(), int(apply))
        snapshot = WeComDirectorySnapshot.objects.get()
        self.assertEqual(snapshot.config_etag, READ_ONLY_IMPORT_ETAG)
        self.assertEqual(snapshot.fetched_at, self.fetched_at)
        self.assertEqual(snapshot.expires_at, self.fetched_at + SNAPSHOT_TTL)
        self.assertEqual(snapshot.directory["_local_import"]["source_origin"], ORIGIN)
        self.assertIsNone(snapshot.directory["members"][0]["status"])
        self.assertIsNone(snapshot.directory["members"][0]["main_department"])
        self.assertEqual(self.business_counts(), before)

    def test_real_gets_display_import_without_configuration_token_or_external_call(self):
        self.import_copy(apply=True)
        before = self.business_counts()
        with patch("apps.wecom.directory_services.WeComDirectoryClient") as employees, patch(
            "apps.wecom.department_mapping_services.WeComDirectoryClient",
        ) as departments:
            for path in (DIRECTORY, MAPPINGS):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.data)
                data = response.data["data"]
                self.assertEqual(len(data["departments"]), 1)
                self.assertEqual(data["corp_id"], self.corp_id)
                self.assertEqual(data["snapshot"]["status"], "CONFIG_UNAVAILABLE")
                self.assertIn(ORIGIN, data["snapshot"]["message"])
                self.assertNotIn("_local_import", data)
                if path == DIRECTORY:
                    self.assertTrue(data["preview_token"])
                    self.assertTrue(data["snapshot"]["can_submit"])
                    self.assertFalse(data["snapshot"]["can_refresh"])
                    self.assertIn("可保存为统一员工", data["snapshot"]["message"])
                    self.assertEqual(data["members"][0]["userid"], "Member.One")
                else:
                    self.assertFalse(data["snapshot"]["can_submit"])
                    self.assertTrue(data["preview_token"])
                    self.assertTrue(data["can_save_mapping"])
                    self.assertIn("可绑定本地", data["snapshot"]["message"])
                    self.assertTrue(data["organizations"])
                    self.assertNotIn("members", data)
            with self.assertRaises(PreconditionFailed):
                require_version(get_config(), None)
            self.assertEqual(self.client.post(DIRECTORY + "sync/", {
                "preview_token": "", "user_ids": ["Member.One"],
            }, format="json").status_code, 400)
            self.assertEqual(self.client.post(DIRECTORY + "refresh/", {}, format="json").status_code, 409)
            employees.assert_not_called()
            departments.assert_not_called()
        self.assertEqual(self.business_counts(), before)

    def test_existing_saved_disabled_or_changed_configuration_hides_import(self):
        self.import_copy(apply=True)
        config = WeComConfig.objects.create(enabled=False, secret_ciphertext=encrypt_secret("test-secret"))
        for enabled in (False, True):
            config.enabled = enabled
            config.save()
            for path in (DIRECTORY, MAPPINGS):
                data = self.client.get(path).data["data"]
                self.assertEqual(data["departments"], [])
                self.assertFalse(data["snapshot"]["can_submit"])
                self.assertEqual(data["snapshot"]["status"], "CONFIG_CHANGED" if enabled else "CONFIG_UNAVAILABLE")
        with self.assertRaises(ValidationError):
            self.import_copy(apply=True)

    def test_normal_or_incompletely_marked_snapshot_is_hidden_and_not_overwritten(self):
        self.import_copy(apply=True)
        row = WeComDirectorySnapshot.objects.get()
        for field in ("_local_import", "config_etag"):
            if field == "_local_import":
                row.directory.pop("_local_import")
            else:
                row.config_etag = '"' + "b" * 64 + '"'
            row.save()
            self.assertEqual(self.client.get(DIRECTORY).data["data"]["members"], [])
            before = WeComDirectorySnapshot.objects.values().get()
            newer = deepcopy(self.envelope)
            newer["fetched_at"] = (self.fetched_at + timedelta(seconds=10)).isoformat()
            with self.assertRaises(ValidationError):
                self.import_copy(newer, apply=True)
            self.assertEqual(WeComDirectorySnapshot.objects.values().get(), before)

    def test_other_corp_is_never_used_as_fallback_or_accepted_for_import(self):
        self.import_copy(apply=True)
        row = WeComDirectorySnapshot.objects.get()
        row.corp_id = "other-corp"
        row.directory["corp_id"] = "other-corp"
        row.save()
        for path in (DIRECTORY, MAPPINGS):
            self.assertEqual(self.client.get(path).data["data"]["departments"], [])
        other = deepcopy(self.envelope)
        other["directory"]["corp_id"] = "other-corp"
        with self.assertRaises(ValidationError):
            import_directory_copy(other, database_name=connection.settings_dict["NAME"],
                expected_corp_id="other-corp", expected_source_origin=ORIGIN, apply=True)
        self.assertEqual(WeComDirectorySnapshot.objects.count(), 1)

    def test_newer_import_replaces_only_source_and_failed_write_retains_old(self):
        self.import_copy(apply=True)
        before = WeComDirectorySnapshot.objects.values().get()
        newer = deepcopy(self.envelope)
        newer["fetched_at"] = (self.fetched_at + timedelta(seconds=10)).isoformat()
        newer["directory"]["members"][0]["name"] = "更新的来源姓名"
        with patch("apps.wecom.directory_imports.WeComDirectorySnapshot.objects.update_or_create",
                   side_effect=RuntimeError("test write failure")), self.assertRaises(RuntimeError):
            self.import_copy(newer, apply=True)
        self.assertEqual(WeComDirectorySnapshot.objects.values().get(), before)
        self.import_copy(newer, apply=True)
        self.assertEqual(WeComDirectorySnapshot.objects.get().directory["members"][0]["name"], "更新的来源姓名")
        with self.assertRaises(ValidationError):
            self.import_copy(apply=True)

    def test_invalid_source_or_incomplete_directory_is_rejected_without_write(self):
        variants = []
        for field, value in (("schema", "other-schema"), ("source_origin", "https://other.example.com"),
            ("source_origin", "http://source.example.com"), ("source_origin", "https://user:secret@source.example.com"),
            ("source_origin", "https://source.example.com/?secret=value"), ("source_config_etag", "invalid"),
            ("fetched_at", "2026-01-01T00:00:00"),
            ("fetched_at", (timezone.now() - timedelta(days=2)).isoformat()),
            ("fetched_at", (timezone.now() + timedelta(days=1)).isoformat())):
            payload = deepcopy(self.envelope)
            payload[field] = value
            variants.append(payload)
        duplicate = deepcopy(self.envelope)
        duplicate["directory"]["members"].append({**duplicate["directory"]["members"][0], "userid": "member.one"})
        variants.append(duplicate)
        for mutation in ("missing-root", "cycle", "unknown-department", "missing-status", "private-field"):
            payload = deepcopy(self.envelope)
            if mutation == "missing-root":
                payload["directory"]["departments"][0]["id"] = 2
            elif mutation == "cycle":
                payload["directory"]["departments"].append({"id": 2, "parentid": 2, "name": "循环部门"})
            elif mutation == "unknown-department":
                payload["directory"]["members"][0]["department"] = [2]
            elif mutation == "missing-status":
                payload["directory"]["members"][0].pop("status")
            else:
                payload["directory"]["members"][0]["secret"] = "must not persist"
            variants.append(payload)
        for index, payload in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                self.import_copy(payload, apply=True)
            self.assertFalse(WeComDirectorySnapshot.objects.exists())
        self.assertFalse(WeComConfig.objects.exists())

    def test_expired_import_remains_read_only_and_access_is_still_required(self):
        self.import_copy(apply=True)
        row = WeComDirectorySnapshot.objects.get()
        row.fetched_at = timezone.now() - timedelta(days=2)
        row.expires_at = row.fetched_at + SNAPSHOT_TTL
        row.directory["_local_import"]["source_read_at"] = row.fetched_at.isoformat()
        row.save()
        data = self.client.get(DIRECTORY).data["data"]
        self.assertEqual(len(data["members"]), 1)
        self.assertIn("已过期", data["snapshot"]["message"])
        self.assertFalse(data["snapshot"]["can_submit"])
        worker = get_user_model().objects.create_user("import-ordinary")
        Employee.objects.create(user=worker, employee_code="IMPORT_ORDINARY", display_name="普通员工")
        self.client.force_login(worker)
        for path in (DIRECTORY, MAPPINGS):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_command_rejects_invalid_json_duplicate_fields_and_wrong_database(self):
        options = {"database_name": connection.settings_dict["NAME"], "corp_id": self.corp_id, "source_origin": ORIGIN,
                   "apply": True, "stdout": StringIO()}
        for text in ("invalid-json", '{"schema":"a","schema":"b"}'):
            with patch("sys.stdin", StringIO(text)), self.assertRaises(CommandError):
                call_command("import_wecom_directory_preview", **options)
        with self.assertRaises(ValidationError):
            import_directory_copy(self.envelope, database_name="wrong-database", expected_corp_id=self.corp_id,
                                  expected_source_origin=ORIGIN, apply=True)
        self.assertFalse(WeComDirectorySnapshot.objects.exists())


class DirectoryReadOnlyImportConcurrencyTests(TransactionTestCase):
    def test_configuration_creation_waits_until_import_commits_then_hides_import(self):
        corp_id = get_config().corp_id
        envelope = {"schema": "wecom-directory-readonly-copy-v1", "source_origin": ORIGIN,
            "fetched_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
            "source_config_etag": '"' + "a" * 64 + '"',
            "directory": {"corp_id": corp_id, "departments": [{"id": 1, "parentid": 0, "name": "来源部门"}],
                "members": [{"userid": "One", "name": "来源姓名", "department": [1],
                             "main_department": None, "status": None, "status_label": "未知"}]}}
        writing, release, creating = Event(), Event(), Event()
        creator_pid = []
        original = WeComDirectorySnapshot.objects.update_or_create

        def pause_before_write(*args, **kwargs):
            writing.set()
            if not release.wait(timeout=15):
                raise AssertionError("未释放导入写入等待点")
            return original(*args, **kwargs)

        def run(function):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                return function()
            finally:
                connections.close_all()

        def import_copy():
            return import_directory_copy(envelope, database_name=connection.settings_dict["NAME"],
                expected_corp_id=corp_id, expected_source_origin=ORIGIN, apply=True)

        def create_config():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                creator_pid.append(cursor.fetchone()[0])
            creating.set()
            return WeComConfig.objects.create(enabled=False).pk

        with patch("apps.wecom.directory_imports.WeComDirectorySnapshot.objects.update_or_create",
                   side_effect=pause_before_write), ThreadPoolExecutor(max_workers=2) as pool:
            imported = pool.submit(run, import_copy)
            try:
                self.assertTrue(writing.wait(timeout=15))
                configured = pool.submit(run, create_config)
                self.assertTrue(creating.wait(timeout=5))
                deadline, blocked = time.monotonic() + 5, False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s "
                                       "AND relation='wecom_config'::regclass AND NOT granted)", creator_pid)
                        blocked = cursor.fetchone()[0]
                    if blocked or configured.done():
                        break
                    time.sleep(0.02)
                self.assertTrue(blocked, "配置创建必须等待导入持有的配置表锁")
            finally:
                release.set()
            self.assertTrue(imported.result(timeout=15)["applied"])
            self.assertIsNotNone(configured.result(timeout=15))
        self.assertEqual(WeComDirectorySnapshot.objects.count(), 1)
        _, directory, metadata = load(get_config())
        self.assertEqual(directory["members"], [])
        self.assertFalse(metadata["can_submit"])
