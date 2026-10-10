"""管材保护的报工／工价事务接入，以及逐计划重开行为。"""
import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.inventory.tube_processing_services import metal_component_limits
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, MetalProcessingSource, OrderMaterialRequirement
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Operation
from apps.workshop_reporting.models import (
    WageScheme, WageSchemeEvent, WorkReport, WorkReportHistory, WorkReportLine,
    WorkshopPlanExecution,
)
from apps.workshop_reporting.tube_plan_services import (
    is_tube_scheme, reopen_tube_plans_for_scheme, tube_plan_is_complete,
)

from . import test_work_report_deletion as deletion_fixture
from . import test_workshop_reporting_api as reporting_fixture


@override_settings(
    WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True,
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False,
)
class TubeReportingGuardTests(APITestCase):
    scheme_payload = reporting_fixture.WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = reporting_fixture.WorkshopReportingApiTests.create_approved_scheme
    create_report = deletion_fixture.WorkReportDeletionTests.create_report
    remove = deletion_fixture.WorkReportDeletionTests.remove
    base = deletion_fixture.WorkReportDeletionTests.base

    def setUp(self):
        reporting_fixture.WorkshopReportingApiTests.setUp(self)
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name='支', defaults={'unit_code': 'TUBE-GUARD-PCS'},
        )
        self.operation.reporting_unit = self.piece_unit
        self.operation.save(update_fields=['reporting_unit'])

    def create_recorded_usage(self, *, dispatched=70, reserved=10):
        """旧来源未办理接续豁免，其实际交接及预留仍需真实报工支持。"""
        category = ProductCategory.objects.create(category_name='管材保护原料', item_type='MATERIAL')
        material = RawMaterialInformation.objects.create(
            material_number='TUBE-GUARD-RAW', item_type='MATERIAL', category=category,
            material_name='铁管', material='铁', specification='20*1.0*500', unit=self.piece_unit,
            warehouse_number='TUBE-GUARD-WH', warehouse_name='测试原料仓',
        )
        requirement = OrderMaterialRequirement.objects.create(
            measurement_kind='PIPE', product_line=self.product_line,
            component_identity=self.metal_bom_line.component_identity, pieces_per_bar=10,
            raw_bar_length_m=Decimal('6.00'), production_task=self.task, raw_material=material,
            unit=self.piece_unit, line_type='RAW', section_code='PROFILE',
            required_quantity=200, internal_issued_quantity=200, source_revision_hash='a' * 64,
        )
        issue = MaterialIssue.objects.create(
            stock_mode='LEGACY', issue_number='TUBE-GUARD-ISSUE', client_request_id=uuid.uuid4(),
            request_payload_hash='b' * 64, production_task=self.task, product_line=self.product_line,
            workshop=self.workshop, status='ISSUED', created_by_employee=self.employee,
            updated_by_employee=self.employee, issued_by_employee=self.employee, issued_at=timezone.now(),
        )
        line = MaterialIssueLine.objects.create(
            issue=issue, line_number=1, requirement=requirement, line_type='RAW', raw_material=material,
            unit=self.piece_unit, section_code_snapshot='PROFILE', material_number_snapshot=material.material_number,
            material_name_snapshot=material.material_name, unit_snapshot='支', requested_quantity=200,
            issued_quantity=200,
        )
        return MetalProcessingSource.objects.create(
            issue_line=line, source_snapshot={}, source_hash='c' * 64, issued_pieces=200,
            completed_pieces=200, dispatched_pieces=dispatched, reserved_pieces=reserved,
        )

    def component_limit(self):
        return metal_component_limits(self.product_line)['components'][str(self.metal_bom_line.component_identity)]

    def test_real_usage_edit_accepts_exact_sum_and_rejects_one_piece_less(self):
        row, payload, _ = self.create_report('100')
        self.create_recorded_usage(dispatched=70, reserved=10)
        self.assertTrue(self.component_limit()['basis_ready'], self.component_limit())
        data = deepcopy(payload)
        data.pop('client_request_id')
        data['lines'][0]['quantity'] = '80'
        accepted = self.client.patch(self.base + row['id'] + '/', data, format='json', HTTP_IF_MATCH=row['etag'])
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(self.component_limit()['allowance']['reported_minimum'], 80)
        data['lines'][0]['quantity'] = '79'
        rejected = self.client.patch(
            self.base + row['id'] + '/', data, format='json', HTTP_IF_MATCH=accepted['ETag'],
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn('80支', str(rejected.data))
        self.assertEqual(WorkReportLine.objects.get(report_id=row['id']).quantity, Decimal('80'))

    def test_real_usage_delete_allows_remaining_coverage_and_rejects_last_support(self):
        first, _, scheme = self.create_report('100')
        second, _, _ = self.create_report('80', scheme=scheme)
        self.create_recorded_usage(dispatched=70, reserved=10)
        accepted = self.remove(first)
        self.assertEqual(accepted.status_code, 204, getattr(accepted, 'data', None))
        self.assertFalse(WorkReport.objects.filter(pk=first['id']).exists())
        rejected = self.remove(second)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn('80支', str(rejected.data))
        self.assertTrue(WorkReport.objects.filter(pk=second['id']).exists())
        self.assertIsNone(WorkReportHistory.objects.get(report_id=second['id']).deleted_at)

    def test_real_usage_rejects_new_operation_current_and_future_approval(self):
        _, _, scheme = self.create_report('100')
        self.create_recorded_usage()
        submitted = self.change_scheme(scheme, add_operation=True)
        original = WageScheme.objects.get(pk=scheme['id'])
        before = (original.status, original.effective_to, original.revision)
        event_count = WageSchemeEvent.objects.count()
        for days in (0, 3):
            with self.subTest(effective_days=days):
                rejected = self.approve(submitted, timezone.localdate() + timedelta(days=days))
                self.assertEqual(rejected.status_code, 400, rejected.data)
                self.assertIn('80支', str(rejected.data))
                original.refresh_from_db()
                self.assertEqual((original.status, original.effective_to, original.revision), before)
                self.assertEqual(WageSchemeEvent.objects.count(), event_count)
                self.assertEqual(WageScheme.objects.get(pk=submitted.data['data']['id']).status, 'PENDING_APPROVAL')

    def test_real_usage_price_only_approval_reuses_report_quantity_and_keeps_wages(self):
        row, _, scheme = self.create_report('100')
        self.create_recorded_usage()
        before = list(WorkReportLine.objects.filter(report_id=row['id']).values(
            'id', 'work_item_id', 'quantity', 'unit_price_snapshot', 'amount', 'scheme_line_id',
        ))
        approved = self.approve(self.change_scheme(scheme), timezone.localdate() + timedelta(days=3))
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['data']['lines'][0]['work_item_id'], scheme['lines'][0]['work_item_id'])
        self.assertEqual(list(WorkReportLine.objects.filter(report_id=row['id']).values(
            'id', 'work_item_id', 'quantity', 'unit_price_snapshot', 'amount', 'scheme_line_id',
        )), before)
        self.assertEqual(self.component_limit()['allowance']['reported_minimum'], 100)

    def change_scheme(self, scheme, *, add_operation=False, price='3.0000'):
        payload = self.scheme_payload()
        payload['lines'][0]['work_item_id'] = scheme['lines'][0]['work_item_id']
        payload['lines'][0]['declared_price'] = price
        if add_operation:
            operation = Operation.objects.create(
                operation_number='TUBE-GUARD-SECOND', product_name='工价测试产品',
                craft=self.craft, name='新增冲孔', reporting_unit=self.piece_unit,
            )
            extra = deepcopy(payload['lines'][0])
            extra.pop('work_item_id')
            extra['operation_id'] = str(operation.pk)
            payload['lines'].append(extra)
        url = f"/api/v1/workshop-reporting/wage-schemes/{scheme['id']}/"
        changed = self.client.post(
            url + 'change/', payload, format='json', HTTP_IF_MATCH=self.client.get(url)['ETag'],
        )
        self.assertEqual(changed.status_code, 201, changed.data)
        submitted = self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/submit/",
            {}, format='json', HTTP_IF_MATCH=changed['ETag'],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        return submitted

    def approve(self, submitted, effective_from=None):
        return self.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{submitted.data['data']['id']}/approve/",
            {'effective_from': str(effective_from or timezone.localdate())}, format='json',
            HTTP_IF_MATCH=submitted['ETag'],
        )

    def test_edit_usage_rejection_rolls_back_report_lines_amount_and_history(self):
        row, payload, _ = self.create_report('100')
        report = WorkReport.objects.get(pk=row['id'])
        before = list(report.lines.values('id', 'quantity', 'unit_price_snapshot', 'amount'))
        original_total, original_revision = report.total_amount, report.revision
        data = deepcopy(payload)
        data.pop('client_request_id')
        data['lines'][0]['quantity'] = '50'
        with patch(
            'apps.inventory.tube_processing_services.assert_tube_reports_cover_usage',
            side_effect=ValidationError({'lines': '报工不足以覆盖已入库和已交接数量。'}),
        ) as guard:
            response = self.client.patch(self.base + row['id'] + '/', data, format='json', HTTP_IF_MATCH=row['etag'])
        self.assertEqual(response.status_code, 400, response.data)
        guard.assert_called_once_with(self.product_line.pk)
        report.refresh_from_db()
        self.assertEqual((report.total_amount, report.revision), (original_total, original_revision))
        self.assertEqual(list(report.lines.values('id', 'quantity', 'unit_price_snapshot', 'amount')), before)
        self.assertIsNone(WorkReportHistory.objects.get(report_id=report.pk).deleted_at)

    def test_delete_usage_rejection_keeps_report_and_does_not_write_deletion_audit(self):
        row, _, _ = self.create_report('100')
        with patch(
            'apps.inventory.tube_processing_services.assert_tube_reports_cover_usage',
            side_effect=ValidationError({'lines': '已有有效外发预留，不能减少完成依据。'}),
        ) as guard:
            response = self.remove(row)
        self.assertEqual(response.status_code, 400, response.data)
        guard.assert_called_once_with(self.product_line.pk)
        self.assertEqual(WorkReportLine.objects.get(report_id=row['id']).quantity, Decimal('100'))
        self.assertIsNone(WorkReportHistory.objects.get(report_id=row['id']).deleted_at)
        self.assertFalse(AuditLog.objects.filter(object_id=row['id'], action='DELETE').exists())

    def test_approval_usage_rejection_rolls_back_old_version_dates_and_approval_event(self):
        _, _, scheme = self.create_report('100')
        submitted = self.change_scheme(scheme, add_operation=True)
        original = WageScheme.objects.get(pk=scheme['id'])
        before = (original.status, original.effective_to, original.revision)
        event_count = WageSchemeEvent.objects.count()
        with patch(
            'apps.inventory.tube_processing_services.assert_tube_reports_cover_usage',
            side_effect=ValidationError({'lines': '新增工序尚未报工，不能覆盖已有产出。'}),
        ) as guard:
            response = self.approve(submitted, timezone.localdate() + timedelta(days=1))
        self.assertEqual(response.status_code, 400, response.data)
        guard.assert_called_once_with(self.product_line.pk)
        original.refresh_from_db()
        self.assertEqual((original.status, original.effective_to, original.revision), before)
        self.assertEqual(WageScheme.objects.get(pk=submitted.data['data']['id']).status, 'PENDING_APPROVAL')
        self.assertEqual(WageSchemeEvent.objects.count(), event_count)

    def test_price_only_version_keeps_work_item_historical_wages_and_completed_plan(self):
        row, _, scheme = self.create_report('200', complete=True)
        historical = list(WorkReportLine.objects.filter(report_id=row['id']).values(
            'work_item_id', 'quantity', 'unit_price_snapshot', 'amount', 'scheme_line_id',
        ))
        approved = self.approve(self.change_scheme(scheme))
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['data']['lines'][0]['work_item_id'], scheme['lines'][0]['work_item_id'])
        self.assertEqual(list(WorkReportLine.objects.filter(report_id=row['id']).values(
            'work_item_id', 'quantity', 'unit_price_snapshot', 'amount', 'scheme_line_id',
        )), historical)
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'COMPLETED')

    def test_new_required_operation_reopens_plan_and_starts_at_zero(self):
        _, _, scheme = self.create_report('200', complete=True)
        approved = self.approve(self.change_scheme(scheme, add_operation=True))
        self.assertEqual(approved.status_code, 200, approved.data)
        execution = WorkshopPlanExecution.objects.get()
        self.assertEqual(execution.status, 'IN_PROGRESS')
        self.assertIsNone(execution.completed_at)
        self.assertIsNone(execution.completed_by_employee_id)
        changed = approved.data['data']
        added = next(line for line in changed['lines'] if line['work_item_id'] != scheme['lines'][0]['work_item_id'])
        self.assertFalse(WorkReportLine.objects.filter(work_item_id=added['work_item_id']).exists())
        self.assertFalse(tube_plan_is_complete(self.schedule_product.pk, WageScheme.objects.get(pk=changed['id'])))
        response = self.client.post(self.base, {
            'client_request_id': str(uuid.uuid4()),
            'production_date': str(timezone.localdate()), 'schedule_product_id': str(self.schedule_product.pk),
            'scheme_id': changed['id'], 'scheme_revision': changed['revision'], 'confirm_plan_completion': True,
            'lines': [{'scheme_line_id': added['id'], 'workshop_employee_id': str(self.worker.pk), 'quantity': '200'}],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'COMPLETED')

    def test_replacement_plan_uses_own_reports_and_reopens_despite_original_scheme_binding(self):
        _, _, scheme = self.create_report('200', complete=True)
        future = timezone.localdate() + timedelta(days=3)
        approved = self.approve(self.change_scheme(scheme, add_operation=True), future)
        self.assertEqual(approved.status_code, 200, approved.data)
        changed = approved.data['data']
        scheme = self.client.get(f"/api/v1/workshop-reporting/wage-schemes/{scheme['id']}/").data['data']
        self.schedule.record_status = 'VOID'
        self.schedule.void_reason = '测试重新排产'
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        self.task.status = 'READY'
        self.task.save(update_fields=['status', 'updated_at'])
        replacement = ProductionSchedule.objects.create(
            schedule_number='TUBE-GUARD-REPLAN', production_task=self.task, record_status='ACTIVE',
            source_revision_hash='d' * 64, client_request_id=uuid.uuid4(), request_payload_hash='e' * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        replacement_product = ProductionScheduleProduct.objects.create(
            schedule=replacement, product_line=self.product_line, line_number=1, planned_quantity=100,
            source_quantity_snapshot=100, unit=self.unit, unit_name_snapshot=self.unit.unit_name,
            material_inbound_date=self.schedule_product.material_inbound_date,
            metal_return_date=self.schedule_product.metal_return_date,
            sewing_return_date=self.schedule_product.sewing_return_date,
            finished_inbound_date=self.schedule_product.finished_inbound_date,
            source_revision_hash='f' * 64,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=replacement_product, craft=self.craft, craft_type_snapshot='INTERNAL',
            craft_name_snapshot=self.craft.name, plan_category='METAL',
        )
        self.task.status = 'IN_PRODUCTION'
        self.task.save(update_fields=['status', 'updated_at'])
        statuses = self.client.get('/api/v1/workshop-reporting/plan-wage-statuses/', {
            'schedule_product_ids': str(replacement_product.pk), 'plan_category': 'METAL',
            'production_date': str(timezone.localdate()),
        })
        self.assertEqual(statuses.status_code, 200, statuses.data)
        self.assertEqual(statuses.data['data'][0]['progress_percent'], 0)
        self.create_report('200', scheme=scheme, complete=True, product=replacement_product)
        # 新版仍绑定旧排产，但价格实际适用于替代计划；GET与保存保持同一范围。
        with patch('apps.workshop_reporting.tube_plan_services.timezone.localdate', return_value=future):
            statuses = self.client.get('/api/v1/workshop-reporting/plan-wage-statuses/', {
                'schedule_product_ids': str(replacement_product.pk), 'plan_category': 'METAL',
                'production_date': str(future),
            })
            self.assertEqual(statuses.status_code, 200, statuses.data)
            self.assertEqual(statuses.data['data'][0]['progress_percent'], 50)
            self.assertTrue(statuses.data['data'][0]['can_report'])
            self.assertEqual(WorkshopPlanExecution.objects.get(schedule_product=replacement_product).status, 'COMPLETED')
            self.assertEqual(len(reopen_tube_plans_for_scheme(WageScheme.objects.get(pk=changed['id']))), 1)
        self.assertEqual(WorkshopPlanExecution.objects.get(schedule_product=replacement_product).status, 'IN_PROGRESS')
        self.assertEqual(WorkshopPlanExecution.objects.get(schedule_product__schedule=self.schedule).status, 'COMPLETED')
        self.assertFalse(tube_plan_is_complete(replacement_product.pk, WageScheme.objects.get(pk=changed['id'])))

    def test_future_version_waits_for_effective_date_and_read_gate_does_not_write(self):
        _, _, scheme = self.create_report('200', complete=True)
        future = timezone.localdate() + timedelta(days=1)
        approved = self.approve(self.change_scheme(scheme, add_operation=True), future)
        self.assertEqual(approved.status_code, 200, approved.data)
        changed = WageScheme.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(reopen_tube_plans_for_scheme(changed, self.employee), [])
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'COMPLETED')
        with patch('apps.workshop_reporting.tube_plan_services.timezone.localdate', return_value=future):
            response = self.client.get('/api/v1/workshop-reporting/plan-wage-statuses/', {
                'schedule_product_ids': str(self.schedule_product.pk), 'production_date': str(future),
                'plan_category': 'METAL',
            })
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data['data'][0]['can_report'], response.data)
            self.assertEqual(response.data['data'][0]['plan_status'], 'IN_PROGRESS')
            self.assertEqual(WorkshopPlanExecution.objects.get().status, 'COMPLETED')
            changes = reopen_tube_plans_for_scheme(changed, self.employee)
        self.assertEqual(len(changes), 1)
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'IN_PROGRESS')

    def test_stable_craft_identity_keeps_guard_after_name_changes(self):
        row, _, scheme = self.create_report('100')
        self.create_recorded_usage()
        self.craft.name = '已更名工艺'
        self.craft.save(update_fields=['name'])
        self.assertTrue(is_tube_scheme(WageScheme.objects.get(pk=scheme['id'])))
        self.assertTrue(self.component_limit()['basis_ready'], self.component_limit())
        response = self.remove(row)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('80支', str(response.data))
        self.assertTrue(WorkReport.objects.filter(pk=row['id']).exists())
