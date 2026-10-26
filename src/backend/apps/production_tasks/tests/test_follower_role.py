from datetime import timedelta

from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase, APIClient

from apps.organizations.models import EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile
from ..api.serializers import (
    ProductionTaskWriteSerializer, ProductionTaskPatchSerializer,
    ProductionTaskCreateFromSalesOrderSerializer, ProductionTaskPmcDecisionSerializer,
)
from ..models import ProductionTask
from ..services import _validate_followers
from . import test_production_task_api as fixtures


class ProductionFollowerRoleTests(APITestCase):
    payload = fixtures.ProductionTaskApiTests.payload

    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        business, _ = OrganizationUnit.objects.get_or_create(unit_code='DEPT_BUSINESS', defaults={'unit_name': '业务部'})
        production, _ = OrganizationUnit.objects.get_or_create(unit_code='DEPT_PRODUCTION', defaults={'unit_name': '生产部'})
        for department in [business, production]:
            EmployeeOrganizationAssignment.objects.create(employee=self.employee, organization_unit=department, effective_from=timezone.now())
        self.role, _ = RoleProfile.objects.get_or_create(role_code='MERCHANDISER', defaults={
            'display_name': '跟单', 'auth_group': Group.objects.create(name='FOLLOWER_ROLE_TEST'),
        })
        self.assignment = EmployeeRoleAssignment.objects.create(employee=self.follower, role_profile=self.role, effective_from=timezone.now() - timedelta(days=2))

    def create_task(self):
        response = self.client.post('/api/v1/production-tasks/', self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return ProductionTask.objects.get(pk=response.data['data']['id']), response

    def test_full_options_use_role_instead_of_production_department(self):
        response = self.client.get('/api/v1/production-tasks/options/')
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row['id'] for row in response.data['data']['employees']}
        self.assertIn(str(self.follower.pk), ids)
        self.assertNotIn(str(self.employee.pk), ids)

    def test_all_write_contracts_accept_only_current_role_members(self):
        for serializer in [ProductionTaskWriteSerializer, ProductionTaskPatchSerializer, ProductionTaskCreateFromSalesOrderSerializer, ProductionTaskPmcDecisionSerializer]:
            with self.subTest(serializer=serializer.__name__):
                field = serializer().fields['follower_ids']
                self.assertEqual(field.run_validation([str(self.follower.pk)]), [self.follower])
                with self.assertRaises(ValidationError):
                    field.run_validation([str(self.employee.pk)])

    def test_expired_and_future_assignments_are_rejected(self):
        self.assignment.effective_to = timezone.now() - timedelta(days=1)
        self.assignment.save(update_fields=['effective_to'])
        with self.assertRaises(ValidationError):
            _validate_followers([self.follower])
        self.assignment.effective_from = timezone.now() + timedelta(days=1)
        self.assignment.effective_to = None
        self.assignment.save(update_fields=['effective_from', 'effective_to'])
        with self.assertRaises(ValidationError):
            _validate_followers([self.follower])

    def test_archived_role_and_inactive_employee_are_rejected(self):
        self.role.archived_at = timezone.now()
        self.role.save(update_fields=['archived_at'])
        with self.assertRaises(ValidationError):
            _validate_followers([self.follower])
        self.role.archived_at = None
        self.role.save(update_fields=['archived_at'])
        self.follower.status = 'INACTIVE'
        self.follower.save(update_fields=['status'])
        with self.assertRaises(ValidationError):
            _validate_followers([self.follower])

    def test_create_without_planner_and_reject_non_follower(self):
        task, _ = self.create_task()
        self.assertIsNone(task.planner_id)
        self.assertEqual(list(task.followers.all()), [self.follower])
        payload = self.payload(follower_ids=[str(self.employee.pk)])
        response = self.client.post('/api/v1/production-tasks/', payload, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ProductionTask.objects.filter(task_number=payload['task_number']).exists())

    def test_filter_keeps_historical_followers_but_form_options_exclude_them(self):
        task, _ = self.create_task()
        task.followers.set([self.employee])
        response = self.client.get('/api/v1/production-tasks/options/?scope=filters')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(str(self.employee.pk), {row['id'] for row in response.data['data']['employees']})
        self.test_full_options_use_role_instead_of_production_department()

    def test_patch_and_pmc_omit_planner_without_erasing_history(self):
        task, created = self.create_task()
        task.planner = self.employee
        task.save(update_fields=['planner'])
        url = f'/api/v1/production-tasks/{task.pk}/'
        etag = self.client.get(url)['ETag']
        response = self.client.patch(url, {'production_priority': 'HIGH'}, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 200, response.data)
        rejected = self.client.patch(url, {'follower_ids': [str(self.employee.pk)]}, format='json', HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(rejected.status_code, 400, rejected.data)
        submitted = self.client.post(url + 'submit/', {}, format='json', HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        today = timezone.localdate().isoformat()
        payload = {'decision': 'CONFIRM', 'follower_ids': [str(self.follower.pk)], 'delivery_date': today,
                   'planned_start_date': today, 'planned_end_date': today, 'includes_tax': True, 'tax_rate': 3,
                   'order_tolerance_percent': '3.00', 'is_repeat_order': False, 'delivery_method': 'SINGLE'}
        result = self.client.post(url + 'pmc-decision/', payload, format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        task.refresh_from_db()
        self.assertEqual(task.planner_id, self.employee.pk)
        self.assertEqual(list(task.followers.all()), [self.follower])

    def test_options_require_login(self):
        self.assertIn(APIClient().get('/api/v1/production-tasks/options/').status_code, [401, 403])
