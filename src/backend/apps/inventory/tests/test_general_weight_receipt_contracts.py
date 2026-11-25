"""一般材料收发按根以及旧称重入库的契约。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.api.material_transfers import MaterialTransferLineInputSerializer
from apps.inventory.catalog_manual_receipts import resolve_manual_catalog
from apps.inventory.catalog_receipts import credit_catalog_inbound, validate_catalog_inbound
from apps.inventory.material_transfers import _resolve_catalog, _transfer_line_snapshot


class GeneralWeightReceiptContractTests(SimpleTestCase):
    def setUp(self):
        self.catalog_id = uuid4()
        self.saved = {'category_key': 'TUBE', 'processing_state': 'RAW', 'unit_name': '根',
                      'attributes': {}, 'name': '管材'}
        self.item = {'material_catalog_id': self.catalog_id, 'zone_id': uuid4(),
                     'material_selection': {'processing_state': 'RAW', 'attributes': {}}, 'raw_bar_count': 3,
                     'raw_bar_length_m': Decimal('6'), 'weight_quantity': Decimal('7.1000')}

    def apply_selection(self, projection, *args, **kwargs):
        projection.material_selection_snapshot = deepcopy(self.saved)
        projection.specification = ''

    def transfer_values(self, item):
        with patch('apps.inventory.material_transfers.MaterialCatalog.objects') as catalogs, \
                patch('apps.inventory.material_transfers.apply_catalog_selection', side_effect=self.apply_selection):
            catalogs.select_for_update.return_value.filter.return_value.first.return_value = SimpleNamespace(category_key='TUBE', base_warehouse_id=None)
            _resolve_catalog(item, request=None, versions={})
        return item

    def manual_values(self, item):
        with patch('apps.inventory.catalog_manual_receipts.MaterialCatalog.objects') as catalogs, \
                patch('apps.inventory.catalog_manual_receipts.apply_catalog_selection', side_effect=self.apply_selection), \
                patch('apps.inventory.catalog_manual_receipts.can_contribute', return_value=False):
            catalogs.filter.return_value.first.return_value = SimpleNamespace(category_key='TUBE')
            resolve_manual_catalog(item, request=None, versions={})
        return item

    def test_general_transfer_accepts_roots_and_length_without_weight(self):
        item = {key: value for key, value in self.item.items() if key != 'weight_quantity'}
        result = self.transfer_values(item)
        self.assertEqual(result['quantity'], Decimal('3'))
        self.assertEqual(result['raw_bar_length_m'], Decimal('6'))
        self.assertNotIn('weight_quantity', result)
        self.assertNotIn('bar_weight_kg', result)

    def test_general_transfer_rejects_weight_from_new_requests(self):
        with self.assertRaisesMessage(ValidationError, '管材收发请按根登记'):
            self.transfer_values(dict(self.item))

    def test_general_transfer_requires_roots_and_length(self):
        for missing in ('raw_bar_count', 'raw_bar_length_m'):
            item = {key: value for key, value in self.item.items() if key not in (missing, 'weight_quantity')}
            with self.subTest(missing=missing), self.assertRaisesMessage(ValidationError, '须填写根数和单根长度'):
                self.transfer_values(item)

    def test_non_pipe_rejects_extra_weight(self):
        self.saved.update(category_key='HARDWARE', unit_name='个')
        item = {key: value for key, value in self.item.items() if key not in ('raw_bar_count', 'raw_bar_length_m')}
        item['quantity'] = Decimal('3')
        with self.assertRaises(ValidationError):
            self.transfer_values(item)

    def test_manual_catalog_keeps_real_weight_and_compatibility_meters(self):
        item = dict(self.item)
        item['received_bar_count'] = item.pop('raw_bar_count')
        item['received_weight_kg'] = item.pop('weight_quantity')
        self.manual_values(item)
        self.assertEqual(item['received_quantity'], Decimal('18'))
        self.assertEqual(item['received_weight_kg'], Decimal('7.1'))
        self.assertEqual(item['calculation_snapshot']['measurement_unit'], 'kg')
        self.assertNotIn('raw_bar_weight_kg', item['calculation_snapshot'])

    def test_manual_catalog_does_not_invent_missing_weight(self):
        item = dict(self.item)
        item['received_bar_count'] = item.pop('raw_bar_count')
        item.pop('weight_quantity')
        with self.assertRaises(ValidationError):
            self.manual_values(item)

    def test_transfer_snapshot_exposes_nullable_weight(self):
        line = SimpleNamespace(line_key=uuid4(), material_catalog_id=self.catalog_id,
            material_selection_snapshot=self.saved, quantity=Decimal('3'), raw_bar_length_m=Decimal('6'),
            weight_quantity=Decimal('7.1'), zone_id=uuid4())
        self.assertEqual(_transfer_line_snapshot(line, SimpleNamespace(direction='IN'))['weight_quantity'], '7.1')
        line.weight_quantity = None
        self.assertIsNone(_transfer_line_snapshot(line, SimpleNamespace(direction='IN'))['weight_quantity'])

    def catalog_line(self):
        return SimpleNamespace(pk=uuid4(), inbound_id=uuid4(), material_catalog_id=self.catalog_id,
            material_selection_snapshot=self.saved, source_unit_text_snapshot='KG', purchase_order_line_id=None,
            purchase_order_line=None, received_weight_kg=Decimal('7.1'), accepted_weight_kg=Decimal('7.1'),
            return_weight_kg=Decimal('0'), bar_weight_kg=None, raw_bar_length_m=Decimal('6'),
            measurement_kind='PIPE', calculation_snapshot={}, accepted_bar_count=3, accepted_quantity=Decimal('18'),
            zone=SimpleNamespace(status='ACTIVE', warehouse=SimpleNamespace(status='ACTIVE', warehouse_type='MATERIAL')),
            inbound=SimpleNamespace(inbound_number='RK-WEIGHT'), purchase_order_number_snapshot='')

    def test_catalog_manual_weight_does_not_require_bom_standard_weight(self):
        line = self.catalog_line()
        with patch('apps.inventory.catalog_receipts.validate_saved_material', return_value=self.saved), \
                patch('apps.inventory.catalog_receipts.build_catalog_stock_identity', return_value={'key': 'identity'}):
            self.assertEqual(validate_catalog_inbound(line), {'key': 'identity'})
            line.accepted_weight_kg = None
            with self.assertRaises(ValidationError):
                validate_catalog_inbound(line)

    def test_catalog_credit_passes_actual_weight_without_standard_weight(self):
        line = self.catalog_line()
        with patch('apps.inventory.catalog_receipts.validate_catalog_inbound', return_value={'key': 'identity'}), \
                patch('apps.inventory.models.MaterialInbound.objects') as inbounds, \
                patch('apps.inventory.public_stock_services.credit_public_stock') as credit:
            inbounds.select_for_update.return_value.filter.return_value.exists.return_value = True
            credit_catalog_inbound.__wrapped__(line=line, actor_employee=None)
        self.assertEqual(credit.call_args.kwargs['quantity'], 3)
        self.assertEqual(credit.call_args.kwargs['weight_quantity'], Decimal('7.1'))
        self.assertIsNone(credit.call_args.kwargs['bar_weight_kg'])

    def test_transfer_serializer_keeps_weight_and_rejects_invalid_values(self):
        item = {**self.item, 'material_selection': {'catalog_version': '2026-11-07T00:00:00Z',
                'scope': 'BASE', 'processing_state': 'RAW', 'unit_name': '根', 'attributes': {'length': '6000'}}}
        serializer = MaterialTransferLineInputSerializer(data=item)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['weight_quantity'], Decimal('7.1'))
        for weight in ('0', '-1', 'NaN', '7.10001'):
            serializer = MaterialTransferLineInputSerializer(data={**item, 'weight_quantity': weight})
            self.assertFalse(serializer.is_valid())

