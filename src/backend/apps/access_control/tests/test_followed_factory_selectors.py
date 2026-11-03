from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.material_issues.models import MaterialIssue
from apps.material_issues.selectors import accessible_material_issues
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_scheduling.selectors import accessible_production_schedules, schedules_with_context, schedule_items_for_category
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_reporting.selectors import accessible_work_reports, reporting_source_products, work_report_selection_sources
from apps.workshop_reporting.tests.test_work_report_task_selection import WorkReportTaskSelectionTests


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class FollowedFactorySelectorTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.fixture = WorkReportTaskSelectionTests()
        self.fixture.setUp()
        self.fixture.user.is_superuser = True
        self.fixture.user.save(update_fields=['is_superuser'])
        self.own_report = self.fixture.create_report()
        self.other_task, self.other_schedule, product, self.other_product = self.fixture.add_task()
        self.other_report = self.fixture.copy_report(self.own_report, product=product, scheduled=self.other_product)
        self.scoped_actor()
        self.fixture.task.followers.add(self.scope_employee)
        self.other_task.salesperson = self.scope_employee
        self.other_task.created_by_employee = self.scope_employee
        self.other_task.save(update_fields=['salesperson', 'created_by_employee'])
        for code in ('production_scheduling.view_productionschedule', 'material_issues.view_materialissue',
                     'workshop_reporting.view_workreport'):
            self.grant(code, 'FOLLOWED')
        self.own_issue = self.issue(self.fixture.task)
        self.other_issue = self.issue(self.other_task)
        self.standalone_issue = self.issue(None)

    def issue(self, task):
        return MaterialIssue.objects.create(issue_number='LL-' + uuid4().hex.upper(), client_request_id=uuid4(),
            request_payload_hash='a' * 64, production_task=task, workshop=self.fixture.workshop,
            created_by_employee=self.scope_employee, updated_by_employee=self.scope_employee)

    def test_followed_lists_sources_and_details_ignore_creator_and_salesperson(self):
        request = self.scoped_request()
        self.assertEqual(set(accessible_production_schedules(request)), {self.fixture.schedule})
        self.assertEqual(set(accessible_material_issues(request)), {self.own_issue})
        self.assertEqual(set(accessible_work_reports(request)), {self.own_report})
        self.assertEqual(set(reporting_source_products(request, 'workshop_reporting.view_workreport')), {self.fixture.schedule_product})
        reports, crafts = work_report_selection_sources(request)
        self.assertEqual(set(reports), {self.own_report})
        self.assertEqual(set(crafts.values_list('schedule_product_id', flat=True)), {self.fixture.schedule_product.pk})
        own = self.client.get('/api/v1/workshop-reporting/context/', {
            'purpose': 'work_report', 'schedule_product_id': str(self.fixture.schedule_product.pk)})
        self.assertEqual(own.status_code, 200, own.data)
        denied = self.client.get('/api/v1/workshop-reporting/context/', {
            'purpose': 'work_report', 'schedule_product_id': str(self.other_product.pk)})
        self.assertEqual(denied.status_code, 404, denied.data)

    def test_reassignment_removes_followed_visibility_without_flag_fallback(self):
        self.fixture.task.followers.remove(self.scope_employee)
        for flags in ({}, {'MODULE_ACCESS_ENABLED': False, 'ACCESS_RESOURCE_SCOPES_ENABLED': False}):
            with self.subTest(flags=flags), override_settings(**flags):
                request = self.scoped_request()
                self.assertFalse(accessible_production_schedules(request).exists())
                self.assertFalse(accessible_material_issues(request).exists())
                self.assertFalse(accessible_work_reports(request).exists())
                self.assertFalse(reporting_source_products(request, 'workshop_reporting.view_workreport').exists())

    def test_independent_workshop_grant_unions_without_expanding_followed_crafts(self):
        sewing = Workshop.objects.get_or_create(name='车缝车间')[0]
        craft = Craft.objects.create(name='跟单范围车缝', craft_type='INTERNAL', workshop=sewing, plan_category='SEWING')
        for product in (self.fixture.schedule_product, self.other_product):
            ProductionScheduleProductCraft.objects.create(schedule_product=product, craft=craft,
                craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name, plan_category='SEWING')
        self.grant('production_scheduling.view_productionschedule', 'WORKSHOP', [self.fixture.workshop])
        self.grant('workshop_reporting.view_workreport', 'WORKSHOP', [self.fixture.workshop])
        self.grant('material_issues.view_materialissue', 'WORKSHOP', [self.fixture.workshop])
        request = self.scoped_request()
        self.assertEqual(set(accessible_material_issues(request)), {self.own_issue, self.other_issue, self.standalone_issue})
        schedules = {row.pk: row for row in schedules_with_context(accessible_production_schedules(request), request)}
        own_crafts = {link.craft_id for link in schedules[self.fixture.schedule.pk].active_products[0].active_crafts}
        other_crafts = {link.craft_id for link in schedules[self.other_schedule.pk].active_products[0].active_crafts}
        self.assertEqual(own_crafts, {self.fixture.craft.pk, craft.pk})
        self.assertEqual(other_crafts, {self.fixture.craft.pk})
        items = list(schedule_items_for_category(request, 'SEWING'))
        self.assertEqual([row.pk for row in items], [self.fixture.schedule_product.pk])
        _, links = work_report_selection_sources(request)
        self.assertFalse(links.filter(schedule_product=self.other_product, craft=craft).exists())
        self.assertTrue(links.filter(schedule_product=self.fixture.schedule_product, craft=craft).exists())
