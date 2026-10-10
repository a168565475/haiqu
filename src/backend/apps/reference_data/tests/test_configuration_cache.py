from unittest.mock import Mock, patch

from django.core.cache import caches
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APITransactionTestCase

from apps.reference_data import configuration_cache as cache_module
from apps.reference_data.configuration_cache import read_configuration, invalidate_configuration
from apps.reference_data.models import Country
from apps.reference_data.tests.test_published_reads import PublishedReadTests
from apps.core.api.concurrency import etag_for_instance


TEST_CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'configuration': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'configuration-tests'},
}


@override_settings(CACHES=TEST_CACHES)
class ConfigurationCacheTests(TransactionTestCase):
    def setUp(self):
        caches['configuration'].clear()
        cache_module._disabled_until = 0

    def tearDown(self):
        cache_module._disabled_until = 0

    def test_reuses_data_and_invalidates_only_affected_category(self):
        load = Mock(return_value={'items': ['old']})
        result = read_configuration('key', {'country'}, load)
        result['items'].append('caller mutation')
        invalidate_configuration('currency')
        self.assertEqual(read_configuration('key', {'country'}, load), {'items': ['old']})
        self.assertEqual(load.call_count, 1)
        invalidate_configuration('country')
        load.return_value = {'items': ['new']}
        self.assertEqual(read_configuration('key', {'country'}, load), {'items': ['new']})
        self.assertEqual(load.call_count, 2)

    def test_late_read_cannot_repopulate_current_namespace(self):
        def old_read():
            invalidate_configuration('country')
            return 'old'
        self.assertEqual(read_configuration('key', {'country'}, old_read), 'old')
        self.assertEqual(read_configuration('key', {'country'}, lambda: 'new'), 'new')

    def test_cache_read_and_fill_failures_return_database_result(self):
        backend = caches['configuration']
        with patch.object(backend, 'get', side_effect=ConnectionError):
            self.assertEqual(read_configuration('key', {'country'}, lambda: 'database'), 'database')
        cache_module._disabled_until = 0
        invalidate_configuration('country')
        with patch.object(backend, 'set', side_effect=ConnectionError):
            self.assertEqual(read_configuration('key', {'country'}, lambda: 'database'), 'database')

    def test_failed_invalidation_bypasses_old_cache(self):
        read_configuration('key', {'country'}, lambda: 'old')
        with patch.object(caches['configuration'], 'set', side_effect=ConnectionError):
            invalidate_configuration('country')
        self.assertEqual(read_configuration('key', {'country'}, lambda: 'new'), 'new')

    def test_database_transaction_bypasses_cache_and_rollback_does_not_invalidate(self):
        tag = 'reference_data.country'
        read_configuration('key', {tag}, lambda: 'old')
        with self.assertRaises(ValueError):
            with transaction.atomic():
                cache_module.configuration_changed(Country, None)
                self.assertEqual(read_configuration('key', {tag}, lambda: 'uncommitted'), 'uncommitted')
                raise ValueError('rollback')
        self.assertEqual(read_configuration('key', {tag}, lambda: 'unexpected'), 'old')
        with transaction.atomic():
            cache_module.configuration_changed(Country, None)
        self.assertEqual(read_configuration('key', {tag}, lambda: 'committed'), 'committed')

    def test_expired_generation_rebuilds_without_a_timer(self):
        read_configuration('key', {'country'}, lambda: 'old')
        caches['configuration'].delete('generation:country')
        self.assertEqual(read_configuration('key', {'country'}, lambda: 'new'), 'new')


@override_settings(CACHES=TEST_CACHES)
class ConfigurationApiTests(APITransactionTestCase):
    # 同样的发布/历史选项/权限契约，在真实提交边界上验证缓存命中后的行为。
    setUpPublished = PublishedReadTests.setUp
    test_draft_publish = PublishedReadTests.test_draft_remains_hidden_until_real_publish_api_commits
    test_history_isolation = PublishedReadTests.test_historical_current_item_does_not_contaminate_batch
    test_batch_matches_single = PublishedReadTests.test_batch_matches_individual_and_keeps_valid_types
    test_type_disable = PublishedReadTests.test_version_changes_on_publish_and_type_disable
    test_access_controls = PublishedReadTests.test_anonymous_and_inactive_employee_cannot_read

    def setUp(self):
        caches['configuration'].clear()
        cache_module._disabled_until = 0
        self.setUpPublished()

    def tearDown(self):
        cache_module._disabled_until = 0

    def test_published_catalog_reads_database_only_on_miss(self):
        from apps.reference_data.published_reads import published_catalog, published_config_state
        with patch('apps.reference_data.published_reads.published_config_state', wraps=published_config_state) as state:
            first = published_catalog()
            self.assertEqual(published_catalog(), first)
            self.assertEqual(state.call_count, 1)

    def test_country_save_refreshes_cache_and_permissions_still_apply(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        country = Country.objects.create(code='ZZ', alpha3_code='ZZZ', numeric_code='999', chinese_name='原值')
        url = '/api/v1/reference-data/countries/?q=ZZ'
        first = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(self.client.get(url, HTTP_HOST='localhost').data, first.data)
        changed = self.client.patch(f'/api/v1/reference-data/countries/{country.pk}/',
                                    {'chinese_name': '新值'}, format='json', HTTP_HOST='localhost',
                                    HTTP_IF_MATCH=etag_for_instance(country))
        self.assertEqual(changed.status_code, 200, changed.data)
        fresh = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(fresh.data['data'][0]['chinese_name'], '新值')
        self.assertEqual(self.client.get(url + '&status=INACTIVE', HTTP_HOST='localhost').data['data'], [])
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(url, HTTP_HOST='localhost').status_code, [401, 403])

    def test_cached_dictionary_reference_count_is_refreshed(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        url = '/api/v1/reference-data/dictionary-types/'
        with patch('apps.reference_data.services.dictionary_type_reference_count', return_value=2):
            first = self.client.get(url, HTTP_HOST='localhost')
            self.assertEqual(first.status_code, 200, first.data)
            self.assertTrue(first.data['data'])
            self.assertEqual(first.data['data'][0]['reference_count'], 2)
        with patch('apps.reference_data.services.dictionary_type_reference_count', return_value=3):
            self.assertEqual(self.client.get(url, HTTP_HOST='localhost').data['data'][0]['reference_count'], 3)
