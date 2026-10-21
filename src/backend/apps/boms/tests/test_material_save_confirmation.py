from copy import deepcopy

from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.material_issues.models import OrderMaterialRequirement
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import (AccessoryColor, AccessoryMaterial, AccessoryProductName,
    AccessorySpecification, ProductCategory, ProductColor)
from ..models import Bom, BomLine, BomSection
from ..services import confirm_bom_product
from . import test_bom_api as fixtures
from . import test_pipe_material_sync as pipe_fixtures


class MaterialSaveConfirmationTests(TestCase):
    setUpFixture = pipe_fixtures.PipeMaterialSyncApiTests.setUpFixture
    tearDown = pipe_fixtures.PipeMaterialSyncApiTests.tearDown
    material = pipe_fixtures.PipeMaterialSyncApiTests.material
    get = pipe_fixtures.PipeMaterialSyncApiTests.get
    payload = pipe_fixtures.PipeMaterialSyncApiTests.payload

    def setUp(self):
        pipe_fixtures.PipeMaterialSyncApiTests.setUp(self)

    def body(self, *lines, intent="draft"):
        current = self.get()
        sections = fixtures.BomApiTests.fixed_sections([
            {"section_type": "PROFILE", "title": "管材类", "lines": list(lines)},
        ])
        ids = {row["title"]: row["id"] for row in current.data["data"]["sections"]}
        for row in sections:
            if row["title"] in ids:
                row["id"] = ids[row["title"]]
        return {"sections": sections, "intent": intent}, current["ETag"]

    def snapshot(self):
        return [list(model.objects.order_by("pk").values()) for model in
                (Bom, BomSection, BomLine, RawMaterialInformation, AuditLog, OrderMaterialRequirement)]

    def preview(self, body, etag):
        return self.client.post(f"/api/v1/boms/{self.bom.pk}/material-save-preview/", body,
                                format="json", HTTP_IF_MATCH=etag)

    def commit(self, body, etag):
        return self.client.patch(f"/api/v1/boms/{self.bom.pk}/", body, format="json", HTTP_IF_MATCH=etag)

    def test_preview_lists_one_new_identity_for_two_rows_and_never_writes(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"), self.payload(tube_thickness="0.80"))
        before = self.snapshot()
        response = self.preview(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(len(data["new_materials"]), 1)
        self.assertEqual(data["new_materials"][0]["locations"], [
            {"section_title": "管材类", "line_number": 1}, {"section_title": "管材类", "line_number": 2},
        ])
        self.assertTrue(data["confirmation_token"])
        self.assertEqual(self.snapshot(), before)

    def test_unconfirmed_save_cannot_create_or_change_bom(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        before = self.snapshot()
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["error"]["code"], "MATERIAL_CREATION_CONFIRMATION_REQUIRED")
        self.assertEqual(self.snapshot(), before)

    def test_confirmed_save_creates_once_and_links_both_rows(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"), self.payload(tube_thickness="0.80"))
        before = RawMaterialInformation.objects.count()
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before + 1)
        self.assertEqual(len({line.raw_values["source_inventory_material_id"]
                             for line in BomLine.objects.filter(section__bom=self.bom)}), 1)

    def test_existing_match_needs_no_confirmation_or_add_permission(self):
        self.user.user_permissions.remove(Permission.objects.get(codename="add_rawmaterialinformation"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        body, etag = self.body(self.payload())
        response = self.preview(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], {"confirmation_token": None, "new_materials": []})
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).raw_values["source_inventory_material_id"], str(self.pipe.pk))

    def test_forged_changed_input_and_stale_tokens_never_write(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        token = self.preview(body, etag).data["data"]["confirmation_token"]
        before = self.snapshot()
        for bad in ("forged", token + "x"):
            self.assertEqual(self.commit({**body, "confirmation_token": bad}, etag).status_code, 409)
        changed = deepcopy(body)
        changed["sections"][0]["lines"][0]["tube_thickness"] = "0.9"
        self.assertEqual(self.commit({**changed, "confirmation_token": token}, etag).status_code, 409)
        self.assertEqual(self.commit({**body, "confirmation_token": token}, '"stale"').status_code, 412)
        self.assertEqual(self.snapshot(), before)

    def test_verify_failure_rolls_back_new_material_lines_and_audit(self):
        body, etag = self.body(self.payload(tube_thickness="0.8"), intent="verify")
        response = self.preview(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        before = self.snapshot()
        response = self.commit({**body, "confirmation_token": response.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_verify_intent_saves_and_confirms_with_one_initial_etag(self):
        color, _ = ProductColor.objects.get_or_create(color_card="CONFIRM", color_code="CONFIRM", color_name="测试确认色")
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
            color_code=color.color_code, actor_employee=self.employee)
        body, etag = self.body(self.payload(tube_thickness="0.8"), intent="verify")
        body["quantity_confirmation_reason"] = "测试批次差异"
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        result = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"]["status"], "VERIFIED")

    def test_new_archive_permission_and_verify_permission_are_enforced(self):
        self.user.user_permissions.remove(Permission.objects.get(codename="add_rawmaterialinformation"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        before = self.snapshot()
        self.assertEqual(self.preview(body, etag).status_code, 403)
        self.user.user_permissions.remove(Permission.objects.get(codename="verify_bom"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        body, etag = self.body(self.payload(), intent="verify")
        self.assertEqual(self.preview(body, etag).status_code, 403)
        self.assertEqual(self.commit(body, etag).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def pending(self, category_name, **changes):
        category = ProductCategory.objects.filter(category_name=category_name, item_type="MATERIAL").first()
        if category_name == "半成品":
            category = ProductCategory.objects.filter(item_type="SEMI_FINISHED", status="ACTIVE", archived_at__isnull=True).first()
        return {"material_number": "CONFIRM-NEW-001", "item_type": category.item_type,
                "category": str(category.pk), "material_name": "测试新增物料", "specification": "40*60",
                "unit": str(self.root_unit.pk), "color": None, "material": "待确认材质",
                "warehouse_number": "CK003", "warehouse_name": "原料管材仓", **changes}

    def test_pending_manual_material_is_deferred_for_hardware_plastic_packaging_and_cutting(self):
        for title, category_name in (("五金件", "五金"), ("塑料件类", "塑料件"), ("包材类", "包材"), ("裁剪明细", "半成品")):
            with self.subTest(title=title):
                body, etag = self.body()
                row = {"part_name": "暂存", "pending_raw_material": self.pending(category_name,
                    material_number="CONFIRM-" + str(len(title)) + category_name),
                    "unit_consumption": "1", "units_per_box": "1"}
                if title != "包材类":
                    row.pop("units_per_box")
                next(section for section in body["sections"] if section["title"] == title)["lines"] = [row]
                before = self.snapshot()
                preview = self.preview(body, etag)
                self.assertEqual(preview.status_code, 200, preview.data)
                self.assertEqual(len(preview.data["data"]["new_materials"]), 1)
                self.assertEqual(preview.data["data"]["new_materials"][0]["item_type"], row["pending_raw_material"]["item_type"])
                self.assertEqual(self.snapshot(), before)
                response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertNotIn("pending_raw_material", BomLine.objects.get(section__bom=self.bom).raw_values)

    def auxiliary(self):
        product = AccessoryProductName.objects.create(product_name="确认用织带", unit_name=self.root_unit.unit_name)
        spec = AccessorySpecification.objects.create(product_name=product, specification_value="25mm")
        color = AccessoryColor.objects.create(product_name=product, color_name="黑色")
        material = AccessoryMaterial.objects.create(material_name="确认用涤棉")
        seed = self.material("CONFIRM-AUX-SEED", "辅料", self.root_unit)
        seed.warehouse_number, seed.warehouse_name = "CK010", "辅料仓"
        seed.save()
        return {"part_name": product.product_name, "unit_consumption": "1",
                "source_accessory_product_name_id": str(product.pk), "source_accessory_specification_id": str(spec.pk),
                "source_accessory_color_id": str(color.pk), "source_accessory_material_id": str(material.pk)}

    def test_auxiliary_full_attributes_link_without_changing_global_material_mapping(self):
        auxiliary = self.auxiliary()
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "辅料类")["lines"] = [auxiliary]
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(len(preview.data["data"]["new_materials"]), 1)
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        source = RawMaterialInformation.objects.get(pk=line.raw_values["source_inventory_material_id"])
        self.assertEqual((source.material_name, source.specification, source.color_snapshot, source.material),
                         ("确认用织带", "25mm", "黑色", "确认用涤棉"))
        self.assertIsNone(AccessoryMaterial.objects.get(pk=auxiliary["source_accessory_material_id"]).inventory_raw_material_id)
        current = self.get()
        new_spec = AccessorySpecification.objects.create(product_name_id=auxiliary["source_accessory_product_name_id"], specification_value="30mm")
        sections = current.data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "辅料类")["lines"][0]
        row["source_accessory_specification_id"] = str(new_spec.pk)
        changed = self.preview({"sections": sections, "intent": "draft"}, current["ETag"])
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["data"]["new_materials"][0]["specification"], "30mm")
        source.refresh_from_db()
        self.assertEqual(source.specification, "25mm")

    def test_previewed_dictionary_change_requires_new_confirmation(self):
        auxiliary = self.auxiliary()
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "辅料类")["lines"] = [auxiliary]
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        AccessoryMaterial.objects.filter(pk=auxiliary["source_accessory_material_id"]).update(material_name="变化后的材质")
        before = self.snapshot()
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_pending_invalid_archive_fields_and_wrong_section_never_write(self):
        body, etag = self.body()
        hardware = next(section for section in body["sections"] if section["title"] == "五金件")
        before = self.snapshot()
        for patch in ({"material_number": ""}, {"specification": ""}, {"warehouse_name": "不存在的仓库"}):
            hardware["lines"] = [{"part_name": "暂存", "pending_raw_material": self.pending("五金", **patch)}]
            response = self.preview(body, etag)
            self.assertEqual(response.status_code, 400, response.data)
        hardware["lines"] = [{"part_name": "暂存", "pending_raw_material": self.pending("塑料件")}]
        self.assertEqual(self.preview(body, etag).status_code, 400)
        hardware["lines"] = [{"part_name": "暂存", "source_inventory_material_id": str(self.pipe.pk),
                              "pending_raw_material": self.pending("五金")}]
        self.assertEqual(self.preview(body, etag).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_pending_matching_inventory_reused_instead_of_duplicate_number_error(self):
        seed = self.material("CONFIRM-EXISTING", "五金", self.root_unit)
        seed.material_name, seed.material, seed.specification = "测试新增物料", "待确认材质", "40*60"
        seed.save()
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "五金件")["lines"] = [
            {"part_name": "暂存", "pending_raw_material": self.pending("五金", material_number=seed.material_number)}]
        before = RawMaterialInformation.objects.count()
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["data"]["new_materials"], [])
        self.assertEqual(self.commit(body, etag).status_code, 200)
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).raw_values["source_inventory_material_id"], str(seed.pk))

    def test_preview_requires_etag_and_uses_session_csrf_protection(self):
        from rest_framework.test import APIClient
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        url = f"/api/v1/boms/{self.bom.pk}/material-save-preview/"
        self.assertEqual(self.client.post(url, body, format="json").status_code, 428)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        before = self.snapshot()
        self.assertEqual(client.post(url, body, format="json", HTTP_IF_MATCH=etag).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        from django.middleware.csrf import _get_new_csrf_string
        csrf = _get_new_csrf_string()
        client.cookies["csrftoken"] = csrf
        response = client.post(url, body, format="json", HTTP_IF_MATCH=etag, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_pending_reuse_displays_actual_archive_number_instead_of_proposed_number(self):
        source = self.material("CONFIRM-REAL-CODE", "五金", self.root_unit)
        source.material_name, source.specification, source.material = "测试新增物料  ", "40*60", ""
        source.save()
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "五金件")["lines"] = [
            {"part_name": "暂存", "pending_raw_material": self.pending("五金", material_number="CONFIRM-UNUSED", material="")},
        ]
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual((line.raw_material, line.raw_values["hardware_material_number"]),
                         ("CONFIRM-REAL-CODE", "CONFIRM-REAL-CODE"))

    def test_pending_hardware_reuse_keeps_kg_flow_unit_and_requires_positive_piece_weight(self):
        source = self.material("CONFIRM-KG", "五金", self.root_unit)
        source.material_name, source.specification, source.material, source.flow_unit = "测试新增物料", "40*60", "待确认材质", "KG"
        source.save()
        body, etag = self.body()
        row = {"part_name": "暂存", "pending_raw_material": self.pending("五金", material_number="CONFIRM-UNUSED")}
        next(section for section in body["sections"] if section["title"] == "五金件")["lines"] = [row]
        before = self.snapshot()
        self.assertEqual(self.preview(body, etag).status_code, 400)
        row["unit_material_weight_kg"] = "0"
        self.assertEqual(self.commit(body, etag).status_code, 400)
        self.assertEqual(self.snapshot(), before)
        row["unit_material_weight_kg"] = "0.125"
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).raw_values["hardware_flow_unit"], "KG")

    def test_verify_quantity_failure_after_material_creation_rolls_back(self):
        color, _ = ProductColor.objects.get_or_create(color_card="CONFIRM", color_code="CONFIRM", color_name="测试确认色")
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
            color_code=color.color_code, actor_employee=self.employee)
        body, etag = self.body(self.payload(tube_thickness="0.8"), intent="verify")
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        before = self.snapshot()
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("quantity_confirmation_reason", response.data["error"]["field_errors"])
        self.assertEqual(self.snapshot(), before)

    def test_token_is_bound_to_intent_bom_and_user(self):
        from ..material_save_plan import SALT
        from django.core import signing
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        token = preview.data["data"]["confirmation_token"]
        values = signing.loads(token, salt=SALT)
        before = self.snapshot()
        for field in ("intent", "bom", "user"):
            other = signing.dumps({**values, field: "other-authorized-preview"}, salt=SALT)
            self.assertEqual(self.commit({**body, "confirmation_token": other}, etag).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_auxiliary_confirmation_reaches_procurement_without_rewriting_placeholder_archive(self):
        from apps.procurement.services import _bom_source_details
        from apps.products.material_identity import resolve_bom_line_raw_material
        auxiliary = self.auxiliary()
        previous = RawMaterialInformation.objects.get(material_number="CONFIRM-AUX-SEED")
        previous.material_name, previous.specification = "确认用织带", "25mm"
        previous.material, previous.color_snapshot = "/", "黑色"
        previous.save()
        previous_snapshot = RawMaterialInformation.objects.filter(pk=previous.pk).values().get()
        color, _ = ProductColor.objects.get_or_create(color_card="CONFIRM", color_code="CONFIRM", color_name="测试确认色")
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
            color_code=color.color_code, actor_employee=self.employee)
        body, etag = self.body(intent="verify")
        body["quantity_confirmation_reason"] = "测试批次数量差异"
        next(section for section in body["sections"] if section["title"] == "辅料类")["lines"] = [auxiliary]
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["data"]["new_materials"][0]["material"], "确认用涤棉")
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.bom.refresh_from_db()
        line = BomLine.objects.get(section__bom=self.bom)
        source, _ = resolve_bom_line_raw_material(line)
        self.assertIsNotNone(source)
        self.assertNotEqual(source.pk, previous.pk)
        blockers, lines = _bom_source_details(self.product_line, self.bom)
        self.assertEqual(blockers, [])
        self.assertEqual(len(lines), 1)
        self.assertEqual(RawMaterialInformation.objects.filter(pk=previous.pk).values().get(), previous_snapshot)
        self.assertIsNone(AccessoryMaterial.objects.get(pk=auxiliary["source_accessory_material_id"]).inventory_raw_material_id)

    def test_verify_only_permission_keeps_legacy_endpoint_without_saving_new_archive(self):
        self.user.user_permissions.remove(Permission.objects.get(codename="change_bom"))
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        body, etag = self.body(self.payload())
        self.assertEqual(self.preview(body, etag).status_code, 403)
        response = self.client.post(f"/api/v1/boms/{self.bom.pk}/verify/", {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertNotEqual(response.data["error"]["code"], "PERMISSION_DENIED")

    def test_another_bom_creates_previewed_identity_before_confirmation_and_it_is_reused(self):
        from ..services import create_bom
        body, etag = self.body(self.payload(tube_thickness="0.8"))
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        original = self.bom
        other_task = deepcopy(self.task)
        other_task.pk = None
        other_task.task_number, other_task.contract_number = "HT-CONFIRM-OTHER", "HTC-CONFIRM-OTHER"
        other_task.save()
        other_product = deepcopy(self.product_line)
        other_product.pk, other_product.production_task = None, other_task
        other_product.save()
        self.bom = create_bom(product_line=other_product, creation_method="BLANK", actor_employee=self.employee)
        other_body, other_etag = self.body(self.payload(tube_thickness="0.8", part_name="其他 BOM 后支撑管"))
        other_preview = self.preview(other_body, other_etag)
        self.assertEqual(other_preview.status_code, 200, other_preview.data)
        self.assertEqual(self.commit({**other_body, "confirmation_token": other_preview.data["data"]["confirmation_token"]}, other_etag).status_code, 200)
        other_source = BomLine.objects.get(section__bom=self.bom).raw_values["source_inventory_material_id"]
        self.bom = original
        before = RawMaterialInformation.objects.count()
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).raw_values["source_inventory_material_id"], other_source)
        self.assertEqual(RawMaterialInformation.objects.count(), before)


class FabricMaterialSaveConfirmationTests(TestCase):
    from . import test_fabric_material_sync as fabric_fixtures
    setUpFixture = fabric_fixtures.FabricMaterialSyncApiTests.setUpFixture
    setUp = fabric_fixtures.FabricMaterialSyncApiTests.setUp
    tearDown = fabric_fixtures.FabricMaterialSyncApiTests.tearDown
    material = fabric_fixtures.FabricMaterialSyncApiTests.material
    get = fabric_fixtures.FabricMaterialSyncApiTests.get
    payload = fabric_fixtures.FabricMaterialSyncApiTests.payload
    body = MaterialSaveConfirmationTests.body
    preview = MaterialSaveConfirmationTests.preview
    commit = MaterialSaveConfirmationTests.commit
    snapshot = MaterialSaveConfirmationTests.snapshot

    def test_fabric_and_pending_cutting_output_are_distinct_and_fabric_is_deduplicated(self):
        from uuid import uuid4
        key = str(uuid4())
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "面料类")["lines"] = [
            self.payload(client_key=key), self.payload(part_name="21"),
        ]
        category = ProductCategory.objects.filter(item_type="SEMI_FINISHED", status="ACTIVE", archived_at__isnull=True).first()
        raw = {"material_number": "CONFIRM-CUTTING", "item_type": "SEMI_FINISHED", "category": str(category.pk),
               "material_name": "座布", "specification": "40*60", "material": "/", "unit": str(self.root_unit.pk),
               "warehouse_number": "CK001", "warehouse_name": "原料布面仓"}
        next(section for section in body["sections"] if section["title"] == "裁剪明细")["lines"] = [
            {"part_name": "座布", "pending_raw_material": raw, "fabric_source_client_key": key,
             "cutting_pieces_per_set": 2, "cutting_sets_per_product": 1},
        ]
        before = self.snapshot()
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(len(preview.data["data"]["new_materials"]), 2)
        self.assertEqual(sorted(row["item_type"] for row in preview.data["data"]["new_materials"]), ["MATERIAL", "SEMI_FINISHED"])
        fabric_preview = next(row for row in preview.data["data"]["new_materials"] if row["item_type"] == "MATERIAL")
        self.assertEqual((fabric_preview["specification"], fabric_preview["width"], fabric_preview["color_name"], fabric_preview["color_label"]),
                         ("400*300D", "1.72", "深宝蓝", "FABRIC_AUTO_SYNC_A / #22 / 深宝蓝"))
        self.assertEqual(self.snapshot(), before)
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        cutting = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        source = RawMaterialInformation.objects.get(pk=cutting.raw_values["source_inventory_material_id"])
        self.assertEqual(source.item_type, "SEMI_FINISHED")
        self.assertEqual(cutting.material, self.fabric_material.material_name)
        self.assertEqual((source.material, source.color_id, source.color_snapshot),
                         (self.fabric_material.material_name, self.fabric_color.pk, self.fabric_color.color_name))
        self.assertEqual(cutting.raw_values["cutting_color"], self.fabric_color.color_name)
        self.assertEqual(cutting.fabric_source_line.section.title, "面料类")
        self.assertEqual((cutting.cutting_pieces_per_set, cutting.cutting_sets_per_product), (2, 1))
        self.assertIsNone(cutting.fabric_meters_per_piece)
        self.assertIsNone(cutting.fabric_meters_per_set)
