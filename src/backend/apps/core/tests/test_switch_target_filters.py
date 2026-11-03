from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import (
    EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from .test_identity_switch_api import FLOW_SETTINGS, IdentitySwitchFixtures


@override_settings(**FLOW_SETTINGS)
class SwitchTargetFilterTests(IdentitySwitchFixtures, APITestCase):
    def setUp(self):
        self.create_identities()
        self.department = OrganizationUnit.objects.create(unit_code="SWITCH_DEP", unit_name="生产部")
        self.role = RoleProfile.objects.create(
            role_code="SWITCH_ROLE", display_name="厂长", auth_group=Group.objects.create(name="switch-role"),
        )
        self.start = timezone.now() - timedelta(days=1)
        EmployeeOrganizationAssignment.objects.create(
            employee=self.employee, organization_unit=self.department, effective_from=self.start,
        )
        EmployeeRoleAssignment.objects.create(
            employee=self.employee, role_profile=self.role, effective_from=self.start,
        )

    def get_targets(self, **params):
        return self.client.get("/api/auth/switch-targets/", params)

    def test_effective_metadata_and_combined_filters_keep_identity_version(self):
        self.login()
        version = self.version()
        response = self.get_targets(department_id=str(self.department.pk), role_id=str(self.role.pk), q="员工甲")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["identity_version"], version)
        self.assertFalse(payload["has_more"])
        self.assertEqual([item["employee_id"] for item in payload["results"]], [str(self.employee.pk)])
        self.assertEqual(payload["results"][0]["departments"], [{"id": str(self.department.pk), "name": "生产部"}])
        self.assertEqual(payload["results"][0]["roles"], [{"id": str(self.role.pk), "name": "厂长"}])
        self.assertEqual(payload["departments"], payload["results"][0]["departments"])
        self.assertEqual(self.get_targets(role_id=str(uuid4())).json()["results"], [])
        self.assertEqual(self.get_targets(q="员工乙", role_id=str(self.role.pk)).json()["results"], [])

    def test_expired_future_archived_and_inactive_affiliations_do_not_match(self):
        self.login()
        for field, value in (("effective_to", timezone.now()), ("effective_from", timezone.now() + timedelta(days=1))):
            with self.subTest(field=field):
                EmployeeOrganizationAssignment.objects.filter(employee=self.employee).update(
                    effective_from=self.start, effective_to=None,
                )
                EmployeeOrganizationAssignment.objects.filter(employee=self.employee).update(**{field: value})
                self.assertEqual(self.get_targets(department_id=str(self.department.pk)).json()["results"], [])
        OrganizationUnit.objects.filter(pk=self.department.pk).update(status="INACTIVE")
        self.assertEqual(self.get_targets().json()["departments"], [])
        RoleProfile.objects.filter(pk=self.role.pk).update(archived_at=timezone.now())
        self.assertEqual(self.get_targets(role_id=str(self.role.pk)).json()["results"], [])
        self.assertEqual(self.get_targets().json()["roles"], [])

    def test_filter_options_and_filtering_are_not_limited_to_first_hundred(self):
        # The selected employee sorts after the first hundred eligible employees.
        first_department = OrganizationUnit.objects.create(unit_code="AAA_SWITCH", unit_name="AAA")
        for index in range(101):
            employee = self.make_employee(f"AAA_SWITCH_{index:03}")
            EmployeeOrganizationAssignment.objects.create(
                employee=employee, organization_unit=first_department, effective_from=self.start,
            )
        self.login()
        default = self.get_targets().json()
        self.assertEqual(len(default["results"]), 100)
        self.assertTrue(default["has_more"])
        self.assertNotIn(str(self.employee.pk), [item["employee_id"] for item in default["results"]])
        self.assertIn({"id": str(self.department.pk), "name": "生产部"}, default["departments"])
        filtered = self.get_targets(department_id=str(self.department.pk), role_id=str(self.role.pk)).json()
        self.assertEqual([item["employee_id"] for item in filtered["results"]], [str(self.employee.pk)])
        self.assertFalse(filtered["has_more"])

    def test_candidates_sort_by_current_department_role_then_name_before_limit(self):
        department = OrganizationUnit.objects.create(unit_code="SORT_DEP", unit_name="AAA")
        roles = [RoleProfile.objects.create(
            role_code=f"SORT_ROLE_{index}", display_name=name,
            auth_group=Group.objects.create(name=f"sort-role-{index}"),
        ) for index, name in enumerate(("AAA", "BBB"))]
        first = self.make_employee("ZZ_SORT", display_name="Alpha")
        second = self.make_employee("AA_SORT", display_name="Beta")
        third = self.make_employee("AB_SORT", display_name="Aardvark")
        without_role = self.make_employee("AC_SORT", display_name="Aaron")
        for employee in (first, second, third, without_role):
            EmployeeOrganizationAssignment.objects.create(
                employee=employee, organization_unit=department, effective_from=self.start,
            )
        for employee, role in ((first, roles[0]), (first, roles[1]), (second, roles[0]), (third, roles[1])):
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=self.start)
        future = OrganizationUnit.objects.create(unit_code="SORT_FUTURE", unit_name="000")
        EmployeeOrganizationAssignment.objects.create(
            employee=second, organization_unit=future, effective_from=timezone.now() + timedelta(days=1),
        )
        self.login()
        rows = self.get_targets().json()["results"]
        self.assertEqual([row["employee_id"] for row in rows], [str(employee.pk) for employee in (
            first, second, third, without_role, self.employee, self.other_employee,
        )])
        self.assertEqual([role["name"] for role in rows[0]["roles"]], ["AAA", "BBB"])
        self.assertEqual([department["name"] for department in rows[1]["departments"]], ["AAA"])

    def test_input_validation_and_original_admin_authorization_remain_enforced(self):
        self.assertEqual(self.get_targets().status_code, 403)
        self.login(self.employee.user)
        self.assertEqual(self.get_targets(role_id=str(self.role.pk)).status_code, 403)
        self.client = type(self.client)(enforce_csrf_checks=True)
        self.login()
        for params in ({"department_id": "invalid"}, {"role_id": "invalid"}, {"q": "x" * 101}):
            self.assertEqual(self.get_targets(**params).status_code, 400)
