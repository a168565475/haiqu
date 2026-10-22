"""旧成品直接入库入口删除契约；不连接数据库。"""
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory


class FinishedReceiptRouteContractTests(SimpleTestCase):
    def test_receipt_history_get_route_remains(self):
        match = resolve('/api/v1/finished-goods-inventory/receipts/')
        self.assertEqual(match.func.actions.get('get'), 'receipts')

    def test_receipt_history_rejects_post(self):
        match = resolve('/api/v1/finished-goods-inventory/receipts/')
        request = APIRequestFactory().post('/api/v1/finished-goods-inventory/receipts/', {}, format='json')
        view = match.func.cls.as_view(match.func.actions, authentication_classes=[], permission_classes=[])
        response = view(request)
        self.assertEqual(response.status_code, 405)
        self.assertNotIn('post', match.func.actions)

    def test_batch_receipt_route_is_removed(self):
        with self.assertRaises(Resolver404):
            resolve('/api/v1/finished-goods-inventory/batch-receipts/')

    def test_legacy_receipt_candidate_routes_are_removed(self):
        for path in ('eligible-products', 'eligible-orders'):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(f'/api/v1/finished-goods-inventory/{path}/')
