from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import (
    TubeCoatingColor,
    TubeDiameter,
    TubeMaterial,
    TubeProductName,
    TubeShape,
    TubeThickness,
)


class TubeDataApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tube_data_admin")
        Employee.objects.create(
            user=self.user,
            employee_code="TUBE_DATA_ADMIN",
            display_name="管材资料管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="reference_data")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_seed_counts_original_values_search_and_summary(self):
        self.assertEqual(TubeProductName.objects.count(), 79)
        self.assertEqual(TubeThickness.objects.count(), 14)
        self.assertEqual(TubeDiameter.objects.count(), 24)
        self.assertEqual(TubeMaterial.objects.count(), 3)
        self.assertEqual(TubeShape.objects.count(), 7)
        self.assertEqual(TubeCoatingColor.objects.count(), 29)
        self.assertEqual(
            list(TubeThickness.objects.values_list("thickness_value", flat=True))[:2],
            ["2.0", "2"],
        )
        self.assertTrue(
            TubeCoatingColor.objects.filter(color_name="Pantone  7771c亮光").exists()
        )
        self.assertTrue(TubeCoatingColor.objects.filter(color_name="/").exists())

        summary = self.client.get("/api/v1/reference-data/production-data-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_product_names"], 79)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_thicknesses"], 14)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_diameters"], 24)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_materials"], 3)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_shapes"], 7)
        self.assertEqual(summary.data["data"]["category_counts"]["tube_coating_colors"], 29)

        filtered = self.client.get("/api/v1/reference-data/tube-product-names/?q=交叉管")
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertGreater(filtered.data["meta"]["total"], 1)

    def test_pinyin_search_is_backfilled_generated_and_read_only(self):
        self.assertFalse(TubeProductName.objects.filter(pinyin_search="").exists())
        self.assertFalse(TubeMaterial.objects.filter(pinyin_search="").exists())
        self.assertFalse(TubeShape.objects.filter(pinyin_search="").exists())

        flat_oval = TubeShape.objects.get(shape_name="扁圆管")
        self.assertIn("bianyuanguan", flat_oval.pinyin_search)
        self.assertIn("byg", flat_oval.pinyin_search)
        self.assertIn("dxingguan", TubeShape.objects.get(shape_name="D形管").pinyin_search)
        self.assertIn("tzg", TubeMaterial.objects.get(material_name="铁-中光").pinyin_search)
        long_tube_pinyin = TubeProductName.objects.get(product_name="扶手长管").pinyin_search
        self.assertIn("fushouchangguan", long_tube_pinyin)
        self.assertIn("fscg", long_tube_pinyin)
        hyphenated_long_tube_pinyin = TubeProductName.objects.get(product_name="中交叉-长管").pinyin_search
        self.assertIn("zhongjiaochachangguan", hyphenated_long_tube_pinyin)
        self.assertIn("zjccg", hyphenated_long_tube_pinyin)
        by_length_initials = self.client.get("/api/v1/reference-data/tube-product-names/?q=FSCG")
        self.assertEqual(by_length_initials.status_code, 200, by_length_initials.data)
        self.assertIn("扶手长管", [item["product_name"] for item in by_length_initials.data["data"]])

        by_initials = self.client.get("/api/v1/reference-data/tube-shapes/?q=BYG")
        self.assertEqual(by_initials.status_code, 200, by_initials.data)
        self.assertIn("扁圆管", [item["shape_name"] for item in by_initials.data["data"]])
        by_full_pinyin = self.client.get("/api/v1/reference-data/tube-shapes/?q=bianyuan")
        self.assertEqual(by_full_pinyin.status_code, 200, by_full_pinyin.data)
        self.assertIn("扁圆管", [item["shape_name"] for item in by_full_pinyin.data["data"]])

        created = self.client.post(
            "/api/v1/reference-data/tube-shapes/",
            {
                "shape_name": "扁圆测试管",
                "pinyin_search": "client-forged-value",
                "sort_order": 999,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertNotIn("client-forged-value", created.data["data"]["pinyin_search"])
        self.assertIn("bianyuanceshiguan", created.data["data"]["pinyin_search"])
        self.assertIn("bycsg", created.data["data"]["pinyin_search"])

        shape_id = created.data["data"]["id"]
        updated = self.client.patch(
            f"/api/v1/reference-data/tube-shapes/{shape_id}/",
            {"shape_name": "方形测试管", "pinyin_search": "still-forged"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertIn("fangxingceshiguan", updated.data["data"]["pinyin_search"])
        self.assertIn("fxcsg", updated.data["data"]["pinyin_search"])
        self.assertNotIn("still-forged", updated.data["data"]["pinyin_search"])

        shape = TubeShape.objects.get(pk=shape_id)
        persisted_name = shape.shape_name
        persisted_pinyin = shape.pinyin_search
        shape.shape_name = "只改内存不落库"
        shape.description = "只保存说明"
        shape.save(update_fields=["description"])
        shape.refresh_from_db()
        self.assertEqual(shape.shape_name, persisted_name)
        self.assertEqual(shape.pinyin_search, persisted_pinyin)

    def test_create_unique_etag_status_audit_and_no_physical_delete(self):
        created = self.client.post(
            "/api/v1/reference-data/tube-shapes/",
            {"shape_name": "自动化测试管形", "sort_order": 99},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        shape_id = created.data["data"]["id"]

        duplicate = self.client.post(
            "/api/v1/reference-data/tube-shapes/",
            {"shape_name": "自动化测试管形", "sort_order": 100},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

        updated = self.client.patch(
            f"/api/v1/reference-data/tube-shapes/{shape_id}/",
            {"description": "管材更新测试"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        stale = self.client.patch(
            f"/api/v1/reference-data/tube-shapes/{shape_id}/",
            {"description": "过期写入"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        deactivated = self.client.post(
            f"/api/v1/reference-data/tube-shapes/{shape_id}/deactivate/",
            {"reason": "测试停用"},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.data)
        self.assertEqual(deactivated.data["data"]["status"], "INACTIVE")
        self.assertEqual(
            self.client.delete(f"/api/v1/reference-data/tube-shapes/{shape_id}/").status_code,
            405,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="TUBE_SHAPE",
                object_id=shape_id,
                action="DEACTIVATED",
            ).exists()
        )

    def test_permissions_are_isolated_between_tube_settings(self):
        limited_user = get_user_model().objects.create_user(username="tube_name_viewer")
        Employee.objects.create(
            user=limited_user,
            employee_code="TUBE_NAME_VIEWER",
            display_name="管材品名只读用户",
        )
        limited_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reference_data",
                codename="view_tubeproductname",
            )
        )
        limited_client = APIClient()
        limited_client.force_authenticate(limited_user)

        self.assertEqual(
            limited_client.get("/api/v1/reference-data/production-data-summary/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/tube-product-names/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/tube-thicknesses/").status_code,
            403,
        )
        self.assertEqual(
            limited_client.post(
                "/api/v1/reference-data/tube-product-names/",
                {"product_name": "无权新增"},
                format="json",
            ).status_code,
            403,
        )
