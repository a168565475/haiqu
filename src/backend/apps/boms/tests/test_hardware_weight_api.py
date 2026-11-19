from copy import deepcopy
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.material_catalog.models import MaterialCatalog
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit
from ..models import Bom, BomLine
from . import test_material_flow_bom as fixtures


class HardwareWeightApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    save = fixtures.MaterialFlowBomTests.save
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    endpoint = "/api/v1/boms/hardware-weight-preview/"

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="material_catalog", codename="view_materialcatalog",
        ))
        self.catalog = MaterialCatalog.objects.create(
            category_key="HARDWARE", template_key="HARDWARE", name="单重测试扁圆头半空心铆钉",
        )
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name="个", defaults={"unit_code": "HW-WEIGHT-PIECE"},
        )

    def rivet_input(self, **changes):
        return {"kind": "RIVET_GB873_STEEL", "material": "铁", "specification": "Φ5×30", **changes}

    def washer_input(self, **changes):
        return {
            "kind": "PLAIN_WASHER", "material": "碳钢", "specification": "平垫片",
            "outer_diameter_mm": "12", "inner_diameter_mm": "6.4", "thickness_mm": "1.6", **changes,
        }

    def payload(self, *, material="铁", specification="Φ5×30", size=None, weight_input=None, **changes):
        self.catalog.refresh_from_db()
        attributes = {"material": material, "specification": specification}
        if size is not None:
            attributes["size"] = size
        for key, value in attributes.items():
            self.catalog.attribute_values.get_or_create(scope="BASE", field_key=key, value=value)
        self.catalog.allowed_units.get_or_create(scope="BASE", unit=self.piece_unit)
        existing = BomLine.objects.filter(section__bom=self.bom, section__title="五金件").first()
        return {
            **({"id": str(existing.pk)} if existing else {}),
            "part_name": self.catalog.name, "material": material, "specification": specification,
            "material_catalog_id": str(self.catalog.pk), "unit": self.piece_unit.unit_name,
            "material_selection": {
                "catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                "attributes": attributes, "unit_id": str(self.piece_unit.pk),
            },
            "unit_consumption": "2", "hardware_weight_mode": "AUTO",
            "hardware_weight_input": weight_input if weight_input is not None else self.rivet_input(
                material=material, specification=specification,
            ),
            "unit_material_weight_kg": "999", **changes,
        }

    def save_hardware(self, payload=None, **changes):
        return self.save([{
            "section_type": "ACCESSORY", "title": "五金件",
            "lines": [payload if payload is not None else self.payload(**changes)],
        }])

    def line(self):
        return BomLine.objects.get(section__bom=self.bom, section__title="五金件")

    def detail_line(self):
        sections = self.get().data["data"]["sections"]
        return next(section for section in sections if section["title"] == "五金件")["lines"][0]

    def test_preview_calculates_single_piece_weights_without_business_writes(self):
        before = (Bom.objects.count(), BomLine.objects.count(), RawMaterialInformation.objects.count(), AuditLog.objects.count())
        for payload, expected_kg, expected_g in (
            (self.rivet_input(), "0.00467000", "4.67"),
            (self.washer_input(), "0.00101645", "1.01644848"),
        ):
            with self.subTest(kind=payload["kind"]):
                response = self.client.post(self.endpoint, payload, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                result = response.data["data"]
                self.assertEqual(Decimal(result["unit_material_weight_kg"]), Decimal(expected_kg))
                self.assertAlmostEqual(Decimal(result["unit_weight_g"]), Decimal(expected_g), places=5)
                self.assertTrue(result["calculation_snapshot"])
        self.assertEqual(
            (Bom.objects.count(), BomLine.objects.count(), RawMaterialInformation.objects.count(), AuditLog.objects.count()),
            before,
        )

    def test_preview_rejects_missing_unsupported_and_invalid_parameters(self):
        invalid = [
            {}, self.rivet_input(specification=""), self.rivet_input(material="铝"),
            self.rivet_input(specification="Φ5×39"), self.rivet_input(kind="UNKNOWN"),
            self.washer_input(inner_diameter_mm="12"), self.washer_input(thickness_mm="-1"),
            self.washer_input(outer_diameter_mm="NaN"), self.washer_input(density_g_cm3="0"),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(self.endpoint, payload, format="json")
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_preview_requires_bom_permission(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(self.endpoint, self.rivet_input(), format="json").status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="add_bom"))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(self.endpoint, self.rivet_input(), format="json").status_code, 200)

    def test_preview_uses_session_csrf_and_active_employee_checks(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.endpoint, self.rivet_input(), format="json").status_code, 403)
        csrf_token = "a" * 32
        client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
        accepted = client.post(self.endpoint, self.rivet_input(), format="json", HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(APIClient().post(self.endpoint, self.rivet_input(), format="json").status_code, 401)
        self.employee.archived_at = timezone.now()
        self.employee.save(update_fields=["archived_at"])
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(self.endpoint, self.rivet_input(), format="json").status_code, 403)

    def test_save_recomputes_forged_weight_and_returns_frozen_calculation(self):
        payload = self.payload()
        payload["hardware_weight_snapshot"] = {"unit_material_weight_kg": "999"}
        payload["raw_values"] = {"hardware_weight_snapshot": {"unit_material_weight_kg": "999"}}
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertEqual(Decimal(line.raw_values["unit_material_weight_kg"]), Decimal("0.00467"))
        self.assertEqual(line.raw_values["hardware_weight_mode"], "AUTO")
        snapshot = line.raw_values["hardware_weight_snapshot"]
        self.assertEqual(Decimal(snapshot["unit_material_weight_kg"]), Decimal("0.00467"))
        result = self.detail_line()
        self.assertEqual(result["hardware_weight_snapshot"], snapshot)
        self.assertEqual(result["hardware_weight_mode"], "AUTO")
        self.assertEqual(Decimal(result["unit_material_weight_kg"]), Decimal("0.00467"))

    def test_catalog_selection_is_authoritative_over_client_weight_material_and_specification(self):
        payload = self.payload(weight_input=self.rivet_input(material="铝", specification="Φ4×20"))
        payload.update(material="铝", specification="Φ4×20")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertEqual((line.material, line.specification), ("铁", "Φ5×30"))
        self.assertEqual(Decimal(line.raw_values["unit_material_weight_kg"]), Decimal("0.00467"))
        self.assertEqual(line.raw_values["hardware_weight_snapshot"]["material"], "铁")

    def test_multiple_rivet_catalog_attributes_preview_save_and_reopen_match(self):
        payload = self.payload(material="65Mn", specification="Φ4-40", size="4×40")
        preview_input = self.rivet_input(material="65Mn", specification="Φ4-40 / 4×40")
        preview = self.client.post(self.endpoint, preview_input, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        saved = self.detail_line()
        self.assertEqual(saved["specification"], "Φ4-40 / 4×40")
        self.assertEqual(saved["hardware_weight_input"], preview_input)
        self.assertEqual(saved["unit_material_weight_kg"], preview.data["data"]["unit_material_weight_kg"])

    def test_multiple_washer_catalog_attributes_preview_save_and_reopen_match(self):
        preview_input = {"kind": "PLAIN_WASHER", "material": "碳钢", "specification": "M6 / 12×6.4×1.6"}
        preview = self.client.post(self.endpoint, preview_input, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        payload = self.payload(material="碳钢", specification="M6", size="12×6.4×1.6", weight_input=preview_input)
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        saved = self.detail_line()
        self.assertEqual(saved["specification"], preview_input["specification"])
        self.assertEqual(saved["unit_material_weight_kg"], preview.data["data"]["unit_material_weight_kg"])

    def test_conflicting_catalog_size_cannot_be_hidden_by_valid_client_input(self):
        for kind, specification, size in (
            ("RIVET_GB873_STEEL", "Φ4-40", "4×35"),
            ("PLAIN_WASHER", "M6", "12×6×1.6"),
        ):
            with self.subTest(kind=kind):
                payload = self.payload(material="65Mn", specification=specification, size=size,
                    weight_input={"kind": kind, "material": "65Mn", "specification": specification})
                response = self.save_hardware(payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_washer_save_recomputes_geometry_and_keeps_dimensions(self):
        response = self.save_hardware(self.payload(
            material="碳钢", specification="平垫片", weight_input=self.washer_input(),
        ))
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertEqual(Decimal(line.raw_values["unit_material_weight_kg"]), Decimal("0.00101645"))
        result = self.detail_line()
        self.assertEqual(result["hardware_weight_input"]["outer_diameter_mm"], "12")
        self.assertEqual(result["hardware_weight_input"]["inner_diameter_mm"], "6.4")
        self.assertEqual(result["hardware_weight_input"]["thickness_mm"], "1.6")

    def test_new_specification_recalculates_existing_auto_weight(self):
        response = self.save_hardware()
        self.assertEqual(response.status_code, 200, response.data)
        original_id = self.line().pk
        response = self.save_hardware(specification="Φ5×32")
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        self.assertEqual(line.pk, original_id)
        self.assertEqual(line.specification, "Φ5×32")
        self.assertEqual(Decimal(line.raw_values["unit_material_weight_kg"]), Decimal("0.00497"))

    def test_manual_weight_is_not_overwritten_after_material_specification_changes(self):
        response = self.save_hardware()
        self.assertEqual(response.status_code, 200, response.data)
        payload = self.payload(hardware_weight_mode="MANUAL", unit_material_weight_kg="0.0048")
        payload.pop("hardware_weight_input")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.detail_line()["hardware_weight_mode"], "MANUAL")
        response = self.save_hardware(
            specification="Φ5×32", hardware_weight_mode="MANUAL", unit_material_weight_kg="0.0048",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(self.line().raw_values["unit_material_weight_kg"]), Decimal("0.0048"))
        self.assertEqual(self.detail_line()["hardware_weight_mode"], "MANUAL")

    def test_legacy_manual_weight_stays_unchanged_when_automation_is_not_requested(self):
        payload = self.payload(unit_material_weight_kg="0.0042")
        payload.pop("hardware_weight_mode")
        payload.pop("hardware_weight_input")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        payload["id"] = str(self.line().pk)
        payload["notes"] = "只补充备注"
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().raw_values["unit_material_weight_kg"], "0.0042")
        self.assertNotEqual(self.line().raw_values.get("hardware_weight_mode"), "AUTO")

    def test_legacy_detail_can_be_resubmitted_without_new_weight_fields_blocking_save(self):
        payload = self.payload(unit_material_weight_kg="0.0042")
        payload.pop("hardware_weight_mode")
        payload.pop("hardware_weight_input")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 200, response.data)
        sections = self.get().data["data"]["sections"]
        row = next(section for section in sections if section["title"] == "五金件")["lines"][0]
        row["notes"] = "旧客户端原样回传详情，只改备注"
        response = self.save(sections)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().notes, row["notes"])
        self.assertEqual(self.line().raw_values["unit_material_weight_kg"], "0.0042")

    def test_unchanged_auto_inputs_keep_historical_snapshot_instead_of_current_table(self):
        response = self.save_hardware()
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        line.raw_values["unit_material_weight_kg"] = "0.00480000"
        snapshot = line.raw_values["hardware_weight_snapshot"]
        snapshot.update(version="historical", unit_material_weight_kg="0.00480000", unit_weight_g="4.8")
        line.save(update_fields=["raw_values"])
        before = deepcopy(snapshot)
        response = self.save_hardware(notes="只调整备注", unit_material_weight_kg="999")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.line().raw_values["hardware_weight_snapshot"], before)
        self.assertEqual(Decimal(self.line().raw_values["unit_material_weight_kg"]), Decimal("0.0048"))

    def test_invalid_recalculation_keeps_saved_line_unchanged(self):
        response = self.save_hardware()
        self.assertEqual(response.status_code, 200, response.data)
        line = self.line()
        before = (line.specification, deepcopy(line.raw_values))
        response = self.save_hardware(specification="Φ5×39")
        self.assertEqual(response.status_code, 400, response.data)
        line.refresh_from_db()
        self.assertEqual((line.specification, line.raw_values), before)

    def test_auto_save_requires_calculation_inputs_for_a_new_line(self):
        payload = self.payload()
        payload.pop("hardware_weight_input")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_washer_specification_change_cannot_silently_reuse_omitted_old_dimensions(self):
        response = self.save_hardware(self.payload(
            material="碳钢", specification="平垫片", weight_input=self.washer_input(),
        ))
        self.assertEqual(response.status_code, 200, response.data)
        before = deepcopy(self.line().raw_values)
        payload = self.payload(material="碳钢", specification="另一尺寸平垫片")
        payload.pop("hardware_weight_input")
        response = self.save_hardware(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.line().specification, "平垫片")
        self.assertEqual(self.line().raw_values, before)

    def test_non_hardware_section_cannot_enable_automatic_weight(self):
        catalog = MaterialCatalog.objects.create(
            category_key="PLASTIC", template_key="PLASTIC", name="单重边界测试塑料件",
        )
        catalog.attribute_values.create(scope="BASE", field_key="specification", value="Φ5×30")
        catalog.allowed_units.create(scope="BASE", unit=self.piece_unit)
        payload = {
            "part_name": catalog.name, "material_catalog_id": str(catalog.pk),
            "material_selection": {
                "catalog_version": catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                "attributes": {"specification": "Φ5×30"}, "unit_id": str(self.piece_unit.pk),
            },
            "hardware_weight_mode": "AUTO", "hardware_weight_input": self.rivet_input(),
        }
        response = self.save([{"section_type": "ACCESSORY", "title": "塑料件类", "lines": [payload]}])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("自动单重", str(response.data))
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_weight_save_preserves_etag_conflict_protection(self):
        response = self.save_hardware()
        self.assertEqual(response.status_code, 200, response.data)
        current = self.get()
        body = {"sections": current.data["data"]["sections"]}
        missing = self.client.patch(f"/api/v1/boms/{self.bom.pk}/", body, format="json")
        self.assertEqual(missing.status_code, 428, missing.data)
        response = self.save_hardware(notes="产生新版本")
        self.assertEqual(response.status_code, 200, response.data)
        stale = self.client.patch(
            f"/api/v1/boms/{self.bom.pk}/", body, format="json", HTTP_IF_MATCH=current["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(self.line().notes, "产生新版本")
        self.assertEqual(Decimal(self.line().raw_values["unit_material_weight_kg"]), Decimal("0.00467"))
