from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db.models import Q
from django.test import SimpleTestCase

from apps.inventory.catalog_stock_queries import catalog_stock_summary
from apps.inventory.public_inventory_queries import public_pipe_summary, public_raw_inventory_page


class PipeWeightSummaryContractTests(SimpleTestCase):
    def setUp(self):
        self.material = SimpleNamespace(pk=uuid4(), material_number="PIPE", material_name="管材",
            category=SimpleNamespace(category_name="管材"), specification="规格", color_id=None,
            color_snapshot="", unit=SimpleNamespace(unit_name="根"), item_type="MATERIAL", material="钢")
        self.selected = {"category_key": "TUBE", "name": "管材", "attributes": {}, "unit_name": "根"}
        self.catalog = SimpleNamespace(material_catalog_id=uuid4(), stock_kind="CATALOG_RAW", identity_key="key",
            unit_id=uuid4(), raw_bar_length_m=Decimal("6"), identity_snapshot={"material_selection_snapshot": self.selected})

    def public_summary(self, *, roots, weights, missing):
        with patch("apps.inventory.public_inventory_queries.PublicStockBalance.objects.filter") as balances, \
                patch("apps.inventory.public_inventory_queries.MaterialStockMovement.objects.filter") as old, \
                patch("apps.inventory.public_inventory_queries.PublicStockMovement.objects.filter") as current:
            balances.return_value.aggregate.return_value = {"available": roots, "meters": roots * 6,
                "weights": weights, "missing_weights": missing, "defective": 0}
            balances.return_value.select_related.return_value.order_by.return_value = []
            old.return_value.aggregate.return_value = {"inbound": 0, "issued": 0}
            current.return_value.exclude.return_value.aggregate.return_value = {"inbound": 0, "issued": 0}
            result = public_pipe_summary(self.material)
            self.assertEqual(balances.return_value.aggregate.call_args.kwargs["missing_weights"].filter,
                Q(quality="AVAILABLE", quantity__gt=0, weight_quantity__isnull=True))
            return result

    def catalog_summary(self, *, roots, weights, missing, free=None):
        with patch("apps.inventory.catalog_stock_queries.PublicStockBalance.objects.filter") as balances, \
                patch("apps.inventory.models.PublicStockMovement.objects.filter") as movements, \
                patch("apps.inventory.catalog_stock_queries.available_catalog_balances", return_value=free or []):
            rows = balances.return_value.select_related.return_value.order_by.return_value
            rows.aggregate.return_value = {"available": roots, "defective": 0, "weights": weights, "missing_weights": missing}
            rows.__iter__.return_value = iter([])
            movements.return_value.aggregate.return_value = {"inbound": 0, "issued": 0}
            result = catalog_stock_summary(self.catalog)
            self.assertEqual(rows.aggregate.call_args.kwargs["missing_weights"].filter,
                Q(quality="AVAILABLE", quantity__gt=0, weight_quantity__isnull=True))
            return result

    def test_any_positive_balance_with_unknown_weight_keeps_total_unknown(self):
        for summary in (self.public_summary, self.catalog_summary):
            for known_weight in (None, Decimal("4.1")):
                with self.subTest(summary=summary.__name__, known_weight=known_weight):
                    self.assertIsNone(summary(roots=3, weights=known_weight, missing=1)["weight_quantity"])

    def test_complete_weight_is_returned_without_using_root_standard_weight(self):
        for summary in (self.public_summary, self.catalog_summary):
            with self.subTest(summary=summary.__name__):
                self.assertEqual(summary(roots=3, weights=Decimal("4.1"), missing=0)["weight_quantity"], "4.1")

    def test_zero_stock_with_no_weight_history_can_return_zero(self):
        for summary in (self.public_summary, self.catalog_summary):
            with self.subTest(summary=summary.__name__):
                self.assertEqual(summary(roots=0, weights=None, missing=0)["weight_quantity"], "0")

    def test_public_raw_and_catalog_list_preserve_unknown_weight(self):
        warehouse = SimpleNamespace(warehouse_number="WH", warehouse_name="材料仓")
        zone = SimpleNamespace(pk=uuid4(), warehouse_id=uuid4(), zone_name="库区", warehouse=warehouse)
        common = dict(raw_bar_length_m=Decimal("6"), quantity=Decimal("2"), meter_quantity=Decimal("12"),
            bar_weight_kg=None, weight_quantity=None, zone=zone, raw_material=self.material,
            inbound_count=1, latest_inbound_time=None, unit=self.material.unit)
        raw = SimpleNamespace(pk=uuid4(), stock_kind="RAW_PIPE", **common)
        catalog = SimpleNamespace(pk=uuid4(), stock_kind="CATALOG_RAW", material_catalog_id=self.catalog.material_catalog_id,
            identity_key="key", identity_snapshot=self.catalog.identity_snapshot, **common)
        with patch("apps.inventory.public_inventory_queries.material_inventory_rows") as ordinary, \
                patch("apps.inventory.public_inventory_queries.PublicStockBalance.objects.filter") as public:
            ordinary_rows = ordinary.return_value.filter.return_value.filter.return_value.exclude.return_value
            ordinary_rows.count.return_value = 0
            ordinary_rows.order_by.return_value.__getitem__.return_value = []
            public_rows = public.return_value.filter.return_value.select_related.return_value
            public_rows.count.return_value = 2
            public_rows.annotate.return_value.order_by.return_value.__getitem__.return_value = [raw, catalog]
            count, rows = public_raw_inventory_page(page=1, page_size=20)
        self.assertEqual(count, 2)
        self.assertTrue(all(row["weight_quantity"] is None for row in rows))

    def test_available_catalog_weight_excludes_reserved_roots_proportionally(self):
        result = self.catalog_summary(roots=5, weights=Decimal("7.3"), missing=0, free=[
            {"quantity": Decimal("3"), "available_quantity": Decimal("1"), "weight_quantity": Decimal("4.1")},
            {"quantity": Decimal("2"), "available_quantity": Decimal("2"), "weight_quantity": Decimal("3.2")},
        ])
        self.assertEqual(result["weight_quantity"], "7.3")
        self.assertEqual(result["available_quantity"], "3")
        self.assertEqual(result["available_weight_quantity"], "4.5667")

    def test_available_catalog_unknown_weight_stays_unknown_unless_no_roots_are_free(self):
        for free_roots, expected in ((Decimal("1"), None), (Decimal("0"), "0")):
            with self.subTest(free_roots=free_roots):
                result = self.catalog_summary(roots=3, weights=None, missing=1, free=[
                    {"quantity": Decimal("3"), "available_quantity": free_roots, "weight_quantity": None},
                ])
                self.assertEqual(result["available_weight_quantity"], expected)

    def test_public_available_weight_matches_current_weight(self):
        for weight, missing in ((Decimal("4.1"), 0), (None, 1)):
            with self.subTest(weight=weight):
                result = self.public_summary(roots=3, weights=weight, missing=missing)
                self.assertEqual(result["available_weight_quantity"], result["weight_quantity"])
