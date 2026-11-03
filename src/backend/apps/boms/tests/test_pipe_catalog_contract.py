"""管材接目录只替换材料来源，不替换原根/米/支合同；禁止数据库访问的单元回归。"""
import django
django.setup()

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from apps.boms.catalog_selection import apply_catalog_selection, required_fields
from apps.boms.material_flow_bom import apply_line_quantities
from apps.boms.models import Bom, BomLine, BomSection


CATALOG_ID = UUID("11111111-1111-4111-8111-111111111111")
ROOT_ID = UUID("22222222-2222-4222-8222-222222222222")
VERSION = datetime(2026, 10, 30, tzinfo=timezone.utc)
ATTRS = {"material": "铁", "shape": "矩形管", "section_size": "25*15", "thickness": "1.5", "length": "3.05"}


def snapshot(unit="根", category="TUBE"):
    return {"schema_version": 1, "catalog_id": str(CATALOG_ID), "catalog_version": VERSION.isoformat(),
        "category_key": category, "template_key": category, "name": "目录品名", "scope": "BASE",
        "processing_state": "RAW", "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
        "attributes": deepcopy(ATTRS), "unit_id": str(ROOT_ID), "unit_name": unit, "display_name": "历史显示名"}


def pipe_line(version=3, snapshot_unit="根"):
    bom = Bom(order_quantity=1000)
    section = BomSection(bom=bom, title="管材类", section_type="PROFILE")
    return BomLine(section=section, line_number=1, material_catalog_id=CATALOG_ID,
        material_selection_snapshot=snapshot(snapshot_unit), unit="根", length_value="500", unit_consumption="2",
        cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6,
        raw_values={"tube_cut_piece_count": "6", "pipe_plan_version": version, "tube_metrics_manual": True,
                    "coating_unit_area_sqm": "0.04", "purchase_unit_weight_kg": "0.44"})


class PipeCatalogContractTests(SimpleTestCase):
    def test_bom_tube_length_is_optional_only_with_explicit_policy(self):
        self.assertIn("length", required_fields("TUBE", ATTRS))
        self.assertEqual(required_fields("TUBE", ATTRS, require_tube_length=False),
                         ("material", "shape", "section_size", "thickness"))
        self.assertEqual(required_fields("FABRIC", {}, require_tube_length=False),
                         required_fields("FABRIC", {}))

    def test_pipe_quantities_do_not_read_catalog_length_attribute(self):
        for length in (None, "999.99"):
            with self.subTest(length=length):
                line = pipe_line()
                line.material_selection_snapshot["attributes"].pop("length")
                if length is not None:
                    line.material_selection_snapshot["attributes"]["length"] = length
                before = deepcopy(line.material_selection_snapshot)
                apply_line_quantities(line, 1000, require_complete=True)
                self.assertEqual(line.unit, "根")
                self.assertEqual(line.total_consumption, "2000")
                self.assertEqual(line.suggested_bar_count, 334)
                self.assertEqual(str(line.raw_bar_length_m), "3.05")
                self.assertEqual(str(line.suggested_purchase_meters), "1018.70")
                self.assertEqual(line.material_selection_snapshot, before)

    def test_original_root_meter_piece_plan_and_saved_versions_are_preserved(self):
        for version, roots, meters in ((2, 337, "1027.85"), (3, 334, "1018.70")):
            with self.subTest(version=version):
                line = pipe_line(version)
                before = deepcopy(line.material_selection_snapshot)
                apply_line_quantities(line, 1000, require_complete=True)
                self.assertEqual(line.unit, "根")
                self.assertEqual(line.total_consumption, "2000")
                self.assertEqual(line.suggested_bar_count, roots)
                self.assertEqual(str(line.raw_bar_length_m), "3.05")
                self.assertEqual(str(line.suggested_purchase_meters), meters)
                self.assertEqual(line.total_purchase_quantity, meters)
                self.assertIsNone(line.material_quantity)
                self.assertEqual(line.material_selection_snapshot, before)

    def test_catalog_unit_does_not_override_profile_manufacturing_unit_or_add_quantity_gate(self):
        line = pipe_line(snapshot_unit="公斤")
        before = deepcopy(line.material_selection_snapshot)
        apply_line_quantities(line, 1000, require_complete=True)
        self.assertEqual(line.unit, "根")
        self.assertEqual(line.suggested_bar_count, 334)
        self.assertEqual(str(line.suggested_purchase_meters), "1018.70")
        self.assertEqual(line.material_selection_snapshot, before)

    def preview_selection(self, *, unit, section="管材类", allowed=True):
        category = "TUBE" if section == "管材类" else "HARDWARE"
        line = pipe_line()
        if category != "TUBE":
            line.section.title, line.section.section_type = section, "HARDWARE"
        attrs = ATTRS if category == "TUBE" else {"specification": "M6"}
        catalog = SimpleNamespace(pk=CATALOG_ID, category_key=category, template_key=category, name="目录品名",
            updated_at=VERSION, spray_enabled=False, allowed_units=SimpleNamespace(filter=lambda **kwargs:
                SimpleNamespace(first=lambda: SimpleNamespace(archived_at=None) if allowed else None)))
        unit_record = SimpleNamespace(pk=ROOT_ID, unit_name=unit, status="ACTIVE", archived_at=None)
        data = {"material_catalog_id": str(CATALOG_ID), "material_selection": {"catalog_version": VERSION.isoformat(),
            "scope": "BASE", "processing_state": "RAW", "attributes": attrs, "unit_id": str(ROOT_ID)}}
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: True))
        with patch("apps.boms.catalog_selection.MaterialCatalog.objects.filter") as catalogs, \
                patch("apps.boms.catalog_selection.MaterialAttributeValue.objects.filter") as values, \
                patch("apps.boms.catalog_selection.ProductionUnit.objects.filter") as units:
            catalogs.return_value.first.return_value = catalog
            values.return_value.first.return_value = SimpleNamespace(archived_at=None)
            units.return_value.first.return_value = unit_record
            apply_catalog_selection(line, data, old=None, request=request, persist=False, versions={})
        return line

    def test_new_profile_catalog_selection_rejects_non_root_unit_id(self):
        with self.assertRaises(ValidationError):
            self.preview_selection(unit="公斤")

    def test_root_not_yet_allowed_uses_existing_preview_option_path(self):
        line = self.preview_selection(unit="根", allowed=False)
        self.assertEqual(line.unit, "根")
        self.assertIsNone(line.material_quantity)

    def test_other_categories_keep_name_specific_units(self):
        line = self.preview_selection(unit="公斤", section="五金件")
        self.assertEqual(line.unit, "公斤")

    def test_unchanged_history_is_not_rebuilt_or_converted(self):
        old = pipe_line(snapshot_unit="公斤")
        old.material_quantity = Decimal("12.75")
        line = deepcopy(old)
        before = deepcopy(old.material_selection_snapshot)
        apply_catalog_selection(line, {"material_catalog_id": str(CATALOG_ID)}, old=old, request=None, persist=False,
                                versions={}, allow_public_creation=False, require_tube_length=False)
        self.assertEqual(line.material_selection_snapshot, before)
        self.assertEqual(line.material_quantity, Decimal("12.75"))

    def test_independent_total_cannot_be_added_or_changed(self):
        for unit, old_quantity in (("根", None), ("公斤", Decimal("12.75"))):
            with self.subTest(unit=unit):
                old = pipe_line(snapshot_unit=unit)
                old.material_quantity = old_quantity
                line = deepcopy(old)
                with self.assertRaises(ValidationError):
                    apply_catalog_selection(line, {"material_catalog_id": str(CATALOG_ID), "material_quantity": Decimal("13")},
                        old=old, request=None, persist=False, versions={})
