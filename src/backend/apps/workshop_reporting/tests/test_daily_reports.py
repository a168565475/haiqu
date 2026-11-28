import uuid
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.boms.material_flow_calculations import pipe_plan
from apps.inventory.assembly_receipt_models import AssemblyReceiptSource
from apps.inventory.models import FinishedGoodsReceipt, Warehouse, WarehouseLocation, WarehouseZone
from apps.material_issues.tests.test_metal_processing import ProcessingFixture
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Workshop
from apps.workshop_config.tests.factories import production_employee

from . import test_work_report_task_selection as fixtures


URL = '/api/v1/workshop-reporting/daily-reports/'


class DailyReportQueries:
    def data(self, report, day=None, **params):
        response = self.client.get(URL, {
            'report': report, 'date': day or timezone.localdate(), 'task_number': self.task.task_number, **params,
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class MetalDailyReportTests(DailyReportQueries, ProcessingFixture, APITestCase):
    def issue_line(self, quantity=402, confirm=True):
        if not hasattr(self, 'line'):
            f = self.f
            f.product_line.quantity = f.bom.order_quantity = f.schedule_product.source_quantity_snapshot = 500
            f.product_line.save(update_fields=['quantity'])
            f.bom.save(update_fields=['order_quantity'])
            f.schedule_product.save(update_fields=['source_quantity_snapshot'])
            planned = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6,
                                order_quantity=500, calculation_version=2)
            f.profile.pieces_per_product = 2
            f.profile.suggested_bar_count = planned['suggested_bar_count']
            f.profile.suggested_purchase_meters = planned['suggested_purchase_meters']
            f.profile.save()
            f.hardware.delete()
        return super().issue_line(quantity, confirm=confirm)

    def test_qualified_quantity_is_summed_by_part_through_selected_date(self):
        day = timezone.localdate() - timedelta(days=1)
        before = day - timedelta(days=1)
        other_issue = self.issue_line(198)
        self.write('completions', self.complete_payload(400, completion_date=str(before)))
        self.write('completions', self.complete_payload(2, completion_date=str(day)))
        self.write('completions', self.complete_payload(198, completion_date=str(day)), line=other_issue)
        for selected, expected in ((day, ['1000', '200', '600', '400']), (before, ['1000', '400', '400', '600'])):
            row, = self.data('metal', selected)['data']
            self.assertEqual([row[field] for field in ('order_quantity', 'today', 'cumulative', 'remaining')], expected)
            self.assertEqual(row['unit'], '支')
        self.assertEqual(self.data('metal', day, task_number='DOES-NOT-EXIST')['data'], [])


@override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class DailyReportTests(DailyReportQueries, APITestCase):
    setUp = fixtures.WorkReportTaskSelectionTests.setUp
    scheme_payload = fixtures.WorkReportTaskSelectionTests.scheme_payload
    create_approved_scheme = fixtures.WorkReportTaskSelectionTests.create_approved_scheme
    create_report = fixtures.WorkReportTaskSelectionTests.create_report
    copy_values = fixtures.WorkReportTaskSelectionTests.copy_values
    copy_row = fixtures.WorkReportTaskSelectionTests.copy_row
    copy_report = fixtures.WorkReportTaskSelectionTests.copy_report

    def add_category(self, category):
        workshop_name = {'SEWING': '车缝车间', 'ASSEMBLY': '装配车间'}[category]
        workshop, _ = Workshop.objects.get_or_create(name=workshop_name)
        craft = self.copy_row(self.craft, workshop_id=workshop.pk, name=f'日报{workshop_name}', plan_category=category)
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=craft, craft_type_snapshot='INTERNAL',
            craft_name_snapshot=craft.name, plan_category=category,
        )
        return craft

    def test_sewing_counts_each_worker_operation_and_lists_order_once(self):
        original = self.create_report()
        original_line = original.lines.get()
        craft = self.add_category('SEWING')
        worker = production_employee(workshop=craft.workshop, position='操作工', name='缝纫员工甲', is_supervisor=False)
        operation = self.copy_row(self.operation, craft_id=craft.pk, operation_number='WG-SEW-001', name='双针')
        work_item = self.copy_row(original_line.work_item, workshop_id=craft.workshop_id, craft_id=craft.pk, operation_id=operation.pk)
        scheme = self.copy_row(original.scheme, workshop_id=craft.workshop_id, scope_craft_id=craft.pk, scheme_number='GJ-DAILY-SEWING')
        scheme_line = self.copy_row(original_line.scheme_line, scheme_id=scheme.pk, work_item_id=work_item.pk)
        report = self.copy_row(original, scheme_id=scheme.pk, workshop_id=craft.workshop_id, report_number='BG-DAILY-SEWING',
                               client_request_id=uuid.uuid4())
        source = self.copy_row(original_line, report_id=report.pk, scheme_line_id=scheme_line.pk, work_item_id=work_item.pk,
                               quantity='65', workshop_employee_id=worker.pk, employee_name_snapshot=worker.display_name,
                               operation_name_snapshot=operation.name)
        self.copy_report(report, quantity='35')
        self.copy_report(report, quantity='10', day=report.production_date + timedelta(days=1))
        other_employee = production_employee(workshop=craft.workshop, position='操作工', name='缝纫员工乙', is_supervisor=False)
        other_operation = self.copy_row(operation, operation_number='WG-SEW-002', name='包边')
        other_item = self.copy_row(source.work_item, identity_key='daily-other-op', operation_id=other_operation.pk)
        other_scheme_line = self.copy_row(scheme_line, line_number=2, work_item_id=other_item.pk)
        self.copy_row(source, line_number=2, quantity='100', workshop_employee_id=other_employee.pk,
                      employee_name_snapshot=other_employee.display_name, work_item_id=other_item.pk, scheme_line_id=other_scheme_line.pk,
                      operation_name_snapshot=other_operation.name)

        result = self.data('sewing-detail', page_size=1)
        self.assertEqual(result['meta']['total'], 2)
        day_rows = result['data'] + self.data('sewing-detail', page_size=1, page=2)['data']
        self.assertEqual({(row['employee'], row['operation'], row['today']) for row in day_rows}, {
            (worker.display_name, source.operation_name_snapshot, '100'),
            (other_employee.display_name, '包边', '100'),
        })
        order, = self.data('sewing-orders')['data']
        self.assertEqual(order['order_quantity'], '100')
        self.assertIsNone(order['remaining'])

    def receipt(self, number, plan, quantity, submit_day, *, linked=True):
        receipt = FinishedGoodsReceipt.objects.create(
            receipt_number=number, production_task_product=plan.product_line, status='PENDING',
            unit=self.unit, received_quantity=quantity, remaining_quantity=0,
            received_by_employee=self.employee, submitted_by_employee=self.employee,
            submitted_at=timezone.make_aware(datetime.combine(submit_day, time(0, 30))),
        )
        if linked:
            AssemblyReceiptSource.objects.create(receipt=receipt, schedule_product=plan, request_id=uuid.uuid4(),
                                                 receipt_date=submit_day + timedelta(days=3))
        return receipt

    def test_assembly_uses_submission_day_pending_and_confirmed_once_and_keeps_colors_separate(self):
        day = timezone.localdate()
        before = day - timedelta(days=1)
        craft = self.add_category('ASSEMBLY')
        other = self.copy_row(self.product_line, line_number=2, color_name_snapshot='蓝色', quantity=70)
        other_plan = self.copy_row(self.schedule_product, product_line_id=other.pk, line_number=2,
                                   planned_quantity=70, source_quantity_snapshot=70)
        self.copy_row(self.schedule_product.crafts.get(craft=craft), schedule_product_id=other_plan.pk)
        pending = self.receipt('DAILY-01', self.schedule_product, 30, before)
        self.receipt('DAILY-02', self.schedule_product, 40, day)
        self.receipt('DAILY-03', other_plan, 10, day)
        self.receipt('DAILY-FUTURE', other_plan, 5, day + timedelta(days=1))
        self.receipt('DAILY-NOT-ASSEMBLY', self.schedule_product, 11, day, linked=False)

        def amounts(selected):
            return [(row['color'], row['order_quantity'], row['today'], row['cumulative'], row['remaining'])
                    for row in self.data('assembly', selected)['data']]

        expected = [(self.product_line.color_name_snapshot, '100', '40', '70', '30'), ('蓝色', '70', '10', '10', '60')]
        self.assertEqual(amounts(day), expected)
        warehouse = Warehouse.objects.create(warehouse_number='DAILY', warehouse_name='成品仓', warehouse_type='FINISHED')
        location = WarehouseLocation.objects.create(zone=WarehouseZone.objects.create(warehouse=warehouse, zone_name='A'),
                                                   location_number='01')
        FinishedGoodsReceipt.objects.filter(pk=pending.pk).update(status='CONFIRMED', location=location, confirmed_at=timezone.now())
        self.assertEqual(amounts(day), expected)
        self.assertEqual(amounts(before), [(self.product_line.color_name_snapshot, '100', '30', '30', '70'),
                                           ('蓝色', '70', '0', '0', '70')])

    @override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_a_scoped_report_grant_cannot_read_metal_or_other_workshops(self):
        craft = self.add_category('ASSEMBLY')
        user = get_user_model().objects.create_user(username='daily-report-reader')
        actor = Employee.objects.create(user=user, employee_code='DAILY-READER', display_name='日报查看员')
        role = RoleProfile.objects.create(role_code='DAILY_REPORT', display_name='日报岗位', auth_group=Group.objects.create(name='daily-report'))
        EmployeeRoleAssignment.objects.create(employee=actor, role_profile=role, effective_from=timezone.now())
        permission = Permission.objects.get(content_type__app_label='workshop_reporting', codename='view_workreport')
        role.auth_group.permissions.add(permission)
        grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='WORKSHOP')
        selection = RoleGrantResource.objects.create(grant=grant, workshop=self.workshop)
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(URL, {'report': 'metal'}).status_code, 403)
        self.assertEqual(self.data('assembly')['data'], [])
        selection.workshop = craft.workshop
        selection.save(update_fields=['workshop'])
        order, = self.data('assembly')['data']
        self.assertEqual(order['order_quantity'], '100')
        self.assertNotIn('today', order)
        self.assertEqual(self.client.get(URL, {'report': 'sewing-orders', 'date': '2026-02-30'}).status_code, 400)
        self.assertEqual(self.client.get(URL, {'report': 'unknown'}).status_code, 400)
        self.assertEqual(self.client.post(URL, {}).status_code, 405)
        self.assertEqual(APIClient().get(URL).status_code, 401)
