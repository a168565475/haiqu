from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.inventory.tests import test_inbound_loading as fixtures
from apps.inventory.models import MaterialInbound
from apps.inventory.selectors import material_inbounds
from apps.inventory.api.serializers import MaterialInboundSerializer
from apps.procurement.models import PurchaseReturn


class QualityLoadingTests(APITestCase):
    make_order = fixtures.InboundLoadingTests.make_order
    batch = fixtures.InboundLoadingTests.batch

    def setUp(self):
        fixtures.InboundLoadingTests.setUp(self)
        self.pending = self.batch('QUALITY', 'PENDING_QUALITY', [(3, 0), (2, 0)])
        self.pending.lines.update(supplier_name_snapshot='品质供应商', supplier_number_snapshot='GYS99991')
        self.completed = self.batch('DONE', 'CONFIRMED', [(1, 0)])
        self.hidden_batch = MaterialInbound.objects.create(inbound_number='HIDDEN-QUALITY', purchase_order=self.hidden,
            status='PENDING_QUALITY', received_by_employee=self.employee)
        self.root = '/api/v1/material-inventory/quality-batches/'

    def get(self, suffix='', params=None):
        response = self.client.get(self.root + suffix, params or {}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def items(self):
        return [{'line_id':str(line.pk), 'expected_received_quantity':str(line.received_quantity),
                 'return_quantity':'1.0000', 'quality_remark':'隔离测试'} for line in self.pending.lines.order_by('id')]

    def post(self, items):
        return self.client.post(self.root+str(self.pending.pk)+'/confirm/', {'items':items}, format='json', HTTP_HOST='localhost')

    def test_list_and_detail_keep_full_payload_without_unused_prefetches(self):
        expected = MaterialInboundSerializer(material_inbounds(MaterialInbound.objects.filter(pk=self.pending.pk)).get()).data
        with CaptureQueriesContext(connection) as queries:
            data = self.get().data['data']
        self.assertEqual(data, [expected])
        for table in ['procurement_purchase_order_line', 'inventory_warehouse_zone', 'inventory_warehouse']:
            self.assertFalse(any(f'FROM "{table}"' in query['sql'] for query in queries))
        self.assertEqual(self.get(str(self.pending.pk)+'/').data['data'], expected)

    def test_optimized_selector_two_queries_preserves_default_selector_contract(self):
        expected = MaterialInboundSerializer(material_inbounds(MaterialInbound.objects.filter(pk=self.pending.pk)), many=True).data
        with self.assertNumQueries(2):
            actual = MaterialInboundSerializer(material_inbounds(MaterialInbound.objects.filter(pk=self.pending.pk), read_optimized=True), many=True).data
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual[0]['lines']), 2)
        self.assertEqual(actual[0]['total_received_quantity'], '5.0000')

    def test_pending_filter_search_distinct_and_completed_detail(self):
        rows = self.get(params={'q':'品质供应商'}).data['data']
        self.assertEqual([row['id'] for row in rows], [str(self.pending.pk)])
        self.assertEqual(len(rows[0]['lines']), 2)
        self.assertEqual(self.get(params={'q':'NO-MATCH'}).data['data'], [])
        self.assertEqual(self.get(str(self.completed.pk)+'/').data['data']['status'], 'CONFIRMED')

    def test_permissions_scope_and_invalid_id(self):
        self.assertEqual(self.client.get(self.root+str(self.hidden_batch.pk)+'/', HTTP_HOST='localhost').status_code, 404)
        self.assertEqual(self.client.get(self.root+'invalid/', HTTP_HOST='localhost').status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        for suffix in ['', str(self.pending.pk)+'/']:
            self.assertEqual(self.client.get(self.root+suffix, HTTP_HOST='localhost').status_code, 403)

    def test_write_rejects_stale_quantity_missing_lines_and_excess_return(self):
        items = self.items(); items[0]['expected_received_quantity'] = '99.0000'
        self.assertEqual(self.post(items).status_code, 409)
        self.assertEqual(self.post(self.items()[:1]).status_code, 400)
        items = self.items(); items[0]['return_quantity'] = '99.0000'
        self.assertEqual(self.post(items).status_code, 400)
        self.pending.refresh_from_db(); self.assertEqual(self.pending.status, 'PENDING_QUALITY')
        self.assertEqual(PurchaseReturn.objects.count(), 0)

    def test_confirm_whole_batch_and_reject_duplicate_submission(self):
        items = self.items(); response = self.post(items)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['status'], 'CONFIRMED')
        self.assertEqual(response.data['data']['total_return_quantity'], '2.0000')
        self.assertEqual(response.data['data']['total_accepted_quantity'], '3.0000')
        self.assertEqual(PurchaseReturn.objects.count(), 1)
        self.assertEqual(self.post(items).status_code, 409)
        self.assertEqual(self.get().data['data'], [])
