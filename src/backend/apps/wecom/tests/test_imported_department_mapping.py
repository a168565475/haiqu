from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event
import time
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.db import close_old_connections, connection, connections, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.wecom import department_mapping_services as services
from apps.wecom.credentials import encrypt_secret
from apps.wecom.directory_imports import import_directory_copy
from apps.wecom.directory_snapshots import require_version
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping, WeComDirectorySnapshot
from apps.wecom.selectors import get_config


ROOT = "/api/v1/wecom/department-mappings/"
EMPLOYEES = "/api/v1/wecom/employee-directory/"


class ImportedMappingFixture:
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.actor = Employee.objects.create(user=self.admin, employee_code="IMPORTED_MAPPING_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.root, _ = OrganizationUnit.objects.get_or_create(unit_code="HAIQU", defaults={"unit_name": "公司"})
        self.unit = OrganizationUnit.objects.create(unit_code="IMPORTED_MAPPING_TARGET", unit_name="生产部", parent=self.root)
        self.corp_id = get_config().corp_id
        self.envelope = {"schema": "wecom-directory-readonly-copy-v1", "source_origin": "https://source.example.com",
            "fetched_at": (timezone.now() - timedelta(minutes=1)).isoformat(), "source_config_etag": '"' + "a" * 64 + '"',
            "directory": {"corp_id": self.corp_id,
                "departments": [{"id": 1, "parentid": 0, "name": "来源公司"}, {"id": 2, "parentid": 1, "name": "生产部"}],
                "members": [{"userid": "One", "name": "来源姓名", "department": [2],
                             "main_department": 2, "status": 1, "status_label": "已激活"}]}}
        self.import_copy()
        for module in ("department_mapping_services", "directory_services"):
            upstream = self.enterContext(patch(f"apps.wecom.{module}.WeComDirectoryClient"))
            upstream.side_effect = AssertionError("导入副本路径不能发起外部读取")

    def import_copy(self, envelope=None):
        return import_directory_copy(envelope or self.envelope, database_name=connection.settings_dict["NAME"],
            expected_corp_id=self.corp_id, expected_source_origin=self.envelope["source_origin"], apply=True)

    def preview(self):
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def payload(self, preview, **fields):
        return {"preview_token": preview.data["data"]["preview_token"], "organization_unit_id": str(self.unit.pk),
                "organization_etag": etag_for_instance(self.unit), "confirmed": True, **fields}

    def update(self, preview, source_id=2, **fields):
        return self.client.put(ROOT + f"{source_id}/", self.payload(preview, **fields), format="json",
                               HTTP_IF_MATCH=preview["ETag"])

    def no_mapping_writes(self):
        self.assertFalse(WeComDepartmentMapping.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE").exists())


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
                   DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ImportedDepartmentMappingTests(ImportedMappingFixture, TestCase):
    def test_department_and_employee_capabilities_use_separate_tokens(self):
        data = self.preview().data["data"]
        self.assertTrue(data["can_save_mapping"])
        self.assertTrue(data["preview_token"])
        self.assertEqual(data["snapshot"]["status"], "CONFIG_UNAVAILABLE")
        self.assertFalse(data["snapshot"]["can_submit"])
        self.assertIn("可绑定本地", data["snapshot"]["message"])
        self.assertIn("不能重新读取", data["snapshot"]["message"])
        employee = self.client.get(EMPLOYEES).data["data"]
        self.assertNotIn("can_save_mapping", employee)
        self.assertTrue(employee["preview_token"])
        self.assertTrue(employee["snapshot"]["can_submit"])
        self.assertFalse(employee["snapshot"]["can_refresh"])
        with self.assertRaises(PreconditionFailed):
            require_version(get_config(), etag_for_instance(WeComDirectorySnapshot.objects.get()))
        for suffix, fields in (("sync/", {"user_ids": ["One"]}), ("match/", {
            "user_id": "One", "employee_id": str(self.actor.pk), "employee_etag": etag_for_instance(self.actor),
            "confirmed": True,
        })):
            response = self.client.post(EMPLOYEES + suffix, {"preview_token": data["preview_token"], **fields}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.client.post(ROOT + "refresh/", {}, format="json").status_code, 409)

    def test_save_clear_and_restore_mapping_without_changing_employees_or_grants(self):
        models = (get_user_model(), Employee, EmployeeRoleAssignment, EmployeeOrganizationAssignment, WeComBinding, OrganizationUnit)
        before = [model.objects.count() for model in models]
        response = self.update(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        mapping = WeComDepartmentMapping.objects.get()
        self.assertEqual(mapping.organization_unit_id, self.unit.pk)
        restored = self.preview()
        self.assertEqual(restored.data["data"]["departments"][1]["mapping"]["organization_unit_id"], str(self.unit.pk))
        response = self.update(restored, organization_unit_id=None, organization_etag=None)
        self.assertEqual(response.status_code, 200, response.data)
        mapping.refresh_from_db()
        self.assertIsNone(mapping.organization_unit_id)
        self.assertEqual([model.objects.count() for model in models], before)
        self.assertEqual(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE", actor_employee=self.actor).count(), 2)
        self.assertFalse(WeComConfig.objects.exists())

    def test_session_csrf_and_if_match_are_still_required(self):
        preview = self.preview()
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.admin)
        client.get("/api/auth/me/")
        self.assertEqual(client.put(ROOT + "2/", self.payload(preview), format="json", HTTP_IF_MATCH=preview["ETag"]).status_code, 403)
        self.assertEqual(self.client.put(ROOT + "2/", self.payload(preview), format="json").status_code, 428)
        self.assertEqual(self.client.put(ROOT + "2/", self.payload(preview), format="json", HTTP_IF_MATCH='"wrong"').status_code, 412)
        self.no_mapping_writes()
        response = client.put(ROOT + "2/", self.payload(preview), format="json", HTTP_IF_MATCH=preview["ETag"],
                              HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200, response.data)

    def test_actor_corp_and_signed_preview_are_checked(self):
        preview = self.preview()
        self.assertEqual(self.update(preview, preview_token="invalid").status_code, 400)
        version = signing.loads(preview.data["data"]["preview_token"], salt=services.PREVIEW_SALT)
        self.assertEqual(version["corp_id"], self.corp_id)
        version["corp_id"] = "other-corp"
        body = self.payload(preview, preview_token=signing.dumps(version, salt=services.PREVIEW_SALT))
        response = self.client.put(ROOT + "2/", body, format="json", HTTP_IF_MATCH=f'"{services.digest(version)}"')
        self.assertEqual(response.status_code, 412)
        other = get_user_model().objects.create_user("other-manager", password="test-password")
        employee = Employee.objects.create(user=other, employee_code="IMPORTED_MAPPING_OTHER", display_name="其他管理员")
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="另一组织管理员"),
            role_code="IMPORTED_MAPPING_OTHER", display_name="另一组织管理员")
        permission = Permission.objects.get(content_type__app_label="organizations", codename="manage_organization")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now() - timedelta(hours=1))
        self.client.force_login(other)
        self.assertEqual(self.update(preview).status_code, 400)
        self.no_mapping_writes()

    def test_expired_or_replaced_snapshot_invalidates_old_preview(self):
        preview = self.preview()
        newer = deepcopy(self.envelope)
        newer["fetched_at"] = (timezone.now() - timedelta(seconds=20)).isoformat()
        self.import_copy(newer)
        self.assertEqual(self.update(preview).status_code, 412)
        preview = self.preview()
        WeComDirectorySnapshot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.preview().data["data"]
        self.assertFalse(expired["can_save_mapping"])
        self.assertEqual(expired["preview_token"], "")
        self.assertEqual(self.update(preview).status_code, 412)
        self.no_mapping_writes()

    def test_incomplete_marker_other_corp_or_new_configuration_cannot_save(self):
        original = WeComDirectorySnapshot.objects.get()
        original_directory = deepcopy(original.directory)
        for mutation in ("marker", "corp", "configuration"):
            with self.subTest(mutation=mutation):
                preview = self.preview()
                if mutation == "marker":
                    original.directory.pop("_local_import")
                elif mutation == "corp":
                    original.directory["corp_id"] = "other-corp"
                else:
                    WeComConfig.objects.create(enabled=False)
                original.save()
                data = self.preview().data["data"]
                self.assertFalse(data["can_save_mapping"])
                self.assertEqual(data["preview_token"], "")
                self.assertEqual(self.update(preview).status_code, 412)
                original.directory = deepcopy(original_directory)
                original.save()
                WeComConfig.objects.all().delete()
        self.no_mapping_writes()

    def test_target_state_etag_and_mapping_or_organization_changes_are_rejected(self):
        self.assertEqual(self.update(self.preview(), organization_etag='"wrong"').status_code, 412)
        self.assertEqual(self.update(self.preview(), organization_unit_id=str(uuid4())).status_code, 404)
        self.assertEqual(self.update(self.preview(), source_id=99).status_code, 404)
        self.unit.status = "INACTIVE"
        self.unit.save()
        self.assertEqual(self.update(self.preview()).status_code, 409)
        self.unit.status, self.unit.archived_at = "ACTIVE", timezone.now()
        self.unit.save()
        self.assertEqual(self.update(self.preview()).status_code, 409)
        self.unit.archived_at = None
        self.unit.save()
        preview = self.preview()
        self.unit.unit_name = "变更名称"
        self.unit.save()
        self.assertEqual(self.update(preview).status_code, 412)
        self.no_mapping_writes()
        preview = self.preview()
        WeComDepartmentMapping.objects.create(corp_id=self.corp_id, wecom_department_id=1, wecom_department_name="来源公司")
        self.assertEqual(self.update(preview).status_code, 412)
        self.assertEqual(WeComDepartmentMapping.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE").exists())

    def test_ordinary_organization_manager_can_save_without_employee_or_wecom_management(self):
        worker = get_user_model().objects.create_user("local-org-manager")
        employee = Employee.objects.create(user=worker, employee_code="LOCAL_ORG_MANAGER", display_name="组织管理员")
        self.client.force_login(worker)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        group = Group.objects.create(name="本地组织维护")
        role = RoleProfile.objects.create(
            auth_group=group, role_code="LOCAL_ORG_MAPPING", display_name="本地组织维护")
        permission = Permission.objects.get(content_type__app_label="organizations", codename="manage_organization")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now() - timedelta(hours=1))
        preview = self.preview()
        self.assertEqual(self.client.get(EMPLOYEES).status_code, 403)
        self.assertEqual(self.update(preview).status_code, 200)
        preview = self.preview()
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assertEqual(self.update(preview, organization_unit_id=None).status_code, 403)
        self.assertEqual(WeComDepartmentMapping.objects.get().organization_unit_id, self.unit.pk)
        self.assertEqual(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE").count(), 1)

    def test_audit_failure_rolls_back_mapping(self):
        preview = self.preview()
        with patch.object(services, "audit", side_effect=RuntimeError("audit failed")), self.assertRaises(RuntimeError):
            self.update(preview)
        self.no_mapping_writes()


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ImportedDepartmentMappingConcurrencyTests(ImportedMappingFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.preview_data, self.etag = services.preview_mappings(self.request())

    def request(self):
        request = RequestFactory().put(ROOT + "2/", HTTP_IF_MATCH=getattr(self, "etag", ""))
        request.user = self.admin
        return request

    def save(self):
        return services.update_mapping(self.request(), 2, {"preview_token": self.preview_data["preview_token"],
            "organization_unit_id": self.unit.pk, "organization_etag": etag_for_instance(self.unit), "confirmed": True})

    def thread_run(self, function, pids=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                if pids is not None:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
            return function()
        finally:
            connections.close_all()

    def wait_for_lock(self, pids, future):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if pids:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s AND wait_event_type='Lock')", pids)
                    if cursor.fetchone()[0]:
                        return
            if future.done():
                break
            time.sleep(0.02)
        self.fail("没有观察到预期的真实数据库锁等待")

    def test_same_preview_concurrent_saves_have_one_success_and_one_audit(self):
        barrier = Barrier(2)
        original = services.lock_configuration_and_root

        def synchronize(*args, **kwargs):
            barrier.wait(timeout=10)
            return original(*args, **kwargs)

        def save_result():
            try:
                self.save()
                return "SAVED"
            except PreconditionFailed:
                return "STALE"

        with patch.object(services, "lock_configuration_and_root", side_effect=synchronize), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.thread_run, save_result) for _ in range(2)]
            self.assertCountEqual([future.result(timeout=25) for future in futures], ["SAVED", "STALE"])
        self.assertEqual(WeComDepartmentMapping.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE").count(), 1)

    def test_root_lock_wait_expiry_rejects_without_mapping_or_audit(self):
        pids = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                OrganizationUnit.objects.select_for_update().get(pk=self.root.pk)
                future = pool.submit(self.thread_run, self.save, pids)
                self.wait_for_lock(pids, future)
                WeComDirectorySnapshot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
            with self.assertRaises(PreconditionFailed):
                future.result(timeout=20)
        self.no_mapping_writes()

    def test_target_lock_wait_expiry_rejects_without_mapping_or_audit(self):
        pids = []
        expires = WeComDirectorySnapshot.objects.get().expires_at
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                OrganizationUnit.objects.select_for_update().get(pk=self.unit.pk)
                future = pool.submit(self.thread_run, self.save, pids)
                self.wait_for_lock(pids, future)
                clock = patch("apps.wecom.department_mapping_services.timezone.now", return_value=expires + timedelta(seconds=1))
                clock.start()
            try:
                with self.assertRaises(PreconditionFailed):
                    future.result(timeout=20)
            finally:
                clock.stop()
        self.no_mapping_writes()

    def test_configuration_creation_waits_until_mapping_commit(self):
        writing, release = Event(), Event()
        pids = []
        original = services.audit

        def pause(*args, **kwargs):
            writing.set()
            if not release.wait(timeout=15):
                raise AssertionError("没有释放审计等待点")
            return original(*args, **kwargs)

        with patch.object(services, "audit", side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            saved = pool.submit(self.thread_run, self.save)
            try:
                self.assertTrue(writing.wait(timeout=10))
                configured = pool.submit(self.thread_run, lambda: WeComConfig.objects.create(enabled=False).pk, pids)
                self.wait_for_lock(pids, configured)
            finally:
                release.set()
            self.assertTrue(saved.result(timeout=20))
            self.assertIsNotNone(configured.result(timeout=20))
        data, _ = services.preview_mappings(self.request())
        self.assertFalse(data["can_save_mapping"])
        self.assertEqual(data["departments"], [])
        self.assertEqual(WeComDepartmentMapping.objects.count(), 1)

    def test_import_replacement_before_mapping_lock_invalidates_old_preview(self):
        writing, release = Event(), Event()
        pids = []
        original = WeComDirectorySnapshot.objects.update_or_create
        newer = deepcopy(self.envelope)
        newer["fetched_at"] = (timezone.now() - timedelta(seconds=10)).isoformat()

        def pause(*args, **kwargs):
            writing.set()
            if not release.wait(timeout=15):
                raise AssertionError("没有释放导入等待点")
            return original(*args, **kwargs)

        with patch("apps.wecom.directory_imports.WeComDirectorySnapshot.objects.update_or_create", side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            imported = pool.submit(self.thread_run, lambda: self.import_copy(newer))
            try:
                self.assertTrue(writing.wait(timeout=10))
                saved = pool.submit(self.thread_run, self.save, pids)
                self.wait_for_lock(pids, saved)
            finally:
                release.set()
            self.assertTrue(imported.result(timeout=20)["applied"])
            with self.assertRaises(PreconditionFailed):
                saved.result(timeout=20)
        self.no_mapping_writes()
