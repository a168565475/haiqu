"""一般材料收发按根记账，既有称重单据保留原始记录。"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit
from apps.inventory.models import MaterialInboundLine, MaterialTransferLine, PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class GeneralTransferWeightApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='general_weight_api')
        Employee.objects.create(user=self.user, employee_code='GENERAL_WEIGHT', display_name='一般重量测试')
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=['inventory', 'material_catalog']))
        self.client.force_authenticate(self.user)
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'GWROOT'})
        self.catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='一般重量管材')
        self.catalog.allowed_units.create(scope='BASE', unit=self.unit)
        shape = self.catalog.attribute_values.create(scope='BASE', field_key='shape', value='圆管')
        self.catalog.attribute_values.create(scope='BASE', field_key='section_size', value='20', parent=shape)
        self.catalog.attribute_values.create(scope='BASE', field_key='material', value='铁')
        self.catalog.attribute_values.create(scope='BASE', field_key='thickness', value='1')
        warehouse = Warehouse.objects.create(warehouse_number='GW1', warehouse_name='一般重量材料仓', warehouse_type='MATERIAL')
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='主库区')

    def payload(self, *, direction='IN'):
        self.catalog.refresh_from_db()
        item = {'material_catalog_id': str(self.catalog.pk), 'zone_id': str(self.zone.pk),
            'raw_bar_count': 3, 'raw_bar_length_m': '6.00', 'material_selection': {
                'catalog_version': self.catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'RAW',
                'unit_id': str(self.unit.pk), 'attributes': {'material': '铁', 'shape': '圆管',
                    'section_size': '20', 'thickness': '1', 'length': '6000'}}}
        return {'client_request_id': str(uuid4()), 'direction': direction,
                'transfer_date': str(timezone.localdate()), 'remark': '一般管材按根登记', 'items': [item]}

    def post(self, payload):
        return self.client.post('/api/v1/material-transfers/', payload, format='json')

    def test_general_inbound_only_records_roots_and_actual_length(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201, response.data)
        line, balance = MaterialTransferLine.objects.get(), PublicStockBalance.objects.get()
        self.assertEqual((line.quantity, line.weight_quantity), (Decimal('3'), None))
        self.assertEqual((balance.quantity, balance.weight_quantity, balance.meter_quantity),
                         (Decimal('3'), None, Decimal('18')))
        self.assertIsNone(balance.bar_weight_kg)
        self.assertEqual(line.material_selection_snapshot['attributes']['length'], '6000')
        self.assertFalse(self.catalog.attribute_values.filter(field_key='length').exists())
        self.assertIsNone(response.data['data']['lines'][0]['weight_quantity'])
        movement = PublicStockMovement.objects.get()
        self.assertEqual(movement.snapshot['receipt_quantity_mode'], 'ROOTS')
        self.assertIsNone(movement.weight_quantity)

    def test_manual_length_is_taken_from_the_receipt_and_matches_outbound_stock(self):
        for direction in ('IN', 'OUT'):
            payload = self.payload(direction=direction)
            item = payload['items'][0]
            item['raw_bar_length_m'] = '6.053'
            del item['material_selection']['attributes']['length']
            response = self.post(payload)
            self.assertEqual(response.status_code, 201, response.data)
            line = MaterialTransferLine.objects.get(transfer__direction=direction)
            self.assertEqual(line.material_selection_snapshot['attributes']['length'], '6053')
            self.assertEqual(line.raw_bar_length_m, Decimal('6.053'))
        self.assertEqual(PublicStockBalance.objects.get().quantity, 0)
        self.assertFalse(self.catalog.attribute_values.filter(field_key='length').exists())
        for direction, label in [('IN', '普通收进'), ('OUT', '普通发出')]:
            ledger = self.client.get('/api/v1/material-stock-records/', {'direction': direction, 'section': 'TUBE'})
            self.assertEqual(ledger.status_code, 200, ledger.data)
            row, = ledger.data['data']
            self.assertEqual((row['movement_label'], Decimal(row['actual_quantity']), row['stock_unit']), (label, Decimal('3'), '根'))
        quality = self.client.get('/api/v1/material-inventory/purchase-receipt-records/', {'quality': 'CHECKED'})
        self.assertEqual(quality.data['total'], 0)

    def test_conflicting_pipe_lengths_do_not_create_stock(self):
        payload = self.payload()
        payload['items'][0]['material_selection']['attributes']['length'] = '5000'
        response = self.post(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('单根长度', response.data['error']['message'])
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_retry_does_not_count_roots_twice_and_changed_roots_conflict(self):
        payload = self.payload()
        self.assertEqual(self.post(payload).status_code, 201)
        self.assertEqual(self.post(payload).status_code, 201)
        changed = deepcopy(payload)
        changed['items'][0]['raw_bar_count'] = 4
        self.assertEqual(self.post(changed).status_code, 409)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 3)

    def test_new_transfers_with_obsolete_weight_prompt_for_roots(self):
        for direction in ('IN', 'OUT'):
            payload = self.payload(direction=direction)
            payload['items'][0]['weight_quantity'] = '7.1'
            response = self.post(payload)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('根', response.data['error']['message'])
        self.assertFalse(MaterialTransferLine.objects.exists())
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_general_outbound_from_previously_weighed_stock_does_not_allocate_kg(self):
        receipt = self.weighed_manual_receipt()
        self.assertEqual(receipt.status_code, 201, receipt.data)
        payload = self.payload(direction='OUT')
        payload['items'][0]['raw_bar_count'] = 1
        response = self.post(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialTransferLine.objects.get(transfer__direction='OUT')
        self.assertIsNone(line.weight_quantity)
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (2, 12, None))
        movement = balance.movements.get(direction='OUT')
        self.assertEqual((movement.before_weight_quantity, movement.weight_quantity, movement.after_weight_quantity),
                         (Decimal('7.1'), None, None))
        self.assertEqual(MaterialInboundLine.objects.get().received_weight_kg, Decimal('7.1'))
        self.assertEqual(balance.movements.get(direction='IN').weight_quantity, Decimal('7.1'))

    def test_weighed_stock_can_receive_roots_then_another_weighed_receipt(self):
        self.assertEqual(self.weighed_manual_receipt().status_code, 201)
        self.assertEqual(self.post(self.payload()).status_code, 201)
        receipt = self.weighed_manual_receipt()
        self.assertEqual(receipt.status_code, 201, receipt.data)
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.weight_quantity), (9, 54, None))
        self.assertEqual(balance.movements.filter(weight_quantity=Decimal('7.1')).count(), 2)

    def weighed_manual_receipt(self):
        payload = self.payload()
        payload['inbound_date'] = payload.pop('transfer_date')
        payload.pop('direction')
        item = payload['items'][0]
        item['received_bar_count'] = item.pop('raw_bar_count')
        item['received_weight_kg'] = '7.1'
        return self.client.post('/api/v1/material-inventory/manual-receipts/', payload, format='json')

    def test_legacy_manual_endpoint_saves_actual_weight_as_kg(self):
        response = self.weighed_manual_receipt()
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInboundLine.objects.get()
        self.assertEqual(line.source_unit_text_snapshot, 'KG')
        self.assertEqual((line.received_bar_count, line.received_weight_kg), (3, Decimal('7.1')))
        self.assertIsNone(line.bar_weight_kg)
        self.assertEqual(PublicStockBalance.objects.get().weight_quantity, Decimal('7.1'))

