from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.access_control.models import RoleSuperuserState
from apps.access_control.management_permissions import can_manage
from apps.access_control.permissions import CanManageOrganization
from apps.access_control.selectors import effective_access
from apps.access_control.superuser_services import SUPERUSER_ROLE_CODES, sync_role_superuser


@override_settings(CONFIRMED_ROLE_POLICY_ENABLED=True)
class RoleSuperuserTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('managed-full-user')
        self.employee = Employee.objects.create(user=self.user, employee_code='MANAGED-FULL', display_name='全权角色测试')
        self.role = RoleProfile.objects.create(role_code='GENERAL_MANAGER', display_name='总经理测试',
                                               auth_group=Group.objects.create(name='managed-full-test'))
        self.assignment = EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=self.role,
            effective_from=timezone.now() - timedelta(days=2))

    def test_role_promotes_real_flags_and_expiry_restores_ordinary_user(self):
        sync_role_superuser(self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser and self.user.is_staff)
        self.assertTrue(can_manage(self.user, 'access_control.manage_accounts'))
        self.assertEqual(effective_access(self.user)['roles'][0]['code'], 'GENERAL_MANAGER')
        self.assignment.effective_to = timezone.now() - timedelta(days=1)
        self.assignment.save(update_fields=['effective_to'])
        sync_role_superuser(self.user)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser or self.user.is_staff)
        self.assertFalse(RoleSuperuserState.objects.filter(user=self.user).exists())

    def test_technical_support_role_promotes_but_future_assignment_does_not(self):
        self.role.role_code = next(code for code in SUPERUSER_ROLE_CODES if code != 'GENERAL_MANAGER')
        self.role.save(update_fields=['role_code'])
        self.assignment.effective_from = timezone.now() + timedelta(days=1)
        self.assignment.save(update_fields=['effective_from'])
        sync_role_superuser(self.user)
        self.assertFalse(self.user.is_superuser)
        self.assignment.effective_from = timezone.now() - timedelta(days=1)
        self.assignment.save(update_fields=['effective_from'])
        sync_role_superuser(self.user)
        self.assertTrue(self.user.is_superuser)

    def test_archived_role_inactive_employee_and_disabled_policy_revoke(self):
        for reason in ('role', 'employee', 'switch'):
            with self.subTest(reason=reason):
                sync_role_superuser(self.user)
                self.assertTrue(self.user.is_superuser)
                if reason == 'role':
                    self.role.archived_at = timezone.now()
                    self.role.save(update_fields=['archived_at'])
                elif reason == 'employee':
                    self.employee.status = 'INACTIVE'
                    self.employee.save(update_fields=['status'])
                with override_settings(CONFIRMED_ROLE_POLICY_ENABLED=reason != 'switch'):
                    sync_role_superuser(self.user)
                self.assertFalse(self.user.is_superuser)
                self.role.archived_at = None
                self.role.save(update_fields=['archived_at'])
                self.employee.status = 'ACTIVE'
                self.employee.save(update_fields=['status'])

    def test_native_superuser_flags_and_admin_are_not_downgraded(self):
        self.user.is_superuser = self.user.is_staff = True
        self.user.save(update_fields=['is_superuser', 'is_staff'])
        sync_role_superuser(self.user)
        self.assignment.delete()
        sync_role_superuser(self.user)
        self.assertTrue(self.user.is_superuser and self.user.is_staff)
        root = get_user_model().objects.create_superuser('admin')
        sync_role_superuser(root)
        self.assertTrue(root.is_superuser and root.is_staff)
        self.assertFalse(RoleSuperuserState.objects.filter(user=root).exists())

    def test_default_off_does_not_promote_and_sync_invalidates_request_cache(self):
        with override_settings(CONFIRMED_ROLE_POLICY_ENABLED=False):
            sync_role_superuser(self.user)
        self.assertFalse(self.user.is_superuser)
        request = SimpleNamespace(user=self.user, META={}, _sales_access_snapshot={'old': True})
        self.user._perm_cache = {'old'}
        sync_role_superuser(self.user, request=request)
        self.assertFalse(hasattr(request, '_sales_access_snapshot'))
        self.assertFalse(hasattr(self.user, '_perm_cache'))

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True)
    def test_role_superuser_can_manage_organizations_and_create_login_account(self):
        from apps.core.api.concurrency import etag_for_instance
        sync_role_superuser(self.user)
        request = SimpleNamespace(user=self.user)
        self.assertTrue(CanManageOrganization().has_permission(request, None))
        target = Employee.objects.create(employee_code='ROLE-ACCOUNT-TARGET', display_name='账号测试目标')
        self.client.force_authenticate(self.user)
        response = self.client.post(f'/api/v1/access/employees/{target.pk}/account/',
            {'username': 'role-created-account', 'password': 'RoleAccountTest938!'},
            format='json', HTTP_IF_MATCH=etag_for_instance(target))
        self.assertEqual(response.status_code, 201, response.data)
