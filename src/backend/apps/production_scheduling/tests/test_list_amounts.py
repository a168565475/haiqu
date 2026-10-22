from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from apps.production_scheduling import list_amounts as amounts


class ScheduleListAmountsTests(SimpleTestCase):
    def summary(self, *, schemes=(), reported=(), report_count=0, scope=None, craft_ids=(3,)):
        link = SimpleNamespace(pk=3, craft_id=4, craft_type_snapshot="INTERNAL",
                               craft=SimpleNamespace(workshop_id=5))
        product = SimpleNamespace(pk=2, product_line_id=6, planned_quantity=100, active_crafts=[link])
        schedule = SimpleNamespace(pk=1, active_products=[product])
        with (
            patch.object(amounts, "_workshop_scope", return_value=scope),
            patch.object(amounts.ProductionScheduleProduct.objects, "filter") as products,
            patch.object(amounts.ProductionScheduleProductCraft.objects, "filter") as crafts,
            patch.object(amounts.WageScheme.objects, "filter") as wages,
            patch.object(amounts.WorkReportLine.objects, "filter") as reports,
            patch.object(amounts, "accessible_work_reports", return_value=[]),
        ):
            products.return_value.values.return_value.annotate.return_value.values_list.return_value = [(1, 1)]
            crafts.return_value.values_list.return_value = [(1, key) for key in craft_ids]
            wages.return_value.prefetch_related.return_value = schemes
            report_query = reports.return_value.values.return_value.annotate.return_value
            report_query.values_list.return_value = [(1, report_count)]
            report_query.__iter__.return_value = reported
            return amounts.schedule_list_amounts(object(), [schedule])["1"]

    def scheme(self):
        line = SimpleNamespace(status="ACTIVE", required_quantity_snapshot=Decimal(200),
                               order_quantity_snapshot=100, declared_price=Decimal("0.1234"))
        return SimpleNamespace(product_line_id=6, scope_craft_id=4, effective_to=None,
                               lines=SimpleNamespace(all=lambda: [line]))

    def test_no_scheme_and_no_reports_are_zero(self):
        self.assertEqual(self.summary(), {"estimated_wage": "0.00", "reported_amount": "0.00"})

    def test_wage_uses_required_count_and_reported_uses_recorded_amount(self):
        result = self.summary(schemes=[self.scheme()], report_count=2, reported=[{
            "report__schedule_product__schedule_id": 1, "total": 2, "amount": Decimal("12.34"),
        }])
        self.assertEqual(result, {"estimated_wage": "24.68", "reported_amount": "12.34"})

    def test_permissions_partial_scope_and_hidden_reports_are_not_zero(self):
        self.assertEqual(self.summary(scope=set()), {"estimated_wage": None, "reported_amount": None})
        self.assertEqual(self.summary(craft_ids=(3, 7)), {"estimated_wage": None, "reported_amount": None})
        self.assertIsNone(self.summary(report_count=1)["reported_amount"])

    def test_conflicting_or_incomplete_wage_basis_stays_unknown(self):
        scheme = self.scheme()
        self.assertIsNone(self.summary(schemes=[scheme, scheme])["estimated_wage"])
        scheme.lines.all()[0].order_quantity_snapshot = 50
        self.assertIsNone(self.summary(schemes=[scheme])["estimated_wage"])
