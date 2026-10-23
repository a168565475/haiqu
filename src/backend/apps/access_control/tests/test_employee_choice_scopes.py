from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from apps.organizations.selectors import active_department_employees, active_role_employees
from apps.customers.api.serializers import CustomerCreateSerializer
from apps.customers.api.complaint_serializers import ComplaintWriteSerializer
from apps.customers.api.governance_serializers import CustomerTransferCreateSerializer
from apps.sales_orders.api.serializers import SalesOrderWriteSerializer
from apps.samples.api.serializers import SampleFeeRecordCreateSerializer
from apps.samples.api.form_serializers import SampleRequestFormSerializer
from apps.production_tasks.api.serializers import ProductionTaskWriteSerializer, ProductionTaskPmcDecisionSerializer
from apps.workflow.api.serializers import TaskCreateSerializer, TaskReassignSerializer, TaskBulkReassignSerializer


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class EmployeeChoiceScopeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("scope-admin", password="test")
        self.admin = Employee.objects.create(user=self.user, employee_code="SCOPE_ADMIN", display_name="管理员")
        self.client.force_login(self.user)
        self.people = {}
        for code in ("BUSINESS", "PRODUCTION", "WAREHOUSE"):
            department, _ = OrganizationUnit.objects.get_or_create(unit_code=f"DEPT_{code}", defaults={"unit_name": code})
            person = Employee.objects.create(employee_code=f"SCOPE_{code}", display_name=code)
            EmployeeOrganizationAssignment.objects.create(employee=person, organization_unit=department, effective_from=timezone.now()-timedelta(days=1))
            self.people[code] = person
        self.role, _ = RoleProfile.objects.get_or_create(role_code="FACTORY_MANAGER", defaults={"display_name": "厂长", "auth_group": Group.objects.create(name="scope-factory")})
        EmployeeRoleAssignment.objects.create(employee=self.people["PRODUCTION"], role_profile=self.role, effective_from=timezone.now()-timedelta(days=1))

    def test_write_fields_reject_people_outside_the_confirmed_department(self):
        cases = [
            (CustomerCreateSerializer, "primary_owner_employee_id", "BUSINESS"),
            (CustomerTransferCreateSerializer, "to_employee_id", "BUSINESS"),
            (ComplaintWriteSerializer, "owner_employee_id", "BUSINESS"),
            (ComplaintWriteSerializer, "collaborator_employee_ids", "BUSINESS"),
            (SalesOrderWriteSerializer, "salesperson_id", "BUSINESS"),
            (SalesOrderWriteSerializer, "merchandiser_id", "BUSINESS"),
            (SampleRequestFormSerializer, "owner_employee_id", "BUSINESS"),
            (ProductionTaskWriteSerializer, "salesperson_id", "BUSINESS"),
            (ProductionTaskWriteSerializer, "follower_ids", "PRODUCTION"),
            (ProductionTaskWriteSerializer, "planner_id", "PRODUCTION"),
            (ProductionTaskPmcDecisionSerializer, "follower_ids", "PRODUCTION"),
            (ProductionTaskPmcDecisionSerializer, "planner_id", "PRODUCTION"),
            (TaskCreateSerializer, "assignee_employee_id", "BUSINESS"),
            (TaskReassignSerializer, "assignee_employee_id", "BUSINESS"),
            (TaskBulkReassignSerializer, "assignee_employee_id", "BUSINESS"),
        ]
        for serializer, name, department in cases:
            with self.subTest(serializer=serializer.__name__, field=name):
                field = serializer().fields[name]
                many = hasattr(field, "child_relation")
                good, bad = str(self.people[department].pk), str(self.admin.pk)
                field.run_validation([good] if many else good)
                with self.assertRaises(ValidationError):
                    field.run_validation([bad] if many else bad)

    def test_factory_manager_is_required_for_both_fee_decisions(self):
        for name in ("free_confirmed_by_employee_id", "approver_employee_id"):
            field = SampleFeeRecordCreateSerializer().fields[name]
            field.run_validation(str(self.people["PRODUCTION"].pk))
            with self.assertRaises(ValidationError):
                field.run_validation(str(self.people["BUSINESS"].pk))
        self.role.archived_at = timezone.now()
        self.role.save(update_fields=["archived_at"])
        self.assertFalse(active_role_employees("FACTORY_MANAGER").exists())

    def test_department_period_state_and_secondary_assignment(self):
        person = self.people["BUSINESS"]
        department = OrganizationUnit.objects.get(unit_code="DEPT_PRODUCTION")
        link = EmployeeOrganizationAssignment.objects.create(employee=person, organization_unit=department, effective_from=timezone.now()+timedelta(days=1))
        self.assertFalse(active_department_employees("DEPT_PRODUCTION").filter(pk=person.pk).exists())
        link.effective_from = timezone.now()-timedelta(days=1)
        link.save()
        self.assertTrue(active_department_employees("DEPT_PRODUCTION").filter(pk=person.pk).exists())
        department.status = "INACTIVE"
        department.save()
        self.assertFalse(active_department_employees("DEPT_PRODUCTION").exists())

    def test_real_options_endpoints_use_the_correct_source(self):
        for url, field, department in [
            ("customers", "owner_options", "BUSINESS"),
            ("inquiries", "owners", "BUSINESS"),
            ("inquiries", "owner_filters", "BUSINESS"),
            ("complaints", "employees", "BUSINESS"),
            ("sales-orders", "employees", "BUSINESS"),
            ("tasks", "assignees", "BUSINESS"),
            ("sample-requests", "owners", "BUSINESS"),
            ("sample-requests", "fee_approvers", "PRODUCTION"),
            ("production-tasks", "employees", "PRODUCTION"),
            ("production-tasks", "salespeople", "BUSINESS"),
            ("finished-goods-inventory", "employees", "WAREHOUSE"),
        ]:
            with self.subTest(url=url, field=field):
                response = self.client.get(f"/api/v1/{url}/options/")
                self.assertEqual(response.status_code, 200, response.data)
                ids = {str(row["id"]) for row in response.data["data"][field]}
                self.assertIn(str(self.people[department].pk), ids)
                self.assertNotIn(str(self.admin.pk), ids)
                for other, person in self.people.items():
                    if other != department:
                        self.assertNotIn(str(person.pk), ids)

    def test_warehouse_service_rejects_nonwarehouse_receiver(self):
        from apps.material_issues.p4_services import _active_employee
        self.assertEqual(_active_employee(self.people["WAREHOUSE"].pk).pk, self.people["WAREHOUSE"].pk)
        with self.assertRaises(ValidationError):
            _active_employee(self.people["PRODUCTION"].pk)

    def test_management_grants_do_not_replace_superadministrator_requirement(self):
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        endpoints = [
            ("post", f"/api/v1/access/employees/{self.people['BUSINESS'].pk}/account/"),
            ("post", "/api/v1/wecom/bindings/"),
            ("get", "/api/v1/wecom/employees/"),
        ]
        with patch("apps.access_control.management_permissions.can_manage", return_value=True):
            for method, url in endpoints:
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403, response.data)
