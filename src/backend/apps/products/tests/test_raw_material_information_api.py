from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Count
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductColor, ProductionUnit


class RawMaterialInformationApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="raw_material_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="RAW_MATERIAL_ADMIN",
            display_name="原料信息管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="products")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def valid_payload(self, suffix="001", *, packaging=False):
        category = ProductCategory.objects.get(
            item_type="MATERIAL",
            category_name="包材" if packaging else "管材",
        )
        unit = ProductionUnit.objects.filter(status="ACTIVE").first()
        color = ProductColor.objects.filter(status="ACTIVE").first()
        return {
            "material_number": f"QA-RAW-{suffix}",
            "item_type": "MATERIAL",
            "category": str(category.pk),
            "material_name": "自动化测试原料",
            "specification": "100*50*30",
            "unit": str(unit.pk),
            "color": str(color.pk),
            "material": "测试材质",
            "is_packaging_auxiliary": packaging,
            "box_shape": "HALF_COVER" if packaging else "",
            "notes": "测试备注",
            "warehouse_number": "CK008",
            "warehouse_name": "包材仓",
        }

    def test_seed_import_is_complete_and_preserves_history(self):
        self.assertEqual(RawMaterialInformation.objects.count(), 4897)
        self.assertEqual(RawMaterialInformation.objects.filter(item_type="MATERIAL").count(), 3137)
        self.assertEqual(RawMaterialInformation.objects.filter(item_type="SEMI_FINISHED").count(), 1760)
        self.assertEqual(RawMaterialInformation.objects.filter(is_packaging_auxiliary=True).count(), 10)
        self.assertEqual(RawMaterialInformation.objects.filter(box_shape="HALF_COVER").count(), 162)
        self.assertEqual(RawMaterialInformation.objects.filter(box_shape="FULL_COVER").count(), 75)
        self.assertEqual(RawMaterialInformation.objects.filter(box_shape="LID_AND_BASE").count(), 1)
        self.assertEqual(RawMaterialInformation.objects.filter(box_shape="DISPLAY_BOX").count(), 1)
        self.assertEqual(
            RawMaterialInformation.objects.values("warehouse_number", "warehouse_name").distinct().count(),
            8,
        )
        self.assertEqual(
            RawMaterialInformation.objects.values("material_number")
            .annotate(record_count=Count("id"))
            .filter(record_count__gt=1)
            .count(),
            26,
        )
        self.assertEqual(
            set(
                RawMaterialInformation.objects.filter(material_number="511741746420")
                .values_list("specification", flat=True)
            ),
            {"16*0.7*6430", "20*28*0.8*6420"},
        )
        self.assertFalse(
            RawMaterialInformation.objects.get(material_number="5000400395").is_packaging_auxiliary
        )
        self.assertTrue(
            RawMaterialInformation.objects.get(material_number="5000400389").is_packaging_auxiliary
        )
        self.assertTrue(
            ProductCategory.objects.filter(
                item_type="SEMI_FINISHED",
                category_name="喷塑五金",
            ).exists()
        )

    def test_list_filters_options_and_search_are_paginated(self):
        category = ProductCategory.objects.get(
            item_type="SEMI_FINISHED",
            category_name="喷塑五金",
        )
        options = self.client.get("/api/v1/raw-materials/options/")
        filtered = self.client.get(
            f"/api/v1/raw-materials/?item_type=SEMI_FINISHED&category_id={category.pk}&page_size=100"
        )
        searched = self.client.get("/api/v1/raw-materials/?q=5000400395")

        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(len(options.data["data"]["units"]), 12)
        self.assertEqual(len(options.data["data"]["colors"]), 324)
        self.assertEqual(len(options.data["data"]["warehouses"]), 8)
        self.assertEqual(len(options.data["data"]["box_shapes"]), 5)
        self.assertTrue(
            any(
                item["item_type"] == "SEMI_FINISHED" and item["category_name"] == "喷塑五金"
                for item in options.data["data"]["categories"]
            )
        )
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertEqual(filtered.data["meta"]["total"], 29)
        self.assertEqual(searched.data["meta"]["total"], 1)
        self.assertEqual(searched.data["data"][0]["material_name"], "12号半盖纸箱")
        self.assertEqual(searched.data["data"][0]["warehouse_number"], "CK008")
        self.assertEqual(searched.data["data"][0]["warehouse_name"], "包材仓")

    def test_list_accepts_every_public_ordering_key_and_rejects_unknown_values(self):
        ordering_keys = [
            "material_number",
            "item_type",
            "category_name",
            "material_name",
            "specification",
            "unit_name",
            "color_name",
            "warehouse",
            "is_packaging_auxiliary",
            "box_shape",
            "updated_at",
        ]

        for ordering_key in ordering_keys:
            for ordering in (ordering_key, f"-{ordering_key}"):
                with self.subTest(ordering=ordering):
                    response = self.client.get(
                        "/api/v1/raw-materials/",
                        {"ordering": ordering, "page_size": 5},
                    )
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertLessEqual(len(response.data["data"]), 5)

        rejected = self.client.get(
            "/api/v1/raw-materials/",
            {"ordering": "category__archived_at"},
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("ordering", rejected.data["error"]["field_errors"])

    def test_display_ordering_places_empty_values_last_and_keeps_ties_stable(self):
        package_category = ProductCategory.objects.get(
            item_type="MATERIAL",
            category_name="包材",
        )
        semi_finished_category = ProductCategory.objects.get(
            item_type="SEMI_FINISHED",
            category_name="喷塑五金",
        )
        unit = ProductionUnit.objects.filter(status="ACTIVE").first()
        shared = {
            "material_name": "QA 排序同值",
            "specification": "QA-SORT-SPEC",
            "unit": unit,
            "material": "",
            "notes": "",
            "warehouse_number": "CK008",
            "warehouse_name": "包材仓",
        }
        first = RawMaterialInformation.objects.create(
            **shared,
            material_number="QA-SORT-001",
            item_type="MATERIAL",
            category=package_category,
            color_snapshot="A",
            is_packaging_auxiliary=False,
            box_shape="HALF_COVER",
            source_row_number=900001,
        )
        second = RawMaterialInformation.objects.create(
            **shared,
            material_number="QA-SORT-002",
            item_type="MATERIAL",
            category=package_category,
            color_snapshot="A",
            is_packaging_auxiliary=True,
            box_shape="FULL_COVER",
            source_row_number=900002,
        )
        empty = RawMaterialInformation.objects.create(
            **shared,
            material_number="QA-SORT-003",
            item_type="SEMI_FINISHED",
            category=semi_finished_category,
            color_snapshot="",
            is_packaging_auxiliary=False,
            box_shape="",
            source_row_number=900003,
        )

        color_response = self.client.get(
            "/api/v1/raw-materials/",
            {"q": "QA-SORT-", "ordering": "color_name", "page_size": 10},
        )
        self.assertEqual(
            [row["id"] for row in color_response.data["data"]],
            [str(first.pk), str(second.pk), str(empty.pk)],
        )

        packaging_response = self.client.get(
            "/api/v1/raw-materials/",
            {"q": "QA-SORT-", "ordering": "is_packaging_auxiliary", "page_size": 10},
        )
        self.assertEqual(
            [row["id"] for row in packaging_response.data["data"]],
            [str(first.pk), str(second.pk), str(empty.pk)],
        )

        box_shape_response = self.client.get(
            "/api/v1/raw-materials/",
            {"q": "QA-SORT-", "ordering": "box_shape", "page_size": 10},
        )
        self.assertEqual(box_shape_response.data["data"][-1]["id"], str(empty.pk))

    def test_create_enforces_type_category_package_and_warehouse_rules(self):
        payload = self.valid_payload("PACKAGE", packaging=True)
        created = self.client.post("/api/v1/raw-materials/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["item_type"], "MATERIAL")
        self.assertTrue(created.data["data"]["is_packaging_auxiliary"])
        self.assertEqual(created.data["data"]["box_shape"], "HALF_COVER")
        self.assertTrue(created.data["data"]["color_name"])

        mismatched = self.valid_payload("MISMATCH")
        mismatched["category"] = str(
            ProductCategory.objects.get(item_type="SEMI_FINISHED", category_name="喷塑管材").pk
        )
        mismatch_response = self.client.post("/api/v1/raw-materials/", mismatched, format="json")
        self.assertEqual(mismatch_response.status_code, 400, mismatch_response.data)
        self.assertIn("category", mismatch_response.data["error"]["field_errors"])

        non_packaging = self.valid_payload("NON-PACKAGE")
        non_packaging["is_packaging_auxiliary"] = True
        non_packaging["box_shape"] = "FULL_COVER"
        non_package_response = self.client.post("/api/v1/raw-materials/", non_packaging, format="json")
        self.assertEqual(non_package_response.status_code, 400, non_package_response.data)
        self.assertIn("is_packaging_auxiliary", non_package_response.data["error"]["field_errors"])

        invalid_warehouse = self.valid_payload("WAREHOUSE")
        invalid_warehouse["warehouse_number"] = "CK008"
        invalid_warehouse["warehouse_name"] = "错误仓库"
        warehouse_response = self.client.post("/api/v1/raw-materials/", invalid_warehouse, format="json")
        self.assertEqual(warehouse_response.status_code, 400, warehouse_response.data)
        self.assertIn("warehouse_name", warehouse_response.data["error"]["field_errors"])

    def test_update_requires_etag_preserves_legacy_color_and_writes_audit_log(self):
        historical = RawMaterialInformation.objects.get(material_number="5000400395")
        detail_url = f"/api/v1/raw-materials/{historical.pk}/"
        retrieved = self.client.get(detail_url)
        etag = retrieved["ETag"]
        self.assertIsNone(retrieved.data["data"]["color"])
        self.assertEqual(retrieved.data["data"]["color_name"], "/")

        missing = self.client.patch(detail_url, {"notes": "不应更新"}, format="json")
        updated = self.client.patch(
            detail_url,
            {"notes": "已更新备注"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        stale = self.client.patch(
            detail_url,
            {"notes": "过期更新"},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["color_name"], "/")
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="RAW_MATERIAL_INFORMATION",
                object_id=historical.pk,
                action="UPDATED",
            ).exists()
        )

    def test_new_number_must_be_unique_but_historical_duplicate_can_be_edited(self):
        duplicate_payload = self.valid_payload("DUPLICATE")
        duplicate_payload["material_number"] = "5000400395"
        rejected = self.client.post("/api/v1/raw-materials/", duplicate_payload, format="json")
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("material_number", rejected.data["error"]["field_errors"])

        historical = RawMaterialInformation.objects.filter(material_number="511741746420").first()
        detail_url = f"/api/v1/raw-materials/{historical.pk}/"
        etag = self.client.get(detail_url)["ETag"]
        updated = self.client.patch(
            detail_url,
            {"notes": "保留历史重复品号"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["material_number"], "511741746420")

    def test_view_permission_is_required(self):
        self.user.user_permissions.clear()
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.get("/api/v1/raw-materials/")
        options = self.client.get("/api/v1/raw-materials/options/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(options.status_code, 403)
