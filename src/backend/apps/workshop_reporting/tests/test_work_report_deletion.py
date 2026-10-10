import importlib
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.middleware.csrf import _get_new_csrf_string
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Workshop
from ..models import WorkReport, WorkReportHistory, WorkshopPlanExecution, WageScheme
from ..report_history import scheme_was_used
from ..services import _replace_scheme_lines
from .test_workshop_reporting_api import WorkshopReportingApiTests


@override_settings(WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True,
                   MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class WorkReportDeletionTests(APITestCase):
    setUp = WorkshopReportingApiTests.setUp
    scheme_payload = WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = WorkshopReportingApiTests.create_approved_scheme
    base = '/api/v1/workshop-reporting/work-reports/'

    def create_report(self, quantity='3', *, scheme=None, complete=False, product=None):
        scheme = scheme or self.create_approved_scheme().data['data']
        payload = {
            'client_request_id': str(uuid.uuid4()), 'production_date': timezone.localdate().isoformat(),
            'schedule_product_id': str((product or self.schedule_product).pk),
            'scheme_id': scheme['id'], 'scheme_revision': scheme['revision'],
            'confirm_plan_completion': complete,
            'lines': [{'scheme_line_id': scheme['lines'][0]['id'],
                       'workshop_employee_id': str(self.worker.pk), 'quantity': quantity}],
        }
        response = self.client.post(self.base, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data'], payload, scheme

    def remove(self, row, reason='重复录入', **headers):
        return self.client.delete(self.base + row['id'] + '/', {'reason': reason}, format='json',
                                  **({'HTTP_IF_MATCH': row['etag']} | headers))

    def test_delete_keeps_full_snapshot_and_reduces_day_totals(self):
        first, payload, scheme = self.create_report()
        second, _, _ = self.create_report('2', scheme=scheme)
        self.assertEqual(self.remove(first).status_code, 204)
        self.assertFalse(WorkReport.objects.filter(pk=first['id']).exists())
        event = AuditLog.objects.get(object_id=first['id'], action='DELETE')
        self.assertEqual(event.after_data['reason'], '重复录入')
        self.assertEqual(event.before_data['report_number'], first['report_number'])
        self.assertEqual(event.before_data['lines'][0]['quantity'], '3.0000')
        history = WorkReportHistory.objects.get(report_id=first['id'])
        self.assertEqual(str(history.client_request_id), payload['client_request_id'])
        self.assertEqual(history.deletion_snapshot, event.before_data)
        self.assertIsNotNone(history.deleted_at)
        day = self.client.get('/api/v1/workshop-reporting/work-report-days/')
        self.assertEqual(day.data['data'][0]['report_count'], 1)
        self.assertEqual(day.data['data'][0]['total_amount'], second['total_amount'])
        detail = self.client.get('/api/v1/workshop-reporting/work-report-days/' + payload['production_date'] + '/')
        self.assertEqual(len(detail.data['data']), 1)
        self.assertEqual(detail.data['data'][0]['lines'][0]['cumulative_quantity'], '2.0000')

    def test_reason_and_etag_are_required(self):
        row, _, _ = self.create_report()
        for reason in ('', '  \n ', 'x' * 1001):
            self.assertEqual(self.remove(row, reason).status_code, 400)
        self.assertEqual(self.client.delete(self.base + row['id'] + '/', {'reason': '误录'}, format='json').status_code, 428)
        self.assertEqual(self.remove(row, HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertTrue(WorkReport.objects.filter(pk=row['id']).exists())
        self.assertFalse(AuditLog.objects.filter(object_id=row['id'], action='DELETE').exists())

    def test_deleted_creation_key_cannot_replay_or_change_payload(self):
        row, payload, _ = self.create_report()
        self.assertEqual(self.remove(row).status_code, 204)
        self.assertEqual(self.client.post(self.base, payload, format='json').status_code, 409)
        changed = deepcopy(payload); changed['lines'][0]['quantity'] = '4'
        self.assertEqual(self.client.post(self.base, changed, format='json').status_code, 409)
        changed['client_request_id'] = str(uuid.uuid4())
        self.assertEqual(self.client.post(self.base, changed, format='json').status_code, 201)
        self.assertEqual(self.remove(row).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(object_id=row['id'], action='DELETE').count(), 1)

    def test_audit_failure_rolls_back_history_lines_and_plan(self):
        row, _, _ = self.create_report('200', complete=True)
        with patch('apps.workshop_reporting.deletion_services.write_audit_log', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.remove(row)
        report = WorkReport.objects.get(pk=row['id'])
        self.assertEqual(report.lines.count(), 1)
        self.assertIsNone(WorkReportHistory.objects.get(report_id=report.pk).deleted_at)
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'COMPLETED')

    def test_completed_plan_reopens_and_can_report_again(self):
        row, _, scheme = self.create_report('200', complete=True)
        self.assertEqual(self.remove(row).status_code, 204)
        execution = WorkshopPlanExecution.objects.get()
        self.assertEqual(execution.status, 'IN_PROGRESS')
        self.assertIsNone(execution.completed_at)
        self.assertIsNone(execution.completed_by_employee_id)
        self.create_report('200', scheme=scheme, complete=True)

    def test_deleting_earlier_schedule_report_reopens_other_completed_schedule(self):
        row, _, scheme = self.create_report('50')
        ProductionSchedule.objects.filter(pk=self.schedule.pk).update(
            record_status='VOID', voided_at=timezone.now(), voided_by_employee=self.employee, void_reason='替换计划验收')
        self.task.status = 'READY'
        self.task.save(update_fields=['status', 'updated_at'])
        schedule = deepcopy(self.schedule); schedule.pk = None; schedule.record_status = 'ACTIVE'
        schedule.schedule_number = 'PC-DELETE-SECOND'; schedule.client_request_id = uuid.uuid4(); schedule.save()
        product = deepcopy(self.schedule_product); product.pk = None; product.schedule = schedule; product.save()
        ProductionScheduleProductCraft.objects.create(schedule_product=product, craft=self.craft,
            craft_type_snapshot='INTERNAL', plan_category='METAL', craft_name_snapshot=self.craft.name)
        self.task.status = 'IN_PRODUCTION'
        self.task.save(update_fields=['status', 'updated_at'])
        # A scheme bound to a single plan cannot be used in a replacement plan. This fixture represents a product-wide scheme.
        WageScheme.objects.filter(pk=scheme['id']).update(schedule_product=None)
        self.create_report('150', scheme=scheme, complete=True, product=product)
        self.assertEqual(self.remove(row).status_code, 204)
        self.assertEqual(WorkshopPlanExecution.objects.get(schedule_product=product).status, 'IN_PROGRESS')

    def test_historical_completion_uses_its_scheme_not_todays_replacement(self):
        row, _, scheme = self.create_report('50')
        self.create_report('150', scheme=scheme, complete=True)
        original = WageScheme.objects.get(pk=scheme['id'])
        self.metal_bom_line.pieces_per_product = 1
        self.metal_bom_line.save(update_fields=['pieces_per_product'])
        payload = self.scheme_payload()
        payload['lines'][0]['work_item_id'] = scheme['lines'][0]['work_item_id']
        changed = self.client.post(f'/api/v1/workshop-reporting/wage-schemes/{original.pk}/change/',
                                  payload, format='json', HTTP_IF_MATCH=self.client.get(f'/api/v1/workshop-reporting/wage-schemes/{original.pk}/')['ETag'])
        self.assertEqual(changed.status_code, 201, changed.data)
        submitted = self.client.post(f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/submit/",
                                    {}, format='json', HTTP_IF_MATCH=changed['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        approved = self.client.post(f"/api/v1/workshop-reporting/wage-schemes/{changed.data['data']['id']}/approve/",
                                   {}, format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['data']['lines'][0]['required_quantity'], '100.0000')
        self.assertEqual(self.remove(row).status_code, 204)
        self.assertEqual(WorkshopPlanExecution.objects.get().status, 'IN_PROGRESS')

    def test_used_scheme_stays_protected_after_last_report_deleted(self):
        row, _, scheme = self.create_report()
        self.assertEqual(self.remove(row).status_code, 204)
        obj = WageScheme.objects.get(pk=scheme['id'])
        self.assertTrue(scheme_was_used(obj))
        with self.assertRaises(Conflict):
            _replace_scheme_lines(obj, [], [])

    def test_delete_switch_off_keeps_tombstone_protection_when_history_enabled(self):
        row, payload, scheme = self.create_report()
        self.assertEqual(self.remove(row).status_code, 204)
        with override_settings(WORK_REPORT_DELETION_ENABLED=False, WORK_REPORT_HISTORY_ENABLED=True):
            self.assertEqual(self.client.post(self.base, payload, format='json').status_code, 409)
            self.assertTrue(scheme_was_used(WageScheme.objects.get(pk=scheme['id'])))

    def test_unmigrated_mode_never_queries_new_history_model(self):
        with override_settings(WORK_REPORT_DELETION_ENABLED=False, WORK_REPORT_HISTORY_ENABLED=False):
            with patch.object(WorkReportHistory.objects, 'select_for_update', side_effect=AssertionError('new table queried')):
                row, payload, _ = self.create_report()
                self.assertFalse(row['can_delete'])
                self.assertEqual(self.remove(row).status_code, 403)
                self.assertEqual(self.client.post(self.base, payload, format='json').status_code, 201)

    def test_existing_report_backfill_preserves_request_identity(self):
        with override_settings(WORK_REPORT_DELETION_ENABLED=False, WORK_REPORT_HISTORY_ENABLED=False):
            row, payload, _ = self.create_report()
        migration = importlib.import_module('apps.workshop_reporting.migrations.0014_workreport_history')
        migration.backfill_report_history(apps, SimpleNamespace(connection=connection))
        migration.backfill_report_history(apps, SimpleNamespace(connection=connection))
        self.assertEqual(WorkReportHistory.objects.filter(report_id=row['id']).count(), 1)
        self.assertEqual(str(WorkReportHistory.objects.get(report_id=row['id']).client_request_id), payload['client_request_id'])

    def test_session_requires_csrf(self):
        row, _, _ = self.create_report()
        client = APIClient(enforce_csrf_checks=True); client.force_login(self.user)
        url = self.base + row['id'] + '/'
        self.assertEqual(client.delete(url, {'reason': '误录'}, format='json', HTTP_IF_MATCH=row['etag']).status_code, 403)
        csrf = _get_new_csrf_string(); client.cookies['csrftoken'] = csrf
        self.assertEqual(client.delete(url, {'reason': '误录'}, format='json', HTTP_IF_MATCH=row['etag'], HTTP_X_CSRFTOKEN=csrf).status_code, 204)

    def scoped_actor(self, delete_workshop=None):
        user = get_user_model().objects.create_user(username='delete-scoped')
        employee = Employee.objects.create(user=user, employee_code='DELETE-SCOPED', display_name='范围删除验收')
        group = Group.objects.create(name='DELETE-SCOPED')
        role = RoleProfile.objects.create(role_code='DELETE_SCOPED', display_name='范围删除验收', auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        for code, scope in [('view_workreport', 'MODULE')] + ([('delete_workreport', 'WORKSHOP')] if delete_workshop else []):
            permission = Permission.objects.get(content_type__app_label='workshop_reporting', codename=code)
            group.permissions.add(permission)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
            if scope == 'WORKSHOP': RoleGrantResource.objects.create(grant=grant, workshop=delete_workshop)
        self.client.force_authenticate(user)

    def test_view_module_never_widens_delete_scope(self):
        row, _, _ = self.create_report()
        self.scoped_actor(Workshop.objects.get_or_create(name='装配车间')[0])
        with override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            detail = self.client.get(self.base + row['id'] + '/')
            self.assertEqual(detail.status_code, 200)
            self.assertFalse(detail.data['data']['can_delete'])
            self.assertEqual(self.remove(row).status_code, 404)

    def test_readonly_cannot_call_delete_directly(self):
        row, _, _ = self.create_report(); self.scoped_actor()
        with override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            self.assertEqual(self.remove(row).status_code, 403)

    def test_matching_workshop_grant_can_delete(self):
        row, _, _ = self.create_report(); self.scoped_actor(self.workshop)
        with override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            self.assertTrue(self.client.get(self.base + row['id'] + '/').data['data']['can_delete'])
            self.assertEqual(self.remove(row).status_code, 204)
