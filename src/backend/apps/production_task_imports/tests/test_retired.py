from django.test import SimpleTestCase
from django.urls import Resolver404, resolve
from rest_framework.exceptions import ValidationError

from apps.production_tasks.api.serializers import ProductionTaskWriteSerializer


class RetiredImportTests(SimpleTestCase):
    def test_legacy_import_routes_are_removed(self):
        for path in (
            '/api/v1/production-task-imports/',
            '/api/v1/production-task-imports/b7250432-985b-42a4-bb80-9c3ce5211243/retry/',
        ):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_legacy_import_payload_is_rejected_before_manual_creation(self):
        serializer = ProductionTaskWriteSerializer()
        with self.assertRaises(ValidationError) as caught:
            serializer.to_internal_value({'import_object_id': 'legacy-record'})
        self.assertIn('import_object_id', caught.exception.detail)

    def test_api_import_and_codex_connection_routes_remain(self):
        self.assertIsNotNone(resolve('/api/v1/ai-production-imports/'))
        self.assertIsNotNone(resolve('/api/v1/codex-connection/'))
