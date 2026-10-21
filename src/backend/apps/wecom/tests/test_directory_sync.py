from copy import deepcopy
from datetime import timedelta
import time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import (
    Employee,
    EmployeeOrganizationAssignment,
    EmployeeRoleAssignment,
    RoleProfile,
)
from apps.wecom.client import WeComError
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig


ROOT = "/api/v1/wecom/employee-directory/"
TEST_KEY = Fernet.generate_key().decode()


@override_settings(
    WECOM_FERNET_KEYS=[TEST_KEY],
    ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComDirectorySyncTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.admin_employee = Employee.objects.create(
            user=self.admin, employee_code="DIRECTORY_ADMIN", display_name="管理员",
        )
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.config = WeComConfig.objects.create(
            enabled=True, secret_ciphertext=encrypt_secret("directory-private-secret"),
        )
        self.source = {
            "corp_id": self.config.corp_id,
            "departments": [{"id": 1, "parentid": 0, "name": "公司"}],
            "members": [self.member()],
        }
        client_patch = patch("apps.wecom.directory_services.WeComDirectoryClient")
        self.directory_client = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.directory_client.return_value.read_directory.side_effect = lambda: deepcopy(self.source)

    def member(self, user_id="Member.One", name="新员工", status=1):
        return {
            "userid": user_id, "name": name, "department": [1], "main_department": 1,
            "status": status, "status_label": {1: "已激活", 2: "已禁用", 4: "未激活", 5: "退出企业"}.get(status, "未知"),
        }

    def employee(self, code="DIRECTORY_EXISTING", name="旧员工", account=True, **fields):
        user = get_user_model().objects.create_user(code.lower(), password="old-password") if account else None
        return Employee.objects.create(user=user, employee_code=code, display_name=name, **fields)

    def grant(self, employee, *, scope="MODULE", codename="manage_accounts"):
        group = Group.objects.create(name=f"员工管理 {employee.pk}")
        permission = Permission.objects.get(content_type__app_label="access_control", codename=codename)
        group.permissions.add(permission)
        role = RoleProfile.objects.create(auth_group=group, role_code=f"DIRECTORY_{employee.pk.hex.upper()}", display_name="员工管理员")
        RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
        EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=timezone.now() - timedelta(hours=1),
        )
        return role

    def binding(self, employee, user_id="Member.One"):
        return WeComBinding.objects.create(
            corp_id=self.config.corp_id, user_id=user_id, member_name="原绑定名称",
            employee=employee, source="MANUAL", created_account=False,
        )

    def preview(self):
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def sync(self, preview, user_ids=None, **fields):
        return self.client.post(ROOT + "sync/", {
            "preview_token": preview.data["data"]["preview_token"],
            "user_ids": user_ids if user_ids is not None else ["Member.One"], **fields,
        }, format="json", HTTP_IF_MATCH=preview["ETag"])

    def match(self, preview, employee, **fields):
        return self.client.post(ROOT + "match/", {
            "preview_token": preview.data["data"]["preview_token"], "user_id": "Member.One",
            "employee_id": str(employee.pk), "employee_etag": etag_for_instance(employee),
            "confirmed": True, **fields,
        }, format="json", HTTP_IF_MATCH=preview["ETag"])

    def counts(self):
        return tuple(model.objects.count() for model in (
            Employee, get_user_model(), WeComBinding, EmployeeRoleAssignment, EmployeeOrganizationAssignment,
        ))

    def test_preview_is_read_only_and_exposes_no_credentials(self):
        before = self.counts()
        audit_count = AuditLog.objects.count()
        response = self.preview()
        data = response.data["data"]
        self.assertEqual(data["corp_id"], self.config.corp_id)
        self.assertEqual(data["departments"], self.source["departments"])
        self.assertEqual(data["members"][0]["action"], "CREATE")
        self.assertIsNone(data["members"][0]["employee"])
        self.assertEqual(data["members"][0]["candidates"], [])
        self.assertTrue(data["preview_token"])
        self.assertRegex(response["ETag"], r'^"[a-f0-9]{64}"$')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.counts(), before)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        for secret in ("directory-private-secret", self.config.secret_ciphertext):
            self.assertNotIn(secret, str(response.data))

    def test_ordinary_module_role_can_preview_without_wecom_configuration_permission(self):
        manager = self.employee()
        self.grant(manager)
        self.client.force_login(manager.user)
        self.preview()
        self.assertEqual(self.client.get("/api/v1/wecom/config/").status_code, 403)

    def test_unauthorized_caller_cannot_read_or_write_and_does_not_call_upstream(self):
        self.client.force_login(self.employee().user)
        for method, path in (("get", ROOT), ("post", ROOT + "sync/"), ("post", ROOT + "match/")):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, {}, format="json")
                self.assertEqual(response.status_code, 403)
        self.directory_client.assert_not_called()

    def test_anonymous_caller_is_rejected_before_upstream(self):
        self.client.logout()
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        self.directory_client.assert_not_called()

    def test_direct_permission_and_non_module_role_do_not_grant_management(self):
        employee = self.employee()
        permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_accounts")
        employee.user.user_permissions.add(permission)
        self.grant(employee, scope="OWN")
        self.client.force_login(employee.user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.directory_client.assert_not_called()

    def test_wecom_manager_permission_does_not_grant_employee_sync(self):
        manager = self.employee()
        self.grant(manager, codename="manage_wecom")
        self.client.force_login(manager.user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.directory_client.assert_not_called()

    def test_other_superuser_has_no_implicit_management_access(self):
        account = get_user_model().objects.create_superuser("other_superuser", "", "test-password")
        Employee.objects.create(user=account, employee_code="DIRECTORY_OTHER_ADMIN", display_name="其他管理员")
        self.client.force_login(account)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.directory_client.assert_not_called()

    def test_inactive_employee_cannot_manage_even_as_admin(self):
        self.admin_employee.status = "INACTIVE"
        self.admin_employee.save()
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.directory_client.assert_not_called()

    @override_settings(ACCESS_MANAGEMENT_ENABLED=False)
    def test_disabled_access_management_fails_closed(self):
        self.assertEqual(self.client.get(ROOT).status_code, 503)
        self.directory_client.assert_not_called()

    def test_session_write_requires_csrf(self):
        preview = self.preview()
        employee = self.employee()
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.directory_client.reset_mock()
        bodies = {
            "sync/": {"preview_token": preview.data["data"]["preview_token"], "user_ids": ["Member.One"]},
            "match/": {
                "preview_token": preview.data["data"]["preview_token"], "user_id": "Member.One",
                "employee_id": str(employee.pk), "employee_etag": etag_for_instance(employee), "confirmed": True,
            },
        }
        before = self.counts()
        for path, body in bodies.items():
            with self.subTest(path=path):
                response = csrf_client.post(ROOT + path, body, format="json", HTTP_IF_MATCH=preview["ETag"])
                self.assertEqual(response.status_code, 403)
        self.directory_client.assert_not_called()
        self.assertEqual(self.counts(), before)

    def test_preview_requires_saved_enabled_readable_configuration(self):
        self.config.enabled = False
        self.config.save()
        self.assertEqual(self.client.get(ROOT).status_code, 409)
        self.directory_client.assert_not_called()

    def test_normal_session_and_csrf_can_submit_selected_members(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get("/api/auth/me/")
        self.assertIn("csrftoken", client.cookies)
        login = client.post("/api/auth/login/", {
            "username": "admin", "password": "test-password",
        }, format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(login.status_code, 200, login.content)
        preview = client.get(ROOT)
        self.assertEqual(preview.status_code, 200, preview.data)
        result = client.post(ROOT + "sync/", {
            "preview_token": preview.data["data"]["preview_token"], "user_ids": ["Member.One"],
        }, format="json", HTTP_IF_MATCH=preview["ETag"], HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"][0]["result"], "CREATED")

    def test_unreadable_credentials_do_not_call_upstream_or_create_records(self):
        before = self.counts()
        with override_settings(WECOM_FERNET_KEYS=[Fernet.generate_key().decode()]):
            response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 409)
        self.directory_client.assert_not_called()
        self.assertEqual(self.counts(), before)

    def test_missing_configuration_is_not_created_by_preview(self):
        self.config.delete()
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(WeComConfig.objects.exists())
        self.directory_client.assert_not_called()

    def test_directory_states_and_invalid_names_are_not_silently_activated(self):
        self.source["members"] = [
            self.member("Active", "在职", 1), self.member("Unactivated", "未激活成员", 4),
            self.member("Disabled", "禁用", 2), self.member("Left", "退出", 5),
            self.member("MissingState", "状态缺失", None), self.member("UnknownState", "未知状态", 88),
            self.member("EmptyName", ""), self.member("LongName", "长" * 151),
            self.member("invalid/userid", "不合规账号"),
        ]
        actions = {row["userid"]: row["action"] for row in self.preview().data["data"]["members"]}
        self.assertEqual(actions["Active"], "CREATE")
        self.assertEqual(actions["Unactivated"], "CREATE")
        for user_id in ("Disabled", "Left", "MissingState", "UnknownState", "EmptyName", "LongName", "invalid/userid"):
            self.assertEqual(actions[user_id], "SKIP", user_id)

    def test_duplicate_names_including_inactive_and_archived_require_review(self):
        active = self.employee("DIRECTORY_ACTIVE", name="新员工")
        inactive = self.employee("DIRECTORY_INACTIVE", name=" 新员工 ", status="INACTIVE")
        archived = self.employee("DIRECTORY_ARCHIVED", name="新员工", archived_at=timezone.now())
        row = self.preview().data["data"]["members"][0]
        self.assertEqual(row["action"], "REVIEW")
        self.assertEqual({str(item["id"]) for item in row["candidates"]}, {str(item.pk) for item in (active, inactive, archived)})

    def test_source_peers_with_same_name_require_review_without_erp_candidates(self):
        self.source["members"].append(self.member("Member.Two"))
        for row in self.preview().data["data"]["members"]:
            self.assertEqual(row["action"], "REVIEW")
            self.assertEqual(row["candidates"], [])

    def test_existing_identity_is_case_insensitive_and_erp_details_are_untouched(self):
        employee = self.employee(name="ERP维护姓名", phone="13800000000", email="erp@example.test", status="INACTIVE")
        binding = self.binding(employee, "member.one")
        self.source["members"][0].update(name="外部新姓名", status=2, status_label="已禁用")
        before_employee = Employee.objects.values().get(pk=employee.pk)
        before_binding = WeComBinding.objects.values().get(pk=binding.pk)
        before_user = get_user_model().objects.values().get(pk=employee.user_id)
        preview = self.preview()
        self.assertEqual(preview.data["data"]["members"][0]["action"], "EXISTING")
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["result"], "EXISTING")
        self.assertEqual(Employee.objects.values().get(pk=employee.pk), before_employee)
        self.assertEqual(WeComBinding.objects.values().get(pk=binding.pk), before_binding)
        self.assertEqual(get_user_model().objects.values().get(pk=employee.user_id), before_user)

    def test_sync_creates_employee_account_and_binding_without_roles_or_departments(self):
        before = self.counts()
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"][0]
        self.assertEqual(result["user_id"], "Member.One")
        self.assertEqual(result["result"], "CREATED")
        employee = Employee.objects.select_related("user").get(pk=result["employee_id"])
        self.assertEqual(employee.display_name, "新员工")
        self.assertEqual(employee.status, "ACTIVE")
        self.assertEqual(employee.employee_code, employee.employee_code.upper())
        self.assertFalse(employee.user.has_usable_password())
        self.assertFalse(employee.user.is_staff)
        self.assertFalse(employee.user.is_superuser)
        self.assertFalse(employee.user.groups.exists())
        self.assertFalse(employee.user.user_permissions.exists())
        binding = WeComBinding.objects.get(employee=employee)
        self.assertEqual(binding.user_id, "Member.One")
        self.assertEqual(binding.corp_id, self.config.corp_id)
        self.assertTrue(binding.created_account)
        self.assertEqual(self.counts(), (before[0] + 1, before[1] + 1, before[2] + 1, before[3], before[4]))

    def test_unactivated_member_can_be_precreated_without_login_or_role(self):
        self.source["members"][0] = self.member(status=4)
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        employee = WeComBinding.objects.select_related("employee__user").get().employee
        self.assertIsNone(employee.user.last_login)
        self.assertFalse(employee.role_assignments.exists())

    def test_repeat_submission_reuses_identity_without_duplicate_accounts_or_audits(self):
        preview = self.preview()
        first = self.sync(preview)
        self.assertEqual(first.status_code, 200, first.data)
        before = self.counts()
        audits = AuditLog.objects.count()
        second = self.sync(preview)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["data"][0]["result"], "EXISTING")
        self.assertEqual(second.data["data"][0]["employee_id"], first.data["data"][0]["employee_id"])
        self.assertEqual(self.counts(), before)
        self.assertEqual(AuditLog.objects.count(), audits)

    def test_sync_does_not_create_unselected_members(self):
        self.source["members"].append(self.member("Member.Two", "第二员工"))
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(list(WeComBinding.objects.values_list("user_id", flat=True)), ["Member.One"])

    def test_review_without_explicit_new_person_confirmation_rolls_back_entire_batch(self):
        self.employee(name="重复姓名")
        self.source["members"].append(self.member("Member.Two", "重复姓名"))
        preview = self.preview()
        before = self.counts()
        response = self.sync(preview, ["Member.One", "Member.Two"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_explicit_duplicate_as_new_confirmation_creates_a_separate_employee(self):
        original = self.employee(name="新员工")
        response = self.sync(self.preview(), confirmed_new_user_ids=["Member.One"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(str(response.data["data"][0]["employee_id"]), str(original.pk))
        self.assertFalse(WeComBinding.objects.filter(employee=original).exists())

    def test_new_duplicate_created_after_preview_requires_fresh_manual_review(self):
        preview = self.preview()
        self.employee(name="新员工")
        before = self.counts()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_skipped_member_cannot_be_forced_into_creation(self):
        self.source["members"][0] = self.member(status=2)
        preview = self.preview()
        before = self.counts()
        response = self.sync(preview, confirmed_new_user_ids=["Member.One"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_sync_requires_preview_etag(self):
        preview = self.preview()
        body = {"preview_token": preview.data["data"]["preview_token"], "user_ids": ["Member.One"]}
        before = self.counts()
        self.assertEqual(self.client.post(ROOT + "sync/", body, format="json").status_code, 428)
        self.assertEqual(self.client.post(ROOT + "sync/", body, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertEqual(self.counts(), before)

    def test_unknown_fields_empty_ids_duplicate_ids_and_invalid_confirmation_are_rejected(self):
        preview = self.preview()
        before = self.counts()
        for fields in (
            {"unexpected": True}, {"user_ids": []}, {"user_ids": ["Member.One", "member.one"]},
            {"user_ids": "Member.One"}, {"confirmed_new_user_ids": ["Member.Two"]},
        ):
            with self.subTest(fields=fields):
                response = self.sync(preview, **fields)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(self.counts(), before)

    def test_tampered_or_expired_preview_token_cannot_create_accounts(self):
        preview = self.preview()
        token = preview.data["data"]["preview_token"]
        before = self.counts()
        response = self.sync(preview, preview_token=token + "tampered")
        self.assertEqual(response.status_code, 400, response.data)
        with patch("django.core.signing.time.time", return_value=time.time() + 601):
            response = self.sync(preview)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.counts(), before)

    def test_preview_token_is_bound_to_the_requesting_account(self):
        preview = self.preview()
        manager = self.employee()
        self.grant(manager)
        self.client.force_login(manager.user)
        before = self.counts()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.counts(), before)

    def test_changed_source_rejects_submit_without_partial_writes(self):
        preview = self.preview()
        before = self.counts()
        self.source["members"][0]["name"] = "预览后改名"
        response = self.sync(preview)
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)

    def test_changed_configuration_rejects_submit(self):
        preview = self.preview()
        before = self.counts()
        self.config.agent_id = "1000099"
        self.config.save()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)

    def test_upstream_failure_is_safe_and_never_creates_partial_records(self):
        preview = self.preview()
        before = self.counts()
        self.directory_client.return_value.read_directory.side_effect = WeComError(
            "UPSTREAM_UNAVAILABLE", "RAW_PRIVATE_UPSTREAM_TOKEN",
        )
        response = self.sync(preview)
        self.assertEqual(response.status_code, 502, response.data)
        self.assertNotIn("RAW_PRIVATE_UPSTREAM_TOKEN", str(response.data))
        self.assertEqual(self.counts(), before)

    def test_unknown_programming_failure_rolls_back_previous_batch_rows_and_is_not_swallowed(self):
        self.source["members"].append(self.member("Member.Two", "第二员工"))
        preview = self.preview()
        before = self.counts()
        audit_count = AuditLog.objects.count()
        original_create = WeComBinding.objects.create
        calls = 0

        def create_binding(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("同步写入失败测试")
            return original_create(**kwargs)

        with patch.object(WeComBinding.objects, "create", side_effect=create_binding):
            with self.assertRaisesMessage(RuntimeError, "同步写入失败测试"):
                self.sync(preview, ["Member.One", "Member.Two"])
        self.assertEqual(calls, 2)
        self.assertEqual(self.counts(), before)
        self.assertEqual(AuditLog.objects.count(), audit_count)

    def test_manual_match_preserves_erp_profile_password_groups_and_roles(self):
        employee = self.employee(phone="13800000000", email="erp@example.test")
        role = self.grant(employee)
        employee.user.groups.add(role.auth_group)
        before_employee = Employee.objects.values().get(pk=employee.pk)
        before_user = get_user_model().objects.values().get(pk=employee.user_id)
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "MATCHED")
        self.assertEqual(str(response.data["data"]["employee_id"]), str(employee.pk))
        self.assertEqual(Employee.objects.values().get(pk=employee.pk), before_employee)
        self.assertEqual(get_user_model().objects.values().get(pk=employee.user_id), before_user)
        self.assertTrue(employee.user.check_password("old-password"))
        self.assertTrue(employee.user.groups.filter(pk=role.auth_group_id).exists())
        self.assertTrue(employee.role_assignments.filter(role_profile=role).exists())
        binding = WeComBinding.objects.get(employee=employee)
        self.assertEqual(binding.source, "MANUAL")
        self.assertFalse(binding.created_account)

    def test_manual_match_creates_account_only_when_employee_has_none(self):
        employee = self.employee(account=False)
        before = self.counts()
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 200, response.data)
        employee.refresh_from_db()
        self.assertFalse(employee.user.has_usable_password())
        self.assertEqual(employee.display_name, "旧员工")
        self.assertTrue(WeComBinding.objects.get(employee=employee).created_account)
        self.assertEqual(self.counts(), (before[0], before[1] + 1, before[2] + 1, before[3], before[4]))

    def test_manual_match_same_identity_and_employee_can_be_retried(self):
        employee = self.employee()
        preview = self.preview()
        first = self.match(preview, employee)
        self.assertEqual(first.status_code, 200, first.data)
        before = self.counts()
        response = self.match(preview, employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "EXISTING")
        self.assertEqual(self.counts(), before)

    def test_manual_match_needs_explicit_confirmation_and_current_employee_etag(self):
        employee = self.employee()
        preview = self.preview()
        before = self.counts()
        self.assertEqual(self.match(preview, employee, confirmed=False).status_code, 400)
        self.assertEqual(self.match(preview, employee, employee_etag='"stale"').status_code, 412)
        self.assertEqual(self.match(preview, employee, unexpected=True).status_code, 400)
        self.assertEqual(self.counts(), before)

    def test_manual_match_cannot_overwrite_either_side_of_an_existing_binding(self):
        first = self.employee("DIRECTORY_FIRST")
        second = self.employee("DIRECTORY_SECOND")
        binding = self.binding(first)
        before = self.counts()
        response = self.match(self.preview(), second)
        self.assertEqual(response.status_code, 409, response.data)
        self.source["members"] = [self.member("Member.Other", "另一成员")]
        response = self.match(self.preview(), first, user_id="Member.Other")
        self.assertEqual(response.status_code, 409, response.data)
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, first.pk)
        self.assertEqual(binding.user_id, "Member.One")
        self.assertEqual(self.counts(), before)

    def test_manual_match_rejects_inactive_archived_or_disabled_employee_accounts(self):
        targets = [
            self.employee("DIRECTORY_STOPPED", status="INACTIVE"),
            self.employee("DIRECTORY_LEFT", status="LEFT"),
            self.employee("DIRECTORY_ARCHIVED", archived_at=timezone.now()),
            self.employee("DIRECTORY_ACCOUNT_STOPPED"),
        ]
        targets[-1].user.is_active = False
        targets[-1].user.save()
        preview = self.preview()
        before = self.counts()
        for employee in targets:
            with self.subTest(employee=employee.employee_code):
                response = self.match(preview, employee)
                self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_manual_match_cannot_attach_to_admin_staff_or_other_superuser(self):
        staff = self.employee("DIRECTORY_STAFF")
        staff.user.is_staff = True
        staff.user.save()
        elevated = self.employee("DIRECTORY_SUPERUSER")
        elevated.user.is_superuser = True
        elevated.user.save()
        preview = self.preview()
        before = self.counts()
        for employee in (self.admin_employee, staff, elevated):
            with self.subTest(employee=employee.employee_code):
                response = self.match(preview, employee)
                self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_manual_match_rejects_ineligible_external_member(self):
        employee = self.employee()
        self.source["members"][0] = self.member(status=5)
        before = self.counts()
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.counts(), before)

    def test_preview_tolerates_identity_created_between_employee_and_binding_reads(self):
        original_filter = WeComBinding.objects.filter
        inserted = []

        def insert_before_binding_read(*args, **kwargs):
            if kwargs == {"corp_id": self.config.corp_id} and not inserted:
                employee = self.employee("DIRECTORY_CONCURRENT", name="并发建档员工")
                inserted.append(employee)
                self.binding(employee)
            return original_filter(*args, **kwargs)

        with patch.object(WeComBinding.objects, "filter", side_effect=insert_before_binding_read):
            preview = self.preview()
        self.assertEqual(len(inserted), 1)
        row = preview.data["data"]["members"][0]
        self.assertEqual(row["action"], "EXISTING")
        self.assertEqual(row["employee"]["id"], str(inserted[0].pk))
        self.assertEqual(row["employee"]["display_name"], "并发建档员工")

    def assert_access_revocation_during_source_read_is_rejected(self, revoke):
        target = self.employee("DIRECTORY_MATCH_TARGET")
        for operation in ("preview", "sync", "match"):
            with self.subTest(operation=operation):
                self.directory_client.return_value.read_directory.side_effect = lambda: deepcopy(self.source)
                manager = self.employee(f"DIRECTORY_REVOKE_{operation.upper()}")
                role = self.grant(manager)
                self.client.force_login(manager.user)
                preview = self.preview() if operation != "preview" else None
                before = self.counts()

                def read_and_revoke():
                    revoke(manager, role)
                    return deepcopy(self.source)

                self.directory_client.return_value.read_directory.side_effect = read_and_revoke
                if operation == "preview":
                    response = self.client.get(ROOT)
                elif operation == "sync":
                    response = self.sync(preview)
                else:
                    response = self.match(preview, target)
                self.assertEqual(response.status_code, 403, response.data)
                self.assertEqual(self.counts(), before)
                self.assertFalse(WeComBinding.objects.exists())

    def test_actor_suspended_during_upstream_read_cannot_preview_sync_or_match(self):
        def suspend(manager, role):
            Employee.objects.filter(pk=manager.pk).update(status="INACTIVE")

        self.assert_access_revocation_during_source_read_is_rejected(suspend)

    def test_role_revoked_during_upstream_read_cannot_preview_sync_or_match(self):
        def revoke(manager, role):
            EmployeeRoleAssignment.objects.filter(employee=manager, role_profile=role).update(effective_to=timezone.now())

        self.assert_access_revocation_during_source_read_is_rejected(revoke)

    def test_explicit_new_person_confirmation_expires_when_candidate_changes(self):
        candidate = self.employee(name="新员工")
        preview = self.preview()
        candidate.phone = "13900000000"
        candidate.save()
        before = self.counts()
        response = self.sync(preview, confirmed_new_user_ids=["Member.One"])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)

    def test_two_same_name_source_members_can_be_explicitly_created_and_retried(self):
        self.source["members"].append(self.member("Member.Two"))
        preview = self.preview()
        user_ids = ["Member.One", "Member.Two"]
        response = self.sync(preview, user_ids, confirmed_new_user_ids=user_ids)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["result"] for row in response.data["data"]], ["CREATED", "CREATED"])
        employee_ids = {row["employee_id"] for row in response.data["data"]}
        self.assertEqual(len(employee_ids), 2)
        self.assertEqual(Employee.objects.filter(pk__in=employee_ids, display_name="新员工").count(), 2)
        before = self.counts()
        response = self.sync(preview, user_ids, confirmed_new_user_ids=user_ids)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["result"] for row in response.data["data"]], ["EXISTING", "EXISTING"])
        self.assertEqual({row["employee_id"] for row in response.data["data"]}, employee_ids)
        self.assertEqual(self.counts(), before)

    def test_unknown_source_identity_cannot_be_submitted_or_manually_matched(self):
        employee = self.employee()
        preview = self.preview()
        before = self.counts()
        response = self.sync(preview, ["Unknown.Member"])
        self.assertEqual(response.status_code, 400, response.data)
        response = self.match(preview, employee, user_id="Unknown.Member")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.counts(), before)
