from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.products.models import RawMaterialInformation
from ..models import Bom, BomLine
from ..services import _merged_raw_values, _sync_profile_lines_to_order_quantity, create_bom
from . import test_material_flow_bom as fixtures


class TubeLegacyMetricMergeTests(SimpleTestCase):
    def test_unchanged_legacy_save_preserves_saved_weight_instead_of_fixed_coefficient(self):
        before = {"tube_unit_weight_kg": "0.9", "long_material_unit_weight_kg": "5.4",
                  "long_material_total_weight_kg": "10.8", "purchase_unit_weight_kg": "0.8",
                  "coating_unit_area_sqm": "0.1"}
        result = _merged_raw_values(before, {"part_name": "只改名称"}, "PROFILE", "管材类", {})
        self.assertEqual({key: result[key] for key in before}, before)

    def test_manual_metrics_clear_unusable_automatic_values_and_preserve_single_weight(self):
        from ..tube_metrics import apply_tube_metrics
        line = SimpleNamespace(line_number=1, length_value="500", raw_bar_length_m=Decimal("3.05"),
            suggested_bar_count=2, raw_values={"tube_shape": "圆管", "tube_diameter": "25", "tube_thickness": "1",
                "tube_metrics_manual": True, "coating_unit_area_sqm": "0.12", "purchase_unit_weight_kg": "0.34",
                "tube_formula_pending": True, "long_material_unit_weight_kg": "2", "long_material_total_weight_kg": "4"})
        apply_tube_metrics(line, require_complete=True)
        self.assertEqual(line.raw_values["tube_unit_weight_kg"], "0.3400")
        self.assertEqual(line.raw_values["long_material_unit_weight_kg"], "")
        self.assertEqual(line.raw_values["long_material_total_weight_kg"], "")
        self.assertNotIn("tube_formula_pending", line.raw_values)


class TubeFormulaBomApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save
    verify = fixtures.MaterialFlowBomTests.verify

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)

    def payload(self, **changes):
        return {"part_name": "公式测试管", "material": "公式测试铁", "tube_shape": "圆管",
                "tube_diameter": "25", "tube_thickness": "1", "length_value": "500",
                "unit_consumption": "2", "tube_cut_piece_count": "6", **changes}

    def save_pipe(self, **changes):
        current = list(BomLine.objects.filter(section__bom=self.bom))
        payload = self.payload(**({"id": str(current[0].pk)} if current else {}), **changes)
        return self.save([{"section_type": "PROFILE", "title": "管材类", "lines": [payload]}])

    def line(self):
        return BomLine.objects.get(section__bom=self.bom, section__section_type="PROFILE")

    def test_preview_is_single_piece_readonly_and_permission_checked(self):
        endpoint = "/api/v1/boms/tube-calculation-preview/"
        before = (Bom.objects.count(), BomLine.objects.count(), RawMaterialInformation.objects.count(), AuditLog.objects.count())
        response = self.client.post(endpoint, self.payload(), format="json")
        self.assertEqual(response.status_code, 200, response.data)
        values = response.data["data"]
        self.assertEqual(Decimal(values["coating_unit_area_sqm"]), Decimal("0.0393"))
        self.assertEqual(Decimal(values["purchase_unit_weight_kg"]), Decimal("0.2959"))
        self.assertEqual(Decimal(values["long_material_unit_weight_kg"]), Decimal("1.8052"))
        self.assertEqual((Bom.objects.count(), BomLine.objects.count(), RawMaterialInformation.objects.count(), AuditLog.objects.count()), before)
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(endpoint, self.payload(), format="json").status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="add_bom"))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(endpoint, self.payload(), format="json").status_code, 200)

    def test_preview_rejects_unknown_shapes_invalid_geometry_and_missing_values(self):
        for changes in ({"tube_shape": "D形"}, {"tube_diameter": "NaN"}, {"tube_thickness": "13"},
                        {"length_value": ""}, {"tube_cut_piece_count": "1.5"}):
            with self.subTest(changes=changes):
                response = self.client.post("/api/v1/boms/tube-calculation-preview/", self.payload(**changes), format="json")
                self.assertEqual(response.status_code, 400, response.data)

    def test_preview_requires_session_csrf_and_active_employee(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/api/v1/boms/tube-calculation-preview/", self.payload(), format="json").status_code, 403)
        anonymous = APIClient()
        self.assertEqual(anonymous.post("/api/v1/boms/tube-calculation-preview/", self.payload(), format="json").status_code, 401)
        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=["archived_at"])
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post("/api/v1/boms/tube-calculation-preview/", self.payload(), format="json").status_code, 403)

    def test_save_calculates_authoritatively_ignores_forged_results_and_quantity(self):
        response = self.save_pipe(purchase_unit_weight_kg="999", coating_unit_area_sqm="999",
                                  raw_values={"tube_formula_snapshot": {"weight_expression": "999"}})
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertEqual(Decimal(line.raw_values["purchase_unit_weight_kg"]), Decimal("0.2959"))
        self.assertEqual(Decimal(line.raw_values["coating_unit_area_sqm"]), Decimal("0.0393"))
        self.assertEqual(line.raw_values["tube_unit_weight_kg"], line.raw_values["purchase_unit_weight_kg"])
        self.assertIn("tube_formula_snapshot", line.raw_values)
        self.assertEqual((line.suggested_bar_count, line.raw_bar_length_m), (339, Decimal("3.05")))

    def test_formula_edit_keeps_old_values_until_explicit_recalculation_or_geometry_edit(self):
        from apps.reference_data.models import TubeCalculationFormula
        self.assertEqual(self.save_pipe().status_code, 200)
        before = deepcopy(self.line().raw_values)
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(area_expression="1", weight_expression="2")
        self.assertEqual(self.save_pipe(part_name="只改部件名称", purchase_unit_weight_kg="999").status_code, 200)
        self.assertEqual(self.line().raw_values["purchase_unit_weight_kg"], before["purchase_unit_weight_kg"])
        self.assertEqual(self.line().raw_values["tube_formula_snapshot"], before["tube_formula_snapshot"])
        self.assertEqual(self.save_pipe(recalculate_tube_metrics=True).status_code, 200)
        self.assertEqual(Decimal(self.line().raw_values["purchase_unit_weight_kg"]), Decimal("2"))
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="3")
        self.assertEqual(self.save_pipe(length_value="501").status_code, 200)
        self.assertEqual(Decimal(self.line().raw_values["purchase_unit_weight_kg"]), Decimal("3"))

    def test_legacy_no_geometry_edit_preserves_manual_values_but_copy_recalculates(self):
        self.assertEqual(self.save_pipe().status_code, 200)
        line = self.line()
        line.raw_values.pop("tube_formula_snapshot")
        line.raw_values.pop("tube_formula_inputs")
        line.raw_values.update(coating_unit_area_sqm="0.88", purchase_unit_weight_kg="0.99",
                               tube_unit_weight_kg="0.99", long_material_unit_weight_kg="6")
        line.save()
        self.assertEqual(self.save_pipe(part_name="保留旧计算", coating_unit_area_sqm="999").status_code, 200)
        self.assertEqual(self.line().raw_values["coating_unit_area_sqm"], "0.88")
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                            actor_employee=self.employee)
        copied_line = BomLine.objects.get(section__bom=copied)
        self.assertEqual(Decimal(copied_line.raw_values["coating_unit_area_sqm"]), Decimal("0.0393"))
        self.assertEqual(self.line().raw_values["coating_unit_area_sqm"], "0.88")

    def test_order_quantity_change_uses_saved_formula_for_weight_summary(self):
        from apps.reference_data.models import TubeCalculationFormula
        self.assertEqual(self.save_pipe().status_code, 200)
        before = deepcopy(self.line().raw_values)
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="99")
        self.bom.order_quantity = 2000
        self.bom.save(update_fields=["order_quantity"])
        _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        line = self.line()
        self.assertEqual(line.raw_values["tube_formula_snapshot"], before["tube_formula_snapshot"])
        self.assertEqual(Decimal(line.raw_values["purchase_unit_weight_kg"]), Decimal("0.2959"))
        self.assertEqual(Decimal(line.raw_values["long_material_total_weight_kg"]), Decimal("1218.5100"))

    def test_new_incomplete_geometry_saves_empty_metrics_and_cannot_confirm(self):
        response = self.save_pipe(tube_diameter="")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().raw_values.get("purchase_unit_weight_kg", ""), "")
        self.assertEqual(self.verify().status_code, 400)

    def test_unsupported_shapes_keep_manual_fields_and_existing_confirmation_flow(self):
        for shape in ("D形管", "方管-带凹槽"):
            with self.subTest(shape=shape):
                response = self.save_pipe(tube_shape=shape, tube_diameter="25*15",
                                          coating_unit_area_sqm="0.8", purchase_unit_weight_kg="0.9")
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.line().raw_values["coating_unit_area_sqm"], "0.8")
                self.assertEqual(self.line().raw_values["purchase_unit_weight_kg"], "0.9")
                self.assertNotIn("tube_formula_snapshot", self.line().raw_values)
        self.assertEqual(self.verify().status_code, 200)

    def test_legacy_missing_dimensions_does_not_gain_new_formula_confirmation_gate(self):
        self.assertEqual(self.save_pipe().status_code, 200)
        line = self.line()
        for key in ("tube_formula_snapshot", "tube_formula_inputs", "tube_formula_pending", "tube_shape", "tube_diameter", "tube_thickness"):
            line.raw_values.pop(key, None)
        line.raw_values["coating_unit_area_sqm"] = "0.8"
        line.save()
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.line().raw_values["coating_unit_area_sqm"], "0.8")

    def test_stale_preview_version_rejects_save_without_changing_saved_line(self):
        from apps.reference_data.models import TubeCalculationFormula
        self.assertEqual(self.save_pipe().status_code, 200)
        preview = self.client.post("/api/v1/boms/tube-calculation-preview/", self.payload(), format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        version = preview.data["data"]["formula_version"]
        before = deepcopy(self.line().raw_values)
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="2", updated_at=timezone.now())
        response = self.save_pipe(recalculate_tube_metrics=True, expected_tube_formula_version=version)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.line().raw_values, before)

    def test_verified_quantity_sync_copy_keeps_formula_but_explicit_copy_uses_latest(self):
        from apps.reference_data.models import TubeCalculationFormula
        from ..services import sync_latest_boms_from_order
        self.assertEqual(self.save_pipe().status_code, 200)
        self.assertEqual(self.verify().status_code, 200)
        before = deepcopy(self.line().raw_values)
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="99")
        self.product_line.quantity = 2000
        self.product_line.save(update_fields=["quantity"])
        sync_latest_boms_from_order(product_line_ids=[self.product_line.pk], actor_employee=self.employee, request=None)
        copied = Bom.objects.filter(product_line=self.product_line).order_by("-version_number").first()
        self.assertNotEqual(copied.pk, self.bom.pk)
        line = BomLine.objects.get(section__bom=copied)
        self.assertEqual(line.raw_values["tube_formula_snapshot"], before["tube_formula_snapshot"])
        self.assertEqual(Decimal(line.raw_values["purchase_unit_weight_kg"]), Decimal("0.2959"))
        self.assertEqual(Decimal(line.raw_values["long_material_total_weight_kg"]), Decimal("1218.5100"))
        explicit = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=copied,
                              actor_employee=self.employee)
        self.assertEqual(Decimal(BomLine.objects.get(section__bom=explicit).raw_values["purchase_unit_weight_kg"]), Decimal("99"))

    def test_formula_failure_can_save_manual_metrics_and_reopen_without_error(self):
        from apps.reference_data.models import TubeCalculationFormula
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="1/0")
        preview = self.client.post("/api/v1/boms/tube-calculation-preview/", self.payload(), format="json")
        self.assertEqual(preview.status_code, 400, preview.data)
        response = self.save_pipe(manual_tube_metrics=True, coating_unit_area_sqm="0.12", purchase_unit_weight_kg="0.34",
                                  recalculate_tube_metrics=True, expected_tube_formula_version="stale")
        self.assertEqual(response.status_code, 200, response.data)
        reopened = next(section for section in self.get().data["data"]["sections"] if section["section_type"] == "PROFILE")["lines"][0]
        self.assertIs(reopened["manual_tube_metrics"], True)
        self.assertEqual((reopened["coating_unit_area_sqm"], reopened["purchase_unit_weight_kg"], reopened["tube_unit_weight_kg"]),
                         ("0.1200", "0.3400", "0.3400"))
        self.assertEqual((reopened["long_material_unit_weight_kg"], reopened["long_material_total_weight_kg"]), ("", ""))
        self.assertEqual(self.verify().status_code, 200)

    def test_invalid_manual_metrics_are_rejected_without_changing_saved_values(self):
        self.assertEqual(self.save_pipe(manual_tube_metrics=True, coating_unit_area_sqm="0", purchase_unit_weight_kg="0").status_code, 200)
        before = deepcopy(self.line().raw_values)
        for field in ("coating_unit_area_sqm", "purchase_unit_weight_kg"):
            for value in ("", "NaN", "Infinity", "-1", "1e2", "0.12345", "1000000000000"):
                with self.subTest(field=field, value=value):
                    response = self.save_pipe(manual_tube_metrics=True, **{field: value})
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertEqual(self.line().raw_values, before)

    def test_manual_mode_survives_omitted_flag_save_quantity_sync_and_copy(self):
        from apps.reference_data.models import TubeCalculationFormula
        self.assertEqual(self.save_pipe(manual_tube_metrics=True, coating_unit_area_sqm="0.12", purchase_unit_weight_kg="0.34").status_code, 200)
        TubeCalculationFormula.objects.filter(group_key="ROUND").update(weight_expression="1/0")
        self.assertEqual(self.save_pipe(part_name="仅改名称").status_code, 200)
        self.bom.order_quantity = 2000
        self.bom.save(update_fields=["order_quantity"])
        _sync_profile_lines_to_order_quantity(self.bom, previous_order_quantity=1000)
        self.product_line.quantity = 2000
        self.product_line.save(update_fields=["quantity"])
        copied = create_bom(product_line=self.product_line, creation_method="COPY", source_bom=self.bom,
                            actor_employee=self.employee)
        for line in (self.line(), BomLine.objects.get(section__bom=copied)):
            self.assertIs(line.raw_values["tube_metrics_manual"], True)
            self.assertEqual(line.raw_values["purchase_unit_weight_kg"], "0.3400")
            self.assertEqual(line.raw_values["long_material_total_weight_kg"], "")
            self.assertNotIn("tube_formula_snapshot", line.raw_values)

    def test_explicit_auto_mode_recalculates_unchanged_geometry(self):
        self.assertEqual(self.save_pipe(manual_tube_metrics=True, coating_unit_area_sqm="0.12", purchase_unit_weight_kg="0.34").status_code, 200)
        response = self.save_pipe(manual_tube_metrics=False)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIs(self.line().raw_values["tube_metrics_manual"], False)
        self.assertEqual(self.line().raw_values["purchase_unit_weight_kg"], "0.2959")
        self.assertEqual(self.line().raw_values["long_material_unit_weight_kg"], "1.8052")
        self.assertIn("tube_formula_snapshot", self.line().raw_values)

    def test_forged_raw_manual_flag_cannot_bypass_automatic_calculation(self):
        response = self.save_pipe(raw_values={"tube_metrics_manual": True}, coating_unit_area_sqm="99", purchase_unit_weight_kg="99")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNot(self.line().raw_values.get("tube_metrics_manual"), True)
        self.assertEqual(self.line().raw_values["purchase_unit_weight_kg"], "0.2959")
