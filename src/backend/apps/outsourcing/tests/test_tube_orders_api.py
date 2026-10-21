"""D2独立订单保存：真实数量服务、数据库事务与公共库存预留。"""
import copy
import json
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.core.models import DailyBusinessNumberCounter
from apps.access_control.tests import test_resource_scopes as access_fixture
from apps.inventory.models import PublicStockMovement
from apps.inventory.public_stock_identity import build_pipe_stock_identity
from apps.inventory.public_stock_services import credit_public_stock, debit_public_stock
from apps.inventory.tests import test_tube_processing_services as tube_fixture
from apps.inventory.tube_processing_services import metal_component_limits, assert_tube_reports_cover_usage
from apps.organizations.models import Employee
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, MaterialIssueAuditEvent, MaterialIssuePublicStockAllocation
from apps.material_issues.pipe_requirements import PIPE_NAMESPACE
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Craft
from apps.workshop_reporting.models import WorkReportLine
from apps.boms.models import BomLine
from ..models import OutsourcingFactory, OutsourcingFactoryCraft, OutsourcingOrder, TubeOutsourcingOrder, TubeOutsourcingLine
from .numbering_concurrency import assert_reference_locks_allow_number_holder


BASE = '/api/v1/tube-outsourcing-orders/'


class TubeApiFixture(tube_fixture.TubeProcessingFixture):
    def make_issue(self, quantity, *, plan=None, proof=True):
        # 原S2夹具允许独立长管参数；D2须使用BOM计算出的5.05米并建立同口径出库凭证。
        length = Decimal('5.05')
        self.metal_bom_line.raw_bar_length_m = length
        self.metal_bom_line.suggested_bar_count = 21
        self.metal_bom_line.suggested_purchase_meters = Decimal('106.05')
        self.metal_bom_line.save(update_fields=['raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters'])
        self.requirement.delete()
        self.requirement.pk = uuid.uuid5(PIPE_NAMESPACE, f'{self.task.pk}:{self.product_line.pk}:{self.component}')
        self.requirement.required_quantity = 210
        self.requirement.raw_bar_length_m = length
        self.requirement.internal_issued_quantity = quantity
        self.requirement.save(force_insert=True)
        identity = build_pipe_stock_identity(raw_material=self.raw, raw_bar_length_m=length, unit=self.root_unit)
        self.pipe_identity = json.loads(json.dumps(identity, cls=DjangoJSONEncoder))
        self.raw_balance = credit_public_stock(identity=identity, zone=self.raw_zone, quantity=100,
            source_type='TEST_TUBE_D2_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        issue = MaterialIssue.objects.create(issue_number=f'TUBE-D2-ISSUE-{uuid.uuid4().hex[:8]}',
            stock_mode='PUBLIC_V2', status='ISSUED', client_request_id=uuid.uuid4(), request_payload_hash='i' * 64,
            production_task=self.task, product_line=self.product_line, workshop=self.workshop,
            recipient_workshop_employee=self.worker, issue_at=timezone.now(), issued_at=timezone.now(),
            issued_by_employee=self.employee, created_by_employee=self.employee, updated_by_employee=self.employee,
            source_revision_hash='i' * 64)
        frozen = {'kind': 'PIPE', 'component_identity': self.component, 'raw_material_id': str(self.raw.pk),
            'product_line_id': str(self.product_line.pk), 'bom_line_id': str(self.metal_bom_line.pk),
            'bom_id': str(self.bom.pk), 'source_revision_hash': 'b' * 64, 'cutting_length_mm': 500,
            'pieces_per_bar': 10, 'raw_bar_length_m': str(length), 'public_identity': self.pipe_identity}
        line = MaterialIssueLine.objects.create(issue=issue, line_number=1, requirement=self.requirement,
            line_type='RAW', raw_material=self.raw, unit=self.piece_unit, unit_snapshot='支',
            section_code_snapshot='PROFILE', conversion_snapshot=frozen,
            requested_quantity=quantity, issued_quantity=quantity)
        MaterialIssueAuditEvent.objects.create(issue=issue, action='CREATED', issue_version=1,
            actor_employee=self.employee, snapshot={'plan_source': {'plan_category': 'METAL',
                'schedule_product_id': str((plan or self.schedule_product).pk)}})
        if proof:
            bars = Decimal(quantity) / 10
            allocation = MaterialIssuePublicStockAllocation.objects.create(line=line, balance=self.raw_balance,
                requested_quantity=quantity, stock_quantity=bars, meter_quantity=bars * length,
                snapshot={'identity_key': self.pipe_identity['identity_key']})
            allocation.movement = debit_public_stock(balance_id=self.raw_balance.pk, quantity=bars,
                source_type='MATERIAL_ISSUE', source_id=issue.pk, source_line_id=allocation.pk,
                actor_employee=self.employee, production_task=self.task, product_line=self.product_line,
                bom_line=self.metal_bom_line, snapshot={'issue_line_id': str(line.pk),
                    'public_identity': self.pipe_identity, 'conversion': frozen})
            allocation.save(update_fields=['movement'])
        return line

    @transaction.atomic
    def setUp(self):
        super().setUp()
        self.raw_balance.refresh_from_db()
        self.spray = Craft.objects.create(craft_type='EXTERNAL', name='测试喷塑', outsourcing_code='POWDER_COATING')
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=self.spray,
            craft_type_snapshot='EXTERNAL', craft_name_snapshot=self.spray.name)
        self.factory = OutsourcingFactory.objects.create(factory_number='TUBE-API-FACTORY', name='管材加工厂',
            processing_type='喷塑', contact_name='测试', contact_phone='123', address='隔离环境',
            created_by_employee=self.employee, updated_by_employee=self.employee)
        OutsourcingFactoryCraft.objects.create(factory=self.factory, craft=self.spray, craft_name_snapshot=self.spray.name)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.report((100, 100))

    def context(self, source='RAW_PIPE', *, client=None):
        query = {'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source}
        if source != 'METAL':
            query['zone_id'] = str((self.raw_zone if source == 'RAW_PIPE' else self.semi_zone).pk)
        response = (client or self.client).get(BASE + 'source-context/', query, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def order_payload(self, source='RAW_PIPE', quantity='20'):
        context = self.context(source)
        self.assertTrue(context['ready'], context)
        self.assertFalse(context['rows'][0]['blockers'], context)
        return {'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'zone_id': context['zone_id'], 'planned_dispatch_date': str(timezone.localdate()),
            'expected_return_date': str(timezone.localdate()), 'remark': '隔离测试',
            'lines': [{'component_identity': self.component, 'quantity': quantity, 'factory_id': str(self.factory.pk)}]}

    def post_order(self, payload, expected=201, *, client=None):
        response = (client or self.client).post(BASE, payload, format='json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, expected, response.data)
        return response


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeOrdersApiTests(TubeApiFixture, APITestCase):
    def test_options_and_context_read_current_source_without_business_writes(self):
        before = (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count(), AuditLog.objects.count())
        options = self.client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data['data']['tasks'][0]['products'][0]['id'], str(self.product_line.pk))
        context = self.context()
        self.assertEqual(context['rows'][0]['order_required'], '200')
        self.assertNotIn('input_identity', context['rows'][0])
        self.assertNotIn('snapshot', context['rows'][0])
        self.assertEqual(before, (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count(), AuditLog.objects.count()))

    def test_raw_save_reserves_once_without_stock_movement_and_recovery_uses_same_number(self):
        payload = self.order_payload()
        movements = PublicStockMovement.objects.count()
        original_stock = self.raw_balance.quantity
        old_orders = OutsourcingOrder.objects.count()
        response = self.post_order(payload)
        data = response.data['data']
        self.assertRegex(data['order_number'], rf'^WF{timezone.localdate():%y%m%d}[0-9]{{3,}}$')
        counter = DailyBusinessNumberCounter.objects.get(number_type='OUTSOURCING_ORDER', business_date=timezone.localdate())
        sequence = counter.last_value
        self.assertEqual((data['total_quantity'], data['total_stock_quantity'], data['total_meters']), ('20', '2', '10.10'))
        self.assertEqual(data['status'], 'PENDING_DISPATCH')
        self.assertIn('ETag', response)
        replay = self.post_order(payload, 200)
        recovered = self.client.get(BASE + f"by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(recovered.status_code, 200, recovered.data)
        self.assertEqual(data['order_number'], recovered.data['data']['order_number'])
        self.assertFalse(replay.data['data']['created'])
        counter.refresh_from_db()
        self.assertEqual(counter.last_value, sequence)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)
        self.assertEqual(TubeOutsourcingLine.objects.count(), 1)
        self.raw_balance.refresh_from_db()
        self.assertEqual(self.raw_balance.quantity, original_stock)
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(OutsourcingOrder.objects.count(), old_orders)
        legacy = self.client.get(f"/api/v1/outsourcing-orders/{data['id']}/", HTTP_HOST='localhost')
        self.assertEqual(legacy.status_code, 404)

    def test_changed_idempotent_request_conflicts_and_stale_new_request_is_412(self):
        payload = self.order_payload()
        self.post_order(payload)
        changed = copy.deepcopy(payload)
        changed['lines'][0]['quantity'] = '10'
        self.post_order(changed, 409)
        stale = copy.deepcopy(payload)
        stale['client_request_id'] = str(uuid.uuid4())
        self.post_order(stale, 412)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)

    def test_blank_rows_skip_and_invalid_or_split_rows_reject(self):
        for quantity in ['', '0', None, '-1', '1.5', 'NaN', True, '9' * 5000]:
            with self.subTest(quantity=str(quantity)[:20]):
                payload = self.order_payload(quantity=quantity)
                self.post_order(payload, 400)
        payload = self.order_payload()
        payload['lines'].append(dict(payload['lines'][0]))
        self.post_order(payload, 400)
        payload = self.order_payload()
        payload['lines'].append({'component_identity': str(uuid.uuid4()), 'quantity': ''})
        self.post_order(payload)
        self.assertEqual(TubeOutsourcingLine.objects.count(), 1)

    def test_raw_requires_whole_bar_and_maximum_and_known_component(self):
        for quantity in ['7', '99999999999999']:
            self.post_order(self.order_payload(quantity=quantity), 400)
        payload = self.order_payload()
        payload['lines'][0]['component_identity'] = str(uuid.uuid4())
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_inactive_zone_and_factory_without_current_craft_cannot_save(self):
        payload = self.order_payload()
        self.raw_zone.status = 'DISABLED'
        self.raw_zone.save(update_fields=['status'])
        self.post_order(payload, 400)
        self.raw_zone.status = 'ACTIVE'
        self.raw_zone.save(update_fields=['status'])
        OutsourcingFactoryCraft.objects.filter(factory=self.factory).delete()
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_feature_and_public_mode_gates(self):
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertEqual(self.client.get(BASE + 'options/', HTTP_HOST='localhost').status_code, 404)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            self.assertEqual(self.client.get(BASE + 'options/', HTTP_HOST='localhost').status_code, 409)

    def test_return_date_cannot_precede_dispatch_date(self):
        payload = self.order_payload()
        payload['expected_return_date'] = str(timezone.localdate() - timedelta(days=1))
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_invisible_task_and_missing_action_permission_are_rejected(self):
        payload = self.order_payload()
        outsider = get_user_model().objects.create_user(username='tube-outsider')
        Employee.objects.create(user=outsider, employee_code='TUBE-OUTSIDER', display_name='无任务范围')
        client = APIClient()
        client.force_authenticate(outsider)
        self.post_order(payload, 403, client=client)
        outsider.user_permissions.add(*Permission.objects.filter(content_type__app_label='outsourcing',
            codename__in=['view_outsourcingorder', 'add_outsourcingorder']))
        client.force_authenticate(get_user_model().objects.get(pk=outsider.pk))
        self.post_order(payload, 404, client=client)
        options = client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data['data']['tasks'], [])

    def test_metal_save_uses_report_minimum_without_changing_manual_source_completion(self):
        source_before = (self.source.completed_pieces, self.source.reserved_pieces, self.source.dispatched_pieces)
        self.post_order(self.order_payload('METAL', '7'))
        self.source.refresh_from_db()
        self.assertEqual(source_before, (self.source.completed_pieces, self.source.reserved_pieces, self.source.dispatched_pieces))
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '93')
        line = TubeOutsourcingLine.objects.get()
        self.assertIsNone(line.stock_quantity)

    def test_public_semi_allows_non_bar_quantity_without_consuming_metal_twice(self):
        self.receive(30)
        before = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        payload = self.order_payload('PUBLIC_SEMI', '7')
        self.post_order(payload)
        line = TubeOutsourcingLine.objects.get()
        self.assertEqual((line.quantity, line.stock_quantity), (7, 7))
        after = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        self.assertEqual(before, after)
        self.assertEqual(self.context('PUBLIC_SEMI')['rows'][0]['max_quantity'], '23')

    def test_raw_then_semi_then_metal_share_external_order_limit(self):
        self.receive(30)
        self.post_order(self.order_payload('RAW_PIPE', '110'))
        self.post_order(self.order_payload('PUBLIC_SEMI', '30'))
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '60')
        self.post_order(self.order_payload('METAL', '60'))
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '0')
        self.assertEqual(self.context('PUBLIC_SEMI')['rows'][0]['max_quantity'], '0')

    def test_semi_then_metal_then_raw_uses_original_allowance_once(self):
        self.receive(30)
        self.post_order(self.order_payload('PUBLIC_SEMI', '30'))
        self.post_order(self.order_payload('METAL', '70'))
        self.assertEqual(self.context('RAW_PIPE')['rows'][0]['max_quantity'], '110')
        self.post_order(self.order_payload('RAW_PIPE', '110'))
        self.assertEqual(self.context('RAW_PIPE')['rows'][0]['max_quantity'], '0')

    def test_two_components_may_use_different_factories_but_share_stock_pool(self):
        second = BomLine.objects.get(pk=self.metal_bom_line.pk)
        second.pk, second.component_identity, second.line_number = uuid.uuid4(), uuid.uuid4(), 2
        second.part_name = '后脚管'
        second.save(force_insert=True)
        factory = OutsourcingFactory.objects.get(pk=self.factory.pk)
        factory.pk, factory.factory_number, factory.name = uuid.uuid4(), 'TUBE-API-SECOND', '第二加工厂'
        factory.save(force_insert=True)
        OutsourcingFactoryCraft.objects.create(factory=factory, craft=self.spray, craft_name_snapshot=self.spray.name)
        debit_public_stock(balance_id=self.raw_balance.pk, quantity=87, source_type='TEST_D2_POOL_ADJUST',
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        payload = self.order_payload(quantity='20')
        payload['lines'].append({'component_identity': str(second.component_identity), 'quantity': '20',
                                'factory_id': str(factory.pk)})
        self.post_order(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        for row in payload['lines']:
            row['quantity'] = '10'
        self.post_order(payload)
        self.assertEqual(set(TubeOutsourcingLine.objects.values_list('factory_id', flat=True)),
                         {self.factory.pk, factory.pk})

    def test_saved_metal_reservation_blocks_removing_required_report_quantity(self):
        self.post_order(self.order_payload('METAL', '80'))
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=79)
                assert_tube_reports_cover_usage(self.product_line.pk)
        self.assertEqual(WorkReportLine.objects.get(work_item=self.items[0]).quantity, 100)

    def test_audit_failure_rolls_back_order_and_reservation(self):
        payload = self.order_payload()
        counters = list(DailyBusinessNumberCounter.objects.order_by('pk').values())
        with patch('apps.outsourcing.tube_services.write_audit_log', side_effect=RuntimeError('模拟审计故障')):
            with self.assertRaises(RuntimeError):
                self.post_order(payload)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        self.assertFalse(TubeOutsourcingLine.objects.exists())
        self.assertEqual(list(DailyBusinessNumberCounter.objects.order_by('pk').values()), counters)
        self.post_order(payload)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeOrdersConcurrencyTests(TubeApiFixture, TransactionTestCase):
    def test_factory_lock_allows_other_wf_order_foreign_key(self):
        payload = self.order_payload()

        def create():
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            return self.post_order(payload, client=client).data['data']['order_number']

        assert_reference_locks_allow_number_holder(self, create, [(OutsourcingFactory, self.factory.pk)])

    def concurrent_posts(self, payloads):
        barrier, results = threading.Barrier(len(payloads)), []

        def run(payload):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                barrier.wait(timeout=10)
                response = client.post(BASE, payload, format='json', HTTP_HOST='localhost')
                results.append(response.status_code)
            except Exception as error:
                results.append(repr(error))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(payload,)) for payload in payloads]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        return results

    def test_same_request_concurrently_creates_one_order(self):
        payload = self.order_payload()
        self.assertCountEqual(self.concurrent_posts([payload, copy.deepcopy(payload)]), [201, 200])
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)
        self.assertEqual(TubeOutsourcingLine.objects.count(), 1)

    def test_different_requests_cannot_reserve_same_version_twice(self):
        payload = self.order_payload('METAL', '80')
        other = copy.deepcopy(payload)
        other['client_request_id'] = str(uuid.uuid4())
        self.assertCountEqual(self.concurrent_posts([payload, other]), [201, 412])
        self.assertEqual(TubeOutsourcingLine.objects.get().quantity, 80)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TubeOrdersScopedPermissionsTests(access_fixture.ScopedActorMixin, TubeApiFixture, APITestCase):
    def test_craft_operator_can_save_without_production_task_read_permission(self):
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        self.grant('outsourcing.add_outsourcingorder', 'CRAFT', [self.spray])
        self.assertFalse(self.scope_user.has_perm('production_tasks.view_productiontask'))
        options = self.client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(len(options.data['data']['tasks']), 1)
        self.post_order(self.order_payload())

    def test_ungranted_spray_cannot_read_context_save_or_recover_saved_order(self):
        payload = self.order_payload()
        self.post_order(payload)
        unrelated = Craft.objects.create(craft_type='EXTERNAL', name='只授权车缝', outsourcing_code='SEWING')
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated])
        self.grant('outsourcing.add_outsourcingorder', 'CRAFT', [unrelated])
        options = self.client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data['data']['tasks'], [])
        self.assertEqual(options.data['data']['factories'], [])
        self.post_order(payload, 403)
        recovery = self.client.get(BASE + f"by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(recovery.status_code, 403, recovery.data)
        payload['client_request_id'] = str(uuid.uuid4())
        self.post_order(payload, 404)
