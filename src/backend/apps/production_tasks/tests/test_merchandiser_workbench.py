from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.outsourcing.tests import test_part_flow_plan_api as sewing
from .test_dashboard_api import DashboardFixture


URL = '/api/v1/merchandiser-workbench/'
TASK_PERMISSION = 'production_tasks.view_productiontask'


def assign_merchandiser(employee):
    role, _ = RoleProfile.objects.get_or_create(role_code='MERCHANDISER', defaults={
        'display_name': '跟单', 'auth_group': Group.objects.get_or_create(name='跟单工作台测试')[0]})
    EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class MerchandiserTaskTests(DashboardFixture, APITestCase):
    def test_current_assignment_is_required_even_when_user_can_read_production_tasks(self):
        self.assertEqual(self.client.get(URL).status_code, 403)
        assign_merchandiser(self.employee)
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.client.logout()
        self.assertIn(self.client.get(URL).status_code, (401, 403))

    def test_owned_task_due_days_completed_and_natural_period(self):
        assign_merchandiser(self.employee)
        self.grant('production_tasks.view_all_productiontask')
        overdue = self.task('PAST', -1)
        today = self.task('TODAY')
        completed = self.task('FINISHED', status='COMPLETED')
        draft = self.task('DRAFT', status='DRAFT')
        for task in (overdue, today, completed, draft):
            task.followers.add(self.employee)
        self.task('CREATED-ONLY')
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        result = resp.data['data']
        self.assertEqual(result['counts']['past'], 1)
        self.assertEqual([day['count'] for day in result['upcoming']], [1, 0, 0, 0, 0, 0, 0])
        row, = self.client.get(URL + 'items/', {'category': 'day', 'date': self.today}).data['data']['rows']
        self.assertEqual(row['task_id'], str(today.pk))
        count = 2 + int(overdue.delivery_date.month == self.today.month)
        self.assertEqual(self.client.get(URL + 'activity/').data['data']['task_count'], count)
        selection = self.client.get(URL + 'items/', {'category': 'period_tasks', 'page_size': 1, 'page': 2}).data
        self.assertEqual((selection['meta']['total'], len(selection['data']['rows'])), (count, 1))
        today.followers.remove(self.employee)
        self.assertEqual(self.client.get(URL).data['data']['upcoming'][0]['count'], 0)

    def test_missing_source_permission_and_invalid_filters(self):
        assign_merchandiser(self.employee)
        result = self.client.get(URL).data['data']
        self.assertIsNone(result['counts']['owing'])
        self.assertEqual(self.client.get(URL + 'items/', {'category': 'owing'}).status_code, 403)
        for params in ({'category': 'day'}, {'category': 'supplier'}, {'category': 'past', 'period': 'year'},
                       {'category': 'day', 'date': self.today + timedelta(days=7)}, {'category': 'ordinary', 'page': 0}):
            self.assertEqual(self.client.get(URL + 'items/', params).status_code, 400)
        self.assertEqual(self.client.get(URL, {'user': self.user.pk}).status_code, 400)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class MerchandiserPrintingTests(sewing.PartFlowPlanFixture, APITestCase):
    create_print_plan = sewing.PartFlowPlanApiTests.create_print_plan
    send_to_printer = sewing.PartFlowPlanApiTests.send_to_printer
    create_part_plan = sewing.PartFlowPlanApiTests.create_part_plan
    part_context = sewing.PartFlowPlanApiTests.part_context
    receive_part = sewing.PartFlowPlanApiTests.receive_part

    def test_partial_dispatch_warehouse_receipt_and_direct_delivery(self):
        sewing_plan = self.create_part_plan()
        printing = self.send_to_printer(self.create_print_plan(self.factory), self.factory, 100)
        transfer = self.client.post(sewing.BASE + sewing_plan['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid4()), 'source_kind': 'PROCESSOR', 'actual_dispatch_date': str(timezone.localdate()),
            'inputs': [{'component_identity': str(self.parts[0].component_identity), 'quantity': 50,
                        'print_order_line_id': printing['lines'][0]['id']}]},
            format='json', HTTP_IF_MATCH=sewing_plan['etag'])
        self.assertEqual(transfer.status_code, 200, transfer.data)
        updated = self.client.get('/api/v1/cut-piece-printing-orders/' + printing['id'] + '/')
        self.receive_part(updated.data['data'], 30)

        self.scoped_actor()
        assign_merchandiser(self.scope_employee)
        self.grant(TASK_PERMISSION, 'MODULE')  # 兼岗可看更多生产任务，个人工作台仍只看本人跟进。
        self.grant(CUT_PIECE_PRINTING, 'FOLLOWED')
        self.assertEqual(self.client.get(URL).data['data']['counts']['owing'], 0)
        task = self.schedule_product.schedule.production_task
        task.followers.add(self.scope_employee)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        counts = response.data['data']['counts']
        self.assertEqual((counts['owing'], counts['unsent']), (1, 1))
        receipt = self.client.get(URL + 'items/', {'category': 'owing'}).data
        self.assertEqual(receipt['meta']['total'], 1)
        row, = receipt['data']['rows']
        self.assertEqual(row['task_id'], str(task.pk))
        self.assertEqual([row['cells'][key] for key in ('sent', 'returned', 'direct', 'remaining')],
                         ['100 片', '30 片', '50 片', '20 片'])
        row, = self.client.get(URL + 'items/', {'category': 'unsent'}).data['data']['rows']
        self.assertEqual(row['cells']['remaining'], '100 片')
