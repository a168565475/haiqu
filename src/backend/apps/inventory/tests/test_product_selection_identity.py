from django.db.models import Case, Count, JSONField, Value, When
from django.test import TestCase

from apps.inventory.product_identity import finished_product_selection_key
from apps.reference_data.models import ProductionUnit


class ProductSelectionInventoryIdentityTests(TestCase):
    def test_database_grouping_ignores_version_but_separates_selected_attributes(self):
        base = {"catalog_version": "2026-10-31T08:00:00+00:00", "color_id": "blue-id",
                "color_name": "蓝色", "material": "铁", "thickness": "0.8"}
        snapshots = [base, {**base, "catalog_version": "2026-11-01T08:00:00+00:00"},
                     {**base, "material": "铝"}, {**base, "thickness": "1.0"}]
        units = [ProductionUnit.objects.create(unit_code=f"IDENTITY_{index}", unit_name=f"库存身份断言{index}")
                 for index in range(len(snapshots))]
        rows = ProductionUnit.objects.filter(pk__in=[unit.pk for unit in units]).annotate(
            selection_snapshot=Case(*[
                When(pk=unit.pk, then=Value(snapshot, output_field=JSONField()))
                for unit, snapshot in zip(units, snapshots)
            ], output_field=JSONField()),
        ).annotate(identity=finished_product_selection_key("selection_snapshot"))
        keys = dict(rows.values_list("pk", "identity"))
        self.assertEqual(keys[units[0].pk], keys[units[1].pk])
        self.assertNotEqual(keys[units[0].pk], keys[units[2].pk])
        self.assertNotEqual(keys[units[0].pk], keys[units[3].pk])
        groups = rows.order_by().values("identity").annotate(total=Count("pk"))
        self.assertEqual(sorted(group["total"] for group in groups), [1, 1, 2])
