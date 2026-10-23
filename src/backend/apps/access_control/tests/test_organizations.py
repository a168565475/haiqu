from datetime import timedelta
from io import StringIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.access_control.department_baseline import DEPARTMENTS, baseline_plan
from apps.access_control.models import RoleActionGrant
from apps.access_control.selectors import effective_access

ROOT = "/api/v1/access/"


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class OrganizationApiTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", "admin@example.test", "StrongTestPassword123!")
        Employee.objects.create(user=self.admin, employee_code="ORG_ADMIN", display_name="管理员")
        self.user = get_user_model().objects.create_user("org_worker")
        self.employee = Employee.objects.create(user=self.user, employee_code="ORG_WORKER", display_name="员工")
        self.root = OrganizationUnit.objects.get(unit_code="HAIQU")
        self.unit = OrganizationUnit.objects.create(unit_code="ORG_TEST", unit_name="测试部门", parent=self.root)
        self.role = RoleProfile.objects.create(auth_group=Group.objects.create(name="ORG_ROLE"), role_code="ORG_ROLE", display_name="测试角色")
        self.client.force_login(self.admin)

    def patch_unit(self, data, etag=None):
        return self.client.patch(ROOT + f"departments/{self.unit.pk}/", data, format="json",
                                 HTTP_IF_MATCH=etag or etag_for_instance(self.unit))

    def link(self, department_id, etag=None):
        return self.client.put(ROOT + f"roles/{self.role.pk}/department/", {"department_id": department_id},
                               format="json", HTTP_IF_MATCH=etag or etag_for_instance(self.role))

    def assign(self, rows, etag=None):
        self.employee.refresh_from_db()
        return self.client.put(ROOT + f"employees/{self.employee.pk}/departments/", {"departments": rows},
                               format="json", HTTP_IF_MATCH=etag or etag_for_instance(self.employee))

    def row(self, unit=None, primary=True, title=""):
        return {"department_id": str((unit or self.unit).pk), "is_primary": primary, "position_title": title}

    def test_employee_department_ids_only_include_current_active_departments(self):
        now = timezone.now()
        second = OrganizationUnit.objects.create(unit_code="SECOND", unit_name="兼岗部门", parent=self.root)
        for unit in (self.unit, second):
            EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=unit,
                effective_from=now - timedelta(days=1), is_primary=unit == self.unit)
        for code, status, start, end in [
            ("ENDED", "ACTIVE", now - timedelta(days=3), now - timedelta(days=1)),
            ("FUTURE", "ACTIVE", now + timedelta(days=1), None),
            ("INACTIVE", "INACTIVE", now - timedelta(days=1), None),
            ("ARCHIVED", "ACTIVE", now - timedelta(days=1), None),
        ]:
            unit = OrganizationUnit.objects.create(unit_code=code, unit_name=code, parent=self.root,
                status=status, archived_at=now if code == "ARCHIVED" else None)
            EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=unit,
                effective_from=start, effective_to=end)
        response = self.client.get(ROOT + f"employees/{self.employee.pk}/roles/")
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(response.data["department_ids"], [str(self.unit.pk), str(second.pk)])
        self.assertCountEqual(response.data["department"].split("、"), [self.unit.unit_name, second.unit_name])

    def test_employee_login_summary_counts_only_successful_account_records(self):
        from apps.core.login_records import record_successful_login
        from apps.access_control.api.serializers import AccessEmployeeSerializer
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from types import SimpleNamespace
        request = SimpleNamespace(META={})
        record_successful_login(request, self.user, "PASSWORD")
        record_successful_login(request, self.user, "WECOM")
        record_successful_login(request, self.admin, "PASSWORD")
        self.user.last_login = timezone.now(); self.user.save(update_fields=["last_login"])
        self.employee.refresh_from_db()
        data = AccessEmployeeSerializer(self.employee).data
        self.assertEqual(data["login_count"], 2)
        self.assertIsNotNone(data["last_login"])
        unregistered = Employee.objects.create(employee_code="NO_LOGIN_ACCOUNT", display_name="无账号")
        self.assertIsNone(AccessEmployeeSerializer(unregistered).data["login_count"])
        self.assertIsNone(AccessEmployeeSerializer(unregistered).data["last_login"])
        with CaptureQueriesContext(connection) as queries:
            rows = AccessEmployeeSerializer(Employee.objects.select_related("user").order_by("id"), many=True).data
        self.assertEqual(len([q for q in queries if '"audit_log"' in q["sql"]]), 1)
        self.assertEqual(next(row for row in rows if row["id"] == str(self.employee.pk))["login_count"], 2)

    def test_departments_create_duplicates_invalid_references_and_no_delete(self):
        data = {"unit_code": "NEW_DEP", "unit_name": "新增部门", "parent_id": str(self.root.pk)}
        self.assertEqual(self.client.post(ROOT + "departments/", data, format="json").status_code, 201)
        self.assertEqual(self.client.post(ROOT + "departments/", data, format="json").status_code, 409)
        self.assertEqual(self.client.post(ROOT + "departments/", {**data, "unit_code": "OTHER"}, format="json").status_code, 409)
        data.update(unit_code="BAD_DEP", unit_name="坏引用", parent_id=str(uuid4()))
        self.assertEqual(self.client.post(ROOT + "departments/", data, format="json").status_code, 400)
        self.assertEqual(self.client.delete(ROOT + f"departments/{self.unit.pk}/").status_code, 405)
        self.assertEqual(self.patch_unit({"parent_id": str(self.unit.pk)}).status_code, 400)

    def test_etag_required_and_stale_updates_do_not_overwrite(self):
        url = ROOT + f"departments/{self.unit.pk}/"
        self.assertEqual(self.client.patch(url, {"unit_name": "变化"}, format="json").status_code, 428)
        self.assertEqual(self.patch_unit({"unit_name": "第一次"}).status_code, 200)
        self.assertEqual(self.patch_unit({"unit_name": "第二次"}).status_code, 412)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.unit_name, "第一次")

    def test_role_classification_preserves_grants_members_and_legacy_permissions(self):
        permission = Permission.objects.get(content_type__app_label="sales_orders", codename="view_salesorder")
        self.role.auth_group.permissions.add(permission)
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=self.role, effective_from=timezone.now())
        self.assertEqual(self.link(str(self.unit.pk)).status_code, 200)
        self.assertEqual(self.role.auth_group.permissions.count(), 1)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(employee=self.employee).count(), 1)
        self.assertEqual(self.link(str(self.unit.pk)).status_code, 412)
        self.role.refresh_from_db()
        self.assertEqual(self.link(None).status_code, 200)

    def test_role_rejects_missing_and_inactive_department(self):
        self.assertEqual(self.link(str(uuid4())).status_code, 400)
        self.unit.status = "INACTIVE"; self.unit.save()
        self.assertEqual(self.link(str(self.unit.pk)).status_code, 400)

    def test_department_membership_never_grants_roles_or_permissions(self):
        self.assertEqual(self.assign([self.row()]).status_code, 200)
        self.assertFalse(EmployeeRoleAssignment.objects.filter(employee=self.employee).exists())
        self.assertEqual(effective_access(self.user)["actions"], {})

    def test_multiple_departments_primary_and_history_preserved(self):
        other = OrganizationUnit.objects.create(unit_code="ORG_OTHER", unit_name="兼岗部门")
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=self.role, effective_from=timezone.now())
        self.assertEqual(self.assign([self.row(), self.row(other, False)]).status_code, 200)
        self.assertEqual(self.assign([self.row(other, True, "主任")]).status_code, 200)
        histories = EmployeeOrganizationAssignment.objects.filter(employee=self.employee)
        self.assertEqual(histories.count(), 3)
        self.assertEqual(histories.filter(effective_to__isnull=True, is_primary=True).count(), 1)
        self.assertEqual(EmployeeRoleAssignment.objects.filter(employee=self.employee).count(), 1)
        result = self.client.get(ROOT + f"employees/{self.employee.pk}/departments/")
        self.assertEqual(len(result.data["departments"]), 3)
        self.assertTrue(AuditLog.objects.filter(action="EMPLOYEE_DEPARTMENTS_REPLACE").exists())

    def test_assignment_duplicates_primary_invalid_reference_and_future(self):
        self.assertEqual(self.assign([self.row(), self.row()]).status_code, 400)
        self.assertEqual(self.assign([self.row(primary=False)]).status_code, 400)
        self.assertEqual(self.assign([{**self.row(), "department_id": str(uuid4())}]).status_code, 400)
        EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=self.unit,
                                                      effective_from=timezone.now() + timedelta(days=2))
        self.assertEqual(self.assign([]).status_code, 409)

    def test_employee_etag_shared_with_other_account_role_writers(self):
        old = etag_for_instance(self.employee)
        self.assertEqual(self.assign([self.row()]).status_code, 200)
        self.assertEqual(self.assign([], etag=old).status_code, 412)
        self.employee.status = "LEFT"; self.employee.save()
        self.assertEqual(self.assign([]).status_code, 409)

    def test_editing_current_assignment_keeps_its_scheduled_expiry(self):
        now = timezone.now()
        expiry = now + timedelta(days=5)
        EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=self.unit,
            is_primary=True, effective_from=now - timedelta(days=1), effective_to=expiry)
        self.assertEqual(self.assign([self.row(title="新岗位")]).status_code, 200)
        latest = EmployeeOrganizationAssignment.objects.filter(employee=self.employee).latest("effective_from")
        self.assertEqual(latest.effective_to, expiry)

    def test_deactivate_checks_roles_children_current_and_future_assignments(self):
        self.assertEqual(self.link(str(self.unit.pk)).status_code, 200)
        self.assertEqual(self.patch_unit({"status": "INACTIVE"}).status_code, 409)
        self.role.refresh_from_db(); self.link(None)
        assignment = EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=self.unit,
            effective_from=timezone.now() + timedelta(days=1))
        self.assertEqual(self.patch_unit({"status": "INACTIVE"}).status_code, 409)
        assignment.delete()
        child = OrganizationUnit.objects.create(unit_code="ORG_CHILD", unit_name="下级", parent=self.unit)
        self.assertEqual(self.patch_unit({"status": "INACTIVE"}).status_code, 409)
        child.delete()
        self.assertEqual(self.patch_unit({"status": "INACTIVE"}).status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.patch_unit({"status": "ACTIVE"}).status_code, 200)

    def test_expired_history_does_not_block_deactivation_and_is_retained(self):
        now = timezone.now()
        EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=self.unit,
            effective_from=now - timedelta(days=3), effective_to=now - timedelta(days=1))
        self.assertEqual(self.patch_unit({"status": "INACTIVE"}).status_code, 200)
        self.assertEqual(self.unit.employee_assignments.count(), 1)

    def test_organization_role_permission_is_separate_from_access_management(self):
        permission = Permission.objects.get(content_type__app_label="organizations", codename="manage_organization")
        RoleActionGrant.objects.create(role=self.role, permission=permission, scope="MODULE")
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=self.role, effective_from=timezone.now())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(ROOT + "departments/").status_code, 200)
        self.assertEqual(self.client.get(ROOT + "roles/").status_code, 200)
        self.assertEqual(self.client.post(ROOT + "roles/", {}, format="json").status_code, 403)
        self.assertEqual(self.assign([self.row()]).status_code, 200)
        self.role.archived_at = timezone.now(); self.role.save()
        self.assertEqual(self.client.get(ROOT + "departments/").status_code, 403)

    def test_anonymous_native_permission_inactive_and_csrf_are_denied(self):
        self.client.logout()
        self.assertIn(self.client.get(ROOT + "departments/").status_code, (401, 403))
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label="organizations", codename="manage_organization"))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(ROOT + "departments/").status_code, 403)
        csrf = APIClient(enforce_csrf_checks=True); csrf.force_login(self.admin)
        self.assertEqual(csrf.post(ROOT + "departments/", {"unit_code": "CSRF", "unit_name": "CSRF"}).status_code, 403)
        self.employee.status = "INACTIVE"; self.employee.save()
        self.assertEqual(self.client.get(ROOT + "departments/").status_code, 401)

    def test_baseline_dry_run_apply_repeat_preserves_counts_and_grants(self):
        for _, _, codes in DEPARTMENTS:
            for code in codes:
                RoleProfile.objects.get_or_create(role_code=code, defaults={"display_name": code, "auth_group": Group.objects.create(name="ORG_SEED:" + code)})
        count = OrganizationUnit.objects.count()
        self.assertEqual(len(baseline_plan()["departments"]), 12)
        self.assertEqual(OrganizationUnit.objects.count(), count)
        from django.db import connection
        for _ in range(2):
            call_command("initialize_departments", apply=True, database_name=connection.settings_dict["NAME"], actor_username="admin", stdout=StringIO())
        self.assertEqual(OrganizationUnit.objects.count(), count + 12)
        self.assertEqual(RoleProfile.objects.filter(department__isnull=False).count(), 20)
        self.assertFalse(RoleProfile.objects.filter(department__unit_name="技术支持").exists())
        self.assertEqual(RoleActionGrant.objects.count(), 0)
        self.assertEqual(EmployeeOrganizationAssignment.objects.count(), 0)
