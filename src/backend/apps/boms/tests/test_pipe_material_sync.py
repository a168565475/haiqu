from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from django.contrib.auth.models import Permission
from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.products.models import RawMaterialInformation
from ..api.serializers import BomLineSerializer
from ..pipe_material_sync import pipe_parameter_values
from ..models import BomLine
from ..services import _editable_model_values, create_bom
from . import test_material_flow_bom as flow_fixtures
from . import test_bom_api as bom_fixtures


class PipeMaterialAutomaticSnapshotTests(SimpleTestCase):
    def test_legacy_parameters_are_available_only_until_explicitly_replaced(self):
        self.assertEqual(pipe_parameter_values({"E": "Φ", "F": "25", "G": "1.5"}),
                         {"tube_shape": "圆管", "tube_diameter": "25", "tube_thickness": "1.5"})
        self.assertEqual(pipe_parameter_values({"E": "圆管", "F": "25", "G": "1.5",
                                                "tube_shape": "", "tube_diameter": "", "tube_thickness": ""}),
                         {"tube_shape": "", "tube_diameter": "", "tube_thickness": ""})
    def test_cleared_parameters_do_not_reappear_from_import_columns(self):
        line = SimpleNamespace(section=SimpleNamespace(section_type="PROFILE"),
                               raw_values={"E": "圆管", "F": "25", "G": "1.5",
                                           "tube_shape": "", "tube_diameter": "", "tube_thickness": ""})
        serializer = BomLineSerializer()
        self.assertEqual((serializer.get_tube_shape(line), serializer.get_tube_diameter(line),
                          serializer.get_tube_thickness(line)), ("", "", ""))

    def test_current_dimensions_replace_stale_specification_even_when_source_id_is_unchanged(self):
        source = SimpleNamespace(raw_values={"source_inventory_material_id": "old-pipe"})
        values, _ = _editable_model_values({
            "source_inventory_material_id": "old-pipe", "specification": "旧规格",
            "tube_shape": "圆管", "tube_diameter": "25", "tube_thickness": "0.8",
            "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6",
        }, "PROFILE", 1000, existing_line=source)
        self.assertEqual(values["specification"], "Φ25 × 0.8 mm")


class PipeMaterialSyncApiTests(TestCase):
    setUpFixture = flow_fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = flow_fixtures.MaterialFlowBomTests.tearDown
    material = flow_fixtures.MaterialFlowBomTests.material
    get = flow_fixtures.MaterialFlowBomTests.get
    save = flow_fixtures.MaterialFlowBomTests.save
    verify = flow_fixtures.MaterialFlowBomTests.verify

    def setUp(self):
        flow_fixtures.MaterialFlowBomTests.setUp(self)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="products", codename="add_rawmaterialinformation",
        ))
        self.pipe.material = "PIPE_AUTO_SYNC测试铁"
        self.pipe.diameter = "25*15"
        self.pipe.thickness = "1.5"
        self.pipe.length = "3050"
        self.pipe.specification = "25*15*1.5*3050"
        self.pipe.warehouse_number = "CK003"
        self.pipe.warehouse_name = "原料管材仓"
        self.pipe.save()

    def payload(self, **changes):
        return {
            "part_name": "前支撑管", "material": self.pipe.material,
            "tube_shape": "圆管", "tube_diameter": "25*15", "tube_thickness": "1.5",
            "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6",
            "tube_coating_color": "黑色磨砂", "purchase_unit_weight_kg": "0.2", **changes,
        }

    def save_pipe(self, *lines):
        return self.save([{"section_type": "PROFILE", "title": "管材类", "lines": list(lines)}])

    def line(self):
        return BomLine.objects.get(section__bom=self.bom, section__section_type="PROFILE")

    def source(self, line=None):
        return RawMaterialInformation.objects.get(pk=(line or self.line()).raw_values["source_inventory_material_id"])

    def test_complete_unmatched_pipe_is_created_and_linked_in_same_save(self):
        response = self.save_pipe(self.payload(tube_thickness="0.8"))
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertTrue(line.raw_values.get("source_inventory_material_id"))
        source = self.source()
        self.assertEqual((source.material, source.diameter, source.thickness, source.length),
                         (self.pipe.material, "25*15", "0.8", "3050"))
        self.assertEqual((source.unit.unit_name, source.category.category_name, source.warehouse_number),
                         ("根", "管材", "CK003"))
        self.assertEqual((line.material, line.specification, line.part_name, line.length_value),
                         (self.pipe.material, "Φ25*15 × 0.8 mm", "前支撑管", "500"))
        self.assertEqual(line.raw_values["tube_coating_color"], "黑色磨砂")
        self.assertIsNone(source.color_id)
        self.assertEqual(source.color_snapshot, "")
        self.assertTrue(AuditLog.objects.filter(object_type="RAW_MATERIAL_INFORMATION", object_id=source.pk,
                                                action="CREATED", context_id=self.bom.pk).exists())

    def test_existing_unknown_shape_full_dimensions_are_reused_without_create_permission(self):
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="products", codename="add_rawmaterialinformation",
        ))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        before = RawMaterialInformation.objects.count()
        response = self.save_pipe(self.payload(tube_diameter="25 × 15", tube_thickness="1.50"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.pipe.pk)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_same_batch_repeated_save_and_another_bom_reuse_one_archive(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_pipe(self.payload(tube_thickness="0.8"),
                                  self.payload(tube_thickness="0.80", part_name="后座管"))
        self.assertEqual(response.status_code, 200, response.data)
        ids = {line.raw_values["source_inventory_material_id"] for line in BomLine.objects.filter(section__bom=self.bom)}
        self.assertEqual(len(ids), 1)
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)
        response = self.save(self.get().data["data"]["sections"])
        self.assertEqual(response.status_code, 200, response.data)
        self.bom = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                              actor_employee=self.employee)
        response = self.save_pipe(self.payload(tube_thickness="0.8"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().raw_values["source_inventory_material_id"], next(iter(ids)))
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)

    def test_changed_linked_parameters_relink_without_modifying_shared_archive(self):
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        before = RawMaterialInformation.objects.filter(pk=self.pipe.pk).values().get()
        sections = self.get().data["data"]["sections"]
        sections[0]["lines"][0].update(material="PIPE_AUTO_SYNC新材质", tube_thickness="0.8", length_value="600")
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        source = self.source()
        self.assertNotEqual(source.pk, self.pipe.pk)
        self.assertEqual((source.material, source.thickness, source.length), ("PIPE_AUTO_SYNC新材质", "0.8", "3650"))
        self.assertEqual((self.line().material, self.line().specification), ("PIPE_AUTO_SYNC新材质", "Φ25*15 × 0.8 mm"))
        self.assertEqual(RawMaterialInformation.objects.filter(pk=self.pipe.pk).values().get(), before)

    def test_existing_matching_source_preferred_over_equivalent_lower_code(self):
        other = deepcopy(self.pipe)
        other.pk = None
        other.material_number = "AAA-PIPE-AUTO-EQUIVALENT"
        other.save()
        response = self.save_pipe(self.payload(source_inventory_material_id=str(self.pipe.pk)))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.pipe.pk)
        response = self.save_pipe(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, other.pk)

    def test_length_shape_and_archived_sources_are_not_reused(self):
        for changes in ({"length_value": "600"}, {"tube_shape": "方管"}):
            self.pipe.specification = "圆管 25*15*1.5*3050"
            self.pipe.source_unique_check = ""
            # 单维圆管提供明确形状证据，双维历史规格仍按既有兼容规则处理。
            self.pipe.diameter = "25"
            self.pipe.specification = "Φ25*1.5*3050"
            self.pipe.save()
            response = self.save_pipe(self.payload(tube_diameter="25", **changes))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertNotEqual(self.source().pk, self.pipe.pk)
        self.pipe.archived_at = timezone.now()
        self.pipe.save()
        response = self.save_pipe(self.payload(tube_diameter="25"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(self.source().pk, self.pipe.pk)

    def test_auto_archive_shape_marker_prevents_cross_shape_reuse(self):
        response = self.save_pipe(self.payload(tube_thickness="0.8"))
        self.assertEqual(response.status_code, 200, response.data)
        first = self.source()
        response = self.save_pipe(self.payload(tube_thickness="0.8", tube_shape="矩形管"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(self.source().pk, first.pk)

    def test_dictionary_shapes_outside_legacy_parser_are_reused_on_repeat_save(self):
        for shape in ("D形管", "方管-带凹槽"):
            with self.subTest(shape=shape):
                response = self.save_pipe(self.payload(tube_shape=shape, tube_thickness="0.8"))
                self.assertEqual(response.status_code, 200, response.data)
                source = self.source()
                before = RawMaterialInformation.objects.count()
                response = self.save(self.get().data["data"]["sections"])
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.source().pk, source.pk)
                self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_invalid_dimension_values_fail_instead_of_preserving_old_source(self):
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        for field, value in (("tube_diameter", "0"), ("tube_diameter", "NaN"),
                             ("tube_diameter", "1000000000000"), ("tube_thickness", "-1"),
                             ("tube_thickness", "1.5*2")):
            sections = self.get().data["data"]["sections"]
            sections[0]["lines"][0][field] = value
            response = self.save(sections)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(self.source().pk, self.pipe.pk)

    def test_partial_dimension_change_saves_draft_but_cannot_confirm(self):
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        sections = self.get().data["data"]["sections"]
        sections[0]["lines"][0].update(tube_thickness="0.8", tube_diameter="")
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.pipe.pk)
        response = self.verify()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("管材", str(response.data))

    def test_partial_payload_rebuilds_specification_from_preserved_dimensions(self):
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        line = self.line()
        response = self.save_pipe({"id": str(line.pk), "part_name": line.part_name,
                                   "source_inventory_material_id": str(self.pipe.pk), "tube_thickness": "0.8"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().thickness, "0.8")
        self.assertEqual(self.line().specification, "Φ25*15 × 0.8 mm")

    def test_clearing_all_legacy_import_dimensions_stays_empty_and_cannot_confirm(self):
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        line = self.line()
        line.raw_values = {key: value for key, value in line.raw_values.items()
                           if key not in {"tube_shape", "tube_diameter", "tube_thickness"}}
        line.raw_values.update(E="圆管", F="25*15", G="1.5")
        line.save()
        sections = self.get().data["data"]["sections"]
        sections[0]["lines"][0].update(tube_shape="", tube_diameter="", tube_thickness="")
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        saved = self.get().data["data"]["sections"][0]["lines"][0]
        self.assertEqual((saved["tube_shape"], saved["tube_diameter"], saved["tube_thickness"]), ("", "", ""))
        self.assertEqual(self.source().pk, self.pipe.pk)
        self.assertEqual(self.verify().status_code, 400)

    def test_create_name_limit_fails_without_silent_truncation(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_pipe(self.payload(tube_thickness="0.8", part_name="管" * 201))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_legacy_material_change_is_preserved_and_cannot_confirm_with_old_source(self):
        for empty_parameters in ({}, {"tube_shape": "", "tube_diameter": "", "tube_thickness": ""}):
            response = self.save_pipe({"part_name": "旧管材", "source_inventory_material_id": str(self.pipe.pk),
                                       "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6"})
            self.assertEqual(response.status_code, 200, response.data)
            line = self.line()
            payload = {"id": str(line.pk), "part_name": line.part_name,
                       "source_inventory_material_id": str(self.pipe.pk), "material": "PIPE_AUTO_SYNC另一材质",
                       "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6", **empty_parameters}
            response = self.save_pipe(payload)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(self.line().material, "PIPE_AUTO_SYNC另一材质")
            self.assertEqual(self.source().pk, self.pipe.pk)
            self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
            self.assertEqual(self.verify().status_code, 400)

    def test_incomplete_draft_does_not_create_and_legacy_link_is_preserved(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_pipe(self.payload(tube_cut_piece_count=""))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(self.line().raw_values.get("source_inventory_material_id"))
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        response = self.save_pipe({"part_name": "旧管材", "source_inventory_material_id": str(self.pipe.pk),
                                   "length_value": "500", "unit_consumption": "2", "tube_cut_piece_count": "6"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.pipe.pk)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_create_permission_is_enforced_and_bom_is_not_partially_saved(self):
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="products", codename="add_rawmaterialinformation",
        ))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        before = RawMaterialInformation.objects.count()
        response = self.save_pipe(self.payload(tube_thickness="0.8"))
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_later_invalid_line_rolls_back_created_material_and_audit(self):
        before = (RawMaterialInformation.objects.count(), AuditLog.objects.count())
        response = self.save_pipe(self.payload(tube_thickness="0.8"), self.payload(length_value="1.5"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual((RawMaterialInformation.objects.count(), AuditLog.objects.count()), before)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_stale_etag_does_not_create_raw_material(self):
        previous = self.get()
        self.assertEqual(self.save_pipe(self.payload()).status_code, 200)
        sections = previous.data["data"]["sections"]
        sections[0]["lines"] = [self.payload(tube_thickness="0.8")]
        before = RawMaterialInformation.objects.count()
        response = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": sections}, format="json",
                                     HTTP_IF_MATCH=previous["ETag"])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before)


class PipeMaterialSyncConcurrencyTests(TransactionTestCase):
    setUpFixture = PipeMaterialSyncApiTests.setUpFixture
    tearDown = PipeMaterialSyncApiTests.tearDown
    material = PipeMaterialSyncApiTests.material
    setUp = PipeMaterialSyncApiTests.setUp
    payload = PipeMaterialSyncApiTests.payload

    def test_two_different_tasks_save_same_missing_pipe_once(self):
        second_task = deepcopy(self.task)
        second_task.pk = None
        second_task.task_number = "HT-PIPE-SYNC-CONCURRENT"
        second_task.contract_number = "HTC-PIPE-SYNC-CONCURRENT"
        second_task.save()
        second_product = deepcopy(self.product_line)
        second_product.pk = None
        second_product.production_task = second_task
        second_product.save()
        second_bom = create_bom(product_line=second_product, creation_method="BLANK", actor_employee=self.employee)
        submissions = []
        for bom in (self.bom, second_bom):
            current = self.client.get(f"/api/v1/boms/{bom.pk}/")
            self.assertEqual(current.status_code, 200, current.data)
            sections = bom_fixtures.BomApiTests.fixed_sections(current.data["data"]["sections"])
            for section in sections:
                if section["section_type"] == "PROFILE":
                    section["lines"] = [self.payload(tube_thickness="0.8")]
            body = {"sections": sections}
            preview = self.client.post(f"/api/v1/boms/{bom.pk}/material-save-preview/", body,
                                       format="json", HTTP_IF_MATCH=current["ETag"])
            self.assertEqual(preview.status_code, 200, preview.data)
            body["confirmation_token"] = preview.data["data"]["confirmation_token"]
            submissions.append((str(bom.pk), current["ETag"], body))
        barrier = Barrier(2)
        user_id = self.user.pk

        def save_concurrently(submission):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.user.__class__.objects.get(pk=user_id))
                bom_id, etag, body = submission
                barrier.wait(timeout=15)
                response = client.patch(f"/api/v1/boms/{bom_id}/", body,
                                        format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                connections.close_all()

        before = RawMaterialInformation.objects.count()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(save_concurrently, submissions))
        for status_code, data in results:
            self.assertEqual(status_code, 200, data)
        lines = BomLine.objects.filter(section__bom_id__in=[self.bom.pk, second_bom.pk])
        self.assertEqual(lines.count(), 2)
        self.assertEqual(len({line.raw_values["source_inventory_material_id"] for line in lines}), 1)
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)
