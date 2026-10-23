from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.access_control.deletion_services import DELETED_REASON
from apps.access_control.selectors import effective_access
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import (
    Employee,
    EmployeeOrganizationAssignment,
    EmployeeRoleAssignment,
    OrganizationUnit,
    RoleProfile,
)
from apps.wecom.credentials import encrypt_secret
from apps.wecom.models import WeComBinding, WeComConfig, WeComDepartmentMapping


ROOT = "/api/v1/wecom/employee-directory/"
SCHEMA_GATE = "apps.wecom.department_mapping_selectors.schema_is_ready"
TEST_KEY = Fernet.generate_key().decode()


@override_settings(
    WECOM_FERNET_KEYS=[TEST_KEY],
    ACCESS_MANAGEMENT_ENABLED=True,
    DEV_AUTO_LOGIN_ENABLED=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class WeComDirectoryDepartmentTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "", "test-password")
        self.admin_employee = Employee.objects.create(
            user=self.admin, employee_code="DIRECTORY_DEPT_ADMIN", display_name="管理员",
        )
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.config = WeComConfig.objects.create(enabled=True, secret_ciphertext=encrypt_secret("test-secret"))
        self.root, _ = OrganizationUnit.objects.get_or_create(unit_code="HAIQU", defaults={"unit_name": "公司"})
        self.unit = OrganizationUnit.objects.create(unit_code="DIRECTORY_DEPT_ONE", unit_name="生产部", parent=self.root)
        self.other_unit = OrganizationUnit.objects.create(unit_code="DIRECTORY_DEPT_TWO", unit_name="质量部", parent=self.root)
        self.source = {
            "corp_id": self.config.corp_id,
            "departments": [{"id": 1, "parentid": 0, "name": "企业微信公司"}],
            "members": [self.member()],
        }
        client_patch = patch("apps.wecom.directory_services.WeComDirectoryClient")
        self.directory_client = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.directory_client.return_value.read_directory.side_effect = lambda: deepcopy(self.source)

    def member(self, user_id="Member.One", name="新员工", status=1):
        return {
            "userid": user_id, "name": name, "department": [1], "main_department": 1,
            "status": status, "status_label": "未激活" if status == 4 else "已激活",
        }

    def employee(self, code="DIRECTORY_DEPT_EXISTING", account=True):
        user = get_user_model().objects.create_user(code.lower(), password="old-password") if account else None
        return Employee.objects.create(user=user, employee_code=code, display_name="ERP 维护姓名")

    def binding(self, employee, user_id="Member.One"):
        return WeComBinding.objects.create(
            corp_id=self.config.corp_id, user_id=user_id, member_name="原绑定姓名",
            employee=employee, source="MANUAL", created_account=False,
        )

    def mapping(self, source_id=1, unit=None, **fields):
        return WeComDepartmentMapping.objects.create(
            corp_id=self.config.corp_id, wecom_department_id=source_id,
            wecom_department_name=f"企业微信部门 {source_id}", organization_unit=unit or self.unit, **fields,
        )

    def multiple_departments(self):
        self.source["departments"].append({"id": 2, "parentid": 1, "name": "企业微信兼岗部门"})
        self.source["members"][0].update(department=[1, 2], main_department=2)

    def grant(self, employee, permissions):
        group = Group.objects.create(name=f"部门同步角色 {employee.pk}")
        role = RoleProfile.objects.create(
            auth_group=group, role_code=f"DEPT_{employee.pk.hex.upper()}", display_name="部门同步管理员",
        )
        for app_label, codename in permissions:
            permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
            RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
            group.permissions.add(permission)
        EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=timezone.now() - timedelta(hours=1),
        )
        return role

    def preview(self, apply_departments=True):
        response = self.client.post(ROOT + "refresh/", {"apply_departments": "true" if apply_departments else "false"})
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def sync(self, preview, user_ids=None, apply_departments=True, **fields):
        return self.client.post(ROOT + "sync/", {
            "preview_token": preview.data["data"]["preview_token"],
            "user_ids": user_ids if user_ids is not None else ["Member.One"],
            "apply_departments": apply_departments, **fields,
        }, format="json", HTTP_IF_MATCH=preview["ETag"])

    def match(self, preview, employee, apply_departments=True, **fields):
        return self.client.post(ROOT + "match/", {
            "preview_token": preview.data["data"]["preview_token"], "user_id": "Member.One",
            "employee_id": str(employee.pk), "employee_etag": etag_for_instance(employee),
            "confirmed": True, "apply_departments": apply_departments, **fields,
        }, format="json", HTTP_IF_MATCH=preview["ETag"])

    def counts(self):
        return tuple(model.objects.count() for model in (
            Employee, get_user_model(), WeComBinding, EmployeeOrganizationAssignment, EmployeeRoleAssignment, AuditLog,
        ))

    def assert_plan(self, preview, status):
        self.assertTrue(preview.data["data"]["apply_departments"])
        plan = preview.data["data"]["members"][0]["department_plan"]
        self.assertEqual(plan["status"], status)
        self.assertTrue(plan["reason"])
        return plan

    def test_department_preview_is_read_only_and_uses_explicit_erp_mapping(self):
        self.mapping()
        before = self.counts()
        preview = self.preview()
        plan = self.assert_plan(preview, "READY")
        self.assertEqual(plan["assignments"], [{
            "department_id": str(self.unit.pk), "department_name": self.unit.unit_name, "is_primary": True,
        }])
        self.assertEqual(self.counts(), before)

    def deleted_binding(self):
        old = self.employee()
        old.status, old.archived_at, old.archive_reason = "INACTIVE", timezone.now(), DELETED_REASON
        old.save()
        old.user.is_active = False
        old.user.save()
        binding = self.binding(old)
        self.mapping()
        return old, binding

    def test_deleted_employee_recreated_with_mapped_department_and_no_old_permissions(self):
        old, binding = self.deleted_binding()
        role = self.grant(old, [("access_control", "manage_accounts")])
        history = EmployeeOrganizationAssignment.objects.create(employee=old, organization_unit=self.other_unit,
            is_primary=True, effective_from=timezone.now() - timedelta(days=1))
        preview = self.preview()
        self.assertEqual(preview.data["data"]["members"][0]["action"], "RECREATE")
        self.assertIsNone(preview.data["data"]["members"][0]["employee"])
        self.assert_plan(preview, "READY")
        result = self.sync(preview)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"][0]["department_status"], "APPLIED")
        binding.refresh_from_db(); old.refresh_from_db(); old.user.refresh_from_db()
        self.assertNotEqual(binding.employee_id, old.pk)
        self.assertEqual(old.status, "INACTIVE"); self.assertIsNotNone(old.archived_at)
        self.assertFalse(old.user.is_active)
        new = binding.employee
        self.assertNotEqual(new.user_id, old.user_id)
        self.assertFalse(new.user.has_usable_password())
        self.assertEqual(new.organization_assignments.get().organization_unit_id, self.unit.pk)
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee=new).exists())
        self.assertFalse(new.user.groups.exists()); self.assertFalse(new.user.user_permissions.exists())
        self.assertTrue(EmployeeRoleAssignment.objects.filter(employee=old, role_profile=role).exists())
        self.assertTrue(EmployeeOrganizationAssignment.objects.filter(pk=history.pk, employee=old).exists())
        self.assertTrue(AuditLog.objects.filter(action="DIRECTORY_RECREATE", before_data__employee_id=str(old.pk), after_data__employee_id=str(new.pk)).exists())
        count = Employee.objects.count()
        self.assertEqual(self.sync(preview).status_code, 412)
        self.assertEqual(Employee.objects.count(), count)

    def test_deleted_employee_change_or_rebind_invalidates_recreation_preview(self):
        old, binding = self.deleted_binding()
        preview = self.preview()
        old.display_name = "变更后的姓名"
        old.save()
        before = self.counts()
        self.assertEqual(self.sync(preview).status_code, 412)
        self.assertEqual(self.counts(), before)
        preview = self.preview()
        binding.employee = self.employee(code="OTHER_BINDING")
        binding.save()
        before = self.counts()
        self.assertEqual(self.sync(preview).status_code, 412)
        self.assertEqual(self.counts(), before)

    def test_recreation_does_not_restore_inactive_or_other_archived_employees(self):
        old, binding = self.deleted_binding()
        old.archive_reason = "人工离职归档"
        old.save()
        preview = self.preview()
        self.assertEqual(preview.data["data"]["members"][0]["action"], "EXISTING")
        self.assert_plan(preview, "PENDING")
        count = Employee.objects.count()
        self.assertEqual(self.sync(preview).status_code, 200)
        self.assertEqual(Employee.objects.count(), count)
        binding.refresh_from_db(); self.assertEqual(binding.employee_id, old.pk)

    def test_recreation_rejects_invalid_source_and_rolls_back_on_audit_failure(self):
        old, binding = self.deleted_binding()
        self.source["members"][0]["status"] = 2
        self.assertEqual(self.preview().data["data"]["members"][0]["action"], "SKIP")
        self.source["members"][0]["status"] = 1
        preview = self.preview()
        before = self.counts()
        with patch("apps.wecom.directory_services.audit", side_effect=RuntimeError("audit failure")):
            with self.assertRaisesMessage(RuntimeError, "audit failure"):
                self.sync(preview)
        binding.refresh_from_db()
        self.assertEqual(binding.employee_id, old.pk)
        self.assertEqual(self.counts(), before)

    def test_new_employee_receives_mapped_department_without_role_or_permission(self):
        self.mapping()
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="生产部角色"), role_code="DIRECTORY_DEPT_ROLE",
            display_name="生产部角色", department=self.unit,
        )
        permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_accounts")
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"][0]
        self.assertEqual((result["result"], result["department_status"]), ("CREATED", "APPLIED"))
        employee = Employee.objects.select_related("user").get(pk=result["employee_id"])
        assignment = EmployeeOrganizationAssignment.objects.get(employee=employee)
        self.assertEqual(assignment.organization_unit_id, self.unit.pk)
        self.assertTrue(assignment.is_primary)
        self.assertEqual(assignment.assigned_by_employee_id, self.admin_employee.pk)
        self.assertLessEqual(assignment.effective_from, timezone.now())
        self.assertIsNone(assignment.effective_to)
        self.assertFalse(employee.role_assignments.exists())
        self.assertFalse(employee.user.groups.exists())
        self.assertFalse(employee.user.user_permissions.exists())
        self.assertEqual(effective_access(employee.user)["actions"], {})

    def test_unactivated_member_can_receive_mapped_department_before_first_login(self):
        self.mapping()
        self.source["members"][0] = self.member(status=4)
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "APPLIED")
        employee = WeComBinding.objects.select_related("employee__user").get().employee
        self.assertIsNone(employee.user.last_login)
        self.assertFalse(employee.role_assignments.exists())
        self.assertEqual(employee.organization_assignments.count(), 1)

    def test_multiple_departments_preserve_exactly_one_explicit_primary(self):
        self.multiple_departments()
        self.mapping()
        self.mapping(2, self.other_unit)
        plan = self.assert_plan(self.preview(), "READY")
        self.assertEqual({row["department_id"] for row in plan["assignments"]}, {str(self.unit.pk), str(self.other_unit.pk)})
        self.assertEqual([row["department_id"] for row in plan["assignments"] if row["is_primary"]], [str(self.other_unit.pk)])
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        employee = Employee.objects.get(pk=response.data["data"][0]["employee_id"])
        assignments = employee.organization_assignments.all()
        self.assertEqual(assignments.count(), 2)
        self.assertEqual(assignments.get(is_primary=True).organization_unit_id, self.other_unit.pk)

    def test_missing_mapping_keeps_department_pending_but_creates_account(self):
        preview = self.preview()
        plan = self.assert_plan(preview, "PENDING")
        self.assertEqual(plan["assignments"], [])
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["result"], "CREATED")
        self.assertEqual(response.data["data"][0]["department_status"], "PENDING")
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())
        self.assertTrue(WeComBinding.objects.get().employee.user_id)

    def test_equal_department_names_do_not_implicitly_create_mapping(self):
        self.source["departments"][0]["name"] = self.unit.unit_name
        self.assert_plan(self.preview(), "PENDING")
        self.assertFalse(WeComDepartmentMapping.objects.exists())

    def test_partial_mapping_never_creates_partial_department_assignments(self):
        self.multiple_departments()
        self.mapping()
        preview = self.preview()
        self.assert_plan(preview, "PENDING")
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "PENDING")
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_null_mapping_target_keeps_department_pending(self):
        mapping = self.mapping()
        mapping.organization_unit = None
        mapping.save()
        self.assert_plan(self.preview(), "PENDING")
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "PENDING")
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_missing_primary_department_is_not_guessed_even_for_one_department(self):
        self.mapping()
        self.source["members"][0]["main_department"] = None
        preview = self.preview()
        self.assert_plan(preview, "PENDING")
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "PENDING")
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_two_source_departments_mapped_to_same_target_merge_and_preserve_primary(self):
        self.multiple_departments()
        self.mapping()
        self.mapping(2, self.unit)
        preview = self.preview()
        plan = self.assert_plan(preview, "READY")
        self.assertEqual(plan["assignments"], [{"department_id": str(self.unit.pk), "department_name": self.unit.unit_name, "is_primary": True}])
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "APPLIED")
        assignment = EmployeeOrganizationAssignment.objects.get()
        self.assertEqual(assignment.organization_unit_id, self.unit.pk)
        self.assertTrue(assignment.is_primary)

    def test_inactive_or_archived_target_is_not_assigned(self):
        self.mapping()
        for fields in ({"status": "INACTIVE"}, {"status": "ACTIVE", "archived_at": timezone.now()}):
            with self.subTest(fields=fields):
                for key, value in fields.items():
                    setattr(self.unit, key, value)
                self.unit.save()
                self.assert_plan(self.preview(), "PENDING")
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["department_status"], "PENDING")
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())

    def test_mapping_from_another_corporation_is_not_reused(self):
        mapping = self.mapping()
        mapping.corp_id = "wwanothercorp"
        mapping.save()
        self.assert_plan(self.preview(), "PENDING")

    def test_existing_binding_without_department_can_fill_the_missing_assignment(self):
        self.mapping()
        employee = self.employee()
        binding = self.binding(employee)
        before_binding = WeComBinding.objects.values().get(pk=binding.pk)
        before_user = get_user_model().objects.values().get(pk=employee.user_id)
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["result"], "EXISTING")
        self.assertEqual(response.data["data"][0]["department_status"], "APPLIED")
        self.assertEqual(employee.organization_assignments.get().organization_unit_id, self.unit.pk)
        after_binding = WeComBinding.objects.values().get(pk=binding.pk)
        self.assertEqual(after_binding.pop("department_snapshot"), [{"id": 1, "name": "企业微信公司"}])
        self.assertGreater(after_binding.pop("updated_at"), before_binding.pop("updated_at"))
        before_binding.pop("department_snapshot")
        self.assertEqual(after_binding, before_binding)
        self.assertEqual(get_user_model().objects.values().get(pk=employee.user_id), before_user)
        employee.refresh_from_db()
        self.assertEqual(employee.display_name, "ERP 维护姓名")

    def test_historical_current_and_future_assignments_are_preserved_without_replacement(self):
        self.mapping()
        now = timezone.now()
        periods = [
            (now - timedelta(days=10), now - timedelta(days=1)),
            (now - timedelta(days=1), None),
            (now + timedelta(days=1), None),
        ]
        self.source["members"] = []
        user_ids = []
        for index, (start, end) in enumerate(periods):
            employee = self.employee(f"DIRECTORY_DEPT_PERIOD_{index}")
            user_id = f"Period.{index}"
            self.binding(employee, user_id)
            self.source["members"].append(self.member(user_id, f"历史成员 {index}"))
            user_ids.append(user_id)
            EmployeeOrganizationAssignment.objects.create(
                employee=employee, organization_unit=self.other_unit, is_primary=True,
                effective_from=start, effective_to=end, position_title="原岗位",
            )
        before = list(EmployeeOrganizationAssignment.objects.order_by("id").values())
        preview = self.preview()
        self.assertEqual([row["department_plan"]["status"] for row in preview.data["data"]["members"]], ["PRESERVED"] * 3)
        response = self.sync(preview, user_ids)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["department_status"] for row in response.data["data"]], ["PRESERVED"] * 3)
        self.assertEqual(list(EmployeeOrganizationAssignment.objects.order_by("id").values()), before)

    def test_repeated_department_sync_does_not_append_assignments(self):
        self.mapping()
        preview = self.preview()
        first = self.sync(preview)
        self.assertEqual(first.status_code, 200, first.data)
        before = self.counts()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["result"], "EXISTING")
        self.assertEqual(response.data["data"][0]["department_status"], "PRESERVED")
        self.assertEqual(self.counts(), before)

    def test_manual_match_without_history_adds_department_and_preserves_erp_name(self):
        self.mapping()
        employee = self.employee(account=False)
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "MATCHED")
        self.assertEqual(response.data["data"]["department_status"], "APPLIED")
        employee.refresh_from_db()
        self.assertEqual(employee.display_name, "ERP 维护姓名")
        self.assertFalse(employee.user.has_usable_password())
        self.assertEqual(employee.organization_assignments.get().organization_unit_id, self.unit.pk)
        self.assertFalse(employee.role_assignments.exists())

    def test_manual_match_with_history_preserves_history_and_only_binds_identity(self):
        self.mapping()
        employee = self.employee()
        now = timezone.now()
        assignment = EmployeeOrganizationAssignment.objects.create(
            employee=employee, organization_unit=self.other_unit, is_primary=True,
            effective_from=now - timedelta(days=3), effective_to=now - timedelta(days=1),
        )
        before = EmployeeOrganizationAssignment.objects.values().get(pk=assignment.pk)
        response = self.match(self.preview(), employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "MATCHED")
        self.assertEqual(response.data["data"]["department_status"], "PRESERVED")
        self.assertEqual(employee.organization_assignments.count(), 1)
        self.assertEqual(EmployeeOrganizationAssignment.objects.values().get(pk=assignment.pk), before)

    def test_manual_match_pending_department_can_be_retried_without_new_records(self):
        employee = self.employee(account=False)
        preview = self.preview()
        self.assert_plan(preview, "PENDING")
        response = self.match(preview, employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "MATCHED")
        self.assertEqual(response.data["data"]["department_status"], "PENDING")
        before = self.counts()
        response = self.match(preview, employee)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "EXISTING")
        self.assertEqual(response.data["data"]["department_status"], "PENDING")
        self.assertEqual(self.counts(), before)
        self.assertFalse(employee.organization_assignments.exists())

    def test_default_sync_does_not_query_new_mapping_table_or_add_department_status(self):
        with patch(SCHEMA_GATE, return_value=False), CaptureQueriesContext(connection) as queries:
            preview = self.client.post(ROOT + "refresh/")
            self.assertEqual(preview.status_code, 200, preview.data)
            response = self.client.post(ROOT + "sync/", {
                "preview_token": preview.data["data"]["preview_token"], "user_ids": ["Member.One"],
            }, format="json", HTTP_IF_MATCH=preview["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("department_status", response.data["data"][0])
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())
        self.assertFalse(any(WeComDepartmentMapping._meta.db_table in query["sql"] for query in queries.captured_queries))

    def test_default_manual_match_does_not_query_new_mapping_table(self):
        employee = self.employee()
        with patch(SCHEMA_GATE, return_value=False), CaptureQueriesContext(connection) as queries:
            preview = self.preview(False)
            response = self.match(preview, employee, apply_departments=False)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("department_status", response.data["data"])
        self.assertFalse(EmployeeOrganizationAssignment.objects.exists())
        self.assertFalse(any(WeComDepartmentMapping._meta.db_table in query["sql"] for query in queries.captured_queries))

    def test_employee_manager_needs_additional_organization_permission_for_department_mode(self):
        manager = self.employee("DIRECTORY_DEPT_MANAGER")
        self.grant(manager, [("access_control", "manage_accounts")])
        self.client.force_login(manager.user)
        response = self.client.post(ROOT + "refresh/", {"apply_departments": "true"})
        self.assertEqual(response.status_code, 403, response.data)
        self.directory_client.assert_not_called()
        self.preview(False)

    def test_organization_manager_alone_cannot_read_employee_directory(self):
        manager = self.employee("DIRECTORY_DEPT_ORG_ONLY")
        self.grant(manager, [("organizations", "manage_organization")])
        self.client.force_login(manager.user)
        response = self.client.post(ROOT + "refresh/", {"apply_departments": "true"})
        self.assertEqual(response.status_code, 403, response.data)
        self.directory_client.assert_not_called()

    def test_both_effective_management_permissions_allow_department_sync(self):
        self.mapping()
        manager = self.employee("DIRECTORY_DEPT_BOTH")
        self.grant(manager, [("access_control", "manage_accounts"), ("organizations", "manage_organization")])
        self.client.force_login(manager.user)
        response = self.sync(self.preview())
        self.assertEqual(response.status_code, 200, response.data)
        assignment = EmployeeOrganizationAssignment.objects.get(employee_id=response.data["data"][0]["employee_id"])
        self.assertEqual(assignment.assigned_by_employee_id, manager.pk)

    def test_revoked_organization_permission_rejects_sync_and_match(self):
        self.mapping()
        manager = self.employee("DIRECTORY_DEPT_REVOKED")
        target = self.employee("DIRECTORY_DEPT_MATCH_TARGET")
        role = self.grant(manager, [("access_control", "manage_accounts"), ("organizations", "manage_organization")])
        self.client.force_login(manager.user)
        preview = self.preview()
        RoleActionGrant.objects.filter(role=role, permission__codename="manage_organization").delete()
        before = self.counts()
        self.directory_client.reset_mock()
        self.assertEqual(self.sync(preview).status_code, 403)
        self.assertEqual(self.match(preview, target).status_code, 403)
        self.directory_client.assert_not_called()
        self.assertEqual(self.counts(), before)

    def test_default_preview_token_cannot_be_promoted_to_department_mode(self):
        self.mapping()
        employee = self.employee()
        preview = self.preview(False)
        before = self.counts()
        self.assertEqual(self.sync(preview).status_code, 400)
        self.assertEqual(self.match(preview, employee).status_code, 400)
        self.assertEqual(self.counts(), before)

    def test_department_preview_token_cannot_be_downgraded_to_default_mode(self):
        self.mapping()
        employee = self.employee()
        preview = self.preview()
        before = self.counts()
        self.assertEqual(self.sync(preview, apply_departments=False).status_code, 400)
        self.assertEqual(self.match(preview, employee, apply_departments=False).status_code, 400)
        self.assertEqual(self.counts(), before)

    def test_changed_mapping_rejects_batch_before_creating_any_identity(self):
        mapping = self.mapping()
        self.source["members"].append(self.member("Member.Two", "第二员工"))
        preview = self.preview()
        mapping.organization_unit = self.other_unit
        mapping.save()
        before = self.counts()
        response = self.sync(preview, ["Member.One", "Member.Two"])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)

    def test_changed_target_version_rejects_sync_and_manual_match(self):
        self.mapping()
        employee = self.employee()
        preview = self.preview()
        self.unit.unit_name = "生产管理部"
        self.unit.save()
        before = self.counts()
        self.assertEqual(self.sync(preview).status_code, 412)
        self.assertEqual(self.match(preview, employee).status_code, 412)
        self.assertEqual(self.counts(), before)

    def test_pending_preview_does_not_apply_mapping_created_after_preview(self):
        preview = self.preview()
        self.assert_plan(preview, "PENDING")
        self.mapping()
        before = self.counts()
        response = self.sync(preview)
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)

    def test_missing_department_migration_returns_503_for_department_mode_only(self):
        self.mapping()
        employee = self.employee()
        preview = self.preview()
        before = self.counts()
        with patch(SCHEMA_GATE, return_value=False):
            self.assertEqual(self.client.post(ROOT + "refresh/", {"apply_departments": "true"}).status_code, 503)
            self.assertEqual(self.sync(preview).status_code, 503)
            self.assertEqual(self.match(preview, employee).status_code, 503)
            self.preview(False)
        self.assertEqual(self.counts(), before)

    def test_audit_failure_after_assignment_rolls_back_account_binding_and_department(self):
        self.mapping()
        preview = self.preview()
        before = self.counts()
        original_create = AuditLog.objects.create
        failures = []

        def fail_after_assignment(**kwargs):
            if EmployeeOrganizationAssignment.objects.exists():
                failures.append(True)
                raise RuntimeError("部门归属审计失败测试")
            return original_create(**kwargs)

        with patch.object(AuditLog.objects, "create", side_effect=fail_after_assignment):
            with self.assertRaisesMessage(RuntimeError, "部门归属审计失败测试"):
                self.sync(preview)
        self.assertEqual(failures, [True])
        self.assertEqual(self.counts(), before)

    def test_old_preview_does_not_fill_departments_after_another_manager_manually_binds_employee(self):
        self.mapping()
        employee = self.employee()
        manager = self.employee("DIRECTORY_DEPT_OTHER_MANAGER")
        self.grant(manager, [("access_control", "manage_accounts")])
        preview = self.preview()
        self.assertIsNone(preview.data["data"]["members"][0]["employee"])
        self.client.force_login(manager.user)
        response = self.match(self.preview(False), employee, apply_departments=False)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["result"], "MATCHED")
        self.client.force_login(self.admin)
        before = self.counts()
        before_employee = Employee.objects.values().get(pk=employee.pk)
        response = self.sync(preview)
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(self.counts(), before)
        self.assertFalse(employee.organization_assignments.exists())
        self.assertEqual(Employee.objects.values().get(pk=employee.pk), before_employee)
