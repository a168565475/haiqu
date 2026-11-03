from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.material_catalog.models import MaterialCatalog
from apps.reference_data.models import ProductionUnit
from ..catalog_stock_identity import build_catalog_stock_identity
from ..models import PublicStockBalance, PublicStockMovement
from ..public_stock_identity import validate_public_identity
from ..public_stock_services import available_public_stock
from .test_public_stock_services import PublicStockFixture


class CatalogStockTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="目录管材")
        self.kg, _ = ProductionUnit.objects.get_or_create(unit_name="公斤", defaults={"unit_code": "U3KG"})
        self.saved = {"schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name, "scope": "BASE",
            "processing_state": "RAW", "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"},
            "unit_id": str(self.root_unit.pk), "unit_name": "根", "display_name": "目录管材 / 铁 / 根"}
        self.identity = self.identity_for(self.saved)

    def identity_for(self, saved):
        return build_catalog_stock_identity(material_catalog_id=self.catalog.pk, material_selection_snapshot=saved,
            raw_bar_length_m="6.00" if saved["processing_state"] == "RAW" and saved["category_key"] == "TUBE" else None)

    def test_missing_required_attributes_cannot_create_stock(self):
        for field in ("material", "shape", "section_size", "thickness"):
            damaged = deepcopy(self.saved)
            damaged["attributes"].pop(field)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.credit(1, identity=self.identity_for(damaged))
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_actual_length_is_required_and_never_parsed_from_catalog_text(self):
        for length in (None, "0", "3.051", "NaN", True):
            with self.subTest(length=length), self.assertRaises(ValidationError):
                build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
                    material_selection_snapshot=self.saved, raw_bar_length_m=length)
        without_length = deepcopy(self.saved)
        without_length["attributes"].pop("length")
        for length in (None, "0", "3.051", "NaN", True):
            with self.subTest(no_attribute_length=length), self.assertRaises(ValidationError):
                build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
                    material_selection_snapshot=without_length, raw_bar_length_m=length)
        kilograms = {**self.saved, "unit_id": str(self.kg.pk), "unit_name": "公斤"}
        with self.assertRaises(ValidationError):
            build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
                material_selection_snapshot=kilograms, raw_bar_length_m="6.00")

    def test_queries_keep_actual_lengths_and_root_meter_balances_separate(self):
        from ..catalog_stock_queries import available_catalog_balances
        first = self.credit(3, identity=self.identity).balance
        short = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.saved, raw_bar_length_m="3.05")
        second = self.credit(2, identity=short).balance
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.meter_quantity, 18)
        self.assertEqual(second.meter_quantity, Decimal("6.10"))
        args = {"material_catalog_id": self.catalog.pk, "material_selection_snapshot": self.saved}
        rows = available_catalog_balances(**args)
        self.assertEqual({row["raw_bar_length_m"] for row in rows}, {Decimal("6"), Decimal("3.05")})
        exact = available_catalog_balances(**args, raw_bar_length_m="3.05")
        self.assertEqual([row["balance_id"] for row in exact], [str(second.pk)])
        self.debit(second.pk, 1)
        second.refresh_from_db()
        self.assertEqual(second.quantity, 1)
        self.assertEqual(second.meter_quantity, Decimal("3.05"))

    def test_missing_inner_snapshot_is_a_controlled_validation_error(self):
        damaged = deepcopy(self.identity)
        damaged["identity_snapshot"].pop("material_selection_snapshot")
        with self.assertRaises(ValidationError):
            self.credit(1, identity=damaged)
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_optional_fields_remain_optional_without_catalog_queries(self):
        from apps.material_catalog.saved_selection import validate_saved_material
        hardware = {**self.saved, "category_key": "HARDWARE", "template_key": "HARDWARE", "attributes": {"specification": "M8"}}
        with self.assertNumQueries(0):
            self.assertEqual(validate_saved_material(self.saved), self.saved)  # 原管颜色仍可省略。
            self.assertEqual(validate_saved_material(hardware), hardware)

    def test_raw_pipe_without_attribute_length_preserves_snapshot_and_actual_stock_length(self):
        from apps.material_catalog.saved_selection import validate_saved_material
        self.saved["attributes"].pop("length")
        original = deepcopy(self.saved)
        with self.assertNumQueries(0):
            validated = validate_saved_material(self.saved)
        validated["attributes"]["material"] = "改变副本"
        self.assertEqual(self.saved, original)
        identity = self.identity_for(self.saved)
        balance = self.credit(2, identity=identity).balance
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.raw_bar_length_m), (2, Decimal("12"), Decimal("6")))
        self.assertEqual(balance.identity_snapshot["material_selection_snapshot"], original)

    def test_saved_snapshot_survives_catalog_changes_and_merges_versions(self):
        first = self.credit(Decimal("12"), identity=self.identity)
        self.catalog.name = "目录已改名"
        self.catalog.save()
        updated = {**self.saved, "name": self.catalog.name, "catalog_version": self.catalog.updated_at.isoformat(), "display_name": "改名"}
        second = self.credit(Decimal("1"), identity=self.identity_for(updated))
        self.assertEqual(first.balance_id, second.balance_id)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 13)
        self.assertEqual(available_public_stock(identity=self.identity), 13)
        self.assertEqual(first.balance.identity_snapshot["material_selection_snapshot"], self.saved)

    def test_same_event_is_idempotent_and_conflicting_quantity_fails(self):
        source = self.source()
        first = self.credit(Decimal("1"), identity=self.identity, **source)
        self.assertEqual(self.credit(Decimal("1"), identity=self.identity, **source).pk, first.pk)
        self.assert_error("IDEMPOTENCY_CONFLICT", lambda: self.credit(Decimal("2"), identity=self.identity, **source))
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_debit_decimal_and_insufficient_stock_preserve_balance(self):
        hardware = {**self.saved, "category_key": "HARDWARE", "template_key": "HARDWARE",
            "attributes": {"specification": "M8"}, "unit_id": str(self.kg.pk), "unit_name": "公斤"}
        balance = self.credit(Decimal("2.5"), identity=self.identity_for(hardware)).balance
        self.debit(balance.pk, Decimal("1.125"))
        self.assert_error("STOCK_INSUFFICIENT", lambda: self.debit(balance.pk, Decimal("2")))
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal("1.375"))

    def test_units_and_attributes_do_not_merge(self):
        first = self.credit(1, identity=self.identity)
        attrs = deepcopy(self.saved)
        attrs["attributes"]["thickness"] = "2"
        second = self.credit(1, identity=self.identity_for(attrs))
        roots = self.saved
        third = self.credit(1, identity=build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=roots, raw_bar_length_m="3.05"))
        self.assertEqual(len({first.balance_id, second.balance_id, third.balance_id}), 3)
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.credit(Decimal("1.1"), identity=self.identity_for(roots)))

    def test_processed_state_uses_semi_warehouse_and_keeps_craft(self):
        from apps.material_catalog.saved_selection import validate_saved_material
        from ..public_stock_identity import build_semi_finished_identity
        from ..public_bom_snapshot import freeze_bom_line, build_output_identity
        self.saved["attributes"].pop("length")
        self.bom_line.material_catalog = self.catalog
        self.bom_line.material_selection_snapshot = self.saved
        identity = build_semi_finished_identity(bom_line=self.bom_line, completed_craft=self.craft, unit=self.piece_unit)
        self.assert_error("WAREHOUSE_SCOPE_INVALID", lambda: self.credit(1, identity=identity))
        movement = self.credit(1, identity=identity, zone=self.semi_zone)
        self.assertEqual(movement.balance.stock_kind, "CATALOG_SEMI")
        selected = identity["identity_snapshot"]["material_selection_snapshot"]
        self.assertEqual(selected["attributes"]["length"], "415 mm")
        self.assertEqual(selected["attributes"]["color"], "黑色")
        self.assertEqual(selected["processing_details"]["cutting_length_mm"], 415)
        self.assertEqual(build_output_identity(freeze_bom_line(self.bom_line), self.craft, self.piece_unit), identity)
        self.assertEqual(self.identity_for(selected), identity)
        damaged = deepcopy(selected)
        damaged["attributes"].pop("length")
        with self.assertRaises(ValidationError):
            validate_saved_material(damaged)

    def test_malformed_snapshot_and_tampered_identity_are_rejected(self):
        for change in ({"schema_version": True}, {"unit_id": "invalid"}, {"attributes": {}}, {"scope": {}}, {"processing_state": []}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.identity_for({**self.saved, **change})
        altered = {**self.identity, "identity_key": "0" * 64}
        with self.assertRaises(ValidationError):
            validate_public_identity(altered)

    def test_snapshot_fk_mismatch_and_precision_fail(self):
        with self.assertRaises(ValidationError):
            build_catalog_stock_identity(material_catalog_id=uuid4(), material_selection_snapshot=self.saved)
        with self.assertRaises(ValidationError):
            self.credit(Decimal("1.00001"), identity=self.identity)

    def test_rollback_does_not_leave_partial_stock(self):
        from django.db import transaction
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                self.credit(2, identity=self.identity)
                self.credit(1, identity=self.identity, zone=self.semi_zone)
        self.assertEqual(PublicStockBalance.objects.count(), 0)
