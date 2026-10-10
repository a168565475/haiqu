from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import ProductInformation
from apps.reference_data.models import ProductCategory, ProductItem, ProductionUnit


class ProductInformationApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="product_information_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="PRODUCT_INFORMATION_ADMIN",
            display_name="产品信息管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="products")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def valid_payload(self, suffix="001"):
        product_item = ProductItem.objects.select_related("category").filter(status="ACTIVE").first()
        unit = ProductionUnit.objects.filter(status="ACTIVE").first()
        return {
            "product_number": f"QA-PRODUCT-{suffix}",
            "product_code": f"QA-CODE-{suffix}",
            "category": str(product_item.category_id),
            "product_name": "自动化测试产品",
            "specification": "100*50*30",
            "unit": str(unit.pk),
            "product_item": str(product_item.pk),
            "warehouse_number": "CK-QA",
            "warehouse_name": "测试仓",
            "scale": "CUSTOM",
            "status": "ACTIVE",
        }

    def test_seed_import_is_complete_and_preserves_known_history(self):
        self.assertEqual(ProductInformation.objects.count(), 185)
        self.assertEqual(ProductInformation.objects.filter(scale="CUSTOM").count(), 179)
        self.assertEqual(ProductInformation.objects.filter(scale="REGULAR").count(), 6)
        self.assertEqual(ProductInformation.objects.filter(status="INACTIVE").count(), 1)
        self.assertTrue(ProductItem.objects.filter(item_number="XY-205-1", category__category_name="外袋").exists())

        historical = ProductInformation.objects.select_related("category", "product_item__category").get(
            product_number="1004200001"
        )
        self.assertEqual(historical.category.category_name, "三折床-不带棚")
        self.assertEqual(historical.product_item.item_number, "XY-212")
        self.assertNotEqual(historical.category_id, historical.product_item.category_id)

    def test_list_filters_and_search_are_paginated(self):
        options = self.client.get("/api/v1/products/options/")
        regular = self.client.get("/api/v1/products/?scale=REGULAR&page_size=100")
        inactive = self.client.get("/api/v1/products/?status=INACTIVE")
        searched = self.client.get("/api/v1/products/?q=HTC-010G")

        self.assertEqual(options.status_code, 200, options.data)
        self.assertGreater(len(options.data["data"]["categories"]), 0)
        self.assertEqual(len(options.data["data"]["units"]), 12)
        self.assertEqual(len(options.data["data"]["items"]), 36)
        self.assertEqual(regular.status_code, 200, regular.data)
        self.assertEqual(regular.data["meta"]["total"], 6)
        self.assertEqual(inactive.data["meta"]["total"], 1)
        self.assertEqual(searched.data["meta"]["total"], 1)
        self.assertEqual(searched.data["data"][0]["product_number"], "1002000011")

    def test_create_enforces_finished_category_and_item_relationship(self):
        payload = self.valid_payload()
        created = self.client.post("/api/v1/products/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["product_type"], "FINISHED")
        self.assertFalse(created.data["data"]["category_item_mismatch"])

        mismatched_payload = self.valid_payload("002")
        item = ProductItem.objects.get(pk=mismatched_payload["product_item"])
        other_category = ProductCategory.objects.filter(
            item_type="FINISHED",
            status="ACTIVE",
        ).exclude(pk=item.category_id).first()
        mismatched_payload["category"] = str(other_category.pk)
        rejected = self.client.post("/api/v1/products/", mismatched_payload, format="json")

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("product_item", rejected.data["error"]["field_errors"])

    def test_update_requires_etag_and_writes_audit_log(self):
        created = self.client.post("/api/v1/products/", self.valid_payload("ETAG"), format="json")
        product_id = created.data["data"]["id"]
        detail_url = f"/api/v1/products/{product_id}/"
        etag = self.client.get(detail_url)["ETag"]

        missing = self.client.patch(detail_url, {"product_name": "不应更新"}, format="json")
        updated = self.client.patch(
            detail_url,
            {"product_name": "已更新产品"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        stale = self.client.patch(
            detail_url,
            {"product_name": "过期更新"},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCT_INFORMATION",
                object_id=product_id,
                action="UPDATED",
            ).exists()
        )

    def test_view_permission_is_required(self):
        self.user.user_permissions.clear()
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.get("/api/v1/products/")

        self.assertEqual(response.status_code, 403)
