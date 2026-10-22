import copy
import uuid
from datetime import timedelta
from decimal import Decimal
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.production_scheduling.api.serializers import ScheduleItemReadSerializer
from apps.workshop_reporting.models import WorkReport, WorkReportLine, WorkshopPlanExecution, WorkReportHistory
from apps.workshop_config.models import WorkshopEmployee
from apps.inventory.models import FinishedGoodsReceipt
from apps.inventory.assembly_reporting_limits import assembly_reporting_limit, assembly_reporting_limits
from .test_assembly_receipts import AssemblyFixture


class AssemblyReportingLimitTests(AssemblyFixture, APITestCase):
    def setUp(self):
        self.prepare(quantity=1000, tolerance='2', report_operations=3)
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        self.client.force_authenticate(self.user)
        self.report = WorkReport.objects.get(scheme=self.assembly_scheme)
        self.report_lines = list(self.report.lines.order_by('line_number'))
        self.set_counts(800, 700, 600)

    def set_counts(self, *values):
        for line, value in zip(self.report_lines, values):
            if value == 0:
                WorkReportLine.objects.filter(pk=line.pk).delete()
            else:
                WorkReportLine.objects.filter(pk=line.pk).update(quantity=value)

    def edit_report(self, quantities):
        url = f'/api/v1/workshop-reporting/work-reports/{self.report.pk}/'
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        data = dict(production_date=str(timezone.localdate()), schedule_product_id=str(self.plan.pk),
            scheme_id=str(self.assembly_scheme.pk), scheme_revision=self.assembly_scheme.revision,
            lines=[dict(scheme_line_id=str(row.scheme_line_id), workshop_employee_id=str(row.workshop_employee_id),
                quantity=str(quantity), production_line=1) for row, quantity in zip(self.report_lines, quantities)])
        return self.client.patch(url, data, format='json', HTTP_IF_MATCH=detail['ETag'])

    def test_minimum_and_remaining_quota(self):
        data = self.preview()
        self.assertEqual((data['reported_minimum'], data['order_maximum'], data['maximum_receivable']), (600, 1020, 600))
        self.assertEqual(self.post(self.payload(received_quantity=450)).status_code, 201)
        self.assertEqual(self.preview()['remaining_receivable'], 150)
        self.assertEqual(self.post(self.payload(received_quantity=151)).status_code, 400)
        self.assertEqual(self.post(self.payload(received_quantity=150)).status_code, 201)

    def test_unreported_required_operation_is_zero(self):
        self.set_counts(800, 700, 0)
        self.assertEqual(self.preview()['maximum_receivable'], 0)
        self.assertEqual(self.post(self.payload(received_quantity=1)).status_code, 400)
        self.assertFalse(FinishedGoodsReceipt.objects.exists())

    def test_reports_accumulate_across_workers_days_and_production_lines(self):
        original = self.report_lines[2]
        new_report = copy.copy(self.report)
        new_report.pk = uuid.uuid4(); new_report._state.adding = True
        new_report.report_number += '-2'; new_report.client_request_id = uuid.uuid4()
        new_report.production_date -= timedelta(days=1)
        new_report.save(force_insert=True)
        worker = WorkshopEmployee.objects.create(workshop=self.assembly_scheme.workshop, name='第二位装配员', position='装配', is_supervisor=False)
        row = copy.copy(original); row.pk = uuid.uuid4(); row._state.adding = True
        row.report = new_report; row.quantity = 50; row.workshop_employee = worker; row.production_line = 2
        row.save(force_insert=True)
        self.assertEqual(self.preview()['reported_minimum'], 650)

    def test_order_tolerance_still_limits_receipts(self):
        self.set_counts(1200, 1100, 1050)
        self.assertEqual(self.preview()['maximum_receivable'], 1020)
        self.assertEqual(self.post(self.payload(received_quantity=1020)).status_code, 201)
        self.assertEqual(self.post(self.payload(received_quantity=1)).status_code, 400)

    def test_fractional_report_does_not_allow_partial_finished_unit(self):
        self.set_counts(800, 700, Decimal('600.9999'))
        self.assertEqual(self.preview()['reported_minimum'], 600)

    def test_missing_approved_basis_is_zero(self):
        self.assembly_scheme.status = 'DRAFT'; self.assembly_scheme.save(update_fields=['status'])
        data = self.preview()
        self.assertFalse(data['reporting_basis_ready']); self.assertEqual(data['maximum_receivable'], 0)

    def test_removed_legacy_receipt_entry_cannot_bypass_reporting_limit(self):
        data = dict(production_task_product_id=str(self.line.pk), expected_received_total=0,
            received_quantity=601, quantity_per_box=None, location_id=self.location_id,
            unit_id=str(self.line.unit_id), actual_color='黑色')
        response = self.client.post('/api/v1/finished-goods-inventory/receipts/', data, format='json')
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(FinishedGoodsReceipt.objects.exists())

    def test_preview_revision_changes_with_reported_amount(self):
        etag = self.preview()['etag']; self.set_counts(800, 700, 500)
        self.assertEqual(self.post(self.payload(received_quantity=500), etag).status_code, 412)

    def test_edit_below_received_rolls_back_entire_report(self):
        receipt = self.post(self.payload(received_quantity=600))
        self.assertEqual(receipt.status_code, 201)
        self.assertEqual(self.client.post(
            f"/api/v1/assembly-finished-receipts/{receipt.data['data']['id']}/confirm/", format='json',
        ).status_code, 200)
        before = list(self.report.lines.order_by('id').values('id', 'quantity'))
        response = self.edit_report([800, 700, 500])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('已累计入库', str(response.data))
        self.assertEqual(list(self.report.lines.order_by('id').values('id', 'quantity')), before)
        self.report.refresh_from_db(); self.assertEqual(self.report.revision, 1)

    def test_edit_to_received_boundary_allowed(self):
        receipt = self.post(self.payload(received_quantity=600))
        self.assertEqual(receipt.status_code, 201)
        self.assertEqual(self.client.post(
            f"/api/v1/assembly-finished-receipts/{receipt.data['data']['id']}/confirm/", format='json',
        ).status_code, 200)
        response = self.edit_report([650, 700, 600])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.preview()['reported_minimum'], 600)

    @override_settings(WORK_REPORT_DELETION_ENABLED=True)
    def test_delete_cannot_bypass_reduction_guard(self):
        receipt = self.post(self.payload(received_quantity=600))
        self.assertEqual(receipt.status_code, 201)
        self.assertEqual(self.client.post(
            f"/api/v1/assembly-finished-receipts/{receipt.data['data']['id']}/confirm/", format='json',
        ).status_code, 200)
        url = f'/api/v1/workshop-reporting/work-reports/{self.report.pk}/'
        detail = self.client.get(url)
        response = self.client.delete(url, {'reason': '测试删除不得绕过入库保护'}, format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.report.lines.count(), 3)
        self.assertTrue(WorkReport.objects.filter(pk=self.report.pk).exists())
        self.assertFalse(WorkReportHistory.objects.filter(deleted_at__isnull=False).exists())

    def test_outbound_does_not_restore_receipt_capacity(self):
        self.confirm(self.post(self.payload(received_quantity=600)))
        FinishedGoodsReceipt.objects.update(remaining_quantity=0)
        self.assertEqual(self.preview()['remaining_receivable'], 0)

    def test_receiving_never_completes_work_report_plan(self):
        self.set_counts(1000, 1000, 1000)
        self.assertEqual(self.post(self.payload(received_quantity=1000)).status_code, 201)
        self.assertFalse(WorkshopPlanExecution.objects.filter(schedule_product=self.plan).exists())
        # 即使旧调用方传入收货完成信息，也不得用它覆盖计划状态。
        result = ScheduleItemReadSerializer(self.plan, context={'category':'ASSEMBLY',
            'receipt_progress':{str(self.plan.pk):{'complete':True}}}).data
        self.assertEqual(result['job_status'], 'IN_PROGRESS')

    def test_bulk_limit_is_same_as_single_without_per_product_queries(self):
        with self.assertNumQueries(5):
            result = assembly_reporting_limits([self.line])
        self.assertEqual(result[self.line.pk]['reported_minimum'], 600)
