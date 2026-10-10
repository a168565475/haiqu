from types import SimpleNamespace
import unittest

from apps.boms.material_attributes import bom_attribute_fields, merge_bom_attribute_fields


def line(title, **values):
    return SimpleNamespace(
        section=SimpleNamespace(title=title),
        part_name=values.pop("part_name", "部件"),
        material=values.pop("material", "材质"),
        specification=values.pop("specification", "规格"),
        raw_values=values,
    )


class BomMaterialAttributesTests(unittest.TestCase):
    def test_maps_six_production_sections_and_omits_empty_values(self):
        fabric = line(
            "面料类",
            material="帆布",
            specification="1.2米",
            fabric_width="145cm",
            fabric_color_card="卡-01",
            fabric_color_code="C-01",
            fabric_color_name="米白",
        )
        fields = bom_attribute_fields(fabric)
        self.assertEqual(
            [(field["key"], field["label"], field["value"]) for field in fields],
            [
                ("specification", "规格", "1.2米"),
                ("material", "材质", "帆布"),
                ("fabric_color_card", "色卡", "卡-01"),
                ("fabric_color_name", "颜色", "米白"),
                ("fabric_color_code", "色号", "C-01"),
                ("fabric_width", "门幅", "145cm"),
            ],
        )
        self.assertFalse(any(item["key"] == "fabric_width" for item in bom_attribute_fields(line("五金件", powder_coating_color="黑色"))))

    def test_pipe_and_hardware_use_spray_color_and_merge_distinct_contributions(self):
        pipe = line("管材类", tube_coating_color="黑色")
        hardware = line("五金件", hardware_color="银色", powder_coating_color="黑色")
        merged = merge_bom_attribute_fields([bom_attribute_fields(pipe), bom_attribute_fields(hardware)])
        self.assertEqual(next(item["value"] for item in merged if item["key"] == "spray_color"), "黑色")
        self.assertEqual(next(item["value"] for item in merged if item["key"] == "part_name"), "部件")

    def test_plastic_auxiliary_and_packaging_keep_their_section_specific_fields(self):
        cases = [
            ("塑料件类", {"plastic_color": "红色"}, {"part_name": "部件", "material": "材质", "plastic_color": "红色", "specification": "规格"}),
            ("辅料类", {"accessory_color": "蓝色"}, {"part_name": "部件", "material": "材质", "accessory_color": "蓝色", "specification": "规格"}),
            ("包材类", {"packaging_color": "透明"}, {"part_name": "部件", "material": "材质", "packaging_color": "透明", "specification": "规格"}),
        ]
        for title, values, expected in cases:
            with self.subTest(title=title):
                self.assertEqual({item["key"]: item["value"] for item in bom_attribute_fields(line(title, **values))}, expected)

    def test_conflicting_spray_sources_are_visible(self):
        fields = bom_attribute_fields(line("管材类", tube_coating_color="黑色", powder_coating_color="白色"))
        self.assertEqual(next(item["value"] for item in fields if item["key"] == "spray_color"), "黑色、白色")

