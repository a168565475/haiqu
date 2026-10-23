from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.wecom.models import WeComBinding
from apps.access_control.models import RoleActionGrant


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class EmployeeNameTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin', password='NameTest123!')
        Employee.objects.create(user=self.admin, employee_code='NAME_ADMIN', display_name='管理员')
        self.user = get_user_model().objects.create_user('name_worker')
        self.employee = Employee.objects.create(user=self.user, employee_code='NAME_EMPLOYEE', display_name='原姓名')
        self.binding = WeComBinding.objects.create(employee=self.employee, corp_id='name-test', user_id='source-id', member_name='企微原名', source='MANUAL')
        self.url = f'/api/v1/access/employees/{self.employee.pk}/name/'
        self.client.force_login(self.admin)

    def rename(self, name='新姓名', **headers):
        return self.client.patch(self.url, {'display_name': name}, format='json',
                                 **({'HTTP_IF_MATCH': etag_for_instance(self.employee)} | headers))

    def test_rename_preserves_identity_and_audits_before_after(self):
        original_etag = etag_for_instance(self.employee)
        response = self.rename('  新姓名  ')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['display_name'], '新姓名')
        self.assertNotEqual(response['ETag'], original_etag)
        self.employee.refresh_from_db(); self.user.refresh_from_db(); self.binding.refresh_from_db()
        self.assertEqual(self.employee.employee_code, 'NAME_EMPLOYEE')
        self.assertEqual(self.employee.user_id, self.user.pk)
        self.assertEqual(self.user.username, 'name_worker')
        self.assertEqual(self.binding.user_id, 'source-id')
        self.assertEqual(self.binding.employee_id, self.employee.pk)
        log = AuditLog.objects.get(object_id=self.employee.pk, action='EMPLOYEE_NAME_UPDATE')
        self.assertEqual(log.before_data, {'employee_name': '原姓名'})
        self.assertEqual(log.after_data, {'employee_name': '新姓名'})
        self.assertEqual(self.rename().status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action='EMPLOYEE_NAME_UPDATE').count(), 1)

    def test_duplicate_names_and_inactive_employee_are_allowed(self):
        Employee.objects.create(employee_code='NAME_SAME', display_name='新姓名')
        self.employee.status = 'LEFT'; self.employee.save()
        self.assertEqual(self.rename().status_code, 200)
        self.assertEqual(Employee.objects.filter(display_name='新姓名').count(), 2)

    def test_boundary_validation_does_not_write(self):
        for data in [{}, {'display_name': ''}, {'display_name': '   '}, {'display_name': None},
                     {'display_name': '名' * 151}, {'display_name': '新姓名', 'employee_code': 'OTHER'}]:
            with self.subTest(data=data):
                response = self.client.patch(self.url, data, format='json', HTTP_IF_MATCH=etag_for_instance(self.employee))
                self.assertEqual(response.status_code, 400)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.display_name, '原姓名')

    def test_missing_stale_version_and_archived_employee(self):
        self.assertEqual(self.client.patch(self.url, {'display_name': '新姓名'}, format='json').status_code, 428)
        self.assertEqual(self.rename(HTTP_IF_MATCH='"stale"').status_code, 412)
        self.employee.archived_at = timezone.now(); self.employee.save()
        self.assertEqual(self.rename().status_code, 404)

    def test_requires_organization_role_and_active_identity(self):
        self.client.logout()
        self.assertIn(self.rename().status_code, (401, 403))
        self.client.force_login(self.user)
        self.assertEqual(self.rename().status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='organizations', codename='manage_organization'))
        self.assertEqual(self.rename().status_code, 403)
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name='NAME_MANAGER'), role_code='NAME_MANAGER', display_name='组织管理员')
        RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(content_type__app_label='organizations', codename='manage_organization'), scope='MODULE')
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        self.assertEqual(self.rename().status_code, 200)
        self.employee.refresh_from_db(); self.employee.status = 'INACTIVE'; self.employee.save()
        self.assertEqual(self.rename().status_code, 401)

    def test_session_csrf_and_atomic_rollback(self):
        client = APIClient(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.patch(self.url, {'display_name': '新姓名'}, format='json', HTTP_IF_MATCH=etag_for_instance(self.employee)).status_code, 403)
        with patch('apps.access_control.organization_services.write_audit_log', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesMessage(RuntimeError, 'audit failed'):
                self.rename()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.display_name, '原姓名')
        self.assertFalse(AuditLog.objects.filter(action='EMPLOYEE_NAME_UPDATE').exists())
