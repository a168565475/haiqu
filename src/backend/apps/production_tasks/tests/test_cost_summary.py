from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock
from datetime import date
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.production_tasks.cost_selectors import task_cost_summary
from apps.production_tasks.models import ProductionTask
from apps.procurement.models import (PurchaseOrder, Supplier, SupplierPurchaseSheet,
                                     PurchaseContractTemplate, PurchaseContractTemplateVersion)
from .test_dashboard_api import DashboardFixture
from apps.workshop_reporting.tests import test_workshop_reporting_api as reporting_fixtures
from django.utils import timezone


class CostSummaryTests(SimpleTestCase):
    def summary(self, *, products=None, **sources):
        task = SimpleNamespace(pk='task-1', currency=SimpleNamespace(code='CNY'),
                               freight_amount=Decimal('0'), other_fee_amount=Decimal('0'))
        data = dict(products=products or [], purchases=[], sheets=[], allocations=[],
                    reports=[], outsourcing=[], tube=[], expenses=[])
        data.update(sources)
        with patch('apps.production_tasks.cost_selectors._cost_sources', return_value=data):
            return task_cost_summary(task=task)

    def product(self, amount='100', currency='CNY', rate='1', snapshot=None):
        return SimpleNamespace(total_amount=Decimal(amount), currency=SimpleNamespace(code=currency),
                               exchange_rate=Decimal(rate), exchange_rate_snapshot=snapshot or {})

    def test_current_report_amount_and_zero_order(self):
        report = SimpleNamespace(pk='r1', report_number='BG1', total_amount=Decimal('12.50'),
                                 production_date=None)
        summary = self.summary(products=[self.product('0')], reports=[report])
        self.assertEqual(summary['recorded_cost'], '12.50')
        self.assertEqual(summary['current_difference'], '-12.50')
        self.assertIsNone(summary['cost_ratio'])
        self.assertTrue(summary['complete'])

    def test_foreign_purchase_is_gap_and_known_partial_preserved(self):
        purchase = SimpleNamespace(pk='p1', order_number='CG1', total_amount=Decimal('20'),
                                   currency_code_snapshot='USD', created_at=None)
        report = SimpleNamespace(pk='r1', report_number='BG1', total_amount=Decimal('3'), production_date=None)
        summary = self.summary(products=[self.product()], purchases=[purchase], reports=[report])
        self.assertEqual(summary['recorded_cost'], '3.00')
        self.assertEqual(summary['missing_count'], 1)
        self.assertIsNone(summary['current_difference'])
        self.assertIsNone(summary['cost_ratio'])
        self.assertEqual(summary['categories'][0]['items'][0]['amount'], '20.00')

    def test_order_foreign_currency_requires_saved_snapshot(self):
        summary = self.summary(products=[self.product('20', 'USD', '7')])
        self.assertIsNone(summary['order_amount'])
        self.assertFalse(summary['complete'])
        summary = self.summary(products=[self.product('20', 'USD', '7', {'source': 'saved'})])
        self.assertEqual(summary['order_amount'], '140.00')

    def test_tube_missing_price_not_zero_cost(self):
        order = SimpleNamespace(pk='o1', order_number='WF1', created_at=None)
        line = SimpleNamespace(pk='l1', order=order, quantity=3, unit_price=None)
        summary = self.summary(products=[self.product()], tube=[line])
        self.assertFalse(summary['complete'])
        self.assertIsNone(summary['categories'][2]['items'][0]['amount_cny'])

    def test_request_sheet_uses_existing_yuan_contract(self):
        sheet = SimpleNamespace(pk='s1', sheet_number='CGDD1', total_amount=Decimal('8'),
                                content_snapshot={}, created_at=None)
        summary = self.summary(products=[self.product()], sheets=[sheet])
        self.assertEqual(summary['recorded_cost'], '8.00')
        self.assertEqual(summary['missing_count'], 0)
        self.assertEqual(summary['categories'][0]['items'][0]['currency'], 'CNY')

    def test_each_cost_rounds_half_up_and_expenses_count(self):
        order = SimpleNamespace(pk='o1', order_number='WF1', created_at=None)
        item = SimpleNamespace(pk='a1', processing_item=SimpleNamespace(order_product=SimpleNamespace(order=order)),
                               allocated_quantity=Decimal('1'), unit_price=Decimal('1.005'))
        expense = SimpleNamespace(pk='e1', description='运费', amount=Decimal('2'), occurred_on=None)
        summary = self.summary(products=[self.product()], outsourcing=[item], expenses=[expense])
        self.assertEqual(summary['recorded_cost'], '3.01')
        self.assertEqual(summary['cost_ratio'], '3.01')

    def test_partial_purchase_lines_and_currency_relation_fallback(self):
        lines = Mock()
        lines.all.return_value = [SimpleNamespace(pk='l1', line_number=1, amount=Decimal('8')),
                                  SimpleNamespace(pk='l2', line_number=2, amount=None)]
        order = SimpleNamespace(pk='p1', order_number='CG1', total_amount=None, lines=lines,
                                currency_code_snapshot='', currency=SimpleNamespace(code='CNY'), created_at=None)
        summary = self.summary(products=[self.product()], purchases=[order])
        self.assertEqual(summary['recorded_cost'], '8.00')
        self.assertEqual(summary['missing_count'], 1)
        self.assertEqual(len(summary['categories'][0]['items']), 2)

    def test_partial_sheet_lines_and_complete_total_never_double_count(self):
        sheet = SimpleNamespace(pk='s1', sheet_number='CGDD1', total_amount=None, created_at=None,
                                content_snapshot={'lines': [{'amount': '8.125'}, {'amount': ''}]})
        summary = self.summary(products=[self.product()], sheets=[sheet])
        self.assertEqual(summary['recorded_cost'], '8.13')
        self.assertEqual(summary['missing_count'], 1)
        sheet.total_amount = Decimal('20')
        summary = self.summary(products=[self.product()], sheets=[sheet])
        self.assertEqual(summary['recorded_cost'], '20.00')
        self.assertEqual(summary['missing_count'], 0)

    def test_maximum_saved_product_and_exchange_rate_keep_decimal_precision(self):
        product = self.product('999999999999999999.9999', 'USD',
                               '99999999999999999.99999999', {'saved': True})
        summary = self.summary(products=[product])
        self.assertEqual(summary['order_amount'], '99999999999999999999989990000000000.00')

    def test_report_link_uses_read_only_day_detail(self):
        report = SimpleNamespace(pk='r1', report_number='BG1', total_amount=Decimal('3'),
                                 production_date=date(2026, 10, 26), schedule_product_id='sp1')
        summary = self.summary(products=[self.product()], reports=[report])
        self.assertEqual(summary['categories'][1]['items'][0]['href'],
                         '/workshop/work-reports/days/2026-10-26?schedule_product_id=sp1')

    def test_invalid_historical_sheet_amounts_remain_explicit_gaps(self):
        sheet = SimpleNamespace(pk='s1', sheet_number='CGDD1', total_amount=None, created_at=None,
                                content_snapshot={'lines': [{'amount': value} for value in
                                                           ['NaN', 'Infinity', 'broken', '-1', '1e100']]})
        summary = self.summary(products=[self.product()], sheets=[sheet])
        self.assertEqual(summary['recorded_cost'], '0.00')
        self.assertEqual(summary['missing_count'], 5)
        self.assertFalse(summary['complete'])

    def test_half_cent_order_uses_displayed_amount_for_difference_and_ratio(self):
        expense = SimpleNamespace(pk='e1', description='零星费用', amount=Decimal('0.01'), occurred_on=None)
        summary = self.summary(products=[self.product('0.0050')], expenses=[expense])
        self.assertEqual(summary['order_amount'], '0.01')
        self.assertEqual(summary['recorded_cost'], '0.01')
        self.assertEqual(summary['current_difference'], '0.00')
        self.assertEqual(summary['cost_ratio'], '100.00')


class CostSummaryDatabaseTests(DashboardFixture, APITestCase):

    def test_saved_draft_purchase_task_scope_and_archived_exclusion(self):
        first = self.task('COST-FIRST')
        second = self.task('COST-SECOND')
        common = dict(currency_code_snapshot='CNY', total_amount=Decimal('12.50'))
        order = PurchaseOrder.objects.create(order_number='CGDD261026001', production_task=first, **common)
        foreign = PurchaseOrder.objects.create(order_number='CGDD261026002', production_task=second, **common)
        supplier = Supplier.objects.create(supplier_number='GYS99997', supplier_name='成本测试供应商',
                                           supplier_type='MATERIAL', supplier_categories=['FABRIC'])
        template = PurchaseContractTemplate.objects.create(template_code='COST_TEST', template_name='成本测试模板')
        version = PurchaseContractTemplateVersion.objects.create(template=template, version_number=1)
        SupplierPurchaseSheet.objects.create(
            purchase_order=order, supplier=supplier, template_version=version,
            sheet_number='CGDD261026003', total_amount=Decimal('12.50'))
        summary = task_cost_summary(task=first)
        self.assertEqual(summary['recorded_cost'], '12.50')
        self.assertEqual(summary['categories'][0]['count'], 1)
        self.assertNotEqual(summary['categories'][0]['items'][0]['source_id'], str(foreign.pk))
        from django.utils import timezone
        PurchaseOrder.objects.filter(production_task=first).update(archived_at=timezone.now())
        self.assertEqual(task_cost_summary(task=first)['recorded_cost'], '0.00')

    def test_empty_real_task_has_no_false_zero_order(self):
        task = self.task('COST-EMPTY')
        summary = task_cost_summary(task=task)
        self.assertEqual(summary['order_amount'], '100.00')
        self.assertEqual(summary['recorded_cost'], '0.00')
        self.assertTrue(summary['complete'])


class CostSummarySourceDatabaseTests(APITestCase):
    setUp = reporting_fixtures.WorkshopReportingApiTests.setUp
    scheme_payload = reporting_fixtures.WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = reporting_fixtures.WorkshopReportingApiTests.create_approved_scheme

    def test_report_reads_current_saved_amount_and_ignores_deleted_history(self):
        from apps.workshop_reporting.models import WorkReport, WorkReportHistory
        scheme = self.create_approved_scheme().data['data']
        report = WorkReport.objects.create(
            report_number='BG-COST-1', production_date=timezone.localdate(), product_line=self.product_line,
            schedule_product=self.schedule_product, workshop=self.workshop, scheme_id=scheme['id'],
            scheme_version_snapshot=1, recorder_employee=self.employee, updated_by_employee=self.employee,
            total_amount=Decimal('8.25'), client_request_id=uuid4(), request_payload_hash='a' * 64)
        self.assertEqual(task_cost_summary(task=self.task)['categories'][1]['amount'], '8.25')
        report.total_amount = Decimal('11.75')
        report.save(update_fields=['total_amount', 'updated_at'])
        summary = task_cost_summary(task=self.task)
        self.assertEqual(summary['categories'][1]['amount'], '11.75')
        WorkReportHistory.objects.create(
            report_id=report.pk, client_request_id=report.client_request_id,
            report_number=report.report_number, request_payload_hash=report.request_payload_hash,
            deleted_at=timezone.now(), deletion_snapshot={'total_amount': '11.75'})
        WorkReport.objects.filter(pk=report.pk).delete()
        summary = task_cost_summary(task=self.task)
        self.assertEqual(summary['categories'][1]['amount'], '0.00')
        self.assertEqual(summary['categories'][1]['count'], 0)

    def test_ordinary_and_tube_outsourcing_include_saved_and_exclude_cancelled(self):
        from apps.outsourcing.models import (OutsourcingFactory, OutsourcingOrder, OutsourcingOrderProduct,
                                              OutsourcingProcessingItem, OutsourcingFactoryAllocation)
        from apps.outsourcing.tube_models import TubeOutsourcingOrder, TubeOutsourcingLine
        factory = OutsourcingFactory.objects.create(
            factory_number='COST-FACTORY', name='成本加工厂', created_by_employee=self.employee,
            updated_by_employee=self.employee)
        ordinary = OutsourcingOrder.objects.create(
            order_number='WF-COST-1', schedule=self.schedule, craft=self.craft,
            delivery_date=timezone.localdate(), source_revision_hash='a' * 64,
            client_request_id=uuid4(), request_payload_hash='b' * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        product = OutsourcingOrderProduct.objects.create(
            order=ordinary, schedule_product=self.schedule_product, bom=self.bom, line_number=1,
            order_quantity_snapshot=100, planned_quantity_snapshot=100, bom_version_snapshot=1)
        processing = OutsourcingProcessingItem.objects.create(
            order_product=product, bom_line=self.metal_bom_line, component_key='cost', line_number=1,
            quantity=Decimal('3'), unit=self.unit)
        OutsourcingFactoryAllocation.objects.create(
            processing_item=processing, factory=factory, allocated_quantity=Decimal('3'), unit_price=Decimal('2.5'))
        tube = TubeOutsourcingOrder.objects.create(
            order_number='WF-COST-2', schedule_product=self.schedule_product, product_line=self.product_line,
            bom=self.bom, craft=self.craft, source_kind='METAL', planned_dispatch_date=timezone.localdate(),
            expected_return_date=timezone.localdate(), client_request_id=uuid4(), request_payload_hash='c' * 64,
            source_revision_hash='d' * 64, created_by_employee=self.employee, updated_by_employee=self.employee)
        TubeOutsourcingLine.objects.create(
            order=tube, bom_line=self.metal_bom_line, component_identity=uuid4(), factory=factory,
            quantity=4, unit_price=Decimal('1.25'))
        summary = task_cost_summary(task=self.task)
        self.assertEqual(summary['categories'][2]['amount'], '12.50')
        self.assertEqual({item['source_type'] for item in summary['categories'][2]['items']},
                         {'OUTSOURCING', 'TUBE_OUTSOURCING'})
        ordinary.status = 'CANCELLED'
        ordinary.save(update_fields=['status'])
        self.assertEqual(task_cost_summary(task=self.task)['categories'][2]['amount'], '5.00')
        tube.status = 'CANCELLED'
        tube.save(update_fields=['status'])
        self.assertEqual(task_cost_summary(task=self.task)['categories'][2]['count'], 0)

    def test_new_request_sheet_task_scope_current_version_and_archive(self):
        from apps.boms.models import Bom
        from apps.procurement.models import PurchaseRequest
        from copy import copy
        other_task = copy(self.task)
        other_task.pk = None
        other_task.task_number = 'HT-COST-OTHER'
        other_task.contract_number = 'COST-OTHER'
        other_task.save(force_insert=True)
        other_product = copy(self.product_line)
        other_product.pk = None
        other_product.production_task = other_task
        other_product.save(force_insert=True)
        other_bom = copy(self.bom)
        other_bom.pk = None
        other_bom.bom_number = 'BOM-COST-OTHER'
        other_bom.production_task = other_task
        other_bom.product_line = other_product
        other_bom.save(force_insert=True)
        request = PurchaseRequest.objects.create(request_number='PR-COST-1', production_task=self.task, bom=self.bom)
        other_request = PurchaseRequest.objects.create(request_number='PR-COST-2', production_task=other_task, bom=other_bom)
        supplier = Supplier.objects.create(supplier_number='GYS99996', supplier_name='成本供应商',
                                           supplier_type='MATERIAL', supplier_categories=['FABRIC'])
        template = PurchaseContractTemplate.objects.create(template_code='COST_SOURCE', template_name='成本模板')
        version = PurchaseContractTemplateVersion.objects.create(template=template, version_number=1)
        common = dict(supplier=supplier, template_version=version)
        current = SupplierPurchaseSheet.objects.create(
            purchase_request=request, sheet_number='CGDD261026101', total_amount=Decimal('18.50'), **common)
        SupplierPurchaseSheet.objects.create(
            purchase_request=request, sheet_number='CGDD261026102', is_current=False,
            total_amount=Decimal('99'), **common)
        SupplierPurchaseSheet.objects.create(
            purchase_request=other_request, sheet_number='CGDD261026103', total_amount=Decimal('70'), **common)
        summary = task_cost_summary(task=self.task)
        self.assertEqual(summary['categories'][0]['amount'], '18.50')
        self.assertEqual(summary['categories'][0]['count'], 1)
        self.assertEqual(summary['categories'][0]['items'][0]['source_id'], str(current.pk))
        current.archived_at = timezone.now()
        current.save(update_fields=['archived_at'])
        self.assertEqual(task_cost_summary(task=self.task)['categories'][0]['amount'], '0.00')
