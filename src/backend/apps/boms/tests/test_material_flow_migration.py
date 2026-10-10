from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.material_issues.tests import test_material_issue_api as fixtures
from apps.inventory.models import MaterialStockBalance


class MaterialFlowMigrationTests(TransactionTestCase):
    serialized_rollback = True
    setUp = fixtures.MaterialIssueApiTests.setUp

    def test_old_bom_lines_get_independent_ids_without_converting_stock(self):
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        old_targets = [("boms", "0006_bom_quantity_difference_reason"),
                       ("inventory", "0012_alter_materialstockmovement_source_constraint"),
                       ("material_issues", "0002_materialissueline_semi_finished_balance_and_more")]
        balance_before = list(MaterialStockBalance.objects.values_list("id", "quantity", "measurement_kind", "meter_quantity"))
        try:
            executor.migrate(old_targets)
            old_apps = executor.loader.project_state(old_targets).apps
            old_balance_model = old_apps.get_model("inventory", "MaterialStockBalance")
            self.assertNotIn("measurement_kind", {field.name for field in old_balance_model._meta.fields})
            self.assertEqual(list(old_balance_model.objects.values_list("id", "quantity")),
                             [(row[0], row[1]) for row in balance_before])
            old_line_model = old_apps.get_model("boms", "BomLine")
            first = old_line_model.objects.get(pk=self.bom_line.pk)
            first.pk = None
            first.line_number = 2
            first.save()
            line_ids = [first.pk, self.bom_line.pk]
        finally:
            MigrationExecutor(connection).migrate(final_targets)
        from apps.boms.models import BomLine
        lines = list(BomLine.objects.filter(pk__in=line_ids))
        self.assertEqual(len({row.component_identity for row in lines}), 2)
        self.assertTrue(all(row.cutting_length_mm is None for row in lines))
        self.assertEqual(list(MaterialStockBalance.objects.values_list("id", "quantity", "measurement_kind", "meter_quantity")), balance_before)
