import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import (
    ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus,
)
from apps.production_tasks.models import ProductionTaskProduct, ProductionTaskStatus
from apps.workshop_config.models import Craft, CraftType, PlanCategory, RecordStatus, Workshop

from ..models import WorkReport
from . import test_workshop_reporting_api as base_api_tests


@override_settings(
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False,
)
class WorkReportTaskSelectionTests(APITestCase):
    setUp = base_api_tests.WorkshopReportingApiTests.setUp
    scheme_payload = base_api_tests.WorkshopReportingApiTests.scheme_payload
    create_approved_scheme = base_api_tests.WorkshopReportingApiTests.create_approved_scheme
    task_url = '/api/v1/workshop-reporting/work-report-tasks/'
    day_url = '/api/v1/workshop-reporting/work-report-days/'
    report_url = '/api/v1/workshop-reporting/work-reports/'

    def copy_values(self, source, **overrides):
        values = {
            field.attname: getattr(source, field.attname)
            for field in source._meta.concrete_fields
            if not field.primary_key and field.name not in {'created_at', 'updated_at'}
        }
        values.update(overrides)
        return values

    def copy_row(self, source, **overrides):
        return type(source).objects.create(**self.copy_values(source, **overrides))

    def add_product(self, task, schedule, line_number):
        product = self.copy_row(self.product_line, production_task_id=task.pk, line_number=line_number)
        scheduled = self.copy_row(
            self.schedule_product, schedule_id=schedule.pk, product_line_id=product.pk, line_number=line_number,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=scheduled, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
        )
        return product, scheduled

    def add_task(self):
        task = self.copy_row(
            self.task, task_number='HT-SELECT-002', contract_number='SELECT-CONTRACT-002',
            order_number='SELECT-ORDER-002', status=ProductionTaskStatus.READY,
        )
        schedule = self.copy_row(
            self.schedule, production_task_id=task.pk, schedule_number='PC-SELECT-002',
            client_request_id=uuid.uuid4(),
        )
        product, scheduled = self.add_product(task, schedule, 1)
        return task, schedule, product, scheduled

    def create_report(self):
        scheme = self.create_approved_scheme().data['data']
        response = self.client.post('/api/v1/workshop-reporting/work-reports/', {
            'client_request_id': str(uuid.uuid4()), 'production_date': timezone.localdate().isoformat(),
            'schedule_product_id': str(self.schedule_product.pk),
            'scheme_id': scheme['id'], 'scheme_revision': scheme['revision'],
            'lines': [{
                'scheme_line_id': scheme['lines'][0]['id'],
                'workshop_employee_id': str(self.worker.pk), 'quantity': '2',
            }],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return WorkReport.objects.get(pk=response.data['data']['id'])

    def copy_report(self, source, *, product=None, scheduled=None, quantity='3', day=None):
        scheme = source.scheme
        source_line = source.lines.get()
        scheme_line = source_line.scheme_line
        work_item = source_line.work_item
        if product is not None:
            scheme = self.copy_row(
                scheme, scheme_number=f'GJ-{uuid.uuid4().hex}', product_line_id=product.pk,
                schedule_product_id=scheduled.pk,
            )
            work_item = self.copy_row(work_item, product_line_id=product.pk)
            scheme_line = self.copy_row(scheme_line, scheme_id=scheme.pk, work_item_id=work_item.pk)
        product = product or source.product_line
        scheduled = scheduled or source.schedule_product
        amount = (Decimal(quantity) * source_line.unit_price_snapshot).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        report = self.copy_row(
            source, report_number=f'BG-{uuid.uuid4().hex}', client_request_id=uuid.uuid4(),
            product_line_id=product.pk, schedule_product_id=scheduled.pk, scheme_id=scheme.pk,
            task_number_snapshot=product.production_task.task_number,
            order_number_snapshot=product.production_task.order_number,
            total_amount=amount, production_date=day or source.production_date,
        )
        self.copy_row(
            source_line, report_id=report.pk, scheme_line_id=scheme_line.pk, work_item_id=work_item.pk,
            quantity=Decimal(quantity), amount=amount,
        )
        return report

    def test_tasks_are_paginated_before_products_and_search_restores_older_task(self):
        task, schedule, _, _ = self.add_task()
        products = ProductionTaskProduct.objects.bulk_create([
            ProductionTaskProduct(**self.copy_values(self.product_line, production_task_id=task.pk, line_number=n))
            for n in range(2, 203)
        ])
        scheduled = ProductionScheduleProduct.objects.bulk_create([
            ProductionScheduleProduct(**self.copy_values(
                self.schedule_product, schedule_id=schedule.pk, product_line_id=product.pk,
                line_number=product.line_number,
            )) for product in products
        ])
        ProductionScheduleProductCraft.objects.bulk_create([
            ProductionScheduleProductCraft(
                schedule_product=product, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
                craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
            ) for product in scheduled
        ])

        first = self.client.get(self.task_url, {'page_size': 1})
        second = self.client.get(self.task_url, {'page_size': 1, 'page': 2})
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data['meta']['total'], 2)
        self.assertEqual(first.data['data'][0]['id'], str(task.pk))
        self.assertEqual(second.data['data'][0]['id'], str(self.task.pk))
        for params in ({'q': self.task.order_number}, {'production_task_id': str(self.task.pk)}):
            response = self.client.get(self.task_url, params)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual([row['id'] for row in response.data['data']], [str(self.task.pk)])
            self.assertEqual([{key: item[key] for key in ('id', 'name')} for item in response.data['data'][0]['workshops']], [
                {'id': str(self.workshop.pk), 'name': self.workshop.name},
            ])

    def test_historical_report_remains_available_after_schedule_void_and_craft_inactive(self):
        self.create_report()
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.version += 1
        self.schedule.void_reason = '历史报工查询测试'
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        self.craft.status = RecordStatus.INACTIVE
        self.craft.save(update_fields=['status', 'updated_at'])

        response = self.client.get(self.task_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['data']), 1)
        row = response.data['data'][0]
        self.assertEqual((row['id'], row['task_number'], row['order_number']), (
            str(self.task.pk), self.task.task_number, self.task.order_number,
        ))
        self.assertEqual([{key: item[key] for key in ('id', 'name')} for item in row['workshops']], [
            {'id': str(self.workshop.pk), 'name': self.workshop.name},
        ])

    def test_task_filters_include_all_products_and_keep_cumulative_and_schedule_scope(self):
        first = self.create_report()
        product, scheduled = self.add_product(self.task, self.schedule, 2)
        second = self.copy_report(first, product=product, scheduled=scheduled, quantity='3')
        self.copy_report(first, quantity='1', day=timezone.localdate() - timedelta(days=1))
        _, _, other_product, other_scheduled = self.add_task()
        self.copy_report(first, product=other_product, scheduled=other_scheduled, quantity='7')
        params = {'production_task_id': str(self.task.pk), 'workshop_id': str(self.workshop.pk)}

        days = self.client.get(self.day_url, params)
        self.assertEqual(days.status_code, 200, days.data)
        self.assertEqual(days.data['meta']['total'], 2)
        today = days.data['data'][0]
        self.assertEqual((today['report_count'], today['product_count'], today['order_count']), (2, 2, 1))
        self.assertEqual(Decimal(today['total_amount']), Decimal('11.73'))
        detail = self.client.get(f'{self.day_url}{timezone.localdate().isoformat()}/', params)
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual({row['id'] for row in detail.data['data']}, {str(first.pk), str(second.pk)})
        for row in detail.data['data']:
            self.assertEqual(Decimal(row['lines'][0]['cumulative_quantity']), Decimal('3'))
        filtered = self.client.get(f'{self.day_url}{timezone.localdate().isoformat()}/', {
            **params, 'schedule_product_id': str(scheduled.pk),
        })
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual([row['id'] for row in filtered.data['data']], [str(second.pk)])

    def test_scoped_report_permission_can_select_task_without_task_view_and_hides_other_workshop(self):
        report = self.create_report()
        other_workshop, _ = Workshop.objects.get_or_create(name='装配车间')
        other_craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=other_workshop, name='任务选择装配工艺',
            plan_category=PlanCategory.ASSEMBLY,
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=other_craft, craft_type_snapshot=CraftType.INTERNAL,
            craft_name_snapshot=other_craft.name, plan_category=PlanCategory.ASSEMBLY,
        )
        user = get_user_model().objects.create_user(username='task-report-scoped')
        employee = Employee.objects.create(user=user, employee_code='TASK-REPORT-SCOPED', display_name='报工查看员')
        group = Group.objects.create(name='TASK-REPORT-SCOPED')
        role = RoleProfile.objects.create(role_code='TASK_REPORT_SCOPED', display_name='报工查看员', auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        permission = Permission.objects.get(content_type__app_label='workshop_reporting', codename='view_workreport')
        group.permissions.add(permission)
        grant = RoleActionGrant.objects.create(role=role, permission=permission, scope='WORKSHOP')
        RoleGrantResource.objects.create(grant=grant, workshop=self.workshop)
        client = APIClient()
        client.force_authenticate(user)

        with override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            response = client.get(self.task_url)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual([{key: item[key] for key in ('id', 'name')} for item in response.data['data'][0]['workshops']], [
                {'id': str(self.workshop.pk), 'name': self.workshop.name},
            ])
            params = {'production_task_id': str(self.task.pk), 'workshop_id': str(self.workshop.pk)}
            self.assertEqual(client.get(self.day_url, params).data['meta']['total'], 1)
            detail = client.get(f'{self.day_url}{timezone.localdate().isoformat()}/', params)
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual([row['id'] for row in detail.data['data']], [str(report.pk)])
            hidden = client.get(self.day_url, {**params, 'workshop_id': str(other_workshop.pk)})
            self.assertEqual(hidden.data['data'], [])
            self.assertFalse(user.has_perm('production_tasks.view_productiontask'))
            report_list = client.get(self.report_url, params)
            self.assertEqual(report_list.status_code, 200, report_list.data)
            self.assertEqual([row['id'] for row in report_list.data['data']], [str(report.pk)])
            hidden_reports = client.get(self.report_url, {**params, 'workshop_id': str(other_workshop.pk)})
            self.assertEqual(hidden_reports.data['data'], [])

    def test_permission_and_invalid_or_missing_task_boundaries(self):
        for url in (self.task_url, self.day_url, self.report_url, f'{self.day_url}{timezone.localdate().isoformat()}/'):
            response = self.client.get(url, {'production_task_id': 'invalid'})
            self.assertEqual(response.status_code, 400, response.data)
            response = self.client.get(url, {'production_task_id': str(uuid.uuid4())})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['data'], [])
        user = get_user_model().objects.create_user(username='task-report-denied')
        Employee.objects.create(user=user, employee_code='TASK-REPORT-DENIED', display_name='无权限查看员')
        self.client.force_authenticate(user)
        for url in (self.task_url, self.day_url, self.report_url, f'{self.day_url}{timezone.localdate().isoformat()}/'):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_report_list_keeps_two_same_day_submissions_and_snapshot_amounts_separate(self):
        first = self.create_report()
        second = self.copy_report(first, quantity='3')

        response = self.client.get(self.report_url, {
            'production_task_id': str(self.task.pk), 'workshop_id': str(self.workshop.pk),
        })

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['meta']['total'], 2)
        self.assertEqual([row['id'] for row in response.data['data']], [str(second.pk), str(first.pk)])
        for row, report, quantity, amount in zip(
            response.data['data'], (second, first), ('3', '2'), ('7.04', '4.69'), strict=True,
        ):
            self.assertEqual(row['report_number'], report.report_number)
            self.assertEqual(Decimal(row['total_amount']), Decimal(amount))
            self.assertEqual(row['line_count'], 1)
            self.assertEqual(Decimal(row['lines'][0]['quantity']), Decimal(quantity))
            self.assertEqual(Decimal(row['lines'][0]['amount']), Decimal(amount))
            self.assertEqual(Decimal(row['lines'][0]['required_quantity']), Decimal('200'))
            self.assertEqual(Decimal(row['lines'][0]['cumulative_quantity']), Decimal('5'))
            self.assertTrue(row['created_at'])
            self.assertTrue(row['recorder'])

    def test_report_list_pagination_preserves_full_cumulative_and_creation_order(self):
        first = self.create_report()
        second = self.copy_report(first, quantity='3')
        previous_day = self.copy_report(first, quantity='1', day=timezone.localdate() - timedelta(days=1))
        WorkReport.objects.filter(pk=first.pk).update(updated_at=timezone.now() + timedelta(seconds=1))

        for page, expected in enumerate((second, first, previous_day), start=1):
            response = self.client.get(self.report_url, {
                'production_task_id': str(self.task.pk), 'workshop_id': str(self.workshop.pk),
                'page_size': 1, 'page': page,
            })
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['meta']['total'], 3)
            self.assertEqual([row['id'] for row in response.data['data']], [str(expected.pk)])
            self.assertEqual(Decimal(response.data['data'][0]['lines'][0]['cumulative_quantity']), Decimal('6'))

    def test_report_list_filters_task_schedule_workshop_and_craft(self):
        first = self.create_report()
        product, scheduled = self.add_product(self.task, self.schedule, 2)
        second = self.copy_report(first, product=product, scheduled=scheduled, quantity='3')
        _, _, other_product, other_scheduled = self.add_task()
        self.copy_report(first, product=other_product, scheduled=other_scheduled, quantity='7')
        params = {'production_task_id': str(self.task.pk), 'workshop_id': str(self.workshop.pk)}

        response = self.client.get(self.report_url, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row['id'] for row in response.data['data']}, {str(first.pk), str(second.pk)})
        filtered = self.client.get(self.report_url, {
            **params, 'schedule_product_id': str(scheduled.pk), 'craft_id': str(self.craft.pk),
        })
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual([row['id'] for row in filtered.data['data']], [str(second.pk)])
        for field in ('workshop_id', 'schedule_product_id', 'craft_id'):
            invalid = self.client.get(self.report_url, {**params, field: 'invalid'})
            self.assertEqual(invalid.status_code, 400, invalid.data)
            missing = self.client.get(self.report_url, {**params, field: str(uuid.uuid4())})
            self.assertEqual(missing.status_code, 200, missing.data)
            self.assertEqual(missing.data['data'], [])
