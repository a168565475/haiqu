from decimal import Decimal

from django.test import TestCase

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductColor, ProductionUnit
from apps.material_issues.models import OrderMaterialRequirement
from ..models import Bom, BomLine, BomSection
from ..services import _create_sections, _sync_profile_lines_to_order_quantity, confirm_bom_product, create_bom
from . import test_bom_api as fixtures


class MaterialFlowBomTests(TestCase):
    setUpFixture = fixtures.BomApiTests.setUp
    tearDown = fixtures.BomApiTests.tearDown

    def setUp(self):
        self.setUpFixture()
        self.product_line.quantity = 1000
        self.product_line.save()
        self.bom = create_bom(product_line=self.product_line, creation_method="BLANK", actor_employee=self.employee)
        self.root_unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "S4ROOT"})
        self.meter_unit, _ = ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "S4METER"})
        ProductionUnit.objects.get_or_create(unit_name="支", defaults={"unit_code": "S4PIECE"})
        self.pipe = self.material("S4PIPE", "管材", self.root_unit)
        self.fabric = self.material("S4FABRIC", "面料", self.meter_unit)

    def material(self, code, category, unit):
        return RawMaterialInformation.objects.create(material_number=code, material_name=code, material="测试材质",
            item_type="MATERIAL", category=ProductCategory.objects.get(category_name=category, item_type="MATERIAL"),
            specification="S4规格", unit=unit)

    def get(self):
        response = self.client.get(f"/api/v1/boms/{self.bom.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def pipe_payload(self, **changes):
        return {"part_name": "座架", "source_inventory_material_id": str(self.pipe.pk), "length_value": "500",
                "unit_consumption": "2", "tube_cut_piece_count": "6", **changes}

    def save(self, supplied):
        current = self.get()
        sections = fixtures.BomApiTests.fixed_sections(supplied)
        ids = {row["title"]: row["id"] for row in current.data["data"]["sections"]}
        for row in sections:
            if row["title"] in ids: row["id"] = ids[row["title"]]
        return self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": sections},
            format="json", HTTP_IF_MATCH=current["ETag"])

    def initial(self):
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload()]}])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def verify(self):
        # 本组测试材料流转，先通过真实服务完成产品核对，避免产品门禁掩盖目标校验。
        color, _ = ProductColor.objects.get_or_create(
            color_card="BOM_FLOW", color_code="BOM_FLOW", color_name="材料流转测试色",
        )
        self.bom = confirm_bom_product(bom=self.bom, product=self.product, product_color=color,
                                      color_code=color.color_code, actor_employee=self.employee)
        response = self.get()
        return self.client.post(f"/api/v1/boms/{self.bom.pk}/verify/", {"quantity_confirmation_reason": "测试批次数量差异"},
            format="json", HTTP_IF_MATCH=response["ETag"])

    def test_save_calculates_roots_meters_and_ignores_derived_input(self):
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload(
            branch_count="1", original_material_length="1", suggested_bar_count=1, suggested_purchase_meters="1")]}])
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual((line.cutting_length_mm, line.suggested_bar_count, line.raw_bar_length_m, line.suggested_purchase_meters),
                         (500, 337, Decimal("3.05"), Decimal("1027.85")))
        self.assertEqual((line.branch_count, line.original_material_length, line.unit), ("337", "3.05", "根"))

    def test_readonly_quantity_preview_formula_errors_permissions_and_no_writes(self):
        endpoint = '/api/v1/boms/material-flow-preview/'
        payload = {'kind': 'PIPE', 'order_quantity': '1000', 'cutting_length_mm': '500', 'pieces_per_product': '2', 'pieces_per_bar': '6'}
        before = (BomLine.objects.count(), OrderMaterialRequirement.objects.count())
        result = self.client.post(endpoint, payload, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual((result.data['data']['suggested_bar_count'], result.data['data']['suggested_purchase_meters']), (337, '1027.85'))
        fabric = self.client.post(endpoint, {'kind': 'FABRIC', 'order_quantity': '1000', 'unit_consumption': '2.5'}, format='json')
        self.assertEqual(fabric.data['data']['suggested_purchase_meters'], '2500.0000')
        for bad in ['1.5', '0', '-1', 'NaN', '1e100']:
            response = self.client.post(endpoint, {**payload, 'pieces_per_bar': bad}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('pieces_per_bar', str(response.data))
        self.assertEqual(self.client.post(endpoint, {'kind': 'PIPE'}, format='json').status_code, 400)
        self.assertEqual((BomLine.objects.count(), OrderMaterialRequirement.objects.count()), before)
        self.user.user_permissions.clear()
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(endpoint, payload, format='json').status_code, 403)

    def test_decimal_cutting_values_rejected_atomically(self):
        self.initial()
        for field in ["length_value", "tube_cut_piece_count", "unit_consumption"]:
            response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload(**{field: "1.5"})]}])
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom).suggested_bar_count, 337)

    def test_missing_cut_count_can_save_but_cannot_verify(self):
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload(tube_cut_piece_count="")]}])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.verify().status_code, 400)

    def test_confirmation_does_not_create_early_stock_quota(self):
        self.initial()
        response = self.verify()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(OrderMaterialRequirement.objects.filter(measurement_kind="PIPE", production_task=self.task).exists())
        from apps.material_issues.pipe_requirements import sync_pipe_requirement
        requirement = sync_pipe_requirement(BomLine.objects.get(section__bom=self.bom).pk)
        self.assertEqual(requirement.required_quantity, 2022)

    def test_copy_keeps_revision_identity_and_relinks_fabric(self):
        self.initial()
        fabric, cutting = self.add_fabric_and_cutting()
        new_bom = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        old_pipe = BomLine.objects.get(section__bom=self.bom, section__section_type="PROFILE")
        new_pipe = BomLine.objects.get(section__bom=new_bom, section__section_type="PROFILE")
        copied_cutting = BomLine.objects.get(section__bom=new_bom, section__title="裁剪明细")
        self.assertEqual(new_pipe.component_identity, old_pipe.component_identity)
        self.assertNotEqual(copied_cutting.fabric_source_line_id, fabric.pk)
        self.assertEqual(copied_cutting.fabric_source_line.section.bom_id, new_bom.pk)

    def test_copy_to_another_product_line_gets_new_identity(self):
        self.initial()
        source_line = BomLine.objects.get(section__bom=self.bom)
        another = self.product_line.__class__.objects.get(pk=self.product_line.pk)
        another.pk = None
        another.line_number = 2
        another.save()
        copy = create_bom(product_line=another, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        self.assertNotEqual(BomLine.objects.get(section__bom=copy).component_identity, source_line.component_identity)

    def test_order_sync_recalculates_not_proportionally_scales_old_roots(self):
        self.initial()
        self.bom.order_quantity = 1001
        self.bom.save()
        from django.db import transaction
        with transaction.atomic():
            _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual((line.branch_count, line.total_purchase_quantity), ("338", "1030.90"))

    def add_fabric_and_cutting(self):
        fabric_section = BomSection.objects.filter(bom=self.bom, title="面料类").first()
        cutting_section = BomSection.objects.filter(bom=self.bom, title="裁剪明细").first()
        fabric = BomLine.objects.create(section=fabric_section, line_number=1, part_name="座布原料", unit="米", unit_consumption="2.5",
            raw_values={"source_inventory_material_id": str(self.fabric.pk)})
        cutting = BomLine.objects.create(section=cutting_section, line_number=1, part_name="座布裁片", unit="套",
            fabric_source_line=fabric, fabric_meters_per_set="1.5")
        return fabric, cutting

    def test_fabric_quantity_and_cutting_mapping_saved(self):
        self.initial()
        fabric, cutting = self.add_fabric_and_cutting()
        payload = self.get().data["data"]["sections"]
        response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.data)
        fabric.refresh_from_db()
        self.assertEqual(Decimal(fabric.total_purchase_quantity), 2500)
        cutting.refresh_from_db()
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)

    def test_removing_referenced_fabric_is_rejected(self):
        self.initial()
        fabric, _ = self.add_fabric_and_cutting()
        payload = self.get().data["data"]["sections"]
        for section in payload:
            if section["title"] == "面料类": section["lines"] = []
        self.assertEqual(self.save(payload).status_code, 400)
        self.assertTrue(BomLine.objects.filter(pk=fabric.pk).exists())

    def test_cross_bom_fabric_and_self_link_are_rejected(self):
        self.initial()
        fabric, cutting = self.add_fabric_and_cutting()
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        foreign_fabric = BomLine.objects.get(section__bom=copied, section__title="面料类")
        for target in [cutting.pk, foreign_fabric.pk, BomLine.objects.get(section__bom=self.bom, section__section_type="PROFILE").pk]:
            payload = self.get().data["data"]["sections"]
            for section in payload:
                if section["title"] == "裁剪明细": section["lines"][0]["fabric_source_line_id"] = str(target)
            self.assertEqual(self.save(payload).status_code, 400)
        cutting.refresh_from_db()
        self.assertEqual(cutting.fabric_source_line_id, fabric.pk)

    def test_picker_scoped_units_permissions_and_bad_input(self):
        response = self.client.get("/api/v1/boms/pipe-materials/", {"q": "S4"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [str(self.pipe.pk)])
        self.assertEqual(self.client.get("/api/v1/boms/fabric-materials/", {"q": "x" * 101}).status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(self.user.__class__.objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/v1/boms/pipe-materials/").status_code, 403)

    def test_save_stale_etag_does_not_change_existing_data(self):
        before = self.get()
        self.initial()
        response = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", {"sections": []}, format="json", HTTP_IF_MATCH=before["ETag"])
        self.assertEqual(response.status_code, 412, response.data)
        self.assertEqual(BomLine.objects.filter(section__bom=self.bom).count(), 1)

    def test_meter_fabric_source_cannot_be_kilograms(self):
        self.initial()
        self.fabric.unit = self.root_unit
        self.fabric.save()
        payload = self.get().data["data"]["sections"]
        for section in payload:
            if section["title"] == "面料类":
                section["lines"] = [{"part_name": "错误单位面料", "source_inventory_material_id": str(self.fabric.pk), "unit_consumption": "2.5"}]
        self.assertEqual(self.save(payload).status_code, 400)

    def test_used_pipe_cannot_disappear_in_revision_with_only_fabric(self):
        self.initial()
        self.assertEqual(self.verify().status_code, 200)
        from apps.material_issues.pipe_requirements import sync_pipe_requirement
        requirement = sync_pipe_requirement(BomLine.objects.get(section__bom=self.bom).pk)
        requirement.internal_issued_quantity = 6
        requirement.save()
        self.add_fabric_and_cutting()
        revision = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        BomLine.objects.filter(section__bom=revision, section__section_type="PROFILE").delete()
        self.bom = revision
        self.assertEqual(self.verify().status_code, 400)

    def test_unissued_confirmed_line_is_deletable_without_early_contribution(self):
        self.initial()
        self.assertEqual(self.verify().status_code, 200)
        response = self.save([])
        self.assertEqual(response.status_code, 200, response.data)

    def test_copy_to_new_order_recalculates_weight(self):
        self.initial()
        self.product_line.quantity = 2000
        self.product_line.save()
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee)
        line = BomLine.objects.get(section__bom=copied)
        self.assertEqual(Decimal(line.raw_values["long_material_total_weight_kg"]), Decimal("3.05") * 674 * Decimal("0.464"))

    def imported_plan(self, *, with_cutting_header=False):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from openpyxl import load_workbook
        from ..workbook_import import parse_bom_workbook
        upload = fixtures.BomApiTests.workbook_bytes(self)
        workbook = load_workbook(BytesIO(upload.read()))
        if with_cutting_header:
            sheet = workbook.worksheets[1]
            sheet['H9'] = '切割长度（mm）'
            sheet['H10'] = 331
            sheet['I10'] = 2
            sheet['P9'] = '每根切割支数'
            sheet['P10'] = 3
            sheet['Q9'] = '采购根数'
            sheet['Q10'] = 1
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bom.xlsx'
            workbook.save(path)
            workbook.close()
            return parse_bom_workbook(path, 'bom.xlsx')

    def test_import_new_headers_recalculates_and_does_not_guess_missing_cut_count(self):
        plan = self.imported_plan(with_cutting_header=True)
        self.bom.sections.all().delete()
        _create_sections(self.bom, plan)
        pipe = BomLine.objects.get(section__bom=self.bom, section__section_type='PROFILE')
        self.assertEqual((pipe.cutting_length_mm, pipe.pieces_per_bar, pipe.raw_bar_length_m), (331, 3, Decimal('1.05')))
        self.assertEqual(pipe.suggested_bar_count, 674)
        old_plan = self.imported_plan()
        self.assertNotIn('tube_cut_piece_count', old_plan['sections'][0]['lines'][0]['raw_values'])

    def test_imported_fabric_alias_recalculates_on_sync_and_cannot_verify_without_source(self):
        plan = self.imported_plan()
        plan['sections'] = [section for section in plan['sections'] if section['section_type'] == 'FABRIC']
        self.bom.sections.all().delete()
        _create_sections(self.bom, plan)
        self.bom.line_count = 1
        self.bom.section_count = 1
        self.bom.save()
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual(line.unit_consumption, '0.5')
        self.assertEqual(Decimal(line.total_purchase_quantity), 500)
        self.bom.order_quantity = 2000
        self.bom.save()
        _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line.refresh_from_db()
        self.assertEqual(Decimal(line.total_purchase_quantity), 1000)
        response = self.verify()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('关联有效原材料', str(response.data))
