from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.workshop_reporting.schedule_outsourcing_status import (
    outsourcing_order_statuses, outsourcing_record_status, outsourcing_stage_status, schedule_outsourcing_statuses,
)


class ScheduleOutsourcingStatusTests(SimpleTestCase):
    today = date(2026, 10, 22)

    def record(self, *, days=8, returned="0", status="PROCESSING", **overrides):
        return {"id": "order:line", "order_number": "WF-001", "craft_name": "喷塑",
                "part_name": "前脚", "factory_name": "加工厂", "quantity_unit": "支",
                "planned_quantity": "100", "received_quantity": returned,
                "expected_return_date": self.today + timedelta(days=days), "status": status, **overrides}

    def test_deadlines_escalate_only_for_unreturned_orders(self):
        for days, risk in [(8, "normal"), (7, "attention"), (4, "attention"), (3, "slow"),
                           (2, "slow"), (1, "urgent"), (0, "urgent"), (-1, "urgent")]:
            with self.subTest(days=days):
                row = outsourcing_record_status(self.record(days=days, returned="40"), self.today)
                self.assertEqual(row["risk"], risk)
                self.assertEqual(row["remaining_quantity"], "60")
                if risk == "urgent":
                    self.assertIn("阻塞风险", row["description"])

    def test_returned_order_clears_expired_deadline(self):
        row = outsourcing_record_status(self.record(days=-10, returned="100"), self.today)
        self.assertEqual((row["state"], row["risk"]), ("RETURNED", "normal"))

    def test_pending_dispatch_still_warns_about_deadline(self):
        row = outsourcing_record_status(self.record(days=0, status="PENDING_DISPATCH"), self.today)
        self.assertEqual((row["state"], row["risk"]), ("WAITING", "urgent"))
        self.assertIn("尚未发出", row["description"])

    def test_closed_with_shortage_is_not_returned(self):
        row = outsourcing_record_status(self.record(status="COMPLETED", returned="95"), self.today)
        self.assertEqual((row["state"], row["risk"]), ("SHORTAGE", "slow"))
        self.assertEqual(row["remaining_quantity"], "5")

    def test_missing_receipt_or_due_date_is_unknown(self):
        row = outsourcing_record_status(self.record(returned=None), self.today)
        self.assertEqual((row["state"], row["risk"]), ("UNKNOWN", "unknown"))
        self.assertIsNone(row["remaining_quantity"])
        row = outsourcing_record_status(self.record(expected_return_date=None), self.today)
        self.assertEqual(row["risk"], "unknown")

    def test_stage_uses_worst_pending_order_and_does_not_add_different_units(self):
        rows = [outsourcing_record_status(self.record(days=9, id="a", quantity_unit="套"), self.today),
                outsourcing_record_status(self.record(days=1, id="b"), self.today),
                outsourcing_record_status(self.record(days=-2, id="c", returned="100"), self.today)]
        stage = outsourcing_stage_status(rows)
        self.assertEqual(stage["risk"], "urgent")
        self.assertEqual(stage["records"][0]["id"], "b")
        self.assertNotIn("percentage", stage)
        self.assertEqual(outsourcing_stage_status([rows[2]])["state"], "RETURNED")

    def test_absence_and_permission_gaps_are_distinct(self):
        self.assertEqual(outsourcing_stage_status([])["state"], "NONE")
        self.assertEqual(outsourcing_stage_status([], allowed=False)["state"], "UNKNOWN")
        self.assertEqual(outsourcing_stage_status([], complete_scope=False)["state"], "UNKNOWN")

    def order_line(self, *, order_id="order-1", order_kind="TUBE", **overrides):
        return {**outsourcing_record_status(self.record(**overrides), self.today),
                "order_id": order_id, "order_kind": order_kind}

    def test_order_groups_parts_and_does_not_expose_product_or_part_fields(self):
        rows = [self.order_line(planned_quantity="400", part_name=part) for part in ("前脚", "后脚")]
        result = outsourcing_order_statuses(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "TUBE:order-1")
        self.assertEqual(result[0]["remaining_display"], "800 支")
        self.assertNotIn("part_name", result[0])
        self.assertNotIn("schedule_product_id", result[0])

    def test_order_does_not_offset_shortage_with_other_part_over_return(self):
        rows = [self.order_line(returned="200"), self.order_line(returned="0", days=1)]
        result = outsourcing_order_statuses(rows)[0]
        self.assertEqual(result["remaining_quantity"], "100")
        self.assertEqual((result["state"], result["risk"]), ("IN_PROGRESS", "urgent"))
        self.assertEqual(outsourcing_order_statuses([rows[0]])[0]["state"], "RETURNED")

    def test_order_keeps_units_separate_and_missing_quantity_unknown(self):
        rows = [self.order_line(returned="20"), self.order_line(quantity_unit="套", returned="50")]
        result = outsourcing_order_statuses(rows)[0]
        self.assertEqual(set(result["remaining_display"].split(" / ")), {"80 支", "50 套"})
        self.assertIsNone(result["remaining_quantity"])
        rows.append(self.order_line(returned=None))
        result = outsourcing_order_statuses(rows)[0]
        self.assertEqual(set(result["remaining_display"].split(" / ")), {"— 支", "50 套"})

    def test_different_order_ids_and_sources_never_merge_by_order_number(self):
        result = outsourcing_order_statuses([
            self.order_line(), self.order_line(order_id="order-2"), self.order_line(order_kind="P4"),
        ])
        self.assertEqual(len(result), 3)

    def test_schedule_groups_same_order_across_products_for_both_external_stages(self):
        module = "apps.workshop_reporting.schedule_outsourcing_status"
        products = [SimpleNamespace(product_line_id=value, schedule_id="s1") for value in ("p1", "p2")]
        schedule = SimpleNamespace(pk="s1", production_task_id="t1", active_products=products, stage_product_count=2)
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: True))
        records = [(product.product_line_id, self.record(
            order_kind="TUBE", order_id=craft, craft_code=craft,
        )) for product in products for craft in ("POWDER_COATING", "SCREEN_PRINTING")]
        with (
            patch(f"{module}._sources_for_tasks") as sources,
            patch(f"{module}._regular_records", return_value=[]),
            patch(f"{module}._tube_records", return_value=records),
            patch(f"{module}._p4_records", return_value=[]),
            patch(f"{module}._projected_records", return_value=[]),
        ):
            sources.return_value = (sources, sources, sources, request)
            result = schedule_outsourcing_statuses([schedule], request=request, as_of_date=self.today)["s1"]
        for stage in ("METAL", "SEWING"):
            self.assertEqual(len(result[stage]["records"]), 1)
            self.assertEqual(result[stage]["records"][0]["remaining_display"], "200 支")

    def test_without_permission_does_not_query_external_sources(self):
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: False))
        schedule = SimpleNamespace(pk="s1", production_task_id="t1", active_products=[], stage_product_count=0)
        with patch("apps.workshop_reporting.schedule_outsourcing_status._sources_for_tasks") as sources:
            result = schedule_outsourcing_statuses([schedule], request=request, as_of_date=self.today)
        sources.assert_not_called()
        self.assertEqual(result["s1"]["METAL"]["state"], "UNKNOWN")
        self.assertEqual(result["s1"]["SEWING"]["state"], "UNKNOWN")
