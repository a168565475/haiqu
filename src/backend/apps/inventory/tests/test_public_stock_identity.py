from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.test import SimpleTestCase

from apps.inventory.public_stock_identity import (
    build_pipe_stock_identity,
    build_semi_finished_identity,
    validate_public_identity,
)
from apps.inventory.stock_services import InventoryStockValidationError


class PublicStockIdentityTests(SimpleTestCase):
    """纯属性测试不访问数据库，跨订单比较也不查询来源批次。"""

    def setUp(self):
        self.bar_unit = SimpleNamespace(pk=UUID(int=1), unit_name="根", unit_code="BAR")
        self.piece_unit = SimpleNamespace(pk=UUID(int=2), unit_name="支", unit_code="PIECE")
        self.set_unit = SimpleNamespace(pk=UUID(int=3), unit_name="套", unit_code="SET")
        self.coating = SimpleNamespace(pk=UUID(int=4), craft_type="EXTERNAL", outsourcing_code="POWDER_COATING", name="喷塑")
        self.cutting = SimpleNamespace(pk=UUID(int=5), craft_type="INTERNAL", plan_category="CUTTING", name="厂内裁剪")

    def pipe_line(self):
        return SimpleNamespace(
            pk=uuid4(), component_identity=uuid4(),
            section=SimpleNamespace(section_type="PROFILE", title="管材类", bom_id=uuid4()),
            category="管材", part_name="前脚管", material="铁", specification="20*28*0.8*6140",
            cutting_length_mm=415, hardness="", raw_bar_length_m=Decimal("6.14"),
            pieces_per_product=2, pieces_per_bar=14, unit="根",
            raw_values={"tube_shape": "矩形管", "tube_diameter": "20*28", "tube_thickness": "0.8", "tube_coating_color": "黑色"},
        )

    def cutting_line(self):
        bom_id = uuid4()
        fabric = SimpleNamespace(
            pk=uuid4(), section=SimpleNamespace(section_type="FABRIC", title="面料类", bom_id=bom_id),
            material="PE", specification="600D", unit="米",
            raw_values={"fabric_color_name": "绿色", "fabric_color_code": "5865C", "fabric_color_card": "潘通", "fabric_width": "1.5米"},
        )
        return SimpleNamespace(
            pk=uuid4(), component_identity=uuid4(),
            section=SimpleNamespace(section_type="FABRIC", title="裁剪明细", bom_id=bom_id),
            category="委外布面", part_name="椅面", material="PE", specification="450*500", unit="米",
            cutting_pieces_per_set=2, cutting_sets_per_product=1, fabric_meters_per_piece=Decimal("0.5"),
            fabric_meters_per_set=Decimal("1"), fabric_source_line=fabric,
            raw_values={"cutting_category": "委外布面", "cutting_color": "绿色"},
        )

    def semi(self, line=None, craft=None, unit=None):
        return build_semi_finished_identity(
            bom_line=line or self.pipe_line(), completed_craft=craft or self.coating,
            unit=unit or self.piece_unit,
        )

    def cutting_semi(self, line=None, craft=None):
        return self.semi(line=line or self.cutting_line(), craft=craft or self.cutting, unit=self.set_unit)

    def raw_material(self):
        return SimpleNamespace(pk=UUID(int=6), item_type="MATERIAL", archived_at=None,
                               category=SimpleNamespace(category_name="管材"), unit_id=self.bar_unit.pk)

    def raw_pipe(self, material=None, length="6.14", unit=None):
        return build_pipe_stock_identity(raw_material=material or self.raw_material(),
                                         raw_bar_length_m=length, unit=unit or self.bar_unit)

    def assert_invalid(self, callback, field=None):
        with self.assertRaises(InventoryStockValidationError) as raised:
            callback()
        if field:
            self.assertEqual(raised.exception.error_meta["field"], field)

    @staticmethod
    def rehash(identity):
        identity["identity_key"] = hashlib.sha256(json.dumps(
            identity["identity_snapshot"], sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
        return identity

    def test_pipe_same_physical_part_pools_across_orders_and_raw_lengths(self):
        first, second = self.pipe_line(), self.pipe_line()
        second.raw_bar_length_m = Decimal("7.25")
        second.specification = "20 × 28 × 0.80 × 7250"
        second.pieces_per_product, second.pieces_per_bar = 9, 17
        second.raw_values.update(tube_diameter="20.0 × 28.00", tube_thickness="0.80")
        second.raw_values["source_inventory_material_id"] = str(uuid4())
        identity = self.semi(first)
        self.assertEqual(identity, self.semi(second))
        snapshot = identity["identity_snapshot"]
        self.assertEqual(snapshot["tube_diameter"], "20*28")
        self.assertEqual(snapshot["tube_thickness"], "0.8")
        self.assertEqual(snapshot["cutting_length_mm"], 415)
        self.assertEqual(snapshot["unit_name"], "支")
        for field in ("bom_line_id", "component_identity", "raw_bar_length_m", "pieces_per_product", "specification"):
            self.assertNotIn(field, snapshot)

    def test_pipe_physical_differences_never_pool(self):
        initial = self.semi()["identity_key"]
        cases = [
            ("category", "型材"), ("part_name", "后脚管"), ("material", "铝"),
            ("cutting_length_mm", 416), ("hardness", "T6"),
            ("tube_shape", "椭圆管"), ("tube_coating_color", "白色"),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                line = self.pipe_line()
                if field.startswith("tube_"):
                    line.raw_values[field] = value
                else:
                    setattr(line, field, value)
                self.assertNotEqual(initial, self.semi(line)["identity_key"])

    def test_pipe_size_conflict_and_unready_old_line_are_rejected(self):
        line = self.pipe_line()
        line.specification = "20*30*0.8*6140"
        self.assert_invalid(lambda: self.semi(line), "specification")
        line = self.pipe_line()
        line.raw_values["F"] = "20*30"
        self.assert_invalid(lambda: self.semi(line), "tube_diameter")
        line = self.pipe_line()
        line.cutting_length_mm, line.length_value = None, "415"
        self.assert_invalid(lambda: self.semi(line), "cutting_length_mm")
        self.assert_invalid(lambda: self.semi(unit=self.bar_unit), "unit")

    def test_round_pipe_legacy_symbol_and_structural_alias_are_equivalent(self):
        line = self.pipe_line()
        line.specification = "Φ25 × 1.2 mm"
        line.raw_values.update(tube_shape="φ", tube_diameter="Φ25", tube_thickness="1.20")
        first = self.semi(line)
        line.raw_values.update(tube_shape="圆管", tube_diameter="25.0", tube_thickness="1.2", E="Φ", F="25", G="1.20")
        self.assertEqual(first, self.semi(line))

    def test_missing_finished_color_cannot_be_replaced_by_raw_color(self):
        for placeholder in (None, "", "/", "—"):
            with self.subTest(placeholder=placeholder):
                line = self.pipe_line()
                line.raw_values.update(tube_coating_color=placeholder, hardware_color="银色", color="银色")
                self.assert_invalid(lambda: self.semi(line), "tube_coating_color")

    def test_non_coated_pipe_is_not_credited_as_coated_product(self):
        metal = SimpleNamespace(pk=uuid4(), craft_type="INTERNAL", plan_category="METAL", name="金工")
        # 厂内金工半成品不要求颜色，也不能把原料颜色带入身份。
        identity = self.semi(craft=metal)
        self.assertEqual(identity["identity_snapshot"]["color"], "")

    def test_profile_external_uses_new_powder_color_and_legacy_alias(self):
        line = self.pipe_line()
        line.raw_values.update(tube_coating_color="", powder_coating_color="白色")
        identity = self.semi(line)
        self.assertEqual(identity["identity_snapshot"]["color"], "白色")

        # 旧 BOM 只有 tube_coating_color 时仍可外发。
        line.raw_values.pop("powder_coating_color")
        line.raw_values["tube_coating_color"] = "黑色"
        self.assertEqual(self.semi(line)["identity_snapshot"]["color"], "黑色")

    def test_profile_spray_color_conflict_is_rejected(self):
        line = self.pipe_line()
        line.raw_values["powder_coating_color"] = "白色"
        self.assert_invalid(lambda: self.semi(line), "powder_coating_color")

    def test_cutting_matches_source_attributes_not_ids_or_consumption(self):
        first, second = self.cutting_line(), self.cutting_line()
        second.material = "/"
        second.raw_values["cutting_color"] = "5865C"
        second.fabric_source_line.raw_values["fabric_width"] = "1.8米"
        second.cutting_sets_per_product = 7
        second.fabric_meters_per_piece = Decimal("0.7")
        second.fabric_meters_per_set = Decimal("1.4")
        identity = self.cutting_semi(first)
        self.assertEqual(identity, self.cutting_semi(second))
        self.assertEqual(identity["identity_snapshot"]["color"], "绿色")
        self.assertEqual(identity["identity_snapshot"]["pieces_per_set"], 2)
        self.assertEqual(identity["identity_snapshot"]["unit_name"], "套")

    def test_cutting_set_composition_and_finished_specification_split_inventory(self):
        first = self.cutting_semi()
        for field, value in (("cutting_pieces_per_set", 3), ("specification", "450*550"), ("part_name", "椅背")):
            with self.subTest(field=field):
                line = self.cutting_line()
                setattr(line, field, value)
                self.assertNotEqual(first["identity_key"], self.cutting_semi(line)["identity_key"])
        line = self.cutting_line()
        line.fabric_source_line.specification = "900D"
        self.assertNotEqual(first["identity_key"], self.cutting_semi(line)["identity_key"])

    def test_cutting_sources_missing_and_conflicting_fields_are_rejected(self):
        for field, value in (("material", "涤纶"), ("specification", "/"), ("cutting_pieces_per_set", None)):
            with self.subTest(field=field):
                line = self.cutting_line()
                setattr(line, field, value)
                self.assert_invalid(lambda: self.cutting_semi(line), field)
        line = self.cutting_line()
        line.raw_values["cutting_color"] = "红色"
        self.assert_invalid(lambda: self.cutting_semi(line), "cutting_color")
        line = self.cutting_line()
        line.fabric_source_line.section.bom_id = uuid4()
        self.assert_invalid(lambda: self.cutting_semi(line), "fabric_source_line")
        line.fabric_source_line = None
        self.assert_invalid(lambda: self.cutting_semi(line), "fabric_source_line")
        line = self.cutting_line()
        line.fabric_source_line.raw_values.update(fabric_color_name="/", fabric_color_code="")
        self.assert_invalid(lambda: self.cutting_semi(line), "fabric.color")

    def test_cutting_actual_completed_process_keeps_sewing_and_cutting_separate(self):
        sewing = SimpleNamespace(pk=uuid4(), craft_type="EXTERNAL", outsourcing_code="SEWING", name="车缝")
        self.assertNotEqual(self.cutting_semi()["identity_key"], self.cutting_semi(craft=sewing)["identity_key"])

    def test_craft_display_rename_does_not_split_same_completed_process(self):
        initial = self.semi()
        self.coating.name = "管材喷塑"
        self.assertEqual(initial, self.semi())
        self.assertNotIn("name", initial["identity_snapshot"]["completed_craft"])

    def test_frozen_identity_survives_later_bom_and_craft_mutation(self):
        line = self.pipe_line()
        frozen = self.semi(line)
        unchanged = deepcopy(frozen)
        line.part_name, line.cutting_length_mm = "新的部位", 620
        line.raw_values["tube_coating_color"] = "白色"
        self.coating.name = "改名后的工艺"
        self.assertEqual(validate_public_identity(frozen), unchanged)
        self.assertNotEqual(frozen["identity_key"], self.semi(line)["identity_key"])
        validated = validate_public_identity(frozen)
        validated["identity_snapshot"]["color"] = "红色"
        self.assertEqual(frozen["identity_snapshot"]["color"], "黑色")

    def test_raw_pipe_separates_source_material_and_raw_bar_length(self):
        identity = self.raw_pipe(length=Decimal("6.140"))
        self.assertEqual(identity, self.raw_pipe(length="6.14"))
        self.assertEqual(identity["raw_bar_length_m"], Decimal("6.14"))
        self.assertNotEqual(identity["identity_key"], self.raw_pipe(length="6.15")["identity_key"])
        material = self.raw_material()
        material.pk = uuid4()
        self.assertNotEqual(identity["identity_key"], self.raw_pipe(material=material)["identity_key"])

    def test_raw_pipe_rejects_archived_non_pipe_and_wrong_units(self):
        for field, value in (("archived_at", "2026-09-28"), ("item_type", "SEMI_FINISHED")):
            with self.subTest(field=field):
                material = self.raw_material()
                setattr(material, field, value)
                self.assert_invalid(lambda: self.raw_pipe(material=material), "raw_material")
        material = self.raw_material()
        material.category.category_name = "五金"
        self.assert_invalid(lambda: self.raw_pipe(material=material), "raw_material")
        self.assert_invalid(lambda: self.raw_pipe(unit=self.piece_unit), "unit")

    def test_nonfinite_boolean_float_fractional_and_invalid_numbers_are_rejected(self):
        for value in (True, False, float("nan"), 6.14, "NaN", "Infinity", "-Infinity", "0", "-1", "6.141", "1e30", [], None):
            with self.subTest(value=value):
                self.assert_invalid(lambda: self.raw_pipe(length=value), "raw_bar_length_m")
        for value in (True, "1.5", "NaN", None):
            with self.subTest(cutting_length=value):
                line = self.pipe_line()
                line.cutting_length_mm = value
                self.assert_invalid(lambda: self.semi(line), "cutting_length_mm")

    def test_validator_detects_mutated_snapshot_and_outer_contract(self):
        for field, value in (("stock_kind", "RAW_PIPE"), ("identity_key", "0" * 64), ("unit_id", str(uuid4())), ("raw_material_id", str(uuid4())), ("raw_bar_length_m", Decimal("6.14"))):
            with self.subTest(field=field):
                identity = self.semi()
                identity[field] = value
                self.assert_invalid(lambda: validate_public_identity(identity))
        identity = self.semi()
        identity["identity_snapshot"]["color"] = "白色"
        self.assert_invalid(lambda: validate_public_identity(identity), "identity")
        identity = self.raw_pipe()
        identity["raw_bar_length_m"] = Decimal("6.15")
        self.assert_invalid(lambda: validate_public_identity(identity), "raw_bar_length_m")

    def test_validator_rejects_incomplete_extra_and_forged_rehashed_snapshots(self):
        for field, value in (("order_id", str(uuid4())), ("schema_version", True), ("cutting_length_mm", True), ("tube_thickness", "0.80"), ("unit_name", "根"), ("color", "/"), ("stock_kind", {}), ("semi_kind", [])):
            with self.subTest(field=field):
                identity = self.semi()
                identity["identity_snapshot"][field] = value
                self.assert_invalid(lambda: validate_public_identity(self.rehash(identity)))
        identity = self.semi()
        del identity["identity_snapshot"]["completed_craft"]
        self.assert_invalid(lambda: validate_public_identity(self.rehash(identity)), "completed_craft")

    def test_hardware_uses_finished_coating_color_and_bom_flow_unit(self):
        unit = SimpleNamespace(pk=uuid4(), unit_name="个", unit_code="PCS")
        line = SimpleNamespace(section=SimpleNamespace(section_type="ACCESSORY", title="五金件"),
                               category="五金", part_name="连接件", material="铁", specification="20*30*2", unit="PCS",
                               raw_values={"hardware_color": "银色", "powder_coating_color": "黑色", "thickness": "2.0"})
        identity = self.semi(line, unit=unit)
        self.assertEqual(identity["identity_snapshot"]["color"], "黑色")
        self.assertEqual(identity["identity_snapshot"]["thickness"], "2")
        line.raw_values["hardware_color"] = "原色"
        self.assertEqual(identity, self.semi(line, unit=unit))
        line.raw_values["powder_coating_color"] = "/"
        self.assert_invalid(lambda: self.semi(line, unit=unit), "color")
