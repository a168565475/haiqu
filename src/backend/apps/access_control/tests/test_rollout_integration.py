from io import StringIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.samples.models import SampleRequest
from apps.workflow.models import BusinessTask
from apps.access_control.models import RoleActionGrant, SalesTeam, SalesTeamMembership


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, SALES_ACCESS_ENABLED=True, MODULE_ACCESS_ENABLED=True)
class RolloutIntegrationTests(APITestCase):
    """Management writes must affect real business APIs in the existing session."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('admin', 's6@example.test', 'S6TestOnly987!')
        Employee.objects.create(user=self.admin, employee_code='S6_ADMIN', display_name='管理员')
        self.user = User.objects.create_user('s6_worker', password='S6TestOnly987!')
        self.worker = Employee.objects.create(user=self.user, employee_code='S6_WORKER', display_name='业务员')
        self.member = Employee.objects.create(employee_code='S6_MEMBER', display_name='团队成员')
        self.outside = Employee.objects.create(employee_code='S6_OUTSIDE', display_name='其他员工')
        self.client.force_login(self.admin)
        self.staff = APIClient()
        self.staff.force_login(self.user)
        self.records = {}
        for owner in [self.worker, self.member, self.outside]:
            code = owner.employee_code
            customer = CustomerAccount.objects.create(account_code=code, account_name=code)
            CustomerAssignment.objects.create(customer_account=customer, employee=owner,
                assignment_role='PRIMARY_OWNER', effective_from=timezone.now(), assigned_by_employee=self.worker)
            sample = SampleRequest.objects.create(customer_account=customer, owner_employee=owner,
                request_number=code, requested_by_employee=owner, requested_at=timezone.now())
            task = BusinessTask.objects.create(task_number=code, title=code, task_type='OTHER',
                created_by_employee=owner, assignee_employee=owner)
            self.records[code] = [f'/api/v1/customers/{customer.pk}/',
                f'/api/v1/sample-requests/{sample.pk}/', f'/api/v1/tasks/{task.pk}/']
        self.team = SalesTeam.objects.create(code='S6_TEAM', name='验收团队', manager=self.worker)
        SalesTeamMembership.objects.create(team=self.team, employee=self.member, created_by_employee=self.worker)

    def role(self, code, scope='OWN'):
        response = self.client.post('/api/v1/access/roles/', {'role_code': code, 'display_name': code}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        grants = [{'permission': p, 'scope': scope} for p in
            ['customers.view_customeraccount', 'samples.view_samplerequest', 'workflow.view_businesstask']]
        grants.append({'permission': 'production_tasks.view_productiontask', 'scope': 'MODULE'})
        changed = self.client.put(f"/api/v1/access/roles/{response.data['id']}/grants/", {'grants': grants},
            format='json', HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(changed.status_code, 200, changed.data)
        return changed

    def assign(self, *roles):
        self.worker.refresh_from_db()
        response = self.client.put(f'/api/v1/access/employees/{self.worker.pk}/roles/',
            {'role_ids': [r.data['id'] for r in roles]}, format='json', HTTP_IF_MATCH=etag_for_instance(self.worker))
        self.assertEqual(response.status_code, 200, response.data)

    def assert_records(self, code, status):
        for url in self.records[code]:
            with self.subTest(url=url):
                response = self.staff.get(url)
                self.assertEqual(response.status_code, status, response.data)

    def test_roles_union_across_sales_samples_tasks_and_modules_without_outside_access(self):
        own = self.role('S6_OWN')
        team = self.role('S6_TEAM_ROLE', 'TEAM')
        self.assign(own, team)
        self.assert_records('S6_WORKER', 200)
        self.assert_records('S6_MEMBER', 200)
        self.assert_records('S6_OUTSIDE', 404)
        self.assertEqual(self.staff.get('/api/v1/production-tasks/').status_code, 200)
        self.assertEqual(self.staff.patch(self.records['S6_MEMBER'][2], {'title': '禁止编辑'}, format='json').status_code, 403)

    def test_revoke_grants_blocks_next_business_requests_in_same_session(self):
        role = self.role('S6_REVOKE')
        self.assign(role)
        self.assert_records('S6_WORKER', 200)
        response = self.client.put(f"/api/v1/access/roles/{role.data['id']}/grants/", {'grants': []},
            format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_records('S6_WORKER', 403)
        self.assertEqual(self.staff.get('/api/v1/production-tasks/').status_code, 403)
        self.assertEqual(self.staff.get('/api/auth/me/').data['user']['effective_access']['actions'], {})

    def test_removing_one_role_keeps_other_role_without_retaining_removed_team_scope(self):
        own, team = self.role('S6_KEEP'), self.role('S6_REMOVE', 'TEAM')
        self.assign(own, team)
        self.assert_records('S6_MEMBER', 200)
        self.assign(own)
        self.assert_records('S6_WORKER', 200)
        self.assert_records('S6_MEMBER', 404)

    def test_disabled_team_loses_team_records_but_keeps_module_access(self):
        self.assign(self.role('S6_TEAM_ONLY', 'TEAM'))
        self.assert_records('S6_MEMBER', 200)
        response = self.client.patch(f'/api/v1/access/sales-teams/{self.team.pk}/', {'is_active': False},
            format='json', HTTP_IF_MATCH=etag_for_instance(self.team))
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_records('S6_MEMBER', 404)
        self.assertEqual(self.staff.get('/api/v1/production-tasks/').status_code, 200)

    def test_suspended_then_reenabled_account_does_not_revive_old_business_session(self):
        self.assign(self.role('S6_SUSPEND'))
        self.assert_records('S6_WORKER', 200)
        for active in [False, True]:
            self.worker.refresh_from_db()
            response = self.client.patch(f'/api/v1/access/employees/{self.worker.pk}/account/',
                {'is_active': active}, format='json', HTTP_IF_MATCH=etag_for_instance(self.worker))
            self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(self.staff.get('/api/auth/me/').data['authenticated'])
        for url in self.records['S6_WORKER']:
            self.assertIn(self.staff.get(url).status_code, [401, 403])
        self.assertTrue(self.staff.login(username='s6_worker', password='S6TestOnly987!'))
        self.assert_records('S6_WORKER', 200)

    def test_removing_new_role_does_not_remove_independent_legacy_module_grant(self):
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='production_tasks', codename='view_productiontask'))
        self.assign(self.role('S6_LEGACY'))
        self.assign()
        self.assert_records('S6_WORKER', 403)
        self.assertEqual(self.staff.get('/api/v1/production-tasks/').status_code, 200)
        sources = self.staff.get('/api/auth/me/').data['user']['effective_access']['legacy_sources']
        self.assertTrue(any(s['type'] == 'DIRECT' and s['permission'] == 'production_tasks.view_productiontask' for s in sources))

    def test_initialization_is_empty_idempotent_and_does_not_assign_employees(self):
        out = StringIO()
        call_command('initialize_access_roles', stdout=out)
        self.assertEqual(RoleProfile.objects.count(), 0)
        call_command('initialize_access_roles', apply=True, stdout=out)
        self.assertEqual(RoleProfile.objects.count(), 20)
        self.assertEqual(RoleActionGrant.objects.count(), 0)
        self.assertEqual(EmployeeRoleAssignment.objects.count(), 0)
        self.assertFalse(RoleProfile.objects.filter(display_name='查看全部权限').exists())
        call_command('initialize_access_roles', apply=True, stdout=out)
        self.assertEqual(RoleProfile.objects.count(), 20)
        self.assertEqual(EmployeeRoleAssignment.objects.count(), 0)

    def test_reported_enforcement_tracks_actual_flags_with_and_without_account(self):
        for sales, modules, expected in [(False, False, 'DISABLED'), (True, False, 'PARTIAL'), (False, True, 'PARTIAL'), (True, True, 'ENABLED')]:
            with self.subTest(sales=sales, modules=modules), override_settings(SALES_ACCESS_ENABLED=sales, MODULE_ACCESS_ENABLED=modules):
                self.assertEqual(self.staff.get('/api/auth/me/').data['user']['effective_access']['business_scope_enforcement'], expected)
                response = self.client.get(f'/api/v1/access/employees/{self.outside.pk}/effective-access/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['business_scope_enforcement'], expected)
                self.assertFalse(response.data['active'])

    def test_unmapped_full_update_routes_fail_closed_for_superuser(self):
        # These existing views support PATCH. An advertised but unmapped PUT
        # must not fall back to superuser-wide access or an unrelated operation.
        for route in ['quotation-versions', 'quotation-lines']:
            response = self.client.put(f'/api/v1/{route}/{uuid4()}/', {}, format='json')
            self.assertEqual(response.status_code, 403, (route, response.data))

    def test_saved_view_permissions_are_configurable_but_strictly_personal(self):
        from apps.preferences.models import SavedView
        role = self.role('S6_PREFS')
        url = f"/api/v1/access/roles/{role.data['id']}/grants/"
        codes = ['preferences.view_savedview', 'preferences.add_savedview', 'preferences.change_savedview']
        rejected = self.client.put(url, {'grants': [{'permission': codes[0], 'scope': 'TEAM'}]},
            format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(rejected.status_code, 400)
        granted = self.client.put(url, {'grants': [{'permission': code, 'scope': 'OWN'} for code in codes]},
            format='json', HTTP_IF_MATCH=role['ETag'])
        self.assertEqual(granted.status_code, 200, granted.data)
        self.assign(granted)
        created = self.staff.post('/api/v1/saved-views/', {'module_code': 'TASK', 'view_name': '本人视图',
            'filter_definition': {}, 'column_definition': [], 'sort_definition': []}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        own_id = created.data['data']['id']
        foreign = SavedView.objects.create(employee=self.member, module_code='TASK', view_name='团队成员私人视图')
        self.assertEqual(self.staff.get(f'/api/v1/saved-views/{foreign.pk}/').status_code, 404)
        self.assertEqual(self.staff.patch(f'/api/v1/saved-views/{foreign.pk}/', {'view_name': '禁止'},
            format='json', HTTP_IF_MATCH=etag_for_instance(foreign)).status_code, 404)
        patched = self.staff.patch(f'/api/v1/saved-views/{own_id}/', {'view_name': '本人修改'},
            format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(patched.status_code, 200, patched.data)
