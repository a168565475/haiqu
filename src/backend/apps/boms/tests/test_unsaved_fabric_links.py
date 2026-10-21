from copy import deepcopy
from uuid import UUID, uuid4

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import FabricMaterial, FabricSpecification, ProductCategory, ProductionUnit
from ..api.serializers import BomLineWriteSerializer, BomUpdateInputSerializer
from ..material_flow_bom import validate_fabric_links
from ..models import Bom, BomLine, BomSection, BomStatus
from ..services import create_bom, update_bom_lines
from . import test_bom_api as api_fixtures
from . import test_material_flow_bom as fixtures


class UnsavedFabricLinkInputTests(SimpleTestCase):
    def test_unmapped_meter_fabric_can_be_linked_in_draft_without_inventory_lookup(self):
        bom = Bom(pk=uuid4())
        fabric_section = BomSection(pk=uuid4(), bom=bom, section_type="FABRIC", title="面料类", line_number=1)
        cutting_section = BomSection(pk=uuid4(), bom=bom, section_type="FABRIC", title="裁剪明细", line_number=2)
        fabric = BomLine(pk=uuid4(), section=fabric_section, line_number=1, part_name="20",
                         material="PVC", specification="400*300D", unit="米", raw_values={})
        cutting = BomLine(pk=uuid4(), section=cutting_section, line_number=1, part_name="座布",
                          fabric_source_line=fabric, unit="套", raw_values={})
        validate_fabric_links([fabric, cutting], require_complete=False)
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)

    def test_malformed_fabric_reference_returns_validation_error(self):
        bom = Bom(pk=uuid4())
        fabric_section = BomSection(pk=uuid4(), bom=bom, section_type="FABRIC", title="面料类", line_number=1)
        cutting_section = BomSection(pk=uuid4(), bom=bom, section_type="FABRIC", title="裁剪明细", line_number=2)
        fabric = BomLine(pk=uuid4(), section=fabric_section, line_number=1, unit="米",
                         raw_values={"source_fabric_material_id": "invalid-uuid"})
        cutting = BomLine(pk=uuid4(), section=cutting_section, line_number=1, fabric_source_line=fabric)
        with self.assertRaisesMessage(ValidationError, "材质、规格、门幅和颜色"):
            validate_fabric_links([fabric, cutting])

    def test_unmapped_source_from_other_bom_is_rejected(self):
        fabric_section = BomSection(pk=uuid4(), bom=Bom(pk=uuid4()), section_type="FABRIC", title="面料类", line_number=1)
        cutting_section = BomSection(pk=uuid4(), bom=Bom(pk=uuid4()), section_type="FABRIC", title="裁剪明细", line_number=2)
        fabric = BomLine(pk=uuid4(), section=fabric_section, line_number=1, unit="米", raw_values={})
        cutting = BomLine(pk=uuid4(), section=cutting_section, line_number=1, fabric_source_line=fabric)
        with self.assertRaisesMessage(ValidationError, "本 BOM"):
            validate_fabric_links([fabric, cutting])

    def test_integer_uuid_input_returns_validation_error_instead_of_server_error(self):
        sections = fixtures.fixtures.BomApiTests.fixed_sections([
            {"section_type": "PROFILE", "title": "管材类", "lines": [
                {"id": 1, "part_name": "管材一"}, {"id": 1, "part_name": "管材二"},
            ]},
        ])
        serializer = BomUpdateInputSerializer(data={"sections": sections})
        self.assertFalse(serializer.is_valid())
        self.assertIn("用料明细不能重复", str(serializer.errors))

    def test_local_keys_are_parsed_without_becoming_response_fields(self):
        client_key, source_key = uuid4(), uuid4()
        serializer = BomLineWriteSerializer(data={
            "part_name": "裁片", "client_key": str(client_key),
            "fabric_source_client_key": str(source_key),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data.get("client_key"), client_key)
        self.assertEqual(serializer.validated_data.get("fabric_source_client_key"), source_key)
        self.assertNotIn("client_key", serializer.data)
        self.assertNotIn("fabric_source_client_key", serializer.data)

    def test_saved_id_and_local_source_key_cannot_both_be_selected(self):
        serializer = BomLineWriteSerializer(data={
            "part_name": "裁片", "fabric_source_line_id": str(uuid4()),
            "fabric_source_client_key": str(uuid4()),
        })
        self.assertFalse(serializer.is_valid())

    def test_local_keys_reject_malformed_values_and_accept_null(self):
        for field in ("client_key", "fabric_source_client_key"):
            with self.subTest(field=field):
                invalid = BomLineWriteSerializer(data={"part_name": "裁片", field: "not-a-uuid"})
                self.assertFalse(invalid.is_valid())
                empty = BomLineWriteSerializer(data={"part_name": "裁片", field: None})
                self.assertTrue(empty.is_valid(), empty.errors)


class UnsavedFabricLinkApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)
        category = ProductCategory.objects.create(item_type="SEMI_FINISHED", category_name="未保存面料测试裁片")
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "UNSAVED_SET"})
        self.cutting_source = RawMaterialInformation.objects.create(
            material_number="UNSAVED_CUTTING", material_name="未保存面料测试裁片", item_type="SEMI_FINISHED",
            category=category, unit=unit, specification="100 × 100", material="测试面料",
        )

    def payload(self):
        key = str(uuid4())
        return [
            {"section_type": "FABRIC", "title": "面料类", "lines": [{
                "part_name": "新面料", "client_key": key,
                "source_inventory_material_id": str(self.fabric.pk), "unit_consumption": "2.5",
            }]},
            {"section_type": "FABRIC", "title": "裁剪明细", "lines": [{
                "part_name": "新裁片", "source_cutting_material_id": str(self.cutting_source.pk),
                "fabric_source_client_key": key, "cutting_pieces_per_set": 2,
                "cutting_sets_per_product": 1,
            }]},
        ]

    def unmapped_fabric_payload(self):
        material = FabricMaterial.objects.create(material_name="草稿测试PVC")
        specification = FabricSpecification.objects.create(specification_name="草稿测试400*300D")
        payload = self.payload()
        fabric = payload[0]["lines"][0]
        fabric.pop("source_inventory_material_id")
        fabric.update(
            source_fabric_material_id=str(material.pk),
            source_fabric_specification_id=str(specification.pk),
        )
        return payload, material, specification

    def snapshot(self):
        return (
            self.bom.__class__.objects.filter(pk=self.bom.pk).values().get(),
            list(BomSection.objects.filter(bom=self.bom).order_by("pk").values()),
            list(BomLine.objects.filter(section__bom=self.bom).order_by("pk").values()),
        )

    def assert_rejected_without_changes(self, payload):
        before = self.snapshot()
        response = self.save(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)
        return response

    def test_new_fabric_and_cutting_link_are_saved_together(self):
        payload = self.payload()
        response = self.save(list(reversed(payload)))
        self.assertEqual(response.status_code, 200, response.data)
        fabric = BomLine.objects.get(section__bom=self.bom, section__title="面料类")
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)
        self.assertEqual((cutting.cutting_pieces_per_set, cutting.cutting_sets_per_product), (2, 1))
        self.assertIsNone(cutting.fabric_meters_per_piece)
        self.assertIsNone(cutting.fabric_meters_per_set)
        self.assertEqual(cutting.total_consumption, "")
        for section in response.data["data"]["sections"]:
            for row in section["lines"]:
                self.assertNotIn("client_key", row)
                self.assertNotIn("fabric_source_client_key", row)
                self.assertNotIn("client_key", row["raw_values"])
                self.assertNotIn("fabric_source_client_key", row["raw_values"])
        saved = self.get().data["data"]["sections"]
        self.assertEqual(self.save(saved).status_code, 200)
        cutting.refresh_from_db()
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)

    def test_service_links_new_fabric_when_cutting_is_saved_first(self):
        current = self.get()
        sections = api_fixtures.BomApiTests.fixed_sections(self.payload())
        ids = {section["title"]: section["id"] for section in current.data["data"]["sections"]}
        for section in sections:
            if section["title"] in ids:
                section["id"] = ids[section["title"]]
        serializer = BomUpdateInputSerializer(data={"sections": sections}, context={"bom": self.bom})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        request = RequestFactory().patch("/", HTTP_IF_MATCH=current["ETag"])
        request.user = self.user
        update_bom_lines(bom=self.bom, sections=list(reversed(serializer.validated_data["sections"])),
                         actor_employee=self.employee, request=request)
        fabric = BomLine.objects.get(section__bom=self.bom, section__title="面料类")
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)

    def test_existing_cutting_can_switch_to_new_fabric_in_one_save(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"]["sections"]
        fabric_section = next(section for section in payload if section["title"] == "面料类")
        cutting = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
        new_fabric = self.payload()[0]["lines"][0]
        fabric_section["lines"] = [new_fabric]
        cutting.update(fabric_source_line_id=None, fabric_source_client_key=new_fabric["client_key"])
        result = self.save(payload)
        self.assertEqual(result.status_code, 200, result.data)
        stored_cutting = BomLine.objects.get(pk=cutting["id"])
        self.assertEqual(stored_cutting.fabric_source_line_id,
                         BomLine.objects.get(section__bom=self.bom, section__title="面料类").pk)

    def test_duplicate_local_keys_are_rejected_without_partial_save(self):
        payload = self.payload()
        payload[0]["lines"].append(deepcopy(payload[0]["lines"][0]))
        self.assert_rejected_without_changes(payload)

    def test_missing_source_key_is_rejected_without_partial_save(self):
        payload = self.payload()
        payload[1]["lines"][0]["fabric_source_client_key"] = str(uuid4())
        self.assert_rejected_without_changes(payload)

    def test_source_key_cannot_target_self_or_non_fabric_row(self):
        payload = self.payload()
        cutting = payload[1]["lines"][0]
        cutting["client_key"] = str(uuid4())
        cutting["fabric_source_client_key"] = cutting["client_key"]
        self.assert_rejected_without_changes(payload)
        key = str(uuid4())
        payload[1]["lines"][0]["fabric_source_client_key"] = key
        payload.append({"section_type": "PROFILE", "title": "管材类", "lines": [{
            "part_name": "管材", "client_key": key, "source_inventory_material_id": str(self.pipe.pk),
        }]})
        self.assert_rejected_without_changes(payload)

    def test_unmapped_reference_fabric_and_cutting_can_save_together_as_draft(self):
        payload, material, specification = self.unmapped_fabric_payload()
        self.cutting_source.material = "/"
        self.cutting_source.save(update_fields=["material"])
        response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.data)
        fabric = BomLine.objects.get(section__bom=self.bom, section__title="面料类")
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual((fabric.material, fabric.specification, fabric.unit),
                         (material.material_name, specification.specification_name, "米"))
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)
        self.assertEqual(cutting.material, material.material_name)
        self.assertNotIn("cutting_material_original", cutting.raw_values)
        self.assertFalse(fabric.raw_values.get("source_inventory_material_id"))
        saved = self.get().data["data"]["sections"]
        self.assertEqual(self.save(saved).status_code, 200)
        cutting.refresh_from_db()
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)
        self.assertEqual(cutting.material, material.material_name)
        material.refresh_from_db()
        self.assertIsNone(material.inventory_raw_material_id)
        self.cutting_source.refresh_from_db()
        self.assertEqual(self.cutting_source.material, "/")

    def test_existing_unmapped_reference_fabric_overrides_cutting_own_and_manual_material(self):
        payload, _, _ = self.unmapped_fabric_payload()
        response = self.save(payload[:1])
        self.assertEqual(response.status_code, 200, response.data)
        fabric = BomLine.objects.get(section__bom=self.bom, section__title="面料类")
        saved = response.data["data"]["sections"]
        cutting_input = payload[1]["lines"][0]
        cutting_input.pop("fabric_source_client_key")
        cutting_input["fabric_source_line_id"] = str(fabric.pk)
        next(section for section in saved if section["title"] == "裁剪明细")["lines"] = [cutting_input]
        response = self.save(saved)
        self.assertEqual(response.status_code, 200, response.data)
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual((cutting.fabric_source_line_id, cutting.material), (fabric.pk, fabric.material))
        saved = response.data["data"]["sections"]
        next(section for section in saved if section["title"] == "裁剪明细")["lines"][0]["material"] = "手填材质"
        response = self.save(saved)
        self.assertEqual(response.status_code, 200, response.data)
        cutting.refresh_from_db()
        self.assertEqual((cutting.fabric_source_line_id, cutting.material), (fabric.pk, fabric.material))

    def test_unmapped_reference_fabric_still_cannot_confirm_bom(self):
        payload, _, _ = self.unmapped_fabric_payload()
        response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.data)
        response = fixtures.MaterialFlowBomTests.verify(self)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("原料", str(response.data))
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.status, BomStatus.PENDING_CONFIRMATION)
        self.assertIsNone(self.bom.confirmed_at)

    def test_invalid_reference_inventory_mapping_is_rejected_without_partial_save(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        payload, reference, _ = self.unmapped_fabric_payload()
        wrong_category = self.material("DRAFT_WRONG_CATEGORY", "管材", self.meter_unit)
        wrong_unit = self.material("DRAFT_WRONG_UNIT", "面料", self.root_unit)
        archived = self.material("DRAFT_ARCHIVED_FABRIC", "面料", self.meter_unit)
        archived.archived_at = timezone.now()
        archived.save(update_fields=["archived_at"])
        for invalid_source in (wrong_category, wrong_unit, archived):
            with self.subTest(source=invalid_source.material_number):
                reference.inventory_raw_material = invalid_source
                reference.save(update_fields=["inventory_raw_material"])
                self.assert_rejected_without_changes(payload)

    def test_partial_reference_inventory_mapping_can_save_but_cannot_confirm_bom(self):
        payload, reference, _ = self.unmapped_fabric_payload()
        reference.inventory_raw_material = self.fabric
        reference.save(update_fields=["inventory_raw_material"])
        response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.data)
        fabric = BomLine.objects.get(section__bom=self.bom, section__title="面料类")
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)
        response = fixtures.MaterialFlowBomTests.verify(self)
        self.assertEqual(response.status_code, 400, response.data)
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.status, BomStatus.PENDING_CONFIRMATION)
        self.assertIsNone(self.bom.confirmed_at)

    def test_source_key_cannot_target_another_cutting_row(self):
        payload = self.payload()
        source_cutting = payload[1]["lines"][0]
        source_cutting["client_key"] = str(uuid4())
        another_cutting = deepcopy(source_cutting)
        another_cutting["client_key"] = str(uuid4())
        another_cutting["part_name"] = "第二块裁片"
        another_cutting["fabric_source_client_key"] = source_cutting["client_key"]
        payload[1]["lines"].append(another_cutting)
        self.assert_rejected_without_changes(payload)

    def test_saved_source_omitted_or_null_remains_compatible(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"]["sections"]
        cutting = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
        source_id = UUID(cutting.pop("fabric_source_line_id"))
        cutting["fabric_source_client_key"] = None
        self.assertEqual(self.save(payload).status_code, 200)
        stored = BomLine.objects.get(pk=cutting["id"])
        self.assertEqual(stored.fabric_source_line_id, source_id)
        cutting["fabric_source_line_id"] = None
        self.assertEqual(self.save(payload).status_code, 200)
        stored.refresh_from_db()
        self.assertIsNone(stored.fabric_source_line_id)

    def test_deleted_and_foreign_saved_sources_are_rejected(self):
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"]["sections"]
        removed = deepcopy(payload)
        next(section for section in removed if section["title"] == "面料类")["lines"] = []
        self.assert_rejected_without_changes(removed)
        other = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                           actor_employee=self.employee)
        foreign = BomLine.objects.get(section__bom=other, section__title="面料类")
        next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]["fabric_source_line_id"] = str(foreign.pk)
        self.assert_rejected_without_changes(payload)

    def test_local_keys_do_not_bypass_stale_etag_or_permission_checks(self):
        stale = self.get()["ETag"]
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        before = self.snapshot()
        result = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": response.data["data"]["sections"]},
                                   format="json", HTTP_IF_MATCH=stale)
        self.assertEqual(result.status_code, 412, result.data)
        self.assertEqual(self.snapshot(), before)
        self.user.user_permissions.clear()
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        result = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": response.data["data"]["sections"]},
                                   format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(result.status_code, 403, result.data)
        self.assertEqual(self.snapshot(), before)

    def test_missing_cutting_material_uses_fabric_without_changing_source_record(self):
        for missing_material in ("", "/"):
            with self.subTest(material=missing_material):
                self.cutting_source.material = missing_material
                self.cutting_source.save(update_fields=["material"])
                result = self.save(self.payload())
                self.assertEqual(result.status_code, 200, result.data)
                cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
                self.assertEqual(cutting.material, "测试材质")
                row = next(section for section in self.get().data["data"]["sections"]
                           if section["title"] == "裁剪明细")["lines"][0]
                self.assertEqual(row["material"], "测试材质")
                self.assertEqual(row["cutting_material_original"], "测试材质")
                self.cutting_source.refresh_from_db()
                self.assertEqual(self.cutting_source.material, missing_material)

    def test_inherited_material_follows_source_changes_after_reload_and_omitted_input(self):
        self.cutting_source.material = "/"
        self.cutting_source.save(update_fields=["material"])
        response = self.save(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        another = self.material("UNSAVED_FABRIC_OTHER", "面料", self.meter_unit)
        another.material = "第二种面料材质"
        another.save(update_fields=["material"])
        for omit_material in (False, True):
            payload = self.get().data["data"]["sections"]
            new_fabric = self.payload()[0]["lines"][0]
            new_fabric["source_inventory_material_id"] = str(another.pk if not omit_material else self.fabric.pk)
            next(section for section in payload if section["title"] == "面料类")["lines"] = [new_fabric]
            cutting = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
            cutting.update(fabric_source_line_id=None, fabric_source_client_key=new_fabric["client_key"])
            if omit_material:
                cutting.pop("material")
            result = self.save(payload)
            self.assertEqual(result.status_code, 200, result.data)
            row = next(section for section in result.data["data"]["sections"]
                       if section["title"] == "裁剪明细")["lines"][0]
            self.assertEqual(row["material"], "测试材质" if omit_material else "第二种面料材质")
            self.assertEqual(row["cutting_material_original"], row["material"])

    def test_source_fabric_overrides_own_cutting_material_and_manual_input(self):
        result = self.save(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        row = next(section for section in result.data["data"]["sections"]
                   if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual(row["material"], "测试材质")
        self.cutting_source.material = "/"
        self.cutting_source.save(update_fields=["material"])
        result = self.save(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        payload = result.data["data"]["sections"]
        row = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
        row["material"] = "用户填写材质"
        result = self.save(payload)
        self.assertEqual(result.status_code, 200, result.data)
        row = next(section for section in result.data["data"]["sections"]
                   if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual((row["material"], row["cutting_material_original"]), ("测试材质", "测试材质"))

    def test_clearing_fabric_source_clears_inherited_material(self):
        self.cutting_source.material = "/"
        self.cutting_source.save(update_fields=["material"])
        result = self.save(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        payload = result.data["data"]["sections"]
        row = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
        row["fabric_source_line_id"] = None
        result = self.save(payload)
        self.assertEqual(result.status_code, 200, result.data)
        row = next(section for section in result.data["data"]["sections"]
                   if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual((row["material"], row["cutting_material_original"]), ("", ""))

    def test_explicit_material_cannot_survive_cleared_source(self):
        self.cutting_source.material = "/"
        self.cutting_source.save(update_fields=["material"])
        result = self.save(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        payload = result.data["data"]["sections"]
        row = next(section for section in payload if section["title"] == "裁剪明细")["lines"][0]
        row.pop("cutting_material_original", None)
        row["material"] = "测试材质"
        row["fabric_source_line_id"] = None
        result = self.save(payload)
        self.assertEqual(result.status_code, 200, result.data)
        row = next(section for section in result.data["data"]["sections"]
                   if section["title"] == "裁剪明细")["lines"][0]
        self.assertEqual((row["material"], row["cutting_material_original"]), ("", ""))
