from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.material_issues.models import MaterialIssue
from apps.material_issues.services import _validate_relations
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.workshop_config.models import Workshop
from apps.workshop_config.selectors import active_employees


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MasterWorkshopEmployeeTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser("admin", password="test")
        self.actor = Employee.objects.create(user=user, employee_code="MASTER_ADMIN", display_name="管理员")
        self.worker = Employee.objects.create(employee_code="MASTER_WORKER", display_name="生产员工")
        department, _ = OrganizationUnit.objects.get_or_create(unit_code="DEPT_PRODUCTION", defaults={"unit_name": "生产部"})
        self.assignment = EmployeeOrganizationAssignment.objects.create(employee=self.worker, organization_unit=department,
                                                                       effective_from=timezone.now()-timedelta(days=1))
        self.workshop = Workshop.objects.get(name="金工车间")
        self.client.force_login(user)
        self.url = f"/api/v1/workshop-config/employees/{self.worker.pk}/"

    def configure(self):
        self.worker.refresh_from_db()
        return self.client.patch(self.url, {"workshop": str(self.workshop.pk), "position": "操作工", "is_supervisor": False},
                                 format="json", HTTP_IF_MATCH=etag_for_instance(self.worker))

    def test_roster_uses_master_ids_without_creating_employee_records(self):
        count = Employee.objects.count()
        response = self.client.get("/api/v1/workshop-config/employees/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [str(self.worker.pk)])
        self.assertEqual(Employee.objects.count(), count)
        self.assertNotIn("workshop_config_employee", connection.introspection.table_names())
        self.assertIn(self.client.post("/api/v1/workshop-config/employees/", {}, format="json").status_code, (403, 405))

    def test_roster_displays_current_department_and_roles(self):
        role = RoleProfile.objects.create(
            auth_group=Group.objects.create(name="生产跟单角色"),
            role_code="PRODUCTION_FOLLOWER",
            display_name="生产跟单",
        )
        EmployeeRoleAssignment.objects.create(
            employee=self.worker,
            role_profile=role,
            effective_from=timezone.now() - timedelta(days=1),
        )

        response = self.client.get("/api/v1/workshop-config/employees/")

        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"][0]
        self.assertEqual(row["department"], self.assignment.organization_unit.unit_name)
        self.assertEqual(row["roles"], "生产跟单")

    def test_edit_only_workshop_fields_and_clear_without_removing_master(self):
        count = Employee.objects.count()
        response = self.configure()
        self.assertEqual(response.status_code, 200, response.data)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.workshop_id, self.workshop.pk)
        self.assertEqual(self.worker.workshop_position, "操作工")
        self.assertEqual(self.worker.display_name, "生产员工")
        self.assertTrue(EmployeeOrganizationAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertEqual(Employee.objects.count(), count)
        self.assertNotIn("workshop", self.client.get("/api/v1/access/employees/").data["data"][0])
        response = self.client.delete(self.url, HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(response.status_code, 204, response.data)
        self.worker.refresh_from_db()
        self.assertIsNone(self.worker.workshop_id)
        self.assertEqual(self.worker.workshop_position, "")
        self.assertEqual(Employee.objects.count(), count)

    def test_concurrency_and_department_removal(self):
        stale = etag_for_instance(self.worker)
        self.assertEqual(self.configure().status_code, 200)
        response = self.client.patch(self.url, {"position": "新岗位"}, format="json", HTTP_IF_MATCH=stale)
        self.assertEqual(response.status_code, 412, response.data)
        self.assignment.effective_to = timezone.now()
        self.assignment.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertFalse(active_employees(Employee.objects.filter(pk=self.worker.pk)).exists())

    def test_production_consumers_require_arranged_active_production_employee(self):
        self.assertFalse(active_employees(Employee.objects.filter(pk=self.worker.pk)).exists())
        self.assertEqual(self.configure().status_code, 200)
        self.worker.refresh_from_db()
        issue = MaterialIssue(workshop=self.workshop, recipient_workshop_employee=self.worker)
        _validate_relations(issue, lock_employee=True)
        self.assertEqual(issue.recipient_workshop_employee_id, self.worker.pk)
        self.assertEqual(issue.recipient_name_snapshot, "生产员工")
        self.worker.workshop_status = "LEFT"
        self.worker.save()
        self.assertFalse(active_employees(Employee.objects.filter(pk=self.worker.pk)).exists())

    def test_history_keeps_name_when_master_is_unlinked(self):
        issue = MaterialIssue.objects.create(issue_number="MASTER-HISTORY", client_request_id=uuid4(), request_payload_hash="x"*64,
                                            recipient_name_snapshot="历史领料人", created_by_employee=self.actor, updated_by_employee=self.actor)
        response = self.client.get(f"/api/v1/material-issues/{issue.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["recipient"], {"id": None, "name": "历史领料人"})

    def test_forbidden_identity_write_and_incomplete_assignment(self):
        for payload in ({"name": "替换姓名"}, {"employee": str(self.actor.pk)}, {"workshop": str(self.workshop.pk)}):
            response = self.client.patch(self.url, payload, format="json", HTTP_IF_MATCH=etag_for_instance(self.worker))
            self.assertEqual(response.status_code, 400, response.data)
