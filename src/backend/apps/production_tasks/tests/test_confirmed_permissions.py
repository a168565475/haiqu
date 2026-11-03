"""确认方案的真实接口边界；全部记录由隔离测试库承载。"""
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.core.api.concurrency import etag_for_instance
from apps.finance.tests.test_statements import create_source
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTaskStatus


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ConfirmedTaskPermissionTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        self.other = Employee.objects.create(employee_code='TASK-OTHER', display_name='其他建单人')
        self.task = create_source(self.other, quantities=(1,), prices=('100',))
        self.task.task_number = self.task.task_number.upper()
        self.task.contract_number = self.task.contract_number.upper()
        self.task.save(update_fields=['task_number', 'contract_number'])
        self.url = f'/api/v1/production-tasks/{self.task.pk}/'

    def patch(self, data):
        self.task.refresh_from_db()
        return self.client.patch(self.url, data, format='json', HTTP_IF_MATCH=etag_for_instance(self.task))

    def test_plan_only_editor_preserves_status_and_rejects_business_fields(self):
        self.grant('production_tasks.view_productiontask')
        self.grant('access_control.edit_productionplan')
        result = self.patch({'planned_start_date': '2026-11-02', 'planned_end_date': '2026-11-04'})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['data']['status'], 'READY')
        self.assertEqual(set(result.data['data']['allowed_update_fields']),
                         {'planned_start_date', 'planned_end_date', 'production_priority', 'follower_ids'})
        self.assertEqual(self.patch({'delivery_date': '2026-11-09'}).status_code, 400)
        self.assertEqual(self.patch({'products': []}).status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.delivery_date.isoformat(), '2026-10-30')
        self.assertEqual(self.task.products.count(), 1)

    def test_followed_read_and_export_recheck_current_relationship(self):
        self.grant('production_tasks.view_productiontask', 'FOLLOWED')
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.task.followers.add(self.scope_employee)
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200, result.data)
        other = create_source(self.scope_employee, quantities=(1,), prices=('100',))
        exported = self.client.get('/api/v1/production-tasks/export/')
        self.assertEqual(exported.status_code, 200, getattr(exported, 'data', None))
        content = b''.join(exported.streaming_content) if exported.streaming else exported.content
        self.assertIn(self.task.task_number.encode(), content)
        self.assertNotIn(other.task_number.encode(), content)
        self.task.followers.clear()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_confirmation_cannot_bypass_plan_field_whitelist(self):
        self.grant('production_tasks.confirm_productiontask')
        grant = self.grant('access_control.edit_productionplan')
        grant.role.role_code = 'MERCHANDISER'
        grant.role.save(update_fields=['role_code'])
        self.task.status = ProductionTaskStatus.PENDING_VALIDATION
        self.task.save(update_fields=['status'])
        result = self.client.post(self.url + 'confirm/', {
            'follower_ids': [str(self.scope_employee.pk)], 'delivery_date': '2026-11-09',
            'planned_start_date': '2026-11-02', 'planned_end_date': '2026-11-04',
        }, format='json', HTTP_IF_MATCH=etag_for_instance(self.task))
        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn('delivery_date', result.data['error']['field_errors'])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.PENDING_VALIDATION)
        self.assertEqual(self.task.delivery_date.isoformat(), '2026-10-30')

    def test_pause_resume_preserves_prior_state_and_checks_etag(self):
        self.grant('access_control.pause_productiontask')
        self.grant('access_control.resume_productiontask')
        old_etag = etag_for_instance(self.task)
        paused = self.client.post(self.url + 'pause/', {'reason': '等待厂内协调'}, format='json', HTTP_IF_MATCH=old_etag)
        self.assertEqual(paused.status_code, 200, paused.data)
        self.assertEqual(paused.data['data']['status'], 'PAUSED')
        stale = self.client.post(self.url + 'resume/', {'reason': '已协调'}, format='json', HTTP_IF_MATCH=old_etag)
        self.assertEqual(stale.status_code, 412, stale.data)
        resumed = self.client.post(self.url + 'resume/', {'reason': '已协调'}, format='json', HTTP_IF_MATCH=paused['ETag'])
        self.assertEqual(resumed.status_code, 200, resumed.data)
        self.assertEqual(resumed.data['data']['status'], 'READY')

    def test_pause_denies_unauthorized_and_unknown_resume_history(self):
        self.grant('production_tasks.view_productiontask')
        denied = self.client.post(self.url + 'pause/', {'reason': '测试'}, format='json', HTTP_IF_MATCH=etag_for_instance(self.task))
        self.assertEqual(denied.status_code, 403)
        self.grant('access_control.resume_productiontask')
        self.task.status = ProductionTaskStatus.PAUSED
        self.task.save(update_fields=['status'])
        result = self.client.post(self.url + 'resume/', {'reason': '没有暂停历史'}, format='json', HTTP_IF_MATCH=etag_for_instance(self.task))
        self.assertEqual(result.status_code, 409, result.data)

    def test_finance_expense_maintenance_does_not_allow_void(self):
        self.grant('production_tasks.manage_productiontaskexpense')
        result = self.client.delete(self.url + f'cost-expenses/{uuid4()}/')
        self.assertEqual(result.status_code, 403, result.data)
