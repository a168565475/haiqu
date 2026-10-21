from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError

from apps.reference_data.models import ProductColor
from ..duplicate_lines import validate_duplicate_material_lines
from ..models import BomLine
from ..services import confirm_bom_product
from . import test_material_save_confirmation as save_fixtures
from . import test_pipe_material_sync as pipe_fixtures


class DuplicateMaterialLineTests(SimpleTestCase):
    def line(self, title="管材类", **changes):
        section_type = "PROFILE" if title == "管材类" else (
            "FABRIC" if title in {"面料类", "辅料类", "裁剪明细"} else "ACCESSORY")
        values = {
            "section": SimpleNamespace(pk=uuid4(), title=title, section_type=section_type),
            "line_number": 1, "category": "材料", "unit": "根", "part_name": "上下短脚管",
            "material": "铁", "specification": "Φ25 × 1.5 mm", "hardness": "T5",
            "cutting_length_mm": 530, "length_value": "530", "notes": "", "unit_consumption": "2",
            "raw_values": {"tube_shape": "圆管", "tube_diameter": "25", "tube_thickness": "1.5",
                           "tube_coating_color": "黑色"},
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def copy_line(self, line, **changes):
        duplicate = deepcopy(line)
        duplicate.line_number = 2
        for field, value in changes.items():
            setattr(duplicate, field, value)
        return duplicate

    def test_pipe_legacy_aliases_and_decimal_formats_are_duplicates(self):
        first = self.line()
        second = self.copy_line(first, part_name=" 上下短脚管 ", material=" 铁 ",
            specification="圆管 25*1.50*6000", raw_values={"E": "Φ", "F": "25.0 mm", "G": "1.50",
                                                       "powder_coating_color": "黑色"})
        with self.assertRaisesMessage(ValidationError, "管材类”第 1、2 行"):
            validate_duplicate_material_lines([second, first])

    def test_counts_notes_and_source_ids_cannot_bypass_duplicates(self):
        first = self.line()
        second = self.copy_line(first, unit_consumption="9", notes="不同备注")
        second.raw_values.update(source_inventory_material_id=str(uuid4()), tube_cut_piece_count="10",
            purchase_unit_weight_kg="3", coating_unit_area_sqm="4")
        with self.assertRaisesMessage(ValidationError, "物料属性完全相同"):
            validate_duplicate_material_lines([first, second])

    def test_pipe_physical_differences_are_allowed(self):
        first = self.line()
        changes = {"part_name": "中交上下管", "material": "铝", "hardness": "T6", "cutting_length_mm": 531,
                   "tube_shape": "椭圆管", "tube_diameter": "26", "tube_thickness": "1.6",
                   "tube_coating_color": "白色"}
        for field, value in changes.items():
            with self.subTest(field=field):
                second = self.copy_line(first)
                if field.startswith("tube_"):
                    second.raw_values[field] = value
                else:
                    setattr(second, field, value)
                validate_duplicate_material_lines([first, second])

    def test_five_other_production_sections_use_their_own_attributes(self):
        for title, color_field in (("五金件", "hardware_color"), ("塑料件类", "plastic_color"),
                                  ("面料类", "fabric_color_name"), ("辅料类", "accessory_color"),
                                  ("包材类", "packaging_color")):
            with self.subTest(title=title):
                first = self.line(title, specification="40 × 60", raw_values={color_field: "黑色"})
                second = self.copy_line(first, specification="40*60", unit_consumption="10")
                with self.assertRaisesMessage(ValidationError, f"{title}”第 1、2 行"):
                    validate_duplicate_material_lines([first, second])
                second.raw_values[color_field] = "白色"
                validate_duplicate_material_lines([first, second])

    def test_fabric_name_does_not_replace_physical_identity_and_width_is_numeric(self):
        first = self.line("面料类", raw_values={"fabric_width": "1.70", "fabric_color_card": "卡A",
                                               "fabric_color_code": "01", "fabric_color_name": "蓝色"})
        second = self.copy_line(first, part_name="另一个裁片名称")
        second.raw_values["fabric_width"] = "1.7"
        with self.assertRaises(ValidationError):
            validate_duplicate_material_lines([first, second])
        for field in ("fabric_width", "fabric_color_card", "fabric_color_code"):
            with self.subTest(field=field):
                different = self.copy_line(second)
                different.raw_values[field] = "2"
                validate_duplicate_material_lines([first, different])

    def test_hardware_thickness_and_spray_color_distinguish_lines(self):
        first = self.line("五金件", raw_values={"thickness": "1.50", "powder_coating_color": "黑色"})
        second = self.copy_line(first)
        second.raw_values["thickness"] = "1.5"
        with self.assertRaises(ValidationError):
            validate_duplicate_material_lines([first, second])
        second.raw_values["thickness"] = "2"
        validate_duplicate_material_lines([first, second])
        second.raw_values.update(thickness="1.5", powder_coating_color="白色")
        validate_duplicate_material_lines([first, second])

    def test_different_sections_are_independent_and_cutting_is_not_guessed(self):
        validate_duplicate_material_lines([self.line(), self.line()])
        cutting = self.line("裁剪明细")
        validate_duplicate_material_lines([cutting, self.copy_line(cutting)])


class DuplicateMaterialLineApiTests(TestCase):
    setUpFixture = pipe_fixtures.PipeMaterialSyncApiTests.setUpFixture
    tearDown = pipe_fixtures.PipeMaterialSyncApiTests.tearDown
    material = pipe_fixtures.PipeMaterialSyncApiTests.material
    get = pipe_fixtures.PipeMaterialSyncApiTests.get
    payload = pipe_fixtures.PipeMaterialSyncApiTests.payload
    body = save_fixtures.MaterialSaveConfirmationTests.body
    snapshot = save_fixtures.MaterialSaveConfirmationTests.snapshot
    preview = save_fixtures.MaterialSaveConfirmationTests.preview
    commit = save_fixtures.MaterialSaveConfirmationTests.commit

    def setUp(self):
        pipe_fixtures.PipeMaterialSyncApiTests.setUp(self)
        color, _ = ProductColor.objects.get_or_create(color_card="DUPLICATE", color_code="01", color_name="判重测试色")
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
            color_code=color.color_code, actor_employee=self.employee)

    def test_duplicate_draft_can_save_but_legacy_verify_rolls_back(self):
        body, etag = self.body(self.payload(), self.payload(unit_consumption="3", notes="不同备注"))
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.filter(section__bom=self.bom).count(), 2)
        before = self.snapshot()
        response = self.client.post(f"/api/v1/boms/{self.bom.pk}/verify/",
            {"quantity_confirmation_reason": "测试批次差异"}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("第 1、2 行物料属性完全相同", str(response.data))
        self.assertEqual(self.snapshot(), before)

    def test_verify_preview_rejects_duplicates_before_new_material_confirmation(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"),
                              self.payload(tube_thickness="0.80"), intent="verify")
        before = self.snapshot()
        response = self.preview(body, etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("管材类", str(response.data))
        self.assertIn("第 1、2 行", str(response.data))
        self.assertEqual(self.snapshot(), before)

    def test_direct_verify_patch_cannot_bypass_preview_and_has_no_partial_writes(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"),
                              self.payload(tube_thickness="0.80"), intent="verify")
        before = self.snapshot()
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("物料属性完全相同", str(response.data))
        self.assertEqual(self.snapshot(), before)

    def test_verify_accepts_different_lengths_and_colors_even_with_shared_raw_material(self):
        body, etag = self.body(self.payload(), self.payload(tube_coating_color="白色"),
                              self.payload(length_value="501"), intent="verify")
        body["quantity_confirmation_reason"] = "测试批次差异"
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], "VERIFIED")
        lines = list(BomLine.objects.filter(section__bom=self.bom).order_by("line_number"))
        self.assertEqual(lines[0].raw_values["source_inventory_material_id"],
                         lines[1].raw_values["source_inventory_material_id"])
