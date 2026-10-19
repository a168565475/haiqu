import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import (
    ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus,
)
from apps.production_tasks.models import ProductionTaskStatus
from apps.workshop_config.models import CraftType, Operation, PlanCategory, Workshop

from ..models import WageScheme, WageSchemeLine, WorkReportHistory
from ..api.serializers import wage_scheme_data
from . import test_workshop_reporting_api as base_api_tests


@override_settings(
    WORK_REPORT_DELETION_ENABLED=True, WORK_REPORT_HISTORY_ENABLED=True,
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False,
)
class WageSchemeLineMetricsTests(APITestCase):
    setUp = base_api_tests.WorkshopReportingApiTests.setUp
    scheme_payload = base_api_tests.WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = base_api_tests.WorkshopReportingApiTests.create_approved_scheme
    scheme_base = '/api/v1/workshop-reporting/wage-schemes/'
    report_base = '/api/v1/workshop-reporting/work-reports/'

    def detail(self, scheme_id, client=None):
        response = (client or self.client).get(f'{self.scheme_base}{scheme_id}/')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def create_report(self, scheme, quantity='1', production_date=None, product=None):
        payload = {
            'client_request_id': str(uuid.uuid4()),
            'production_date': (production_date or timezone.localdate()).isoformat(),
            'schedule_product_id': str((product or self.schedule_product).pk),
            'scheme_id': scheme['id'], 'scheme_revision': scheme['revision'],
            'lines': [{
                'scheme_line_id': scheme['lines'][0]['id'],
                'workshop_employee_id': str(self.worker.pk), 'quantity': quantity,
            }],
        }
        response = self.client.post(self.report_base, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data'], payload

    def approve_created(self, created, effective_from=None):
        self.assertEqual(created.status_code, 201, created.data)
        url = f"{self.scheme_base}{created.data['data']['id']}/"
        submitted = self.client.post(
            f'{url}submit/', {}, format='json', HTTP_IF_MATCH=created['ETag'],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        approved = self.client.post(
            f'{url}approve/',
            {'effective_from': (effective_from or timezone.localdate()).isoformat()},
            format='json', HTTP_IF_MATCH=submitted['ETag'],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        return approved

    def viewer_client(self, username, codenames):
        user = get_user_model().objects.create_user(username=username)
        Employee.objects.create(user=user, employee_code=username.upper(), display_name='统计查看员')
        user.user_permissions.set(Permission.objects.filter(
            content_type__app_label='workshop_reporting', codename__in=codenames,
        ))
        client = APIClient()
        client.force_authenticate(user)
        return client

    def assert_completed(self, line, quantity, amount):
        self.assertEqual(Decimal(line['completed_quantity']), Decimal(quantity))
        self.assertEqual(Decimal(line['completed_amount']), Decimal(amount))

    def test_empty_reports_are_real_zero_and_estimate_uses_required_quantity(self):
        approved = self.create_approved_scheme()

        line = self.detail(approved.data['data']['id'])['lines'][0]

        self.assert_completed(line, '0', '0')
        self.assertEqual(line['estimated_amount'], '469.0000')
        self.assertEqual(self.detail(approved.data['data']['id'])['declared_total'], '2.3450')

    def test_completed_amount_sums_rounded_snapshots_across_price_versions(self):
        approved = self.create_approved_scheme()
        original = approved.data['data']
        self.create_report(original)
        self.create_report(original)
        tomorrow = timezone.localdate() + timedelta(days=1)
        payload = self.scheme_payload()
        payload['lines'][0]['work_item_id'] = original['lines'][0]['work_item_id']
        payload['lines'][0]['declared_price'] = '3.1000'
        created = self.client.post(
            f"{self.scheme_base}{original['id']}/change/", payload,
            format='json', HTTP_IF_MATCH=approved['ETag'],
        )
        changed = self.approve_created(created, tomorrow).data['data']
        self.assertEqual(changed['lines'][0]['work_item_id'], original['lines'][0]['work_item_id'])
        self.create_report(changed, '2', production_date=tomorrow)

        for scheme_id in (original['id'], changed['id']):
            with self.subTest(scheme_id=scheme_id):
                line = self.detail(scheme_id)['lines'][0]
                self.assert_completed(line, '4', '10.90')
        self.assertEqual(self.detail(changed['id'])['lines'][0]['estimated_amount'], '620.0000')

    def test_edit_and_delete_recompute_metrics_without_counting_history(self):
        scheme = self.create_approved_scheme().data['data']
        report, payload = self.create_report(scheme, '3')
        self.assert_completed(self.detail(scheme['id'])['lines'][0], '3', '7.04')
        detail = self.client.get(f"{self.report_base}{report['id']}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        edit_payload = deepcopy(payload)
        edit_payload.pop('client_request_id')
        edit_payload['lines'][0]['quantity'] = '4'
        edited = self.client.patch(
            f"{self.report_base}{report['id']}/", edit_payload,
            format='json', HTTP_IF_MATCH=detail['ETag'],
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assert_completed(self.detail(scheme['id'])['lines'][0], '4', '9.38')

        deleted = self.client.delete(
            f"{self.report_base}{report['id']}/", {'reason': '统计回归测试撤销误录'},
            format='json', HTTP_IF_MATCH=edited['ETag'],
        )

        self.assertEqual(deleted.status_code, 204, getattr(deleted, 'data', None))
        self.assertIsNotNone(WorkReportHistory.objects.get(report_id=report['id']).deleted_at)
        self.assert_completed(self.detail(scheme['id'])['lines'][0], '0', '0')

    def test_other_schedule_is_excluded_but_legacy_unbound_scheme_uses_product_scope(self):
        scheme = self.create_approved_scheme().data['data']
        self.create_report(scheme, '5')
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.version += 1
        self.schedule.void_reason = '统计测试重新排产'
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        self.task.status = ProductionTaskStatus.READY
        self.task.save(update_fields=['status', 'updated_at'])
        today = timezone.localdate()
        second_schedule = ProductionSchedule.objects.create(
            schedule_number='PC-METRICS-002', production_task=self.task, record_status=ScheduleStatus.ACTIVE,
            version=1, source_snapshot={'task_number': self.task.task_number}, source_revision_hash='d' * 64,
            client_request_id=uuid.uuid4(), request_payload_hash='e' * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        second_product = ProductionScheduleProduct.objects.create(
            schedule=second_schedule, product_line=self.product_line, line_number=1, planned_quantity=100,
            source_quantity_snapshot=100, unit=self.unit, unit_name_snapshot=self.unit.unit_name,
            material_inbound_date=today, metal_return_date=today + timedelta(days=1),
            sewing_return_date=today + timedelta(days=2), finished_inbound_date=today + timedelta(days=3),
            product_snapshot={'product_name': self.product_line.product_name_snapshot}, source_revision_hash='f' * 64,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=second_product, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
        )
        self.create_report(scheme, '7', product=second_product)

        self.assert_completed(self.detail(scheme['id'])['lines'][0], '5', '11.73')
        WageScheme.objects.filter(pk=scheme['id']).update(schedule_product=None)
        self.assert_completed(self.detail(scheme['id'])['lines'][0], '12', '28.15')

    def test_missing_required_quantity_and_void_line_have_no_estimate(self):
        scheme = self.create_approved_scheme().data['data']
        self.create_report(scheme)
        for changes in (
            {'required_quantity_snapshot': None},
            {'required_quantity_snapshot': Decimal('200'), 'status': 'VOID'},
        ):
            with self.subTest(changes=changes):
                WageSchemeLine.objects.filter(pk=scheme['lines'][0]['id']).update(**changes)
                line = self.detail(scheme['id'])['lines'][0]
                self.assertIsNone(line['estimated_amount'])
                self.assert_completed(line, '1', '2.35')

    def test_report_permission_and_report_workshop_scope_are_required_for_metrics(self):
        scheme = self.create_approved_scheme().data['data']
        self.create_report(scheme)
        base_permissions = ['view_wagescheme', 'view_all_wagescheme']
        for username, additional in (
            ('metrics-no-report', []),
            ('metrics-report-outside', ['view_workreport']),
        ):
            with self.subTest(username=username):
                client = self.viewer_client(username, base_permissions + additional)
                line = self.detail(scheme['id'], client)['lines'][0]
                self.assertIsNone(line['completed_quantity'])
                self.assertIsNone(line['completed_amount'])
                self.assertEqual(line['estimated_amount'], '469.0000')
        allowed = self.viewer_client(
            'metrics-report-all', base_permissions + ['view_workreport', 'view_all_workreport'],
        )
        self.assert_completed(self.detail(scheme['id'], allowed)['lines'][0], '1', '2.35')

    def test_wage_scheme_outside_view_scope_returns_404(self):
        scheme = self.create_approved_scheme().data['data']
        client = self.viewer_client('metrics-wage-outside', [
            'view_wagescheme', 'view_workreport', 'view_all_workreport',
        ])

        response = client.get(f"{self.scheme_base}{scheme['id']}/")

        self.assertEqual(response.status_code, 404, response.data)

    def test_scoped_report_grant_does_not_borrow_current_wage_action_scope(self):
        scheme = self.create_approved_scheme().data['data']
        self.create_report(scheme)
        user = get_user_model().objects.create_user(username='metrics-resource-viewer')
        employee = Employee.objects.create(
            user=user, employee_code='METRICS-RESOURCE-VIEWER', display_name='统计范围查看员',
        )
        group = Group.objects.create(name='METRICS_RESOURCE_VIEWER')
        role = RoleProfile.objects.create(
            role_code='METRICS_RESOURCE_VIEWER', display_name='统计范围查看员', auth_group=group,
        )
        EmployeeRoleAssignment.objects.create(
            employee=employee, role_profile=role, effective_from=timezone.now(),
        )
        other_workshop = Workshop.objects.get_or_create(name='装配车间')[0]
        for codename, workshop in (
            ('view_wagescheme', self.workshop), ('view_workreport', other_workshop),
        ):
            permission = Permission.objects.get(
                content_type__app_label='workshop_reporting', codename=codename,
            )
            group.permissions.add(permission)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='WORKSHOP')
            RoleGrantResource.objects.create(grant=grant, workshop=workshop)
        client = APIClient()
        client.force_authenticate(user)

        with override_settings(
            MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
        ):
            line = self.detail(scheme['id'], client)['lines'][0]
            self.assertIsNone(line['completed_quantity'])
            self.assertIsNone(line['completed_amount'])
            self.assertEqual(line['estimated_amount'], '469.0000')

            RoleGrantResource.objects.filter(
                grant__role=role, grant__permission__codename='view_workreport',
            ).update(workshop=self.workshop)
            self.assert_completed(self.detail(scheme['id'], client)['lines'][0], '1', '2.35')

    def test_multiple_lines_use_one_report_aggregate_query(self):
        payload = self.scheme_payload()
        operation = Operation.objects.create(
            operation_number='WG-METRICS-002', product_name='工价测试产品', craft=self.craft,
            name='弯管', reporting_unit=self.unit,
        )
        second_line = deepcopy(payload['lines'][0])
        second_line['operation_id'] = str(operation.pk)
        payload['lines'].append(second_line)
        created = self.client.post(self.scheme_base, payload, format='json')
        scheme = self.approve_created(created).data['data']

        with CaptureQueriesContext(connection) as captured:
            detail = self.detail(scheme['id'])

        self.assertEqual(len(detail['lines']), 2)
        aggregates = [
            query['sql'] for query in captured.captured_queries
            if 'workshop_work_report_line' in query['sql'] and 'SUM(' in query['sql'].upper()
        ]
        self.assertEqual(len(aggregates), 1, aggregates)
        self.assertIn('GROUP BY', aggregates[0].upper())
        for line in detail['lines']:
            self.assert_completed(line, '0', '0')


class WageSchemeEstimatedAmountPrecisionTests(SimpleTestCase):
    def test_estimated_amount_supports_maximum_stored_decimal_values(self):
        line = MagicMock(
            status='ACTIVE', required_quantity_snapshot=Decimal('99999999999999999999.9999'),
            declared_price=Decimal('99999999999999.9999'), previous_price=None, revised_price=None,
            bom_component_identity_snapshot=None,
        )
        scheme = MagicMock(status='DRAFT', parent_scheme_id=None, approved_by_employee_id=None)
        scheme.lines.all.return_value = [line]
        scheme.events.all.return_value = []
        scheme.scheme_crafts.all.return_value = []

        result = wage_scheme_data(scheme)

        self.assertEqual(
            result['lines'][0]['estimated_amount'],
            '9999999999999999989999990000000000.0000',
        )
