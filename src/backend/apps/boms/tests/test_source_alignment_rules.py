from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.api.serializers import BomLineWriteSerializer
from apps.boms.material_flow_bom import validate_fabric_links
from apps.boms.tube_metrics import tube_calculation_preview
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity, validate_catalog_stock_identity
from apps.procurement.pipe_purchase import pipe_meters


class SourceAlignmentRuleTests(SimpleTestCase):
    def test_length_input_keeps_third_place_and_rejects_extra_precision(self):
        serializer = BomLineWriteSerializer()
        self.assertEqual(serializer.validate_source_raw_bar_length_m("6.305"), "6.305")
        self.assertEqual(serializer.validate_source_raw_bar_length_m("3.050"), "3.05")
        with self.assertRaises(ValidationError):
            serializer.validate_source_raw_bar_length_m("6.3051")

    def test_purchase_meters_do_not_round_source_length(self):
        self.assertEqual(pipe_meters(3, "6.305"), (3, Decimal("18.915")))

    def test_catalog_stock_identity_keeps_old_two_place_identity_and_new_precision(self):
        snapshot = {"schema_version": 1, "catalog_id": "00000000-0000-4000-8000-000000000001", "catalog_version": "v1",
                    "category_key": "TUBE", "template_key": "TUBE", "name": "测试管材", "scope": "BASE",
                    "processing_state": "RAW", "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
                    "attributes": {"material": "钢", "shape": "圆管", "section_size": "22", "thickness": "1"},
                    "unit_id": "00000000-0000-4000-8000-000000000002", "unit_name": "根", "display_name": "测试管材"}
        def identity(length):
            return build_catalog_stock_identity(material_catalog_id=snapshot["catalog_id"],
                                                material_selection_snapshot=snapshot, raw_bar_length_m=length)
        old = identity("3.05")
        self.assertEqual(old, identity("3.050"))
        self.assertEqual(old["identity_snapshot"]["raw_bar_length_m"], "3.05")
        current = identity("6.305")
        self.assertEqual(current["identity_snapshot"]["raw_bar_length_m"], "6.305")
        self.assertEqual(validate_catalog_stock_identity(current), current)
        self.assertNotEqual(current["identity_key"], identity("6.30")["identity_key"])

    @patch("apps.boms.tube_metrics.calculate_tube_metrics")
    def test_tube_preview_passes_actual_long_length_to_formula(self, calculate):
        calculate.return_value = {"formula_snapshot": {"updated_at": "v1"},
                                  "coating_unit_area_sqm": "1", "purchase_unit_weight_kg": "2"}
        tube_calculation_preview({"tube_shape": "圆管", "tube_diameter": "22", "tube_thickness": "1",
                                  "length_value": "500", "tube_cut_piece_count": "6", "source_raw_bar_length_m": "6.305"})
        self.assertEqual(calculate.call_args_list[0].kwargs["length_mm"], "500")
        self.assertEqual(calculate.call_args_list[1].kwargs["length_mm"], Decimal("6305"))

    def cotton_lines(self, **snapshot_changes):
        source = SimpleNamespace(pk="source", section=SimpleNamespace(bom_id="bom", title="辅料类", section_type="FABRIC"),
                                 material_catalog_id="cotton", fabric_source_line_id=None,
                                 material_selection_snapshot={"category_key": "AUXILIARY", "template_key": "COTTON",
                                                              "processing_state": "RAW", "unit_name": "米", **snapshot_changes})
        cutting = SimpleNamespace(pk="cut", section=SimpleNamespace(bom_id="bom", title="裁剪明细", section_type="FABRIC"),
                                  fabric_source_line_id="source", line_number=1)
        return source, cutting

    def test_cutting_accepts_same_bom_meter_raw_cotton(self):
        for unit in ("米", "m"):
            source, cutting = self.cotton_lines(unit_name=unit)
            validate_fabric_links([source, cutting], require_complete=True)
            self.assertIs(cutting.fabric_source_line, source)

    def test_cutting_rejects_non_meter_processed_or_other_bom_cotton(self):
        for changes in ({"unit_name": "KG"}, {"unit_name": "个"}, {"processing_state": "PROCESSED"}, {"template_key": "AUXILIARY_GENERAL"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_fabric_links(list(self.cotton_lines(**changes)), require_complete=True)
        source, cutting = self.cotton_lines()
        source.section.bom_id = "other"
        with self.assertRaises(ValidationError):
            validate_fabric_links([source, cutting], require_complete=True)
