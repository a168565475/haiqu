"""一般管材根数及实重 API 回归；由独占测试库统一执行。"""
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
        warehouse = Warehouse.objects.create(warehouse_number='GW1', warehouse_name='一般重量材料仓', warehouse_type='MATERIAL')
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='主库区')

    def payload(self, *, direction='IN'):
        self.catalog.refresh_from_db()
        item = {'material_catalog_id': str(self.catalog.pk), 'zone_id': str(self.zone.pk),
            'raw_bar_count': 3, 'raw_bar_length_m': '6.00', 'material_selection': {
                'catalog_version': self.catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'RAW',
                'unit_id': str(self.unit.pk), 'attributes': {'material': '铁', 'shape': '圆管',
                    'section_size': '20', 'thickness': '1', 'length': '6000'}}}
        if direction == 'IN':
            item['weight_quantity'] = '7.1000'
        return {'client_request_id': str(uuid4()), 'direction': direction,
                'transfer_date': str(timezone.localdate()), 'remark': '一般管材实重登记', 'items': [item]}

    def post(self, payload):
        return self.client.post('/api/v1/material-transfers/', payload, format='json')

    def test_general_inbound_saves_actual_weight_without_standard_weight(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201, response.data)
        line, balance = MaterialTransferLine.objects.get(), PublicStockBalance.objects.get()
        self.assertEqual((line.quantity, line.weight_quantity), (Decimal('3'), Decimal('7.1')))
        self.assertEqual((balance.quantity, balance.weight_quantity, balance.meter_quantity),
                         (Decimal('3'), Decimal('7.1'), Decimal('18')))
        self.assertIsNone(balance.bar_weight_kg)
        self.assertEqual(Decimal(response.data['data']['lines'][0]['weight_quantity']), Decimal('7.1'))

    def test_retry_preserves_weight_and_changed_weight_conflicts(self):
        payload = self.payload()
        self.assertEqual(self.post(payload).status_code, 201)
        self.assertEqual(self.post(payload).status_code, 201)
        changed = deepcopy(payload)
        changed['items'][0]['weight_quantity'] = '8.0000'
        self.assertEqual(self.post(changed).status_code, 409)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().weight_quantity, Decimal('7.1'))

    def test_missing_weight_rejects_without_creating_inventory(self):
        payload = self.payload()
        payload['items'][0].pop('weight_quantity')
        response = self.post(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialTransferLine.objects.exists())
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_general_outbound_saves_server_allocated_weight(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        payload = self.payload(direction='OUT')
        payload['items'][0]['raw_bar_count'] = 1
        response = self.post(payload)
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialTransferLine.objects.get(transfer__direction='OUT')
        self.assertEqual(line.weight_quantity, Decimal('2.3667'))
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.weight_quantity), (Decimal('2'), Decimal('4.7333')))

    def test_legacy_manual_endpoint_saves_actual_weight_as_kg(self):
        payload = self.payload()
        payload['inbound_date'] = payload.pop('transfer_date')
        payload.pop('direction')
        item = payload['items'][0]
        item['received_bar_count'] = item.pop('raw_bar_count')
        item['received_weight_kg'] = item.pop('weight_quantity')
        response = self.client.post('/api/v1/material-inventory/manual-receipts/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInboundLine.objects.get()
        self.assertEqual(line.source_unit_text_snapshot, 'KG')
        self.assertEqual((line.received_bar_count, line.received_weight_kg), (3, Decimal('7.1')))
        self.assertIsNone(line.bar_weight_kg)
        self.assertEqual(PublicStockBalance.objects.get().weight_quantity, Decimal('7.1'))

