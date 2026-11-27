from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile


class WarehouseWorkbenchApiTests(APITestCase):
    url = '/api/v1/warehouse-workbench/'

    def setUp(self):
        user = get_user_model().objects.create_user(username='warehouse-workbench-test')
        self.employee = Employee.objects.create(user=user, employee_code='WH-WB', display_name='仓管')
        self.client.force_authenticate(user)

    def assign_keeper(self):
        role, _ = RoleProfile.objects.get_or_create(role_code='WAREHOUSE_KEEPER', defaults={
            'display_name': '仓管', 'auth_group': Group.objects.create(name='warehouse-workbench-test')})
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())

    def test_other_role_cannot_open_any_workbench_endpoint(self):
        for suffix in ('', 'items/', 'detail/', 'activity/'):
            with self.subTest(endpoint=suffix):
                self.assertEqual(self.client.get(self.url + suffix).status_code, 403)

    def test_role_without_operational_grants_and_query_validation(self):
        self.assign_keeper()
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200, result.data)
        for card in result.data['data']['queues'].values():
            self.assertFalse(card['available'])
            self.assertIsNone(card['count'])
        summary = self.client.get(self.url + 'activity/', {'period': 'quarter', 'summary': 1})
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertTrue(all(n is None for n in summary.data['data']['counts'].values()))
        self.assertEqual(summary.data['meta']['total'], 0)
        self.assertEqual(self.client.get(self.url + 'items/', {'queue': 'issue'}).status_code, 403)
        self.assertEqual(self.client.get(self.url + 'activity/', {'queue': 'purchase'}).status_code, 403)
        for params in ({'queue': 'unknown'}, {'queue': 'purchase', 'task_id': self.employee.pk},
                       {'queue': 'issue', 'page_size': 101}, {'queue': 'issue', 'unrecognized': 1}):
            with self.subTest(query=params):
                self.assertEqual(self.client.get(self.url + 'items/', params).status_code, 400)
