from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.procurement.api.group_serializers import PurchaseGroupProgressSerializer
from apps.procurement.group_selectors import purchase_group_progress


def related(items):
    return SimpleNamespace(all=lambda: items)


class PurchaseGroupBarDisplayTests(SimpleTestCase):
    def setUp(self):
        self.material_id = uuid4()
        self.batches = []
        self.source = SimpleNamespace(
            pk=uuid4(), line_number=1, source_bom_line_id_snapshot=uuid4(), product_line_id_snapshot=uuid4(),
            required_quantity=Decimal("100"), source_unit_text="米", compatibility_issues=[],
            source_snapshot={"section_type_snapshot": "PROFILE", "raw_bar_length_m": "2", "suggested_bar_count": 50,
                             "raw_material_snapshot": "管材", "calculation_snapshot": {"raw_material_id": str(self.material_id)}},
            batch_lines=related(self.batches),
        )
        self.group = SimpleNamespace(pk=uuid4(), compatibility_issues=[], lines=related([self.source]))

    def batch(self, roots=10, *, quantity="20", status="PURCHASING", archived=False):
        line = SimpleNamespace(
            purchase_order=SimpleNamespace(purchase_group_id=self.group.pk, status=status,
                                           archived_at="archived" if archived else None, batch_request_id=uuid4()),
            calculation_snapshot={"raw_material_id": str(self.material_id)}, source_unit_text="米",
            required_quantity=self.source.required_quantity, source_bom_line_id_snapshot=self.source.source_bom_line_id_snapshot,
            actual_purchase_quantity=Decimal(quantity), actual_bar_count=roots,
            raw_material_snapshot="管材", material_inbound_lines=related([]),
        )
        self.batches.append(line)
        return line

    def inbound(self, roots=10, *, quantity="20", status="CONFIRMED", returned=0):
        return SimpleNamespace(inbound=SimpleNamespace(status=status), source_unit_text_snapshot="米",
                               raw_material_information_id=self.material_id, accepted_quantity=Decimal(quantity),
                               accepted_bar_count=roots, received_bar_count=(roots or 0) + returned, return_bar_count=returned)

    def test_sums_saved_roots_with_accepted_roots_without_deducting_returns_twice(self):
        first = self.batch(15, quantity="30")
        second = self.batch(5, quantity="10")
        first.material_inbound_lines = related([self.inbound(10, quantity="20", returned=5)])
        second.material_inbound_lines = related([self.inbound(2, quantity="4")])
        frozen = deepcopy(self.source.source_snapshot)
        result = purchase_group_progress(self.group)
        line = result["lines"][0]
        self.assertEqual((line["purchased_bar_count"], line["accepted_bar_count"]), (20, 12))
        self.assertEqual((line["purchased_quantity"], line["accepted_quantity"], line["progress_percent"]),
                         (Decimal("40"), Decimal("24"), Decimal("24.0000")))
        self.assertEqual(result["status"], "PURCHASING")
        self.assertEqual(self.source.source_snapshot, frozen)

    def test_drafts_archived_orders_and_unconfirmed_inbounds_do_not_contribute(self):
        self.batch(None, status="DRAFT")
        self.batch(None, archived=True)
        self.batch(3, quantity="6", status="SUBMITTED")
        self.batch(2, quantity="4", status="COMPLETED")
        active = self.batch(2, quantity="4")
        active.material_inbound_lines = related([self.inbound(2, quantity="4"), self.inbound(None, status="PENDING_QUALITY")])
        line = purchase_group_progress(self.group)["lines"][0]
        self.assertEqual((line["purchased_bar_count"], line["accepted_bar_count"]), (7, 2))
        self.assertEqual(line["compatibility_issues"], [])

    def test_empty_pipe_totals_are_zero_and_non_pipe_totals_are_null(self):
        line = PurchaseGroupProgressSerializer(purchase_group_progress(self.group)).data["lines"][0]
        self.assertEqual((line["purchased_bar_count"], line["accepted_bar_count"]), ("0", "0"))
        self.source.source_snapshot["section_type_snapshot"] = "MATERIAL"
        line = purchase_group_progress(self.group)["lines"][0]
        self.assertIsNone(line["purchased_bar_count"])
        self.assertIsNone(line["accepted_bar_count"])

    def test_missing_purchase_roots_stay_unknown_without_changing_completion(self):
        missing = self.batch(None, quantity="100")
        missing.material_inbound_lines = related([self.inbound(50, quantity="100")])
        self.batch(2, quantity="4")
        for reverse in (False, True):
            if reverse:
                self.batches.reverse()
            result = purchase_group_progress(self.group)
            line = result["lines"][0]
            self.assertIsNone(line["purchased_bar_count"])
            self.assertEqual(line["accepted_bar_count"], 50)
            self.assertEqual(line["purchased_quantity"], Decimal("104"))
            self.assertEqual(line["compatibility_issues"], [])
            self.assertTrue(line["is_satisfied"])
            self.assertEqual(result["status"], "COMPLETED")

    def test_missing_accepted_roots_stay_unknown_without_changing_meter_progress(self):
        batch = self.batch(60, quantity="120")
        inbounds = [self.inbound(None, quantity="100"), self.inbound(10, quantity="20")]
        batch.material_inbound_lines = related(inbounds)
        for reverse in (False, True):
            if reverse:
                inbounds.reverse()
            result = purchase_group_progress(self.group)
            line = result["lines"][0]
            self.assertEqual(line["purchased_bar_count"], 60)
            self.assertIsNone(line["accepted_bar_count"])
            self.assertEqual(line["progress_percent"], Decimal("120.0000"))
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(line["compatibility_issues"], [])

    def test_existing_source_mismatch_does_not_expose_partial_root_totals(self):
        self.batch(10)
        invalid = self.batch(100, quantity="200")
        invalid.source_bom_line_id_snapshot = uuid4()
        result = purchase_group_progress(self.group)
        line = result["lines"][0]
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(line["compatibility_issues"], ["BATCH_SOURCE_MISMATCH"])
        self.assertIsNone(line["purchased_bar_count"])
        self.assertIsNone(line["accepted_bar_count"])
        self.assertIsNone(line["purchased_quantity"])

    def test_inbound_identity_mismatch_preserves_existing_unknown_state(self):
        line = self.batch(10)
        inbound = self.inbound(10)
        inbound.source_unit_text_snapshot = "千克"
        line.material_inbound_lines = related([inbound])
        result = purchase_group_progress(self.group)
        item = result["lines"][0]
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(item["compatibility_issues"], ["INBOUND_IDENTITY_OR_UNIT_MISMATCH"])
        self.assertIsNone(item["accepted_bar_count"])

    def test_large_root_sum_serializes_as_exact_string(self):
        large = 9007199254740993
        first = self.batch(large, quantity=str(large * 2))
        first.material_inbound_lines = related([self.inbound(large, quantity=str(large * 2))])
        second = self.batch(7, quantity="14")
        second.material_inbound_lines = related([self.inbound(7, quantity="14")])
        data = PurchaseGroupProgressSerializer(purchase_group_progress(self.group)).data["lines"][0]
        self.assertEqual(data["purchased_bar_count"], "9007199254741000")
        self.assertEqual(data["accepted_bar_count"], "9007199254741000")
