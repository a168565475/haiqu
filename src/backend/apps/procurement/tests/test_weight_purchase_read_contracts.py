"""重量采购只读口径契约；所有测试禁止数据库访问。"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.procurement.api.read_details import ReadDetailLineSerializer, ReadInboundLineSerializer
from apps.procurement.group_selectors import purchase_batch_display_status, purchase_group_completion_summary, purchase_group_progress
from apps.procurement.tracking_selectors import _bom_snapshot, arrival_rows


def related(items):
    return SimpleNamespace(all=lambda: items)


class WeightPurchaseReadContractTests(SimpleTestCase):
    def setUp(self):
        self.material_id, self.source_id, self.product_id, self.group_id = (uuid4() for _ in range(4))
        self.order = SimpleNamespace(pk=uuid4(), purchase_group_id=self.group_id, status='PURCHASING',
            archived_at=None, batch_request_id=uuid4(), production_task=SimpleNamespace(
                pk=uuid4(), task_number='WEIGHT-CONTRACT', archived_at=None), order_number='CG-WEIGHT', batch_number=1)
        self.line = SimpleNamespace(pk=uuid4(), purchase_order=self.order, purchase_order_id=self.order.pk,
            material_catalog_id=None, material_selection_snapshot={}, material_attributes_snapshot={},
            calculation_snapshot={'raw_material_id': str(self.material_id)}, source_unit_text='KG',
            source_bom_line_id_snapshot=self.source_id, product_line_id_snapshot=self.product_id,
            required_quantity=Decimal('100'), actual_purchase_quantity=Decimal('100'), actual_bar_count=50,
            raw_bar_length_m=Decimal('6'), raw_bar_weight_kg=Decimal('2'), section_type_snapshot='PROFILE',
            raw_material_snapshot='PIPE', material_snapshot='钢', part_name_snapshot='管材',
            product_name_snapshot='产品', specification_snapshot='', supplier_id=uuid4(),
            supplier_name_snapshot='供应商', delivery_date=date(2026, 12, 1))
        self.receipt = SimpleNamespace(inbound_id=uuid4(), inbound=SimpleNamespace(
            status='CONFIRMED', purchase_order_id=self.order.pk), source_unit_text_snapshot='KG',
            material_catalog_id=None, material_selection_snapshot={}, raw_material_information_id=self.material_id,
            accepted_quantity=Decimal('300'), return_quantity=Decimal('0'), accepted_bar_count=50,
            accepted_weight_kg=Decimal('60'), return_weight_kg=Decimal('0'), purchase_return_line=None)
        self.line.material_inbound_lines = related([self.receipt])
        self.order.lines = related([self.line])
        source = SimpleNamespace(pk=uuid4(), line_number=1, source_bom_line_id_snapshot=self.source_id,
            product_line_id_snapshot=self.product_id, required_quantity=Decimal('100'), source_unit_text='KG',
            compatibility_issues=[], source_snapshot={'section_type_snapshot': 'PROFILE',
                'calculation_snapshot': {'raw_material_id': str(self.material_id)}}, batch_lines=related([self.line]))
        self.group = SimpleNamespace(pk=self.group_id, compatibility_issues=[], lines=related([source]))

    def test_batch_does_not_compare_theoretical_meters_with_purchase_weight(self):
        self.assertEqual(purchase_batch_display_status(self.order), 'PURCHASING')
        self.receipt.accepted_weight_kg = Decimal('100')
        self.assertEqual(purchase_batch_display_status(self.order), 'COMPLETED')

    def test_batch_missing_weight_cannot_complete(self):
        self.receipt.accepted_weight_kg = None
        self.assertEqual(purchase_batch_display_status(self.order), 'PURCHASING')

    def test_batch_return_is_checked_in_kg(self):
        self.receipt.accepted_weight_kg = Decimal('100')
        self.receipt.return_weight_kg = Decimal('5')
        self.receipt.return_quantity = Decimal('18')
        self.receipt.purchase_return_line = SimpleNamespace(quantity=Decimal('5'), return_order=SimpleNamespace(
            purchase_order_id=self.order.pk, inbound_id=self.receipt.inbound_id, status='COMPLETED'))
        self.assertEqual(purchase_batch_display_status(self.order), 'COMPLETED')

    def test_group_progress_and_remaining_use_accepted_kg(self):
        result = purchase_group_progress(self.group)
        line = result['lines'][0]
        self.assertEqual(result['status'], 'PURCHASING')
        self.assertEqual(line['accepted_quantity'], Decimal('60'))
        self.assertEqual(line['in_progress_quantity'], Decimal('40'))
        self.assertEqual(line['progress_percent'], Decimal('60'))

    def test_group_missing_weight_is_unknown(self):
        self.receipt.accepted_weight_kg = None
        result = purchase_group_progress(self.group)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['lines'][0]['accepted_quantity'])
        self.assertIsNone(result['lines'][0]['in_progress_quantity'])

    def test_non_pipe_kg_material_keeps_original_quantity_fields(self):
        self.line.section_type_snapshot = 'ACCESSORY'
        self.group.lines.all()[0].source_snapshot['section_type_snapshot'] = 'ACCESSORY'
        self.receipt.accepted_weight_kg = None
        self.assertEqual(purchase_batch_display_status(self.order), 'COMPLETED')
        self.assertEqual(purchase_group_progress(self.group)['lines'][0]['accepted_quantity'], Decimal('300'))

    def test_read_detail_reports_weight_and_keeps_missing_weight_unknown(self):
        serializer = ReadDetailLineSerializer()
        self.assertEqual(serializer.get_accepted_quantity(self.line), '60')
        self.assertEqual(serializer.get_accepted_weight_kg(self.line), '60')
        self.receipt.accepted_weight_kg = None
        self.assertIsNone(serializer.get_accepted_quantity(self.line))
        self.assertIsNone(serializer.get_accepted_weight_kg(self.line))

    def test_group_completion_matches_return_weight(self):
        self.group.manual_completed_at = None
        self.group.batches = related([self.order])
        self.receipt.return_weight_kg = Decimal('5')
        self.receipt.return_quantity = Decimal('18')
        self.receipt.purchase_return_line = SimpleNamespace(quantity=Decimal('5'), return_order=SimpleNamespace(
            purchase_order_id=self.order.pk, inbound_id=self.receipt.inbound_id, status='COMPLETED'))
        self.assertTrue(purchase_group_completion_summary(self.group)['can_complete'])
        self.receipt.return_weight_kg = None
        self.assertFalse(purchase_group_completion_summary(self.group)['can_complete'])

    def tracking_row(self, *, missing_weight=False):
        queryset = MagicMock()
        queryset.filter.return_value = queryset
        queryset.select_related.return_value = queryset
        queryset.only.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.distinct.return_value = queryset
        queryset.__iter__.side_effect = lambda: iter([self.line])
        receipt = dict(source_unit_text_snapshot='KG', bad_owner=0, bad_selection=0,
            material_catalog_id=None, raw_material_information_id=self.material_id,
            measurement_kind='PIPE', raw_bar_length_m=Decimal('6'), bar_weight_kg=Decimal('2'),
            received=Decimal('300'), accepted=Decimal('300'), pending=Decimal('0'), returned=Decimal('0'),
            # 聚合总和可能有值，但其中一张入库缺重时仍须 UNKNOWN。
            received_weight=Decimal('60'), accepted_weight=Decimal('60'),
            pending_weight=Decimal('0'), returned_weight=Decimal('0'), missing_weight=int(missing_weight),
            return_pending_meter=0, return_pending_weight=0, missing_roots=0, received_roots=30)
        with patch('apps.procurement.tracking_selectors.PurchaseOrderLine.objects.filter', return_value=queryset), \
                patch('apps.procurement.tracking_selectors._materials', return_value=({}, {}, {})), \
                patch('apps.procurement.tracking_selectors._identity', return_value=(('raw', str(self.material_id)), [])), \
                patch('apps.procurement.tracking_selectors._receipt_summaries', return_value={self.line.pk: [receipt]}), \
                patch('apps.procurement.tracking_selectors.SupplierPurchaseSheet.objects.filter') as sheets:
            sheets.return_value.values.return_value = []
            return arrival_rows(today=date(2026, 12, 2))[0]

    def test_arrival_remaining_and_risk_use_kg(self):
        row = self.tracking_row()
        self.assertEqual(Decimal(row['received_quantity']), Decimal('60'))
        self.assertEqual(Decimal(row['unreceived_quantity']), Decimal('40'))
        self.assertEqual(row['unreceived_weight_kg'], row['unreceived_quantity'])
        self.assertEqual({risk['code'] for risk in row['risks']}, {'OVERDUE'})

    def test_missing_arrival_weight_is_unknown_without_meter_fallback(self):
        row = self.tracking_row(missing_weight=True)
        self.assertFalse(row['source_reliable'])
        self.assertIsNone(row['received_quantity'])
        self.assertIsNone(row['received_weight_kg'])
        self.assertIsNone(row['unreceived_quantity'])
        self.assertIn('ARRIVAL_UNKNOWN', {risk['code'] for risk in row['risks']})
        self.assertNotIn('ARRIVED', {risk['code'] for risk in row['risks']})

    def test_bom_weight_is_compared_to_roots_times_unit_weight(self):
        line = SimpleNamespace(section=SimpleNamespace(section_type='PROFILE', title='管材'),
            raw_values={'source_raw_material_id': str(self.material_id), 'long_material_unit_weight_kg': '2',
                        'long_material_total_weight_kg': '100'}, material_catalog_id=None,
            material_selection_snapshot={}, raw_material='PIPE', part_name='管材', material='',
            specification='', unit='根', raw_bar_length_m=Decimal('6'), suggested_bar_count=50,
            suggested_purchase_meters=Decimal('300'))
        plan = {'raw_bar_length_m': '6', 'suggested_bar_count': 50, 'suggested_purchase_meters': '300'}
        with patch('apps.procurement.tracking_selectors._identity', return_value=(('raw', str(self.material_id)), [])), \
                patch('apps.procurement.tracking_selectors.build_material_attribute_snapshot', return_value={}), \
                patch('apps.procurement.tracking_selectors.pipe_plan_for_line', return_value=plan):
            snapshot, _, notes = _bom_snapshot(line, None, ({}, {}, {}))
            self.assertEqual(snapshot['source_unit_text'], 'KG')
            self.assertEqual(snapshot['required_quantity'], Decimal('100'))
            self.assertEqual(notes, [])
            line.raw_values['long_material_total_weight_kg'] = '99'
            self.assertTrue(_bom_snapshot(line, None, ({}, {}, {}))[2])
            line.raw_values.pop('long_material_unit_weight_kg')
            snapshot, _, notes = _bom_snapshot(line, None, ({}, {}, {}))
            self.assertEqual(snapshot['source_unit_text'], 'KG')
            self.assertIsNone(snapshot['required_quantity'])
            self.assertTrue(notes)


class HardwareWeightReadContractTests(WeightPurchaseReadContractTests):
    """同一采购读契约覆盖五金：300 个只能算 60 KG 到货。"""
    def setUp(self):
        super().setUp()
        self.line.section_type_snapshot = 'ACCESSORY'
        self.line.calculation_snapshot['measurement_kind'] = 'HARDWARE_WEIGHT'
        self.line.raw_bar_length_m = self.line.raw_bar_weight_kg = self.line.actual_bar_count = None
        self.line.part_name_snapshot = '铆钉'
        source = self.group.lines.all()[0]
        source.source_snapshot['section_type_snapshot'] = 'ACCESSORY'
        source.source_snapshot['calculation_snapshot']['measurement_kind'] = 'HARDWARE_WEIGHT'

    def test_non_pipe_kg_material_keeps_original_quantity_fields(self):
        self.line.calculation_snapshot.pop('measurement_kind')
        self.group.lines.all()[0].source_snapshot['calculation_snapshot'].pop('measurement_kind')
        super().test_non_pipe_kg_material_keeps_original_quantity_fields()

    def test_inbound_history_preserves_reference_pieces_separate_from_kg(self):
        self.receipt.measurement_kind = 'OTHER'
        self.receipt.received_quantity = Decimal('320')
        self.receipt.calculation_snapshot = {'measurement_kind': 'HARDWARE_WEIGHT', 'piece_unit': '片'}
        serializer = ReadInboundLineSerializer()
        self.assertEqual(serializer.get_measurement_kind(self.receipt), 'HARDWARE_WEIGHT')
        self.assertEqual(serializer.get_piece_unit(self.receipt), '片')
        self.assertEqual(serializer.get_received_piece_count(self.receipt), '320')
        self.assertEqual(serializer.get_accepted_piece_count(self.receipt), '300')
        self.assertEqual(serializer.get_return_piece_count(self.receipt), '0')

