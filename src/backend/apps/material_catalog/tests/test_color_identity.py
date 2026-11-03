import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.api.serializers import BomCatalogSelectionSerializer
from apps.boms.catalog_selection import apply_catalog_selection
from apps.core.api.concurrency import etag_for_instance
from apps.material_catalog.colors import color_metadata
from apps.material_catalog.models import MaterialAttributeValue, MaterialCatalog
from apps.material_catalog.public_configuration import public_options, require_public_value
from apps.material_catalog.saved_selection import validate_saved_material
from apps.material_catalog.snapshots import material_identity_key
from apps.organizations.models import Employee
from apps.reference_data.models import FabricMaterial, FabricSpecification, FabricWidth, ProductColor, ProductionUnit, TubeCoatingColor


ROOT = "/api/v1/material-catalog/"


class MaterialColorIdentityTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="color_identity_admin", password="ColorIdentity123!", email="")
        employee = Employee.objects.create(user=self.user, employee_code="COLOR_ID_ADMIN", display_name="颜色身份测试")
        self.client.force_authenticate(self.user)
        self.request = SimpleNamespace(user=self.user, employee=employee, META={}, headers={})
        self.catalog = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="颜色身份面料")
        self.first = ProductColor.objects.create(color_card="卡A", color_code="01", color_name="身份测试红")
        self.second = ProductColor.objects.create(color_card="卡B", color_code="02", color_name=self.first.color_name)
        self.unit = ProductionUnit.objects.create(unit_code="COLOR-ID-M", unit_name="颜色测试米")
        self.material = FabricMaterial.objects.create(material_name="颜色测试材质")
        self.specification = FabricSpecification.objects.create(specification_name="颜色测试规格")
        self.width = FabricWidth.objects.create(width_value="颜色测试门幅")

    def row(self, color=None, **changes):
        data = {"id": str(uuid4()), "scope": "BASE", "field_key": "color", "parent_id": None,
                "value": color.color_name if color else "新颜色", **(color_metadata(color) if color else {})}
        data.update(changes)
        return data

    def save(self, rows, *, etag=None, units=None):
        self.catalog.refresh_from_db()
        return self.client.put(f"{ROOT}{self.catalog.pk}/", {
            "name": self.catalog.name, "spray_enabled": False, "base_warehouse_id": None, "semi_warehouse_id": None,
            "values": rows, "units": units or [],
        }, format="json", HTTP_IF_MATCH=etag or etag_for_instance(self.catalog))

    def selection(self, color):
        self.catalog.refresh_from_db()
        return {"catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                "attributes": {"material": self.material.material_name, "fabric_spec": self.specification.specification_name,
                               "width": self.width.width_value, "color": color.color_name},
                "unit_id": str(self.unit.pk), **color_metadata(color)}

    def select(self, selection, *, old=None, persist=True, request=None):
        line = SimpleNamespace(section=SimpleNamespace(title="面料类", section_type="FABRIC"), raw_values={})
        with transaction.atomic():
            apply_catalog_selection(line, {"material_catalog_id": str(self.catalog.pk), "material_selection": selection},
                                    old=old, request=request or self.request, persist=persist, versions={}, allow_public_creation=False)
        return line

    def test_public_candidates_and_catalog_keep_same_name_different_cards(self):
        rows = [row for row in public_options("FABRIC", "FABRIC", "BASE")["values"]
                if row["field_key"] == "color" and row["value"] == self.first.color_name]
        self.assertEqual({row["product_color_id"] for row in rows}, {str(self.first.pk), str(self.second.pk)})
        self.assertEqual({row["color_card"] for row in rows}, {"卡A", "卡B"})
        response = self.save([self.row(self.first), self.row(self.second)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["values"]), 2)
        self.assertEqual(set(self.catalog.attribute_values.values_list("product_color_id", flat=True)), {self.first.pk, self.second.pk})
        other = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="未使用颜色的面料")
        self.assertFalse(other.attribute_values.exists())

    def test_new_metadata_saves_and_failed_draft_rolls_back_public_usage_unit_and_audit(self):
        new = self.row(value="新三字段红", product_color_id=None, color_card="新卡", color_code="N1", color_name="新三字段红")
        before = (ProductColor.objects.count(), ProductionUnit.objects.count(), AuditLog.objects.count())
        with patch("apps.material_catalog.services.write_audit_log", side_effect=RuntimeError("color audit failed")):
            with self.assertRaisesRegex(RuntimeError, "color audit failed"):
                self.save([new], units=[{"id": str(uuid4()), "scope": "BASE", "unit_name": "颜色回滚单位"}])
        self.assertEqual((ProductColor.objects.count(), ProductionUnit.objects.count(), AuditLog.objects.count()), before)
        self.assertFalse(self.catalog.attribute_values.exists())
        response = self.save([new])
        self.assertEqual(response.status_code, 200, response.data)
        saved = response.data["data"]["values"][0]
        self.assertTrue(saved["product_color_id"])
        self.assertEqual((saved["color_card"], saved["color_code"], saved["color_name"]), ("新卡", "N1", "新三字段红"))

    def test_edit_rebinds_usage_without_changing_global_color_and_requires_etag(self):
        first = self.save([self.row(self.first)])
        self.assertEqual(first.status_code, 200, first.data)
        row = first.data["data"]["values"][0]
        row.update(product_color_id=None, color_card="更换卡", color_code="更换号")
        changed = self.save([row], etag=first["ETag"])
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertNotEqual(changed.data["data"]["values"][0]["product_color_id"], str(self.first.pk))
        self.first.refresh_from_db()
        self.assertEqual((self.first.color_card, self.first.color_code), ("卡A", "01"))
        self.assertEqual(self.save([row], etag=first["ETag"]).status_code, 412)

    def test_legacy_unbound_color_remains_unbound_without_guessing_card(self):
        legacy = MaterialAttributeValue.objects.create(catalog=self.catalog, scope="BASE", field_key="color", value=self.first.color_name)
        detail = self.client.get(f"{ROOT}{self.catalog.pk}/")
        row = detail.data["data"]["values"][0]
        self.assertIsNone(row["product_color_id"])
        self.assertEqual((row["color_card"], row["color_code"]), ("", ""))
        count = ProductColor.objects.count()
        self.assertEqual(self.save([row]).status_code, 200)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.product_color_id)
        self.assertEqual(ProductColor.objects.count(), count)
        with self.assertRaises(ValidationError):
            require_public_value(self.catalog, "BASE", "color", self.first.color_name)

    def test_inactive_color_is_preserved_only_for_unchanged_usage_and_history(self):
        response = self.save([self.row(self.first)])
        self.assertEqual(response.status_code, 200, response.data)
        line = self.select(self.selection(self.first))
        snapshot = deepcopy(line.material_selection_snapshot)
        self.first.status = "INACTIVE"
        self.first.save(update_fields=["status"])
        self.assertEqual(self.save(response.data["data"]["values"]).status_code, 200)
        self.assertEqual(self.save([self.row(self.first)]).status_code, 400)
        with self.assertRaises(ValidationError):
            self.select(self.selection(self.first))
        self.assertEqual(self.select(self.selection(self.first), old=line).material_selection_snapshot, snapshot)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, "INACTIVE")

    def test_bom_reselection_changes_identity_and_freezes_all_color_fields(self):
        user = get_user_model().objects.create_user(username="color_identity_bom_editor")
        employee = Employee.objects.create(user=user, employee_code="COLOR_ID_EDITOR", display_name="颜色选料员")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_catalog", codename="view_materialcatalog"))
        user.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="change_bom"))
        request = SimpleNamespace(user=user, employee=employee, META={}, headers={})
        self.assertFalse(user.has_perm("material_catalog.change_materialcatalog"))
        first = self.select(self.selection(self.first), request=request)
        old_snapshot = deepcopy(first.material_selection_snapshot)
        second = self.select(self.selection(self.second), old=first, request=request)
        snapshot = second.material_selection_snapshot
        self.assertEqual({key: snapshot[key] for key in color_metadata(self.second)}, color_metadata(self.second))
        self.assertEqual((second.raw_values["fabric_color_card"], second.raw_values["fabric_color_code"]), ("卡B", "02"))
        self.assertNotEqual(material_identity_key(old_snapshot), material_identity_key(snapshot))
        self.assertEqual(first.material_selection_snapshot, old_snapshot)
        self.assertEqual(validate_saved_material(snapshot), snapshot)
        preview = self.select(self.selection(self.second), persist=False)
        self.assertEqual(preview.material_selection_snapshot["product_color_id"], str(self.second.pk))

    def test_invalid_color_id_metadata_or_new_color_cannot_write_bom(self):
        before = (ProductColor.objects.count(), self.catalog.attribute_values.count(), AuditLog.objects.count())
        invalid = [dict(product_color_id=str(uuid4())), dict(color_card="伪造卡"),
                   dict(product_color_id=None, color_card="BOM不能新增的卡", color_code="NEW")]
        for changes in invalid:
            for persist in (False, True):
                with self.subTest(changes=changes, persist=persist):
                    selection = {**self.selection(self.first), **changes}
                    with self.assertRaises(ValidationError):
                        self.select(selection, persist=persist)
                    self.assertEqual((ProductColor.objects.count(), self.catalog.attribute_values.count(), AuditLog.objects.count()), before)
        serializer = BomCatalogSelectionSerializer(data={**self.selection(self.first), "product_color_id": "invalid"})
        self.assertFalse(serializer.is_valid())

    def test_old_snapshot_hash_and_unedited_snapshot_stay_exactly_compatible(self):
        line = self.select(self.selection(self.first))
        old = deepcopy(line.material_selection_snapshot)
        for field in color_metadata(self.first):
            old.pop(field)
        content = {key: old[key] for key in ("catalog_id", "processing_state", "processing_stage", "completed_craft", "semi_kind", "attributes", "unit_id")}
        expected = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(material_identity_key(old), expected)
        self.assertEqual(validate_saved_material(old), old)
        line.material_selection_snapshot = old
        preserved = self.select(None, old=line)
        self.assertEqual(preserved.material_selection_snapshot, old)
        self.assertNotIn("product_color_id", preserved.material_selection_snapshot)

    def test_spray_source_and_old_empty_card_creation_are_unchanged(self):
        spray = TubeCoatingColor.objects.create(color_name=self.first.color_name)
        rows = [row for row in public_options("TUBE", "TUBE", "SPRAY")["values"] if row["field_key"] == "color" and row["value"] == spray.color_name]
        self.assertEqual(rows[0]["id"], str(spray.pk))
        self.assertNotIn("product_color_id", rows[0])
        response = self.save([self.row(value="空卡空号色")])
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"]["values"][0]
        self.assertEqual((row["color_card"], row["color_code"], row["color_name"]), ("", "", "空卡空号色"))
