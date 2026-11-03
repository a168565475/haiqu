from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase

from apps.finance.statement_models import ReceivableStatement
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency
from apps.workshop_config.models import Workshop
from apps.access_control.catalog import scopes_for, validate_grants
from apps.access_control.production_role_templates import templates, GROUP_ONLY_ROLES
from apps.access_control.role_policy import (
    allowed_task_update_fields, filter_statement_scope, filter_task_scope, require_task_edit_fields,
)
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ConfirmedRolePolicyTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.other = Employee.objects.create(employee_code='FOLLOWED-OTHER', display_name='其他员工')

    def task(self, number, salesperson=None):
        return ProductionTask.objects.create(task_number=number, contract_number=number,
            order_source='NEW', order_number=number, order_date=timezone.localdate(),
            delivery_date=timezone.localdate(), salesperson=salesperson or self.scope_employee,
            currency=Currency.objects.get(code='CNY'), includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method='SINGLE',
            created_by_employee=self.scope_employee)

    def test_followed_is_current_relationship_not_creator_or_salesperson(self):
        self.grant('production_tasks.view_productiontask', 'FOLLOWED')
        own = self.task('FOLLOWED-ONE', self.other)
        other = self.task('FOLLOWED-TWO')
        own.followers.add(self.scope_employee)
        request = self.scoped_request()
        visible = filter_task_scope(request, ProductionTask.objects.all(), 'production_tasks.view_productiontask', '')
        self.assertEqual(list(visible), [own])
        own.followers.clear()
        self.assertFalse(filter_task_scope(request, ProductionTask.objects.all(), 'production_tasks.view_productiontask', '').exists())
        self.grant('production_tasks.view_productiontask', 'MODULE')
        visible = filter_task_scope(self.scoped_request(), ProductionTask.objects.all(), 'production_tasks.view_productiontask', '')
        self.assertEqual(set(visible), {own, other})

    def test_followed_cannot_be_configured_for_write(self):
        self.assertIn('FOLLOWED', scopes_for('boms.view_bom'))
        with self.assertRaises(ValidationError):
            validate_grants([{'permission': 'boms.change_bom', 'scope': 'FOLLOWED'}])

    def test_statement_scope_uses_saved_salesperson_after_task_transfer(self):
        self.grant('finance.view_receivablestatement', 'OWN')
        task = self.task('STATEMENT-TASK', self.other)
        values = dict(production_task=task, task_number_snapshot=task.task_number,
            salesperson_code_snapshot='SAVED', salesperson_name_snapshot='保存归属',
            source_order_date=timezone.localdate(), source_revision='1', amount=100,
            created_by_employee=self.scope_employee, updated_by_employee=self.scope_employee)
        own = ReceivableStatement.objects.create(number='SAVED-ONE', salesperson=self.scope_employee, **values)
        ReceivableStatement.objects.create(number='SAVED-TWO', salesperson=self.other, **values)
        visible = filter_statement_scope(self.scoped_request(), ReceivableStatement.objects.all(), 'finance.view_receivablestatement')
        self.assertEqual(list(visible), [own])
        task.salesperson = self.scope_employee
        task.save(update_fields=['salesperson'])
        self.assertEqual(list(visible), [own])
        self.grant('boms.view_bom', 'FOLLOWED')
        task.followers.add(self.scope_employee)
        self.assertEqual(filter_task_scope(self.scoped_request(), ReceivableStatement.objects.all(),
                                         'boms.view_bom', 'production_task').count(), 2)

    def test_plan_edit_rejects_unapproved_fields_and_full_editor_can_still_edit(self):
        with self.assertRaises(PermissionDenied):
            require_task_edit_fields(self.scoped_request(), {'planned_start_date'})
        self.grant('access_control.edit_productionplan')
        request = self.scoped_request()
        self.assertIn('follower_ids', allowed_task_update_fields(request))
        require_task_edit_fields(request, {'planned_start_date', 'planned_end_date', 'followers'})
        require_task_edit_fields(request, {'follower_ids', 'production_priority'})
        for field in ('products', 'delivery_date', 'unknown_field'):
            with self.assertRaises(ValidationError):
                require_task_edit_fields(request, {field})
        self.grant('production_tasks.change_productiontask')
        self.assertIsNone(allowed_task_update_fields(self.scoped_request()))

    def test_templates_separate_business_scope_and_unplanned_roles(self):
        rows = templates(dict(Workshop.objects.values_list('name', 'pk')))
        for grants in rows.values():
            validate_grants(grants)
        codes = lambda role: {row['permission'] for row in rows[role]}
        self.assertNotIn('boms.view_bom', codes('PURCHASING'))
        self.assertNotIn('production_tasks.change_productiontask', codes('PMC'))
        self.assertIn('access_control.sync_bomquantity', codes('TECHNICAL'))
        self.assertIn('access_control.sync_bomquantity', codes('FACTORY_MANAGER'))
        self.assertIn('material_issues.view_metalprocessingsource', codes('FACTORY_MANAGER'))
        self.assertNotIn('material_issues.view_metalprocessingsource', codes('WAREHOUSE_KEEPER'))
        self.assertNotIn('access_control.sync_bomquantity', codes('PMC'))
        self.assertEqual({row['scope'] for row in rows['MERCHANDISER']}, {'FOLLOWED'})
        self.assertEqual(rows['FINANCE'], rows['CASHIER'])
        self.assertNotIn('access_control.void_productiontaskexpense', codes('FINANCE'))
        self.assertNotIn('production_tasks.manage_productiontaskexpense', codes('FACTORY_MANAGER'))
        self.assertTrue(all(code.startswith('finance.view_') for code in codes('FACTORY_MANAGER') if code.startswith('finance.')))
        self.assertFalse(any(code.startswith(('customers.', 'sales_orders.', 'inquiries.', 'quotations.')) for code in codes('FACTORY_MANAGER')))
        self.assertIn('access_control.cuttingreport_sample', codes('FABRIC_SAMPLING'))
        self.assertNotIn('access_control.complete_samplerequest', codes('FABRIC_SAMPLING'))
        self.assertTrue(all(rows[role] == [] for role in GROUP_ONLY_ROLES))
