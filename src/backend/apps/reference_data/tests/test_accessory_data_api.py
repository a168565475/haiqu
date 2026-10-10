from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
)


class AccessoryDataApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="accessory_data_admin")
        Employee.objects.create(
            user=self.user,
            employee_code="ACCESSORY_DATA_ADMIN",
            display_name="辅料资料管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="reference_data")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_seed_counts_relations_supplemental_names_and_summary(self):
        self.assertEqual(AccessoryProductName.objects.count(), 148)
        self.assertEqual(AccessorySpecification.objects.count(), 349)
        self.assertEqual(AccessoryColor.objects.count(), 284)
        self.assertEqual(AccessoryMaterial.objects.count(), 27)
        self.assertEqual(
            AccessoryProductName.objects.filter(
                description="来源：辅料品名维护_20260831105443.xlsx"
            ).count(),
            112,
        )
        self.assertEqual(
            AccessoryProductName.objects.filter(
                description="由辅料规格/颜色表关联补充；单位待维护。",
                unit_name="",
            ).count(),
            36,
        )
        self.assertFalse(AccessorySpecification.objects.filter(product_name__isnull=True).exists())
        self.assertFalse(AccessoryColor.objects.filter(product_name__isnull=True).exists())
        self.assertTrue(
            AccessorySpecification.objects.filter(
                product_name__product_name="喷胶棉",
                specification_value="133*69*2.5",
                weight="120",
            ).exists()
        )
        self.assertTrue(
            AccessoryColor.objects.filter(
                product_name__product_name="M5螺帽",
                color_name="镀蓝白锌",
            ).exists()
        )

        summary = self.client.get("/api/v1/reference-data/production-data-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        counts = summary.data["data"]["category_counts"]
        self.assertEqual(counts["accessory_product_names"], 148)
        self.assertEqual(counts["accessory_specifications"], 349)
        self.assertEqual(counts["accessory_colors"], 284)
        self.assertEqual(counts["accessory_materials"], 27)

        filtered = self.client.get("/api/v1/reference-data/accessory-specifications/?q=喷胶棉")
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertGreater(filtered.data["meta"]["total"], 1)

    def test_relation_unique_etag_archive_protection_status_audit_and_no_delete(self):
        name_response = self.client.post(
            "/api/v1/reference-data/accessory-product-names/",
            {"product_name": "自动化测试辅料", "unit_name": "个", "sort_order": 999},
            format="json",
        )
        self.assertEqual(name_response.status_code, 201, name_response.data)
        product_name_id = name_response.data["data"]["id"]

        created = self.client.post(
            "/api/v1/reference-data/accessory-specifications/",
            {
                "product_name": product_name_id,
                "specification_value": "测试规格",
                "weight": "10g",
                "sort_order": 999,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        specification_id = created.data["data"]["id"]
        self.assertEqual(created.data["data"]["product_name_label"], "自动化测试辅料")

        duplicate = self.client.post(
            "/api/v1/reference-data/accessory-specifications/",
            {
                "product_name": product_name_id,
                "specification_value": "测试规格",
                "weight": "不同克重",
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

        protected = self.client.post(
            f"/api/v1/reference-data/accessory-product-names/{product_name_id}/archive/",
            {"reason": "测试引用保护"},
            format="json",
            HTTP_IF_MATCH=name_response["ETag"],
        )
        self.assertEqual(protected.status_code, 409, protected.data)

        updated = self.client.patch(
            f"/api/v1/reference-data/accessory-specifications/{specification_id}/",
            {"weight": "11g"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        stale = self.client.patch(
            f"/api/v1/reference-data/accessory-specifications/{specification_id}/",
            {"weight": "过期写入"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        deactivated = self.client.post(
            f"/api/v1/reference-data/accessory-specifications/{specification_id}/deactivate/",
            {"reason": "测试停用"},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.data)
        self.assertEqual(deactivated.data["data"]["status"], "INACTIVE")
        self.assertEqual(
            self.client.delete(
                f"/api/v1/reference-data/accessory-specifications/{specification_id}/"
            ).status_code,
            405,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="ACCESSORY_SPECIFICATION",
                object_id=specification_id,
                action="DEACTIVATED",
            ).exists()
        )

    def test_inactive_name_cannot_be_selected_for_new_relation(self):
        inactive_name = AccessoryProductName.objects.filter(specifications__isnull=True, colors__isnull=True).first()
        if inactive_name is None:
            inactive_name = AccessoryProductName.objects.create(
                product_name="无引用辅料品名",
                unit_name="个",
                status="INACTIVE",
            )
        else:
            inactive_name.status = "INACTIVE"
            inactive_name.save(update_fields=["status", "updated_at"])
        response = self.client.post(
            "/api/v1/reference-data/accessory-colors/",
            {"product_name": str(inactive_name.pk), "color_name": "黑色"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_accessory_material_can_map_to_inventory_raw_material(self):
        inventory_material = RawMaterialInformation.objects.filter(
            item_type="MATERIAL", archived_at__isnull=True
        ).first()
        self.assertIsNotNone(inventory_material)
        response = self.client.post(
            "/api/v1/reference-data/accessory-materials/",
            {
                "material_name": "自动化测试辅料材质",
                "inventory_raw_material": str(inventory_material.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["data"]["inventory_raw_material"]), str(inventory_material.pk))
        self.assertEqual(response.data["data"]["inventory_material_unit"], inventory_material.unit.unit_name)

    def test_permissions_are_isolated_between_accessory_settings(self):
        limited_user = get_user_model().objects.create_user(username="accessory_name_viewer")
        Employee.objects.create(
            user=limited_user,
            employee_code="ACCESSORY_NAME_VIEWER",
            display_name="辅料品名只读用户",
        )
        limited_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reference_data",
                codename="view_accessoryproductname",
            )
        )
        limited_client = APIClient()
        limited_client.force_authenticate(limited_user)

        self.assertEqual(
            limited_client.get("/api/v1/reference-data/production-data-summary/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/accessory-product-names/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/accessory-specifications/").status_code,
            403,
        )
        self.assertEqual(
            limited_client.post(
                "/api/v1/reference-data/accessory-product-names/",
                {"product_name": "无权新增", "unit_name": "个"},
                format="json",
            ).status_code,
            403,
        )
