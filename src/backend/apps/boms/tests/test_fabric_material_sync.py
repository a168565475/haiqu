from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import FabricMaterial, FabricSpecification, FabricWidth, ProductColor
from ..models import BomLine
from ..services import create_bom
from . import test_material_flow_bom as flow_fixtures


class FabricMaterialSyncApiTests(TestCase):
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
        self.fabric_material = FabricMaterial.objects.create(material_name="FABRIC_AUTO_SYNC_PVC")
        self.fabric_spec, _ = FabricSpecification.objects.get_or_create(specification_name="400*300D")
        self.fabric_width, _ = FabricWidth.objects.get_or_create(width_value="1.72")
        self.fabric_color = ProductColor.objects.create(
            color_card="FABRIC_AUTO_SYNC_A", color_code="#22", color_name="深宝蓝",
        )
        self.fabric.material = self.fabric_material.material_name
        self.fabric.specification = "400*300D"
        self.fabric.width = "1.50"
        self.fabric.color = self.fabric_color
        self.fabric.color_snapshot = "深宝蓝"
        self.fabric.warehouse_number = "CK001"
        self.fabric.warehouse_name = "原料布面仓"
        self.fabric.save()

    def payload(self, **changes):
        return {
            "part_name": "20", "unit_consumption": "1",
            "source_fabric_material_id": str(self.fabric_material.pk),
            "source_fabric_specification_id": str(self.fabric_spec.pk),
            "source_fabric_width_id": str(self.fabric_width.pk),
            "source_product_color_id": str(self.fabric_color.pk), **changes,
        }

    def save_fabric(self, *lines):
        return self.save([{"section_type": "FABRIC", "title": "面料类", "lines": list(lines)}])

    def line(self):
        return BomLine.objects.get(section__bom=self.bom, section__title="面料类")

    def source(self, line=None):
        return RawMaterialInformation.objects.get(pk=(line or self.line()).raw_values["source_inventory_material_id"])

    def saved_payload(self):
        return next(section for section in self.get().data["data"]["sections"] if section["title"] == "面料类")["lines"][0]

    def test_complete_reference_selection_creates_inventory_source_on_save(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(self.line().raw_values.get("source_inventory_material_id"))
        source = self.source()
        self.assertEqual((source.material_name, source.material, source.specification, source.width),
                         ("布料", "FABRIC_AUTO_SYNC_PVC", "400*300D", "1.72"))
        self.assertEqual((source.color_id, source.color_snapshot, source.unit.unit_name, source.warehouse_number),
                         (self.fabric_color.pk, "深宝蓝", "米", "CK001"))
        self.assertEqual(self.line().part_name, "20")
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)
        self.fabric_material.refresh_from_db()
        self.assertIsNone(self.fabric_material.inventory_raw_material_id)
        self.assertTrue(AuditLog.objects.filter(object_type="RAW_MATERIAL_INFORMATION", object_id=source.pk,
                                                action="CREATED", context_id=self.bom.pk).exists())
        self.assertEqual(self.verify().status_code, 200)

    def test_reuses_numeric_equivalent_width_and_keeps_part_name_without_add_permission(self):
        width, _ = FabricWidth.objects.get_or_create(width_value="1.500")
        self.user.user_permissions.remove(Permission.objects.get(codename="add_rawmaterialinformation"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload(source_fabric_width_id=str(width.pk)))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.fabric.pk)
        self.assertEqual(self.line().part_name, "20")
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_same_batch_repeated_save_and_other_bom_reuse_one_source(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload(), self.payload(part_name="21"))
        self.assertEqual(response.status_code, 200, response.data)
        ids = {line.raw_values["source_inventory_material_id"] for line in BomLine.objects.filter(section__bom=self.bom)}
        self.assertEqual(len(ids), 1)
        response = self.save(self.get().data["data"]["sections"])
        self.assertEqual(response.status_code, 200, response.data)
        self.bom = create_bom(product_line=self.product_line, creation_method="BLANK", actor_employee=self.employee)
        response = self.save_fabric(self.payload(part_name="另一个用途"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(str(self.source().pk), ids)
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)

    def test_changed_reference_attributes_relink_without_mutating_old_source(self):
        self.assertEqual(self.save_fabric(self.payload()).status_code, 200)
        changes = [
            ("source_fabric_specification_id", FabricSpecification.objects.create(specification_name="500*300D")),
            ("source_fabric_width_id", FabricWidth.objects.create(width_value="1.731")),
            ("source_product_color_id", ProductColor.objects.create(color_card="FABRIC_AUTO_SYNC_B", color_code="#22", color_name="深宝蓝")),
            ("source_fabric_material_id", FabricMaterial.objects.create(material_name="FABRIC_AUTO_SYNC_PE")),
        ]
        for field, reference in changes:
            with self.subTest(field=field):
                old = self.source()
                old_values = RawMaterialInformation.objects.filter(pk=old.pk).values().get()
                payload = self.saved_payload()
                payload[field] = str(reference.pk)
                response = self.save_fabric(payload)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertNotEqual(self.source().pk, old.pk)
                self.assertEqual(RawMaterialInformation.objects.filter(pk=old.pk).values().get(), old_values)
                self.assertEqual(self.line().part_name, "20")

    def test_explicit_clear_all_parameters_preserves_draft_but_blocks_confirmation_and_roundtrip(self):
        self.assertEqual(self.save_fabric(self.payload()).status_code, 200)
        source_id = self.source().pk
        payload = self.saved_payload()
        for field in ("source_fabric_material_id", "source_fabric_specification_id", "source_fabric_width_id", "source_product_color_id"):
            payload[field] = None
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().material, "")
        self.assertEqual(self.line().specification, "")
        self.assertEqual(self.line().raw_values["fabric_width"], "")
        self.assertEqual(self.source().pk, source_id)
        self.assertEqual(self.verify().status_code, 400)
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.verify().status_code, 400)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_partial_reference_selection_is_draft_only_and_does_not_create(self):
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload(source_product_color_id=None))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(self.line().raw_values.get("source_inventory_material_id"))
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        self.assertEqual(self.verify().status_code, 400)

    def test_each_cleared_identity_field_blocks_confirmation(self):
        for field in ("source_fabric_material_id", "source_fabric_specification_id", "source_fabric_width_id", "source_product_color_id"):
            with self.subTest(field=field):
                self.assertEqual(self.save_fabric(self.payload()).status_code, 200)
                payload = self.saved_payload()
                payload[field] = None
                response = self.save_fabric(payload)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.verify().status_code, 400)
                self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
                self.assertEqual(self.verify().status_code, 400)

    def test_source_only_legacy_line_keeps_snapshot_and_can_confirm(self):
        self.fabric.color = None
        self.fabric.save(update_fields=["color"])
        response = self.save_fabric({"part_name": "旧裁片", "source_inventory_material_id": str(self.fabric.pk),
                                     "unit_consumption": "1", "material": "忽略旧接口的非字典快照"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().material, self.fabric.material)
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.verify().status_code, 200)

    def test_snapshot_color_without_fk_does_not_match_specific_color_card(self):
        self.fabric.width = "1.72"
        self.fabric.color = None
        self.fabric.save(update_fields=["width", "color"])
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(self.source().pk, self.fabric.pk)

    def test_explicit_clear_legacy_snapshot_is_not_restored_by_source_only_compatibility(self):
        for field in ("material", "specification", "fabric_width", "fabric_color_card", "fabric_color_code", "fabric_color_name"):
            with self.subTest(field=field):
                response = self.save_fabric({"part_name": "旧裁片", "source_inventory_material_id": str(self.fabric.pk),
                                             "unit_consumption": "1"})
                self.assertEqual(response.status_code, 200, response.data)
                historical = self.line()
                historical.raw_values.update(fabric_width="1.50", fabric_color_card="历史色卡",
                                             fabric_color_code="#22", fabric_color_name="深宝蓝")
                historical.save(update_fields=["raw_values"])
                payload = self.saved_payload()
                payload[field] = ""
                response = self.save_fabric(payload)
                self.assertEqual(response.status_code, 200, response.data)
                actual = getattr(self.line(), field) if field in {"material", "specification"} else self.line().raw_values[field]
                self.assertEqual(actual, "")
                self.assertEqual(self.verify().status_code, 400)
                self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
                self.assertEqual(self.verify().status_code, 400)

    def test_archived_match_is_not_reused(self):
        self.fabric.width = "1.72"
        self.fabric.archived_at = timezone.now()
        self.fabric.save(update_fields=["width", "archived_at"])
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(self.source().pk, self.fabric.pk)

    def test_existing_same_color_name_different_card_does_not_match(self):
        self.fabric.width = "1.72"
        self.fabric.color = ProductColor.objects.create(color_card="OTHER_CARD", color_code="#22", color_name="深宝蓝")
        self.fabric.save(update_fields=["width", "color"])
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(self.source().pk, self.fabric.pk)

    def test_equivalent_candidates_prefer_current_source_and_otherwise_stable_number(self):
        self.fabric.width = "1.72"
        self.fabric.save(update_fields=["width"])
        duplicate = deepcopy(self.fabric)
        duplicate.pk = None
        duplicate.material_number = "A-FABRIC-EQUIVALENT"
        duplicate.material = "  FABRIC_AUTO_SYNC_PVC  "
        duplicate.specification = "400 × 300D"
        duplicate.save()
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, duplicate.pk)
        payload = self.saved_payload()
        payload["source_inventory_material_id"] = str(self.fabric.pk)
        response = self.save_fabric(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.source().pk, self.fabric.pk)
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.source().pk, self.fabric.pk)

    def test_missing_warehouse_returns_400_and_rolls_back(self):
        RawMaterialInformation.objects.filter(warehouse_name="原料布面仓").update(warehouse_name="临时其他仓")
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("原料布面仓", str(response.data))
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_ambiguous_warehouse_does_not_guess_a_default(self):
        other = deepcopy(self.fabric)
        other.pk = None
        other.material_number = "FABRIC_OTHER_WAREHOUSE"
        other.warehouse_number = "CK-FABRIC-OTHER"
        other.save()
        before = RawMaterialInformation.objects.count()
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_changed_legacy_dictionary_selection_missing_width_blocks_old_mapping_confirmation(self):
        self.fabric_material.inventory_raw_material = self.fabric
        self.fabric_material.save(update_fields=["inventory_raw_material"])
        response = self.save_fabric(self.payload(source_fabric_width_id=None, source_product_color_id=None))
        self.assertEqual(response.status_code, 200, response.data)
        # 模拟变更前已存在的历史快照；新建缺参行本来就应处于 pending。
        historical = self.line()
        historical.raw_values.pop("fabric_source_sync_pending", None)
        historical.save(update_fields=["raw_values"])
        payload = self.saved_payload()
        spec = FabricSpecification.objects.create(specification_name="LEGACY-CHANGED-SPEC")
        payload["source_fabric_specification_id"] = str(spec.pk)
        response = self.save_fabric(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.verify().status_code, 400)
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.verify().status_code, 400)

    def test_new_partial_dictionary_selection_cannot_confirm_using_global_mapping(self):
        self.fabric_material.inventory_raw_material = self.fabric
        self.fabric_material.save(update_fields=["inventory_raw_material"])
        other_spec = FabricSpecification.objects.create(specification_name="NEW-DIFFERENT-SPEC")
        response = self.save_fabric(self.payload(source_fabric_specification_id=str(other_spec.pk),
                                               source_fabric_width_id=None, source_product_color_id=None))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.verify().status_code, 400)

    def test_cleared_historical_color_snapshot_cannot_confirm_using_global_mapping(self):
        self.fabric_material.inventory_raw_material = self.fabric
        self.fabric_material.save(update_fields=["inventory_raw_material"])
        response = self.save_fabric(self.payload(source_fabric_width_id=None, source_product_color_id=None))
        self.assertEqual(response.status_code, 200, response.data)
        historical = self.line()
        historical.raw_values.pop("fabric_source_sync_pending", None)
        historical.raw_values["fabric_color_name"] = "历史深宝蓝"
        historical.save(update_fields=["raw_values"])
        payload = self.saved_payload()
        payload["fabric_color_name"] = ""
        self.assertEqual(self.save_fabric(payload).status_code, 200)
        self.assertEqual(self.verify().status_code, 400)
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.verify().status_code, 400)

    def test_unchanged_historical_partial_dictionary_snapshot_remains_compatible(self):
        response = self.save_fabric({"part_name": "旧裁片", "source_inventory_material_id": str(self.fabric.pk),
                                     "unit_consumption": "1"})
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        line.raw_values.update(source_fabric_material_id=str(self.fabric_material.pk),
                               source_fabric_specification_id=str(self.fabric_spec.pk))
        line.save(update_fields=["raw_values"])
        self.assertEqual(self.save(self.get().data["data"]["sections"]).status_code, 200)
        self.assertEqual(self.verify().status_code, 200)

    def test_invalid_nonempty_width_is_not_saved_as_incomplete_draft(self):
        before = RawMaterialInformation.objects.count()
        for value in ("0", "-1", "NaN", "Infinity", "1.72米", "1e999999"):
            with self.subTest(value=value):
                width, _ = FabricWidth.objects.get_or_create(width_value=value)
                response = self.save_fabric(self.payload(source_fabric_width_id=str(width.pk)))
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_create_permission_and_later_validation_failure_roll_back_all_changes(self):
        permission = Permission.objects.get(codename="add_rawmaterialinformation")
        self.user.user_permissions.remove(permission)
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        before = (RawMaterialInformation.objects.count(), AuditLog.objects.count())
        response = self.save_fabric(self.payload())
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual((RawMaterialInformation.objects.count(), AuditLog.objects.count()), before)
        self.user.user_permissions.add(permission)
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        response = self.save_fabric(self.payload(), self.payload(unit_consumption="-1"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual((RawMaterialInformation.objects.count(), AuditLog.objects.count()), before)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_stale_etag_does_not_create_material(self):
        old = self.get()
        self.assertEqual(self.save_fabric(self.payload()).status_code, 200)
        sections = flow_fixtures.fixtures.BomApiTests.fixed_sections([
            {"section_type": "FABRIC", "title": "面料类", "lines": [self.payload()]},
        ])
        before = RawMaterialInformation.objects.count()
        response = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": sections}, format="json",
                                     HTTP_IF_MATCH=old["ETag"])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before)

    def test_new_cutting_links_in_same_save_and_material_inheritance_is_preserved(self):
        cutting = self.material("FABRIC_AUTO_CUTTING", "面料", self.meter_unit)
        cutting.item_type = "SEMI_FINISHED"
        cutting.category = flow_fixtures.ProductCategory.objects.create(item_type="SEMI_FINISHED", category_name="面料同步裁片")
        cutting.unit, _ = flow_fixtures.ProductionUnit.objects.get_or_create(unit_name="套")
        cutting.save()
        key = str(uuid4())
        rows = [dict(part_name="裁片", source_inventory_material_id=str(cutting.pk), fabric_source_client_key=key,
                     cutting_pieces_per_set=2, fabric_meters_per_piece="0.1", cutting_sets_per_product=1, material=material)
                for material in ("/", "210D")]
        sections = [{"section_type": "FABRIC", "title": "裁剪明细", "lines": rows},
                    {"section_type": "FABRIC", "title": "面料类", "lines": [self.payload(client_key=key)]}]
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        lines = list(BomLine.objects.filter(section__bom=self.bom, section__title="裁剪明细").order_by("line_number"))
        self.assertEqual([line.material for line in lines], [self.fabric_material.material_name, "210D"])
        self.assertTrue(all(line.fabric_source_line_id == self.line().pk for line in lines))
        next_material = FabricMaterial.objects.create(material_name="FABRIC_AUTO_NEW_INHERIT")
        sections = response.data["data"]["sections"]
        next(section for section in sections if section["title"] == "面料类")["lines"][0]["source_fabric_material_id"] = str(next_material.pk)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        for line in lines:
            line.refresh_from_db()
        self.assertEqual([line.material for line in lines], [next_material.material_name, "210D"])
        self.assertEqual(self.verify().status_code, 200)


class FabricMaterialSyncConcurrencyTests(TransactionTestCase):
    setUpFixture = FabricMaterialSyncApiTests.setUpFixture
    tearDown = FabricMaterialSyncApiTests.tearDown
    material = FabricMaterialSyncApiTests.material
    setUp = FabricMaterialSyncApiTests.setUp
    payload = FabricMaterialSyncApiTests.payload

    def test_two_different_tasks_create_one_fabric(self):
        second_task = deepcopy(self.task)
        second_task.pk = None
        second_task.task_number = "HT-FABRIC-SYNC-CONCURRENT"
        second_task.contract_number = "HTC-FABRIC-SYNC-CONCURRENT"
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
            sections = flow_fixtures.fixtures.BomApiTests.fixed_sections(current.data["data"]["sections"])
            next(section for section in sections if section["title"] == "面料类")["lines"] = [self.payload()]
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
                response = client.patch(f"/api/v1/boms/{bom_id}/", body, format="json", HTTP_IF_MATCH=etag)
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
