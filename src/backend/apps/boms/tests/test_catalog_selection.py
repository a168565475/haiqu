from copy import deepcopy

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from apps.material_catalog.models import MaterialCatalog, MaterialAttributeValue, MaterialAllowedUnit
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit, TubeCoatingColor, TubeMaterial
from ..models import BomLine
from . import test_material_flow_bom as fixtures


class CatalogSelectionTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save
    tearDown = fixtures.MaterialFlowBomTests.tearDown

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="新目录铁管")

    def configure_tube(self):
        attrs = self.line()["material_selection"]["attributes"]
        shape = self.catalog.attribute_values.create(scope="BASE", field_key="shape", value=attrs["shape"])
        for key, value in attrs.items():
            if key != "shape":
                self.catalog.attribute_values.create(scope="BASE", field_key=key, value=value,
                                                     parent=shape if key == "section_size" else None)
        self.catalog.allowed_units.create(scope="BASE", unit=self.root_unit)

    def line(self, **changes):
        selection = {"catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
            "attributes": {"material": "铁", "shape": "矩形管", "section_size": "25*15", "thickness": "1.5", "length": "3.05"},
            "unit_id": str(self.root_unit.pk)}
        return {"part_name": self.catalog.name, "material_catalog_id": str(self.catalog.pk), "material_selection": selection,
                "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6", **changes}

    def supplied(self, *lines):
        return [{"title": "管材类", "section_type": "PROFILE", "lines": list(lines)}]

    def test_save_freezes_current_name_attributes_without_public_material_or_directory_writes(self):
        self.configure_tube()
        self.catalog.attribute_values.filter(field_key="material").update(value="此品名私有管材")
        other = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="另一品名")
        before = RawMaterialInformation.objects.count()
        data = self.line()
        data["material_selection"]["attributes"]["material"] = "此品名私有管材"
        response = self.save(self.supplied(data))
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(line.material_catalog_id, self.catalog.pk)
        self.assertEqual(line.material_selection_snapshot["attributes"]["section_size"], "25*15")
        self.assertEqual(line.material_selection_snapshot["attributes"]["material"], "此品名私有管材")
        self.assertFalse(TubeMaterial.objects.filter(material_name="此品名私有管材").exists())
        self.assertEqual(MaterialCatalog.objects.get(pk=self.catalog.pk).updated_at, self.catalog.updated_at)
        self.assertEqual(line.material_selection_snapshot["processing_stage"], "RAW")
        self.assertEqual(line.material_selection_snapshot["unit_id"], str(self.root_unit.pk))
        self.assertEqual(MaterialAttributeValue.objects.filter(catalog=self.catalog).count(), 5)
        self.assertFalse(other.attribute_values.exists())
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        self.assertEqual(response.data["data"]["sections"][0]["lines"][0]["material_catalog_id"], str(self.catalog.pk))

    def test_preview_is_read_only_and_needs_no_legacy_creation_confirmation(self):
        from .test_bom_api import BomApiTests
        self.configure_tube()
        current = self.get()
        sections = BomApiTests.fixed_sections(self.supplied(self.line()))
        section_ids = {section["title"]: section["id"] for section in current.data["data"]["sections"]}
        for section in sections:
            if section["title"] in section_ids:
                section["id"] = section_ids[section["title"]]
        response = self.client.post(f"/api/v1/boms/{self.bom.pk}/material-save-preview/",
            {"sections": sections, "intent": "draft"},
            format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["new_materials"], [])
        self.assertEqual(self.catalog.attribute_values.count(), 5)
        self.assertEqual(self.catalog.allowed_units.count(), 1)

    def test_invalid_second_pipe_leaves_configured_catalog_and_bom_unchanged(self):
        from uuid import uuid4
        self.configure_tube()
        second = self.line(material_catalog_id=str(uuid4()))
        response = self.save(self.supplied(self.line(), second))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.catalog.attribute_values.count(), 5)
        self.assertEqual(self.catalog.allowed_units.count(), 1)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom, material_catalog__isnull=False).exists())

    def test_multiple_lines_reuse_configured_options_within_transaction(self):
        self.configure_tube()
        response = self.save(self.supplied(self.line(), self.line(length_value="600")))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.catalog.attribute_values.count(), 5)
        self.assertEqual(self.catalog.allowed_units.count(), 1)

    def test_unchanged_saved_selection_preserves_history_after_directory_edits(self):
        self.configure_tube()
        self.assertEqual(self.save(self.supplied(self.line())).status_code, 200)
        line = BomLine.objects.get(section__bom=self.bom)
        frozen = deepcopy(line.material_selection_snapshot)
        self.catalog.name = "目录后来改名"
        self.catalog.save()
        self.catalog.attribute_values.update(archived_at=timezone.now())
        response = self.save(self.supplied({"id": str(line.pk), "part_name": "任意覆盖不能改变快照", "length_value": "500",
            "unit_consumption": "2", "tube_cut_piece_count": "6", "material_catalog_id": str(self.catalog.pk)}))
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertEqual(line.material_selection_snapshot, frozen)
        self.assertEqual(line.part_name, frozen["name"])

    def test_wrong_category_and_mixed_legacy_source_rejected(self):
        line = self.line(source_inventory_material_id=str(self.pipe.pk))
        self.assertEqual(self.save(self.supplied(line)).status_code, 400)
        self.catalog.category_key = self.catalog.template_key = "FABRIC"
        self.catalog.save()
        self.assertEqual(self.save(self.supplied(self.line())).status_code, 400)

    def test_stale_catalog_version_rejected_before_writes(self):
        line = self.line()
        self.catalog.save()
        response = self.save(self.supplied(line))
        self.assertEqual(response.status_code, 412, response.data)
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_viewer_can_select_configured_pipe_without_maintenance_permission(self):
        self.configure_tube()
        self.user.user_permissions.remove(Permission.objects.get(codename="change_materialcatalog"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        response = self.save(self.supplied(self.line()))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.catalog.attribute_values.count(), 5)

    def test_public_or_other_pipe_material_and_wrong_shape_dimension_are_rejected(self):
        self.configure_tube()
        other = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="别的管材")
        public = TubeMaterial.objects.create(material_name="公共和其他品名有的材质")
        other.attribute_values.create(scope="BASE", field_key="material", value=public.material_name)
        shape = self.catalog.attribute_values.create(scope="BASE", field_key="shape", value="方管")
        self.catalog.attribute_values.create(scope="BASE", field_key="section_size", value="20*20", parent=shape)
        for key, value in (("material", public.material_name), ("section_size", "20*20")):
            with self.subTest(key=key):
                line = self.line()
                line["material_selection"]["attributes"][key] = value
                response = self.save(self.supplied(line))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("当前品名", str(response.data))
        self.assertEqual(self.catalog.attribute_values.count(), 7)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_archived_pipe_attribute_and_unregistered_root_unit_are_rejected(self):
        self.configure_tube()
        thickness = self.catalog.attribute_values.get(field_key="thickness")
        thickness.archived_at = timezone.now()
        thickness.save(update_fields=["archived_at"])
        self.assertEqual(self.save(self.supplied(self.line())).status_code, 400)
        thickness.refresh_from_db()
        self.assertIsNotNone(thickness.archived_at)
        thickness.archived_at = None
        thickness.save(update_fields=["archived_at"])
        self.catalog.allowed_units.update(archived_at=timezone.now())
        response = self.save(self.supplied(self.line()))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("单位", str(response.data))
        self.assertFalse(self.catalog.allowed_units.filter(archived_at__isnull=True).exists())

    def test_formal_bom_cannot_add_units_or_use_another_catalogs_attributes(self):
        catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="U2独立单位五金")
        other = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="U2同模板五金")
        other.attribute_values.create(scope="BASE", field_key="specification", value="M6")
        catalog.allowed_units.create(scope="BASE", unit=self.root_unit)
        line = {"part_name": catalog.name, "material_catalog_id": str(catalog.pk), "material_selection": {
            "catalog_version": catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
            "attributes": {"specification": "M6"}, "unit_id": str(self.root_unit.pk)}}
        sections = [{"title": "五金件", "section_type": "ACCESSORY", "lines": [line]}]
        self.assertEqual(self.save(sections).status_code, 400)
        self.assertFalse(catalog.attribute_values.exists())
        catalog.attribute_values.create(scope="BASE", field_key="specification", value="M6")
        line["material_selection"]["unit_id"] = str(self.meter_unit.pk)
        self.assertEqual(self.save(sections).status_code, 400)
        self.assertFalse(catalog.allowed_units.filter(unit=self.meter_unit).exists())

    def test_same_name_private_units_record_the_selected_catalog_unit_id(self):
        catalogs = [MaterialCatalog.objects.create(category_key="PACKAGING", template_key="BAG", name=name)
                    for name in ("纸袋甲", "纸袋乙")]
        units = []
        for catalog in catalogs:
            catalog.attribute_values.create(scope="BASE", field_key="size", value="30×40")
            unit = ProductionUnit.all_objects.create(catalog_owner=catalog, unit_code=catalog.name, unit_name="专用捆")
            catalog.allowed_units.create(scope="BASE", unit=unit)
            units.append(unit)
        selected = {"catalog_version": catalogs[0].updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                    "attributes": {"size": "30×40"}, "unit_id": str(units[1].pk)}
        sections = [{"title": "包材类", "section_type": "ACCESSORY", "lines": [{
            "part_name": catalogs[0].name, "material_catalog_id": str(catalogs[0].pk), "units_per_box": "12",
            "material_selection": selected}]}]
        self.assertEqual(self.save(sections).status_code, 400)
        selected["unit_id"] = str(units[0].pk)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        saved = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(saved.unit, "专用捆")
        self.assertEqual(saved.material_selection_snapshot["unit_id"], str(units[0].pk))
        self.assertFalse(ProductionUnit.objects.filter(unit_name="专用捆").exists())

    def test_missing_shape_and_placeholder_spec_are_rejected(self):
        for field, value in (("shape", ""), ("section_size", "/"), ("material", "")):
            with self.subTest(field=field):
                line = self.line()
                line["material_selection"]["attributes"][field] = value
                self.assertEqual(self.save(self.supplied(line)).status_code, 400)
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_missing_bom_etag_is_rejected(self):
        response = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": self.supplied(self.line())}, format="json")
        self.assertEqual(response.status_code, 428, response.data)

    def test_missing_unit_id_is_validation_error_and_rolls_back(self):
        from uuid import uuid4
        self.configure_tube()
        line = self.line()
        line["material_selection"]["unit_id"] = str(uuid4())
        response = self.save(self.supplied(line))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("单位", str(response.data))
        self.assertEqual(self.catalog.attribute_values.count(), 5)

    def test_result_color_requires_current_pipe_spray_option_and_stays_out_of_raw_snapshot(self):
        self.configure_tube()
        self.catalog.spray_enabled = True
        self.catalog.save()
        public = TubeCoatingColor.objects.create(color_name="公共喷塑色未给本品名")
        rejected = self.save(self.supplied(self.line(tube_coating_color=public.color_name)))
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertFalse(self.catalog.attribute_values.filter(scope="SPRAY", value=public.color_name).exists())
        color = "此品名私有喷塑色"
        self.catalog.attribute_values.create(scope="SPRAY", field_key="color", value=color)
        response = self.save(self.supplied(self.line(tube_coating_color=color)))
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(line.material_selection_snapshot["processing_state"], "RAW")
        self.assertIsNone(line.material_selection_snapshot["completed_craft"])
        self.assertNotIn("color", line.material_selection_snapshot["attributes"])
        self.assertFalse(TubeCoatingColor.objects.filter(color_name=color).exists())
        self.assertEqual(line.raw_values["tube_coating_color"], color)

    def test_cutting_selection_retains_processed_state_and_actual_craft(self):
        from apps.workshop_config.models import Craft
        from apps.reference_data.models import ProductionUnit, ProductColor, MaterialAttributePublicValue
        from apps.material_catalog.saved_selection import validate_saved_material
        from uuid import uuid4
        craft, _ = Craft.objects.get_or_create(craft_type="EXTERNAL", outsourcing_code="CUTTING", defaults={"name": "U2裁剪"})
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "U2SET"})
        catalog = MaterialCatalog.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="U2座布裁片")
        fabric_catalog = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="U2来源面料")
        source_attrs = {"material": "涤纶", "fabric_spec": "600D", "width": "1.5", "color": "蓝色"}
        for key, value in [*source_attrs.items(), ("fabric_spec", "400D"), ("material", "锦纶"), ("width", "1.8")]:
            if key != "color":
                fabric_catalog.attribute_values.create(scope="BASE", field_key=key, value=value)
        color = ProductColor.objects.create(color_card="CUT-SOURCE-A", color_code="01", color_name="蓝色")
        next_color = ProductColor.objects.create(color_card="CUT-SOURCE-B", color_code="02", color_name="蓝色")
        for item in (color, next_color):
            fabric_catalog.attribute_values.create(scope="BASE", field_key="color", value=item.color_name, product_color=item)
        catalog.allowed_units.create(scope="BASE", unit=unit)
        fabric_catalog.allowed_units.create(scope="BASE", unit=self.meter_unit)
        source_key = str(uuid4())
        source = {"client_key": source_key, "part_name": fabric_catalog.name, "material_catalog_id": str(fabric_catalog.pk), "unit_consumption": "1",
                  "material_selection": {"catalog_version": fabric_catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                                         "attributes": source_attrs, "unit_id": str(self.meter_unit.pk), "product_color_id": str(color.pk),
                                         "color_card": color.color_card, "color_code": color.color_code, "color_name": color.color_name}}
        selected = {"catalog_version": catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "PROCESSED",
            "semi_kind": "CUTTING", "completed_craft": {"id": str(craft.pk), "craft_type": "EXTERNAL", "code": "CUTTING"},
            "attributes": {"material": "伪造材质", "width": "伪造门幅", "size": "伪造尺寸", "color": "伪造颜色", "specification": "伪造规格", "model": "旧款号", "process": "旧做法"}, "unit_id": str(unit.pk)}
        line = {"part_name": catalog.name, "material_catalog_id": str(catalog.pk), "material_selection": selected,
            "category": "管材", "cutting_category": "管材",
            "fabric_source_client_key": source_key, "cutting_pieces_per_set": 2, "cutting_sets_per_product": 1}
        supplied = [{"title": "面料类", "section_type": "FABRIC", "lines": [source]}, {"title": "裁剪明细", "section_type": "FABRIC", "lines": [line]}]
        public_count = MaterialAttributePublicValue.objects.count()
        response = self.save(supplied)
        self.assertEqual(response.status_code, 200, response.data)
        saved = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(saved.material_selection_snapshot["processing_state"], "PROCESSED")
        self.assertEqual(saved.material_selection_snapshot["processing_stage"], "CUTTING")
        self.assertEqual(saved.material_selection_snapshot["completed_craft"], selected["completed_craft"])
        self.assertEqual(saved.unit, "套")
        self.assertEqual(saved.specification, "600D / 1.5")
        self.assertEqual(saved.raw_values["cutting_color"], "蓝色")
        self.assertEqual(saved.material, "涤纶")
        self.assertEqual(saved.raw_values["fabric_width"], "1.5")
        self.assertEqual(saved.material_selection_snapshot["attributes"], {"material": "涤纶", "width": "1.5", "specification": "600D", "color": "蓝色"})
        self.assertEqual(saved.material_selection_snapshot["product_color_id"], str(color.pk))
        validate_saved_material(saved.material_selection_snapshot, material_catalog_id=catalog.pk)
        self.assertEqual(MaterialAttributePublicValue.objects.count(), public_count)
        saved_selection = deepcopy(saved.material_selection_snapshot)
        self.assertEqual(self.get().data["data"]["sections"][-1]["lines"][0]["material_selection_snapshot"], saved_selection)
        payload = self.get().data["data"]["sections"]
        fabric_payload = next(section for section in payload if section["title"] == "面料类")["lines"][0]
        source_selection = deepcopy(BomLine.objects.get(section__bom=self.bom, section__title="面料类").material_selection_snapshot)
        source_selection.pop("unit_name", None)
        source_selection["attributes"]["fabric_spec"] = "400D"
        source_selection["attributes"].update(material="锦纶", width="1.8")
        source_selection.update(product_color_id=str(next_color.pk), color_card=next_color.color_card, color_code=next_color.color_code, color_name=next_color.color_name)
        fabric_payload["material_selection"] = source_selection
        changed = self.save(payload)
        self.assertEqual(changed.status_code, 200, changed.data)
        saved.refresh_from_db()
        self.assertEqual(saved.specification, "400D / 1.8")
        self.assertEqual(saved.material, "锦纶")
        self.assertEqual(saved.raw_values["fabric_width"], "1.8")
        self.assertEqual(saved.material_selection_snapshot["attributes"], {"material": "锦纶", "width": "1.8", "specification": "400D", "color": "蓝色"})
        self.assertEqual(saved.material_selection_snapshot["product_color_id"], str(next_color.pk))
        validate_saved_material(saved.material_selection_snapshot, material_catalog_id=catalog.pk)
        selected["processing_state"] = "RAW"
        catalog.refresh_from_db()
        selected["catalog_version"] = catalog.updated_at.isoformat()
        cutting_payload = next(section for section in changed.data["data"]["sections"] if section["title"] == "裁剪明细")["lines"][0]
        cutting_payload["material_selection"] = selected
        self.assertEqual(self.save(changed.data["data"]["sections"]).status_code, 400)

    def test_existing_new_material_cannot_be_moved_to_wrong_section(self):
        self.configure_tube()
        self.assertEqual(self.save(self.supplied(self.line())).status_code, 200)
        line = BomLine.objects.get(section__bom=self.bom)
        response = self.save([{"title": "五金件", "section_type": "ACCESSORY", "lines": [{"id": str(line.pk),
            "part_name": line.part_name, "material_catalog_id": str(self.catalog.pk)}]}])
        self.assertEqual(response.status_code, 400, response.data)

    def test_each_non_pipe_template_saves_its_real_identity(self):
        cases = [
            ("FABRIC", "FABRIC", "面料类", "FABRIC", {"material": "布", "fabric_spec": "600D", "width": "150", "color": "黑"}),
            ("HARDWARE", "HARDWARE", "五金件", "ACCESSORY", {"material": "铁", "specification": "M6"}),
            ("PLASTIC", "PLASTIC", "塑料件类", "ACCESSORY", {"material": "PP", "model": "圆管塞25"}),
            ("PACKAGING", "CARTON", "包材类", "ACCESSORY", {"material": "纸", "size": "40*30*20"}),
            ("PACKAGING", "BAG", "包材类", "ACCESSORY", {"material": "PE", "size": "40*60"}),
            ("PACKAGING", "PACKAGING_GENERAL", "包材类", "ACCESSORY", {"material": "纸", "specification": "40"}),
            ("AUXILIARY", "TAPE", "辅料类", "FABRIC", {"material": "涤纶", "width": "25"}),
            ("AUXILIARY", "COTTON", "辅料类", "FABRIC", {"material": "棉", "thickness": "5"}),
            ("AUXILIARY", "AUXILIARY_GENERAL", "辅料类", "FABRIC", {"material": "涤纶", "specification": "20"}),
        ]
        for category, template, title, kind, attrs in cases:
            with self.subTest(template=template):
                catalog = MaterialCatalog.objects.create(category_key=category, template_key=template, name="U2"+template)
                for key, value in attrs.items():
                    catalog.attribute_values.create(scope="BASE", field_key=key, value=value)
                catalog.allowed_units.create(scope="BASE", unit=self.meter_unit)
                line = {"part_name": catalog.name, "material_catalog_id": str(catalog.pk), "unit_consumption": "2",
                    "material_selection": {"catalog_version": catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                        "attributes": attrs, "unit_id": str(self.meter_unit.pk)}}
                if title == "包材类":
                    line["units_per_box"] = "12"
                response = self.save([{"title": title, "section_type": kind, "lines": [line]}])
                self.assertEqual(response.status_code, 200, response.data)
                saved = BomLine.objects.get(section__bom=self.bom, material_catalog=catalog)
                self.assertEqual(saved.material_selection_snapshot["attributes"], attrs)

    def test_optional_material_is_not_made_mandatory_for_packaging(self):
        catalog = MaterialCatalog.objects.create(category_key="PACKAGING", template_key="CARTON", name="U2尺寸确定的纸箱")
        catalog.attribute_values.create(scope="BASE", field_key="size", value="40*30*20")
        catalog.allowed_units.create(scope="BASE", unit=self.root_unit)
        line = {"part_name": catalog.name, "material_catalog_id": str(catalog.pk), "units_per_box": "12", "material_selection": {
            "catalog_version": catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
            "attributes": {"size": "40*30*20"}, "unit_id": str(self.root_unit.pk)}}
        response = self.save([{"title": "包材类", "section_type": "ACCESSORY", "lines": [line]}])
        self.assertEqual(response.status_code, 200, response.data)
        saved = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(saved.material_selection_snapshot["attributes"], {"size": "40*30*20"})
        self.assertEqual(saved.unit_consumption, "")
        self.assertEqual(saved.total_consumption, "84")
        self.bom.order_quantity = 1009
        self.bom.save(update_fields=["order_quantity"])
        from apps.boms.services import _sync_profile_lines_to_order_quantity
        _sync_profile_lines_to_order_quantity(self.bom)
        saved.refresh_from_db()
        self.assertEqual(saved.total_consumption, "85")

    def test_profile_catalog_rejects_non_root_units_without_partial_options(self):
        self.configure_tube()
        self.catalog.allowed_units.create(scope="BASE", unit=self.meter_unit)
        for unit_name in ("米", "公斤"):
            with self.subTest(unit_name=unit_name):
                line = self.line()
                line["material_selection"].pop("unit_id")
                line["material_selection"]["unit_name"] = unit_name
                response = self.save(self.supplied(line))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(self.catalog.attribute_values.count(), 5)
                self.assertEqual(self.catalog.allowed_units.count(), 2)
                self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_profile_does_not_accept_independent_material_total(self):
        self.configure_tube()
        for value in ("12.5", "0", "-1", "NaN", "Infinity"):
            with self.subTest(value=value):
                line = self.line(material_quantity=value)
                self.assertEqual(self.save(self.supplied(line)).status_code, 400)
        self.assertEqual(self.catalog.attribute_values.count(), 5)
