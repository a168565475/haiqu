from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import FabricMaterial, FabricSpecification, FabricWidth


class FabricDataApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="fabric_data_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="FABRIC_DATA_ADMIN",
            display_name="面料资料管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="reference_data")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_seed_counts_values_search_and_summary(self):
        self.assertEqual(FabricMaterial.objects.count(), 7)
        self.assertEqual(FabricSpecification.objects.count(), 16)
        self.assertEqual(FabricWidth.objects.count(), 8)
        self.assertEqual(
            list(FabricMaterial.objects.values_list("material_name", flat=True)),
            ["加密尼龙", "PU涂层", "PVC耐高温", "PU", "/", "PVC", "PE"],
        )
        self.assertEqual(
            list(FabricWidth.objects.values_list("width_value", flat=True)),
            ["1.7", "1.58", "1.52", "1.72", "1.75", "1.6", "1.5", "1.1"],
        )

        summary = self.client.get("/api/v1/reference-data/production-data-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["category_counts"]["fabric_materials"], 7)
        self.assertEqual(summary.data["data"]["category_counts"]["fabric_specifications"], 16)
        self.assertEqual(summary.data["data"]["category_counts"]["fabric_widths"], 8)

        filtered = self.client.get("/api/v1/reference-data/fabric-specifications/?q=特斯林")
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["meta"]["total"], 2)

    def test_create_unique_etag_status_and_no_physical_delete(self):
        inventory_material = RawMaterialInformation.objects.filter(
            item_type="MATERIAL", archived_at__isnull=True
        ).first()
        self.assertIsNotNone(inventory_material)
        created = self.client.post(
            "/api/v1/reference-data/fabric-materials/",
            {
                "material_name": "自动化测试面料",
                "inventory_raw_material": str(inventory_material.pk),
                "sort_order": 99,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(str(created.data["data"]["inventory_raw_material"]), str(inventory_material.pk))
        self.assertEqual(
            created.data["data"]["inventory_material_number"], inventory_material.material_number
        )
        material_id = created.data["data"]["id"]

        duplicate = self.client.post(
            "/api/v1/reference-data/fabric-materials/",
            {"material_name": "自动化测试面料", "sort_order": 100},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

        updated = self.client.patch(
            f"/api/v1/reference-data/fabric-materials/{material_id}/",
            {"description": "面料更新测试"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        stale = self.client.patch(
            f"/api/v1/reference-data/fabric-materials/{material_id}/",
            {"description": "过期写入"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        deactivated = self.client.post(
            f"/api/v1/reference-data/fabric-materials/{material_id}/deactivate/",
            {"reason": "测试停用"},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.data)
        self.assertEqual(deactivated.data["data"]["status"], "INACTIVE")
        self.assertEqual(
            self.client.delete(f"/api/v1/reference-data/fabric-materials/{material_id}/").status_code,
            405,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="FABRIC_MATERIAL",
                object_id=material_id,
                action="DEACTIVATED",
            ).exists()
        )

    def test_fabric_mapping_rejects_semi_finished_inventory_item(self):
        semi_finished = RawMaterialInformation.objects.filter(
            item_type="SEMI_FINISHED", archived_at__isnull=True
        ).first()
        self.assertIsNotNone(semi_finished)
        response = self.client.post(
            "/api/v1/reference-data/fabric-materials/",
            {
                "material_name": "错误映射到半成品",
                "inventory_raw_material": str(semi_finished.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_permissions_are_isolated_between_fabric_settings(self):
        limited_user = get_user_model().objects.create_user(username="fabric_material_viewer")
        Employee.objects.create(
            user=limited_user,
            employee_code="FABRIC_MATERIAL_VIEWER",
            display_name="材质只读用户",
        )
        limited_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reference_data",
                codename="view_fabricmaterial",
            )
        )
        limited_client = APIClient()
        limited_client.force_authenticate(limited_user)

        self.assertEqual(
            limited_client.get("/api/v1/reference-data/production-data-summary/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/fabric-materials/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/fabric-specifications/").status_code,
            403,
        )
        self.assertEqual(
            limited_client.post(
                "/api/v1/reference-data/fabric-materials/",
                {"material_name": "无权新增"},
                format="json",
            ).status_code,
            403,
        )
