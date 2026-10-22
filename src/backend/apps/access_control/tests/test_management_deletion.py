from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.wecom.models import WeComBinding
from apps.access_control.deletion_services import DELETED_REASON
from apps.access_control.models import RoleActionGrant


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ManagementDeletionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "", "test-pass")
        self.actor = Employee.objects.create(user=self.user, employee_code="DELETE_ADMIN", display_name="管理员")
        self.client = APIClient()
        self.client.force_login(self.user)

    def employee(self, code="MISTAKE", admin=False):
        user = get_user_model().objects.create_user(code.lower(), is_superuser=admin)
        return Employee.objects.create(user=user, employee_code=code, display_name="误建员工")

    def role(self):
        return RoleProfile.objects.create(auth_group=Group.objects.create(name="delete-role"),
                                          role_code="DELETE_ROLE", display_name="误建角色")

    def preview(self, kind, objects):
        items = [{"id": str(obj.pk), "etag": etag_for_instance(obj)} for obj in objects]
        response = self.client.post(f"/api/v1/access/{kind}/delete-preview/", {"items": items}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return items, response.data

    def delete(self, kind, items, preview, **headers):
        return self.client.post(f"/api/v1/access/{kind}/delete-selected/",
                                {"items": items, "token": preview["token"], "confirmed": True}, format="json",
                                HTTP_IF_MATCH=preview["etag"], **headers)

    def test_unused_employee_and_account_are_deleted_even_when_admin(self):
        employee = self.employee(admin=True)
        user_id, employee_id = employee.user_id, employee.pk
        binding = WeComBinding.objects.create(employee=employee, corp_id="test", user_id="mistake", member_name="误建员工", source="MANUAL")
        items, preview = self.preview("employees", [employee])
        self.assertEqual(preview["rows"][0]["mode"], "DELETE")
        self.assertTrue(Employee.objects.filter(pk=employee_id).exists())
        response = self.delete("employees", items, preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Employee.objects.filter(pk=employee_id).exists())
        self.assertFalse(get_user_model().objects.filter(pk=user_id).exists())
        self.assertFalse(WeComBinding.objects.filter(pk=binding.pk).exists())
        self.assertTrue(AuditLog.objects.filter(object_id=employee_id, action="EMPLOYEE_DELETE").exists())

    def test_referenced_employee_is_hidden_and_sessions_are_revoked_without_history_changes(self):
        employee = self.employee()
        role = self.role()
        assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now()-timedelta(days=1))
        other_client = APIClient(); other_client.force_login(employee.user)
        session_key = other_client.session.session_key
        items, preview = self.preview("employees", [employee])
        self.assertEqual(preview["rows"][0]["mode"], "ARCHIVE")
        self.assertEqual(self.delete("employees", items, preview).status_code, 200)
        employee.refresh_from_db(); employee.user.refresh_from_db(); assignment.refresh_from_db()
        self.assertEqual(employee.archive_reason, DELETED_REASON)
        self.assertFalse(employee.user.is_active)
        self.assertIsNone(assignment.effective_to)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        self.assertNotIn(str(employee.pk), str(self.client.get('/api/v1/access/employees/').data))

    def test_current_admin_can_delete_self_and_still_records_audit(self):
        items, preview = self.preview("employees", [self.actor])
        response = self.delete("employees", items, preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["self_deleted"])
        self.actor.refresh_from_db(); self.user.refresh_from_db()
        self.assertIsNotNone(self.actor.archived_at)
        self.assertFalse(self.user.is_active)
        self.assertTrue(AuditLog.objects.filter(actor_employee=self.actor, action="EMPLOYEE_DELETE").exists())
        self.assertIn(self.client.get('/api/v1/access/employees/').status_code, (401, 403))

    def test_stale_batch_rejects_all_without_partial_delete(self):
        first, second = self.employee(), self.employee("SECOND")
        items, preview = self.preview("employees", [first, second])
        second.display_name = "后来修改"; second.save()
        self.assertEqual(self.delete("employees", items, preview).status_code, 412)
        self.assertEqual(Employee.objects.filter(pk__in=[first.pk, second.pk], archived_at__isnull=True).count(), 2)
        self.assertFalse(AuditLog.objects.filter(action="EMPLOYEE_DELETE").exists())

    def test_new_reference_requires_another_preview(self):
        employee = self.employee()
        items, preview = self.preview("employees", [employee])
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=self.role(), effective_from=timezone.now())
        self.assertEqual(self.delete("employees", items, preview).status_code, 412)
        self.assertTrue(Employee.objects.filter(pk=employee.pk, archived_at__isnull=True).exists())

    def test_unused_role_and_its_own_grants_are_deleted(self):
        role = self.role(); group_id = role.auth_group_id
        permission = Permission.objects.filter(codename="manage_accounts").first()
        RoleActionGrant.objects.create(role=role, permission=permission, scope="MODULE")
        role.auth_group.permissions.add(permission)
        items, preview = self.preview("roles", [role])
        self.assertEqual(self.delete("roles", items, preview).status_code, 200)
        self.assertFalse(RoleProfile.objects.filter(pk=role.pk).exists())
        self.assertFalse(Group.objects.filter(pk=group_id).exists())

    def test_referenced_role_is_hidden_and_native_group_permission_stops(self):
        role = self.role(); employee = self.employee()
        employee.user.groups.add(role.auth_group)
        permission = Permission.objects.filter(codename="manage_accounts").first()
        role.auth_group.permissions.add(permission)
        items, preview = self.preview("roles", [role])
        self.assertEqual(self.delete("roles", items, preview).status_code, 200)
        role.refresh_from_db()
        self.assertEqual(role.archive_reason, DELETED_REASON)
        self.assertFalse(role.auth_group.permissions.exists())
        self.assertNotIn(str(role.pk), str(self.client.get('/api/v1/access/roles/').data))

    def test_department_with_role_is_archived_but_role_reference_survives(self):
        unit = OrganizationUnit.objects.create(unit_code="DELETE_DEPT", unit_name="误建部门")
        role = self.role(); role.department = unit; role.save()
        items, preview = self.preview("departments", [unit])
        self.assertEqual(self.delete("departments", items, preview).status_code, 200)
        unit.refresh_from_db(); role.refresh_from_db()
        self.assertEqual(unit.status, "INACTIVE")
        self.assertEqual(role.department_id, unit.pk)
        self.assertNotIn(str(unit.pk), str(self.client.get('/api/v1/access/departments/').data))

    def test_permission_csrf_and_audit_failure_do_not_delete(self):
        employee = self.employee()
        items, preview = self.preview("employees", [employee])
        self.client.force_login(employee.user)
        self.assertEqual(self.delete("employees", items, preview).status_code, 403)
        self.client = APIClient(enforce_csrf_checks=True); self.client.force_login(self.user)
        self.assertEqual(self.delete("employees", items, preview).status_code, 403)
        self.client = APIClient(); self.client.force_login(self.user)
        with patch('apps.access_control.deletion_services.write_audit_log', side_effect=RuntimeError('审计失败')):
            with self.assertRaisesMessage(RuntimeError, '审计失败'):
                self.delete("employees", items, preview)
        self.assertTrue(Employee.objects.filter(pk=employee.pk, archived_at__isnull=True).exists())

    def test_regular_role_manager_can_delete_with_real_session_and_csrf(self):
        from django.middleware.csrf import _get_new_csrf_string
        manager, target = self.employee("MANAGER"), self.employee("TARGET")
        role = self.role()
        RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(codename="manage_accounts"), scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=manager, role_profile=role, effective_from=timezone.now())
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(manager.user)
        csrf = _get_new_csrf_string()
        self.client.cookies["csrftoken"] = csrf
        self.client.credentials(HTTP_X_CSRFTOKEN=csrf)
        items, preview = self.preview("employees", [target])
        self.assertEqual(self.delete("employees", items, preview).status_code, 200)
        self.assertFalse(Employee.objects.filter(pk=target.pk).exists())

    def test_missing_version_tampered_token_and_invalid_selection_are_rejected(self):
        employee = self.employee()
        items, preview = self.preview("employees", [employee])
        body = {"items": items, "token": preview["token"], "confirmed": True}
        endpoint = "/api/v1/access/employees/delete-selected/"
        self.assertEqual(self.client.post(endpoint, body, format="json").status_code, 428)
        self.assertEqual(self.client.post(endpoint, {**body, "token": "tampered"}, format="json", HTTP_IF_MATCH=preview["etag"]).status_code, 400)
        self.assertEqual(self.client.post(endpoint, {**body, "confirmed": False}, format="json", HTTP_IF_MATCH=preview["etag"]).status_code, 400)
        for invalid in ([], items + items, [{"id": "bad", "etag": "bad"}]):
            self.assertEqual(self.client.post("/api/v1/access/employees/delete-preview/", {"items": invalid}, format="json").status_code, 400)
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())

    def test_uuid_audit_reference_preserves_department_without_foreign_key(self):
        from apps.core.audit import write_audit_log
        unit = OrganizationUnit.objects.create(unit_code="AUDITED_DEPT", unit_name="已有审计部门")
        write_audit_log(object_type="ACCESS_ORGANIZATION", object_id=unit.pk, action="DEPARTMENT_CREATE", actor_employee=self.actor)
        items, preview = self.preview("departments", [unit])
        self.assertEqual(preview["rows"][0]["mode"], "ARCHIVE")
        self.assertEqual(self.delete("departments", items, preview).status_code, 200)
        self.assertTrue(OrganizationUnit.objects.filter(pk=unit.pk, archive_reason=DELETED_REASON).exists())

    def test_unused_department_is_permanently_deleted(self):
        unit = OrganizationUnit.objects.create(unit_code="UNUSED_DEPT", unit_name="误建部门")
        unit_id = unit.pk
        items, preview = self.preview("departments", [unit])
        self.assertEqual(preview["rows"][0]["mode"], "DELETE")
        self.assertEqual(self.delete("departments", items, preview).status_code, 200)
        self.assertFalse(OrganizationUnit.objects.filter(pk=unit_id).exists())
