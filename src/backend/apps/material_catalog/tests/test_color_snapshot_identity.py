from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.duplicate_lines import validate_duplicate_material_lines
from apps.material_catalog.saved_selection import validate_saved_material


class ColorSnapshotIdentityTests(SimpleTestCase):
    def test_processed_snapshot_keeps_original_color_metadata_beside_processing_color(self):
        snapshot = {"schema_version": 1, "catalog_id": str(uuid4()), "catalog_version": "original",
                    "category_key": "HARDWARE", "template_key": "HARDWARE", "name": "测试五金",
                    "scope": "BASE", "processing_state": "PROCESSED", "processing_stage": "POWDER_COATING",
                    "completed_craft": {"id": str(uuid4()), "craft_type": "EXTERNAL", "code": "POWDER_COATING"},
                    "semi_kind": "HARDWARE", "attributes": {"specification": "A", "color": "喷塑蓝"},
                    "unit_id": str(uuid4()), "unit_name": "个", "display_name": "测试五金 / A / 喷塑蓝 / 个",
                    "product_color_id": str(uuid4()), "color_card": "原色卡", "color_code": "R1", "color_name": "原色红"}
        self.assertEqual(validate_saved_material(snapshot), snapshot)

    def test_bom_confirm_distinguishes_same_name_colors_and_keeps_duplicate_protection(self):
        first = SimpleNamespace(
            section=SimpleNamespace(pk="fabric-section", title="面料类", section_type="FABRIC"),
            category="面料类", unit="米", raw_values={}, material_catalog_id="fabric", line_number=1,
            material_selection_snapshot={"attributes": {"color": "红"}, "processing_state": "RAW",
                "product_color_id": "first", "color_card": "A", "color_code": "01", "color_name": "红"},
        )
        second = deepcopy(first)
        second.line_number = 2
        second.material_selection_snapshot.update(product_color_id="second", color_card="B", color_code="02")
        validate_duplicate_material_lines([first, second])
        second.material_selection_snapshot = deepcopy(first.material_selection_snapshot)
        with self.assertRaises(ValidationError):
            validate_duplicate_material_lines([first, second])
        for line in (first, second):
            for key in ("product_color_id", "color_card", "color_code", "color_name"):
                line.material_selection_snapshot.pop(key)
        with self.assertRaises(ValidationError):
            validate_duplicate_material_lines([first, second])
