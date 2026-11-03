"""仅在任务登记的隔离 PostgreSQL 测试库运行，不写共享业务库。"""
import copy
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.models import PublicStockMovement
from apps.inventory.public_stock_services import credit_public_stock, debit_public_stock
from apps.inventory.tube_processing_services import _usage
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderSemiFinishedRequirement
from apps.production_tasks.cost_selectors import _cost_sources
from ..models import TubeOutsourcingOrder, TubePlanReceipt, TubePlanRecordCorrection
from ..plan_correction_stock import DISPATCH_SOURCE, RECEIPT_SOURCE
from .test_plan_orders_api import PlanApiFixture
from .test_tube_orders_api import BASE


class CorrectionApiMixin:
    def correction_payload(self, order, kind='DISPATCH', *, operation='UPDATE', quantity=80, record=None):
        record = record or order['dispatch_records' if kind == 'DISPATCH' else 'receipt_records'][0]
        payload = {'client_request_id': str(uuid.uuid4()), 'record_kind': kind, 'record_id': record['id'], 'operation': operation}
        if operation == 'UPDATE':
            payload.update(business_date=str(timezone.localdate() - timedelta(days=1)),
                lines=[{'component_identity': row['component_identity'], 'quantity': str(quantity)} for row in record['lines']])
        return payload

    def correct(self, order, payload, expected=200, etag=None):
        response = self.client.post(BASE + order['id'] + '/plan-record-correction/', payload, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=etag or order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response.data['data'] if expected == 200 else response


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanRecordCorrectionTests(CorrectionApiMixin, PlanApiFixture, APITestCase):
    def dispatched(self, source='METAL', quantity='100'):
        order = self.plan(source)
        return self.write_plan(order, 'dispatch', self.dispatch_payload(source, quantity))

    def test_direct_update_keeps_identity_and_updates_usage_without_stock(self):
        order = self.plan(quantity='250')
        order = self.write_plan(order, 'dispatch', {**self.dispatch_payload(), 'remark': '原外发备注'})
        before = order['dispatch_records'][0]
        count = PublicStockMovement.objects.count()
        payload = self.correction_payload(order, quantity=250)
        changed = self.correct(order, payload)
        record = changed['dispatch_records'][0]
        self.assertEqual((record['id'], record['order_number']), (before['id'], before['order_number']))
        self.assertEqual(record['actual_dispatch_date'], payload['business_date'])
        self.assertEqual(changed['plan_summary']['dispatched_quantity'], '250')
        self.assertEqual(_usage(self.product_line.pk)[self.component]['dispatched'], 250)
        self.assertEqual(sum(line.quantity * line.unit_price for line in _cost_sources(self.task)['tube']), Decimal('312.50'))
        self.assertEqual(PublicStockMovement.objects.count(), count)
        self.assertEqual(TubeOutsourcingOrder.objects.get(pk=record['id']).remark, '原外发备注')
        deleted = self.correct(changed, self.correction_payload(changed, operation='DELETE'))
        self.assertEqual(deleted['dispatch_records'], [])
        self.assertEqual(deleted['plan_summary']['dispatched_quantity'], '0')
        self.assertEqual(deleted['status'], 'PENDING_DISPATCH')
        self.assertEqual(_usage(self.product_line.pk)[self.component]['dispatched'], 0)
        self.assertFalse(_cost_sources(self.task)['tube'].exists())
        self.assertTrue(TubeOutsourcingOrder.objects.filter(pk=record['id'], status='CANCELLED').exists())

    def test_dispatch_increase_cannot_exceed_entered_plan_quantity(self):
        order = self.dispatched()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='50'))
        record = next(row for row in order['dispatch_records'] if row['lines'][0]['quantity'] == '100')
        response = self.correct(order, self.correction_payload(order, quantity=151, record=record), expected=400)
        self.assertIn('委外总单填写的200支', str(response.data))
        self.assertFalse(TubePlanRecordCorrection.objects.exists())
        changed = self.correct(order, self.correction_payload(order, quantity=150, record=record))
        self.assertEqual(changed['plan_summary']['dispatched_quantity'], '200')

    def test_existing_over_plan_dispatch_can_be_reduced_and_deleted(self):
        order = self.dispatched()
        # 模拟本次规则启用前已经超量的记录，减量不必一次降到总单数量以内。
        TubeOutsourcingOrder.objects.get(pk=order['id']).lines.update(quantity=50)
        changed = self.correct(order, self.correction_payload(order, quantity=80))
        self.assertEqual(changed['plan_summary']['dispatched_quantity'], '80')
        self.correct(changed, self.correction_payload(changed, quantity=81), expected=400)
        deleted = self.correct(changed, self.correction_payload(changed, operation='DELETE'))
        self.assertEqual(deleted['plan_summary']['dispatched_quantity'], '0')

    def test_same_request_replay_precedes_old_etag_and_lookup_checks_parent(self):
        order = self.dispatched()
        payload = self.correction_payload(order)
        changed = self.correct(order, payload)
        replay = self.correct(order, payload)
        self.assertEqual(replay['record_correction'], changed['record_correction'])
        self.assertEqual(TubePlanRecordCorrection.objects.count(), 1)
        bad = copy.deepcopy(payload)
        bad['lines'][0]['quantity'] = '70'
        response = self.correct(changed, bad, expected=409)
        self.assertEqual(response.data['error']['code'], 'IDEMPOTENCY_CONFLICT')
        url = BASE + order['id'] + '/plan-record-correction-by-request/' + payload['client_request_id'] + '/'
        found = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(found.status_code, 200, found.data)
        self.assertEqual(found.data['data']['record_correction'], changed['record_correction'])
        self.assertEqual(self.client.get(url.replace(order['id'], str(uuid.uuid4())), HTTP_HOST='localhost').status_code, 404)
        self.correct(order, self.correction_payload(order), expected=412)

    def test_rejects_zero_partial_duplicate_added_fields_and_old_nonplan(self):
        order = self.dispatched()
        for patch_data in ({'lines': []}, {'lines': [{'component_identity': self.component, 'quantity': '0'}]},
                           {'factory_id': str(self.factory.pk)}, {'materials': []}):
            payload = self.correction_payload(order)
            payload.update(patch_data)
            self.correct(order, payload, expected=400)
        payload = self.correction_payload(order)
        payload['lines'].append(copy.deepcopy(payload['lines'][0]))
        self.correct(order, payload, expected=400)
        payload = self.correction_payload(order)
        payload['lines'][0]['component_identity'] = str(uuid.uuid4())
        self.correct(order, payload, expected=400)
        payload = self.correction_payload(order, operation='DELETE')
        payload['business_date'] = str(timezone.localdate())
        self.correct(order, payload, expected=400)
        payload = self.correction_payload(order)
        payload['record_id'] = order['id']
        self.correct(order, payload, expected=404)
        for invalid in ([], 'invalid'):
            self.correct(order, invalid, expected=400)
        for invalid in ('invalid', [], {'component_identity': self.component, 'quantity': '10', 'zone_id': str(self.semi_zone.pk)}):
            payload = self.correction_payload(order)
            payload['lines'] = [invalid]
            self.correct(order, payload, expected=400)
        batch_id = order['dispatch_records'][0]['id']
        response = self.client.post(BASE + batch_id + '/plan-record-correction/', self.correction_payload(order),
            format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TubePlanRecordCorrection.objects.exists())

    def test_dispatch_reduction_checks_component_receipt_but_not_batch_pairing(self):
        order = self.dispatched()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='100'))
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '150'))
        self.correct(order, self.correction_payload(order, operation='DELETE'), expected=400)
        changed = self.correct(order, self.correction_payload(order, quantity=50))
        self.assertEqual(changed['plan_summary']['dispatched_quantity'], '150')
        self.assertEqual(changed['plan_summary']['received_quantity'], '150')

    def test_raw_increase_decrease_delete_preserves_original_roots_meters_and_requirement(self):
        order = self.dispatched('RAW_PIPE', '20')
        batch = TubeOutsourcingOrder.objects.get(pk=order['dispatch_records'][0]['id'])
        line = batch.lines.get()
        original = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_DISPATCH', source_id=batch.pk)
        balance = original.balance
        self.requirement.refresh_from_db()
        issued = self.requirement.outsourcing_issued_quantity
        stock = balance.quantity
        original_data = (original.quantity, original.before_quantity, original.after_quantity, original.snapshot)
        self.assertNotEqual(self.requirement.unit_id, balance.unit_id)
        # 更正使用保存换算与身份，当前 BOM 后续变化不重解释历史记录。
        self.metal_bom_line.specification = '当前BOM另有改动'
        self.metal_bom_line.save(update_fields=['specification'])
        changed = self.correct(order, self.correction_payload(order, quantity=30))
        balance.refresh_from_db(); self.requirement.refresh_from_db()
        self.assertEqual(balance.quantity, stock - 1)
        self.assertEqual(balance.meter_quantity, balance.quantity * balance.raw_bar_length_m)
        self.assertEqual(self.requirement.outsourcing_issued_quantity, issued + 10)
        changed = self.correct(changed, self.correction_payload(changed, quantity=10))
        balance.refresh_from_db(); self.requirement.refresh_from_db(); line.refresh_from_db()
        self.assertEqual(balance.quantity, stock + 1)
        self.assertEqual(line.stock_quantity, 1)
        self.assertEqual(Decimal(line.snapshot['meters']), balance.raw_bar_length_m)
        self.assertEqual(self.requirement.outsourcing_issued_quantity, issued - 10)
        self.correct(changed, self.correction_payload(changed, quantity=11), expected=400)
        changed = self.correct(changed, self.correction_payload(changed, operation='DELETE'))
        balance.refresh_from_db(); self.requirement.refresh_from_db(); original.refresh_from_db()
        self.assertEqual(balance.quantity, stock + 2)
        self.assertEqual(self.requirement.outsourcing_issued_quantity, issued - 20)
        self.assertEqual((original.quantity, original.before_quantity, original.after_quantity, original.snapshot), original_data)
        self.assertEqual(PublicStockMovement.objects.filter(source_type=DISPATCH_SOURCE).count(), 3)

    def test_receipt_after_downstream_use_can_reduce_only_free_stock_and_keep_history(self):
        order = self.dispatched()
        order = self.write_plan(order, 'receipt', {**self.receipt_payload(order, '80'), 'remark': '原入库备注'})
        saved_record = order['receipt_records'][0]
        original = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        debit_public_stock(balance_id=original.balance_id, quantity=20, source_type='TEST_DOWNSTREAM',
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        changed = self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=50))
        original.balance.refresh_from_db(); original.refresh_from_db()
        self.assertEqual(original.balance.quantity, 30)
        self.assertEqual(original.quantity, 80)
        self.assertEqual(changed['receipt_records'][0]['remark'], '原入库备注')
        self.assertEqual(changed['receipt_records'][0]['id'], saved_record['id'])
        inventory = self.client.get('/api/v1/semi-finished-receipts/', {'direction': 'IN'}, HTTP_HOST='localhost')
        self.assertEqual(inventory.status_code, 200, inventory.data)
        historical = next(row for row in inventory.data['data']['items'] if row['id'] == str(original.pk))
        self.assertEqual(historical['receipt_date'], saved_record['receipt_date'])
        correction = PublicStockMovement.objects.get(source_type=RECEIPT_SOURCE)
        detail = self.client.get(f'/api/v1/semi-finished-receipts/{correction.pk}/', {'direction': 'OUT'}, HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['source_display'], '入库调整差额')
        self.assertEqual(detail.data['data']['source_detail']['source_number'], order['order_number'])
        self.assertTrue(detail.data['data']['source_detail']['is_plan'])
        self.correct(changed, self.correction_payload(changed, 'RECEIPT', operation='DELETE'), expected=409)
        credit_public_stock(identity=original.snapshot['public_identity'], zone=self.semi_zone, quantity=20,
            source_type='TEST_REPLENISH', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        deleted = self.correct(changed, self.correction_payload(changed, 'RECEIPT', operation='DELETE'))
        self.assertEqual(deleted['receipt_records'], [])
        self.assertEqual(deleted['plan_summary']['received_quantity'], '0')
        self.assertIsNotNone(TubePlanReceipt.objects.get(pk=saved_record['id']).voided_at)
        self.assertTrue(PublicStockMovement.objects.filter(pk=original.pk).exists())
        self.assertEqual(PublicStockMovement.objects.filter(source_type=RECEIPT_SOURCE).count(), 2)

    def test_receipt_increase_repeated_corrections_and_dispatch_limit(self):
        order = self.dispatched()
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '80'))
        changed = self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=100))
        changed = self.correct(changed, self.correction_payload(changed, 'RECEIPT', quantity=90))
        self.assertEqual(changed['plan_summary']['received_quantity'], '90')
        self.correct(changed, self.correction_payload(changed, 'RECEIPT', quantity=101), expected=400)
        self.assertEqual(TubePlanRecordCorrection.objects.count(), 2)

    def test_receipt_reduction_protects_pending_ordinary_public_issue(self):
        order = self.dispatched()
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '100'))
        original = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        extra_zone = self.make_zone('CORRECTION-SEMI-OTHER', 'SEMI_FINISHED')
        credit_public_stock(identity=original.snapshot['public_identity'], zone=extra_zone, quantity=20,
            source_type='CORRECTION_OTHER_ZONE', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        existing = MaterialIssue.objects.first()
        pending = MaterialIssue.objects.create(issue_number='CORRECTION-PENDING', stock_mode='PUBLIC_V2',
            status='PENDING_REVIEW', client_request_id=uuid.uuid4(), request_payload_hash='p' * 64,
            production_task=self.task, product_line=self.product_line, workshop=existing.workshop,
            recipient_workshop_employee=existing.recipient_workshop_employee,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        identity = original.snapshot['public_identity']
        requirement = OrderSemiFinishedRequirement.objects.create(production_task=self.task,
            product_line=self.product_line, component_identity=self.component, bom_line=self.metal_bom_line,
            completed_craft=self.spray, unit=self.piece_unit, required_quantity=200,
            identity_key=identity['identity_key'], identity_snapshot=identity['identity_snapshot'], source_revision_hash='r' * 64)
        MaterialIssueLine.objects.create(issue=pending, line_number=1, line_type='SEMI', unit=self.piece_unit, semi_requirement=requirement,
            requested_quantity=110, conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': original.snapshot['public_identity']})
        self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=80), expected=409)
        original.balance.refresh_from_db()
        self.assertEqual(original.balance.quantity, 100)
        self.assertFalse(TubePlanRecordCorrection.objects.exists())

    def test_failure_rolls_back_stock_and_receipt(self):
        order = self.dispatched()
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '80'))
        original = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        with patch('apps.outsourcing.plan_correction_services._update_plan', side_effect=RuntimeError('isolated rollback')):
            with self.assertRaises(RuntimeError):
                self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=70))
        original.balance.refresh_from_db()
        self.assertEqual(original.balance.quantity, 80)
        self.assertEqual(TubePlanReceipt.objects.get().lines.get().received_quantity, 80)
        self.assertFalse(TubePlanRecordCorrection.objects.exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type=RECEIPT_SOURCE).exists())

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
        SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_permission_is_specific_to_record_kind_for_post_and_recovery(self):
        order = self.dispatched()
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '50'))
        ScopedActorMixin.scoped_actor(self)
        ScopedActorMixin.grant(self, 'outsourcing.confirm_dispatch_outsourcingorder', 'CRAFT', [self.spray])
        self.correct(order, self.correction_payload(order, 'RECEIPT', quantity=40), expected=403)
        changed = self.correct(order, self.correction_payload(order, quantity=80))
        ScopedActorMixin.grant(self, 'outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        payload = self.correction_payload(changed, 'RECEIPT', quantity=40)
        changed = self.correct(changed, payload)
        response = self.client.get(BASE + order['id'] + '/plan-record-correction-by-request/' + payload['client_request_id'] + '/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
