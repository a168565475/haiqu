from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import include, path
from openpyxl import load_workbook

from apps.products.material_identity import resolve_bom_line_raw_material
from apps.products.models import RawMaterialInformation
from ..material_flow_calculations import MaterialFlowValueError, pipe_plan, pipe_plan_for_line
from ..models import Bom, BomLine, BomSection
from ..services import _sync_profile_lines_to_order_quantity
from . import test_material_flow_bom as fixtures

urlpatterns = [path("api/v1/", include("apps.boms.api.urls"))]


class SourcePipePurchaseCalculationTests(SimpleTestCase):
    def test_catalog_mapping_must_still_have_active_catalog_and_allowed_unit(self):
        from ..material_save_plan import _has_active_import_material_mapping
        line = SimpleNamespace(material_catalog_id="catalog", material_selection_snapshot={
            "unit_id": "91fb71ce-d88c-464e-a680-f102c0c153aa", "scope": "BASE"})
        allowed = SimpleNamespace(archived_at=None, catalog=SimpleNamespace(archived_at=None),
                                  unit=SimpleNamespace(archived_at=None, status="ACTIVE"))
        with patch("apps.material_catalog.models.MaterialAllowedUnit.objects.select_related") as query, \
                patch("apps.boms.material_save_plan._active_import_material_source") as raw_source:
            query.return_value.filter.return_value.first.return_value = allowed
            self.assertTrue(_has_active_import_material_mapping(line, []))
            for record in (allowed, allowed.catalog, allowed.unit):
                record.archived_at = "archived"
                self.assertFalse(_has_active_import_material_mapping(line, []))
                record.archived_at = None
            allowed.unit.status = "DISABLED"
            self.assertFalse(_has_active_import_material_mapping(line, []))
            allowed.unit.status = "ACTIVE"
            query.return_value.filter.return_value.first.return_value = None
            self.assertFalse(_has_active_import_material_mapping(line, []))
            line.material_selection_snapshot["unit_id"] = "invalid"
            self.assertFalse(_has_active_import_material_mapping(line, []))
            line.material_selection_snapshot = {}
            self.assertFalse(_has_active_import_material_mapping(line, []))
            raw_source.assert_not_called()

    def test_inactive_resolved_or_planned_material_cannot_clear_import_marker(self):
        from ..material_save_plan import _active_import_material_source
        source = SimpleNamespace(pk="known", archived_at=None,
            category=SimpleNamespace(archived_at=None, status="ACTIVE"),
            unit=SimpleNamespace(archived_at=None, status="ACTIVE"))
        line = SimpleNamespace(raw_values={"source_raw_material_id": "known"})
        with patch("apps.products.material_identity.resolve_bom_line_raw_material", return_value=(source, "source_raw_material_id")):
            self.assertIs(_active_import_material_source(line, [source]), source)
            for reference in (source.unit, source.category):
                reference.status = "DISABLED"
                self.assertIsNone(_active_import_material_source(line, [source]))
                reference.status = "ACTIVE"

    def test_deferred_matching_needs_a_known_import_draft(self):
        from ..api.serializers import BomUpdateInputSerializer, FIXED_BOM_SECTIONS
        serializer = BomUpdateInputSerializer(data={
            "sections": [{"title": title, "section_type": kind, "lines": []} for title, kind in FIXED_BOM_SECTIONS],
            "defer_import_material_matching": True,
        })
        self.assertFalse(serializer.is_valid())

    def plan(self, **changes):
        return pipe_plan(**{
            "cutting_length_mm": 500, "pieces_per_product": 2,
            "pieces_per_bar": 6, "order_quantity": 1000,
            "source_purchase_allowance_percent": "1", "source_raw_bar_length_m": "3.10",
            **changes,
        })

    def test_explicit_allowance_keeps_net_demand_and_rounds_purchase_up(self):
        result = self.plan()
        self.assertEqual((result["demand_pieces"], result["suggested_bar_count"],
                          result["raw_bar_length_m"], result["suggested_purchase_meters"]),
                         (2000, 337, "3.10", "1044.70"))
        self.assertEqual(self.plan(source_purchase_allowance_percent="0")["suggested_bar_count"], 334)

    def test_source_length_must_fit_all_cut_pieces(self):
        for changes in ({"cutting_length_mm": 600}, {"pieces_per_bar": 7},
                        {"source_raw_bar_length_m": "2.99"}):
            with self.subTest(changes=changes), self.assertRaises(MaterialFlowValueError):
                self.plan(**changes)

    def test_invalid_explicit_source_values_are_rejected(self):
        for field, values in {
            "source_purchase_allowance_percent": ("-1", "101", "NaN", "1.00001", True),
            "source_raw_bar_length_m": ("0", "-1", "NaN", "3.101", True),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(MaterialFlowValueError):
                    self.plan(**{field: value})


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class SourcePipePurchaseApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    setUp = fixtures.MaterialFlowBomTests.setUp
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    pipe_payload = fixtures.MaterialFlowBomTests.pipe_payload
    workbook_bytes = fixtures.fixtures.BomApiTests.workbook_bytes
    def save(self, supplied, **options):
        current = self.get()
        sections = fixtures.fixtures.BomApiTests.fixed_sections(supplied)
        ids = {row["title"]: row["id"] for row in current.data["data"]["sections"]}
        for row in sections:
            if row["title"] in ids:
                row["id"] = ids[row["title"]]
        body = {"sections": sections, **options}
        preview = self.client.post(f"/api/v1/boms/{self.bom.pk}/material-save-preview/", body,
            format="json", HTTP_IF_MATCH=current["ETag"])
        if preview.status_code != 200:
            return preview
        if preview.data["data"]["confirmation_token"]:
            body["confirmation_token"] = preview.data["data"]["confirmation_token"]
        return self.client.patch(f"/api/v1/boms/{self.bom.pk}/", body,
            format="json", HTTP_IF_MATCH=current["ETag"])

    def create_source_pipe(self):
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [
            self.pipe_payload(source_purchase_allowance_percent="1", source_raw_bar_length_m="3.10")
        ]}])
        self.assertEqual(response.status_code, 200, response.data)
        return BomLine.objects.get(section__bom=self.bom)

    def test_api_persists_returns_and_keeps_source_values_when_old_ui_omits_them(self):
        line = self.create_source_pipe()
        self.assertEqual((line.total_consumption, line.branch_count, line.original_material_length,
                          line.total_purchase_quantity), ("2000", "337", "3.10", "1044.70"))
        source, source_key = resolve_bom_line_raw_material(line)
        self.assertEqual(source_key, "source_inventory_material_id")
        self.assertEqual(source.length, "3100")
        sections = self.get().data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "管材类")["lines"][0]
        self.assertEqual(Decimal(row.pop("source_purchase_allowance_percent")), Decimal("1"))
        self.assertEqual(Decimal(row.pop("source_raw_bar_length_m")), Decimal("3.10"))
        row["notes"] = "旧页面保存时仍保留原表采购参数"
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertEqual((line.branch_count, line.original_material_length), ("337", "3.10"))

    def test_order_quantity_change_and_downstream_snapshot_keep_explicit_allowance(self):
        line = self.create_source_pipe()
        self.bom.order_quantity = Decimal("500")
        self.bom.save(update_fields=["order_quantity"])
        _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line.refresh_from_db()
        self.assertEqual((line.total_consumption, line.branch_count, line.total_purchase_quantity),
                         ("1000", "169", "523.90"))
        self.assertEqual(line.raw_values["tube_cut_length_m"], "3.10")
        snapshot = pipe_plan_for_line(line)
        self.assertEqual((snapshot["suggested_bar_count"], snapshot["raw_bar_length_m"]), (169, "3.10"))

    def test_invalid_source_changes_leave_saved_values_unchanged(self):
        line = self.create_source_pipe()
        for changes in ({"length_value": "600"}, {"tube_cut_piece_count": "7"},
                        {"source_purchase_allowance_percent": "-1"}):
            sections = self.get().data["data"]["sections"]
            row = next(section for section in sections if section["title"] == "管材类")["lines"][0]
            row.update(changes)
            response = self.save(sections)
            self.assertEqual(response.status_code, 400, response.data)
            line.refresh_from_db()
            self.assertEqual((line.length_value, line.branch_count, line.original_material_length),
                             ("500", "337", "3.10"))

    def test_import_draft_can_defer_matching_without_creating_material_or_unknown_metrics(self):
        self.bom.creation_method = "IMPORT"
        self.bom.save(update_fields=["creation_method"])
        payload = self.pipe_payload(source_purchase_allowance_percent="1", source_raw_bar_length_m="3.10")
        payload.pop("source_inventory_material_id")
        before = RawMaterialInformation.objects.count()
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [payload]}],
                             defer_import_material_matching=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertEqual((line.branch_count, line.total_purchase_quantity), ("337", "1044.70"))
        self.assertTrue(line.raw_values["import_material_matching_deferred"])
        self.assertFalse(line.raw_values.get("purchase_unit_weight_kg"))
        from ..material_flow_bom import apply_line_quantities
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            apply_line_quantities(line, self.bom.order_quantity, require_complete=True)

    def test_deferred_matching_is_restricted_to_unconfirmed_import_drafts(self):
        supplied = [{"section_type": "PROFILE", "title": "管材类", "lines": [self.pipe_payload()]}]
        self.assertEqual(self.save(supplied, defer_import_material_matching=True).status_code, 400)
        self.bom.creation_method = "IMPORT"
        self.bom.save(update_fields=["creation_method"])
        self.assertEqual(self.save(supplied, defer_import_material_matching=True, intent="verify").status_code, 400)

    def test_normal_save_cannot_clear_unmatched_import_marker(self):
        from ..material_flow_bom import apply_line_quantities
        from rest_framework.exceptions import ValidationError
        section = BomSection.objects.create(bom=self.bom, line_number=2, title="五金件", section_type="ACCESSORY")
        line = BomLine.objects.create(section=section, line_number=1,
            part_name="待核铆钉", unit="个", raw_values={"import_material_matching_deferred": True})
        response = self.save(self.get().data["data"]["sections"])
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertTrue(line.raw_values["import_material_matching_deferred"])
        with self.assertRaises(ValidationError):
            apply_line_quantities(line, self.bom.order_quantity, require_complete=True)

    def test_normal_matching_clears_marker_only_after_valid_source_is_bound(self):
        self.bom.creation_method = "IMPORT"
        self.bom.save(update_fields=["creation_method"])
        payload = self.pipe_payload()
        payload.pop("source_inventory_material_id")
        response = self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [payload]}],
                             defer_import_material_matching=True)
        self.assertEqual(response.status_code, 200, response.data)
        sections = self.get().data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "管材类")["lines"][0]
        row["source_inventory_material_id"] = str(self.pipe.pk)
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        line = BomLine.objects.get(section__bom=self.bom)
        self.assertFalse(line.raw_values.get("import_material_matching_deferred"))
        self.assertIsNotNone(resolve_bom_line_raw_material(line)[0])

    @patch("apps.boms.uploads._clamav_scan", return_value="stream: OK")
    def test_import_create_can_keep_ambiguous_pipe_shape_pending_without_metrics(self, _scanner):
        original = self.workbook_bytes()
        workbook = load_workbook(BytesIO(original.read()))
        workbook["BOM数据"]["F10"] = "35*25"
        content = BytesIO()
        workbook.save(content)
        workbook.close()
        before = RawMaterialInformation.objects.count()
        for deferred, expected_status in ((False, 400), (True, 201)):
            upload = SimpleUploadedFile("ambiguous_pipe.xlsx", content.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response = self.client.post("/api/v1/boms/", {
                "production_task_product_id": str(self.product_line.pk), "creation_method": "IMPORT",
                "workbook": upload, "defer_import_material_matching": deferred,
            }, format="multipart")
            self.assertEqual(response.status_code, expected_status, response.data)
        imported = Bom.objects.get(pk=response.data["data"]["id"])
        line = BomLine.objects.get(section__bom=imported, section__section_type="PROFILE")
        self.assertEqual(imported.status, "PENDING_CONFIRMATION")
        self.assertEqual(RawMaterialInformation.objects.count(), before)
        self.assertTrue(line.raw_values["import_material_matching_deferred"])
        self.assertFalse(line.raw_values.get("purchase_unit_weight_kg"))
