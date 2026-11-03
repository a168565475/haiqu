import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.catalog_selection import apply_catalog_selection
from apps.core.api.concurrency import etag_for_instance
from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
from apps.material_catalog.public_configuration import ensure_public_value, public_options
from apps.organizations.models import Employee
from apps.reference_data.models import (
    MaterialAttributePublicValue, ProductColor, ProductionUnit, TubeDiameter, TubeMaterial, TubeShape, TubeShapeDimension,
)


ROOT = "/api/v1/material-catalog/"
PUBLIC = "/api/v1/reference-data/material-attribute-values/"


class PublicMaterialOptionsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="public_config_admin", password="PublicConfigTest123!", email="")
        self.employee = Employee.objects.create(user=self.user, employee_code="PUBLIC_CONFIG_ADMIN", display_name="公共配置测试")
        self.client.force_authenticate(self.user)
        self.request = SimpleNamespace(user=self.user, employee=self.employee, META={}, headers={})
        self.catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="公共测试五金")

    def value(self, key, value, **extra):
        return {"id": str(uuid4()), "scope": "BASE", "field_key": key, "value": value, "parent_id": None, **extra}

    def payload(self, values, units=None):
        return {"name": self.catalog.name, "spray_enabled": False, "base_warehouse_id": None,
                "semi_warehouse_id": None, "values": values, "units": units or []}

    def save(self, payload, etag=None):
        return self.client.put(f"{ROOT}{self.catalog.pk}/", payload, format="json",
                               HTTP_IF_MATCH=etag or etag_for_instance(self.catalog))

    def test_catalog_save_publishes_shared_candidates_without_copying_other_catalog(self):
        response = self.save(self.payload([self.value("specification", "公共规格-A"), self.value("color", "公共无卡颜色")]))
        self.assertEqual(response.status_code, 200, response.data)
        second = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="另一五金")
        result = self.client.get(ROOT + "public-options/", {"category_key": "HARDWARE", "template_key": "HARDWARE", "scope": "BASE"})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertIn("公共规格-A", [row["value"] for row in result.data["data"]["values"]])
        self.assertFalse(second.attribute_values.exists())
        self.assertTrue(ProductColor.objects.filter(color_name="公共无卡颜色", color_card="", color_code="").exists())

    def test_shape_dimensions_keep_relation_and_project_unbound_legacy_diameters(self):
        first = TubeShape.objects.create(shape_name="公共测试形状甲")
        second = TubeShape.objects.create(shape_name="公共测试形状乙")
        bound = TubeDiameter.objects.create(diameter_value="公共关系尺寸")
        unbound = TubeDiameter.objects.create(diameter_value="公共通用尺寸")
        relation = TubeShapeDimension.objects.create(shape=first, diameter=bound)
        rows = public_options("TUBE", "TUBE", "BASE")["values"]
        pairs = {(row["value"], row["parent_id"]) for row in rows if row["field_key"] == "section_size"}
        self.assertIn((bound.diameter_value, str(first.pk)), pairs)
        self.assertNotIn((bound.diameter_value, str(second.pk)), pairs)
        self.assertTrue({(unbound.diameter_value, str(first.pk)), (unbound.diameter_value, str(second.pk))} <= pairs)
        relation.status = "INACTIVE"
        relation.save(update_fields=["status"])
        self.assertFalse(any(row["value"] == bound.diameter_value for row in public_options("TUBE", "TUBE", "BASE")["values"]))

    def test_audit_failure_rolls_back_public_values_units_and_catalog(self):
        original_version = self.catalog.updated_at
        audit_count = AuditLog.objects.count()
        payload = self.payload([self.value("specification", "必须回滚公共规格")], [{"id": str(uuid4()), "scope": "BASE", "unit_name": "回滚单位"}])
        with patch("apps.material_catalog.services.write_audit_log", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.save(payload)
        self.catalog.refresh_from_db()
        self.assertEqual(self.catalog.updated_at, original_version)
        self.assertFalse(self.catalog.attribute_values.exists())
        self.assertFalse(ProductionUnit.objects.filter(unit_name="回滚单位").exists())
        self.assertFalse(MaterialAttributePublicValue.objects.filter(value="必须回滚公共规格").exists())
        self.assertEqual(AuditLog.objects.count(), audit_count)

    def test_shape_rename_publishes_unchanged_dimension_under_new_shape(self):
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="形状改名管材")
        shape = self.value("shape", "改名前形状")
        size = self.value("section_size", "改名测试尺寸", parent_id=shape["id"])
        payload = self.payload([shape, size])
        first = self.save(payload)
        self.assertEqual(first.status_code, 200, first.data)
        shape["value"] = "改名后形状"
        second = self.save(payload, etag=first["ETag"])
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(TubeShapeDimension.objects.filter(
            shape__shape_name="改名后形状", diameter__diameter_value="改名测试尺寸",
        ).exists())

    def test_inactive_public_value_is_not_revived_and_unchanged_catalog_can_save(self):
        public = MaterialAttributePublicValue.objects.create(category_key="HARDWARE", template_key="HARDWARE", scope="BASE", field_key="specification", value="已停用规格", status="INACTIVE")
        response = self.save(self.payload([self.value("specification", public.value)]))
        self.assertEqual(response.status_code, 400, response.data)
        stored = MaterialAttributeValue.objects.create(catalog=self.catalog, scope="BASE", field_key="specification", value=public.value)
        unit = ProductionUnit.objects.create(unit_code="PUB-INACTIVE", unit_name="停用历史单位", status="INACTIVE")
        allowed = MaterialAllowedUnit.objects.create(catalog=self.catalog, scope="BASE", unit=unit)
        response = self.save(self.payload([self.value("specification", public.value, id=str(stored.pk))], [{"id": str(allowed.pk), "scope": "BASE", "unit_name": unit.unit_name}]))
        self.assertEqual(response.status_code, 200, response.data)
        public.refresh_from_db()
        unit.refresh_from_db()
        self.assertEqual(public.status, "INACTIVE")
        self.assertEqual(unit.status, "INACTIVE")

    def test_bom_existing_public_selection_needs_no_catalog_maintenance_permission(self):
        user = get_user_model().objects.create_user(username="public_bom_editor")
        employee = Employee.objects.create(user=user, employee_code="PUBLIC_BOM_EDITOR", display_name="公共选料编辑员")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_catalog", codename="view_materialcatalog"))
        user.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="change_bom"))
        self.assertTrue(user.has_perm("material_catalog.view_materialcatalog"))
        self.assertFalse(user.has_perm("material_catalog.change_materialcatalog"))
        request = SimpleNamespace(user=user, employee=employee, META={}, headers={})
        public = MaterialAttributePublicValue.objects.create(category_key="HARDWARE", template_key="HARDWARE", scope="BASE", field_key="specification", value="已有公共规格")
        unit = ProductionUnit.objects.create(unit_code="PUB-READ", unit_name="公共已有单位")
        data = {"material_catalog_id": str(self.catalog.pk), "material_selection": {
            "scope": "BASE", "catalog_version": self.catalog.updated_at.isoformat(), "processing_state": "RAW",
            "attributes": {"specification": public.value}, "unit_id": str(unit.pk),
        }}
        line = SimpleNamespace(section=SimpleNamespace(title="五金件", section_type="OTHER"), raw_values={})
        with transaction.atomic():
            apply_catalog_selection(line, data, old=None, request=request, persist=True, versions={}, allow_public_creation=False)
        self.assertEqual(line.material_selection_snapshot["attributes"]["specification"], public.value)
        self.assertTrue(self.catalog.attribute_values.filter(value=public.value).exists())
        self.assertTrue(self.catalog.allowed_units.filter(unit=unit).exists())
        with self.assertRaises(PermissionDenied):
            ensure_public_value(self.catalog, "BASE", "specification", "无权创建的全新公共值", request=request, persist=False)

    def test_bom_rejects_missing_public_values_without_creating_usage(self):
        data = {"material_catalog_id": str(self.catalog.pk), "material_quantity": "1", "material_selection": {
            "scope": "BASE", "catalog_version": self.catalog.updated_at.isoformat(), "processing_state": "RAW",
            "attributes": {"specification": "BOM失败新规格"}, "unit_name": "BOM失败新单位",
        }}
        line = SimpleNamespace(section=SimpleNamespace(title="五金件", section_type="OTHER"), raw_values={})
        with self.assertRaises(ValidationError), transaction.atomic():
            apply_catalog_selection(line, data, old=None, request=self.request, persist=True, versions={}, allow_public_creation=False)
        self.assertFalse(MaterialAttributePublicValue.objects.filter(value="BOM失败新规格").exists())
        self.assertFalse(ProductionUnit.objects.filter(unit_name="BOM失败新单位").exists())
        self.assertFalse(self.catalog.attribute_values.exists())

    def test_extract_dry_run_apply_is_idempotent_and_reports_conflicts(self):
        MaterialAttributeValue.objects.create(catalog=self.catalog, scope="BASE", field_key="specification", value="提取公共规格")
        tube = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="提取管材")
        MaterialAttributeValue.objects.create(catalog=tube, scope="BASE", field_key="material", value="长" * 151)
        before = self.catalog.updated_at
        output = StringIO()
        call_command("extract_public_material_configuration", "--dry-run", stdout=output)
        self.assertGreaterEqual(json.loads(output.getvalue())["counts"]["conflicts"], 1)
        self.assertFalse(MaterialAttributePublicValue.objects.filter(value="提取公共规格").exists())
        call_command("extract_public_material_configuration", "--apply", stdout=StringIO())
        after_first = AuditLog.objects.count()
        call_command("extract_public_material_configuration", "--apply", stdout=StringIO())
        self.assertEqual(AuditLog.objects.count(), after_first)
        self.assertEqual(MaterialAttributePublicValue.objects.filter(value="提取公共规格").count(), 1)
        self.assertFalse(TubeMaterial.objects.filter(material_name="长" * 151).exists())
        self.catalog.refresh_from_db()
        self.assertEqual(self.catalog.updated_at, before)

    def test_maintenance_permissions_and_etag(self):
        created = self.client.post(PUBLIC, {"category_key": "HARDWARE", "template_key": "HARDWARE", "scope": "BASE", "field_key": "thread", "value": "公共螺纹"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        url = PUBLIC + created.data["data"]["id"] + "/"
        self.assertEqual(self.client.patch(url, {"value": "更新螺纹"}, format="json").status_code, 428)
        self.assertEqual(self.client.patch(url, {"value": "更新螺纹"}, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        changed = self.client.patch(url, {"value": "更新螺纹"}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(changed.status_code, 200, changed.data)
        inactive = self.client.post(url + "deactivate/", {"reason": "定向检查"}, format="json", HTTP_IF_MATCH=changed["ETag"])
        self.assertEqual(inactive.status_code, 200, inactive.data)
        viewer = get_user_model().objects.create_user(username="public_viewer")
        Employee.objects.create(user=viewer, employee_code="PUBLIC_VIEW", display_name="查看员")
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="reference_data", codename="view_tubematerial"))
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(ROOT + "public-fields/").status_code, 200)
        self.assertEqual(self.client.get(ROOT + "public-tube-options/").status_code, 200)
        self.assertEqual(self.client.post(PUBLIC, {"value": "不应写入"}, format="json").status_code, 403)
