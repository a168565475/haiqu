"""管材加工价：按外发支数计价、旧单空价兼容及各读取入口保持一致。"""
import copy
import uuid
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine
from ..api.tube_serializers import TubeOrderWriteSerializer
from ..models import TubeOutsourcingLine, TubeOutsourcingOrder
from ..services import _json_hash
from .test_tube_materials_api import TubeMaterialFixture
from .test_plan_orders_api import PlanApiFixture
from .test_tube_receipts_api import TubeReceiptFixture


UNIFIED_URL = '/api/v1/unified-outsourcing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubePricesApiTests(TubeReceiptFixture, APITestCase):
    def set_unit_area(self, value):
        values = dict(self.metal_bom_line.raw_values or {})
        if value is None:
            values.pop('coating_unit_area_sqm', None)
        else:
            values['coating_unit_area_sqm'] = value
        self.metal_bom_line.raw_values = values
        self.metal_bom_line.save(update_fields=['raw_values'])

    def priced_payload(self, price='2.50'):
        payload = self.order_payload()
        payload['lines'][0]['unit_price'] = price
        return payload

    def assert_price(self, order, price='2.50', amount='50.00'):
        self.assertEqual(Decimal(order['lines'][0]['unit_price']), Decimal(price))
        self.assertEqual(Decimal(order['lines'][0]['planned_amount']), Decimal(amount))
        self.assertEqual(Decimal(order['planned_amount']), Decimal(amount))

    def test_create_detail_and_dispatch_use_pieces_not_stock_roots_or_meters(self):
        payload = self.priced_payload()
        order = self.post_order(payload).data['data']
        line = TubeOutsourcingLine.objects.get(order_id=order['id'])
        self.assertEqual((line.quantity, line.stock_quantity, line.unit_price),
                         (20, 2, Decimal('2.50')))
        self.assertEqual(Decimal(line.snapshot['meters']), Decimal('10.10'))
        self.assert_price(order)
        self.assert_price(self.detail(order).data['data'])
        dispatched = self.act(order).data['data']
        self.assert_price(dispatched)
        self.assertEqual(dispatched['status'], 'PROCESSING')
        self.assert_price(self.preview(dispatched)['order'])

    def test_source_context_exposes_positive_bom_unit_area(self):
        self.set_unit_area('0.1250')
        row = self.context()['rows'][0]
        self.assertEqual(row['unit_area_sqm'], '0.1250')

    def test_square_meter_price_freezes_area_and_calculates_amount(self):
        self.set_unit_area('0.1250')
        payload = self.priced_payload()
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        order = self.post_order(payload).data['data']
        line = TubeOutsourcingLine.objects.get(order_id=order['id'])
        self.assertEqual(line.price_unit, 'SQUARE_METER')
        self.assertEqual(line.unit_area_sqm, Decimal('0.1250'))
        self.assertEqual(order['lines'][0]['line_area_sqm'], '2.5000')
        self.assertEqual(order['lines'][0]['planned_amount'], '6.25')
        self.assertEqual(order['total_area_sqm'], '2.5000')
        self.assertEqual(order['planned_amount'], '6.25')

    def test_mixed_piece_and_square_meter_lines_sum_amount_and_area(self):
        self.set_unit_area('0.1250')
        second = BomLine.objects.get(pk=self.metal_bom_line.pk)
        second.pk, second.component_identity, second.line_number = uuid.uuid4(), uuid.uuid4(), 2
        second.part_name = '按支后脚管'
        second.raw_values = {**(second.raw_values or {}), 'coating_unit_area_sqm': '0.2500'}
        second.save(force_insert=True)
        payload = self.priced_payload()
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        payload['lines'].append({'component_identity': str(second.component_identity), 'quantity': '10',
                                 'factory_id': str(self.factory.pk), 'price_unit': 'PIECE',
                                 'unit_price': '3.00'})
        order = self.post_order(payload).data['data']
        rows = {row['component_identity']: row for row in order['lines']}
        self.assertEqual(rows[self.component]['planned_amount'], '6.25')
        self.assertEqual(rows[str(second.component_identity)]['planned_amount'], '30.00')
        self.assertEqual(order['total_area_sqm'], '5.0000')
        self.assertEqual(order['planned_amount'], '36.25')

    def test_missing_zero_or_invalid_area_rejects_square_meter_but_allows_piece(self):
        for value in [None, '0', '-0.1', 'abc', True]:
            with self.subTest(value=value):
                self.set_unit_area(value)
                payload = self.priced_payload()
                payload['lines'][0]['price_unit'] = 'SQUARE_METER'
                self.post_order(payload, 400)
        self.set_unit_area('abc')
        payload = self.priced_payload()
        payload['lines'][0]['price_unit'] = 'PIECE'
        order = self.post_order(payload).data['data']
        self.assertEqual(order['lines'][0]['price_unit'], 'PIECE')
        self.assertIsNone(order['lines'][0]['unit_area_sqm'])
        self.assertIsNone(order['total_area_sqm'])

    def test_legacy_missing_price_unit_remains_piece_and_area_unknown(self):
        self.set_unit_area('0.1250')
        order = self.post_order(self.priced_payload()).data['data']
        line = TubeOutsourcingLine.objects.get(order_id=order['id'])
        self.assertEqual(line.price_unit, 'PIECE')
        self.assertIsNone(line.unit_area_sqm)
        self.assertEqual(order['lines'][0]['price_unit'], 'PIECE')
        self.assertIsNone(order['lines'][0]['unit_area_sqm'])
        self.assertIsNone(order['total_area_sqm'])

    def test_changed_area_or_price_unit_conflicts_for_same_client_request(self):
        self.set_unit_area('0.1250')
        payload = self.priced_payload()
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        order = self.post_order(payload).data['data']
        changed = copy.deepcopy(payload)
        changed['lines'][0]['price_unit'] = 'PIECE'
        self.post_order(changed, 409)
        self.set_unit_area('0.2500')
        replay = self.post_order(payload, 200).data['data']
        self.assertEqual(replay['id'], order['id'])
        self.assertEqual(replay['lines'][0]['unit_area_sqm'], '0.1250')

    def test_saved_area_does_not_change_after_bom_edit(self):
        self.set_unit_area('0.1250')
        payload = self.priced_payload()
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        order = self.post_order(payload).data['data']
        self.set_unit_area('0.2500')
        detail = self.detail(order).data['data']
        self.assertEqual(detail['lines'][0]['unit_area_sqm'], '0.1250')
        self.assertEqual(detail['total_area_sqm'], '2.5000')

    def test_square_meter_rounding_matches_decimal_half_even(self):
        self.set_unit_area('0.0005')
        payload = self.order_payload('METAL', '10')
        payload['lines'][0]['unit_price'] = '1.00'
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        order = self.post_order(payload).data['data']
        self.assertEqual(order['lines'][0]['line_area_sqm'], '0.0050')
        self.assertEqual(order['lines'][0]['planned_amount'], '0.00')
        self.assertEqual(order['planned_amount'], '0.00')

    def test_cutting_source_rejects_square_meter_price_unit(self):
        payload = self.priced_payload()
        payload['source_kind'] = 'PUBLIC_CUTTING'
        payload['craft_id'] = str(uuid.uuid4())
        payload['lines'][0]['price_unit'] = 'SQUARE_METER'
        serializer = TubeOrderWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('lines', serializer.errors)

    def test_receipt_keeps_planned_amount_from_dispatched_quantity(self):
        order = self.post_order(self.priced_payload()).data['data']
        dispatched = self.act(order).data['data']
        payload = self.receipt_payload(dispatched, '18', '少回两支')
        receipt = self.receive_final(dispatched, payload).data['data']
        self.assertEqual(receipt['lines'][0]['received_quantity'], '18')
        self.assert_price(receipt)
        self.assert_price(self.receive_final(dispatched, payload, expected=200).data['data'])
        preview = self.preview(dispatched)
        self.assert_price(preview['order'])
        self.assert_price(preview['receipt'])
        self.assert_price(self.detail(order).data['data'])

    def test_zero_and_two_decimal_prices_are_accepted(self):
        for price in ['0', '0.00', '2.5', '2.50', '2.5000']:
            with self.subTest(price=price):
                order = self.post_order(self.priced_payload(price)).data['data']
                self.assert_price(order, price, str(20 * Decimal(price)))

    def test_negative_nonfinite_and_more_than_two_decimal_prices_are_rejected(self):
        for price in ['-0.01', '2.501', '0.0001', 'NaN', 'Infinity', True, '', ' ', '\t', 'abc',
                      '999999999999999.00', '1.00001']:
            with self.subTest(price=price):
                self.post_order(self.priced_payload(price), 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())
        self.assertFalse(TubeOutsourcingLine.objects.exists())

    def test_missing_price_keeps_legacy_payload_hash_and_returns_unknown_amount(self):
        payload = self.order_payload()
        serializer = TubeOrderWriteSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        legacy_data = copy.deepcopy(serializer.validated_data)
        for row in legacy_data['lines']:
            row.pop('unit_price', None)
        order = self.post_order(payload).data['data']
        saved = TubeOutsourcingOrder.objects.get(pk=order['id'])
        self.assertEqual(saved.request_payload_hash, _json_hash(legacy_data))
        self.assertIsNone(saved.lines.get().unit_price)
        self.assertIsNone(order['lines'][0]['unit_price'])
        self.assertIsNone(order['lines'][0]['planned_amount'])
        self.assertIsNone(order['planned_amount'])
        replay = self.post_order(payload, 200).data['data']
        self.assertEqual(replay['id'], order['id'])
        dispatched = self.act(order).data['data']
        self.assertIsNone(dispatched['planned_amount'])
        self.assertIsNone(self.preview(dispatched)['order']['planned_amount'])
        receipt = self.receive_final(dispatched, self.receipt_payload(dispatched, '20', '')).data['data']
        self.assertIsNone(receipt['lines'][0]['unit_price'])
        self.assertIsNone(receipt['lines'][0]['planned_amount'])
        self.assertIsNone(receipt['planned_amount'])

    def test_explicit_null_price_is_unknown_not_zero(self):
        order = self.post_order(self.priced_payload(None)).data['data']
        self.assertIsNone(order['lines'][0]['unit_price'])
        self.assertIsNone(order['lines'][0]['planned_amount'])
        self.assertIsNone(order['planned_amount'])

    def test_changed_price_conflicts_for_same_client_request(self):
        payload = self.priced_payload()
        order = self.post_order(payload).data['data']
        self.post_order(payload, 200)
        changed = copy.deepcopy(payload)
        changed['lines'][0]['unit_price'] = '2.51'
        self.post_order(changed, 409)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)
        self.assert_price(self.detail(order).data['data'])

    def test_any_unpriced_line_keeps_whole_order_total_unknown(self):
        second = BomLine.objects.get(pk=self.metal_bom_line.pk)
        second.pk, second.component_identity, second.line_number = uuid.uuid4(), uuid.uuid4(), 2
        second.part_name = '未录价后脚管'
        second.save(force_insert=True)
        payload = self.priced_payload()
        payload['lines'].append({'component_identity': str(second.component_identity), 'quantity': '10',
                                 'factory_id': str(self.factory.pk)})
        order = self.post_order(payload).data['data']
        self.assertIsNone(order['planned_amount'])
        priced = next(row for row in order['lines'] if row['component_identity'] == self.component)
        unknown = next(row for row in order['lines'] if row['component_identity'] == str(second.component_identity))
        self.assertEqual(Decimal(priced['planned_amount']), Decimal('50.00'))
        self.assertIsNone(unknown['unit_price'])
        self.assertIsNone(unknown['planned_amount'])
        dispatched = self.act(order).data['data']
        self.assertIsNone(dispatched['planned_amount'])
        self.assertIsNone(self.preview(dispatched)['order']['planned_amount'])
        receipt_payload = self.receipt_payload(dispatched, '0', '未回货，按本单结束')
        receipt = self.receive_final(dispatched, receipt_payload).data['data']
        self.assertIsNone(receipt['planned_amount'])

    def test_unified_list_reports_planned_price_for_tube_order(self):
        order = self.post_order(self.priced_payload()).data['data']
        response = self.client.get(UNIFIED_URL, {'factory_id': str(self.factory.pk)}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        row = next(item for item in response.data['data'] if item['id'] == order['id'])
        self.assertEqual(Decimal(row['planned_amount']), Decimal('50.00'))


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeHardwareFactoryListTests(TubeMaterialFixture, APITestCase):
    def test_unified_factory_filter_finds_factory_with_only_hardware(self):
        order = self.post_order(self.hardware_payload()).data['data']
        response = self.client.get(UNIFIED_URL, {'factory_id': str(self.hardware_factory.pk)}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        matching = [row for row in response.data['data'] if row['id'] == order['id']]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['factory_names'], [self.hardware_factory.name])
        self.assertEqual(matching[0]['factory_count'], 1)
        self.assertIsNone(matching[0]['planned_amount'])
        all_rows = self.client.get(UNIFIED_URL, HTTP_HOST='localhost')
        self.assertEqual(all_rows.status_code, 200, all_rows.data)
        row = next(item for item in all_rows.data['data'] if item['id'] == order['id'])
        self.assertCountEqual(row['factory_names'], [self.factory.name, self.hardware_factory.name])

    def test_unrelated_factory_filter_does_not_match_order(self):
        order = self.post_order(self.hardware_payload()).data['data']
        response = self.client.get(UNIFIED_URL, {'factory_id': str(uuid.uuid4())}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(order['id'], [row['id'] for row in response.data['data']])


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubePlanPriceApiTests(PlanApiFixture, APITestCase):
    def test_plan_dispatch_inherits_frozen_area_price_without_warehouse_override(self):
        values = dict(self.metal_bom_line.raw_values or {})
        values['coating_unit_area_sqm'] = '0.1250'
        self.metal_bom_line.raw_values = values
        self.metal_bom_line.save(update_fields=['raw_values'])
        context = self.plan_context('METAL')
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'METAL', 'zone_id': None,
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': '200',
                'factory_id': str(self.factory.pk), 'price_unit': 'SQUARE_METER', 'unit_price': '1.25'}]}
        plan = self.post_order(payload).data['data']
        dispatch = self.dispatch_payload('METAL', '100')
        dispatch['lines'][0].pop('unit_price')
        saved = self.write_plan(plan, 'dispatch', dispatch)
        batch = TubeOutsourcingOrder.objects.get(plan_id=plan['id'])
        line = batch.lines.get()
        self.assertEqual(line.price_unit, 'SQUARE_METER')
        self.assertEqual(line.unit_area_sqm, Decimal('0.1250'))
        self.assertEqual(line.unit_price, Decimal('1.25'))
        record_line = saved['dispatch_records'][0]['lines'][0]
        self.assertEqual(record_line['price_unit'], 'SQUARE_METER')
        self.assertEqual(record_line['unit_area_sqm'], '0.1250')
        self.assertEqual(record_line['line_area_sqm'], '12.5000')
        self.assertEqual(record_line['unit_price'], '1.25')
        self.assertEqual(record_line['planned_amount'], '15.62')
