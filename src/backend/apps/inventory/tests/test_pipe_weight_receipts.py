from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.catalog_receipts import catalog_receipt_values
from apps.inventory.pipe_receipts import receipt_pipe_values, quality_pipe_quantities


class PipeWeightReceiptTests(SimpleTestCase):
    def setUp(self):
        active = {"status": "ACTIVE", "archived_at": None}
        self.material = SimpleNamespace(pk=uuid4(), item_type="MATERIAL", archived_at=None,
            unit=SimpleNamespace(unit_name="根", catalog_owner_id=None, **active), category=SimpleNamespace(category_name="管材", **active))
        self.purchase = SimpleNamespace(section_type_snapshot="PROFILE", source_unit_text="KG",
            raw_bar_length_m=Decimal("6"), raw_bar_weight_kg=Decimal("2.5"), material_catalog_id=uuid4(),
            calculation_snapshot={"raw_material_id": str(self.material.pk), "raw_bar_weight_kg": "2.5"})
        self.selected = {"category_key": "TUBE", "processing_state": "RAW", "unit_name": "根"}

    def receive(self, mode, **data):
        item = {"received_weight_kg": Decimal("4.1"), **data}
        if mode == "catalog":
            with patch("apps.procurement.catalog_materials.purchase_catalog_selection", return_value=self.selected):
                return catalog_receipt_values(purchase_line=self.purchase, item=item), item
        with patch("apps.inventory.pipe_receipts.RawMaterialInformation.objects.select_related") as query:
            query.return_value.filter.return_value.first.return_value = self.material
            return receipt_pipe_values(item, purchase_line=self.purchase), item

    def test_missing_receipt_roots_are_rounded_up_in_both_paths(self):
        for mode in ("catalog", "legacy"):
            with self.subTest(mode=mode):
                values, item = self.receive(mode)
                self.assertEqual(values["received_bar_count"], 2)
                self.assertEqual(values["received_weight_kg"], Decimal("4.1"))
                self.assertEqual(item["received_quantity"], Decimal("12"))

    def test_verified_receipt_roots_override_estimate_without_changing_weight(self):
        for mode in ("catalog", "legacy"):
            with self.subTest(mode=mode):
                values, item = self.receive(mode, received_bar_count=3)
                self.assertEqual(values["received_bar_count"], 3)
                self.assertEqual(values["accepted_bar_count"], 3)
                self.assertEqual(values["received_weight_kg"], Decimal("4.1"))
                self.assertEqual(item["received_quantity"], Decimal("18"))

    def test_invalid_receipt_roots_are_rejected_in_both_paths(self):
        for mode in ("catalog", "legacy"):
            for roots in (0, -1, Decimal("1.5"), True):
                with self.subTest(mode=mode, roots=roots), self.assertRaises(ValidationError):
                    self.receive(mode, received_bar_count=roots)

    def test_missing_standard_weight_is_not_treated_as_legacy_meters(self):
        self.purchase.raw_bar_weight_kg = None
        self.purchase.calculation_snapshot.pop("raw_bar_weight_kg")
        for mode in ("catalog", "legacy"):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                self.receive(mode, received_bar_count=2)

    def line(self, roots=2):
        return SimpleNamespace(measurement_kind="PIPE", source_unit_text_snapshot="KG",
            raw_bar_length_m=Decimal("6"), bar_weight_kg=Decimal("2.5"),
            received_bar_count=roots, received_weight_kg=Decimal("4.1"))

    def test_verified_partial_return_preserves_remaining_actual_weight(self):
        line = self.line()
        meters = quality_pipe_quantities(line, {"return_weight_kg": Decimal("3"), "return_bar_count": 1})
        self.assertEqual(meters, Decimal("6"))
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (1, 1))
        self.assertEqual(line.accepted_weight_kg, Decimal("1.1"))

    def test_full_return_defaults_to_verified_received_roots(self):
        line = self.line(roots=3)
        quality_pipe_quantities(line, {"return_weight_kg": Decimal("4.1")})
        self.assertEqual((line.return_bar_count, line.accepted_bar_count), (3, 0))
        self.assertEqual(line.accepted_weight_kg, 0)

    def test_zero_and_full_return_weight_must_match_real_roots(self):
        for weight, roots in (("0", 1), ("1", 0), ("3", 2), ("4.1", 1), ("4.1", 3)):
            with self.subTest(weight=weight, roots=roots), self.assertRaises(ValidationError):
                quality_pipe_quantities(self.line(), {"return_weight_kg": Decimal(weight), "return_bar_count": roots})

    def test_invalid_return_roots_are_rejected(self):
        for roots in (-1, Decimal("0.5"), True):
            with self.subTest(roots=roots), self.assertRaises(ValidationError):
                quality_pipe_quantities(self.line(), {"return_weight_kg": Decimal("1"), "return_bar_count": roots})

    def test_manual_receipt_saves_actual_roots_and_weight_without_bom_standard(self):
        item = {"received_weight_kg": Decimal("4.1"), "received_bar_count": 3, "raw_bar_length_m": Decimal("6")}
        values = receipt_pipe_values(item, material=self.material)
        self.assertEqual((values["received_bar_count"], values["received_weight_kg"]), (3, Decimal("4.1")))
        self.assertIsNone(values["bar_weight_kg"])
        self.assertEqual(item["received_quantity"], Decimal("18"))

    def test_manual_receipt_requires_actual_weight_without_guessing_from_meters(self):
        with self.assertRaises(ValidationError):
            receipt_pipe_values({"received_quantity": Decimal("18"), "received_bar_count": 3,
                "raw_bar_length_m": Decimal("6")}, material=self.material)

    def test_manual_weight_cannot_overflow_legacy_purchase_snapshot_column(self):
        with self.assertRaises(ValidationError):
            receipt_pipe_values({"received_weight_kg": Decimal("100000000000000"), "received_bar_count": 3,
                "raw_bar_length_m": Decimal("6")}, material=self.material)
