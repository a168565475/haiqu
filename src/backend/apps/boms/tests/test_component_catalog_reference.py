from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
from apps.procurement.services import _bom_source_details
from apps.reference_data.models import MaterialAttributePublicValue
from ..models import BomLine
from ..services import create_bom
from . import test_component_parts as fixtures


class ComponentCatalogReferenceTests(TestCase):
    setUpFixture = fixtures.ComponentPartsApiTests.setUpFixture
    tearDown = fixtures.ComponentPartsApiTests.tearDown
    material = fixtures.ComponentPartsApiTests.material
    get = fixtures.ComponentPartsApiTests.get
    save = fixtures.ComponentPartsApiTests.save
    verify = fixtures.ComponentPartsApiTests.verify

    def setUp(self):
        fixtures.ComponentPartsApiTests.setUp(self)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="material_catalog", codename="view_materialcatalog"))
        self.part_catalog = MaterialCatalog.objects.create(
            category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="椅面")
        self.piece_catalog = MaterialCatalog.objects.create(
            category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="椅面棉片")

    def bind(self, line, catalog, *, attributes=None):
        line.update(material_catalog_id=str(catalog.pk), material_selection={
            "catalog_version": catalog.updated_at.isoformat(), "scope": "BASE",
            "processing_state": "PROCESSED", "attributes": attributes or {},
            "unit_name": line["unit"],
        })

    def payload(self):
        rows = fixtures.ComponentPartsApiTests.payload(self)
        for line in rows[0]["lines"]:
            self.bind(line, self.part_catalog if line["component_kind"] == "SEWN_PART" else self.piece_catalog)
        return rows

    def saved(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]["sections"]

    def test_names_use_existing_catalog_without_creating_options_or_fake_craft(self):
        before = (MaterialAllowedUnit.objects.count(), MaterialAttributeValue.objects.count())
        rows = self.payload()
        for line in rows[0]["lines"]:
            line["part_name"] = "客户端伪造名称"
        result = self.save(rows)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual((MaterialAllowedUnit.objects.count(), MaterialAttributeValue.objects.count()), before)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        piece = part.cut_pieces.get()
        self.assertEqual((part.part_name, piece.part_name), ("椅面", "椅面棉片"))
        self.assertEqual((part.unit, piece.unit), ("个", "片"))
        self.assertIsNone(part.fabric_source_line_id)
        self.assertEqual((part.total_purchase_quantity, piece.total_purchase_quantity), ("", ""))
        self.assertEqual((piece.material, piece.specification), ("珍珠棉", "55*111cm"))
        for line in (part, piece):
            selected = line.material_selection_snapshot
            self.assertEqual(selected["selection_kind"], "BOM_COMPONENT_REFERENCE")
            self.assertEqual(selected["attributes"], {})
            self.assertIsNone(selected["completed_craft"])
            self.assertIsNone(selected["semi_kind"])
        self.assertEqual(self.verify().status_code, 200)
        self.bom.refresh_from_db()
        _, purchasable = _bom_source_details(self.product_line, self.bom)
        self.assertEqual([row["bom_line_id"] for row in purchasable], [str(piece.fabric_source_line_id)])

    def test_optional_real_attributes_are_frozen_but_do_not_replace_piece_dimensions(self):
        MaterialAttributeValue.objects.create(catalog=self.piece_catalog, scope="BASE", field_key="model", value="图号 A")
        rows = self.payload()
        piece = next(line for line in rows[0]["lines"] if line["component_kind"] == "CUT_PIECE")
        piece["material_selection"]["attributes"] = {"model": "图号 A"}
        result = self.save(rows)
        self.assertEqual(result.status_code, 200, result.data)
        saved = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        self.assertEqual(saved.material_selection_snapshot["attributes"], {"model": "图号 A"})
        self.assertEqual(saved.specification, "55*111cm")
        piece["material_selection"]["attributes"] = {"model": "未维护图号"}
        rejected = self.save(rows)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        saved.refresh_from_db()
        self.assertEqual(saved.material_selection_snapshot["attributes"], {"model": "图号 A"})

    def test_catalog_version_permission_and_wrong_units_fail_without_partial_save(self):
        for change, expected in (("version", 412), ("category", 400), ("unit", 400), ("craft", 400)):
            rows = self.payload()
            parent = next(line for line in rows[0]["lines"] if line["component_kind"] == "SEWN_PART")
            if change == "version":
                parent["material_selection"]["catalog_version"] = "stale"
            elif change == "category":
                wrong = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="不是部位档案")
                self.bind(parent, wrong)
            elif change == "unit":
                parent["material_selection"]["unit_name"] = "米"
            else:
                parent["material_selection"]["semi_kind"] = "CUTTING"
            response = self.save(rows)
            self.assertEqual(response.status_code, expected, (change, response.data))
            self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="material_catalog", codename="view_materialcatalog"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        self.assertEqual(self.save(self.payload()).status_code, 403)

    def test_public_attributes_fill_part_details_without_creating_catalog_options(self):
        attrs = {"model": "椅面图号 A", "size": "成形 50*60cm"}
        for key, value in attrs.items():
            MaterialAttributePublicValue.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI",
                scope="BASE", field_key=key, value=value)
        before = (MaterialAllowedUnit.objects.count(), MaterialAttributeValue.objects.count(),
                  MaterialAttributePublicValue.objects.count())
        rows = self.payload()
        parent = next(line for line in rows[0]["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(parent, self.part_catalog, attributes=attrs)
        response = self.save(rows)
        self.assertEqual(response.status_code, 200, response.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        self.assertEqual(part.specification, "成形 50*60cm")
        self.assertEqual(part.material_selection_snapshot["attributes"], attrs)
        self.assertEqual(part.material_selection_snapshot["identity_attributes_version"], 1)
        self.assertEqual(part.material, "")
        self.assertFalse(part.raw_values.get("cutting_color"))
        self.assertFalse(part.raw_values.get("fabric_color_name"))
        self.assertFalse(part.raw_values.get("fabric_width"))
        self.assertEqual(before, (MaterialAllowedUnit.objects.count(), MaterialAttributeValue.objects.count(),
                                 MaterialAttributePublicValue.objects.count()))
        self.assertEqual(self.verify().status_code, 200)

    def test_new_part_and_piece_references_cannot_select_source_material_attributes(self):
        for kind in ("SEWN_PART", "CUT_PIECE"):
            for key, value in (("material", "涤纶"), ("color", "蓝色"), ("fabric_spec", "600D"), ("width", "150cm")):
                with self.subTest(kind=kind, key=key):
                    rows = self.payload()
                    line = next(line for line in rows[0]["lines"] if line["component_kind"] == kind)
                    catalog = self.part_catalog if kind == "SEWN_PART" else self.piece_catalog
                    MaterialAttributeValue.objects.get_or_create(catalog=catalog, scope="BASE", field_key=key, value=value)
                    self.bind(line, catalog, attributes={key: value})
                    response = self.save(rows)
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn("来自关联原料", str(response.data))
                    self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_existing_source_attributes_survive_save_and_catalog_refresh_without_rewriting_identity(self):
        self.saved()
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        piece = part.cut_pieces.get()
        attrs = {"material": "历史独立材质", "color": "历史颜色", "fabric_spec": "历史规格", "width": "历史门幅"}
        for line in (part, piece):
            # 隔离夹具保留升级前已保存的数据；正式保存接口不允许新增这些独立原料属性。
            line.material_selection_snapshot.update(attributes=deepcopy(attrs), identity_attributes_version=1)
            line.save(update_fields=["material_selection_snapshot"])
        part.material = "历史兼容字段"
        part.raw_values.update(cutting_color="历史兼容颜色", fabric_color_name="历史兼容颜色", fabric_width="历史兼容门幅")
        part.save(update_fields=["material", "raw_values"])
        craft = SimpleNamespace(pk=uuid4(), craft_type="EXTERNAL", outsourcing_code="SEWING")
        before = build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit)
        saved_snapshots = {line.pk: deepcopy(line.material_selection_snapshot) for line in (part, piece)}
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            response = self.save(self.get().data["data"]["sections"])
        self.assertEqual(response.status_code, 200, response.data)
        for line in (part, piece):
            line.refresh_from_db()
            self.assertEqual(line.material_selection_snapshot, saved_snapshots[line.pk])
        self.part_catalog.save()
        self.piece_catalog.save()
        sections = self.get().data["data"]["sections"]
        for section in sections:
            for line in section["lines"]:
                if line["component_kind"]:
                    self.bind(line, self.part_catalog if line["component_kind"] == "SEWN_PART" else self.piece_catalog,
                              attributes=deepcopy(attrs))
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        part.refresh_from_db()
        self.assertEqual(part.material, "历史兼容字段")
        self.assertEqual(part.raw_values["fabric_width"], "历史兼容门幅")
        self.assertEqual(before, build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit))
        self.assertEqual(part.material_selection_snapshot["attributes"], attrs)
        self.assertEqual(part.material_selection_snapshot["identity_attributes_version"], 1)
        parent = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
        parent["material_selection"]["attributes"]["color"] = "另选颜色"
        response = self.save(sections)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("来自关联原料", str(response.data))

    def test_explicit_part_dimensions_win_and_inactive_public_attributes_roll_back(self):
        option = MaterialAttributePublicValue.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI",
            scope="BASE", field_key="size", value="档案尺寸")
        rows = self.payload()
        parent = next(line for line in rows[0]["lines"] if line["component_kind"] == "SEWN_PART")
        parent["specification"] = "本单成形尺寸"
        self.bind(parent, self.part_catalog, attributes={"size": option.value})
        option.status = "INACTIVE"
        option.save()
        response = self.save(rows)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())
        option.status = "ACTIVE"
        option.save()
        response = self.save(rows)
        self.assertEqual(response.status_code, 200, response.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        self.assertEqual(part.specification, "本单成形尺寸")

    def test_refreshing_legacy_attributes_does_not_reinterpret_stock_identity(self):
        MaterialAttributeValue.objects.create(catalog=self.part_catalog, scope="BASE", field_key="model", value="旧图号")
        rows = self.payload()
        parent = next(line for line in rows[0]["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(parent, self.part_catalog, attributes={"model": "旧图号"})
        response = self.save(rows)
        self.assertEqual(response.status_code, 200, response.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        part.material_selection_snapshot.pop("identity_attributes_version")
        part.save(update_fields=["material_selection_snapshot"])
        craft = SimpleNamespace(pk=uuid4(), craft_type="EXTERNAL", outsourcing_code="SEWING")
        before = build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit)
        self.part_catalog.save()
        sections = self.get().data["data"]["sections"]
        parent = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(parent, self.part_catalog, attributes={"model": "旧图号"})
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        part.refresh_from_db()
        self.assertNotIn("identity_attributes_version", part.material_selection_snapshot)
        self.assertEqual(before, build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit))

    def test_unchanged_reference_keeps_snapshot_after_catalog_rename_or_archive(self):
        sections = self.saved()
        parent = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        frozen = deepcopy(parent.material_selection_snapshot)
        self.part_catalog.name = "目录后来改名"
        self.part_catalog.archived_at = timezone.now()
        self.part_catalog.save()
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        parent.refresh_from_db()
        self.assertEqual(parent.material_selection_snapshot, frozen)
        self.assertEqual(parent.part_name, "椅面")

    def test_copy_keeps_catalog_reference_and_rebinds_local_composition(self):
        self.saved()
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                            actor_employee=self.employee)
        piece = BomLine.objects.get(section__bom=copied, component_kind="CUT_PIECE")
        self.assertEqual(piece.material_catalog_id, self.piece_catalog.pk)
        self.assertEqual(piece.parent_part.material_catalog_id, self.part_catalog.pk)
        self.assertEqual(piece.fabric_source_line.section.bom_id, copied.pk)
        self.assertEqual(piece.parent_part.section.bom_id, copied.pk)

    def test_explicit_current_catalog_version_refreshes_name_but_used_name_is_protected(self):
        sections = self.saved()
        self.part_catalog.name = "更新后的椅面"
        self.part_catalog.save()
        row = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(row, self.part_catalog)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        self.assertEqual(part.part_name, "更新后的椅面")
        self.part_catalog.name = "已流转后目录再次改名"
        self.part_catalog.save()
        sections = response.data["data"]["sections"]
        row = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(row, self.part_catalog)
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            rejected = self.save(sections)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        part.refresh_from_db()
        self.assertEqual(part.part_name, "更新后的椅面")

    def test_used_component_cannot_change_catalog_but_can_change_target_quantity(self):
        sections = self.saved()
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        another = MaterialCatalog.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="另一椅面")
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            changed = deepcopy(sections)
            row = next(line for section in changed for line in section["lines"] if line["component_kind"] == "SEWN_PART")
            self.bind(row, another)
            response = self.save(changed)
            self.assertEqual(response.status_code, 400, response.data)
            row = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
            row["parts_per_product"] = 3
            response = self.save(sections)
            self.assertEqual(response.status_code, 200, response.data)

    def test_catalog_reference_does_not_reinterpret_existing_inventory_identity(self):
        plain = fixtures.ComponentPartsApiTests.payload(self)
        response = self.save(plain)
        self.assertEqual(response.status_code, 200, response.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        craft = SimpleNamespace(pk=uuid4(), craft_type="EXTERNAL", outsourcing_code="SEWING")
        before = build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit)
        sections = response.data["data"]["sections"]
        for section in sections:
            for line in section["lines"]:
                if line["component_kind"]:
                    self.bind(line, self.part_catalog if line["component_kind"] == "SEWN_PART" else self.piece_catalog)
        result = self.save(sections)
        self.assertEqual(result.status_code, 200, result.data)
        part.refresh_from_db()
        after = build_semi_finished_identity(bom_line=part, completed_craft=craft, unit=self.part_unit)
        self.assertEqual(before, after)

    def test_one_catalog_can_be_part_or_piece_in_different_boms(self):
        self.saved()
        first_bom = self.bom
        self.bom = create_bom(product_line=self.product_line, creation_method="BLANK", actor_employee=self.employee)
        rows = self.payload()
        piece = next(line for line in rows[0]["lines"] if line["component_kind"] == "CUT_PIECE")
        self.bind(piece, self.part_catalog)
        result = self.save(rows)
        self.assertEqual(result.status_code, 200, result.data)
        first = BomLine.objects.get(section__bom=first_bom, material_catalog=self.part_catalog)
        second = BomLine.objects.get(section__bom=self.bom, component_kind="CUT_PIECE")
        self.assertEqual((first.component_kind, second.component_kind), ("SEWN_PART", "CUT_PIECE"))
        self.assertEqual(first.material_catalog_id, second.material_catalog_id)
        self.part_catalog.refresh_from_db()
        self.assertEqual((self.part_catalog.category_key, self.part_catalog.name), ("FABRIC_SEMI", "椅面"))
        self.assertFalse(self.part_catalog.allowed_units.exists())

    def test_used_unlinked_component_cannot_be_rebound_to_catalog(self):
        result = self.save(fixtures.ComponentPartsApiTests.payload(self))
        self.assertEqual(result.status_code, 200, result.data)
        part = BomLine.objects.get(section__bom=self.bom, component_kind="SEWN_PART")
        sections = result.data["data"]["sections"]
        row = next(line for section in sections for line in section["lines"] if line["component_kind"] == "SEWN_PART")
        self.bind(row, self.part_catalog)
        with patch("apps.boms.component_parts._used_component_identities", return_value={part.component_identity}):
            rejected = self.save(sections)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        part.refresh_from_db()
        self.assertIsNone(part.material_catalog_id)
        self.assertEqual(part.material_selection_snapshot, {})

    def test_non_component_catalog_selection_still_requires_real_attributes(self):
        rows = self.payload()
        source = rows[1]["lines"][0]
        source.pop("source_inventory_material_id")
        catalog = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key="COTTON", name="空属性原棉")
        self.bind(source, catalog)
        source["material_selection"]["processing_state"] = "RAW"
        result = self.save(rows)
        self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())
