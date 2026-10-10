from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee
from apps.reference_data.models import ConfigRelease, DictionaryType, ReferenceDictionary
from apps.reference_data.services import build_config_snapshot
from apps.core.api.concurrency import etag_for_instance


class PublishedReadTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="published_read_test")
        Employee.objects.create(user=self.user, employee_code="PUBLISHED_READ_TEST", display_name="读取测试")
        self.client.force_authenticate(self.user)
        for code in ['CUSTOMER_GRADE', 'COUNTRY_REGION']:
            DictionaryType.objects.get_or_create(code=code, defaults={'chinese_name': code, 'english_name': code, 'group_code': 'CUSTOMER', 'status': 'ACTIVE'})
        self.grade, _ = ReferenceDictionary.objects.get_or_create(
            category_code='CUSTOMER_GRADE', item_code='CACHE_TEST',
            defaults={'dictionary_type': DictionaryType.objects.get(code='CUSTOMER_GRADE'), 'display_name': '缓存原值', 'status': 'ACTIVE'},
        )
        latest = ConfigRelease.objects.order_by('-version').first()
        ConfigRelease.objects.create(version=(latest.version if latest else 0) + 1, status='PUBLISHED', published_at=timezone.now(), snapshot=build_config_snapshot())

    def test_draft_remains_hidden_until_real_publish_api_commits(self):
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='reference_data'))
        url = '/api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE'
        first = self.client.get(url, HTTP_HOST='localhost').data
        self.grade.display_name = '发布新值'
        self.grade.save(update_fields=['display_name', 'updated_at'])
        self.assertEqual(self.client.get(url, HTTP_HOST='localhost').data, first)
        latest = ConfigRelease.objects.order_by('-version').first()
        published = self.client.post('/api/v1/reference-data/config-releases/', {'notes': '缓存发布测试'}, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag_for_instance(latest))
        self.assertEqual(published.status_code, 201, published.data)
        fresh = self.client.get(url, HTTP_HOST='localhost').data
        self.assertNotEqual(first['meta']['config_revision'], fresh['meta']['config_revision'])
        self.assertEqual(next(item['label'] for item in fresh['data']['CUSTOMER_GRADE'] if item['id'] == str(self.grade.pk)), '发布新值')

    def test_historical_current_item_does_not_contaminate_batch(self):
        self.grade.status = 'INACTIVE'
        self.grade.save(update_fields=['status', 'updated_at'])
        latest = ConfigRelease.objects.order_by('-version').first()
        ConfigRelease.objects.create(version=latest.version + 1, status='PUBLISHED', published_at=timezone.now(), snapshot=build_config_snapshot())
        batch = self.client.get('/api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE', HTTP_HOST='localhost').data
        self.assertNotIn(str(self.grade.pk), [item['id'] for item in batch['data']['CUSTOMER_GRADE']])
        single = self.client.get(f'/api/v1/reference-data/options/CUSTOMER_GRADE/?current_id={self.grade.pk}', HTTP_HOST='localhost').data
        selected = next(item for item in single['data'] if item['id'] == str(self.grade.pk))
        self.assertTrue(selected['extra']['current_selection'])

    def test_batch_matches_individual_and_keeps_valid_types(self):
        result = self.client.get('/api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE,COUNTRY_REGION,UNKNOWN', HTTP_HOST='localhost')
        self.assertEqual(result.status_code, 200)
        for code in ['CUSTOMER_GRADE', 'COUNTRY_REGION']:
            single = self.client.get(f'/api/v1/reference-data/options/{code}/', HTTP_HOST='localhost')
            self.assertEqual(result.data['data'][code], single.data['data'])
        self.assertIn('UNKNOWN', result.data['errors'])

    def test_invalid_batch_is_rejected(self):
        for query in ['', '?type_codes=' + ','.join(f'T_{i}' for i in range(21)), '?type_codes=BAD/TYPE']:
            result = self.client.get('/api/v1/reference-data/options-batch/' + query, HTTP_HOST='localhost')
            self.assertEqual(result.status_code, 400)

    def test_version_changes_on_publish_and_type_disable(self):
        url = '/api/v1/reference-data/published-version/'
        first = self.client.get(url, HTTP_HOST='localhost').data['data']
        latest = ConfigRelease.objects.order_by('-version').first()
        ConfigRelease.objects.create(version=latest.version + 1, status='PUBLISHED', published_at=timezone.now(), snapshot=latest.snapshot)
        second = self.client.get(url, HTTP_HOST='localhost').data['data']
        self.assertNotEqual(first['config_revision'], second['config_revision'])
        item = DictionaryType.objects.get(code='CUSTOMER_GRADE')
        item.status = 'INACTIVE'
        item.save(update_fields=['status', 'updated_at'])
        third = self.client.get(url, HTTP_HOST='localhost').data['data']
        self.assertNotEqual(second['config_revision'], third['config_revision'])
        batch = self.client.get('/api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE', HTTP_HOST='localhost')
        self.assertIn('CUSTOMER_GRADE', batch.data['errors'])

    def test_anonymous_and_inactive_employee_cannot_read(self):
        for url in ['/api/v1/reference-data/options-batch/?type_codes=CUSTOMER_GRADE', '/api/v1/reference-data/published-version/']:
            self.client.force_authenticate(None)
            self.assertIn(self.client.get(url, HTTP_HOST='localhost').status_code, [401, 403])
            self.client.force_authenticate(self.user)
            employee = Employee.objects.get(user=self.user)
            employee.status = 'INACTIVE'
            employee.save(update_fields=['status', 'updated_at'])
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            self.assertEqual(self.client.get(url, HTTP_HOST='localhost').status_code, 403)
