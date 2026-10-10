from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient, APITestCase
from unittest.mock import patch

from apps.audit.models import AuditLog
from apps.files.models import BusinessFile, FileScanStatus
from apps.imports.security import ScannerUnavailable
from apps.organizations.models import Employee
from apps.reference_data.models import (
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductionUnit,
)


class ProductionDataApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="production_data_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="PRODUCTION_DATA_ADMIN",
            display_name="生产资料管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="reference_data")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_seed_data_counts_relations_and_images_are_complete(self):
        self.assertEqual(ProductCategory.objects.count(), 50)
        self.assertEqual(ProductionUnit.objects.count(), 12)
        self.assertEqual(ProductColor.objects.count(), 324)
        self.assertEqual(ProductItem.objects.count(), 36)
        self.assertEqual(ProductColor.objects.filter(image_file__isnull=False).count(), 23)
        self.assertFalse(ProductItem.objects.filter(category__isnull=True).exists())
        self.assertFalse(ProductItem.objects.exclude(category__status="ACTIVE").exists())

        summary = self.client.get("/api/v1/reference-data/production-data-summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(
            summary.data["data"]["category_counts"],
            {
                "product_categories": 50,
                "production_units": 12,
                "product_colors": 324,
                "product_items": 36,
                "fabric_materials": 7,
                "fabric_specifications": 16,
                "fabric_widths": 8,
                "tube_product_names": 79,
                "tube_thicknesses": 14,
                "tube_diameters": 24,
                "tube_materials": 3,
                "tube_shapes": 7,
                "tube_coating_colors": 29,
                "accessory_product_names": 148,
                "accessory_specifications": 349,
                "accessory_colors": 284,
                "accessory_materials": 27,
            },
        )

        unit = ProductionUnit.objects.get(unit_code="01")
        self.assertEqual(unit.unit_name, "个")
        unit_list = self.client.get(
            f"/api/v1/reference-data/production-units/?q={unit.unit_name}&status=ACTIVE&page_size=5"
        )
        self.assertEqual(unit_list.status_code, 200, unit_list.data)
        self.assertEqual(unit_list.data["meta"]["total"], 1)
        self.assertEqual(unit_list.data["data"][0]["unit_code"], unit.unit_code)

    def test_unique_rules_category_reference_protection_and_audit(self):
        category_response = self.client.post(
            "/api/v1/reference-data/product-categories/",
            {
                "item_type": "FINISHED",
                "category_name": "自动化测试类别",
                "sort_order": 999,
                "description": "测试专用",
            },
            format="json",
        )
        self.assertEqual(category_response.status_code, 201, category_response.data)
        category_id = category_response.data["data"]["id"]

        duplicate = self.client.post(
            "/api/v1/reference-data/product-categories/",
            {
                "item_type": "MATERIAL",
                "category_name": "自动化测试类别",
                "sort_order": 1000,
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

        item_response = self.client.post(
            "/api/v1/reference-data/product-items/",
            {
                "item_number": "QA-PRODUCT-ITEM-001",
                "category": category_id,
                "sort_order": 999,
            },
            format="json",
        )
        self.assertEqual(item_response.status_code, 201, item_response.data)
        self.assertIsNone(item_response.data["data"]["legacy_data_id"])

        blocked_archive = self.client.post(
            f"/api/v1/reference-data/product-categories/{category_id}/archive/",
            {"reason": "验证引用保护"},
            format="json",
            HTTP_IF_MATCH=category_response["ETag"],
        )
        self.assertEqual(blocked_archive.status_code, 409, blocked_archive.data)

        deactivated = self.client.post(
            f"/api/v1/reference-data/product-categories/{category_id}/deactivate/",
            {"reason": "验证停用"},
            format="json",
            HTTP_IF_MATCH=category_response["ETag"],
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.data)

        rejected_item = self.client.post(
            "/api/v1/reference-data/product-items/",
            {
                "item_number": "QA-PRODUCT-ITEM-002",
                "category": category_id,
                "sort_order": 1000,
            },
            format="json",
        )
        self.assertEqual(rejected_item.status_code, 400, rejected_item.data)

        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCT_CATEGORY",
                object_id=category_id,
                action="DEACTIVATED",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCT_ITEM",
                object_id=item_response.data["data"]["id"],
                action="CREATED",
            ).exists()
        )

    def test_etag_status_filters_and_database_unique_constraints(self):
        unit = ProductionUnit.objects.order_by("sort_order").first()
        detail_url = f"/api/v1/reference-data/production-units/{unit.pk}/"
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200, detail.data)
        stale_etag = detail["ETag"]

        updated = self.client.patch(
            detail_url,
            {"description": "ETag 更新测试"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        stale = self.client.patch(
            detail_url,
            {"description": "过期写入"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductionUnit.objects.create(
                unit_code=unit.unit_code,
                unit_name="不会写入的重复单位",
            )

        color = ProductColor.objects.order_by("sort_order").first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductColor.objects.create(
                color_card=color.color_card,
                color_code=color.color_code,
                color_name=color.color_name,
            )

        inactive = self.client.post(
            f"{detail_url}deactivate/",
            {"reason": "验证状态筛选"},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(inactive.status_code, 200, inactive.data)
        filtered = self.client.get("/api/v1/reference-data/production-units/?status=INACTIVE")
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertIn(str(unit.pk), {row["id"] for row in filtered.data["data"]})

        invalid_category_filter = self.client.get(
            "/api/v1/reference-data/product-items/?category_id=not-a-uuid"
        )
        self.assertEqual(invalid_category_filter.status_code, 400, invalid_category_filter.data)

    def test_permissions_are_isolated_per_production_data_model(self):
        limited_user = get_user_model().objects.create_user(username="limited_production_viewer")
        Employee.objects.create(
            user=limited_user,
            employee_code="LIMITED_PRODUCTION_VIEWER",
            display_name="类别只读用户",
        )
        limited_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reference_data",
                codename="view_productcategory",
            )
        )
        limited_client = APIClient()
        limited_client.force_authenticate(limited_user)

        self.assertEqual(
            limited_client.get("/api/v1/reference-data/production-data-summary/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/product-categories/").status_code,
            200,
        )
        self.assertEqual(
            limited_client.get("/api/v1/reference-data/production-units/").status_code,
            403,
        )
        self.assertEqual(
            limited_client.post(
                "/api/v1/reference-data/product-categories/",
                {"item_type": "FINISHED", "category_name": "无权新增"},
                format="json",
            ).status_code,
            403,
        )

    def test_color_image_read_signature_size_etag_and_clear(self):
        color = ProductColor.objects.filter(image_file__isnull=False).select_related("image_file").first()
        image_url = f"/api/v1/reference-data/product-colors/{color.pk}/image/"
        image_response = self.client.get(image_url)
        self.assertEqual(image_response.status_code, 200)
        image_bytes = b"".join(image_response.streaming_content)
        self.assertTrue(image_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        detail = self.client.get(f"/api/v1/reference-data/product-colors/{color.pk}/")
        missing_etag = self.client.delete(image_url)
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)

        invalid_signature = self.client.post(
            image_url,
            {"image": SimpleUploadedFile("fake.png", b"not-a-png", content_type="image/png")},
            format="multipart",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(invalid_signature.status_code, 400, invalid_signature.data)

        too_large = self.client.post(
            image_url,
            {
                "image": SimpleUploadedFile(
                    "oversized.png",
                    b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024),
                    content_type="image/png",
                )
            },
            format="multipart",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(too_large.status_code, 400, too_large.data)

        with patch("apps.files.uploads._clamav_scan", side_effect=ScannerUnavailable()):
            scan_unavailable = self.client.post(
                image_url,
                {
                    "image": SimpleUploadedFile(
                        "scanner-test.png",
                        b"\x89PNG\r\n\x1a\n" + b"safe-test-data",
                        content_type="image/png",
                    )
                },
                format="multipart",
                HTTP_IF_MATCH=detail["ETag"],
            )
        self.assertEqual(scan_unavailable.status_code, 503, scan_unavailable.data)

        old_file = color.image_file
        replacement_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="replacement.png",
            storage_key="production-colors/test/replacement.png",
            content_type="image/png",
            size_bytes=21,
            content_hash="replacement-test",
            scan_status=FileScanStatus.CLEAN,
        )
        with patch(
            "apps.reference_data.api.views.save_scanned_image",
            return_value=replacement_file,
        ) as save_image:
            replaced = self.client.post(
                image_url,
                {
                    "image": SimpleUploadedFile(
                        "replacement.png",
                        b"\x89PNG\r\n\x1a\n" + b"replacement",
                        content_type="image/png",
                    )
                },
                format="multipart",
                HTTP_IF_MATCH=detail["ETag"],
            )
        self.assertEqual(replaced.status_code, 200, replaced.data)
        self.assertTrue(replaced.data["data"]["has_image"])
        save_image.assert_called_once()
        old_file.refresh_from_db()
        self.assertIsNotNone(old_file.archived_at)

        cleared = self.client.delete(image_url, HTTP_IF_MATCH=replaced["ETag"])
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertFalse(cleared.data["data"]["has_image"])
        color.refresh_from_db()
        self.assertIsNone(color.image_file_id)
        replacement_file.refresh_from_db()
        self.assertIsNotNone(replacement_file.archived_at)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCT_COLOR",
                object_id=color.pk,
                action="IMAGE_CLEARED",
            ).exists()
        )
