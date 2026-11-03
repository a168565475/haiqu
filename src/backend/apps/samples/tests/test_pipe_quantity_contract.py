"""R2只核样品业务米与根制材料保存来源，不连接数据库。"""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from apps.samples.catalog_materials import freeze_sample_selection


class SamplePipeQuantityContractTests(SimpleTestCase):
    def saved(self, *, category='TUBE', unit='根'):
        return {'schema_version': 1, 'catalog_id': str(uuid4()), 'catalog_version': 'frozen',
            'category_key': category, 'template_key': category, 'name': '原管' if category == 'TUBE' else '五金',
            'scope': 'BASE', 'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '属性原文不作换算'} if category == 'TUBE' else {'specification': 'M8'},
            'unit_id': str(uuid4()), 'unit_name': unit, 'display_name': '保存原料'}

    def previous(self, selected):
        return {'key': 'line', 'category': 'tube' if selected['category_key'] == 'TUBE' else 'hardware',
            'material_catalog_id': selected['catalog_id'], 'material_selection_snapshot': selected,
            'quantity': '1', 'unitId': '', 'unitLabel': '米', 'pipeInputMode': 'TOTAL_METERS'}

    def test_root_material_snapshot_keeps_fractional_total_meter_demand(self):
        selected = self.saved()
        previous = self.previous(selected)
        row = {**deepcopy(previous), 'quantity': '1.25'}
        freeze_sample_selection(row, previous=previous, request=SimpleNamespace(), versions={})
        self.assertEqual(row['unitLabel'], '米')
        self.assertEqual(row['unitId'], '')
        self.assertEqual(row['pipeInputMode'], 'TOTAL_METERS')
        self.assertEqual(row['quantity'], '1.25')
        self.assertEqual(row['material_selection_snapshot'], selected)
        self.assertNotIn('raw_bar_length_m', row)

    def test_non_root_pipe_material_is_rejected(self):
        previous = self.previous(self.saved(unit='公斤'))
        with self.assertRaises(ValidationError):
            freeze_sample_selection(deepcopy(previous), previous=previous, request=SimpleNamespace(), versions={})

    def test_retired_catalog_quantity_is_not_silently_relabelled_to_meters(self):
        previous = self.previous(self.saved())
        previous.pop('pipeInputMode')
        previous['unitLabel'] = '根'
        row = deepcopy(previous)
        with self.assertRaises(ValidationError):
            freeze_sample_selection(row, previous=previous, request=SimpleNamespace(), versions={})
        self.assertEqual(row, previous)

    def test_other_material_still_uses_its_saved_unit(self):
        selected = self.saved(category='HARDWARE', unit='公斤')
        previous = self.previous(selected)
        row = {**deepcopy(previous), 'quantity': '1.25'}
        freeze_sample_selection(row, previous=previous, request=SimpleNamespace(), versions={})
        self.assertEqual(row['unitLabel'], '公斤')
        self.assertEqual(row['quantity'], '1.25')

    def test_catalog_pipe_procurement_keeps_original_meter_snapshot_fields(self):
        from apps.samples.pipe_materials import sample_pipe_snapshot
        selected = self.saved()
        row = {**self.previous(selected), 'quantity': '5', 'supplyQuantity': '3', 'shortageQuantity': '2'}
        snapshot = sample_pipe_snapshot(SimpleNamespace(pk=uuid4()), row)
        self.assertEqual(snapshot['required_meters'], '5')
        self.assertEqual(snapshot['supply_meters'], '3')
        self.assertEqual(snapshot['shortage_meters'], '2')
        self.assertEqual(snapshot['material_selection_snapshot'], selected)
        self.assertNotIn('raw_bar_length_m', snapshot)

    def test_catalog_pipe_arrival_must_match_saved_actual_roots_and_length(self):
        from apps.samples.pipe_materials import sample_pipe_snapshot, sample_pipe_arrival_quantity
        selected = self.saved()
        row = {**self.previous(selected), 'quantity': '5', 'supplyQuantity': '3', 'shortageQuantity': '2'}
        procurement = SimpleNamespace(pk=uuid4())
        line = SimpleNamespace(material_catalog_id=selected['catalog_id'], material_selection_snapshot=selected,
            measurement_kind='PIPE', source_unit_text_snapshot='米', raw_bar_length_m=Decimal('3'), accepted_bar_count=1,
            accepted_quantity=Decimal('3'), calculation_snapshot=sample_pipe_snapshot(procurement, row))
        self.assertEqual(sample_pipe_arrival_quantity(line, procurement, row), Decimal('3'))
        line.accepted_quantity = Decimal('4')
        with self.assertRaises(ValidationError):
            sample_pipe_arrival_quantity(line, procurement, row)

    def balance(self, selected):
        return SimpleNamespace(pk=uuid4(), material_catalog_id=selected['catalog_id'], raw_material_id=None,
            identity_snapshot={'material_selection_snapshot': selected}, quantity=Decimal('2'), raw_bar_length_m=Decimal('3'),
            unit=SimpleNamespace(unit_name='根'), zone=SimpleNamespace(zone_name='一区', warehouse=SimpleNamespace(warehouse_name='材料仓')))

    def test_catalog_warehouse_selected_one_actual_root_supplies_three_meters(self):
        from apps.samples.warehouse_stock import validate_allocations
        selected = self.saved()
        demand = {**self.previous(selected), 'name': '原管'}
        balance = self.balance(selected)
        with patch('apps.samples.warehouse_stock.stock_rows', return_value=('PUBLIC_V2', [(balance, Decimal('2'))])):
            result = validate_allocations(demand, [{'balanceId': str(balance.pk), 'stockMode': 'PUBLIC_V2', 'quantity': '1'}], Decimal('3'))
        self.assertEqual(result[0]['quantity'], '1')
        self.assertEqual(result[0]['rawBarLengthM'], '3')

    def test_catalog_stock_missing_actual_batch_length_is_not_guessed_from_attributes(self):
        from apps.core.api.exceptions import Conflict
        from apps.samples.warehouse_stock import stock_rows
        selected = self.saved()
        balance = self.balance(selected)
        balance.raw_bar_length_m = None
        query = MagicMock()
        query.select_related.return_value = query
        query.order_by.return_value = query
        query.__iter__.return_value = iter([balance])
        with patch('apps.inventory.catalog_stock_queries.available_catalog_balances', return_value=[{'balance_id': balance.pk, 'available_quantity': Decimal('2')}]), \
                patch('apps.samples.warehouse_stock.PublicStockBalance.objects.filter', return_value=query), \
                patch('apps.samples.warehouse_stock.reserved_quantity_for_balance', return_value=Decimal('0')):
            with self.assertRaises(Conflict):
                stock_rows(self.previous(selected))
