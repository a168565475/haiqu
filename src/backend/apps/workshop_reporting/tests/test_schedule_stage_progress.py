"""展示计算的定向单元测试；查询替身不代表真实入库或权限验收。"""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.workshop_reporting import schedule_stage_progress as progress


class ScheduleStageProgressTests(SimpleTestCase):
    def test_outbound_uses_order_quantity_even_when_received_stock_is_all_shipped(self):
        first, second = self.make_product(), self.make_product()
        schedule = SimpleNamespace(active_products=[first, second], stage_product_count=2)
        received = {first.product_line_id: 50}
        result = progress._outbound_progress(schedule, received, {first.product_line_id: 20})
        self.assertEqual(result["percentage"], 10)
        self.assertEqual([item["percentage"] for item in result["products"]], [20, 0])
        self.assertEqual(result["products"][0]["received_quantity"], 50)
        self.assertEqual(result["products"][0]["order_quantity"], 100)
        self.assertEqual(result["products"][0]["outbound_quantity"], 20)
        self.assertEqual(progress._outbound_progress(schedule, {}, {})["percentage"], 0)
        self.assertEqual(progress._outbound_progress(schedule, received, received)["percentage"], 25)
        complete = {first.product_line_id: 100, second.product_line_id: 100}
        self.assertEqual(progress._outbound_progress(schedule, complete, complete)["percentage"], 100)
        self.assertEqual(progress._outbound_progress(schedule, complete, {first.product_line_id: 200})["percentage"], 50)

    def test_outbound_missing_permission_hidden_product_and_partial_schedule(self):
        product = self.make_product()
        schedule = SimpleNamespace(active_products=[product], stage_product_count=1)
        received = {product.product_line_id: 50}
        self.assertIsNone(progress._outbound_progress(schedule, received, None)["percentage"])
        self.assertIsNone(progress._outbound_progress(schedule, received, None)["products"][0]["received_quantity"])
        schedule.stage_product_count = 2
        self.assertIsNone(progress._outbound_progress(schedule, received, received)["percentage"])
        schedule.stage_product_count = 1
        product.planned_quantity = 50
        self.assertIsNone(progress._outbound_progress(schedule, received, received)["percentage"])

    def make_link(self, category, *, external=False):
        return SimpleNamespace(
            pk=uuid.uuid4(), craft_type_snapshot="EXTERNAL" if external else "INTERNAL",
            plan_category=None if external else category,
            craft_id=uuid.uuid4(),
            craft=SimpleNamespace(workshop_id=uuid.uuid4(), outsourcing_code=category if external else None),
        )

    def make_product(self, *, quantity=100, links=None):
        return SimpleNamespace(
            pk=uuid.uuid4(), product_line_id=uuid.uuid4(),
            product_line=SimpleNamespace(quantity=quantity),
            planned_quantity=quantity, source_quantity_snapshot=quantity,
            active_crafts=links or [], metal_return_date=date(2026, 10, 24),
            sewing_return_date=date(2026, 10, 29), finished_inbound_date=date(2026, 10, 31),
        )

    def test_last_fraction_is_not_reported_as_complete(self):
        self.assertEqual(progress._percentage(progress._metric("READY", 100, Decimal("99.9999"))), 99)
        self.assertEqual(progress._percentage(progress._metric("READY", 100, 100)), 100)
        self.assertIsNone(progress._percentage(progress._metric("NOT_CONFIGURED")))

    def test_not_applicable_and_missing_values_do_not_average_known_products(self):
        product = self.make_product()
        absent = self.reporting_result(product, [], category="METAL")
        self.assertEqual(absent["status"], "NOT_APPLICABLE")
        self.assertIsNone(progress._percentage(absent))
        for missing in (absent, progress._metric()):
            with self.subTest(status=missing["status"]):
                mixed = progress._aggregate([progress._metric("READY", 100, 100), missing])
                self.assertEqual(mixed["status"], "NOT_CONFIGURED")
                self.assertIsNone(progress._percentage(mixed))

    def reporting_result(self, product, links, *, category="CUTTING", lines=None, quantities=()):
        internal = next((link for link in links if link.craft_type_snapshot == "INTERNAL"), None)
        candidates = [] if lines is None else [SimpleNamespace(
            product_line_id=product.product_line_id, workshop_id=internal.craft.workshop_id,
            scope_craft_id=internal.craft_id, lines=SimpleNamespace(all=lambda: lines),
        )]
        with (
            patch.object(progress.WageScheme.objects, "filter") as schemes,
            patch.object(progress.WorkReportLine.objects, "filter") as reports,
        ):
            schemes.return_value.filter.return_value.prefetch_related.return_value = candidates
            reports.return_value.values.return_value.annotate.return_value = [
                {"report__schedule_product_id": product.pk, "work_item_id": item, "quantity": quantity,
                 "report__scheme__scope_craft__plan_category": category}
                for item, quantity in quantities
            ]
            result = progress._internal_reporting_metrics([product], {product.pk: links}, date(2026, 10, 22))
            self.assertIn("report__scheme__scope_craft__plan_category", reports.return_value.values.call_args.args)
            self.assertEqual(reports.call_args.kwargs["report__scheme__scope_craft__craft_type"], "INTERNAL")
            return result[category][product.pk]

    def test_conflicting_candidates_or_changed_order_quantity_remain_unknown(self):
        link = self.make_link("METAL")
        product = self.make_product(links=[link])
        scope = (product.product_line_id, link.craft.workshop_id, link.craft_id)
        scopes = {product.pk: ({scope}, True)}
        line = SimpleNamespace(status="ACTIVE", order_quantity_snapshot=99)
        scheme = SimpleNamespace(lines=SimpleNamespace(all=lambda: [line]))
        for candidates in ([scheme, scheme], [scheme]):
            with self.subTest(candidate_count=len(candidates)):
                metric = progress._category_reporting_metrics([product], scopes, {scope: candidates}, {})[product.pk]
                self.assertEqual(metric["status"], "NOT_CONFIGURED")
                self.assertIsNone(progress._percentage(metric))

    def test_external_cutting_alone_is_not_part_of_internal_progress(self):
        link = self.make_link("CUTTING", external=True)
        product = self.make_product(links=[link])
        self.assertEqual(self.reporting_result(product, [link])["status"], "NOT_APPLICABLE")

    def test_unfilled_internal_cutting_shows_zero_even_with_external_cutting(self):
        links = [self.make_link("CUTTING"), self.make_link("CUTTING", external=True)]
        product = self.make_product(links=links)
        for lines in (None, []):
            with self.subTest(lines=lines):
                metric = self.reporting_result(product, links, lines=lines)
                self.assertEqual(metric["status"], "READY")
                self.assertEqual(progress._percentage(metric), 0)

    def test_all_internal_stages_use_reports_without_inventory_receipts(self):
        for category in ("METAL", "CUTTING", "SEWING"):
            links = [self.make_link(category), self.make_link(category, external=True)]
            product = self.make_product(links=links)
            lines = [SimpleNamespace(
                work_item_id=uuid.uuid4(), status="ACTIVE", required_quantity_snapshot=Decimal(100),
                order_quantity_snapshot=100,
            ) for _ in range(2)]
            for quantities, expected in (
                ([], 0),
                ([(lines[0].work_item_id, 50), (lines[1].work_item_id, 50)], 50),
                ([(lines[0].work_item_id, 200)], 50),
                ([(line.work_item_id, 100) for line in lines], 100),
            ):
                with self.subTest(category=category, expected=expected, quantities=quantities):
                    metric = self.reporting_result(product, links, category=category, lines=lines, quantities=quantities)
                    self.assertEqual(progress._percentage(metric), expected)
            for lines_value in (None, []):
                with self.subTest(category=category, lines=lines_value):
                    metric = self.reporting_result(product, links, category=category, lines=lines_value)
                    self.assertEqual(progress._percentage(metric), 0)
            lines[0].required_quantity_snapshot = None
            self.assertEqual(progress._percentage(self.reporting_result(product, links, category=category, lines=lines)), 0)
            product.active_crafts = []
            self.assertIsNone(progress._percentage(self.reporting_result(product, links, category=category)))

    def test_hidden_internal_cutting_is_not_defaulted_to_zero(self):
        link = self.make_link("CUTTING")
        product = self.make_product()
        self.assertIsNone(progress._percentage(self.reporting_result(product, [link])))

    def test_unfilled_cutting_is_zero_and_does_not_use_partial_denominator(self):
        unfilled = progress._metric("READY")
        self.assertEqual(progress._percentage(unfilled), 0)
        combined = progress._aggregate([unfilled, progress._metric("READY", 100, 100)])
        self.assertEqual(progress._percentage(combined), 0)
        product = self.make_product(links=[self.make_link("ASSEMBLY")])
        self.assertEqual(self.summary([product], [], cutting=unfilled)["overall_percentage"], 25)

    def summary(self, products, receipts, *, total_count=None, cutting=None):
        schedule = SimpleNamespace(
            pk=uuid.uuid4(), active_products=products,
            stage_product_count=len(products) if total_count is None else total_count,
        )
        links = [SimpleNamespace(
            pk=link.pk, schedule_product_id=product.pk, plan_category=link.plan_category,
        ) for product in products for link in product.active_crafts]
        with (
            patch.object(progress, "schedules_with_context", return_value=[schedule]),
            patch.object(progress, "schedule_outsourcing_statuses", return_value={str(schedule.pk): {}}),
            patch.object(progress.ProductionScheduleProductCraft.objects, "filter") as craft_query,
            patch.object(progress, "_internal_reporting_metrics", side_effect=lambda products, links, day: {
                category: {
                    product.pk: (cutting or progress._metric("READY", 100, 0)) if category == "CUTTING"
                    else progress._metric("READY", 100, 100 if category == "METAL" else 0)
                    for product in products
                } for category in ("METAL", "CUTTING", "SEWING")
            }),
            patch.object(progress.FinishedGoodsReceipt.objects, "filter") as receipt_query,
        ):
            craft_query.return_value.select_related.return_value = links
            receipt_query.return_value.values.return_value.annotate.return_value.values_list.return_value = receipts
            return progress.schedule_stage_progress_statuses(
                [schedule.pk], request=SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: False)), as_of_date=date(2026, 10, 22),
            )[str(schedule.pk)]

    def test_overall_weights_all_four_stages_and_caps_each_product(self):
        first = self.make_product(links=[self.make_link("ASSEMBLY")])
        second = self.make_product(links=[self.make_link("ASSEMBLY")])
        row = self.summary([first, second], [(first.product_line_id, 200)])
        self.assertEqual(row["stage_progress"]["ASSEMBLY"]["percentage"], 50)
        self.assertEqual(row["overall_percentage"], 37)
        self.assertEqual(row["as_of_date"], "2026-10-22")
        self.assertEqual(row["stage_progress"]["CUTTING"]["products"][0]["planned_date"], "2026-10-29")

    def test_missing_stage_partial_schedule_or_hidden_product_keeps_total_unknown(self):
        product = self.make_product(links=[self.make_link("ASSEMBLY")])
        receipts = [(product.product_line_id, 100)]
        unknown_cutting = self.summary([product], receipts, cutting=progress._metric())
        self.assertIsNone(unknown_cutting["overall_percentage"])
        restricted = self.summary([product], receipts, total_count=2)
        self.assertIsNone(restricted["overall_percentage"])
        self.assertIsNone(restricted["stage_progress"]["ASSEMBLY"]["percentage"])
        self.assertEqual(restricted["stage_progress"]["ASSEMBLY"]["products"], [{
            "schedule_product_id": str(product.pk), "status": "READY", "percentage": 100,
            "planned_date": "2026-10-31",
        }])
        product.planned_quantity = 50
        self.assertIsNone(self.summary([product], receipts)["overall_percentage"])
