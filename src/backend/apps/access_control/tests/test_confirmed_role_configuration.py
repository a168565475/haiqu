import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, RoleProfile
from apps.access_control.management.commands.configure_confirmed_roles import role_plan
from apps.access_control.models import RoleActionGrant
from apps.access_control.production_role_templates import GROUP_ONLY_ROLES


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True, CONFIRMED_ROLE_POLICY_ENABLED=True)
class ConfirmedRoleConfigurationTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin')
        Employee.objects.create(user=self.admin, employee_code='CONFIRMED-ADMIN', display_name='配置测试')
        self.role = RoleProfile.objects.create(role_code=GROUP_ONLY_ROLES[0], display_name='普通员工分组测试',
            auth_group=Group.objects.create(name='confirmed-group-only'))
        self.permission = Permission.objects.get(content_type__app_label='finance', codename='add_receipt')
        self.role.auth_group.permissions.add(self.permission)
        RoleActionGrant.objects.create(role=self.role, permission=self.permission, scope='MODULE')
        self.sales = RoleProfile.objects.create(role_code='ACCOUNT_MANAGER', display_name='未规划测试',
            auth_group=Group.objects.create(name='preserve-account-manager'))
        self.sales.auth_group.permissions.add(self.permission)

    def apply(self, digest):
        call_command('configure_confirmed_roles', apply=True, role_code=[self.role.role_code],
            database_name=connection.settings_dict['NAME'], expected_digest=digest,
            actor_username='admin', stdout=io.StringIO())

    def test_preview_reports_exact_revocation_without_writing_and_apply_preserves_sales(self):
        plan = role_plan([self.role.role_code])
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(plan['roles'][0]['removed_group_permissions'], ['finance.add_receipt'])
        self.assertTrue(self.role.action_grants.exists())
        self.apply(plan['digest'])
        self.assertFalse(self.role.action_grants.exists())
        self.assertFalse(self.role.auth_group.permissions.exists())
        self.assertTrue(self.sales.auth_group.permissions.filter(pk=self.permission.pk).exists())
        unchanged = role_plan([self.role.role_code])
        self.assertEqual(unchanged['roles'][0]['revoked'], [])
        self.assertFalse(unchanged['roles'][0]['group_projection_changed'])

    def test_stale_digest_and_native_members_are_blocked_without_changes(self):
        plan = role_plan([self.role.role_code])
        with self.assertRaises(CommandError):
            self.apply('wrong-digest')
        self.assertTrue(self.role.auth_group.permissions.exists())
        self.admin.groups.add(self.role.auth_group)
        plan = role_plan([self.role.role_code])
        self.assertTrue(plan['blockers'])
        with self.assertRaises(CommandError):
            self.apply(plan['digest'])
        self.assertTrue(self.role.action_grants.exists())

    def test_unplanned_roles_cannot_be_selected_for_replacement(self):
        for code in ('SALESPERSON', 'ACCOUNT_MANAGER', 'UNKNOWN'):
            with self.subTest(code=code), self.assertRaises(CommandError):
                role_plan([code])
