from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile


ROOT = '/api/v1/codex-connection/'


class SerializerBoundaryTests(SimpleTestCase):
    def test_unknown_fields_and_non_object_return_structured_validation_error(self):
        from rest_framework.exceptions import ValidationError
        from apps.codex_connection.serializers import EmptySerializer
        for payload in ({'command': 'anything'}, ['invalid']):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ValidationError) as raised:
                    EmptySerializer(data=payload).is_valid(raise_exception=True)
                self.assertIn('non_field_errors', raised.exception.detail)


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class CodexConnectionApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('codex_admin', '', 'TestPassword123!')
        self.employee = Employee.objects.create(user=self.user, employee_code='CODEX_ADMIN', display_name='连接管理员')
        self.client = APIClient()
        self.client.force_login(self.user)

    def snapshot(self):
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 200)
        return response

    def post(self, action, data=None, etag=None):
        return self.client.post(ROOT + action + '/', data or {}, format='json',
                                HTTP_IF_MATCH=etag or self.snapshot()['ETag'])

    def test_status_contract_contains_no_challenge_or_credentials(self):
        response = self.snapshot()
        self.assertEqual(response.data['data']['status'], 'DISCONNECTED')
        self.assertEqual(set(response.data['data']), {
            'config_generation', 'status', 'selected_model', 'cli_version', 'account', 'models',
            'rate_limits', 'limits_updated_at', 'last_checked_at', 'last_test_at', 'error_code',
            'paused', 'operation',
        })
        self.assertIn('ETag', response)

    def test_staff_and_direct_permission_do_not_grant_connection_management(self):
        user = get_user_model().objects.create_user('codex_staff', password='TestPassword123!', is_staff=True)
        Employee.objects.create(user=user, employee_code='CODEX_STAFF', display_name='普通员工')
        permission = Permission.objects.get(content_type__app_label='access_control', codename='manage_codex_connection')
        user.user_permissions.add(permission)
        self.client.force_login(user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.assertEqual(self.client.post(ROOT + 'login/', {}, format='json').status_code, 403)

    def test_explicit_role_grant_and_revocation(self):
        user = get_user_model().objects.create_user('codex_manager', password='TestPassword123!')
        employee = Employee.objects.create(user=user, employee_code='CODEX_MANAGER', display_name='角色管理员')
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name='CODEX_MANAGER'),
                                          role_code='CODEX_MANAGER', display_name='连接管理角色')
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                                              effective_from=timezone.now() - timedelta(minutes=1))
        permission = Permission.objects.get(content_type__app_label='access_control', codename='manage_codex_connection')
        grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='MODULE')
        self.client.force_login(user)
        self.snapshot()
        grant.delete()
        self.assertEqual(self.client.get(ROOT).status_code, 403)

    def test_inactive_employee_and_anonymous_cannot_read(self):
        self.client.logout()
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        self.client.force_login(self.user)
        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=['archived_at'])
        self.assertEqual(self.client.get(ROOT).status_code, 403)

    def test_write_requires_csrf_and_matching_etag(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(ROOT + 'login/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post(ROOT + 'login/', {}, format='json').status_code, 428)
        self.assertEqual(self.post('login', etag='"old"').status_code, 412)

    def test_login_queues_once_without_calling_runtime_from_request(self):
        from apps.codex_connection.models import CodexOperation
        with patch('apps.codex_connection.runtime_client.RuntimeClient.call') as runtime:
            response = self.post('login')
            self.assertEqual(response.status_code, 202)
            runtime.assert_not_called()
        self.assertEqual(CodexOperation.objects.count(), 1)
        self.assertEqual(self.post('login').status_code, 409)
        self.assertEqual(CodexOperation.objects.count(), 1)
        self.assertNotIn('user_code', str(list(AuditLog.objects.filter(object_type='CODEX_CONNECTION').values())))

    def test_cancel_targets_current_operation_only(self):
        from uuid import uuid4
        started = self.post('login')
        operation_id = started.data['data']['operation']['id']
        self.assertEqual(self.post('login-cancel', {'operation_id': str(uuid4())}).status_code, 409)
        response = self.post('login-cancel', {'operation_id': operation_id})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.data['data']['operation']['can_cancel'])

    def test_unknown_fields_and_arbitrary_model_are_rejected(self):
        self.assertEqual(self.post('login', {'command': 'anything'}).status_code, 400)
        response = self.client.patch(ROOT + 'model/', {'model': 'unknown'}, format='json',
                                     HTTP_IF_MATCH=self.snapshot()['ETag'])
        self.assertEqual(response.status_code, 400)

    def test_challenge_is_restricted_to_initiator(self):
        response = self.post('login')
        operation_id = response.data['data']['operation']['id']
        other = get_user_model().objects.create_superuser('codex_other', '', 'TestPassword123!')
        Employee.objects.create(user=other, employee_code='CODEX_OTHER', display_name='另一管理员')
        self.client.force_login(other)
        with patch('apps.codex_connection.runtime_client.RuntimeClient.call') as runtime:
            response = self.client.get(ROOT + 'challenge/', {'operation_id': operation_id})
            self.assertEqual(response.status_code, 403)
            runtime.assert_not_called()

    def test_missing_schema_returns_safe_503(self):
        with patch('apps.codex_connection.selectors.schema_is_ready', return_value=False):
            response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['error']['code'], 'CODEX_SCHEMA_UNAVAILABLE')

    def test_fast_worker_completion_returns_matching_status_operation_and_etag(self):
        from types import SimpleNamespace
        from apps.codex_connection.models import CodexConnection
        from apps.codex_connection.views import snapshot_response
        self.assertEqual(self.post('login').status_code, 202)
        stale = CodexConnection.objects.get()
        current = CodexConnection.objects.get()
        current.status = 'CONNECTED'
        current.account = {'display_name': 'a***@example.test', 'plan_type': 'pro'}
        current.save()
        current.operations.update(state='SUCCEEDED', completed_at=timezone.now())
        response = snapshot_response(stale, SimpleNamespace(employee=self.employee))
        self.assertEqual(response.data['data']['status'], 'CONNECTED')
        self.assertIsNone(response.data['data']['operation'])
        self.assertEqual(response['ETag'], self.client.get(ROOT)['ETag'])
