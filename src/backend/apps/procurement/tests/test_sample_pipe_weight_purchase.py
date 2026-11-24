"""打样采购按 KG 计价，原米数需求与采购手填参数分别冻结。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.inventory.material_flow_reset import pipe_reset_values
from apps.material_catalog.models import MaterialCatalog
from apps.procurement.api.serializers import PurchaseOrderUpdateLineSerializer
from apps.procurement.models import PurchaseOrderLine
from apps.procurement.pipe_purchase import purchase_pipe_values, sample_weight_source_snapshot
from apps.procurement.services import _purchase_order_confirmation_errors
from . import test_sample_pipe_flow as pipe_fixture
from . import test_sample_purchase_api as sample_fixture


class SamplePipeWeightValueTests(SimpleTestCase):
    def setUp(self):
        self.demand = {'schema_version': 3, 'source': 'SAMPLE', 'measurement_kind': 'PIPE',
                       'required_meters': '12.5', 'supply_meters': '0', 'shortage_meters': '12.5'}
        self.snapshot = sample_weight_source_snapshot(self.demand, '米')

    def test_suggested_weight_uses_whole_bars_and_actual_weight_ceil_does_not_change_price_quantity(self):
        values = purchase_pipe_values(self.snapshot, {'raw_bar_length_m': '6', 'raw_bar_weight_kg': '2.5',
                                                       'actual_purchase_quantity': '5.0001'})
        self.assertEqual((values['suggested_bar_count'], values['suggested_purchase_weight_kg']), (3, Decimal('7.5')))
        self.assertEqual((values['actual_bar_count'], values['actual_purchase_weight_kg'], values['actual_purchase_meters']),
                         (3, Decimal('5.0001'), Decimal('18')))
        self.assertEqual(values['calculation_snapshot']['sample_demand_snapshot'], self.demand)
        self.assertIsNone(self.snapshot['raw_bar_weight_kg'])

    def test_partial_draft_keeps_entered_parameters_and_later_edit_inherits_them(self):
        first = purchase_pipe_values(self.snapshot, {'raw_bar_weight_kg': '2.5', 'actual_purchase_quantity': '5.0001'})
        self.assertIsNone(first['suggested_purchase_weight_kg'])
        self.assertIsNone(first['actual_purchase_weight_kg'])
        self.assertEqual(first['calculation_snapshot']['raw_bar_weight_kg'], '2.5000')
        complete = purchase_pipe_values(first['calculation_snapshot'], {'raw_bar_length_m': '6'})
        self.assertEqual((complete['actual_bar_count'], complete['actual_purchase_weight_kg']), (3, Decimal('5.0001')))
        cleared = purchase_pipe_values(complete['calculation_snapshot'], {'raw_bar_weight_kg': None})
        self.assertIsNone(cleared['actual_bar_count'])
        self.assertIsNone(cleared['calculation_snapshot']['raw_bar_weight_kg'])

    def test_invalid_weight_parameters_and_legacy_root_only_input_are_rejected(self):
        valid = {'raw_bar_length_m': '6', 'raw_bar_weight_kg': '2.5', 'actual_purchase_quantity': '5'}
        for field in valid:
            for value in ('0', '-1', 'NaN', 'Infinity', 'bad'):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    purchase_pipe_values(self.snapshot, {**valid, field: value})
        with self.assertRaises(ValidationError):
            purchase_pipe_values(self.snapshot, {'actual_bar_count': 2, 'raw_bar_length_m': 6})
        with self.assertRaises(ValidationError):
            purchase_pipe_values(self.snapshot, {**valid, 'actual_bar_count': 3})

    def test_update_serializer_distinguishes_omitted_parameter_from_clear(self):
        serializer = PurchaseOrderUpdateLineSerializer(data={'id': str(uuid4()), 'unit_price': '3'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        for field in ('raw_bar_length_m', 'raw_bar_weight_kg', 'actual_purchase_quantity'):
            self.assertNotIn(field, serializer.validated_data)

    def test_non_pipe_kg_confirmation_does_not_require_bar_weight(self):
        line = SimpleNamespace(calculation_snapshot={}, section_type_snapshot='HARDWARE', source_unit_text='KG',
            raw_bar_length_m=None, line_number=1, actual_purchase_quantity=Decimal('2.5'), supplier_id=uuid4(),
            delivery_date=timezone.localdate(), unit_price=Decimal('2'), amount=Decimal('5'))
        with patch('apps.procurement.services.validate_pipe_purchase_source'):
            self.assertEqual(_purchase_order_confirmation_errors(SimpleNamespace(currency_code_snapshot='CNY'), [line]), [])

    def test_sample_reset_keeps_manual_unit_weight_and_clears_actual_weight(self):
        snapshot = purchase_pipe_values(self.snapshot, {'raw_bar_length_m': '6', 'raw_bar_weight_kg': '2.5',
            'actual_purchase_quantity': '5.0001'})['calculation_snapshot']
        key = uuid4()
        line = SimpleNamespace(source_unit_text='KG', calculation_snapshot=snapshot,
            raw_bar_length_m=Decimal('6'), raw_bar_weight_kg=Decimal('2.5'), purchase_order=SimpleNamespace(source_type='SAMPLE'),
            sample_material_source=SimpleNamespace(line_key=key, procurement_request=SimpleNamespace(lines=[{'key': str(key), 'unitLabel': '米'}])))
        with patch('apps.samples.pipe_materials.sample_pipe_snapshot', return_value=self.demand):
            values, warning = pipe_reset_values(line)
        self.assertFalse(warning)
        self.assertEqual((values['source_unit_text'], values['required_quantity'], values['raw_bar_weight_kg']), ('KG', Decimal('7.5'), Decimal('2.5')))
        self.assertIsNone(values['actual_purchase_weight_kg'])
        self.assertIsNone(values['calculation_snapshot']['actual_purchase_weight_kg'])

    def test_bom_weight_reset_does_not_restore_meter_requirement(self):
        line = SimpleNamespace(source_unit_text='KG', calculation_snapshot={}, purchase_order=SimpleNamespace(source_type='PRODUCTION'),
            bom_line_id=uuid4(), bom_line=SimpleNamespace(section=SimpleNamespace(section_type='PROFILE')))
        snapshot = {'measurement_unit': 'kg', 'raw_bar_length_m': '6', 'raw_bar_weight_kg': '2.5',
                    'suggested_bar_count': 3, 'suggested_purchase_meters': '18', 'suggested_purchase_weight_kg': '7.5'}
        with patch('apps.procurement.reset_sources.validate_purchase_description'), patch('apps.procurement.pipe_purchase.pipe_source_snapshot', return_value=snapshot):
            values, warning = pipe_reset_values(line)
        self.assertFalse(warning)
        self.assertEqual((values['source_unit_text'], values['required_quantity']), ('KG', '7.5'))
        self.assertIsNone(values['actual_purchase_weight_kg'])

    def test_refresh_reset_sample_keeps_basis_and_compares_original_demand(self):
        from apps.procurement.reset_sources import refresh_reset_purchase_source
        key = uuid4()
        snapshot = purchase_pipe_values(self.snapshot, {'raw_bar_weight_kg': '2.5'})['calculation_snapshot']
        line = SimpleNamespace(source_unit_text='KG', calculation_snapshot={**snapshot, 'requires_source_confirmation': True},
            raw_bar_length_m=None, raw_bar_weight_kg=None, actual_purchase_quantity=None, quantity_difference_reason='',
            purchase_order=SimpleNamespace(source_type='SAMPLE', status='DRAFT'),
            sample_material_source=SimpleNamespace(line_key=key, procurement_request=SimpleNamespace(lines=[{'key': str(key), 'unitLabel': '米'}])))
        with patch('apps.samples.pipe_materials.sample_pipe_snapshot', return_value=self.demand), patch('apps.procurement.pipe_purchase.validate_pipe_purchase_source'):
            refresh_reset_purchase_source(line)
        self.assertEqual(line.calculation_snapshot['raw_bar_weight_kg'], '2.5000')
        self.assertEqual(line.calculation_snapshot['sample_demand_snapshot'], self.demand)
        self.assertNotIn('requires_source_confirmation', line.calculation_snapshot)
        self.assertIsNone(line.required_quantity)


class SamplePipeWeightPurchaseApiTests(APITestCase):
    def setUp(self):
        pipe_fixture.SamplePipeFlowTests.setUp(self)
        self.demand.pop('cuttingLengthMm')
        self.demand.pop('piecesPerBar')
        self.demand.update(pipeInputMode='TOTAL_METERS', quantity='12.5', supplyQuantity='0', shortageQuantity='12.5', unitLabel='米')
        self.save_demand()

    def save_demand(self):
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '0'}], 'notes': ''}
        record.save(update_fields=['draft', 'warehouse_draft'])

    def source(self):
        result = self.client.get(self.root + 'source/', {'sample_procurement_request_id': str(self.procurement.pk)})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data['data']['can_create'], result.data)
        return result.data['data']

    def create(self, **values):
        source = self.source()
        self.assertEqual(source['lines'][0]['source_unit_text'], 'KG')
        self.assertEqual(source['lines'][0]['sample_demand_unit'], '米')
        self.assertIsNone(source['lines'][0]['required_quantity'])
        result = self.client.post(self.root, {'source_type': 'SAMPLE', 'sample_procurement_request_id': str(self.procurement.pk),
            'source_revision': source['source_revision'], 'currency_id': str(self.currency.pk),
            'lines': [{'sample_line_key': self.key, 'supplier_id': str(self.supplier.pk),
                       'delivery_date': str(timezone.localdate()), 'unit_price': '2', **values}]}, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        self.order_id = result.data['data']['id']
        self.purchase_line = PurchaseOrderLine.objects.get(purchase_order_id=self.order_id)
        return result

    def edit(self, detail, **values):
        result = self.client.patch(self.root + self.order_id + '/', {'lines': [{'id': str(self.purchase_line.pk),
            'supplier_id': str(self.supplier.pk), 'delivery_date': str(timezone.localdate()), 'unit_price': '3', **values}]},
            format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        self.purchase_line.refresh_from_db()
        return result

    def test_partial_draft_reopen_edit_and_confirm_keep_demand_and_weight_separate(self):
        created = self.create(raw_bar_weight_kg='2.5', actual_purchase_quantity='5.0001')
        row = created.data['data']['lines'][0]
        self.assertIsNone(row['required_quantity'])
        self.assertIsNone(row['actual_purchase_quantity'])
        self.assertEqual(row['calculation_snapshot']['actual_purchase_weight_kg'], '5.0001')
        self.assertEqual(self.client.post(self.root + self.order_id + '/confirm/', {}, format='json').status_code, 400)
        reopened = self.client.get(self.root + self.order_id + '/')
        edited = self.edit(reopened, raw_bar_length_m='6')
        line = self.purchase_line
        self.assertEqual((line.required_quantity, line.actual_purchase_quantity, line.actual_bar_count, line.amount),
                         (Decimal('7.5'), Decimal('5.0001'), 3, Decimal('15.0003')))
        self.assertEqual((line.sample_demand_quantity, line.sample_supply_quantity), (Decimal('12.5'), 0))
        self.assertEqual(edited.data['data']['lines'][0]['sample_demand_unit'], '米')
        edited = self.edit(edited, raw_bar_weight_kg='3')
        self.assertEqual((self.purchase_line.required_quantity, self.purchase_line.actual_bar_count), (Decimal('9'), 2))
        confirmed = self.client.post(self.root + self.order_id + '/confirm/', {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def test_saved_kg_print_is_frozen_and_source_change_blocks_confirmation(self):
        self.create(raw_bar_length_m='6', raw_bar_weight_kg='2.5', actual_purchase_quantity='5.0001')
        self.procurement.lines[0]['shortageQuantity'] = '13'
        self.procurement.lines[0]['quantity'] = '13'
        self.procurement.save(update_fields=['lines'])
        blocked = self.client.post(self.root + self.order_id + '/confirm/', {}, format='json')
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.procurement.lines[0]['shortageQuantity'] = '12.5'
        self.procurement.lines[0]['quantity'] = '12.5'
        self.procurement.save(update_fields=['lines'])
        confirmed = self.client.post(self.root + self.order_id + '/confirm/', {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        options = self.client.get(self.root + self.order_id + '/sheet-options/').data['data']
        sheets = self.client.post(self.root + self.order_id + '/generate-sheets/', {'assignments': [
            {'supplier_id': str(self.supplier.pk), 'template_version_id': options['templates'][0]['version_id']}]}, format='json')
        self.assertEqual(sheets.status_code, 201, sheets.data)
        sheet = self.client.get('/api/v1/supplier-purchase-sheets/' + sheets.data['data'][0]['id'] + '/')
        row = sheet.data['data']['content_snapshot']['lines'][0]
        self.assertEqual((row['unit'], row['price_unit'], row['actual_purchase_weight_kg']), ('kg', '元/kg', '5.0001'))
        self.assertEqual(Decimal(row['amount']), Decimal('10.0002'))


class SampleCatalogPipeWeightPurchaseApiTests(SamplePipeWeightPurchaseApiTests):
    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='打样目录管材')
        self.saved = {'schema_version': 1, 'catalog_id': str(self.catalog.pk), 'catalog_version': self.catalog.updated_at.isoformat(),
            'category_key': 'TUBE', 'template_key': 'TUBE', 'name': self.catalog.name, 'scope': 'BASE', 'processing_state': 'RAW',
            'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '铁', 'shape': '圆管', 'section_size': '20', 'thickness': '1'},
            'unit_id': str(self.raw_material.unit_id), 'unit_name': '根', 'display_name': '打样目录管材 / 根'}
        self.demand.pop('rawMaterialId')
        self.demand.update(material_catalog_id=str(self.catalog.pk), material_selection_snapshot=deepcopy(self.saved))
        self.save_demand()


class OrdinaryKgSamplePurchaseApiTests(APITestCase):
    purchase_payload = sample_fixture.SamplePurchaseApiTests.purchase_payload
    create_order = sample_fixture.SamplePurchaseApiTests.create_order

    def setUp(self):
        sample_fixture.SamplePurchaseApiTests.setUp(self)

    def test_non_pipe_kg_purchase_confirms_without_pipe_parameters(self):
        from apps.reference_data.models import ProductionUnit
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='KG', defaults={'unit_code': 'SAMPLEKG'})
        self.raw_material.unit = unit
        self.raw_material.save(update_fields=['unit'])
        self.demand['unitLabel'] = 'KG'
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        self.create_order()
        response = self.client.post(self.root + self.sample_order_id + '/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.purchase_line.refresh_from_db()
        self.assertEqual((self.purchase_line.source_unit_text, self.purchase_line.actual_purchase_quantity), ('KG', Decimal('4')))
        self.assertIsNone(self.purchase_line.raw_bar_weight_kg)
