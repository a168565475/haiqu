from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.access_control.models import RoleActionGrant

URL = "/api/v1/access/employees/adjust-selected/"


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class EmployeeBatchTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="TestPassword123!")
        Employee.objects.create(user=self.admin, employee_code="BATCH_ADMIN", display_name="管理员")
        self.employees = [Employee.objects.create(employee_code=f"BATCH_{i}", display_name=f"员工{i}") for i in range(2)]
        self.old = OrganizationUnit.objects.create(unit_code="BATCH_OLD", unit_name="原部门")
        self.new = OrganizationUnit.objects.create(unit_code="BATCH_NEW", unit_name="新部门")
        self.role = RoleProfile.objects.create(auth_group=Group.objects.create(name="BATCH_ROLE"), role_code="BATCH_ROLE", display_name="新角色", department=self.new)
        self.old_role = RoleProfile.objects.create(auth_group=Group.objects.create(name="BATCH_OLD_ROLE"), role_code="BATCH_OLD_ROLE", display_name="原角色", department=self.old)
        for employee in self.employees:
            EmployeeOrganizationAssignment.objects.create(employee=employee, organization_unit=self.old, is_primary=True, effective_from=timezone.now() - timedelta(days=1))
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=self.old_role, effective_from=timezone.now() - timedelta(days=1))
        self.client.force_login(self.admin)

    def payload(self, **changes):
        for employee in self.employees:
            employee.refresh_from_db()
        return {"items": [{"id": str(e.pk), "etag": etag_for_instance(e)} for e in self.employees],
                "department_ids": [], "role_ids": [], **changes}

    def post(self, **changes):
        return self.client.post(URL, self.payload(**changes), format="json")

    def test_combined_replacement_preserves_history_and_audits_every_employee(self):
        response = self.post(department_ids=[str(self.new.pk)], role_ids=[str(self.role.pk)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated_count"], 2)
        for employee in self.employees:
            self.assertEqual(employee.organization_assignments.get(effective_to__isnull=True).organization_unit_id, self.new.pk)
            self.assertEqual(EmployeeRoleAssignment.objects.get(employee=employee, effective_to__isnull=True).role_profile_id, self.role.pk)
            self.assertEqual(employee.organization_assignments.count(), 2)
            self.assertEqual(EmployeeRoleAssignment.objects.filter(employee=employee).count(), 2)
        self.assertEqual(AuditLog.objects.filter(action__in=["EMPLOYEE_DEPARTMENTS_REPLACE", "EMPLOYEE_ROLES_REPLACE"]).count(), 4)

    def test_department_change_clears_unselected_roles_and_retains_history(self):
        self.assertEqual(self.post(department_ids=[str(self.new.pk)]).status_code, 200)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(role_profile=self.old_role, effective_to__isnull=True).count(), 0)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(role_profile=self.old_role, effective_to__isnull=False).count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="EMPLOYEE_ROLES_REPLACE").count(), 2)

    def test_empty_selections_clear_all_current_departments_and_roles(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(employee__in=self.employees, effective_to__isnull=True).exists())
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee__in=self.employees, effective_to__isnull=True).exists())
        self.assertEqual(EmployeeOrganizationAssignment.objects.filter(employee__in=self.employees).count(), 2)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(employee__in=self.employees).count(), 2)
        self.assertEqual(AuditLog.objects.filter(action__in=["EMPLOYEE_DEPARTMENTS_REPLACE", "EMPLOYEE_ROLES_REPLACE"]).count(), 4)

    def test_clearing_roles_failure_rolls_back_cleared_departments(self):
        last = sorted(self.employees, key=lambda e: e.pk)[-1]
        EmployeeRoleAssignment.objects.create(employee=last, role_profile=self.role, effective_from=timezone.now() + timedelta(days=1))
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(EmployeeOrganizationAssignment.objects.filter(employee__in=self.employees, effective_to__isnull=True).count(), 2)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(role_profile=self.old_role, effective_to__isnull=True).count(), 2)
        self.assertFalse(AuditLog.objects.filter(action="EMPLOYEE_DEPARTMENTS_REPLACE").exists())

    def test_explicit_empty_roles_clears_old_roles_when_changing_departments(self):
        response = self.post(department_ids=[str(self.new.pk)], role_ids=[])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee__in=self.employees, effective_to__isnull=True).exists())

    def test_multiple_departments_merge_role_options_and_preserve_existing_primary(self):
        assignment = self.employees[0].organization_assignments.get(effective_to__isnull=True)
        assignment.position_title = "原岗位"
        assignment.save()
        response = self.post(department_ids=[str(self.new.pk), str(self.old.pk)],
                             role_ids=[str(self.role.pk), str(self.old_role.pk)])
        self.assertEqual(response.status_code, 200, response.data)
        for employee in self.employees:
            active = employee.organization_assignments.filter(effective_to__isnull=True)
            self.assertEqual(set(active.values_list("organization_unit_id", flat=True)), {self.new.pk, self.old.pk})
            self.assertEqual(active.get(is_primary=True).organization_unit_id, self.old.pk)
            self.assertEqual(set(EmployeeRoleAssignment.objects.filter(employee=employee, effective_to__isnull=True)
                                 .values_list("role_profile_id", flat=True)), {self.role.pk, self.old_role.pk})
        self.assertEqual(self.employees[0].organization_assignments.get(effective_to__isnull=True, is_primary=True).position_title, "原岗位")

    def test_new_primary_uses_first_selected_department(self):
        extra = OrganizationUnit.objects.create(unit_code="BATCH_EXTRA", unit_name="另一部门")
        response = self.post(department_ids=[str(extra.pk), str(self.new.pk)])
        self.assertEqual(response.status_code, 200, response.data)
        for employee in self.employees:
            active = employee.organization_assignments.filter(effective_to__isnull=True)
            self.assertEqual(active.count(), 2)
            self.assertEqual(active.get(is_primary=True).organization_unit_id, extra.pk)

    def test_invalid_department_lists_do_not_change_any_employee(self):
        missing_id = uuid4()
        self.assertFalse(OrganizationUnit.objects.filter(pk=missing_id).exists())
        for ids in ([str(self.new.pk)] * 2, [str(self.new.pk), str(missing_id)]):
            response = self.post(department_ids=ids)
            self.assertEqual(response.status_code, 400, response.data)
        self.new.status = "INACTIVE"
        self.new.save()
        self.assertEqual(self.post(department_ids=[str(self.old.pk), str(self.new.pk)]).status_code, 400)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(organization_unit=self.new).exists())

    def test_stale_item_rejects_whole_batch(self):
        data = self.payload(department_ids=[str(self.new.pk)])
        data["items"][1]["etag"] = '"old"'
        self.assertEqual(self.client.post(URL, data, format="json").status_code, 412)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(organization_unit=self.new).exists())

    def test_later_failure_rolls_back_prior_employee_and_audit(self):
        last = sorted(self.employees, key=lambda e: e.pk)[-1]
        EmployeeRoleAssignment.objects.create(employee=last, role_profile=self.role, effective_from=timezone.now() + timedelta(days=1))
        response = self.post(department_ids=[str(self.new.pk)], role_ids=[str(self.role.pk)])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(organization_unit=self.new).exists())
        self.assertFalse(AuditLog.objects.filter(action="EMPLOYEE_DEPARTMENTS_REPLACE").exists())

    def test_roles_must_match_each_employees_department(self):
        self.assertEqual(self.post(role_ids=[str(self.role.pk)]).status_code, 400)
        self.assertEqual(self.post(department_ids=[str(self.new.pk)], role_ids=[str(self.old_role.pk)]).status_code, 400)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(role_profile=self.old_role, effective_to__isnull=True).count(), 2)

    def test_invalid_empty_duplicate_and_inactive_inputs(self):
        for data in ({"items": []}, {"items": self.payload()["items"]}, self.payload(department_ids=None), self.payload(role_ids=[str(self.role.pk)] * 2)):
            self.assertEqual(self.client.post(URL, data, format="json").status_code, 400)
        for field in ("department_ids", "role_ids"):
            data = self.payload()
            del data[field]
            self.assertEqual(self.client.post(URL, data, format="json").status_code, 400)
        data = self.payload(department_ids=[str(self.new.pk)]); data["items"].append(data["items"][0])
        self.assertEqual(self.client.post(URL, data, format="json").status_code, 400)
        self.employees[1].status = "LEFT"; self.employees[1].save()
        self.assertEqual(self.post(department_ids=[str(self.new.pk)]).status_code, 409)

    def test_permissions_are_checked_for_each_requested_change(self):
        user = get_user_model().objects.create_user("batch_org_manager")
        manager = Employee.objects.create(user=user, employee_code="BATCH_MANAGER", display_name="组织管理员")
        permission = Permission.objects.get(content_type__app_label="organizations", codename="manage_organization")
        RoleActionGrant.objects.create(role=self.old_role, permission=permission, scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=manager, role_profile=self.old_role, effective_from=timezone.now())
        self.client.force_login(user)
        self.assertEqual(self.post(department_ids=[str(self.new.pk)], role_ids=[str(self.role.pk)]).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.post(department_ids=[str(self.new.pk)], role_ids=[]).status_code, 403)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(organization_unit=self.new).exists())

    def test_only_access_permission_cannot_clear_departments(self):
        user = get_user_model().objects.create_user("batch_access_manager")
        manager = Employee.objects.create(user=user, employee_code="BATCH_ACCESS_MANAGER", display_name="角色管理员")
        permission = Permission.objects.get(content_type__app_label="access_control", codename="manage_access")
        RoleActionGrant.objects.create(role=self.old_role, permission=permission, scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=manager, role_profile=self.old_role, effective_from=timezone.now())
        self.client.force_login(user)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(EmployeeOrganizationAssignment.objects.filter(employee__in=self.employees, effective_to__isnull=True).count(), 2)
        self.assertEqual(self.post(department_ids=[str(self.new.pk)]).status_code, 403)
        self.assertEqual(self.post(department_ids=[str(self.new.pk)], role_ids=[]).status_code, 403)
        self.assertFalse(EmployeeOrganizationAssignment.objects.filter(organization_unit=self.new).exists())

    def test_session_csrf_and_anonymous_requests(self):
        csrf = APIClient(enforce_csrf_checks=True); csrf.force_login(self.admin)
        self.assertEqual(csrf.post(URL, self.payload(department_ids=[str(self.new.pk)]), format="json").status_code, 403)
        self.client.logout()
        self.assertIn(self.post(department_ids=[str(self.new.pk)]).status_code, (401, 403))
