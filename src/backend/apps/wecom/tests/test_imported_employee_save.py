from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event
from io import StringIO
import time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.wecom import directory_services as services
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping, WeComDirectorySnapshot
from apps.wecom.services import create_oauth_state, oauth_login
from apps.wecom.employee_department_snapshots import department_snapshot
from apps.wecom.tests.test_imported_department_mapping import ImportedMappingFixture


ROOT = "/api/v1/wecom/employee-directory/"


class EmployeeSaveFixture(ImportedMappingFixture):
    def setUp(self):
        super().setUp()
        WeComDepartmentMapping.objects.create(corp_id=self.corp_id, wecom_department_id=2,
            wecom_department_name="生产部", organization_unit=self.unit)

    def preview(self, apply=False):
        response = self.client.get(ROOT, {"apply_departments": str(apply).lower()})
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def sync(self, preview, **fields):
        return self.client.post(ROOT + "sync/", {"preview_token": preview.data["data"]["preview_token"],
            "user_ids": ["One"], "apply_departments": preview.data["data"]["apply_departments"], **fields},
            format="json", HTTP_IF_MATCH=preview["ETag"])

    def match(self, preview, employee):
        return self.client.post(ROOT + "match/", {"preview_token": preview.data["data"]["preview_token"],
            "user_id": "One", "employee_id": str(employee.pk), "employee_etag": etag_for_instance(employee),
            "confirmed": True, "apply_departments": preview.data["data"]["apply_departments"]},
            format="json", HTTP_IF_MATCH=preview["ETag"])

    def replace_members(self, members):
        newer = deepcopy(self.envelope)
        newer["fetched_at"] = (timezone.now() - timedelta(seconds=5)).isoformat()
        newer["directory"]["members"] = members
        self.import_copy(newer)

    def assert_no_identity_writes(self, employee_count=1):
        self.assertEqual(Employee.objects.count(), employee_count)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(WeComBinding.objects.exists())
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action__startswith="DIRECTORY_").exists())


@override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()], ACCESS_MANAGEMENT_ENABLED=True,
                   DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ImportedEmployeeSaveTests(EmployeeSaveFixture, TestCase):
    def test_department_snapshot_keeps_missing_values_unknown_and_multiple_ids(self):
        directory = {"departments": [{"id": 2, "name": "生产部"}]}
        self.assertIsNone(department_snapshot(directory, {}))
        self.assertEqual(department_snapshot(directory, {"department": []}), [])
        self.assertEqual(department_snapshot(directory, {"department": [2, 9]}),
                         [{"id": 2, "name": "生产部"}, {"id": 9, "name": None}])

    def test_backfill_defaults_to_dry_run_and_apply_is_idempotent(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.get()
        binding.department_snapshot = None
        binding.save(update_fields=["department_snapshot"])
        count = get_user_model().objects.count()
        call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, stdout=StringIO())
        binding.refresh_from_db()
        self.assertIsNone(binding.department_snapshot)
        for _ in range(2):
            call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, apply=True, stdout=StringIO())
        binding.refresh_from_db()
        self.assertEqual(binding.department_snapshot, [{"id": 2, "name": "生产部"}])
        self.assertEqual(get_user_model().objects.count(), count)
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_backfill_rejects_missing_or_duplicate_source_before_any_write(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.get()
        binding.department_snapshot = None
        binding.save(update_fields=["department_snapshot"])
        snapshot = WeComDirectorySnapshot.objects.get()
        original = deepcopy(snapshot.directory)
        for missing in (True, False):
            directory = deepcopy(original)
            if missing:
                del directory["members"][0]["department"]
            else:
                directory["members"].append(deepcopy(directory["members"][0]))
            snapshot.directory = directory
            snapshot.save(update_fields=["directory"])
            with self.assertRaises(CommandError):
                call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, apply=True, stdout=StringIO())
            binding.refresh_from_db()
            self.assertIsNone(binding.department_snapshot)

    def test_backfill_keeps_multiple_departments_and_unknown_name(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.get()
        binding.department_snapshot = None
        binding.save(update_fields=["department_snapshot"])
        snapshot = WeComDirectorySnapshot.objects.get()
        snapshot.directory["members"][0]["department"] = [2, 9]
        snapshot.save(update_fields=["directory"])
        call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, apply=True, stdout=StringIO())
        binding.refresh_from_db()
        self.assertEqual(binding.department_snapshot, [{"id": 2, "name": "生产部"}, {"id": 9, "name": None}])

    def test_backfill_refuses_expired_source(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.get()
        binding.department_snapshot = None
        binding.save(update_fields=["department_snapshot"])
        snapshot = WeComDirectorySnapshot.objects.get()
        snapshot.expires_at = timezone.now() - timedelta(seconds=1)
        snapshot.fetched_at = snapshot.expires_at - timedelta(minutes=1)
        snapshot.directory["_local_import"]["source_read_at"] = snapshot.fetched_at.isoformat()
        snapshot.save(update_fields=["expires_at", "fetched_at", "directory"])
        with self.assertRaises(CommandError):
            call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, apply=True, stdout=StringIO())
        binding.refresh_from_db()
        self.assertIsNone(binding.department_snapshot)

    def test_backfill_rolls_back_entire_batch_if_second_write_fails(self):
        self.replace_members([
            self.envelope["directory"]["members"][0],
            {**self.envelope["directory"]["members"][0], "userid": "Two", "name": "另一个员工"},
        ])
        self.assertEqual(self.sync(self.preview(), user_ids=["One", "Two"]).status_code, 200)
        WeComBinding.objects.update(department_snapshot=None)
        original_save = WeComBinding.save
        saved = []

        def fail_second(instance, *args, **kwargs):
            saved.append(instance.pk)
            if len(saved) == 2:
                raise RuntimeError("模拟第二次写入失败")
            return original_save(instance, *args, **kwargs)

        with patch.object(WeComBinding, "save", fail_second), self.assertRaises(RuntimeError):
            call_command("backfill_wecom_employee_departments", corp_id=self.corp_id, apply=True, stdout=StringIO())
        self.assertEqual(WeComBinding.objects.filter(department_snapshot__isnull=True).count(), 2)

    def test_save_persists_source_departments_and_list_survives_source_expiry(self):
        saved = self.sync(self.preview())
        self.assertEqual(saved.status_code, 200, saved.data)
        binding = WeComBinding.objects.get()
        expected = [{"id": 2, "name": "生产部"}]
        self.assertEqual(binding.department_snapshot, expected)
        snapshot = WeComDirectorySnapshot.objects.get()
        snapshot.expires_at = timezone.now() - timedelta(seconds=1)
        snapshot.fetched_at = snapshot.expires_at - timedelta(minutes=1)
        snapshot.save(update_fields=["expires_at", "fetched_at"])
        listing = self.client.get("/api/v1/access/employees/")
        self.assertEqual(listing.status_code, 200, listing.data)
        rows = listing.data["data"]
        if isinstance(rows, dict):
            rows = rows["results"]
        employee = next(row for row in rows if row["id"] == str(binding.employee_id))
        self.assertEqual(employee["wecom_departments"], expected)
        actor = next(row for row in rows if row["id"] == str(self.actor.pk))
        self.assertIsNone(actor["wecom_departments"])
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_existing_binding_refreshes_department_snapshot_without_changing_identity(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.get()
        original_employee_id = binding.employee_id
        binding.department_snapshot = None
        binding.save(update_fields=["department_snapshot"])
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["result"], "EXISTING")
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, original_employee_id)
        self.assertEqual(binding.department_snapshot, [{"id": 2, "name": "生产部"}])
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_manual_match_persists_source_departments_and_preserves_employee(self):
        employee = Employee.objects.create(employee_code="SOURCE_DEPARTMENT_MATCH", display_name="已有员工")
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 200, response.data)
        binding = WeComBinding.objects.get(employee=employee)
        self.assertEqual(binding.department_snapshot, [{"id": 2, "name": "生产部"}])
        employee.refresh_from_db()
        self.assertEqual(employee.display_name, "已有员工")
        self.assertFalse(employee.organization_assignments.exists())
        self.assertFalse(employee.role_assignments.exists())

    def test_preview_can_save_without_refresh_and_default_save_is_one_employee_center(self):
        preview = self.preview()
        meta = preview.data["data"]["snapshot"]
        self.assertTrue(meta["can_submit"])
        self.assertFalse(meta["can_refresh"])
        self.assertEqual(meta["status"], "CONFIG_UNAVAILABLE")
        self.assertFalse(preview.data["data"]["apply_departments"])
        self.assert_no_identity_writes()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        binding = WeComBinding.objects.select_related("employee__user").get()
        employee, user = binding.employee, binding.employee.user
        self.assertEqual(response.data["data"][0]["employee_id"], str(employee.pk))
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(user.groups.count() + user.user_permissions.count(), 0)
        self.assertFalse(employee.role_assignments.exists())
        self.assertFalse(employee.organization_assignments.exists())
        listing = self.client.get("/api/v1/access/employees/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(str(employee.pk), str(listing.data))
        repeated = self.sync(preview)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["data"][0]["result"], "EXISTING")
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_CREATE").count(), 1)

    def test_explicit_department_fill_has_no_roles_and_retries_preserve_history(self):
        preview = self.preview(True)
        saved = self.sync(preview)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["data"][0]["department_status"], "APPLIED")
        assignment = EmployeeOrganizationAssignment.objects.get()
        self.assertEqual(assignment.organization_unit_id, self.unit.pk)
        self.assertTrue(assignment.is_primary)
        self.assertFalse(EmployeeRoleAssignment.objects.exists())
        retried = self.sync(preview)
        self.assertEqual(retried.status_code, 200, retried.data)
        self.assertEqual(retried.data["data"][0]["department_status"], "PRESERVED")
        self.assertEqual(EmployeeOrganizationAssignment.objects.count(), 1)

    def test_same_name_needs_manual_confirmation_or_matches_existing_without_overwrite(self):
        target = Employee.objects.create(employee_code="EXISTING_CENTER", display_name="来源姓名")
        preview = self.preview(True)
        self.assertEqual(preview.data["data"]["members"][0]["action"], "REVIEW")
        self.assertEqual(self.sync(preview).status_code, 409)
        self.assert_no_identity_writes(employee_count=2)
        response = self.match(preview, target)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["employee_id"], str(target.pk))
        target.refresh_from_db()
        self.assertEqual(target.display_name, "来源姓名")
        self.assertEqual(Employee.objects.count(), 2)
        self.assertTrue(target.user_id)
        self.assertEqual(target.organization_assignments.get().organization_unit_id, self.unit.pk)
        self.assertFalse(target.role_assignments.exists())
        self.assertEqual(self.match(preview, target).status_code, 200)
        self.assertEqual(WeComBinding.objects.count(), 1)

    def test_confirmed_different_person_can_create_and_existing_inactive_identity_is_preserved(self):
        old = Employee.objects.create(employee_code="OTHER_PERSON", display_name="来源姓名", status="LEFT")
        preview = self.preview()
        response = self.sync(preview, confirmed_new_user_ids=["One"])
        self.assertEqual(response.status_code, 200, response.data)
        employee = WeComBinding.objects.select_related("employee__user").get().employee
        self.assertNotEqual(employee.pk, old.pk)
        employee.status = "INACTIVE"
        employee.save()
        employee.user.is_active = False
        employee.user.save()
        again = self.sync(self.preview(True))
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["data"][0]["result"], "EXISTING")
        employee.refresh_from_db()
        self.assertEqual(employee.status, "INACTIVE")
        self.assertFalse(employee.user.is_active)
        self.assertFalse(employee.organization_assignments.exists())

    def test_invalid_batch_or_audit_error_rolls_back_accounts_employees_bindings_and_departments(self):
        first = deepcopy(self.envelope["directory"]["members"][0])
        second = {**first, "userid": "Two", "name": "第二人", "status": 2, "status_label": "已禁用"}
        self.replace_members([first, second])
        self.assertEqual(self.sync(self.preview(True), user_ids=["One", "Two"]).status_code, 409)
        self.assert_no_identity_writes()
        second.update(status=1, status_label="已激活")
        self.replace_members([first, second])
        preview = self.preview(True)
        original = services.audit
        calls = []

        def fail_on_second_creation(*args, **kwargs):
            if args[2] == "DIRECTORY_CREATE":
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError("test audit failure")
            return original(*args, **kwargs)

        with patch.object(services, "audit", side_effect=fail_on_second_creation), self.assertRaises(RuntimeError):
            self.sync(preview, user_ids=["One", "Two"])
        self.assert_no_identity_writes()

    def test_expiry_replacement_configuration_conflict_and_mapping_change_reject_before_writes(self):
        preview = self.preview()
        self.replace_members(deepcopy(self.envelope["directory"]["members"]))
        self.assertEqual(self.sync(preview).status_code, 412)
        preview = self.preview(True)
        mapping = WeComDepartmentMapping.objects.get()
        mapping.organization_unit = None
        mapping.save()
        self.assertEqual(self.sync(preview).status_code, 412)
        preview = self.preview()
        config = WeComConfig.objects.create(enabled=False)
        self.assertEqual(self.sync(preview).status_code, 412)
        config.delete()
        preview = self.preview()
        WeComDirectorySnapshot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.sync(preview).status_code, 412)
        self.assertFalse(self.preview().data["data"]["snapshot"]["can_submit"])
        self.assert_no_identity_writes()

    def test_csrf_if_match_signature_and_department_mode_are_required(self):
        preview = self.preview()
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        body = {"preview_token": preview.data["data"]["preview_token"], "user_ids": ["One"]}
        self.assertEqual(csrf.post(ROOT + "sync/", body, format="json", HTTP_IF_MATCH=preview["ETag"]).status_code, 403)
        self.assertEqual(self.client.post(ROOT + "sync/", body, format="json").status_code, 428)
        self.assertEqual(self.sync(preview, preview_token=body["preview_token"] + "tampered").status_code, 400)
        self.assertEqual(self.sync(preview, apply_departments=True).status_code, 400)
        self.assertEqual(self.sync(preview, members=[]).status_code, 400)
        self.assert_no_identity_writes()

    def test_expiry_during_last_audit_rolls_back_whole_save_and_match(self):
        original = services.audit
        expires = WeComDirectorySnapshot.objects.get().expires_at
        target = Employee.objects.create(employee_code="AUDIT_WAIT_TARGET", display_name="现有ERP员工")
        for operation in ("save", "match"):
            clock = None

            def expire_after_audit(*args, **kwargs):
                nonlocal clock
                result = original(*args, **kwargs)
                if args[2] in ("DIRECTORY_CREATE", "DIRECTORY_MATCH"):
                    clock = patch("apps.wecom.directory_services.timezone.now", return_value=expires + timedelta(seconds=1))
                    clock.start()
                return result

            preview = self.preview()
            try:
                with patch.object(services, "audit", side_effect=expire_after_audit):
                    response = self.sync(preview) if operation == "save" else self.match(preview, target)
                self.assertEqual(response.status_code, 412, response.data)
            finally:
                if clock:
                    clock.stop()
            self.assert_no_identity_writes(employee_count=2)
            target.refresh_from_db()
            self.assertIsNone(target.user_id)

    def test_other_corp_or_incomplete_source_marker_cannot_issue_save_capability(self):
        row = WeComDirectorySnapshot.objects.get()
        original = deepcopy(row.directory)
        for mutation in ("corp", "marker"):
            preview = self.preview()
            if mutation == "corp":
                row.directory["corp_id"] = "other-corp"
            else:
                row.directory.pop("_local_import")
            row.save()
            data = self.preview().data["data"]
            self.assertFalse(data["snapshot"]["can_submit"])
            self.assertFalse(data["snapshot"]["can_refresh"])
            self.assertEqual(data["preview_token"], "")
            self.assertEqual(self.sync(preview).status_code, 412)
            row.directory = deepcopy(original)
            row.save()
        self.assert_no_identity_writes()

    def test_account_manager_can_save_but_cannot_fill_departments_without_organization_grant(self):
        worker = get_user_model().objects.create_user("local-account-manager")
        employee = Employee.objects.create(user=worker, employee_code="LOCAL_ACCOUNT_MANAGER", display_name="账号管理员")
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="本地账号维护"), role_code="LOCAL_ACCOUNT_SAVE", display_name="账号维护")
        permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_accounts")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now() - timedelta(hours=1))
        self.client.force_login(worker)
        self.assertEqual(self.client.get(ROOT, {"apply_departments": "true"}).status_code, 403)
        preview = self.preview()
        self.assertEqual(self.sync(preview).status_code, 200)
        saved = WeComBinding.objects.select_related("employee").get().employee
        self.assertFalse(saved.organization_assignments.exists())
        self.assertFalse(saved.role_assignments.exists())
        assignment.effective_to = timezone.now()
        assignment.save()
        self.assertEqual(self.sync(preview).status_code, 403)

    def test_later_oauth_reuses_saved_identity_before_and_after_role_authorization(self):
        self.assertEqual(self.sync(self.preview()).status_code, 200)
        binding = WeComBinding.objects.select_related("employee__user").get()
        user_id, employee_id = binding.employee.user_id, binding.employee_id
        config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-secret"))

        def login_request():
            request = RequestFactory().get("/api/auth/wecom/callback/")
            SessionMiddleware(lambda req: None).process_request(request)
            request.session.create()
            request.user = AnonymousUser()
            return request

        with patch("apps.wecom.services.WeComClient") as client:
            client.return_value.get_identity.return_value = {"userid": "one", "corpid": self.corp_id}
            client.return_value.get_member.return_value = {"userid": "one", "name": "企微新姓名", "status": 1}
            request = login_request()
            self.assertEqual(oauth_login(request, create_oauth_state(request, config), "test-code"), "/auth/waiting-role")
            self.assertEqual(request.user.pk, user_id)
            role = RoleProfile.objects.create(auth_group=Group.objects.create(name="后续组织授权"), role_code="LATER_EMPLOYEE_ROLE", display_name="组织授权")
            permission = Permission.objects.get(content_type__app_label="organizations", codename="manage_organization")
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            EmployeeRoleAssignment.objects.create(employee=binding.employee, role_profile=role,
                effective_from=timezone.now() - timedelta(hours=1))
            request = login_request()
            self.assertEqual(oauth_login(request, create_oauth_state(request, config), "test-code"), "/")
            self.assertEqual(request.user.pk, user_id)
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, employee_id)
        self.assertEqual(binding.employee.display_name, "来源姓名")
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action="AUTO_CREATE").exists())


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ImportedEmployeeSaveConcurrencyTests(EmployeeSaveFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.apply = False
        self.preview_data, self.etag = services.preview_directory(self.request())

    def request(self):
        request = RequestFactory().post(ROOT + "sync/", HTTP_IF_MATCH=getattr(self, "etag", ""))
        request.user = self.admin
        return request

    def save(self):
        return services.sync_directory(self.request(), {"preview_token": self.preview_data["preview_token"],
            "user_ids": ["One"], "confirmed_new_user_ids": [], "apply_departments": self.apply})

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
        self.fail("未观察到预期的数据库锁等待")

    def test_parallel_save_and_retry_create_one_complete_identity(self):
        barrier = Barrier(2)
        original = services.lock_configuration

        def synchronize(*args):
            barrier.wait(timeout=10)
            return original(*args)

        with patch.object(services, "lock_configuration", side_effect=synchronize), ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=25)[0] for future in [pool.submit(self.thread_run, self.save) for _ in range(2)]]
        self.assertCountEqual([row["result"] for row in results], ["CREATED", "EXISTING"])
        self.assertEqual(Employee.objects.count(), 2)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="DIRECTORY_CREATE").count(), 1)

    def test_root_lock_expiry_rejects_before_creating_identity(self):
        self.apply = True
        self.preview_data, self.etag = services.preview_directory(self.request(), apply_departments=True)
        pids = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                OrganizationUnit.objects.select_for_update().get(pk=self.root.pk)
                saved = pool.submit(self.thread_run, self.save, pids)
                self.wait_for_lock(pids, saved)
                WeComDirectorySnapshot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
            with self.assertRaises(PreconditionFailed):
                saved.result(timeout=20)
        self.assert_no_identity_writes()

    def test_parallel_save_and_manual_match_reuse_one_external_identity(self):
        target = Employee.objects.create(employee_code="MATCH_RACE_TARGET", display_name="已有ERP姓名")
        barrier = Barrier(2)
        original = services.lock_configuration

        def synchronize(*args):
            barrier.wait(timeout=10)
            return original(*args)

        def match_result():
            try:
                return services.match_directory_employee(self.request(), {
                    "preview_token": self.preview_data["preview_token"], "user_id": "One",
                    "employee_id": target.pk, "employee_etag": etag_for_instance(target), "confirmed": True,
                })["result"]
            except Conflict:
                return "CONFLICT"

        with patch.object(services, "lock_configuration", side_effect=synchronize), ThreadPoolExecutor(max_workers=2) as pool:
            saved = pool.submit(self.thread_run, lambda: self.save()[0]["result"])
            matched = pool.submit(self.thread_run, match_result)
            results = (saved.result(timeout=25), matched.result(timeout=25))
        self.assertIn(results, (("CREATED", "CONFLICT"), ("EXISTING", "MATCHED")))
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 2)
        target.refresh_from_db()
        self.assertEqual(target.display_name, "已有ERP姓名")

    def test_target_lock_expiry_rolls_back_already_prepared_account_employee_and_binding(self):
        self.apply = True
        self.preview_data, self.etag = services.preview_directory(self.request(), apply_departments=True)
        expires, pids = WeComDirectorySnapshot.objects.get().expires_at, []
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                OrganizationUnit.objects.select_for_update().get(pk=self.unit.pk)
                saved = pool.submit(self.thread_run, self.save, pids)
                self.wait_for_lock(pids, saved)
                clock = patch("apps.wecom.directory_services.timezone.now", return_value=expires + timedelta(seconds=1))
                clock.start()
            try:
                with self.assertRaises(PreconditionFailed):
                    saved.result(timeout=20)
            finally:
                clock.stop()
        self.assert_no_identity_writes()

    def test_configuration_creation_waits_for_employee_commit(self):
        writing, release, pids = Event(), Event(), []
        original = services._new_user

        def pause(name):
            writing.set()
            if not release.wait(timeout=15):
                raise AssertionError("未释放员工保存等待点")
            return original(name)

        with patch.object(services, "_new_user", side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            saved = pool.submit(self.thread_run, self.save)
            try:
                self.assertTrue(writing.wait(timeout=10))
                configured = pool.submit(self.thread_run, lambda: WeComConfig.objects.create(enabled=False).pk, pids)
                self.wait_for_lock(pids, configured)
            finally:
                release.set()
            self.assertEqual(saved.result(timeout=20)[0]["result"], "CREATED")
            self.assertIsNotNone(configured.result(timeout=20))
        self.assertEqual(WeComBinding.objects.count(), 1)
        self.assertEqual(Employee.objects.count(), 2)

    def test_import_replacement_while_save_waits_rejects_without_identity(self):
        writing, release, pids = Event(), Event(), []
        original = WeComDirectorySnapshot.objects.update_or_create
        newer = deepcopy(self.envelope)
        newer["fetched_at"] = (timezone.now() - timedelta(seconds=5)).isoformat()

        def pause(*args, **kwargs):
            writing.set()
            if not release.wait(timeout=15):
                raise AssertionError("未释放导入等待点")
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
        self.assert_no_identity_writes()
