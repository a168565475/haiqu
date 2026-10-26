from copy import deepcopy

from django.test import SimpleTestCase

from ..purchase_sheet_line_display import purchase_sheet_line_display
from ..purchase_sheet_pdf import _money, _number
from ..purchase_sheet_xlsx import _number_format


class PurchaseSheetLineDisplayTests(SimpleTestCase):
    def test_plastic_attributes_are_separated_from_specification_and_color(self):
        line = {
            "part_name": "半通", "specification": "16", "material": "PE", "remark": "",
            "section_title": "塑料件类",
            "material_attributes_snapshot": {"fields": [
                {"key": "part_name", "label": "品名", "value": "半通"},
                {"key": "material", "label": "材质", "value": "PE"},
                {"key": "plastic_color", "label": "颜色", "value": "黑色"},
                {"key": "specification", "label": "规格", "value": "16"},
            ]},
        }
        original = deepcopy(line)
        self.assertEqual(purchase_sheet_line_display(line), {"specification": "16", "attributes": "材质：PE", "color": "黑色"})
        self.assertEqual(line, original)

    def test_contract_values_override_snapshot_including_explicit_blanks(self):
        line = {"specification": "", "material": "", "material_attributes_snapshot": {"fields": [
            {"key": "specification", "label": "规格", "value": "旧规格"},
            {"key": "material", "label": "材质", "value": "旧材质"},
            {"key": "tube_shape", "label": "形状", "value": "圆管"},
        ]}}
        self.assertEqual(purchase_sheet_line_display(line), {"specification": "", "attributes": "形状：圆管", "color": ""})
        line.update(specification="新规格", material="新材质")
        self.assertEqual(purchase_sheet_line_display(line), {
            "specification": "新规格", "attributes": "材质：新材质；形状：圆管", "color": "",
        })

    def test_fabric_preserves_card_code_width_and_requirement_as_attributes(self):
        line = {"specification": "600D", "material": "帆布", "remark": "按确认样",
                "material_attributes_snapshot": {"fields": [
                    {"key": "fabric_color_card", "label": "色卡", "value": "卡A"},
                    {"key": "fabric_color_name", "label": "颜色", "value": "深灰"},
                    {"key": "fabric_color_code", "label": "色号", "value": "DG-01"},
                    {"key": "fabric_width", "label": "门幅", "value": "1.5m"},
                    {"key": "fabric_width", "label": "门幅", "value": "1.5m"},
                ]}}
        self.assertEqual(purchase_sheet_line_display(line), {
            "specification": "600D", "attributes": "材质：帆布；色卡：卡A；色号：DG-01；门幅：1.5m；要求：按确认样", "color": "深灰",
        })

    def test_diameter_equal_to_specification_is_preserved_and_powder_color_excluded(self):
        line = {"specification": "16", "material": "铁", "material_attributes_snapshot": {"fields": [
            {"key": "tube_diameter", "label": "直径", "value": "16"},
            {"key": "tube_thickness", "label": "厚度", "value": "0.8"},
            {"key": "tube_coating_color", "label": "颜色", "value": "黑色"},
            {"key": "legacy", "label": "喷塑颜色", "value": "白色"},
        ]}}
        self.assertEqual(purchase_sheet_line_display(line), {
            "specification": "16", "attributes": "材质：铁；直径：16；厚度：0.8", "color": "",
        })

    def test_duplicate_color_values_are_shown_once_without_labels(self):
        line = {"material_attributes_snapshot": {"fields": [
            {"key": "plastic_color", "label": "颜色", "value": "黑色"},
            {"key": "hardware_color", "label": "颜色", "value": "黑色"},
            {"key": "accessory_color", "label": "颜色", "value": "白色"},
        ]}}
        self.assertEqual(purchase_sheet_line_display(line)["color"], "黑色 / 白色")

    def test_legacy_lines_keep_requirements_without_guessing_a_color(self):
        self.assertEqual(purchase_sheet_line_display({"specification": "M8", "material": "钢", "remark": "镀锌"}), {
            "specification": "M8", "attributes": "材质：钢；要求：镀锌", "color": "",
        })
        self.assertEqual(purchase_sheet_line_display({}), {"specification": "", "attributes": "", "color": ""})

    def test_invalid_or_blank_snapshot_fields_do_not_enter_output(self):
        for fields in ([None, "invalid", {}, {"label": "颜色", "value": ""}], None, "invalid", 7, {}):
            with self.subTest(fields=fields):
                self.assertEqual(purchase_sheet_line_display({"specification": "M8", "material_attributes_snapshot": {
                    "fields": fields,
                }}), {"specification": "M8", "attributes": "", "color": ""})

    def test_sample_material_and_extra_attributes_are_kept_and_remark_is_color(self):
        self.assertEqual(purchase_sheet_line_display({
            "specification": "样品规格", "material": "原材料描述", "remark": "样品蓝色",
            "material_attributes_snapshot": {"fields": [{"key": "tube_shape", "label": "形状", "value": "圆管"}]},
        }, sample_source=True), {"specification": "样品规格", "attributes": "材质：原材料描述；形状：圆管", "color": "样品蓝色"})

    def test_pdf_numbers_and_xlsx_formats_only_remove_trailing_zeroes(self):
        for value, text, cell_format in (
            ("48.0000", "48", "0"), ("70.20", "70.2", "0.#"),
            ("0.4500", "0.45", "0.##"), ("1.123456", "1.123456", "0.######"), ("0.0000", "0", "0"),
        ):
            with self.subTest(value=value):
                self.assertEqual(_number(value), text)
                self.assertEqual(_money(value), text)
                self.assertEqual(_number_format(value), cell_format)
