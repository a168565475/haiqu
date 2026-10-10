import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, OrganizationUnit, EmployeeOrganizationAssignment
from apps.access_control.models import SalesTeam, SalesTeamMembership

ROOT = '/api/v1/access/'
PASSWORD = 'IsolatedAccessTest974!'


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class AccountTeamTests(APITestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('admin','admin@example.test',PASSWORD)
        self.admin_employee=Employee.objects.create(user=self.admin,employee_code='AT_ADMIN',display_name='管理员')
        self.employee=Employee.objects.create(employee_code='AT_SALES',display_name='业务员')
        self.manager=Employee.objects.create(employee_code='AT_MANAGER',display_name='客户经理')
        self.client.force_login(self.admin)

    def create_account(self):
        self.employee.refresh_from_db()
        return self.client.post(ROOT+f'employees/{self.employee.pk}/account/',{'username':'at_sales','password':PASSWORD},format='json',HTTP_IF_MATCH=etag_for_instance(self.employee))

    def team(self,code='TEAM_A'):
        response=self.client.post(ROOT+'sales-teams/',{'code':code,'name':code,'manager_id':str(self.manager.pk)},format='json')
        self.assertEqual(response.status_code,201,response.data)
        return response

    def test_create_account_links_existing_employee_and_starts_without_roles(self):
        count=Employee.objects.count();response=self.create_account()
        self.assertEqual(response.status_code,201,response.data)
        self.employee.refresh_from_db();self.assertTrue(self.employee.user.check_password(PASSWORD))
        self.assertEqual(Employee.objects.count(),count)
        self.assertEqual(response.data['role_ids'],[])
        self.assertEqual(response.data['username'],'at_sales')
        self.assertNotIn(PASSWORD,json.dumps(response.data))
        self.assertNotIn(PASSWORD,json.dumps(list(AuditLog.objects.values('before_data','after_data'))))
        self.assertEqual(self.create_account().status_code,409)

    def test_account_status_and_password_reset_invalidate_sessions(self):
        self.create_account();staff=APIClient();self.assertTrue(staff.login(username='at_sales',password=PASSWORD))
        self.employee.refresh_from_db()
        response=self.client.patch(ROOT+f'employees/{self.employee.pk}/account/',{'is_active':False},format='json',HTTP_IF_MATCH=etag_for_instance(self.employee))
        self.assertEqual(response.status_code,200)
        # Do not touch the old session until AFTER re-enabling.
        self.employee.refresh_from_db()
        self.client.patch(ROOT+f'employees/{self.employee.pk}/account/',{'is_active':True},format='json',HTTP_IF_MATCH=etag_for_instance(self.employee))
        self.assertFalse(staff.get('/api/auth/me/').data['authenticated'])
        self.assertTrue(staff.login(username='at_sales',password=PASSWORD))
        self.employee.refresh_from_db()
        reset=self.client.post(ROOT+f'employees/{self.employee.pk}/reset-password/',{'password':'NewIsolatedPassword843!'},format='json',HTTP_IF_MATCH=etag_for_instance(self.employee))
        self.assertEqual(reset.status_code,200,reset.data)
        self.assertFalse(staff.get('/api/auth/me/').data['authenticated'])
        self.assertFalse(staff.login(username='at_sales',password=PASSWORD))
        self.assertTrue(staff.login(username='at_sales',password='NewIsolatedPassword843!'))

    def test_protected_admin_cannot_be_disabled_or_reset(self):
        headers={'HTTP_IF_MATCH':etag_for_instance(self.admin_employee)}
        self.assertEqual(self.client.patch(ROOT+f'employees/{self.admin_employee.pk}/account/',{'is_active':False},format='json',**headers).status_code,409)
        self.assertEqual(self.client.post(ROOT+f'employees/{self.admin_employee.pk}/reset-password/',{'password':PASSWORD},format='json',**headers).status_code,409)
        self.admin.refresh_from_db();self.assertTrue(self.admin.is_active)

    def test_archived_role_keeps_assignment_impact_count(self):
        role = self.client.post(ROOT+'roles/', {'role_code':'IMPACT_ROLE','display_name':'影响人数'}, format='json')
        self.assertEqual(role.status_code, 201, role.data)
        self.employee.refresh_from_db()
        assigned = self.client.put(ROOT+f'employees/{self.employee.pk}/roles/', {'role_ids':[role.data['id']]}, format='json', HTTP_IF_MATCH=etag_for_instance(self.employee))
        self.assertEqual(assigned.status_code, 200, assigned.data)
        archived = self.client.patch(ROOT+f"roles/{role.data['id']}/", {'archived':True}, format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertEqual(archived.data['assigned_employee_count'], 1)

    def test_weak_password_missing_etag_and_extra_fields_rejected(self):
        url=ROOT+f'employees/{self.employee.pk}/account/'
        payload={'username':'weak','password':'123'}
        self.assertEqual(self.client.post(url,payload,format='json').status_code,428)
        headers={'HTTP_IF_MATCH':etag_for_instance(self.employee)}
        self.assertEqual(self.client.post(url,payload,format='json',**headers).status_code,400)
        payload['password']=PASSWORD;payload['is_superuser']=True
        self.assertEqual(self.client.post(url,payload,format='json',**headers).status_code,400)
        self.assertFalse(get_user_model().objects.filter(username='weak').exists())

    def test_account_audit_failure_rolls_back_user_and_binding(self):
        with patch('apps.access_control.services.write_audit_log',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError): self.create_account()
        self.employee.refresh_from_db();self.assertIsNone(self.employee.user_id)
        self.assertFalse(get_user_model().objects.filter(username='at_sales').exists())

    def test_cross_department_members_and_unique_team(self):
        for e,code in [(self.employee,'SALES_DEPT'),(self.manager,'SERVICE_DEPT')]:
            dept=OrganizationUnit.objects.create(unit_code=code,unit_name=code)
            EmployeeOrganizationAssignment.objects.create(employee=e,organization_unit=dept,effective_from=timezone.now()-timedelta(days=1))
        first=self.team();second=self.team('TEAM_B')
        payload={'employee_ids':[str(self.employee.pk)]}
        added=self.client.post(ROOT+f"sales-teams/{first.data['id']}/members/",payload,format='json',HTTP_IF_MATCH=first['ETag'])
        self.assertEqual(added.status_code,200,added.data)
        self.assertEqual(added.data['member_ids'],[str(self.employee.pk)])
        duplicate=self.client.post(ROOT+f"sales-teams/{second.data['id']}/members/",payload,format='json',HTTP_IF_MATCH=second['ETag'])
        self.assertEqual(duplicate.status_code,409)
        with self.assertRaises(IntegrityError),transaction.atomic():
            SalesTeamMembership.objects.create(team_id=second.data['id'],employee=self.employee,created_by_employee=self.admin_employee)
        self.assertEqual(self.client.delete(ROOT+f"sales-teams/{first.data['id']}/members/").status_code,405)

    def test_team_changes_require_versions_and_reject_manager_transfer(self):
        team=self.team();url=ROOT+f"sales-teams/{team.data['id']}/"
        self.assertEqual(self.client.patch(url,{'name':'新名称'},format='json').status_code,428)
        changed=self.client.patch(url,{'name':'新名称'},format='json',HTTP_IF_MATCH=team['ETag']);self.assertEqual(changed.status_code,200)
        self.assertEqual(self.client.patch(url,{'name':'旧版本覆盖'},format='json',HTTP_IF_MATCH=team['ETag']).status_code,412)
        self.assertEqual(self.client.patch(url,{'manager_id':str(self.employee.pk)},format='json',HTTP_IF_MATCH=changed['ETag']).status_code,400)

    def test_inactive_team_rejects_members_and_non_admin_denied(self):
        team=self.team();url=ROOT+f"sales-teams/{team.data['id']}/"
        disabled=self.client.patch(url,{'is_active':False},format='json',HTTP_IF_MATCH=team['ETag'])
        self.assertEqual(self.client.post(url+'members/',{'employee_ids':[str(self.employee.pk)]},format='json',HTTP_IF_MATCH=disabled['ETag']).status_code,409)
        self.create_account();self.employee.refresh_from_db();self.client.force_login(self.employee.user)
        self.assertEqual(self.client.get(ROOT+'sales-teams/').status_code,403)
        self.assertEqual(self.client.post(ROOT+f'employees/{self.employee.pk}/reset-password/',{'password':PASSWORD},format='json').status_code,403)
