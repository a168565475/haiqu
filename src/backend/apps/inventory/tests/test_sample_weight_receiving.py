from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.inventory.api.serializers import SampleMaterialInboundLineInputSerializer
from apps.inventory.models import MaterialInboundLine, MaterialStockBalance, PublicStockBalance
from apps.inventory.sample_receiving_services import _matches_receipt, _sample_receipt_row
from apps.samples.models import SampleMaterialArrival
from apps.samples.pipe_materials import sample_pipe_arrival_quantity
from apps.samples.sample_issue_stock import debit_pipe_plan
from apps.procurement.tests import test_sample_pipe_flow as pipe_fixture
from apps.procurement.tests import test_sample_purchase_api as purchase_fixture
from .test_sample_receiving import SampleReceivingHelpers


class SampleWeightReceivingContractTests(SimpleTestCase):
    def setUp(self):
        self.line = SimpleNamespace(section_type_snapshot='PROFILE', source_unit_text='KG',
            raw_bar_weight_kg=Decimal('2.5'), raw_bar_length_m=Decimal('6'))

    def test_full_weight_defaults_to_ceiling_roots_and_accepts_checked_roots(self):
        for item, roots in (({}, 2), ({'received_weight_kg': Decimal('4.1'), 'received_bar_count': 3}, 3)):
            row = _sample_receipt_row(line=self.line, item=item, remaining=Decimal('4.1'))
            self.assertEqual((row['received_weight_kg'], row['received_bar_count'], row['raw_bar_length_m']),
                             (Decimal('4.1'), roots, Decimal('6')))

    def test_sample_weight_must_match_full_remaining_weight(self):
        for weight in ('3.9', '4.2'):
            with self.subTest(weight=weight), self.assertRaises(ValidationError):
                _sample_receipt_row(line=self.line, item={'received_weight_kg': Decimal(weight)}, remaining=Decimal('4.1'))

    def test_checked_roots_must_be_positive_whole_numbers(self):
        for roots in (0, -1, Decimal('1.5')):
            with self.subTest(roots=roots), self.assertRaises(ValidationError):
                _sample_receipt_row(line=self.line, item={'received_bar_count': roots}, remaining=Decimal('4.1'))

    def test_old_meter_receipt_keeps_original_full_receipt_and_rejects_weight_fields(self):
        self.line.source_unit_text = '米'
        row = _sample_receipt_row(line=self.line, item={}, remaining=Decimal('12'))
        self.assertEqual(row['received_bar_count'], 2)
        self.assertNotIn('received_weight_kg', row)
        with self.assertRaises(ValidationError):
            _sample_receipt_row(line=self.line, item={'received_weight_kg': Decimal('4.1')}, remaining=Decimal('12'))

    def test_serializer_accepts_weight_and_checked_roots_but_never_meters(self):
        payload = {'purchase_order_line_id': str(uuid4()), 'zone_id': str(uuid4()),
                   'received_weight_kg': '4.1', 'received_bar_count': 3}
        self.assertTrue(SampleMaterialInboundLineInputSerializer(data=payload).is_valid())
        self.assertFalse(SampleMaterialInboundLineInputSerializer(data={**payload, 'received_quantity': '18'}).is_valid())
        self.assertFalse(SampleMaterialInboundLineInputSerializer(data={**payload, 'raw_bar_length_m': '6'}).is_valid())

    def test_replay_rejects_changed_weight_or_checked_roots(self):
        line_id, zone_id, order_id = uuid4(), uuid4(), uuid4()
        line = SimpleNamespace(purchase_order_line_id=line_id, zone_id=zone_id, location_id=None, remark='',
            measurement_kind='PIPE', source_unit_text_snapshot='KG', received_weight_kg=Decimal('4.1'),
            bar_weight_kg=Decimal('2.5'), received_bar_count=3)
        inbound = SimpleNamespace(purchase_order_id=order_id, status='CONFIRMED', quality_confirmed_at=None,
            inbound_date='2026-11-07', remark='', lines=SimpleNamespace(all=lambda: [line]))
        item = {'purchase_order_line_id': line_id, 'zone_id': zone_id, 'received_weight_kg': Decimal('4.1'), 'received_bar_count': 3}
        def matches(row):
            return _matches_receipt(inbound, purchase_order_id=order_id, inbound_date='2026-11-07', remark='', items=[row])
        self.assertTrue(matches(item))
        self.assertFalse(matches({**item, 'received_weight_kg': Decimal('4.2')}))
        self.assertFalse(matches({**item, 'received_bar_count': 4}))


class SampleWeightArrivalContractTests(SimpleTestCase):
    def setUp(self):
        self.material_id = uuid4()
        self.snapshot = {'raw_material_id': str(self.material_id), 'pieces_per_bar': 6}
        self.row = {'category': 'tube', 'pipeInputMode': 'TOTAL_METERS'}
        self.line = SimpleNamespace(measurement_kind='PIPE', source_unit_text_snapshot='KG',
            raw_material_information_id=self.material_id, raw_bar_length_m=Decimal('6'), accepted_bar_count=3,
            accepted_quantity=Decimal('18'), received_weight_kg=Decimal('4.1'), accepted_weight_kg=Decimal('4.1'),
            return_weight_kg=Decimal('0'), bar_weight_kg=Decimal('2.5'),
            calculation_snapshot={'schema_version': 4, 'source': 'SAMPLE', 'measurement_unit': 'kg',
                                  'sample_demand_snapshot': self.snapshot.copy()})

    def arrival(self):
        with patch('apps.samples.pipe_materials.sample_pipe_snapshot', return_value=self.snapshot):
            return sample_pipe_arrival_quantity(self.line, SimpleNamespace(), self.row)

    def test_kg_receipt_returns_real_root_meters_to_sample_demand(self):
        self.assertEqual(self.arrival(), Decimal('18'))

    def test_historical_piece_demand_still_receives_piece_quantity(self):
        self.row = {'category': 'tube', 'cuttingLengthMm': '500', 'piecesPerBar': '6', 'pipeCalculation': {'schema_version': 2}}
        self.snapshot['pieces_per_bar'] = 8
        self.line.calculation_snapshot['sample_demand_snapshot'] = self.snapshot.copy()
        self.assertEqual(self.arrival(), Decimal('24'))

    def test_catalog_receipt_also_returns_meters_not_kg(self):
        catalog_id, selected = uuid4(), {'unit_name': '根'}
        self.row.update(material_catalog_id=str(catalog_id))
        self.line.material_catalog_id = catalog_id
        self.line.material_selection_snapshot = selected
        with patch('apps.samples.catalog_materials.sample_saved_selection', return_value=selected):
            self.assertEqual(self.arrival(), Decimal('18'))

    def test_missing_weight_or_changed_frozen_demand_is_rejected(self):
        for field, value in (('accepted_weight_kg', None), ('return_weight_kg', Decimal('1'))):
            saved = getattr(self.line, field)
            setattr(self.line, field, value)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.arrival()
            setattr(self.line, field, saved)
        self.line.calculation_snapshot['sample_demand_snapshot']['raw_material_id'] = str(uuid4())
        with self.assertRaises(ValidationError):
            self.arrival()


class SampleLegacyWeightIssueContractTests(SimpleTestCase):
    def test_sample_root_issue_consumes_actual_weight_and_final_remainder(self):
        balance = SimpleNamespace(pk=uuid4(), zone_id=uuid4(), raw_bar_length_m=Decimal('6'),
            quantity=Decimal('3'), meter_quantity=Decimal('18'), weight_quantity=Decimal('4.1'),
            bar_weight_kg=Decimal('2.5'), version=1, save=Mock())
        with patch('apps.samples.sample_issue_stock.require_business_stock_write'), \
                patch('apps.samples.sample_issue_stock.MaterialStockMovement.objects.filter') as movements, \
                patch('apps.samples.sample_issue_stock.MaterialStockBalance.objects.select_for_update') as balances, \
                patch('apps.samples.sample_issue_stock.MaterialStockMovement.objects.create') as create:
            movements.return_value.first.return_value = None
            balances.return_value.get.return_value = balance
            for roots, weight in ((1, Decimal('1.3667')), (2, Decimal('2.7333'))):
                debit_pipe_plan.__wrapped__(plan={'public': False, 'allocations': [
                    {'balance': balance, 'bars': Decimal(roots), 'inbound_line_ids': []}]},
                    source_id=uuid4(), source_line_id=uuid4(), actor_employee=None, snapshot={})
                self.assertEqual(create.call_args.kwargs['weight_quantity'], weight)
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (0, 0, 0))


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=False,
                   MODULE_ACCESS_ENABLED=False)
class SampleWeightReceivingApiTests(SampleReceivingHelpers, APITestCase):
    def setUp(self):
        pipe_fixture.SamplePipeFlowTests.setUp(self)
        self.demand.pop('cuttingLengthMm')
        self.demand.pop('piecesPerBar')
        self.demand.update(pipeInputMode='TOTAL_METERS', quantity='8', supplyQuantity='0', shortageQuantity='8', unitLabel='米')
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '0'}], 'notes': ''}
        record.save(update_fields=['draft', 'warehouse_draft'])
        self.prepare()

    def purchase_payload(self):
        payload = purchase_fixture.SamplePurchaseApiTests.purchase_payload(self)
        payload['lines'][0].update(actual_purchase_quantity='4.1', raw_bar_length_m='6', raw_bar_weight_kg='2.5')
        return payload

    def test_checked_roots_credit_actual_kg_and_keep_sample_demand_in_meters(self):
        payload, etag = self.receipt_payload(), self.receipt_etag()
        payload['items'][0].update(received_weight_kg='4.1', received_bar_count=3)
        received = self.receive_all(payload, etag)
        self.assertEqual(received.status_code, 201, received.data)
        line = MaterialInboundLine.objects.get(pk=received.data['data']['lines'][0]['id'])
        self.assertEqual((line.accepted_bar_count, line.accepted_weight_kg, line.accepted_quantity),
                         (3, Decimal('4.1'), Decimal('18')))
        self.assertEqual(SampleMaterialArrival.objects.get(inbound_line=line).accepted_quantity, 18)
        model = PublicStockBalance if line.inbound.stock_mode == 'PUBLIC_V2' else MaterialStockBalance
        balance = model.objects.get(raw_material=self.raw_material)
        self.assertEqual((balance.quantity, balance.weight_quantity), (3, Decimal('4.1')))
        self.assertEqual(self.receive_all(payload, etag).status_code, 200)
        changed = deepcopy(payload)
        changed['items'][0]['received_bar_count'] = 4
        self.assertEqual(self.receive_all(changed, etag).status_code, 409)
        movements = []
        for roots in (1, 2):
            movements.extend(debit_pipe_plan(plan={'public': line.inbound.stock_mode == 'PUBLIC_V2', 'allocations': [
                {'balance': balance, 'bars': Decimal(roots), 'inbound_line_ids': [str(line.pk)]}]},
                source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee, snapshot={}))
        balance.refresh_from_db()
        self.assertEqual((balance.quantity, balance.weight_quantity), (0, 0))
        self.assertEqual(sum(row.weight_quantity for row in movements), Decimal('4.1'))

    def test_default_roots_and_full_weight_validation(self):
        payload = self.receipt_payload()
        payload['items'][0]['received_weight_kg'] = '4'
        self.assertEqual(self.receive_all(payload).status_code, 400)
        payload['items'][0]['received_weight_kg'] = '4.2'
        self.assertEqual(self.receive_all(payload).status_code, 400)
        payload['items'][0]['received_weight_kg'] = '4.1'
        received = self.receive_all(payload)
        self.assertEqual(received.status_code, 201, received.data)
        line = MaterialInboundLine.objects.get(pk=received.data['data']['lines'][0]['id'])
        self.assertEqual((line.accepted_bar_count, line.accepted_quantity, line.accepted_weight_kg),
                         (2, Decimal('12'), Decimal('4.1')))


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class SampleLegacyWeightReceivingApiTests(SampleWeightReceivingApiTests):
    pass


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=False,
                   MODULE_ACCESS_ENABLED=False)
class SampleCatalogWeightReceivingApiTests(SampleReceivingHelpers, APITestCase):
    purchase_payload = SampleWeightReceivingApiTests.purchase_payload

    def setUp(self):
        from apps.material_catalog.models import MaterialCatalog
        from apps.procurement.models import PurchaseOrder

        pipe_fixture.SamplePipeFlowTests.setUp(self)
        self.catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='样品KG目录管材')
        selected = {'schema_version': 1, 'catalog_id': str(self.catalog.pk),
            'catalog_version': self.catalog.updated_at.isoformat(), 'category_key': 'TUBE', 'template_key': 'TUBE',
            'name': self.catalog.name, 'scope': 'BASE', 'processing_state': 'RAW', 'processing_stage': 'RAW',
            'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '6000'},
            'unit_id': str(self.raw_material.unit_id), 'unit_name': '根', 'display_name': '样品KG目录管材 / 根'}
        self.demand.pop('cuttingLengthMm')
        self.demand.pop('piecesPerBar')
        self.demand.update(rawMaterialId='', material_catalog_id=str(self.catalog.pk), material_selection_snapshot=selected,
            name=self.catalog.name, specification='25 / 1.2', material='铁', pipeInputMode='TOTAL_METERS',
            quantity='8', supplyQuantity='0', shortageQuantity='8', unitLabel='米')
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '0'}], 'notes': ''}
        record.save(update_fields=['draft', 'warehouse_draft'])
        self.create_order()
        confirmed = self.client.post(self.root + self.sample_order_id + '/confirm/', {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.order = PurchaseOrder.objects.get(pk=self.sample_order_id)
        self.assertEqual(self.order.status, 'SUBMITTED')
        # 采购签发不在本测试范围；建立已签发的采购中状态，继续验证真实收货 API。
        self.order.status = 'PURCHASING'
        self.order.save(update_fields=['status', 'updated_at'])

    def test_catalog_source_manual_unit_weight_confirmation_and_receiving(self):
        self.purchase_line.refresh_from_db()
        self.assertEqual((self.purchase_line.source_unit_text, self.purchase_line.raw_bar_weight_kg,
                          self.purchase_line.actual_purchase_quantity, self.purchase_line.amount),
                         ('KG', Decimal('2.5'), Decimal('4.1'), Decimal('8.2')))
        payload = self.receipt_payload()
        payload['items'][0].update(received_weight_kg='4.1', received_bar_count=3)
        received = self.receive_all(payload)
        self.assertEqual(received.status_code, 201, received.data)
        line = MaterialInboundLine.objects.get(pk=received.data['data']['lines'][0]['id'])
        self.assertEqual((line.source_unit_text_snapshot, line.accepted_bar_count,
                          line.accepted_weight_kg, line.accepted_quantity), ('KG', 3, Decimal('4.1'), Decimal('18')))
        self.assertEqual(SampleMaterialArrival.objects.get(inbound_line=line).accepted_quantity, Decimal('18'))
        balance = PublicStockBalance.objects.get(material_catalog=self.catalog)
        self.assertEqual((balance.quantity, balance.weight_quantity, balance.meter_quantity),
                         (3, Decimal('4.1'), Decimal('18')))
