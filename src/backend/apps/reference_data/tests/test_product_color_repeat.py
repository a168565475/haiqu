from django.utils import timezone
from rest_framework.test import APITestCase

from apps.reference_data.models import ProductColor
from .test_production_data_api import ProductionDataApiTests


class ProductColorRepeatTests(APITestCase):
    setUp = ProductionDataApiTests.setUp

    def test_saved_color_can_be_loaded_after_refresh_and_duplicate_has_clear_message(self):
        url = '/api/v1/reference-data/product-colors/'
        payload = {'color_card': 'RELOAD', 'color_code': '001', 'color_name': '刷新颜色'}
        created = self.client.post(url, payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        loaded = self.client.get(url, {'q': 'RELOAD', 'status': 'ACTIVE'})
        self.assertEqual(loaded.status_code, 200, loaded.data)
        self.assertEqual([item['id'] for item in loaded.data['data']], [created.data['data']['id']])
        duplicate = self.client.post(url, payload, format='json')
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertIn('请选择已有颜色', duplicate.data['error']['message'])
        self.assertNotIn('color_card', duplicate.data['error']['message'])
        detail = self.client.get(url + str(created.data['data']['id']) + '/')
        updated = self.client.patch(url + str(created.data['data']['id']) + '/', payload,
                                    format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(ProductColor.objects.filter(**payload).count(), 1)

    def test_archived_color_is_not_offered_as_active_or_duplicated(self):
        payload = {'color_card': 'ARCHIVED', 'color_code': '001', 'color_name': '归档颜色'}
        ProductColor.objects.create(**payload, archived_at=timezone.now(), status='INACTIVE')
        url = '/api/v1/reference-data/product-colors/'
        loaded = self.client.get(url, {'q': 'ARCHIVED', 'status': 'ACTIVE'})
        self.assertEqual(loaded.status_code, 200, loaded.data)
        self.assertEqual(loaded.data['data'], [])
        duplicate = self.client.post(url, payload, format='json')
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(ProductColor.objects.filter(**payload).count(), 1)
