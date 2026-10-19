from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.tests import test_inbound_loading as fixtures
from apps.inventory.models import MaterialInbound, MaterialInboundLine
from apps.procurement.models import PurchaseReturn, PurchaseReturnLine


class ReturnLoadingTests(APITestCase):
    make_order = fixtures.InboundLoadingTests.make_order

    def setUp(self):
        fixtures.InboundLoadingTests.setUp(self)
        self.line.color_snapshot = '铁-中光'
        self.line.save(update_fields=['color_snapshot'])
        self.root = '/api/v1/purchase-returns/'
        self.first = self.make_return(self.order, 'FIRST', '旧名称', 'QUALITY_GENERATED')
        self.second = self.make_return(self.order, 'SECOND', '最新名称', 'COMPLETED')
        self.hidden_return = self.make_return(self.hidden, 'HIDDEN', '不应泄露名称', 'COMPLETED')
        self.make_return(self.archived, 'ARCHIVED', '归档名称', 'COMPLETED')

    def make_return(self, order, number, name, status):
        inbound = MaterialInbound.objects.create(inbound_number=number, purchase_order=order, received_by_employee=self.employee)
        record = PurchaseReturn.objects.create(return_number=number, purchase_order=order, inbound=inbound, supplier=self.supplier,
            supplier_number_snapshot='GYS99991', supplier_name_snapshot=name, status=status, generated_by_employee=self.employee)
        if order.pk == self.order.pk:
            for index in range(2):
                line = MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=self.line, zone=self.zone,
                    received_quantity=2, return_quantity=1, accepted_quantity=1, purchased_quantity_snapshot=10,
                    product_name_snapshot='休闲椅', part_name_snapshot=f'材料{index}', quality_remark=f'品质{index}')
                PurchaseReturnLine.objects.create(return_order=record, inbound_line=line, quantity=1)
        return record

    def get(self, suffix='', params=None):
        response = self.client.get(self.root + suffix, params or {}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_filter_options_latest_visible_snapshot_without_loading_lines(self):
        with CaptureQueriesContext(connection) as queries:
            suppliers = self.get('filter-options/').data['data']['suppliers']
        self.assertEqual(suppliers, [{'id': self.supplier.pk, 'supplier_number': 'GYS99991', 'supplier_name': '最新名称'}])
        sql = '\n'.join(q['sql'] for q in queries)
        self.assertNotIn('FROM "procurement_purchase_return_line"', sql)
        self.assertNotIn('JOIN "inventory_material_inbound"', sql)
        self.assertNotIn('FROM "inventory_material_inbound_line"', sql)

    def test_list_detail_lines_etag_and_scope_preserved(self):
        with CaptureQueriesContext(connection) as queries:
            rows = self.get().data['data']
        self.assertEqual({row['id'] for row in rows}, {str(self.first.pk), str(self.second.pk)})
        self.assertTrue(all(len(row['lines']) == 2 for row in rows))
        self.assertTrue(all(line['product_name'] == '休闲椅' and line['color'] == '铁-中光' for row in rows for line in row['lines']))
        self.assertFalse(any('FROM "inventory_material_inbound_line"' in q['sql'] for q in queries))
        detail = self.get(str(self.first.pk) + '/')
        self.assertEqual(detail.data['data'], next(row for row in rows if row['id'] == str(self.first.pk)))
        self.assertTrue(detail['ETag'])
        self.assertEqual(detail['ETag'], self.get(str(self.first.pk) + '/')['ETag'])
        self.assertEqual(self.client.get(self.root + str(self.hidden_return.pk) + '/', HTTP_HOST='localhost').status_code, 404)

    def test_stats_ignore_status_and_page_but_respect_search_supplier_and_order(self):
        expected = {'total': 2, 'QUALITY_GENERATED': 1, 'PROCUREMENT_CONFIRMED': 0, 'COMPLETED': 1}
        self.assertEqual(self.get('stats/', {'status': 'COMPLETED', 'page_size': 1}).data['data'], expected)
        self.assertEqual(self.get('', {'status': 'COMPLETED'}).data['meta']['total'], 1)
        self.assertEqual(self.get('stats/', {'q': 'FIRST'}).data['data']['total'], 1)
        self.assertEqual(self.get('stats/', {'purchase_order_id': str(self.hidden.pk)}).data['data']['total'], 0)
        self.assertEqual(self.get('', {'q': 'NO-MATCH'}).data['data'], [])
        self.assertEqual(self.get('stats/', {'supplier_id': str(self.supplier.pk)}).data['data']['total'], 2)

    def test_return_amount_uses_only_this_return_quantity_and_purchase_price(self):
        self.line.unit_price = Decimal('1.2345')
        self.line.amount = Decimal('12.3450')
        self.line.save()
        data = self.get(str(self.first.pk) + '/').data['data']
        self.assertEqual(data['return_amount'], '2.4690')
        self.assertNotEqual(data['return_amount'], str(self.line.amount))
        self.assertEqual(data['currency_code'], self.order.currency_code_snapshot)
        self.line.unit_price = Decimal('0')
        self.line.amount = Decimal('0')
        self.line.save()
        self.assertEqual(self.get(str(self.first.pk) + '/').data['data']['return_amount'], '0.0000')
        self.line.unit_price = None
        self.line.amount = None
        self.line.save()
        self.assertIsNone(self.get(str(self.first.pk) + '/').data['data']['return_amount'])

    def test_invalid_parameters_and_permissions(self):
        for suffix in ['', 'stats/']:
            for query in [{'status':'INVALID'}, {'purchase_order_id':'bad'}, {'supplier_id':'bad'}, {'ordering':'id'}]:
                self.assertEqual(self.client.get(self.root+suffix, query, HTTP_HOST='localhost').status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        for suffix in ['', 'stats/', 'filter-options/', str(self.first.pk)+'/']:
            self.assertEqual(self.client.get(self.root+suffix, HTTP_HOST='localhost').status_code, 403)

    def test_archived_order_removed_from_all_read_paths(self):
        self.order.archived_at = timezone.now(); self.order.save(update_fields=['archived_at'])
        self.assertEqual(self.get().data['data'], [])
        self.assertEqual(self.get('stats/').data['data']['total'], 0)
        self.assertEqual(self.get('filter-options/').data['data']['suppliers'], [])
        self.assertEqual(self.client.get(self.root+str(self.first.pk)+'/', HTTP_HOST='localhost').status_code, 404)
