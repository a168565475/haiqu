from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.procurement.api.group_serializers import PurchaseGroupProgressSerializer
from apps.procurement.group_selectors import purchase_group_progress


def related(items):
    return SimpleNamespace(all=lambda: items)


class PurchaseGroupInProgressTests(SimpleTestCase):
    def setUp(self):
        self.material_id = uuid4()
        self.batches = []
        self.source = SimpleNamespace(
            pk=uuid4(), line_number=1, source_bom_line_id_snapshot=uuid4(), product_line_id_snapshot=uuid4(),
            required_quantity=Decimal("100"), source_unit_text="米", compatibility_issues=[],
            source_snapshot={"section_type_snapshot": "PROFILE", "raw_material_snapshot": "管材",
                             "calculation_snapshot": {"raw_material_id": str(self.material_id)}},
            batch_lines=related(self.batches),
        )
        self.group = SimpleNamespace(pk=uuid4(), compatibility_issues=[], lines=related([self.source]))

    def batch(self, quantity="100", roots=50, *, status="PURCHASING", archived=False):
        line = SimpleNamespace(
            purchase_order=SimpleNamespace(pk=uuid4(), purchase_group_id=self.group.pk, status=status,
                                           archived_at="archived" if archived else None, batch_request_id=uuid4()),
            calculation_snapshot={"raw_material_id": str(self.material_id)}, source_unit_text="米",
            required_quantity=self.source.required_quantity, source_bom_line_id_snapshot=self.source.source_bom_line_id_snapshot,
            actual_purchase_quantity=Decimal(quantity), actual_bar_count=roots,
            raw_material_snapshot="管材", material_inbound_lines=related([]),
        )
        self.batches.append(line)
        return line

    def inbound(self, quantity="60", roots=30, *, status="CONFIRMED"):
        return SimpleNamespace(
            inbound_id=uuid4(), inbound=SimpleNamespace(status=status), source_unit_text_snapshot="米",
            raw_material_information_id=self.material_id, accepted_quantity=Decimal(quantity), accepted_bar_count=roots,
            return_quantity=Decimal("0"), return_bar_count=0,
        )

    def data(self):
        return PurchaseGroupProgressSerializer(purchase_group_progress(self.group)).data

    def test_active_orders_count_until_quality_is_confirmed(self):
        first = self.batch(status="SUBMITTED")
        first.material_inbound_lines = related([self.inbound(status="PENDING_QUALITY")])
        second = self.batch()
        second.material_inbound_lines = related([self.inbound()])
        result = self.data()
        item = result["lines"][0]
        self.assertEqual((item["in_progress_quantity"], item["in_progress_bar_count"]), ("140.0000", "70"))
        self.assertEqual((item["purchased_quantity"], item["accepted_quantity"], item["progress_percent"]),
                         ("200.0000", "60.0000", "60.0000"))
        self.assertEqual(result["status"], "PURCHASING")

    def test_closed_draft_and_archived_batches_have_no_in_progress_quantity(self):
        for status, archived in [("DRAFT", False), ("COMPLETED", False), ("PURCHASING", True)]:
            self.batch(roots=None, status=status, archived=archived)
        item = self.data()["lines"][0]
        self.assertEqual((item["in_progress_quantity"], item["in_progress_bar_count"]), ("0.0000", "0"))
        self.assertEqual(item["purchased_quantity"], "100.0000")

    def test_each_batch_is_clamped_before_summing(self):
        fulfilled = self.batch()
        fulfilled.material_inbound_lines = related([self.inbound("120", 60)])
        self.batch("50", 25)
        result = self.data()
        item = result["lines"][0]
        self.assertEqual((item["in_progress_quantity"], item["in_progress_bar_count"]), ("50.0000", "25"))
        self.assertEqual(item["progress_percent"], "120.0000")
        self.assertEqual(result["status"], "COMPLETED")

    def test_empty_pipe_is_zero_and_general_material_has_no_bar_count(self):
        item = self.data()["lines"][0]
        self.assertEqual((item["in_progress_quantity"], item["in_progress_bar_count"]), ("0.0000", "0"))
        self.source.source_snapshot["section_type_snapshot"] = "MATERIAL"
        self.batch("10", None)
        item = self.data()["lines"][0]
        self.assertEqual(item["in_progress_quantity"], "10.0000")
        self.assertIsNone(item["in_progress_bar_count"])

    def test_unknown_purchase_roots_remain_null_in_any_order(self):
        self.batch(roots=None)
        self.batch("50", 25)
        for reverse in (False, True):
            if reverse:
                self.batches.reverse()
            result = self.data()
            item = result["lines"][0]
            self.assertEqual(item["in_progress_quantity"], "150.0000")
            self.assertIsNone(item["in_progress_bar_count"])
            self.assertEqual(item["compatibility_issues"], [])
            self.assertEqual(result["status"], "PURCHASING")

    def test_unknown_accepted_roots_preserve_known_quantity_and_progress(self):
        first = self.batch()
        receipts = [self.inbound("60", None), self.inbound("20", 10)]
        first.material_inbound_lines = related(receipts)
        for reverse in (False, True):
            if reverse:
                receipts.reverse()
            result = self.data()
            item = result["lines"][0]
            self.assertEqual(item["in_progress_quantity"], "20.0000")
            self.assertIsNone(item["in_progress_bar_count"])
            self.assertEqual(item["progress_percent"], "80.0000")
            self.assertEqual(item["compatibility_issues"], [])
            self.assertEqual(result["status"], "PURCHASING")

    def test_existing_source_mismatch_does_not_expose_partial_in_progress_totals(self):
        self.batch()
        invalid = self.batch()
        invalid.source_bom_line_id_snapshot = uuid4()
        result = self.data()
        item = result["lines"][0]
        self.assertIsNone(item["in_progress_quantity"])
        self.assertIsNone(item["in_progress_bar_count"])
        self.assertEqual(item["compatibility_issues"], ["BATCH_SOURCE_MISMATCH"])
        self.assertEqual(result["status"], "UNKNOWN")

    def test_exact_strings_preserve_large_roots_and_small_decimal_remainders(self):
        roots = 9007199254740993
        first = self.batch("1234567890123456789012345.6789", roots)
        first.material_inbound_lines = related([self.inbound("0.0001", 0)])
        self.batch("0.0001", 7)
        item = self.data()["lines"][0]
        self.assertEqual(item["in_progress_quantity"], "1234567890123456789012345.6789")
        self.assertEqual(item["in_progress_bar_count"], "9007199254741000")
