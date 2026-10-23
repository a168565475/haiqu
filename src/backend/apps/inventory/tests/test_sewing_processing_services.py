from apps.workshop_config.tests.factories import production_employee
"""隔离 PostgreSQL 中验证车缝报工与首次产出共用额度，不操作真实业务库。"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import PreconditionFailed
from apps.outsourcing.models import OutsourcingFactory, TubeOutsourcingLine, TubeOutsourcingOrder
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft, Operation
from apps.workshop_reporting.models import WageScheme, WageSchemeCraft, WageSchemeLine, WorkItem, WorkReport, WorkReportLine
from ..sewing_processing_services import (
    assert_sewing_quantity_available, assert_sewing_reports_cover_usage, sewing_component_limits,
)
from . import test_internal_receipt_sewing as sewing_fixture


class SewingProcessingFixture(sewing_fixture.SewingFixture):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save(update_fields=['is_superuser', 'is_staff'])
        self.today = timezone.localdate()
        self.component = str(self.parts[0].component_identity)
        self.sewing_workshop = self.sewing_plan_craft.workshop
        self.worker = production_employee(workshop=self.sewing_workshop, position='车缝工', name='裁片测试员工',
            is_supervisor=False)
        self.sheet_unit, _ = ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code':'SEW-PIECE'})
        self.items = []
        for index, (mode, unit) in enumerate([('SET', self.set_unit), ('PIECE', self.sheet_unit)], 1):
            operation = Operation.objects.create(operation_number=f'SEW-TEST-{index}', product_name='裁片测试',
                craft=self.sewing_plan_craft, name=f'车缝工序{index}', reporting_unit=unit)
            self.items.append(WorkItem.objects.create(product_line=self.product_line, workshop=self.sewing_workshop,
                craft=self.sewing_plan_craft, operation=operation, unit=unit, identity_key=uuid.uuid4().hex,
                display_name=self.parts[0].part_name, bom_component_identity=self.parts[0].component_identity,
                counting_mode=mode))
        self.scheme, self.scheme_lines = self.make_scheme()
        self.print_craft, _ = Craft.objects.get_or_create(outsourcing_code='SCREEN_PRINTING',
            defaults={'name':'裁片测试丝印', 'craft_type':'EXTERNAL', 'created_by_employee':self.employee})
        self.factory = OutsourcingFactory.objects.create(factory_number='SEW-DIRECT-FACTORY', name='裁片测试厂',
            processing_type='丝印', created_by_employee=self.employee, updated_by_employee=self.employee)

    def make_scheme(self, *, parent=None, day=None, items=None):
        scheme = WageScheme.objects.create(scheme_number=f'SEW-SCHEME-{WageScheme.objects.count()+1}',
            product_line=self.product_line, schedule_product=self.schedule_product, workshop=self.sewing_workshop,
            scope_craft=self.sewing_plan_craft, status='APPROVED', effective_from=day or self.today-timedelta(days=10),
            parent_scheme=parent, version=parent.version+1 if parent else 1, product_name_snapshot='裁片测试',
            operation_product_name_snapshot='裁片测试', created_by_employee=self.employee,
            updated_by_employee=self.employee, approved_by_employee=self.employee, approved_at=timezone.now())
        WageSchemeCraft.objects.create(scheme=scheme, craft=self.sewing_plan_craft)
        lines = []
        for index, item in enumerate(items or self.items, 1):
            lines.append(WageSchemeLine.objects.create(scheme=scheme, work_item=item, line_number=index,
                display_name_snapshot=item.display_name, craft_name_snapshot=self.sewing_plan_craft.name,
                operation_name_snapshot=item.operation.name, operation_number_snapshot=item.operation.operation_number,
                unit_name_snapshot=item.unit.unit_name, bom_component_identity_snapshot=self.parts[0].component_identity,
                counting_mode=item.counting_mode, order_quantity_snapshot=500, bom_sets_per_product_snapshot=1,
                bom_pieces_per_set_snapshot=2, required_quantity_snapshot=500 if item.counting_mode=='SET' else 1000,
                declared_price=1))
        return scheme, lines

    def report(self, quantities=(200, 300), *, lines=None, day=None):
        lines = lines or self.scheme_lines
        report = WorkReport.objects.create(report_number=f'SEW-REPORT-{WorkReport.objects.count()+1}',
            production_date=day or self.today, product_line=self.product_line, schedule_product=self.schedule_product,
            workshop=self.sewing_workshop, scheme=lines[0].scheme, scheme_version_snapshot=lines[0].scheme.version,
            recorder_employee=self.employee, updated_by_employee=self.employee, total_amount=sum(quantities),
            client_request_id=uuid.uuid4(), request_payload_hash='e'*64)
        for index, (quantity, line) in enumerate(zip(quantities, lines), 1):
            if quantity:
                WorkReportLine.objects.create(report=report, line_number=index, scheme_line=line, work_item=line.work_item,
                    workshop_employee=self.worker, quantity=quantity, order_quantity_snapshot=500,
                    required_quantity_snapshot=line.required_quantity_snapshot, unit_price_snapshot=1, amount=quantity,
                    display_name_snapshot=line.display_name_snapshot, craft_name_snapshot=line.craft_name_snapshot,
                    operation_name_snapshot=line.operation_name_snapshot, unit_name_snapshot=line.unit_name_snapshot,
                    employee_name_snapshot=self.worker.display_name)
        return report

    def direct(self, quantity, *, status='PENDING_DISPATCH'):
        order = TubeOutsourcingOrder.objects.create(order_number=f'SEW-DIRECT-{TubeOutsourcingOrder.objects.count()+1}',
            schedule_product=self.schedule_product, product_line=self.product_line, bom=self.bom, craft=self.print_craft,
            source_kind='SEWING', planned_dispatch_date=self.today, expected_return_date=self.today, status=status,
            client_request_id=uuid.uuid4(), request_payload_hash='a'*64, source_revision_hash='b'*64,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        TubeOutsourcingLine.objects.create(order=order, bom_line=self.parts[0], component_identity=self.parts[0].component_identity,
            factory=self.factory, quantity=quantity)
        return order

    def component_limit(self, **kwargs):
        return sewing_component_limits(self.product_line, **kwargs)['components'][self.component]


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
    WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True,
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class SewingProcessingTests(SewingProcessingFixture, TestCase):
    url = sewing_fixture.InternalSewingReceiptTests.url
    preview = sewing_fixture.InternalSewingReceiptTests.preview
    receive = sewing_fixture.InternalSewingReceiptTests.receive

    def test_no_report_has_no_direct_quota_but_existing_receipt_remains_available(self):
        row = self.component_limit()
        self.assertTrue(row['basis_ready'], row)
        self.assertEqual(row['allowance']['remaining'], 0)
        self.assertEqual(self.receive(10).status_code, 201)

    def test_required_operations_take_minimum_and_piece_count_uses_frozen_factor(self):
        self.report((200, 301))
        row = self.component_limit()
        self.assertEqual(row['allowance']['reported_minimum'], 150)
        self.assertEqual(row['allowance']['remaining'], 150)
        self.parts[0].cutting_pieces_per_set = 99
        self.parts[0].save(update_fields=['cutting_pieces_per_set'])
        self.assertFalse(self.component_limit()['basis_ready'])
        self.assertIn('当前裁片实物属性冲突', str(self.component_limit()['blockers']))

    def test_missing_conflicting_or_less_than_one_set_frozen_basis_blocks(self):
        self.report((200, 1))
        self.assertIn('不足一整套', str(self.component_limit()['blockers']))
        WorkReportLine.objects.filter(work_item=self.items[1]).update(quantity=300)
        WageSchemeLine.objects.filter(pk=self.scheme_lines[1].pk).update(bom_pieces_per_set_snapshot=None)
        self.assertFalse(self.component_limit()['basis_ready'])

    def test_future_reports_cannot_support_current_dispatch(self):
        self.report(day=self.today+timedelta(days=1))
        self.assertEqual(self.component_limit()['allowance']['remaining'], 0)

    def test_partial_report_of_one_operation_does_not_count_other_operations(self):
        self.report((200, 0))
        self.assertEqual(self.component_limit()['allowance']['remaining'], 0)

    def test_receive_then_direct_deducts_first_receipts_and_preserves_receipt_counts(self):
        self.report((200, 300))
        self.assertEqual(self.receive(100).status_code, 201)
        row = self.component_limit()
        self.assertEqual((row['allowance']['received'], row['allowance']['remaining']), (100, 50))
        self.direct(50)
        self.assertEqual(self.component_limit()['allowance']['remaining'], 0)

    def test_direct_then_receipt_and_cancel_share_order_quota(self):
        self.report((500, 1000))
        order = self.direct(120)
        row = next(row for row in self.preview()['lines'] if row['bom_line_id']==str(self.parts[0].pk))
        self.assertEqual((row['received'], row['directly_committed'], row['can_receive']), ('0', '120', '380'))
        self.assertEqual(self.receive(381).status_code, 400)
        self.assertEqual(self.receive(380).status_code, 201)
        TubeOutsourcingOrder.objects.filter(pk=order.pk).update(status='CANCELLED')
        self.assertEqual(self.receive(120).status_code, 201)

    def test_pending_dispatched_completed_and_excluded_order_use_same_output(self):
        self.report((500, 1000))
        pending = self.direct(70)
        self.direct(80, status='PROCESSING')
        self.direct(90, status='COMPLETED')
        self.direct(60, status='CANCELLED')
        row = self.component_limit()['allowance']
        self.assertEqual((row['reserved'], row['dispatched'], row['remaining']), (70, 170, 260))
        self.assertEqual(self.component_limit(exclude_tube_order_id=pending.pk)['allowance']['remaining'], 330)

    def test_history_over_report_or_order_is_explicit_conflict(self):
        self.report((100, 200))
        self.direct(101)
        self.assertFalse(self.component_limit()['basis_ready'])
        self.assertIn('超过有效报工', str(self.component_limit()['blockers']))
        with self.assertRaises(ValidationError):
            assert_sewing_reports_cover_usage(self.product_line.pk)

    def test_receipts_without_direct_do_not_add_report_mutation_restriction(self):
        self.assertEqual(self.receive(100).status_code, 201)
        assert_sewing_reports_cover_usage(self.product_line.pk)

    def test_quantity_guard_uses_revision_and_rechecks_under_shared_lock(self):
        self.report()
        context = sewing_component_limits(self.product_line)
        with transaction.atomic():
            assert_sewing_quantity_available(product_line_id=self.product_line.pk, requested={self.component:150},
                expected_revision=context['revision'])
        self.direct(1)
        with self.assertRaises(PreconditionFailed), transaction.atomic():
            assert_sewing_quantity_available(product_line_id=self.product_line.pk, requested={self.component:150},
                expected_revision=context['revision'])

    def test_historical_piece_factor_conflict_after_version_change_is_not_guessed(self):
        self.report()
        self.scheme.status = 'SUPERSEDED'
        self.scheme.save(update_fields=['status'])
        _, lines = self.make_scheme(parent=self.scheme, day=self.today)
        WageSchemeLine.objects.filter(pk=lines[1].pk).update(bom_pieces_per_set_snapshot=3)
        self.parts[0].cutting_pieces_per_set = 3
        self.parts[0].save(update_fields=['cutting_pieces_per_set'])
        self.assertIn('每套片数缺失或存在冲突', str(self.component_limit()['blockers']))

    def test_work_report_edit_below_direct_usage_rolls_back(self):
        report = self.report()
        self.direct(100)
        base = f'/api/v1/workshop-reporting/work-reports/{report.pk}/'
        detail = self.client.get(base)
        self.assertEqual(detail.status_code, 200, detail.data)
        payload = {'schedule_product_id':str(self.schedule_product.pk), 'scheme_id':str(self.scheme.pk),
            'scheme_revision':self.scheme.revision, 'production_date':str(self.today), 'lines':[
                {'scheme_line_id':str(line.pk), 'workshop_employee_id':str(self.worker.pk), 'quantity':quantity}
                for line, quantity in zip(self.scheme_lines, ['99', '300'])]}
        response = self.client.patch(base, payload, format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('100套', str(response.data))
        self.assertEqual(WorkReportLine.objects.get(report=report, work_item=self.items[0]).quantity, 200)

    def test_work_report_delete_with_direct_usage_rolls_back(self):
        report = self.report()
        self.direct(100)
        base = f'/api/v1/workshop-reporting/work-reports/{report.pk}/'
        detail = self.client.get(base)
        self.assertEqual(detail.status_code, 200, detail.data)
        response = self.client.delete(base, {'reason':'验证直发占用保护'}, format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('100套', str(response.data))
        self.assertEqual(WorkReportLine.objects.filter(report=report).count(), 2)

    def test_future_scheme_with_new_unreported_operation_cannot_replace_direct_basis(self):
        self.report()
        self.direct(100)
        operation = Operation.objects.create(operation_number='SEW-TEST-NEW', product_name='裁片测试',
            craft=self.sewing_plan_craft, name='新增车缝工序', reporting_unit=self.set_unit)
        base = f'/api/v1/workshop-reporting/wage-schemes/{self.scheme.pk}/'
        lines = [{'craft_id':str(self.sewing_plan_craft.pk), 'operation_id':str(item.operation_id),
            'bom_line_id':str(self.parts[0].pk), 'work_item_id':str(item.pk),
            'display_name':self.parts[0].part_name,
            'counting_mode':item.counting_mode, 'declared_price':'2', 'status':'ACTIVE'} for item in self.items]
        lines.append({'craft_id':str(self.sewing_plan_craft.pk), 'operation_id':str(operation.pk),
            'bom_line_id':str(self.parts[0].pk), 'display_name':self.parts[0].part_name,
            'counting_mode':'SET', 'declared_price':'2', 'status':'ACTIVE'})
        payload = {'product_line_id':str(self.product_line.pk), 'schedule_product_id':str(self.schedule_product.pk),
            'workshop_id':str(self.sewing_workshop.pk), 'craft_ids':[str(self.sewing_plan_craft.pk)],
            'operation_product_name':'裁片测试', 'lines':lines}
        changed = self.client.post(base+'change/', payload, format='json', HTTP_IF_MATCH=self.client.get(base)['ETag'])
        self.assertEqual(changed.status_code, 201, changed.data)
        new_base = f'/api/v1/workshop-reporting/wage-schemes/{changed.data["data"]["id"]}/'
        submitted = self.client.post(new_base+'submit/', {}, format='json', HTTP_IF_MATCH=changed['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        approved = self.client.post(new_base+'approve/', {'effective_from':str(self.today+timedelta(days=3))},
            format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(approved.status_code, 400, approved.data)
        self.assertIn('100套', str(approved.data))
        self.scheme.refresh_from_db()
        self.assertIsNone(self.scheme.effective_to)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class SewingProcessingConcurrencyTests(SewingProcessingFixture, TransactionTestCase):
    serialized_rollback = True

    def test_two_direct_reservations_cannot_spend_same_report_output(self):
        self.report()
        context = sewing_component_limits(self.product_line)
        barrier = Barrier(2)

        def reserve():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                    assert_sewing_quantity_available(product_line_id=self.product_line.pk,
                        requested={self.component:100}, expected_revision=context['revision'])
                    self.direct(100)
                    return 'created'
            except PreconditionFailed:
                return 'stale'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ['created', 'stale'])
        self.assertEqual(TubeOutsourcingOrder.objects.filter(source_kind='SEWING').count(), 1)
        self.assertEqual(self.component_limit()['allowance']['remaining'], 50)
