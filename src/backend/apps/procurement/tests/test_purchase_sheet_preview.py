from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase
from openpyxl import load_workbook
from rest_framework.exceptions import ValidationError

from apps.procurement.purchase_sheet_preview import build_purchase_sheet_preview
from apps.procurement.purchase_sheet_xlsx import build_supplier_purchase_sheet_xlsx
from apps.procurement.purchase_sheet_services import normalize_sheet_content
from apps.procurement.api.views import SupplierPurchaseSheetViewSet


class PurchaseSheetPreviewTests(SimpleTestCase):
    def sheet(self, code="FABRIC"):
        return SimpleNamespace(sheet_number="CG-TEST", status="DRAFT", content_snapshot={
            "title": "通用旧标题", "order": {"production_task_number": "SC-TEST"},
            "buyer": {"name": "测试甲方"}, "seller": {"name": "测试乙方"},
            "purchase_date": "2026-10-26", "tax_rate": "13", "freight_bearer": "乙方",
            "settlement_mode": "NORMAL", "remark": "预览测试", "total_amount": "6",
            "lines": [{"source_purchase_order_line_id": "line-1", "part_name": "测试布", "specification": "600D",
                       "unit": "米", "quantity": "5.0000", "unit_price": "1.2000", "amount": "6.0000",
                       "delivery_date": "2026-10-30", "material_attributes_snapshot": {"fields": []}}],
        }, template_version=SimpleNamespace(template=SimpleNamespace(template_code=code)))

    def test_five_previews_match_exported_text_and_no_phantom_columns(self):
        for code, columns, image_count in [("FABRIC", 7, 1), ("FOAM_CUTTING", 6, 2), ("AUXILIARY", 7, 2), ("PLASTIC_PART", 9, 2), ("WEBBING_ACTUAL_WEIGHT", 8, 1)]:
            with self.subTest(code=code):
                sheet = self.sheet(code)
                preview = build_purchase_sheet_preview(sheet)
                workbook = load_workbook(BytesIO(build_supplier_purchase_sheet_xlsx(sheet)), data_only=True)
                try:
                    self.assertEqual(len(preview["columns"]), columns)
                    self.assertEqual(len(preview["images"]), image_count)
                    for row in preview["rows"]:
                        for cell in row["cells"]:
                            value = workbook.active[cell["address"]].value
                            if isinstance(value, str):
                                self.assertEqual("".join(run["text"] for run in cell["runs"]), value)
                    self.assertNotEqual(preview["terms"]["title"], "通用旧标题")
                    self.assertTrue(all(image["width"] > 0 and image["height"] > 0 for image in preview["images"]))
                finally:
                    workbook.close()

    def test_preview_uses_cached_amount_and_trims_zeroes(self):
        preview = build_purchase_sheet_preview(self.sheet())
        cells = {c["address"]: "".join(r["text"] for r in c["runs"]) for row in preview["rows"] for c in row["cells"]}
        self.assertEqual(cells["D6"], "5")
        self.assertEqual(cells["E6"], "1.2")
        self.assertEqual(cells["F6"], "6")

    def test_explicit_edits_reach_both_outputs_and_keep_original_resources(self):
        for code in ("FABRIC", "FOAM_CUTTING", "AUXILIARY", "PLASTIC_PART", "WEBBING_ACTUAL_WEIGHT"):
            with self.subTest(code=code):
                sheet = self.sheet(code)
                original = build_supplier_purchase_sheet_xlsx(sheet)
                sheet.content_snapshot.update(title="已修改标题", payment_and_delivery="新交期", quality_standards=["新质量一", "新质量二", "新质量三"], original_template_edits=["title", "payment_and_delivery", "quality_standards"])
                result = build_supplier_purchase_sheet_xlsx(sheet)
                preview = build_purchase_sheet_preview(sheet)
                self.assertEqual(preview["terms"]["title"], "已修改标题")
                self.assertEqual(preview["terms"]["payment_and_delivery"], "新交期")
                self.assertIn("新质量三", str(preview["terms"]["quality_standards"]))
                with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(result)) as after:
                    for name in before.namelist():
                        if name not in {"xl/worksheets/sheet1.xml", "xl/drawings/drawing1.xml"}:
                            self.assertEqual(before.read(name), after.read(name), name)

    def test_edit_markers_survive_normalization_and_unknown_fields_fail(self):
        sheet = self.sheet()
        content = deepcopy(sheet.content_snapshot)
        content["original_template_edits"] = ["title", "title"]
        normalized, _ = normalize_sheet_content(sheet, content)
        self.assertEqual(normalized["original_template_edits"], ["title"])
        content["original_template_edits"] = ["lines"]
        with self.assertRaises(ValidationError):
            normalize_sheet_content(sheet, content)

    def test_post_preview_does_not_mutate_saved_snapshot_or_allow_published_edits(self):
        sheet = self.sheet()
        before = deepcopy(sheet.content_snapshot)
        submitted = deepcopy(before)
        submitted["lines"][0]["quantity"] = "7"
        view = SupplierPurchaseSheetViewSet()
        request = SimpleNamespace(method="POST", data={"content": submitted})
        with patch.object(view, "get_object", return_value=sheet):
            response = view.preview(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(sheet.content_snapshot, before)
            sheet.status = "PUBLISHED"
            with self.assertRaises(ValidationError):
                view.preview(request)

    def test_preview_reuses_existing_view_and_edit_permissions(self):
        permissions = SupplierPurchaseSheetViewSet.action_permission_map
        self.assertEqual(permissions["preview.GET"], permissions["retrieve"])
        self.assertEqual(permissions["preview.POST"], permissions["update"])
        from apps.access_control.module_operations import ACTION_OVERRIDES
        module = ACTION_OVERRIDES['SupplierPurchaseSheetViewSet']
        self.assertEqual(module['preview.GET'], module['retrieve'])
        self.assertEqual(module['preview.POST'], module['update'])

    def test_unsupported_template_does_not_return_an_inaccurate_preview(self):
        from apps.procurement.fabric_purchase_sheet_template import FabricPurchaseSheetTemplateError
        with self.assertRaises(FabricPurchaseSheetTemplateError):
            build_purchase_sheet_preview(self.sheet("HARDWARE"))
