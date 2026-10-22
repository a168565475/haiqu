from copy import deepcopy
from datetime import timedelta
import time
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import (
    Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from apps.wecom.client import WeComError
from apps.wecom.credentials import encrypt_secret
from apps.wecom.department_mapping_selectors import mapping_snapshot
from apps.wecom.department_mapping_services import require_mapping_source
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping


ROOT = "/api/v1/wecom/department-mappings/"
TEST_KEY = Fernet.generate_key().decode()


@override_settings(
    WECOM_FERNET_KEYS=[TEST_KEY], ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComDepartmentMappingTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.actor = Employee.objects.create(user=self.admin, employee_code="MAPPING_ADMIN", display_name="映射管理员")
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("mapping-private-secret"))
        self.root = OrganizationUnit.objects.get(unit_code="HAIQU")
        self.unit = OrganizationUnit.objects.create(unit_code="MAPPING_TARGET", unit_name="映射目标部门", parent=self.root)
        self.source = {
            "corp_id": self.config.corp_id,
            "departments": [{"id": 1, "parentid": 0, "name": "公司"}, {"id": 2, "parentid": 1, "name": self.unit.unit_name}],
            "members": [{"userid": "private-member-id", "name": "不应出现在映射页的成员",
                         "department": [2], "main_department": 2, "status": 1, "status_label": "已激活"}],
        }
        upstream_patch = patch("apps.wecom.department_mapping_services.WeComDirectoryClient")
        self.upstream = upstream_patch.start()
        self.addCleanup(upstream_patch.stop)
        self.upstream.return_value.read_directory.side_effect = lambda: deepcopy(self.source)

    def employee(self, code="MAPPING_WORKER"):
        user = get_user_model().objects.create_user(code.lower())
        return Employee.objects.create(user=user, employee_code=code, display_name="组织管理员")

    def grant(self, employee, app="organizations", codename="manage_organization", scope="MODULE"):
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name=f"映射角色 {employee.pk}"),
            role_code=f"MAPPING_{employee.pk.hex.upper()}", display_name="组织管理员",
        )
        role.auth_group.permissions.add(permission)
        RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
        return EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=timezone.now() - timedelta(hours=1),
        )

    def preview(self):
        response = self.client.post(ROOT + "refresh/")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def payload(self, preview, **fields):
        return {"preview_token": preview.data["data"]["preview_token"], "organization_unit_id": str(self.unit.pk),
                "organization_etag": etag_for_instance(self.unit), "confirmed": True, **fields}

    def update(self, preview, department_id=2, **fields):
        return self.client.put(ROOT + f"{department_id}/", self.payload(preview, **fields), format="json",
                               HTTP_IF_MATCH=preview["ETag"])

    def mapping(self, department_id=2, **fields):
        return WeComDepartmentMapping.objects.create(corp_id=self.config.corp_id, wecom_department_id=department_id,
            wecom_department_name="原来源名称", organization_unit=self.unit, **fields)

    def test_preview_is_read_only_and_suggests_without_automatic_mapping(self):
        employee_count = Employee.objects.count()
        audit_count = AuditLog.objects.count()
        preview = self.preview()
        self.assertTrue(preview.data["data"]["can_save_mapping"])
        source = next(row for row in preview.data["data"]["departments"] if row["id"] == 2)
        self.assertIsNone(source["mapping"])
        self.assertEqual(source["candidates"][0]["id"], str(self.unit.pk))
        self.assertFalse(WeComDepartmentMapping.objects.exists())
        self.assertEqual(Employee.objects.count(), employee_count)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        self.assertIn("no-store", preview["Cache-Control"])
        self.assertRegex(preview["ETag"], r'^"[a-f0-9]{64}"$')

    def test_preview_does_not_expose_members_credentials_or_private_config(self):
        text = str(self.preview().data)
        for value in ("private-member-id", "不应出现在映射页的成员", "mapping-private-secret", self.config.secret_ciphertext,
                      "agent_id", "secret_ciphertext", "members"):
            self.assertNotIn(value, text)

    def test_organization_manager_needs_neither_account_nor_wecom_permission(self):
        employee = self.employee()
        self.grant(employee)
        self.client.force_login(employee.user)
        preview = self.preview()
        self.assertEqual(self.update(preview).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/wecom/config/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/wecom/employee-directory/").status_code, 403)

    def test_anonymous_and_unauthorized_callers_fail_before_upstream(self):
        self.client.logout()
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 401)
        self.client.force_login(self.employee().user)
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 403)
        self.assertEqual(self.client.put(ROOT + "2/", {}, format="json").status_code, 403)
        self.upstream.assert_not_called()

    def test_account_or_wecom_management_does_not_grant_organization_management(self):
        for code in ("manage_accounts", "manage_wecom"):
            with self.subTest(permission=code):
                employee = self.employee(code=f"MAP_{code.upper()}")
                self.grant(employee, app="access_control", codename=code)
                self.client.force_login(employee.user)
                self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 403)
        self.upstream.assert_not_called()

    def test_direct_permission_and_own_scope_do_not_grant_organization_management(self):
        employee = self.employee()
        self.grant(employee, scope="OWN")
        employee.user.user_permissions.add(Permission.objects.get(content_type__app_label="organizations", codename="manage_organization"))
        self.client.force_login(employee.user)
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 403)
        self.upstream.assert_not_called()

    def test_disabled_employee_is_rejected(self):
        self.actor.status = "INACTIVE"
        self.actor.save()
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 403)
        self.upstream.assert_not_called()

    def test_permission_is_rechecked_after_source_validation(self):
        employee = self.employee()
        assignment = self.grant(employee)
        self.client.force_login(employee.user)
        preview = self.preview()

        def revoke_permission(*args):
            directory = require_mapping_source(*args)
            assignment.effective_to = timezone.now()
            assignment.save()
            return directory

        with patch("apps.wecom.department_mapping_services.require_mapping_source", side_effect=revoke_permission):
            self.assertEqual(self.update(preview).status_code, 403)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_permission_is_rechecked_before_preview_returns(self):
        employee = self.employee()
        assignment = self.grant(employee)
        self.client.force_login(employee.user)

        def revoke_permission():
            assignment.effective_to = timezone.now()
            assignment.save()
            return deepcopy(self.source)

        self.upstream.return_value.read_directory.side_effect = revoke_permission
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 403)

    def test_missing_mapping_migration_is_reported_before_querying_new_table(self):
        with patch("apps.wecom.department_mapping_selectors.schema_is_ready", return_value=False):
            self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 503)
            self.assertEqual(self.client.put(ROOT + "2/", {}, format="json").status_code, 503)
        self.upstream.assert_not_called()

    def test_missing_or_disabled_configuration_is_conflict(self):
        self.config.enabled = False
        self.config.save()
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 409)
        self.config.delete()
        self.assertEqual(self.client.post(ROOT + "refresh/").status_code, 409)
        self.upstream.assert_not_called()

    def test_upstream_error_is_safe_and_never_writes(self):
        self.upstream.return_value.read_directory.side_effect = WeComError("PRIVATE", "不可泄露上游数据")
        response = self.client.post(ROOT + "refresh/")
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("不可泄露上游数据", str(response.data))
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_invalid_and_expired_preview_tokens_are_rejected(self):
        preview = self.preview()
        self.assertEqual(self.update(preview, preview_token="invalid").status_code, 400)
        old_time = time.time() - 601
        with patch("django.core.signing.time.time", return_value=old_time):
            old_preview = self.preview()
        self.assertEqual(self.update(old_preview).status_code, 400)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_preview_cannot_be_replayed_by_another_actor(self):
        preview = self.preview()
        employee = self.employee()
        self.grant(employee)
        self.client.force_login(employee.user)
        self.assertEqual(self.update(preview).status_code, 400)

    def test_if_match_is_required_and_must_match_preview(self):
        preview = self.preview()
        self.assertEqual(self.client.put(ROOT + "2/", self.payload(preview), format="json").status_code, 428)
        self.assertEqual(self.client.put(ROOT + "2/", self.payload(preview), format="json", HTTP_IF_MATCH='"wrong"').status_code, 412)

    def test_confirmation_target_version_and_strict_fields_are_required(self):
        preview = self.preview()
        for fields in ({"confirmed": False}, {"organization_etag": None}, {"extra": "unsupported"}):
            with self.subTest(fields=fields):
                self.assertEqual(self.update(preview, **fields).status_code, 400)
        body = self.payload(preview)
        body.pop("confirmed")
        self.assertEqual(self.client.put(ROOT + "2/", body, format="json", HTTP_IF_MATCH=preview["ETag"]).status_code, 400)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_csrf_is_required_for_session_write(self):
        preview = self.preview()
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.put(ROOT + "2/", self.payload(preview), format="json", HTTP_IF_MATCH=preview["ETag"])
        self.assertEqual(response.status_code, 403)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_source_change_including_member_changes_invalidates_preview(self):
        preview = self.preview()
        self.source["members"][0]["name"] = "来源变化"
        self.preview()  # 主动刷新来源后，旧预览版本不能继续保存。
        self.assertEqual(self.update(preview).status_code, 412)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_config_change_invalidates_preview(self):
        preview = self.preview()
        self.config.erp_origin = "https://changed.example.test"
        self.config.save()
        self.assertEqual(self.update(preview).status_code, 412)

    def test_config_change_while_reading_source_invalidates_submission(self):
        preview = self.preview()

        def change_config(*args):
            directory = require_mapping_source(*args)
            self.config.enabled = False
            self.config.save()
            return directory

        with patch("apps.wecom.department_mapping_services.require_mapping_source", side_effect=change_config):
            self.assertEqual(self.update(preview).status_code, 412)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_binding_uses_valid_snapshot_without_another_network_read(self):
        preview = self.preview()
        self.upstream.reset_mock()
        self.upstream.return_value.read_directory.side_effect = AssertionError("绑定不应重新读取通讯录")
        response = self.update(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.upstream.assert_not_called()
        self.assertEqual(WeComDepartmentMapping.objects.get().organization_unit_id, self.unit.pk)

    def test_mapping_change_invalidates_preview(self):
        preview = self.preview()
        self.mapping()
        self.assertEqual(self.update(preview).status_code, 412)

    def test_any_erp_organization_change_invalidates_preview(self):
        preview = self.preview()
        self.unit.unit_name = "新部门名"
        self.unit.save()
        self.assertEqual(self.update(preview).status_code, 412)

    def test_target_etag_must_match_even_with_valid_preview(self):
        self.assertEqual(self.update(self.preview(), organization_etag='"wrong"').status_code, 412)

    def test_nonexistent_source_and_invalid_uint32_are_rejected(self):
        preview = self.preview()
        self.assertEqual(self.update(preview, department_id=99).status_code, 404)
        for department_id in (0, 4294967296):
            with self.subTest(department_id=department_id):
                self.assertEqual(self.update(preview, department_id=department_id).status_code, 400)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_missing_target_is_rejected(self):
        self.assertEqual(self.update(self.preview(), organization_unit_id=str(uuid4())).status_code, 404)

    def test_inactive_and_archived_targets_cannot_be_mapped(self):
        self.unit.status = "INACTIVE"
        self.unit.save()
        self.assertEqual(self.update(self.preview()).status_code, 409)
        self.unit.status = "ACTIVE"
        self.unit.archived_at = timezone.now()
        self.unit.save()
        self.assertEqual(self.update(self.preview()).status_code, 409)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_save_records_mapping_and_audit_without_assigning_employee_or_roles(self):
        models = (Employee, get_user_model(), WeComBinding, EmployeeRoleAssignment, EmployeeOrganizationAssignment, OrganizationUnit)
        before = [model.objects.count() for model in models]
        response = self.update(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        mapping = WeComDepartmentMapping.objects.get()
        self.assertEqual(mapping.organization_unit_id, self.unit.pk)
        self.assertEqual(mapping.wecom_department_name, self.unit.unit_name)
        self.assertEqual(response.data["data"]["organization_unit_id"], str(self.unit.pk))
        self.assertTrue(response.data["data"]["organization_active"])
        self.assertEqual([model.objects.count() for model in models], before)
        audit = AuditLog.objects.get(action="DEPARTMENT_MAPPING_UPDATE")
        self.assertEqual(audit.actor_employee_id, self.actor.pk)
        self.assertEqual(audit.after_data["organization_unit_id"], str(self.unit.pk))

    def test_clearing_retains_mapping_record_and_audit_without_target_version(self):
        mapping = self.mapping()
        preview = self.preview()
        body = self.payload(preview, organization_unit_id=None)
        body.pop("organization_etag")
        response = self.client.put(ROOT + "2/", body, format="json", HTTP_IF_MATCH=preview["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        mapping.refresh_from_db()
        self.assertIsNone(mapping.organization_unit_id)
        self.assertEqual(response.data["data"]["id"], str(mapping.pk))
        self.assertIsNone(response.data["data"]["organization_etag"])
        self.assertFalse(response.data["data"]["organization_active"])
        self.assertEqual(AuditLog.objects.filter(action="DEPARTMENT_MAPPING_UPDATE").count(), 1)

    def test_mapping_change_requires_fresh_preview_for_next_save(self):
        preview = self.preview()
        self.assertEqual(self.update(preview).status_code, 200)
        self.assertEqual(self.update(preview).status_code, 412)
        self.assertEqual(self.update(self.preview(), organization_unit_id=None, organization_etag=None).status_code, 200)

    def test_multiple_source_departments_can_map_to_same_target(self):
        self.assertEqual(self.update(self.preview(), department_id=1).status_code, 200)
        self.assertEqual(self.update(self.preview(), department_id=2).status_code, 200)
        self.assertEqual(WeComDepartmentMapping.objects.filter(organization_unit=self.unit).count(), 2)

    def test_audit_failure_rolls_back_mapping_write(self):
        preview = self.preview()
        with patch("apps.wecom.department_mapping_services.audit", side_effect=RuntimeError("审计写入失败")):
            with self.assertRaisesMessage(RuntimeError, "审计写入失败"):
                self.update(preview)
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_mapping_snapshot_has_stable_source_order_and_target_versions(self):
        later = self.mapping(department_id=9)
        earlier = self.mapping(department_id=2)
        snapshot = mapping_snapshot(self.config.corp_id)
        self.assertEqual([row["id"] for row in snapshot["mappings"]], [str(earlier.pk), str(later.pk)])
        self.assertEqual(snapshot["mappings"][0]["organization_etag"], etag_for_instance(self.unit))
        self.assertEqual(mapping_snapshot("other-corp"), {"mappings": []})

    def test_database_enforces_uint32_identity_and_protects_target(self):
        self.mapping()
        for department_id in (0, 4294967296):
            with self.subTest(department_id=department_id), self.assertRaises(IntegrityError), transaction.atomic():
                self.mapping(department_id=department_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.mapping()
        with self.assertRaises(ProtectedError):
            self.unit.delete()
        self.mapping(department_id=4294967295)
        WeComDepartmentMapping.objects.create(corp_id="another-corp", wecom_department_id=2,
            wecom_department_name="其他企业部门", organization_unit=self.unit)
        self.assertEqual(WeComDepartmentMapping.objects.count(), 3)
