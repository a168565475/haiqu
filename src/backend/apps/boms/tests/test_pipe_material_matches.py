from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit
from ..api.serializers import BomPipeMaterialMatchQuerySerializer
from ..models import BomLine
from ..material_flow_bom import apply_line_quantities
from ..services import _editable_model_values
from .. import selectors
from . import test_material_flow_bom as flow_fixtures


class PipeMaterialValidationTests(SimpleTestCase):
    def test_missing_pipe_source_names_missing_link_without_claiming_unit_missing(self):
        line = SimpleNamespace(
            section=SimpleNamespace(title="管材类", section_type="PROFILE"),
            line_number=5, length_value="500", unit_consumption="2", unit="根",
            raw_values={"tube_cut_piece_count": "6"},
            cutting_pieces_per_set=None, fabric_meters_per_piece=None,
            cutting_sets_per_product=None,
        )
        with patch("apps.boms.material_flow_bom.resolve_bom_line_raw_material", return_value=(None, None)):
            with self.assertRaises(ValidationError) as caught:
                apply_line_quantities(line, 1000, require_complete=True)
        message = str(caught.exception.detail)
        self.assertIn("管材类第 5 行", message)
        self.assertIn("对应原料", message)
        self.assertNotIn("补齐单位", message)


class PipeMaterialMatchRuleTests(SimpleTestCase):
    def material(self, **changes):
        return SimpleNamespace(
            **{"pk": "pipe-1", "material": "铁-硬管", "diameter": "25*15",
               "thickness": "1.5", "length": "3050", "specification": "25*15*1.5*3050", **changes}
        )

    def match(self, materials, **changes):
        self.assertTrue(hasattr(selectors, "match_pipe_material_candidates"), "缺少管材精确匹配规则")
        return selectors.match_pipe_material_candidates(
            materials,
            **{"material": "铁-硬管", "diameter": "25 × 15", "thickness": "1.50",
               "tube_shape": "椭圆管", "raw_bar_length_m": "3.05", **changes},
        )

    def test_same_section_other_thickness_does_not_match(self):
        result = self.match([self.material(thickness="0.8")])
        self.assertEqual(result["reason"], "no_match")
        self.assertEqual(result["candidates"], [])

    def test_shape_unknown_requires_manual_choice_even_for_one_candidate(self):
        source = self.material()
        result = self.match([source])
        self.assertEqual(result["candidates"], [source])
        self.assertEqual(result["reason"], "needs_review")
        self.assertIsNone(result["automatic_source_id"])

    def test_explicit_round_shape_and_matching_length_allow_unique_link(self):
        source = self.material(diameter="25", specification="Φ25*1.5*3050")
        result = self.match([source], diameter="25.0", tube_shape="圆管")
        self.assertEqual(result["reason"], "unique")
        self.assertEqual(result["automatic_source_id"], source.pk)

    def test_unknown_or_mismatching_length_cannot_auto_link(self):
        for changes in ({"length": ""}, {"length": "3060"}, {"length": "3.05"}):
            result = self.match([self.material(diameter="25", specification="Φ25*1.5", **changes)],
                                diameter="25", tube_shape="圆管")
            self.assertEqual(result["reason"], "needs_review")

    def test_multiple_candidates_are_not_silently_reduced_to_first(self):
        result = self.match([self.material(), self.material(pk="pipe-2", length="4000")])
        self.assertEqual(result["reason"], "multiple")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertIsNone(result["automatic_source_id"])

    def test_numeric_specification_is_fallback_for_new_archive_without_legacy_fields(self):
        source = self.material(diameter="", thickness="", length="", specification="Φ25*1.5*3050")
        result = self.match([source], diameter="25", tube_shape="圆管")
        self.assertEqual(result["automatic_source_id"], source.pk)
        unknown = self.material(diameter="", thickness="", length="", specification="25型管1.5")
        self.assertEqual(self.match([unknown])["reason"], "no_match")

    def test_missing_parameter_does_not_return_all_materials(self):
        self.assertEqual(self.match([self.material()], material="")["reason"], "incomplete")

    def test_phi_prefix_on_two_dimensions_is_not_round_shape_evidence(self):
        result = self.match([self.material(specification="Φ25*15*1.5*3050")], tube_shape="圆管")
        self.assertEqual(result["reason"], "needs_review")

    def test_conflicting_specification_and_dimension_fields_do_not_auto_link(self):
        result = self.match([self.material(diameter="25", specification="Φ30*1.5*3050")],
                            diameter="25", tube_shape="圆管")
        self.assertEqual(result["reason"], "needs_review")

    def test_explicit_shape_conflict_is_not_a_manual_candidate(self):
        source = self.material(diameter="25", specification="Φ25*1.5*3050")
        result = self.match([source], diameter="25", tube_shape="方管")
        self.assertEqual(result["reason"], "no_match")
        self.assertEqual(result["candidates"], [])


class PipeMaterialMatchInputTests(SimpleTestCase):
    def test_query_rejects_invalid_dimensions_and_lengths(self):
        for key, value in (("diameter", "25*15*1.5"), ("diameter", "NaN"), ("thickness", "0"),
                           ("thickness", "1.5*2"), ("raw_bar_length_m", "-1"),
                           ("raw_bar_length_m", "NaN"), ("material", "x" * 201)):
            with self.subTest(key=key, value=value):
                serializer = BomPipeMaterialMatchQuerySerializer(data={key: value})
                self.assertFalse(serializer.is_valid())
                self.assertIn(key, serializer.errors)

    def test_partial_or_blank_query_is_valid_and_normalized(self):
        serializer = BomPipeMaterialMatchQuerySerializer(data={"material": " 铁-硬管 ", "diameter": ""})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["material"], "铁-硬管")


class PipeMaterialSpecificationTests(SimpleTestCase):
    def payload(self, **changes):
        return {"source_inventory_material_id": "new-pipe", "tube_shape": "圆管",
                "tube_diameter": "25", "tube_thickness": "0.8", "length_value": "500",
                "unit_consumption": "2", "tube_cut_piece_count": "6", **changes}

    def test_new_link_rebuilds_stale_specification_from_current_tube_attributes(self):
        values, _ = _editable_model_values(self.payload(specification="Φ25 × 1.5 mm"), "PROFILE", 1000)
        self.assertEqual(values["specification"], "Φ25 × 0.8 mm")

    def test_new_link_uses_bom_section_specification_not_archive_bar_length(self):
        values, _ = _editable_model_values(self.payload(specification="Φ25*0.8*3050"), "PROFILE", 1000)
        self.assertEqual(values["specification"], "Φ25 × 0.8 mm")

    def test_same_source_and_legacy_source_only_preserve_snapshot(self):
        source = SimpleNamespace(raw_values={"source_inventory_material_id": "new-pipe"})
        values, _ = _editable_model_values(self.payload(specification="旧版已确认规格"), "PROFILE", 1000,
                                           existing_line=source)
        self.assertEqual(values["specification"], "旧版已确认规格")
        values, _ = _editable_model_values({"source_inventory_material_id": "new-pipe", "specification": "档案完整规格"},
                                           "PROFILE", 1000)
        self.assertEqual(values["specification"], "档案完整规格")


class PipeMaterialMatchApiTests(TestCase):
    setUpFixture = flow_fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = flow_fixtures.MaterialFlowBomTests.tearDown
    material = flow_fixtures.MaterialFlowBomTests.material
    get = flow_fixtures.MaterialFlowBomTests.get
    save = flow_fixtures.MaterialFlowBomTests.save
    verify = flow_fixtures.MaterialFlowBomTests.verify
    endpoint = "/api/v1/boms/pipe-material-matches/"

    def setUp(self):
        flow_fixtures.MaterialFlowBomTests.setUp(self)
        self.pipe.material = "PIPE_MATCH_TEST铁-硬管"
        self.pipe.diameter = "25"
        self.pipe.thickness = "1.5"
        self.pipe.length = "3050"
        self.pipe.specification = "Φ25*1.5*3050"
        self.pipe.save()
        self.query = {"material": self.pipe.material, "diameter": "25", "thickness": "1.5",
                      "tube_shape": "圆管", "raw_bar_length_m": "3.05"}

    def pipe_payload(self, **changes):
        return {"part_name": "后座管", "material": self.pipe.material,
                "source_inventory_material_id": str(self.pipe.pk), "tube_shape": "圆管",
                "tube_diameter": "25", "tube_thickness": "1.5", "specification": "Φ25 × 1.5 mm",
                "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6", **changes}

    def save_pipe(self, payload):
        return self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [payload]}])

    def test_unique_query_returns_stable_source_and_does_not_write(self):
        before = (RawMaterialInformation.objects.count(), BomLine.objects.count())
        response = self.client.get(self.endpoint, self.query)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["reason"], "unique")
        self.assertEqual(data["automatic_source_id"], str(self.pipe.pk))
        candidate = data["candidates"][0]
        self.assertEqual((candidate["diameter"], candidate["thickness"], candidate["length"]), ("25", "1.5", "3050"))
        self.assertEqual((RawMaterialInformation.objects.count(), BomLine.objects.count()), before)

    def test_different_length_stays_manual_candidate_and_different_thickness_is_excluded(self):
        response = self.client.get(self.endpoint, {**self.query, "raw_bar_length_m": "4"})
        self.assertEqual(response.data["data"]["reason"], "needs_review")
        self.assertEqual(len(response.data["data"]["candidates"]), 1)
        response = self.client.get(self.endpoint, {**self.query, "thickness": "0.8"})
        self.assertEqual(response.data["data"]["reason"], "no_match")

    def test_candidates_require_active_material_category_and_root_unit(self):
        unit = ProductionUnit.objects.create(unit_code="PIPE_MATCH_UNIT", unit_name="PIPE_MATCH_OTHER")
        cases = [
            (self.pipe, "archived_at", timezone.now()),
            (self.pipe, "item_type", "SEMI_FINISHED"),
            (self.pipe, "unit", unit),
            (self.pipe.category, "status", "INACTIVE"),
            (self.pipe.category, "archived_at", timezone.now()),
            (self.pipe.unit, "status", "INACTIVE"),
            (self.pipe.unit, "archived_at", timezone.now()),
        ]
        for instance, field, value in cases:
            with self.subTest(model=instance.__class__.__name__, field=field):
                previous = getattr(instance, field)
                setattr(instance, field, value)
                instance.save()
                response = self.client.get(self.endpoint, self.query)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["data"]["candidates"], [])
                setattr(instance, field, previous)
                instance.save()

    def test_invalid_query_and_permission_are_enforced(self):
        self.assertEqual(self.client.get(self.endpoint, {**self.query, "thickness": "NaN"}).status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.endpoint, self.query).status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.endpoint, self.query).status_code, 401)

    def test_link_save_keeps_component_parameters_and_can_confirm(self):
        response = self.save_pipe(self.pipe_payload())
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual((line.part_name, line.material, line.specification, line.length_value,
                          line.unit_consumption, line.unit),
                         ("后座管", self.pipe.material, "Φ25 × 1.5 mm", "500", "2", "根"))
        self.assertEqual(line.raw_values["source_inventory_material_id"], str(self.pipe.pk))
        self.assertEqual(line.raw_values["tube_cut_piece_count"], "6")
        self.assertEqual(self.verify().status_code, 200)

    def test_unmatched_draft_saves_and_confirmation_explains_missing_link(self):
        response = self.save_pipe(self.pipe_payload(source_inventory_material_id=None))
        self.assertEqual(response.status_code, 200, response.data)
        response = self.verify()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("对应原料", str(response.data))
        self.assertNotIn("补齐单位", str(response.data))

    def test_changed_thickness_before_link_rebuilds_the_old_saved_specification(self):
        initial = self.save_pipe(self.pipe_payload(source_inventory_material_id=None))
        self.assertEqual(initial.status_code, 200, initial.data)
        self.pipe.thickness = "0.8"
        self.pipe.specification = "Φ25*0.8*3050"
        self.pipe.save()
        sections = self.get().data["data"]["sections"]
        for section in sections:
            if section["title"] == "管材类":
                section["lines"][0].update(tube_thickness="0.8", source_inventory_material_id=str(self.pipe.pk))
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(line.specification, "Φ25 × 0.8 mm")
        self.assertEqual(line.raw_values["tube_thickness"], "0.8")
        self.assertEqual(line.part_name, "后座管")

    def test_new_pipe_without_display_specification_uses_current_tube_parameters(self):
        response = self.save_pipe(self.pipe_payload(specification=""))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).specification, "Φ25 × 1.5 mm")

    def test_mismatch_rejected_atomically_instead_of_overwriting_entered_values(self):
        for field, value in (("material", "不锈钢"), ("tube_diameter", "30"), ("tube_thickness", "0.8"), ("tube_shape", "方管")):
            with self.subTest(field=field):
                response = self.save_pipe(self.pipe_payload(**{field: value}))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("不会自动替换", str(response.data))
                self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_legacy_source_only_payload_remains_valid(self):
        response = self.save_pipe(flow_fixtures.MaterialFlowBomTests.pipe_payload(self))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).material, self.pipe.material)

    def test_stale_etag_and_existing_stable_id_protection_remain(self):
        stale = self.get()["ETag"]
        self.assertEqual(self.save_pipe(self.pipe_payload()).status_code, 200)
        current = self.get().data["data"]["sections"]
        response = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": current},
                                     format="json", HTTP_IF_MATCH=stale)
        self.assertEqual(response.status_code, 412, response.data)
        for section in current:
            if section["title"] == "管材类":
                section["lines"][0]["source_inventory_material_id"] = None
        response = self.save(current)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不能清空稳定原料 ID", str(response.data))


