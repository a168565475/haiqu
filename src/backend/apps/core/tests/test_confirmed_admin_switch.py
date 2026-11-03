from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from .test_identity_switch_api import FLOW_SETTINGS, IdentitySwitchFixtures


@override_settings(**FLOW_SETTINGS, CONFIRMED_ROLE_POLICY_ENABLED=True)
class ConfirmedAdministratorSwitchTests(IdentitySwitchFixtures, APITestCase):
    def setUp(self):
        self.create_identities()
        employee = self.make_employee('ROLE-GM', 'role-gm', '总经理测试')
        role = RoleProfile.objects.create(role_code='GENERAL_MANAGER', display_name='总经理',
            auth_group=Group.objects.create(name='confirmed-switch-gm'))
        self.assignment = EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
            effective_from=timezone.now())
        self.admin = employee.user

    def test_role_superuser_switches_and_returns_with_real_session_and_csrf(self):
        response = self.enter_flow()
        self.assertFalse(response.data['user']['is_superuser'])
        returned = self.return_admin()
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data['user']['id'], self.admin.pk)
        self.assertTrue(returned.data['user']['is_superuser'])

    def test_role_revocation_during_switch_cannot_restore_superuser(self):
        self.enter_flow()
        self.assignment.delete()
        returned = self.return_admin()
        self.assertEqual(returned.status_code, 403, returned.data)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_superuser)
