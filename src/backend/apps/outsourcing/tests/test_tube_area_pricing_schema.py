from importlib import import_module

from django.db import connection
from django.test import SimpleTestCase, TestCase


class TubeAreaPricingMigrationContractTests(SimpleTestCase):
    def test_price_unit_migration_declares_database_default(self):
        migration_module = import_module(
            'apps.outsourcing.migrations.0019_tube_line_area_pricing'
        )
        price_unit_operation = next(
            operation
            for operation in migration_module.Migration.operations
            if getattr(operation, 'name', None) == 'price_unit'
        )

        self.assertEqual(price_unit_operation.field.db_default, 'PIECE')


class TubeAreaPricingSchemaTests(TestCase):
    def test_price_unit_keeps_database_default_for_legacy_writers(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'tube_outsourcing_line'
                  AND column_name = 'price_unit'
                """
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertIsNotNone(row[0])
        self.assertIn("'PIECE'", row[0])
