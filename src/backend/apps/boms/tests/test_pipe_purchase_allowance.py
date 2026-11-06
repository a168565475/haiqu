from decimal import Decimal

from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings

from apps.procurement.pipe_purchase import pipe_source_snapshot, purchase_pipe_values
from ..api.serializers import BomLineWriteSerializer
from ..material_flow_calculations import MaterialFlowValueError, pipe_plan
from ..models import BomLine
from ..services import _sync_profile_lines_to_order_quantity, create_bom
from . import test_material_flow_bom as fixtures


class PipePurchaseAllowanceCalculationTests(SimpleTestCase):
    def plan(self, **changes):
        return pipe_plan(**{
            "cutting_length_mm": 500, "pieces_per_product": 1, "pieces_per_bar": 1,
            "order_quantity": 500, "purchase_allowance_mode": "AUTO", **changes,
        })

    def test_automatic_bucket_boundaries(self):
        for base, rule, allowance in ((1, "PLUS_5", 5), (500, "PLUS_5", 5),
                (501, "PLUS_8", 8), (1000, "PLUS_8", 8), (1001, "PERCENT_1", 11),
                (5000, "PERCENT_1", 50), (5001, "PERCENT_1", 51)):
            with self.subTest(base=base):
                result = self.plan(order_quantity=base)
                self.assertEqual((result["base_purchase_bar_count"], result["purchase_allowance_rule"],
                    result["purchase_allowance_bar_count"], result["suggested_bar_count"]),
                    (base, rule, allowance, base + allowance))

    def test_manual_options_are_available_in_every_bucket(self):
        for base in (1, 501, 1001, 5001):
            for rule, extra in (("NONE", 0), ("PLUS_5", 5), ("PLUS_8", 8),
                    ("PERCENT_0_5", (base + 199) // 200), ("PERCENT_1", (base + 99) // 100)):
                with self.subTest(base=base, rule=rule):
                    result = self.plan(order_quantity=base, purchase_allowance_mode="MANUAL", purchase_allowance_rule=rule)
                    self.assertEqual(result["suggested_bar_count"], base + extra)

    def test_round_base_roots_before_percentage_allowance(self):
        result = self.plan(order_quantity=1000, pieces_per_product=2, pieces_per_bar=6,
                           purchase_allowance_mode="MANUAL", purchase_allowance_rule="PERCENT_1")
        self.assertEqual((result["base_purchase_bar_count"], result["purchase_allowance_bar_count"],
                          result["suggested_bar_count"]), (334, 4, 338))

    def test_explicit_new_rule_replaces_source_allowance_without_losing_source(self):
        result = self.plan(source_purchase_allowance_percent="20", purchase_allowance_mode="MANUAL",
                           purchase_allowance_rule="PLUS_8")
        self.assertEqual(result["suggested_bar_count"], 508)
        self.assertEqual(Decimal(result["source_purchase_allowance_percent"]), Decimal("20"))

    def test_legacy_snapshots_do_not_gain_new_keys(self):
        for version, roots in ((2, 505), (3, 500)):
            result = self.plan(calculation_version=version, purchase_allowance_mode=None)
            self.assertEqual(result["suggested_bar_count"], roots)
            self.assertNotIn("base_purchase_bar_count", result)
            self.assertNotIn("purchase_allowance_mode", result)

    def test_version_four_defaults_to_auto_and_invalid_contract_is_rejected(self):
        self.assertEqual(self.plan(calculation_version=4, purchase_allowance_mode=None)["suggested_bar_count"], 505)
        for changes in ({"purchase_allowance_mode": "OTHER"}, {"purchase_allowance_rule": "OTHER"},
                {"purchase_allowance_mode": "MANUAL"}, {"purchase_allowance_mode": "", "purchase_allowance_rule": "PLUS_5"}):
            with self.subTest(changes=changes), self.assertRaises(MaterialFlowValueError):
                self.plan(**changes)

    def test_serializer_rejects_invalid_rule_and_ignores_client_derived_counts(self):
        serializer = BomLineWriteSerializer(data={"part_name": "管材", "purchase_allowance_mode": "MANUAL", "purchase_allowance_rule": "NONE",
                                                 "base_purchase_bar_count": 999, "purchase_allowance_bar_count": 999})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("base_purchase_bar_count", serializer.validated_data)
        self.assertNotIn("purchase_allowance_bar_count", serializer.validated_data)
        for data in ({"purchase_allowance_mode": "MANUAL"}, {"purchase_allowance_rule": "PLUS_5"},
                     {"purchase_allowance_mode": "MANUAL", "purchase_allowance_rule": "OTHER"}):
            serializer = BomLineWriteSerializer(data={"part_name": "管材", **data})
            self.assertFalse(serializer.is_valid())


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class PipePurchaseAllowanceApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    setUp = fixtures.MaterialFlowBomTests.setUp
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    pipe_payload = fixtures.MaterialFlowBomTests.pipe_payload
    save = fixtures.MaterialFlowBomTests.save

    def create_pipe(self, **changes):
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload(**changes)]}])
        self.assertEqual(response.status_code, 200, response.data)
        return BomLine.objects.get(section__bom=self.bom)

    def row(self):
        sections = self.get().data["data"]["sections"]
        return sections, next(section for section in sections if section["section_type"] == "PROFILE")["lines"][0]

    def test_new_pipe_defaults_to_auto_and_derived_counts_cannot_be_spoofed(self):
        line = self.create_pipe(base_purchase_bar_count=1, purchase_allowance_bar_count=999, branch_count="1")
        self.assertEqual((line.branch_count, line.suggested_bar_count, line.total_purchase_quantity), ("339", 339, "1033.95"))
        _, row = self.row()
        self.assertEqual((row["base_purchase_bar_count"], row["purchase_allowance_bar_count"],
                          row["purchase_allowance_mode"], row["purchase_allowance_rule"]), (334, 5, "AUTO", "PLUS_5"))

    def test_manual_zero_survives_save_quantity_sync_and_purchase_snapshot(self):
        line = self.create_pipe(purchase_allowance_mode="MANUAL", purchase_allowance_rule="NONE")
        self.bom.order_quantity = 3000
        self.bom.save(update_fields=["order_quantity"])
        with transaction.atomic():
            _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line.refresh_from_db()
        self.assertEqual((line.suggested_bar_count, line.raw_values["purchase_allowance_rule"]), (1000, "NONE"))
        snapshot = pipe_source_snapshot(line)
        self.assertEqual((snapshot["base_purchase_bar_count"], snapshot["purchase_allowance_bar_count"]), (1000, 0))
        purchase = purchase_pipe_values(snapshot, {})
        self.assertEqual(purchase["calculation_snapshot"], snapshot)
        self.assertEqual(purchase["suggested_bar_count"], 1000)
        sections, row = self.row()
        self.assertEqual(row["purchase_allowance_bar_count"], 0)
        row["notes"] = "保留手选"
        row.pop("purchase_allowance_mode")
        row.pop("purchase_allowance_rule")
        self.assertEqual(self.save(sections).status_code, 200)
        line.refresh_from_db()
        self.assertEqual(line.raw_values["purchase_allowance_mode"], "MANUAL")

    def test_auto_changes_bucket_after_order_quantity_sync(self):
        line = self.create_pipe()
        self.bom.order_quantity = 1501
        self.bom.save(update_fields=["order_quantity"])
        with transaction.atomic():
            _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line.refresh_from_db()
        self.assertEqual((line.raw_values["base_purchase_bar_count"], line.raw_values["purchase_allowance_rule"],
                          line.suggested_bar_count), (501, "PLUS_8", 509))

    def test_copy_preserves_manual_selection_and_recalculates_for_target_quantity(self):
        original = self.create_pipe(purchase_allowance_mode="MANUAL", purchase_allowance_rule="PERCENT_0_5")
        self.product_line.quantity = 3000
        self.product_line.save(update_fields=["quantity"])
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                            actor_employee=self.employee)
        line = BomLine.objects.get(section__bom=copied)
        self.assertEqual((line.raw_values["purchase_allowance_mode"], line.raw_values["purchase_allowance_rule"],
            line.raw_values["base_purchase_bar_count"], line.raw_values["purchase_allowance_bar_count"], line.suggested_bar_count),
            ("MANUAL", "PERCENT_0_5", 1000, 5, 1005))
        original.refresh_from_db()
        self.assertEqual((original.suggested_bar_count, original.raw_values["base_purchase_bar_count"]), (336, 334))

    def test_source_percentage_stays_legacy_until_explicit_selection(self):
        line = self.create_pipe(source_purchase_allowance_percent="1")
        self.assertEqual(line.suggested_bar_count, 337)
        sections, row = self.row()
        self.assertIsNone(row["base_purchase_bar_count"])
        row.update(purchase_allowance_mode="MANUAL", purchase_allowance_rule="PLUS_8")
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertEqual(line.suggested_bar_count, 342)
        self.assertEqual(Decimal(line.raw_values["source_purchase_allowance_percent"]), Decimal("1"))

    def test_invalid_options_and_non_pipe_use_are_atomic(self):
        line = self.create_pipe()
        for mode, rule in (("MANUAL", "BAD"), ("MANUAL", ""), ("BAD", "PLUS_5"), ("", "")):
            sections, row = self.row()
            row.update(purchase_allowance_mode=mode, purchase_allowance_rule=rule)
            self.assertEqual(self.save(sections).status_code, 400)
        response = self.save([{"section_type": "ACCESSORY", "title": "五金件", "lines": [
            {"part_name": "错误分类", "purchase_allowance_mode": "AUTO"}]}])
        self.assertEqual(response.status_code, 400)
        line.refresh_from_db()
        self.assertEqual(line.suggested_bar_count, 339)

    def test_preview_matches_save_and_rejects_non_pipe_allowance(self):
        endpoint = "/api/v1/boms/material-flow-preview/"
        payload = {"kind": "PIPE", "order_quantity": "1000", "cutting_length_mm": "500",
                   "pieces_per_product": "2", "pieces_per_bar": "6", "purchase_allowance_mode": "AUTO"}
        before = BomLine.objects.count()
        response = self.client.post(endpoint, payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["data"]["base_purchase_bar_count"], response.data["data"]["suggested_bar_count"]), (334, 339))
        self.assertEqual(self.client.post(endpoint, {**payload, "kind": "FABRIC", "unit_consumption": "2"}, format="json").status_code, 400)
        self.assertEqual(BomLine.objects.count(), before)
