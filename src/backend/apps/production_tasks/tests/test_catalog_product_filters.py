from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.production_tasks.api.views import ProductionTaskViewSet
from apps.production_tasks.models import ProductionTask


class CatalogProductFilterTests(SimpleTestCase):
    def filtered(self, parameters):
        view = ProductionTaskViewSet()
        view.request = SimpleNamespace(query_params=parameters)
        with patch('apps.production_tasks.api.views.accessible_production_tasks',
                   return_value=ProductionTask.objects.all()):
            return view._filtered_queryset()

    def test_new_catalog_filter_uses_catalog_foreign_key_with_uuid_parameter(self):
        identity = UUID('a3e05cd0-3c82-41db-a363-72198d4d5739')
        sql, parameters = self.filtered({'product_catalog_id': str(identity)}).query.sql_with_params()
        self.assertIn('"product_catalog_id" = %s', sql)
        self.assertIn(identity, parameters)
        self.assertNotIn(str(identity), sql)
        self.assertNotIn('"product_id" = %s', sql)

    def test_legacy_filter_keeps_legacy_foreign_key(self):
        identity = UUID('a3e05cd0-3c82-41db-a363-72198d4d5739')
        sql, parameters = self.filtered({'product_id': str(identity)}).query.sql_with_params()
        self.assertIn('"product_id" = %s', sql)
        self.assertIn(identity, parameters)
        self.assertNotIn('"product_catalog_id" = %s', sql)

    def test_invalid_catalog_identifier_returns_field_error_before_query_execution(self):
        with self.assertRaises(ValidationError) as caught:
            self.filtered({'product_catalog_id': 'not-a-uuid'})
        self.assertIn('product_catalog_id', caught.exception.detail)
