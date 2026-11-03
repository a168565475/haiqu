"""创建总单填写委外需求，不受采购量限制；模拟外部依赖，不创建数据库。"""
from contextlib import ExitStack
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.outsourcing.plan_services import create_plan


class PlanCreatePurchaseLimitTests(SimpleTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.product = SimpleNamespace(pk=uuid4(), product_line_id=uuid4(), product_line=object(), schedule_id=uuid4())
        self.craft = SimpleNamespace(pk=uuid4())
        self.factory = SimpleNamespace(pk=uuid4(), name='加工厂')
        self.bom_line = SimpleNamespace(pk=uuid4())
        self.component = uuid4()
        self.request = SimpleNamespace(employee=object())
        self.context = {'ready': True, 'blockers': [], 'bom_id': str(uuid4()), 'source_revision': 'source',
            'rows': [{'component_identity': str(self.component), 'bom_line_id': str(self.bom_line.pk),
                      'part_name': '部件', 'order_required': '100', 'blockers': [], 'input_identity': {},
                      'snapshot': {'public_output_identity': {'id': 'output'}}}]}
        prefix = 'apps.outsourcing.plan_services.'
        for name in ['require_tube_feature', 'lock_request', 'lock_source_product', 'require_saved_order_access',
                     'validate_public_identity', 'write_audit_log']:
            self.stack.enter_context(patch(prefix + name))
        self.stack.enter_context(patch(prefix + '_json_hash', return_value='payload-hash'))
        self.source = self.stack.enter_context(patch(prefix + 'source_product', return_value=(self.product, self.craft)))
        self.stack.enter_context(patch(prefix + 'source_zone', return_value=None))
        self.stack.enter_context(patch(prefix + 'plan_source_context', return_value=self.context))
        boms = self.stack.enter_context(patch(prefix + 'Bom.objects'))
        boms.filter.return_value.order_by.return_value.select_for_update.return_value = []
        bom_lines = self.stack.enter_context(patch(prefix + 'BomLine.objects'))
        bom_lines.filter.return_value.select_related.return_value.order_by.return_value.select_for_update.return_value = [self.bom_line]
        self.stack.enter_context(patch(prefix + 'source_factories'))
        factories = self.stack.enter_context(patch(prefix + 'OutsourcingFactory.objects'))
        factories.filter.return_value.select_for_update.return_value = [self.factory]
        self.orders = self.stack.enter_context(patch(prefix + 'TubeOutsourcingOrder.objects'))
        self.orders.filter.return_value.first.return_value = None
        self.orders.filter.return_value.exclude.return_value.exists.return_value = False
        self.orders.create.return_value = SimpleNamespace(pk=uuid4(), order_number='WF-test')
        self.line_model = self.stack.enter_context(patch(prefix + 'TubeOutsourcingLine'))
        self.line_model.side_effect = lambda **values: SimpleNamespace(**values)
        self.stack.enter_context(patch(prefix + 'processing_line_fields', return_value={}))
        self.stack.enter_context(patch(prefix + 'next_business_number', return_value='WF-test'))
        self.stack.enter_context(patch('apps.wecom.workshop_notifications.outsourcing_created'))
        self.reference = self.stack.enter_context(patch(
            'apps.outsourcing.plan_purchase_reference.add_plan_purchase_reference'))

    def payload(self, quantity=240, source='METAL'):
        return {'client_request_id': uuid4(), 'schedule_product_id': self.product.pk, 'source_kind': source,
            'source_revision': 'source', 'planned_dispatch_date': '2026-11-02', 'expected_return_date': '2026-11-03',
            'lines': [{'component_identity': self.component, 'quantity': quantity,
                       'factory_id': self.factory.pk, 'unit_price': Decimal('1.25')}]}

    def submit(self, data):
        return create_plan.__wrapped__(data=data, request=self.request)

    def test_tube_and_cutting_can_create_demand_without_querying_or_freezing_purchase_reference(self):
        for source in ['METAL', 'SEWING']:
            with self.subTest(source=source):
                _, created = self.submit(self.payload(source=source))
                self.assertTrue(created)
                snapshot = self.orders.create.call_args.kwargs['source_snapshot']
                self.assertNotIn('purchase_reference', snapshot['rows'][0])
                self.assertEqual(snapshot['source_revision'], 'source')
                self.assertNotIn('purchase_reference', self.context['rows'][0])
                self.assertEqual(self.line_model.call_args.kwargs['quantity'], 240)
                self.reference.assert_not_called()

    def test_no_purchase_zero_unknown_and_less_than_demand_do_not_block_creation(self):
        for source in ['METAL', 'SEWING']:
            for limit in [None, '0', '239.0000']:
                with self.subTest(source=source, limit=limit):
                    self.reference.return_value = {'quantity': limit}
                    _, created = self.submit(self.payload(source=source))
                    self.assertTrue(created)
                    self.assertEqual(self.line_model.call_args.kwargs['quantity'], 240)
                    self.reference.assert_not_called()

    def test_original_successful_request_replays_without_recreating(self):
        existing = SimpleNamespace(is_plan=True, request_payload_hash='payload-hash')
        self.orders.filter.return_value.first.return_value = existing
        result, created = self.submit(self.payload())
        self.assertIs(result, existing)
        self.assertFalse(created)
        self.reference.assert_not_called()
        self.source.assert_not_called()
        self.orders.create.assert_not_called()
