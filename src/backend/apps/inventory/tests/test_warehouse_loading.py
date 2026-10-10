from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.inventory.tests import test_inbound_loading as fixtures
from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound
from apps.inventory.api.serializers import MaterialInboundSerializer
from apps.inventory.selectors import material_inbounds


class WarehouseLoadingTests(APITestCase):
    make_order = fixtures.InboundLoadingTests.make_order
    batch = fixtures.InboundLoadingTests.batch

    def setUp(self):
        fixtures.InboundLoadingTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='inventory',
            codename__in=['view_material_receipt', 'view_finishedgoodsreceipt']))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

    def test_filter_options_match_full_fields_without_order_or_usage_queries(self):
        for root in ['material-inventory', 'finished-goods-inventory']:
            if root == 'finished-goods-inventory':
                warehouse = Warehouse.objects.create(warehouse_number='FIN-FILTER', warehouse_name='成品仓', warehouse_type='FINISHED')
                WarehouseZone.objects.create(warehouse=warehouse, zone_name='成品库区')
            url = '/api/v1/' + root + '/options/'
            full = self.client.get(url, HTTP_HOST='localhost')
            self.assertEqual(full.status_code, 200, full.data)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url, {'scope':'filters'}, HTTP_HOST='localhost')
            self.assertEqual(response.status_code, 200, response.data)
            for key, fields in [('warehouses', ['id','warehouse_number','warehouse_name']), ('zones', ['id','warehouse','zone_name'])]:
                self.assertEqual(response.json()['data'][key], [{k:r[k] for k in fields} for r in full.json()['data'][key]])
            if root == 'material-inventory':
                self.assertEqual(response.data['data']['sections'], full.data['data']['sections'])
            sql = '\n'.join(q['sql'] for q in queries)
            self.assertNotIn('procurement_purchase_order', sql)
            self.assertNotIn('inventory_finished_goods_receipt', sql)

    def test_options_invalid_scope_and_permissions(self):
        for root in ['material-inventory', 'finished-goods-inventory']:
            self.assertEqual(self.client.get('/api/v1/'+root+'/options/', {'scope':'bad'}, HTTP_HOST='localhost').status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        for root in ['material-inventory', 'finished-goods-inventory']:
            self.assertEqual(self.client.get('/api/v1/'+root+'/options/', {'scope':'filters'}, HTTP_HOST='localhost').status_code, 403)

    def test_inbound_details_keep_snapshot_fields_nullable_location_and_pending_filter(self):
        batch = self.batch('FILTER-OK', 'CONFIRMED', [(3, 1), (2, 0)])
        self.batch('FILTER-PENDING', 'PENDING_QUALITY', [(1, 0)])
        expected = MaterialInboundSerializer(material_inbounds(MaterialInbound.objects.filter(pk=batch.pk)), many=True).data
        response = self.client.get('/api/v1/material-inventory/inbound-details/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], expected)
        self.assertIsNone(response.data['data'][0]['lines'][0]['location_id'])
