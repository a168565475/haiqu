from uuid import uuid4

from django.db import transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductColor, ProductionUnit
from ..api.serializers import BomUpdateInputSerializer, FIXED_BOM_SECTIONS
from ..models import BomLine
from ..services import confirm_bom_product
from . import test_material_save_confirmation as fixtures


class PendingCuttingSnapshotTests(SimpleTestCase):
    def validate_pending(self, *, source_specification="400 × 600 mm", **changes):
        row = {"part_name": "座布", "pending_raw_material": {
            "material_number": "PENDING-CUTTING", "material_name": "座布", "item_type": "SEMI_FINISHED",
            "category": ProductCategory(item_type="SEMI_FINISHED", category_name="裁片"),
            "unit": ProductionUnit(unit_code="PENDING-SET", unit_name="套"),
            "material": "档案材质", "specification": source_specification,
        }, **changes}
        sections = [{"title": title, "section_type": section_type,
                     "lines": [row] if title == "裁剪明细" else []} for title, section_type in FIXED_BOM_SECTIONS]
        serializer = BomUpdateInputSerializer(data={"sections": sections})
        serializer.validate_sections(sections)
        return row

    def test_explicit_blank_or_placeholder_is_not_hidden_by_pending_archive(self):
        for specification in ("", "/"):
            with self.subTest(specification=specification), self.assertRaises(ValidationError):
                self.validate_pending(specification=specification)

    def test_pending_snapshot_preserves_explicit_cutting_attributes(self):
        row = self.validate_pending(material="修改后材质", specification="500 × 700 mm", unit="片")
        self.assertEqual((row["material"], row["specification"], row["unit"]),
                         ("修改后材质", "500 × 700 mm", "片"))
        self.assertEqual(row["_pending_raw_source"].specification, "400 × 600 mm")

    def test_valid_line_cannot_hide_placeholder_in_new_cutting_archive(self):
        with self.assertRaises(ValidationError):
            self.validate_pending(source_specification="/", specification="500 × 700 mm")

    def test_omitted_attributes_use_pending_archive(self):
        row = self.validate_pending()
        self.assertEqual((row["material"], row["specification"], row["unit"]),
                         ("档案材质", "400 × 600 mm", "套"))


class CuttingSpecificationTests(TestCase):
    setUpFixture = fixtures.MaterialSaveConfirmationTests.setUpFixture
    tearDown = fixtures.MaterialSaveConfirmationTests.tearDown
    material = fixtures.MaterialSaveConfirmationTests.material
    get = fixtures.MaterialSaveConfirmationTests.get
    body = fixtures.MaterialSaveConfirmationTests.body
    preview = fixtures.MaterialSaveConfirmationTests.preview
    commit = fixtures.MaterialSaveConfirmationTests.commit
    snapshot = fixtures.MaterialSaveConfirmationTests.snapshot
    pending = fixtures.MaterialSaveConfirmationTests.pending

    def setUp(self):
        fixtures.MaterialSaveConfirmationTests.setUp(self)
        category = ProductCategory.objects.create(item_type="SEMI_FINISHED", category_name="裁片规格测试")
        self.cutting_source = RawMaterialInformation.objects.create(
            material_number="CUTTING-SPEC-001", material_name="座布", item_type="SEMI_FINISHED",
            category=category, unit=self.root_unit, specification="400 × 600 mm", material="测试面料",
        )

    def cutting_body(self, row, intent="draft"):
        body, etag = self.body(intent=intent)
        next(section for section in body["sections"] if section["title"] == "裁剪明细")["lines"] = [
            {"part_name": "座布", "unit_consumption": "1", **row},
        ]
        return body, etag

    def assert_invalid_specification(self, body, etag):
        before = self.snapshot()
        for submit in (self.preview, self.commit):
            response = submit(body, etag)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn("裁剪明细", str(response.data))
            self.assertIn("规格", str(response.data))
            self.assertEqual(self.snapshot(), before)

    def test_missing_specification_in_source_snapshot_is_rejected_for_both_source_fields(self):
        self.cutting_source.specification = "/"
        self.cutting_source.save(update_fields=["specification"])
        for source_field in ("source_cutting_material_id", "source_inventory_material_id"):
            for intent in ("draft", "verify"):
                with self.subTest(source_field=source_field, intent=intent):
                    body, etag = self.cutting_body({source_field: str(self.cutting_source.pk)}, intent)
                    self.assert_invalid_specification(body, etag)

    def test_manual_blank_and_inventory_placeholders_are_rejected(self):
        for specification in ("", "  ", "/", "—", "-", "--", "–", "N/A", "n/a", "NULL", "null"):
            for source_field in ("source_cutting_material_id", "source_inventory_material_id"):
                with self.subTest(specification=specification, source_field=source_field):
                    body, etag = self.cutting_body({source_field: str(self.cutting_source.pk),
                                                   "specification": specification})
                    self.assert_invalid_specification(body, etag)

    def test_pending_cutting_placeholder_is_rejected_before_material_creation(self):
        for intent in ("draft", "verify"):
            with self.subTest(intent=intent):
                body, etag = self.cutting_body({"pending_raw_material": self.pending("半成品",
                    specification="/", category=str(self.cutting_source.category_id))}, intent)
                self.assert_invalid_specification(body, etag)

    def test_pending_archive_cannot_hide_explicit_invalid_line_specification(self):
        for specification in ("", "/"):
            with self.subTest(specification=specification):
                body, etag = self.cutting_body({"pending_raw_material": self.pending("半成品",
                    specification="400 × 600 mm", category=str(self.cutting_source.category_id)),
                    "specification": specification})
                self.assert_invalid_specification(body, etag)

    def test_valid_line_cannot_hide_placeholder_in_pending_archive(self):
        body, etag = self.cutting_body({"pending_raw_material": self.pending("半成品",
            specification="/", category=str(self.cutting_source.category_id)), "specification": "500 × 700 mm"})
        self.assert_invalid_specification(body, etag)

    def test_pending_cutting_keeps_edited_line_specification_after_confirmed_save(self):
        body, etag = self.cutting_body({"pending_raw_material": self.pending("半成品",
            specification="400 × 600 mm", category=str(self.cutting_source.category_id)),
            "specification": "500 × 700 mm", "material": "修改后材质"})
        before = self.snapshot()
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(self.snapshot(), before)
        response = self.commit({**body, "confirmation_token": preview.data["data"]["confirmation_token"]}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual((line.specification, line.material), ("500 × 700 mm", "修改后材质"))
        source = RawMaterialInformation.objects.get(pk=line.raw_values["source_inventory_material_id"])
        self.assertEqual(source.specification, "400 × 600 mm")

    def test_omitted_specification_uses_valid_source_snapshot(self):
        for source_field in ("source_cutting_material_id", "source_inventory_material_id"):
            with self.subTest(source_field=source_field):
                body, etag = self.cutting_body({source_field: str(self.cutting_source.pk)})
                before = self.snapshot()
                response = self.preview(body, etag)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.snapshot(), before)

    def test_explicit_valid_specification_repairs_bom_without_changing_source_archive(self):
        self.cutting_source.specification = "/"
        self.cutting_source.save(update_fields=["specification"])
        body, etag = self.cutting_body({"source_inventory_material_id": str(self.cutting_source.pk),
                                      "specification": "  400 × 600 mm  "})
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(line.specification, "400 × 600 mm")
        self.cutting_source.refresh_from_db()
        self.assertEqual(self.cutting_source.specification, "/")

    def test_valid_pending_cutting_is_still_deferred_until_confirmed_save(self):
        body, etag = self.cutting_body({"pending_raw_material": self.pending("半成品",
            specification="400 × 600 mm", category=str(self.cutting_source.category_id))})
        before = self.snapshot()
        preview = self.preview(body, etag)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(self.snapshot(), before)
        token = preview.data["data"]["confirmation_token"]
        self.assertTrue(token)
        response = self.commit({**body, "confirmation_token": token}, etag)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")
        self.assertEqual(line.specification, "400 × 600 mm")
        source = RawMaterialInformation.objects.get(pk=line.raw_values["source_inventory_material_id"])
        self.assertEqual((source.item_type, source.specification), ("SEMI_FINISHED", "400 × 600 mm"))

    def test_other_sections_keep_their_existing_specification_rules(self):
        body, etag = self.body()
        next(section for section in body["sections"] if section["title"] == "五金件")["lines"] = [
            {"part_name": "五金件", "pending_raw_material": self.pending("五金", specification="/"),
             "unit_consumption": "1"},
        ]
        before = self.snapshot()
        response = self.preview(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.snapshot(), before)

    def prepare_saved_cutting_for_verification(self):
        fabric_key = str(uuid4())
        body, etag = self.cutting_body({"source_cutting_material_id": str(self.cutting_source.pk),
                                      "fabric_source_client_key": fabric_key, "fabric_meters_per_set": "0.5"})
        next(section for section in body["sections"] if section["title"] == "面料类")["lines"] = [
            {"part_name": "座布原料", "client_key": fabric_key,
             "source_inventory_material_id": str(self.fabric.pk), "unit_consumption": "0.5"},
        ]
        response = self.commit(body, etag)
        self.assertEqual(response.status_code, 200, response.data)
        color, _ = ProductColor.objects.get_or_create(
            color_card="CUTTING-SPEC", color_code="CUTTING-SPEC", color_name="裁片规格测试色",
        )
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
                                      color_code=color.color_code, actor_employee=self.employee)
        return BomLine.objects.get(section__bom=self.bom, section__title="裁剪明细")

    def test_independent_verify_rejects_saved_legacy_placeholder_without_writes(self):
        line = self.prepare_saved_cutting_for_verification()
        for specification in ("", "/", "N/A"):
            with self.subTest(specification=specification), transaction.atomic():
                BomLine.objects.filter(pk=line.pk).update(specification=specification)
                current = self.get()
                before = self.snapshot()
                response = self.client.post(f"/api/v1/boms/{self.bom.pk}/verify/",
                    {"quantity_confirmation_reason": "测试批次数量差异"}, format="json", HTTP_IF_MATCH=current["ETag"])
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("规格", str(response.data))
                self.assertEqual(self.snapshot(), before)

    def test_independent_verify_accepts_saved_valid_specification(self):
        self.prepare_saved_cutting_for_verification()
        current = self.get()
        response = self.client.post(f"/api/v1/boms/{self.bom.pk}/verify/",
            {"quantity_confirmation_reason": "测试批次数量差异"}, format="json", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], "VERIFIED")
