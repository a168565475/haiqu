from copy import deepcopy
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.models import Warehouse
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit
from apps.material_catalog.models import MaterialCatalog, MaterialAllowedUnit
from apps.material_catalog.snapshots import build_material_snapshot, material_identity_key
from . import test_material_catalog_api as catalog_api

ROOT = catalog_api.ROOT


class U1ContractTests(TestCase):
    setUp = catalog_api.MaterialCatalogApiTests.setUp
    create_catalog = catalog_api.MaterialCatalogApiTests.create_catalog
    write = catalog_api.MaterialCatalogApiTests.write
    add_value = catalog_api.MaterialCatalogApiTests.add_value
    assert_write = catalog_api.MaterialCatalogApiTests.assert_write

    def warehouse(self, number, warehouse_type="MATERIAL", status="ACTIVE"):
        return Warehouse.objects.create(warehouse_number=number, warehouse_name=number, warehouse_type=warehouse_type, status=status)

    def test_separate_warehouses_roundtrip_and_switch_off_preserves_semi(self):
        base = self.warehouse("U1-RAW")
        semi = self.warehouse("U1-SEMI", "SEMI_FINISHED")
        current = self.create_catalog()
        current = self.assert_write(self.write(current, "patch", payload={"base_warehouse_id": str(base.pk), "semi_warehouse_id": str(semi.pk), "spray_enabled": True}))
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "SPRAY", "unit_name": "U1加工单位"}))
        old = deepcopy(current.data["data"])
        current = self.assert_write(self.write(current, "patch", payload={"spray_enabled": False}))
        detail = self.client.get(f"{ROOT}{current.data['data']['id']}/").data["data"]
        self.assertEqual(detail["semi_warehouse_id"], str(semi.pk))
        self.assertEqual(detail["base_warehouse_id"], str(base.pk))
        self.assertEqual(detail["units"], old["units"])
        self.assertEqual(detail["values"], old["values"])
        current = self.assert_write(self.write(current, "patch", payload={"base_warehouse_id": None}))
        self.assertIsNone(current.data["data"]["base_warehouse_id"])
        self.assertEqual(Warehouse.objects.count(), 2)

    def test_invalid_warehouse_patch_is_atomic_and_etag_checked(self):
        inactive = self.warehouse("U1-OFF", status="DISABLED")
        current = self.create_catalog()
        for identifier in (str(inactive.pk), str(uuid4()), "invalid"):
            response = self.write(current, "patch", payload={"spray_enabled": True, "base_warehouse_id": identifier})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(MaterialCatalog.objects.get(pk=current.data["data"]["id"]).spray_enabled)
        updated = self.assert_write(self.write(current, "patch", payload={"spray_enabled": True}))
        self.assertEqual(self.write(current, "patch", payload={"base_warehouse_id": None}).status_code, 412)
        self.assertNotEqual(updated["ETag"], current["ETag"])

    def test_warehouse_choices_are_minimal_and_follow_catalog_read_permission(self):
        warehouse = self.warehouse("U1-READ")
        self.warehouse("U1-OFF", status="DISABLED")
        user = get_user_model().objects.create_user(username="u1-reader")
        Employee.objects.create(user=user, employee_code="U1-READER", display_name="U1只读测试员")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(ROOT + "options/").status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_materialcatalog"))
        user = get_user_model().objects.get(pk=user.pk)
        self.client.force_authenticate(user)
        response = self.client.get(ROOT + "options/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["warehouses"], [{"id": str(warehouse.pk), "warehouse_number": "U1-READ", "warehouse_name": "U1-READ", "warehouse_type": "MATERIAL"}])
        self.assertEqual(response.data["data"]["units"], [])
        self.assertEqual(self.client.get("/api/v1/warehouses/").status_code, 403)

    def test_input_units_reuse_ids_without_sharing_candidates_or_duplicate_rows(self):
        a = self.create_catalog(name="U1品名A")
        b = self.create_catalog(name="U1品名B")
        a = self.assert_write(self.write(a, "post", "units/", {"scope": "BASE", "unit_name": " U1独立单位 "}))
        unit = a.data["data"]["units"][0]
        self.assertEqual(ProductionUnit.objects.filter(unit_name="U1独立单位").count(), 1)
        self.assertEqual(self.client.get(f"{ROOT}{b.data['data']['id']}/").data["data"]["units"], [])
        self.assertEqual(self.write(a, "post", "units/", {"scope": "BASE", "unit_name": "U1独立单位"}).status_code, 400)
        self.assertEqual(MaterialAllowedUnit.objects.filter(catalog_id=a.data["data"]["id"]).count(), 1)
        b = self.assert_write(self.write(b, "post", "units/", {"scope": "BASE", "unit_name": "U1独立单位"}))
        self.assertEqual(b.data["data"]["units"][0]["unit_id"], unit["unit_id"])
        a = self.assert_write(self.write(a, "patch", f"units/{unit['id']}/", {"unit_name": "U1新单位"}))
        self.assertEqual(a.data["data"]["units"][0]["id"], unit["id"])
        self.assertEqual(b.data["data"]["units"][0]["unit_name"], "U1独立单位")

    def test_unit_xor_validation_and_inactive_units_not_restored(self):
        current = self.create_catalog()
        unit = ProductionUnit.objects.create(unit_code="U1-OFF", unit_name="U1停用单位", status="INACTIVE")
        for data in ({}, {"unit_name": " "}, {"unit_name": "a" * 81}, {"unit_name": "U1停用单位"}, {"unit_id": str(unit.pk), "unit_name": "新单位"}):
            self.assertEqual(self.write(current, "post", "units/", {"scope": "BASE", **data}).status_code, 400)
        unit.refresh_from_db()
        self.assertEqual(unit.status, "INACTIVE")

    def test_snapshot_shape_ownership_freeze_and_identity_dimensions(self):
        a = self.create_catalog()
        a = self.assert_write(self.add_value(a, field="shape", value="圆管"))
        shape = next(row for row in a.data["data"]["values"] if row["field_key"] == "shape")
        a = self.assert_write(self.add_value(a, field="section_size", value="Φ25×1.2", parent_id=shape["id"]))
        a = self.assert_write(self.write(a, "post", "units/", {"scope": "BASE", "unit_name": "U1根"}))
        catalog = MaterialCatalog.objects.get(pk=a.data["data"]["id"])
        snapshot = build_material_snapshot(catalog=catalog, scope="BASE", processing_state="RAW", required_fields=("shape", "section_size"), attributes={"shape": "圆管", "section_size": "Φ25×1.2"}, unit_id=a.data["data"]["units"][0]["unit_id"])
        frozen = deepcopy(snapshot)
        a = self.assert_write(self.write(a, "patch", f"values/{shape['id']}/", {"value": "改名圆管"}))
        self.assertEqual(snapshot, frozen)
        key = material_identity_key(snapshot)
        for field, value in (("processing_stage", "CUTTING"), ("processing_state", "PROCESSED"), ("unit_id", str(uuid4())), ("attributes", {"shape": "圆管", "section_size": "Φ32×1.2"})):
            self.assertNotEqual(key, material_identity_key({**snapshot, field: value}))
        self.assertEqual(key, material_identity_key({**snapshot, "catalog_version": "other", "display_name": "other"}))
        with self.assertRaises(ValidationError):
            build_material_snapshot(catalog=catalog, scope="BASE", processing_state="RAW", required_fields=("shape", "section_size"), attributes={"section_size": "Φ25×1.2"}, unit_id=snapshot["unit_id"])

    def test_empty_or_incomplete_snapshot_is_rejected_by_entry_requirements(self):
        current = self.create_catalog()
        catalog = MaterialCatalog.objects.get(pk=current.data["data"]["id"])
        for attributes in ({}, {"color": "无颜色"}):
            with self.assertRaises(ValidationError):
                build_material_snapshot(catalog=catalog, scope="BASE", processing_state="RAW", attributes=attributes, unit_id=str(uuid4()), required_fields=("material", "shape", "section_size", "thickness", "length"))

    def test_base_group_metal_result_and_direct_cutting_warehouse(self):
        warehouse = self.warehouse("U1-RESULT", "SEMI_FINISHED")
        current = self.create_catalog()
        current = self.assert_write(self.write(current, "patch", payload={"semi_warehouse_id": str(warehouse.pk)}))
        self.assertFalse(current.data["data"]["spray_enabled"])
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_name": "U1加工结果单位"}))
        catalog = MaterialCatalog.objects.get(pk=current.data["data"]["id"])
        arguments = dict(catalog=catalog, scope="BASE", attributes={"color": "无颜色"}, unit_id=current.data["data"]["units"][0]["unit_id"], required_fields=("color",))
        craft = {"id": str(uuid4()), "craft_type": "INTERNAL", "code": "METAL"}
        result = build_material_snapshot(**arguments, processing_state="PROCESSED", completed_craft=craft, semi_kind="PIPE")
        self.assertEqual((result["scope"], result["processing_stage"], result["processing_state"]), ("BASE", "METAL", "PROCESSED"))
        with self.assertRaises(ValidationError):
            build_material_snapshot(**arguments, processing_state="RAW", completed_craft=craft, semi_kind="PIPE")
        cutting = self.create_catalog(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")
        cutting = self.assert_write(self.write(cutting, "patch", payload={"semi_warehouse_id": str(warehouse.pk)}))
        self.assertEqual(cutting.data["data"]["semi_warehouse_id"], str(warehouse.pk))
        self.assertIsNone(cutting.data["data"]["base_warehouse_id"])
