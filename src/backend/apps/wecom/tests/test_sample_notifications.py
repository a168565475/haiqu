"""08隔离PostgreSQL业务/API检查；不代表正式员工走单，不调用企微网络。"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, Warehouse, WarehouseZone
from apps.organizations.models import EmployeeRoleAssignment
from apps.samples.models import SampleMaterialIssue, SampleMaterialProcurementRequest, SampleRequest
from apps.samples.tests import test_application_api as application_tests
from apps.samples.tests import test_material_api as material_tests
from apps.samples.tests import test_application_production as production_tests
from apps.wecom.models import NotificationEvent, NotificationDelivery, NotificationRule
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_catalog import get_event
from apps.wecom.notification_selectors import recipient_payload
from apps.wecom.notification_services import register_business_event, update_rule
from .test_notifications import SETTINGS, create_rule, employee, grant_role, rule_data


@override_settings(**SETTINGS)
class SampleApplicationNotificationTests(APITestCase):
    def setUp(self):
        self.f = application_tests.SampleApplicationApiTests()
        self.f.setUp()
        self.director = employee('U08_DIRECTOR')
        self.director_role = grant_role(self.director, 'FACTORY_MANAGER', 'samples.review_sample_application')
        self.executor = employee('U08_EXECUTOR')
        self.executor_role = grant_role(self.executor, 'METAL_SAMPLING', 'samples.complete_sample_requirements')
        create_rule('SAMPLE_SUBMITTED', self.f.employee, ['FACTORY_MANAGER'])
        create_rule('SAMPLE_EFFECTIVE', self.f.employee, ['METAL_SAMPLING'])
        self.applicant_role = grant_role(self.f.employee, 'U08_APPLICANT', 'samples.add_samplerequest')
        create_rule('SAMPLE_RETURNED', self.f.employee, [self.applicant_role.role_code], recipient_scope='SUBMITTER')

    def request(self):
        return SimpleNamespace(user=self.f.user, employee=self.f.employee, META={}, headers={})

    def test_factory_creator_effective_once_without_self_review_or_pending_notification(self):
        EmployeeRoleAssignment.objects.create(employee=self.f.employee, role_profile=self.director_role, effective_from=timezone.now())
        payload = self.f.payload()
        created = self.f.submit(payload)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['data']['status'], 'PENDING_COMPLETION')
        sample = SampleRequest.objects.get(pk=created.data['data']['id'])
        self.assertEqual((sample.created_by_employee_id, sample.requested_by_employee_id), (self.f.employee.pk, self.f.employee.pk))
        audit = AuditLog.objects.get(object_id=sample.pk, action='APPLICATION_EFFECTIVE')
        self.assertEqual(audit.actor_employee_id, self.f.employee.pk)
        self.assertIn('FACTORY_MANAGER', audit.after_data['note'])
        self.assertFalse(AuditLog.objects.filter(object_id=sample.pk, action='DIRECTOR_APPROVED').exists())
        self.assertFalse(NotificationEvent.objects.filter(event_code='SAMPLE_SUBMITTED').exists())
        event = NotificationEvent.objects.get(event_code='SAMPLE_EFFECTIVE')
        self.assertEqual(event.recipients.get().employee_id, self.executor.pk)
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
        replay = self.f.submit(payload)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(self.f.review(created).status_code, 409)

    def test_general_manager_and_forged_role_still_require_review(self):
        grant_role(self.f.employee, 'GENERAL_MANAGER', 'samples.add_samplerequest')
        created = self.f.submit(self.f.payload(role_code='FACTORY_MANAGER', directly_effective=True))
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['data']['status'], 'DIRECTOR_REVIEW')
        event = NotificationEvent.objects.get(event_code='SAMPLE_SUBMITTED')
        self.assertEqual(event.recipients.get().employee_id, self.director.pk)
        approved = self.f.review(created)
        self.assertEqual(approved.status_code, 200, approved.data)  # 不改变当前已有的本人审核规则。
        event.recipients.get().refresh_from_db()
        self.assertFalse(event_object_accessible('SAMPLE_SUBMITTED', event.object_id, self.director.user, object_version=event.object_version))

    def test_expired_or_archived_factory_role_does_not_bypass_review(self):
        EmployeeRoleAssignment.objects.create(employee=self.f.employee, role_profile=self.director_role,
            effective_from=timezone.now() - timedelta(days=2), effective_to=timezone.now() - timedelta(days=1))
        self.assertEqual(self.f.submit().data['data']['status'], 'DIRECTOR_REVIEW')
        self.director_role.archived_at = timezone.now()
        self.director_role.save()
        self.assertEqual(self.f.submit().data['data']['status'], 'DIRECTOR_REVIEW')

    def test_return_to_real_original_applicant_only_and_resubmission_expires_message(self):
        outsider = employee('U08_SAME_ROLE')
        EmployeeRoleAssignment.objects.create(employee=outsider, role_profile=self.applicant_role, effective_from=timezone.now())
        created = self.f.submit()
        returned = self.f.review(created, 'return', '补充规格')
        self.assertEqual(returned.status_code, 200, returned.data)
        event = NotificationEvent.objects.get(event_code='SAMPLE_RETURNED')
        self.assertEqual(event.context['submitter_id'], str(self.f.employee.pk))
        self.assertEqual(list(event.recipients.values_list('employee_id', flat=True)), [self.f.employee.pk])
        self.assertFalse(event_object_accessible('SAMPLE_RETURNED', event.object_id, outsider.user, object_version=event.object_version))
        response = self.f.client.post(f'/api/v1/sample-requests/{event.object_id}/application-resubmit/',
            {'payload': self.f.payload()}, format='json', HTTP_IF_MATCH=returned['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(recipient_payload(event.recipients.get(), self.f.user)['title'], '通知已过期')
        self.assertEqual(NotificationEvent.objects.filter(event_code='SAMPLE_SUBMITTED').count(), 2)

    def test_return_scope_cannot_be_switched_to_role_broadcast(self):
        grant_role(self.f.employee, 'U08_NOTIFICATION_MANAGER', 'access_control.manage_notifications')
        request = self.request()
        from apps.wecom.notification_selectors import rule_etag
        request.headers = {'If-Match': rule_etag(NotificationRule.objects.get(event_code='SAMPLE_RETURNED'))}
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            update_rule(request, 'SAMPLE_RETURNED', rule_data('SAMPLE_RETURNED', [self.applicant_role.role_code], recipient_scope='ROLE_MEMBERS'))

    def test_wrong_object_version_type_or_submitter_rejected_and_rollback_is_atomic(self):
        created = self.f.submit()
        event = NotificationEvent.objects.get()
        args = dict(event_code=event.event_code, idempotency_key='u08-invalid', object_type=event.object_type,
            object_id=event.object_id, object_version=event.object_version,
            context={key: value for key, value in event.context.items() if not key.startswith('_')})
        for updates in ({'object_type': 'material_issues.MaterialIssue'}, {'object_version': 'wrong', 'context': {**args['context'], 'object_version': 'wrong'}},
                        {'context': {**args['context'], 'submitter_id': str(uuid4())}}):
            with self.subTest(updates=updates), self.assertRaises(Conflict):
                register_business_event(**{**args, **updates})
        count = NotificationEvent.objects.count()
        with self.assertRaises(RuntimeError), transaction.atomic():
            approved = self.f.review(created)
            self.assertEqual(approved.status_code, 200, approved.data)
            raise RuntimeError('rollback')
        self.assertEqual(NotificationEvent.objects.count(), count)
        self.assertEqual(SampleRequest.objects.get(pk=event.object_id).status, 'DIRECTOR_REVIEW')

    def test_revoked_recipient_permission_hides_content_and_blocks_delivery(self):
        self.f.submit()
        event = NotificationEvent.objects.get()
        RoleActionGrant.objects.filter(role=self.director_role).delete()
        recipient = event.recipients.get()
        self.assertFalse(recipient_payload(recipient, self.director.user)['target_accessible'])
        # API客户端不代表正式Session；该验证只证明撤权重查服务。
        self.assertFalse(event_object_accessible(event.event_code, event.object_id, self.director.user, role_codes=['FACTORY_MANAGER'], object_version=event.object_version))


@override_settings(**SETTINGS)
class SampleMaterialNotificationTests(APITestCase):
    def setUp(self):
        self.f = material_tests.SampleMaterialApiTests()
        self.f.setUp()
        self.warehouse = employee('U08_WAREHOUSE')
        self.warehouse_role = grant_role(self.warehouse, 'WAREHOUSE_KEEPER', 'samples.review_sample_materials')
        self.executor = employee('U08_METAL')
        self.executor_role = grant_role(self.executor, 'METAL_SAMPLING', 'samples.edit_sample_materials')
        metal = Permission.objects.get(content_type__app_label='access_control', codename='metalwork_sample')
        RoleActionGrant.objects.create(role=self.executor_role, permission=metal, scope='MODULE')
        self.purchaser = employee('U08_PURCHASER')
        self.purchase_role = grant_role(self.purchaser, 'PURCHASING', 'samples.view_sample_procurement')
        for code, role in [('SAMPLE_REQUIREMENTS_COMPLETED', self.executor_role), ('SAMPLE_MATERIALS_SUBMITTED', self.warehouse_role),
                           ('SAMPLE_MATERIAL_SHORTAGE', self.purchase_role), ('SAMPLE_MATERIALS_AVAILABLE', self.executor_role),
                           ('SAMPLE_MATERIAL_ISSUE_SUBMITTED', self.warehouse_role), ('SAMPLE_MATERIAL_ISSUED', self.executor_role),
                           ('SAMPLE_PRODUCTION_READY', self.executor_role)]:
            create_rule(code, self.f.employee, [role.role_code])

    def warehouse_state(self):
        state = self.f.to_warehouse()
        self.sample = SampleRequest.objects.get(pk=self.f.root.split('/')[-2])
        return state

    def stock(self, quantity):
        warehouse = Warehouse.objects.create(warehouse_number='U08-MAT', warehouse_name='08材料仓', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='08材料区')
        raw_id = self.sample.material_request.draft['lines'][0]['rawMaterialId']
        return MaterialStockBalance.objects.create(raw_material_id=raw_id, unit=self.f.unit, zone=zone, quality='AVAILABLE', quantity=quantity)

    def test_material_submit_shortage_partial_supply_and_real_stock_condition(self):
        state = self.warehouse_state()
        self.assertEqual(NotificationEvent.objects.get(event_code='SAMPLE_REQUIREMENTS_COMPLETED').recipients.get().employee_id, self.executor.pk)
        self.assertEqual(NotificationEvent.objects.get(event_code='SAMPLE_MATERIALS_SUBMITTED').recipients.get().employee_id, self.warehouse.pk)
        stock = self.stock(Decimal('12'))
        response = self.f.put('warehouse-review', self.f.supplies(state, ('12', '0', '0')), True, state['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        shortage = NotificationEvent.objects.get(event_code='SAMPLE_MATERIAL_SHORTAGE')
        self.assertEqual(shortage.object_id, str(SampleMaterialProcurementRequest.objects.get().pk))
        self.assertEqual(shortage.recipients.get().employee_id, self.purchaser.pk)
        ready = NotificationEvent.objects.get(event_code='SAMPLE_MATERIALS_AVAILABLE')
        self.assertEqual(ready.recipients.get().employee_id, self.executor.pk)
        self.assertIn('不代表全部齐料', ready.rendered_body)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 12)
        self.assertFalse(MaterialStockMovement.objects.exists())  # 核库不扣库。
        stock.quantity = 0
        stock.save()
        self.assertFalse(recipient_payload(ready.recipients.get(), self.executor.user)['target_accessible'])

    def test_no_physical_stock_does_not_publish_available_notice(self):
        state = self.warehouse_state()
        response = self.f.put('warehouse-review', self.f.supplies(state, ('12', '6', '4')), True, state['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(NotificationEvent.objects.filter(event_code='SAMPLE_MATERIALS_AVAILABLE').exists())

    def test_procurement_only_identity_reads_narrow_context_without_full_sample_access(self):
        state = self.warehouse_state()
        response = self.f.put('warehouse-review', self.f.supplies(state, ('0', '0', '0')), True, state['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.purchaser.user)
        self.assertEqual(client.get(self.f.root).status_code, 403)
        self.assertEqual(client.get(self.f.root + 'materials/').status_code, 403)
        context = client.get(self.f.root + 'procurement-material-context/')
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(context.data['data']['sample']['id'], str(self.sample.pk))
        self.assertEqual(context.data['data']['materials']['procurementRequest']['id'], str(SampleMaterialProcurementRequest.objects.get().pk))
        self.assertNotIn('owner_employee', context.data['data']['sample'])
        self.assertNotIn('purpose', context.data['data']['sample'])
        self.assertFalse(context.data['data']['materials']['canEdit'])
        RoleActionGrant.objects.filter(role=self.purchase_role).delete()
        self.assertEqual(client.get(self.f.root + 'procurement-material-context/').status_code, 403)

    def test_issue_uses_real_sample_issue_uuid_and_actual_debit_and_replay(self):
        state = self.warehouse_state()
        stock = self.stock(Decimal('12'))
        ready = self.f.put('warehouse-review', self.f.supplies(state, ('12', '0', '0')), True, state['ETag'])
        url = self.f.root + 'material-issue/'
        initiation = self.f.client.post(url + 'initiate/', {'client_request_id': str(uuid4())}, format='json', HTTP_IF_MATCH=ready['ETag'])
        self.assertEqual(initiation.status_code, 200, initiation.data)
        issue = SampleMaterialIssue.objects.get()
        event = NotificationEvent.objects.get(event_code='SAMPLE_MATERIAL_ISSUE_SUBMITTED')
        self.assertEqual((event.object_type, event.object_id), ('samples.SampleMaterialIssue', str(issue.pk)))
        self.assertEqual(event.target['params'], {'sampleId': str(self.sample.pk)})
        self.assertEqual(event.target['route_name'], 'sample-material-issue-confirm')
        request_id = str(uuid4())
        confirmed = self.f.client.post(url + 'confirm/', {'request_id': request_id}, format='json', HTTP_IF_MATCH=initiation['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        issued = NotificationEvent.objects.get(event_code='SAMPLE_MATERIAL_ISSUED')
        self.assertEqual(issued.recipients.get().employee_id, self.executor.pk)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 0)
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='SAMPLE_MATERIAL_ISSUE').count(), 1)
        replay = self.f.client.post(url + 'confirm/', {'request_id': request_id}, format='json', HTTP_IF_MATCH=initiation['ETag'])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(NotificationEvent.objects.filter(event_code='SAMPLE_MATERIAL_ISSUED').count(), 1)
        self.assertFalse(event_object_accessible(event.event_code, event.object_id, self.warehouse.user, object_version=event.object_version))

    def test_no_materials_only_notifies_current_parameter_or_reporting_operators(self):
        self.f.prepare()
        only_materials = employee('U08_MATERIALS_ONLY')
        EmployeeRoleAssignment.objects.create(employee=only_materials, role_profile=self.executor_role, effective_from=timezone.now())
        RoleActionGrant.objects.filter(role=self.executor_role, permission__codename='metalwork_sample').delete()
        state = self.f.client.get(self.f.root + 'materials/')
        result = self.f.client.post(self.f.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        event = NotificationEvent.objects.get(event_code='SAMPLE_PRODUCTION_READY')
        self.assertEqual(event.status, 'NO_RECIPIENT')
        self.assertFalse(NotificationEvent.objects.filter(event_code='SAMPLE_MATERIALS_SUBMITTED').exists())


class SampleCompletionNotificationTests(APITestCase):
    def setUp(self):
        self.f = production_tests.ApplicationProductionTests()
        self.f.setUp()
        self.f.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='access_control',
            codename__in=['metalwork_sample', 'cutting_sample', 'metalreport_sample', 'cuttingreport_sample']))
        self.warehouse = employee('U08_FINISHED_WAREHOUSE')
        self.role = grant_role(self.warehouse, 'WAREHOUSE_KEEPER', 'samples.add_sampleinventoryreceipt')
        self.factory = employee('U08_FINISHED_FACTORY')
        grant_role(self.factory, 'FACTORY_MANAGER', 'samples.view_samplerequest')
        create_rule('SAMPLE_COMPLETED', self.f.employee, ['WAREHOUSE_KEEPER', 'FACTORY_MANAGER'])

    @override_settings(**SETTINGS)
    def test_both_parameters_and_reports_auto_complete_once_without_director_gate(self):
        ready = self.f.no_materials()
        self.assertFalse(NotificationEvent.objects.filter(event_code='SAMPLE_COMPLETED').exists())
        metal = self.f.upload('metalwork', ready['ETag'])
        cutting = self.f.upload('cutting', metal['ETag'])
        incomplete = self.f.report(cutting['ETag'], False)
        self.assertFalse(NotificationEvent.objects.filter(event_code='SAMPLE_COMPLETED').exists())
        done = self.f.report(incomplete['ETag'])
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['data']['status'], 'FINISHED')
        event = NotificationEvent.objects.get(event_code='SAMPLE_COMPLETED')
        self.assertEqual(set(event.recipients.values_list('employee_id', flat=True)), {self.factory.pk, self.warehouse.pk})
        self.assertEqual(event.recipients.count(), 2)
        self.assertEqual(NotificationDelivery.objects.filter(recipient__event=event).count(), 4)
        self.assertFalse(get_event('SAMPLE_INVENTORY_RECEIVED')['enabled_by_default'])


@override_settings(**SETTINGS)
class SampleNotificationDeliveryTests(TransactionTestCase):
    def test_state_change_and_revocation_block_pending_delivery_before_network(self):
        from apps.wecom.notification_services import process_delivery
        fixture = SampleApplicationNotificationTests()
        fixture.setUp()
        created = fixture.f.submit()
        self.assertEqual(created.status_code, 201, created.data)
        event = NotificationEvent.objects.get()
        delivery = event.recipients.get().deliveries.get(channel='WECOM')
        RoleActionGrant.objects.filter(role=fixture.director_role).delete()
        result = process_delivery(delivery)
        self.assertEqual((result.status, result.error_code, result.attempt_count), ('FAILED', 'RECIPIENT_NOT_ELIGIBLE', 0))

    def test_concurrent_same_business_key_preserves_single_event_and_two_channels(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections, connections
        from threading import Barrier
        fixture = SampleApplicationNotificationTests()
        fixture.setUp()
        fixture.f.submit()
        event = NotificationEvent.objects.get()
        args = dict(event_code=event.event_code, idempotency_key=event.idempotency_key, object_type=event.object_type,
            object_id=event.object_id, object_version=event.object_version,
            context={key: value for key, value in event.context.items() if not key.startswith('_')})
        barrier = Barrier(2)
        def replay():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return register_business_event(**args).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(replay) for _ in range(2)]
            ids = [future.result(timeout=30) for future in futures]
        self.assertEqual(ids, [event.pk, event.pk])
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
