from copy import deepcopy
from uuid import UUID, uuid4
from unittest.mock import patch
from importlib import import_module
from types import SimpleNamespace

from django.db import IntegrityError, connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.reference_data.models import ProductCategory, ProductionUnit
from ..api.serializers import BomLineWriteSerializer
from ..component_parts import required_component_quantity
from ..material_flow_bom import apply_line_quantities, inherit_cutting_fabric_attributes
from ..models import Bom, BomLine, BomSection
from ..services import create_bom
from . import test_material_flow_bom as fixtures


class PieceUnitMigrationTests(TestCase):
    def setUp(self):
        self.migration = import_module("apps.boms.migrations.0021_ensure_cut_piece_unit")
        self.historical_apps = MigrationLoader(connection).project_state([
            ("reference_data", "0032_purchase_payable_number_rule")]).apps
        self.migrate_unit()

    def migrate_unit(self):
        self.migration.ensure_cut_piece_unit(self.historical_apps, SimpleNamespace(connection=connection))

    def test_missing_piece_unit_is_created_once_without_using_a_number_sequence(self):
        ProductionUnit.objects.filter(unit_name="片").delete()
        self.migrate_unit()
        unit = ProductionUnit.objects.get(unit_name="片")
        self.assertEqual((unit.unit_code, unit.status), ("BOM_CUT_PIECE", "ACTIVE"))
        self.migrate_unit()
        self.assertEqual(ProductionUnit.objects.get(unit_name="片").pk, unit.pk)

    def test_existing_active_piece_unit_is_preserved(self):
        unit = ProductionUnit.objects.get(unit_name="片")
        unit.unit_code, unit.description = "EXISTING_PIECE", "已有业务单位"
        unit.save()
        before = ProductionUnit.objects.filter(pk=unit.pk).values().get()
        self.migrate_unit()
        self.assertEqual(ProductionUnit.objects.filter(pk=unit.pk).values().get(), before)

    def test_inactive_or_archived_piece_unit_blocks_without_reactivating(self):
        unit = ProductionUnit.objects.get(unit_name="片")
        for status, archived_at in (("INACTIVE", None), ("ACTIVE", timezone.now())):
            unit.status, unit.archived_at = status, archived_at
            unit.save()
            with self.assertRaisesMessage(RuntimeError, "已停用或归档"):
                self.migrate_unit()
            unit.refresh_from_db()
            self.assertEqual((unit.status, unit.archived_at), (status, archived_at))

    def test_reserved_code_collision_blocks_without_renaming_existing_unit(self):
        ProductionUnit.objects.filter(unit_name="片").delete()
        existing = ProductionUnit.objects.create(unit_name="编码冲突测试单位", unit_code="BOM_CUT_PIECE")
        with self.assertRaisesMessage(RuntimeError, "已被其他单位占用"):
            self.migrate_unit()
        existing.refresh_from_db()
        self.assertEqual(existing.unit_name, "编码冲突测试单位")
        self.assertFalse(ProductionUnit.objects.filter(unit_name="片").exists())


class ComponentQuantityTests(SimpleTestCase):
    def rows(self):
        section = BomSection(bom=Bom(order_quantity=7), title="裁剪明细", section_type="FABRIC")
        part = BomLine(section=section, component_kind="SEWN_PART", part_name="扶手", unit="个", parts_per_product=2)
        piece = BomLine(section=section, component_kind="CUT_PIECE", part_name="内衬", unit="片",
                        parent_part=part, pieces_per_part=3, specification="50*20cm")
        return part, piece

    def test_product_part_and_piece_counts_are_separate(self):
        part, piece = self.rows()
        self.assertEqual(required_component_quantity(part), 14)
        self.assertEqual(required_component_quantity(piece), 42)
        self.assertEqual(required_component_quantity(piece, 10), 60)
        for line in (part, piece):
            apply_line_quantities(line, 7, require_complete=True)
        self.assertEqual((part.total_consumption, part.unit), ("14", "个"))
        self.assertEqual((piece.total_consumption, piece.unit, piece.total_purchase_quantity), ("42", "片", ""))

    def test_missing_ratios_do_not_become_one(self):
        part, piece = self.rows()
        part.parts_per_product = None
        apply_line_quantities(piece, 7)
        self.assertEqual(piece.total_consumption, "")
        with self.assertRaises(ValidationError):
            required_component_quantity(piece)

    def test_invalid_and_overflow_ratios_are_rejected(self):
        for value in (0, -1, "1.5", True, "NaN", 99999999999999):
            part, piece = self.rows()
            piece.pieces_per_part = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                required_component_quantity(piece)

    def test_source_attributes_do_not_replace_cut_dimensions(self):
        part, piece = self.rows()
        piece.fabric_source_line = BomLine(material="珍珠棉", specification="1.2门幅/4mm厚",
                                          raw_values={"accessory_color": "白色"})
        inherit_cutting_fabric_attributes(piece)
        self.assertEqual(piece.specification, "50*20cm")
        self.assertEqual(piece.material, "珍珠棉")
        self.assertEqual(piece.raw_values["cutting_color"], "白色")
        part.specification = "车缝成形尺寸"
        inherit_cutting_fabric_attributes(part)
        self.assertEqual(part.specification, "车缝成形尺寸")

    def test_parent_input_key_and_id_are_mutually_exclusive(self):
        values = {"part_name": "内衬", "component_kind": "CUT_PIECE", "parent_part_id": str(uuid4()),
                  "parent_part_client_key": str(uuid4())}
        self.assertFalse(BomLineWriteSerializer(data=values).is_valid())
        values.pop("parent_part_id")
        serializer = BomLineWriteSerializer(data=values)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("parent_part_client_key", serializer.data)


class ComponentPartsApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save
    verify = fixtures.MaterialFlowBomTests.verify

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name="片", defaults={"unit_code": "PART_PIECE"})
        self.part_unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "PART_EACH"})
        ProductCategory.objects.get_or_create(category_name="辅料", item_type="MATERIAL")
        self.cotton = self.material("PART_COTTON", "辅料", self.meter_unit)
        self.cotton.material = "珍珠棉"
        self.cotton.specification = "1.2门幅/4mm厚"
        self.cotton.save()

    def payload(self):
        source_key, part_key = str(uuid4()), str(uuid4())
        source = {"client_key": source_key, "part_name": "珍珠棉原料", "unit": "米", "unit_consumption": "0.56",
                  "source_inventory_material_id": str(self.cotton.pk), "material": self.cotton.material,
                  "specification": self.cotton.specification}
        part = {"client_key": part_key, "part_name": "椅面", "component_kind": "SEWN_PART",
                "parts_per_product": 2, "unit": "个"}
        piece = {"part_name": "椅面棉片", "component_kind": "CUT_PIECE", "parent_part_client_key": part_key,
                 "fabric_source_client_key": source_key, "pieces_per_part": 3, "unit": "片", "specification": "55*111cm"}
        # 裁片先于父部位和来源原料，验证同次新增不依赖列表顺序。
        return [{"title": "裁剪明细", "section_type": "FABRIC", "lines": [piece, part]},
                {"title": "辅料类", "section_type": "FABRIC", "lines": [source]}]

    def saved(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_unit_options_use_bom_permissions_and_only_active_units(self):
        from django.contrib.auth.models import Permission
        inactive = ProductionUnit.objects.create(unit_code="PART_DISABLED", unit_name="停用部位单位", status="INACTIVE")
        archived = ProductionUnit.objects.create(unit_code="PART_ARCHIVED", unit_name="归档部位单位", archived_at=timezone.now())
        self.assertFalse(self.user.user_permissions.filter(content_type__app_label="reference_data").exists())
        response = self.client.get("/api/v1/boms/editor-reference-options/")
        self.assertEqual(response.status_code, 200, response.data)
        options = response.data["data"]["component_units"]
        ids = {row["id"] for row in options}
        self.assertIn(str(self.part_unit.pk), ids)
        self.assertNotIn(str(inactive.pk), ids)
        self.assertNotIn(str(archived.pk), ids)
        self.assertEqual(set(next(row for row in options if row["id"] == str(self.part_unit.pk))), {"id", "unit_code", "unit_name"})
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label="boms", codename="change_bom"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/v1/boms/editor-reference-options/").status_code, 403)

    def test_save_new_cotton_piece_and_parent_in_one_transaction(self):
        response = self.saved()
        piece = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        part = piece.parent_part
        self.assertEqual((piece.total_consumption, part.total_consumption), ("6000", "2000"))
        self.assertEqual((piece.unit, part.unit), ("片", "个"))
        self.assertEqual(piece.fabric_source_line.section.title, "辅料类")
        self.assertEqual((piece.material, piece.specification), ("珍珠棉", "55*111cm"))
        self.assertIsNone(part.fabric_source_line_id)
        self.assertIsNone(part.material_catalog_id)
        row = next(line for section in response.data["data"]["sections"] for line in section["lines"]
                   if line["component_kind"] == "CUT_PIECE")
        self.assertEqual(UUID(row["parent_part_id"]), part.pk)
        self.assertNotIn("parent_part_client_key", row)
        verified = self.verify()
        self.assertEqual(verified.status_code, 200, verified.data)

    def test_preview_does_not_write_lines_or_convert_old_data(self):
        from .test_bom_api import BomApiTests
        current = self.get()
        sections = BomApiTests.fixed_sections(self.payload())
        ids = {section["title"]: section["id"] for section in current.data["data"]["sections"]}
        for section in sections:
            if section["title"] in ids:
                section["id"] = ids[section["title"]]
        before = list(BomLine.objects.filter(section__bom=self.bom).values())
        result = self.client.post(f"/api/v1/boms/{self.bom.pk}/material-save-preview/", {"sections": sections},
                                 format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(list(BomLine.objects.filter(section__bom=self.bom).values()), before)

    def test_copy_rebinds_both_parent_and_source_to_new_bom(self):
        self.saved()
        source_piece = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                            actor_employee=self.employee)
        piece = BomLine.objects.get(section__bom=copied, component_kind="CUT_PIECE")
        self.assertEqual(piece.parent_part.section.bom_id, copied.pk)
        self.assertEqual(piece.fabric_source_line.section.bom_id, copied.pk)
        self.assertNotEqual(piece.parent_part_id, source_piece.parent_part_id)
        self.assertEqual(piece.component_identity, source_piece.component_identity)
        self.assertEqual(piece.total_consumption, "6000")

    def test_parent_cannot_be_another_piece_or_unknown_saved_row(self):
        for invalid in ("piece", "missing"):
            payload = self.payload()
            piece, part = payload[0]["lines"]
            if invalid == "piece":
                part.update(component_kind="CUT_PIECE", parts_per_product=None, pieces_per_part=1, unit="片")
            else:
                piece.pop("parent_part_client_key")
                piece["parent_part_id"] = str(uuid4())
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)
            self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_deleting_parent_or_source_while_retaining_piece_rolls_back(self):
        saved = self.saved().data["data"]["sections"]
        before = list(BomLine.objects.filter(section__bom=self.bom).order_by("pk").values())
        for kind in ("SEWN_PART", "SOURCE"):
            payload = deepcopy(saved)
            for section in payload:
                if kind == "SOURCE" and section["title"] == "辅料类":
                    section["lines"] = []
                else:
                    section["lines"] = [line for line in section["lines"] if line["component_kind"] != kind]
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)
            self.assertEqual(list(BomLine.objects.filter(section__bom=self.bom).order_by("pk").values()), before)

    def test_foreign_bom_parent_is_rejected(self):
        saved = self.saved().data["data"]["sections"]
        other = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                           actor_employee=self.employee)
        foreign = BomLine.objects.get(section__bom=other, component_kind="SEWN_PART")
        piece = next(line for section in saved for line in section["lines"] if line["component_kind"] == "CUT_PIECE")
        piece["parent_part_id"] = str(foreign.pk)
        result = self.save(saved)
        self.assertEqual(result.status_code, 400, result.data)

    def test_whole_unused_part_and_children_can_be_removed(self):
        saved = self.saved().data["data"]["sections"]
        next(section for section in saved if section["title"] == "裁剪明细")["lines"] = []
        result = self.save(saved)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exclude(component_kind="").exists())

    def test_confirmation_requires_real_dimensions_ratios_and_children(self):
        for changed in ("dimensions", "ratio", "children"):
            payload = self.payload()
            if changed == "dimensions":
                payload[0]["lines"][0]["specification"] = ""
            elif changed == "ratio":
                payload[0]["lines"][0]["pieces_per_part"] = None
            else:
                payload[0]["lines"] = payload[0]["lines"][1:]
            response = self.save(payload)
            self.assertEqual(response.status_code, 200, response.data)
            result = self.verify()
            self.assertEqual(result.status_code, 400, result.data)

    def test_confirmation_rejects_missing_physical_source_specification(self):
        self.cotton.specification = "/"
        self.cotton.save()
        self.saved()
        result = self.verify()
        self.assertEqual(result.status_code, 400, result.data)

    def test_units_and_old_set_fields_cannot_change_new_piece_semantics(self):
        for changes in ({"unit": "不存在的单位"}, {"cutting_pieces_per_set": 2, "cutting_sets_per_product": 1}, {"pieces_per_part": 0}):
            payload = self.payload()
            payload[0]["lines"][0].update(changes)
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)
        self.part_unit.archived_at = timezone.now()
        self.part_unit.save()
        self.assertEqual(self.save(self.payload()).status_code, 400)

    def test_database_rejects_negative_component_counts(self):
        self.saved()
        piece = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BomLine.objects.filter(pk=piece.pk).update(pieces_per_part=0)

    def test_used_composition_blocks_direct_and_source_changes_but_allows_target_changes(self):
        saved = self.saved().data["data"]["sections"]
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        changed_cotton = self.material("PART_COTTON_CHANGED", "辅料", self.meter_unit)
        changed_cotton.material, changed_cotton.specification = "珍珠棉", "1.2门幅/5mm厚"
        changed_cotton.save()
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            for change in ("ratio", "dimension", "source", "parent_unit", "delete"):
                payload = deepcopy(saved)
                cut = next(section for section in payload if section["title"] == "裁剪明细")
                piece = next(line for line in cut["lines"] if line["component_kind"] == "CUT_PIECE")
                parent = next(line for line in cut["lines"] if line["component_kind"] == "SEWN_PART")
                if change == "ratio":
                    piece["pieces_per_part"] = 4
                elif change == "dimension":
                    piece["specification"] = "99*99cm"
                elif change == "source":
                    # 原料关联没变时旧接口会恢复冻结规格；改选真实不同厚度原料才会改变实物。
                    next(section for section in payload if section["title"] == "辅料类")["lines"][0]["source_inventory_material_id"] = str(changed_cotton.pk)
                elif change == "parent_unit":
                    parent["unit"] = "片"
                else:
                    cut["lines"] = []
                result = self.save(payload)
                self.assertEqual(result.status_code, 400, (change, result.data))
            payload = deepcopy(saved)
            next(line for section in payload for line in section["lines"] if line["component_kind"] == "SEWN_PART")["parts_per_product"] = 3
            result = self.save(payload)
            self.assertEqual(result.status_code, 200, result.data)

    def test_real_issued_requirement_freezes_composition_through_database_relations(self):
        from apps.material_issues.models import OrderSemiFinishedRequirement
        from apps.workshop_config.models import Craft
        from ..component_parts import _used_component_identities
        saved = self.saved().data["data"]["sections"]
        piece = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        craft, _ = Craft.objects.get_or_create(craft_type="EXTERNAL", outsourcing_code="SEWING",
                                               defaults={"name": "组成保护测试车缝"})
        # 真实关系及已领数量用于验证查询路径；不是真实业务入库验收。
        OrderSemiFinishedRequirement.objects.create(production_task=self.bom.production_task,
            product_line=self.product_line, component_identity=piece.component_identity, bom_line=piece,
            completed_craft=craft, unit=self.piece_unit, identity_key="c" * 64,
            identity_snapshot={"test": "组成已领保护"}, source_revision_hash="d" * 64,
            required_quantity=6000, internal_issued_quantity=1)
        self.assertEqual(_used_component_identities(self.bom, {piece.component_identity}), {piece.component_identity})
        line = next(line for section in saved for line in section["lines"] if line["component_kind"] == "CUT_PIECE")
        line["pieces_per_part"] = 4
        result = self.save(saved)
        self.assertEqual(result.status_code, 400, result.data)
        piece.refresh_from_db()
        self.assertEqual(piece.pieces_per_part, 3)
