"""对账单保存业务员是财务只读归属，任务换派不能改变该事实。"""
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.organizations.models import Employee
from apps.finance.statement_models import ReceivableStatement
from apps.finance.tests.test_statements import create_source, make_receipt


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ConfirmedFinanceOwnScopeTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.grant('finance.view_receivablestatement', 'OWN')
        self.grant('finance.view_receipt', 'OWN')
        self.other = Employee.objects.create(employee_code='SAVED-OTHER', display_name='其他业务员')
        self.task = create_source(self.scope_employee, quantities=(1,), prices=('100',))
        values = dict(production_task=self.task, task_number_snapshot=self.task.task_number,
            salesperson_code_snapshot='SAVED', salesperson_name_snapshot='保存业务员',
            source_order_date=self.task.order_date, source_revision='1', amount=100,
            created_by_employee=self.scope_employee, updated_by_employee=self.scope_employee)
        self.own = ReceivableStatement.objects.create(number='SAVED-OWN', salesperson=self.scope_employee, **values)
        self.hidden = ReceivableStatement.objects.create(number='SAVED-HIDDEN', salesperson=self.other, **values)
        self.own_receipt = make_receipt(self.own, self.scope_employee)
        self.hidden_receipt = make_receipt(self.hidden, self.scope_employee)

    def test_list_detail_and_receipts_use_saved_salesperson(self):
        for salesperson in (self.other, self.scope_employee):
            self.task.salesperson = salesperson
            self.task.save(update_fields=['salesperson'])
            result = self.client.get('/api/v1/finance/statements/')
            self.assertEqual(result.status_code, 200, result.data)
            self.assertEqual([item['id'] for item in result.data['data']], [str(self.own.pk)])
            self.assertEqual(self.client.get(f'/api/v1/finance/statements/{self.hidden.pk}/').status_code, 404)
            self.assertEqual(self.client.get(f'/api/v1/finance/statements/{self.own.pk}/').status_code, 200)
            result = self.client.get('/api/v1/finance/receipts/')
            self.assertEqual(result.status_code, 200, result.data)
            self.assertEqual([item['id'] for item in result.data['data']], [str(self.own_receipt.pk)])
            self.assertEqual(self.client.get(f'/api/v1/finance/receipts/{self.hidden_receipt.pk}/').status_code, 404)
            self.assertEqual(self.client.get(f'/api/v1/finance/statements/{self.hidden.pk}/receipts/').status_code, 404)
            self.assertEqual(self.client.get(f'/api/v1/finance/statements/{self.own.pk}/receipts/').status_code, 200)
            result = self.client.get(f'/api/v1/finance/receipts/{self.hidden_receipt.pk}/attachments/{uuid4()}/')
            self.assertEqual(result.status_code, 404)

    def test_own_read_does_not_open_finance_source_or_writes(self):
        self.assertEqual(self.client.get('/api/v1/finance/source-tasks/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/v1/finance/source-tasks/{self.task.pk}/products/').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/finance/receipts/', {}, format='json').status_code, 403)

    def test_same_read_permission_module_role_unions_with_own(self):
        self.grant('finance.view_receivablestatement', 'MODULE')
        result = self.client.get(f'/api/v1/finance/statements/{self.hidden.pk}/')
        self.assertEqual(result.status_code, 200, result.data)
