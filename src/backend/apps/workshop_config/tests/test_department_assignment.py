from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.access_control.models import SalesTeam, SalesTeamMembership
from apps.workshop_config.models import Workshop, WorkshopEmployee


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class DepartmentAssignmentTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', password='TestAssignments123!')
        self.actor = Employee.objects.create(user=self.user, employee_code='ASSIGN_ADMIN', display_name='管理员')
        self.client.force_login(self.user)
        self.production, _ = OrganizationUnit.objects.get_or_create(unit_code='DEPT_PRODUCTION', defaults={'unit_name': '生产部'})
        self.sales, _ = OrganizationUnit.objects.get_or_create(unit_code='DEPT_BUSINESS', defaults={'unit_name': '业务部'})
        self.worker = Employee.objects.create(employee_code='ASSIGN_WORKER', display_name='员工')
        self.workshop = Workshop.objects.get(name='装配车间')
        self.url = '/api/v1/workshop-config/employees/'

    def assign(self, unit, **data):
        return EmployeeOrganizationAssignment.objects.create(employee=self.worker, organization_unit=unit,
            **({'effective_from': timezone.now() - timedelta(days=1)} | data))

    def payload(self):
        return {'workshop': str(self.workshop.pk), 'position': '工人', 'is_supervisor': False}

    def row(self):
        if not self.worker.organization_assignments.filter(organization_unit=self.production).exists():
            self.assign(self.production)
        self.worker.workshop = self.workshop
        self.worker.workshop_position = '工人'
        self.worker.save()
        return self.worker

    def test_production_options_and_save_enforce_current_membership(self):
        self.assign(self.sales)
        self.assertEqual(self.client.get(self.url).data['meta']['total'], 0)
        self.assertEqual(self.client.patch(self.url + f'{self.worker.pk}/', self.payload(), format='json').status_code, 404)
        membership = self.assign(self.production)
        self.assertEqual(self.client.get(self.url).data['data'][0]['id'], str(self.worker.pk))
        self.assertEqual(self.client.patch(self.url + f'{self.worker.pk}/', self.payload(), format='json', HTTP_IF_MATCH=etag_for_instance(self.worker)).status_code, 200)
        membership.effective_to = timezone.now(); membership.save()
        self.assertEqual(self.client.get(self.url).data['meta']['total'], 0)
        self.assertEqual(self.client.patch(self.url + f'{self.worker.pk}/', {'position': '组长'}, format='json').status_code, 404)

    def test_future_inactive_or_archived_department_is_not_a_candidate(self):
        assignment = self.assign(self.production, effective_from=timezone.now() + timedelta(days=1))
        self.assertEqual(self.client.get(self.url).data['meta']['total'], 0)
        assignment.effective_from = timezone.now() - timedelta(days=1); assignment.save()
        for status, archived in [('INACTIVE', None), ('ACTIVE', timezone.now())]:
            self.production.status = status; self.production.archived_at = archived; self.production.save()
            self.assertEqual(self.client.get(self.url).data['meta']['total'], 0)

    def test_sales_members_must_belong_to_business_department(self):
        team = SalesTeam.objects.create(code='DEPT_TEAM', name='团队', manager=self.actor)
        url = f'/api/v1/access/sales-teams/{team.pk}/members/'
        self.assign(self.production)
        payload = {'employee_ids': [str(self.worker.pk)]}
        self.assertEqual(self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag_for_instance(team)).status_code, 400)
        self.assertFalse(SalesTeamMembership.objects.exists())
        self.assign(self.sales)
        self.assertEqual(self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag_for_instance(team)).status_code, 200)
        self.assertEqual(SalesTeamMembership.objects.get().employee_id, self.worker.pk)

    def test_unreferenced_configuration_is_deleted_without_deleting_employee(self):
        row = self.row()
        response = self.client.delete(self.url + f'{row.pk}/', HTTP_IF_MATCH=etag_for_instance(row))
        self.assertEqual(response.status_code, 204)
        row.refresh_from_db(); self.assertIsNone(row.workshop_id)
        self.assertTrue(Employee.objects.filter(pk=self.worker.pk).exists())
        self.assertIsNone(AuditLog.objects.get(object_id=row.pk).after_data['workshop_id'])

    def test_referenced_configuration_is_hidden_and_can_be_reassigned(self):
        self.assign(self.production)
        row = self.row()
        write_audit_log(object_type='WORKSHOP_EMPLOYEE', object_id=row.pk, action='CREATED', actor_employee=self.actor)
        response = self.client.delete(self.url + f'{row.pk}/', HTTP_IF_MATCH=etag_for_instance(row))
        self.assertEqual(response.status_code, 204)
        row.refresh_from_db(); self.assertIsNone(row.workshop_id)
        self.assertEqual(self.client.get(self.url).data['meta']['total'], 1)
        self.assertEqual(self.client.get(self.url + 'summary/').data['data']['total'], 1)
        self.assertEqual(self.client.get(self.url + f'{row.pk}/').status_code, 200)
        self.assertEqual(self.client.patch(self.url + f'{row.pk}/', self.payload(), format='json', HTTP_IF_MATCH=etag_for_instance(row)).status_code, 200)
        self.assertEqual(AuditLog.objects.filter(object_id=row.pk).count(), 3)

    def test_deletion_requires_permission_version_csrf_and_rolls_back_on_audit_failure(self):
        row = self.row(); url = self.url + f'{row.pk}/'
        self.assertEqual(self.client.delete(url).status_code, 428)
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH='"stale"').status_code, 412)
        from rest_framework.test import APIClient
        csrf = APIClient(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.delete(url, HTTP_IF_MATCH=etag_for_instance(row)).status_code, 403)
        with patch('apps.workshop_config.services.write_audit_log', side_effect=RuntimeError('audit failure')):
            with self.assertRaisesMessage(RuntimeError, 'audit failure'):
                self.client.delete(url, HTTP_IF_MATCH=etag_for_instance(row))
        self.assertTrue(WorkshopEmployee.objects.filter(pk=row.pk).exists())
        self.client.logout()
        self.assertIn(self.client.delete(url, HTTP_IF_MATCH=etag_for_instance(row)).status_code, (401, 403))
        self.assertEqual(self.client.get(url).status_code, 401)
