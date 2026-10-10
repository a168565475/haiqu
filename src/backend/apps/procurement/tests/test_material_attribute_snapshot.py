from types import SimpleNamespace
from unittest import TestCase

from ..material_attribute_snapshot import build_material_attribute_snapshot


class MaterialAttributeSnapshotTests(TestCase):
    def test_profile_keeps_shape_diameter_thickness_but_excludes_powder_color(self):
        line = SimpleNamespace(
            part_name="立柱",
            material="铁",
            specification="25*1.0",
            raw_values={
                "tube_shape": "圆管",
                "tube_diameter": "25",
                "tube_thickness": "1.0",
                "tube_coating_color": "黑色",
            },
        )

        snapshot = build_material_attribute_snapshot(
            line,
            SimpleNamespace(title="型材类", section_type="PROFILE"),
        )

        self.assertEqual(
            [field["label"] for field in snapshot["fields"]],
            ["部件名称", "材质", "规格", "形状", "直径", "厚度"],
        )
        self.assertNotIn("喷塑", str(snapshot))
        self.assertNotIn("黑色", str(snapshot))

    def test_fabric_keeps_color_card_color_code_and_width(self):
        line = SimpleNamespace(
            part_name="",
            material="帆布",
            specification="600D",
            raw_values={
                "fabric_color_card": "卡A",
                "fabric_color_name": "深灰",
                "fabric_color_code": "DG-01",
                "fabric_width": "1.5m",
            },
        )

        snapshot = build_material_attribute_snapshot(
            line,
            SimpleNamespace(title="面料类", section_type="FABRIC"),
        )

        self.assertEqual(
            [field["label"] for field in snapshot["fields"]],
            ["规格", "材质", "色卡", "颜色", "色号", "门幅"],
        )
