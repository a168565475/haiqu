from decimal import Decimal
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, APITestCase

from apps.core.api.concurrency import etag_for_instance, PreconditionRequired, PreconditionFailed
from apps.core.api.exceptions import Conflict
from apps.production_tasks.tests.test_dashboard_api import DashboardFixture
from apps.production_tasks.api.cost_serializers import ProductionTaskExpenseWriteSerializer
from apps.production_tasks.cost_models import ProductionTaskExpense
from apps.production_tasks.cost_services import create_task_expense, update_task_expense, void_task_expense


class CostPermissionLabelsTests(SimpleTestCase):
    def test_cost_catalog_labels_work_before_migration(self):
        from apps.access_control.presentation import presentation
        for code, label in [('view_productiontaskcost', '查看订单成本'),
                            ('manage_productiontaskexpense', '维护订单零星费用')]:
            result = presentation(f'production_tasks.{code}', None, 'production_tasks')
            self.assertEqual(result['resource_name'], '订单成本')
            self.assertEqual(result['action_name'], label)


class ExpenseValidationTests(TestCase):
    def test_invalid_amount_description_and_date(self):
        valid = dict(expense_type='OTHER', description='运费', amount='1.00', occurred_on='2026-10-26', client_request_id=str(uuid4()))
        for field, value in [('amount', '0'), ('amount', '-1'), ('amount', '10000000000000000'), ('description', '  '), ('occurred_on', 'bad')]:
            serializer = ProductionTaskExpenseWriteSerializer(data={**valid, field: value})
            self.assertFalse(serializer.is_valid(), (field, value))


class ExpenseServiceTests(DashboardFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.production_task = self.task('EXPENSE')
        self.payload = dict(expense_type='TRANSPORT', description='运输', amount=Decimal('10.00'), occurred_on=self.today, remark='', client_request_id=uuid4())
        self.request = APIRequestFactory().post('/')

    def create_expense(self, task=None, payload=None):
        return create_task_expense(task=task or self.production_task, validated_data=payload or self.payload, actor_employee=self.employee, request=self.request)

    def test_replay_and_conflict(self):
        expense, created = self.create_expense()
        self.assertTrue(created)
        replay, created = self.create_expense()
        self.assertFalse(created)
        self.assertEqual(expense.pk, replay.pk)
        with self.assertRaises(Conflict):
            self.create_expense(payload={**self.payload, 'amount': Decimal('11.00')})
        with self.assertRaises(Conflict):
            self.create_expense(task=self.task('ANOTHER'))
        self.assertEqual(ProductionTaskExpense.objects.count(), 1)

    def test_etag_update_void_and_no_resurrection(self):
        expense, _ = self.create_expense()
        arguments = dict(task=self.production_task, expense_id=expense.pk, validated_data={'amount': Decimal('12.00')}, actor_employee=self.employee)
        with self.assertRaises(PreconditionRequired):
            update_task_expense(**arguments, request=self.request)
        old = etag_for_instance(expense)
        request = APIRequestFactory().patch('/', HTTP_IF_MATCH=old)
        updated = update_task_expense(**arguments, request=request)
        self.assertEqual(updated.amount, Decimal('12.00'))
        replay, created = self.create_expense()
        self.assertFalse(created)
        self.assertEqual(replay.pk, updated.pk)
        with self.assertRaises(PreconditionFailed):
            update_task_expense(**arguments, request=request)
        void_task_expense(task=self.production_task, expense_id=expense.pk, actor_employee=self.employee, request=APIRequestFactory().delete('/', HTTP_IF_MATCH=etag_for_instance(updated)))
        with self.assertRaises(Conflict):
            self.create_expense()

    def test_archived_task_rejects_create(self):
        from django.utils import timezone
        self.production_task.archived_at = timezone.now()
        self.production_task.save(update_fields=['archived_at'])
        with self.assertRaises(Conflict):
            self.create_expense()


class ExpenseApiTests(DashboardFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.production_task = self.task('EXPENSE-API')
        self.url = f'/api/v1/production-tasks/{self.production_task.pk}/cost-expenses/'
        self.payload = dict(expense_type='LOADING', description='装卸', amount='25.00', occurred_on=str(self.today), client_request_id=str(uuid4()))

    def test_dedicated_permissions_and_replay(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.grant('production_tasks.view_productiontaskcost')
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 403)
        self.grant('production_tasks.manage_productiontaskexpense')
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('etag', response.data['data'])
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 200)
        self.assertEqual(len(self.client.get(self.url).data['data']), 1)

    def test_patch_delete_preconditions_and_task_isolation(self):
        self.grant('production_tasks.view_productiontaskcost', 'production_tasks.manage_productiontaskexpense')
        created = self.client.post(self.url, self.payload, format='json').data['data']
        url = f'{self.url}{created["id"]}/'
        self.assertEqual(self.client.patch(url, {'amount': '26.00'}, format='json').status_code, 428)
        self.assertEqual(self.client.patch(url, {'amount': '26.00'}, format='json', HTTP_IF_MATCH='old').status_code, 412)
        other = self.task('EXPENSE-ISOLATION')
        other_url = f'/api/v1/production-tasks/{other.pk}/cost-expenses/{created["id"]}/'
        self.assertEqual(self.client.patch(other_url, {'amount': '26.00'}, format='json', HTTP_IF_MATCH=created['etag']).status_code, 404)
        self.assertEqual(self.client.patch(f'{self.url}invalid-uuid/', {'amount': '26.00'}, format='json', HTTP_IF_MATCH=created['etag']).status_code, 400)
        updated = self.client.patch(url, {'amount': '26.00'}, format='json', HTTP_IF_MATCH=created['etag'])
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=updated.data['data']['etag']).status_code, 204)
        self.assertEqual(self.client.get(self.url).data['data'], [])
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 409)

