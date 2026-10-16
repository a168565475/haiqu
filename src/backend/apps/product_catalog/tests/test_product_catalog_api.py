from hashlib import sha256
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import ProductInformation


ROOT = "/api/v1/product-catalog/"


class ProductCatalogApiTests(APITestCase):
    def setUp(self):
        self.assertTrue(apps.is_installed("apps.product_catalog"), "尚未注册独立产品管理应用")
        self.Category = apps.get_model("product_catalog", "ProductCatalogCategory")
        self.Name = apps.get_model("product_catalog", "ProductCatalogName")
        self.Product = apps.get_model("product_catalog", "ProductCatalog")
        self.Color = apps.get_model("product_catalog", "ProductCatalogColor")
        self.Import = apps.get_model("product_catalog", "ProductCatalogImport")
        self.user = get_user_model().objects.create_superuser(username="product_catalog_admin", password="CatalogTest123!", email="")
        self.employee = Employee.objects.create(user=self.user, employee_code="PRODUCT_CATALOG_ADMIN", display_name="产品测试员")
        self.client.force_authenticate(self.user)
        self.category = self.Category.objects.create(name="折叠椅")
        self.name = self.Name.objects.create(category=self.category, name="折叠休闲椅（完整品名）")

    def create_product(self, **overrides):
        payload = {"name_id": str(self.name.pk), "product_code": "", "item_number": "A 01", "specification": "100 × 50", "unit": "", "scale": "常规"}
        payload.update(overrides)
        response = self.client.post(ROOT, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("ETag", response)
        return response

    def write(self, previous, method="patch", suffix="", payload=None):
        return getattr(self.client, method)(f"{ROOT}{previous.data['data']['id']}/{suffix}", payload or {}, format="json", HTTP_IF_MATCH=previous["ETag"])

    def test_identical_products_keep_independent_identity_and_legacy_data(self):
        legacy = list(ProductInformation.objects.order_by("id").values_list("id", "updated_at"))
        first, second = self.create_product(), self.create_product()
        self.assertNotEqual(first.data["data"]["id"], second.data["data"]["id"])
        self.assertEqual(first.data["data"]["product_code"], "")
        self.assertEqual(first.data["data"]["item_number"], "A 01")
        self.assertEqual(first.data["data"]["unit"], "")
        self.assertEqual(first.data["data"]["scale"], "常规")
        self.assertEqual([row["value"] for row in first.data["data"]["colors"]], ["无颜色"])
        self.assertIsNone(first.data["data"]["source"])
        self.assertEqual(legacy, list(ProductInformation.objects.order_by("id").values_list("id", "updated_at")))
        audit = AuditLog.objects.get(object_type="PRODUCT_CATALOG", object_id=first.data["data"]["id"])
        self.assertEqual(audit.actor_employee_id, self.employee.pk)

    def test_nonempty_duplicate_codes_and_verbatim_fields_are_allowed(self):
        for _ in range(2):
            current = self.create_product(product_code="  C  001  ", scale="按单定制 原值", unit="套")
            self.assertEqual(current.data["data"]["product_code"], "  C  001  ")
            self.assertEqual(current.data["data"]["scale"], "按单定制 原值")

    def test_list_filters_names_products_and_has_fifty_row_pagination(self):
        current = self.create_product()
        self.Product.objects.bulk_create([self.Product(name=self.name, item_number=f"bulk-{index}") for index in range(54)])
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["meta"], {"page": 1, "page_size": 50, "total": 55, "total_pages": 2})
        for filters in ({"name_id": str(self.name.pk), "q": "100 ×"}, {"category_id": str(self.category.pk), "q": "A 01"}):
            filtered = self.client.get(ROOT, filters)
            self.assertEqual(filtered.data["meta"]["total"], 1)
            self.assertEqual(filtered.data["data"][0]["id"], current.data["data"]["id"])
        self.assertEqual(self.client.get(ROOT, {"page_size": 500}).data["meta"]["page_size"], 100)
        self.assertEqual(self.client.get(ROOT, {"category_id": "not-uuid"}).status_code, 400)
        names = self.client.get(f"{ROOT}names/", {"category_id": self.category.pk, "q": "完整"})
        self.assertEqual(names.data["data"][0]["product_count"], 55)

    def test_options_only_use_independent_categories_units_and_scales(self):
        self.create_product(unit="套", scale="定制")
        response = self.client.get(f"{ROOT}options/")
        self.assertEqual(response.data["data"], {"categories": [{"id": str(self.category.pk), "name": "折叠椅", "name_count": 1}], "units": ["套"], "scales": ["定制"]})
        self.assertEqual(self.client.post(f"{ROOT}options/", {"name": "非法类别"}, format="json").status_code, 405)

    def test_options_count_active_names_including_empty_without_product_multiplication(self):
        archived_at = timezone.now()
        self.Category.objects.filter(pk=self.category.pk).update(sort_order=2)
        empty_category = self.Category.objects.create(name="空类别", sort_order=0)
        archived_names_category = self.Category.objects.create(name="仅含归档品名类别", sort_order=1)
        archived_category = self.Category.objects.create(name="归档类别", archived_at=archived_at)
        empty_name = self.Name.objects.create(category=self.category, name="尚无产品的品名")
        archived_name = self.Name.objects.create(category=self.category, name="归档品名", archived_at=archived_at)
        self.Name.objects.create(category=archived_names_category, name="已归档品名", archived_at=archived_at)
        self.Name.objects.create(category=archived_category, name="归档类别中的品名")
        self.Product.objects.bulk_create([
            self.Product(name=self.name), self.Product(name=self.name), self.Product(name=self.name),
            self.Product(name=self.name, archived_at=archived_at), self.Product(name=archived_name),
        ])

        response = self.client.get(f"{ROOT}options/")
        self.assertEqual(response.status_code, 200)
        counts = {row["id"]: row.get("name_count") for row in response.data["data"]["categories"]}
        self.assertEqual(counts, {str(self.category.pk): 2, str(empty_category.pk): 0, str(archived_names_category.pk): 0})
        expected_order = [str(empty_category.pk), str(archived_names_category.pk), str(self.category.pk)]
        self.assertEqual([row["id"] for row in response.data["data"]["categories"]], expected_order)
        self.assertEqual(expected_order[0], str(empty_category.pk))
        filtered = self.client.get(f"{ROOT}options/", {"q": "不存在的搜索内容", "category_id": str(empty_category.pk)})
        self.assertEqual(filtered.data, response.data)

        names = self.client.get(f"{ROOT}names/", {"category_id": str(self.category.pk)})
        self.assertEqual({row["id"]: row["product_count"] for row in names.data["data"]}, {str(self.name.pk): 3, str(empty_name.pk): 0})

    def test_name_creation_rename_uniqueness_and_no_implicit_merge(self):
        response = self.client.post(f"{ROOT}names/", {"category_id": str(self.category.pk), "name": "  完整月亮椅  "}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["name"], "  完整月亮椅  ")
        url = f"{ROOT}names/{response.data['data']['id']}/"
        self.assertEqual(self.client.patch(url, {"name": "新名字"}, format="json").status_code, 428)
        changed = self.client.patch(url, {"name": "新名字"}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertNotEqual(changed["ETag"], response["ETag"])
        self.assertEqual(self.client.patch(url, {"name": "再改"}, format="json", HTTP_IF_MATCH=response["ETag"]).status_code, 412)
        conflict = self.client.patch(url, {"name": self.name.name}, format="json", HTTP_IF_MATCH=changed["ETag"])
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(self.client.post(f"{ROOT}names/", {"category_id": str(self.category.pk), "name": self.name.name}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"category_id": str(uuid4())}, format="json", HTTP_IF_MATCH=changed["ETag"]).status_code, 400)
        self.assertEqual(self.client.delete(url, HTTP_IF_MATCH=changed["ETag"]).status_code, 405)

    def test_colors_share_parent_version_and_soft_removal_restores_identity(self):
        original = self.create_product()
        changed = self.write(original, "post", "colors/", {"value": "  红色  "})
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(self.Product.objects.count(), 1)
        self.assertNotEqual(changed["ETag"], original["ETag"])
        self.assertEqual(self.write(original, payload={"unit": "套"}).status_code, 412)
        self.assertEqual(self.write(changed, "post", "colors/", {"value": "红色"}).status_code, 400)
        color = next(row for row in changed.data["data"]["colors"] if row["value"] == "红色")
        removed = self.write(changed, "delete", f"colors/{color['id']}/")
        self.assertEqual(removed.status_code, 200)
        self.assertIsNotNone(self.Color.objects.get(pk=color["id"]).archived_at)
        restored = self.write(removed, "post", "colors/", {"value": "红色"})
        self.assertEqual(next(row["id"] for row in restored.data["data"]["colors"] if row["value"] == "红色"), color["id"])
        self.assertEqual(set(AuditLog.objects.filter(object_id=original.data["data"]["id"]).values_list("action", flat=True)), {"CREATED", "COLOR_ADDED", "COLOR_REMOVED", "COLOR_RESTORED"})

    def test_name_rename_invalidates_product_detail_version(self):
        current = self.create_product()
        url = f"{ROOT}names/{self.name.pk}/"
        name_detail = self.client.get(url)
        renamed = self.client.patch(url, {"name": "已维护的完整品名"}, format="json", HTTP_IF_MATCH=name_detail["ETag"])
        self.assertEqual(renamed.status_code, 200)
        detail = self.client.get(f"{ROOT}{current.data['data']['id']}/")
        self.assertEqual(detail.data["data"]["name"], "已维护的完整品名")
        self.assertNotEqual(detail["ETag"], current["ETag"])
        self.assertEqual(self.write(current, payload={"unit": "只"}).status_code, 412)

    def test_missing_stale_etag_cross_product_color_and_no_physical_delete(self):
        first, second = self.create_product(), self.create_product()
        url = f"{ROOT}{first.data['data']['id']}/"
        for method, suffix, payload in (("patch", "", {"unit": "套"}), ("post", "colors/", {"value": "黑"}), ("delete", f"colors/{first.data['data']['colors'][0]['id']}/", {})):
            response = getattr(self.client, method)(url + suffix, payload, format="json")
            self.assertEqual(response.status_code, 428)
        self.assertEqual(self.write(first, "delete", f"colors/{second.data['data']['colors'][0]['id']}/").status_code, 404)
        self.assertEqual(self.write(first, "delete").status_code, 405)

    def test_product_patch_preserves_source_and_rejects_name_move_unknown_fields(self):
        current = self.create_product()
        changed = self.write(current, payload={"unit": "只", "scale": "定制", "product_code": "C 9", "item_number": "货号", "specification": "  原规格  "})
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["data"]["specification"], "  原规格  ")
        for payload in ({"name_id": str(self.name.pk)}, {"source": None}, {"warehouse_name": "仓库"}, {"unit": ["只", "套"]}, {"colors": []}, {"scale": None}, {}):
            self.assertEqual(self.write(changed, payload=payload).status_code, 400, payload)

    def test_audit_failure_rolls_back_product_and_color_version(self):
        current = self.create_product()
        with patch("apps.product_catalog.services.write_audit_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.write(current, "post", "colors/", {"value": "蓝"})
        detail = self.client.get(f"{ROOT}{current.data['data']['id']}/")
        self.assertEqual(detail.data, current.data)
        self.assertEqual(detail["ETag"], current["ETag"])

    def test_source_retains_file_bytes_raw_fields_and_database_identity(self):
        from apps.product_catalog.services import create_product_record
        content = b"test source bytes"
        batch = self.Import.objects.create(filename="products.xlsx", sha256=sha256(content).hexdigest(), sheet="产品", source_bytes=content, row_count=2)
        source = {"filename": batch.filename, "sha256": batch.sha256, "sheet": batch.sheet, "row": 2, "raw_fields": {"仓库": "原始仓库", "编号": "/"}, "import_id": batch.pk}
        product = create_product_record(data={"name_id": self.name.pk, "product_code": "", "item_number": "A", "specification": "", "unit": "", "scale": "常规"}, source=source)
        detail = self.client.get(f"{ROOT}{product.pk}/")
        self.assertEqual(detail.data["data"]["source"], {key: value for key, value in source.items() if key != "import_id"})
        self.assertEqual(bytes(product.source_import.source_bytes), content)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.Product.objects.create(name=self.name, source_import=batch, source_filename=batch.filename, source_sha256=batch.sha256, source_sheet=batch.sheet, source_row=2, source_raw_fields={})
        changed = self.write(detail, payload={"unit": "套"})
        self.assertEqual(changed.data["data"]["source"], detail.data["data"]["source"])

    def test_database_rejects_incomplete_source_and_duplicate_color_or_name(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.Product.objects.create(name=self.name, source_filename="incomplete.xlsx")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.Name.objects.create(category=self.category, name=self.name.name)
        current = self.create_product()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.Color.objects.create(product_id=current.data["data"]["id"], value="无颜色")

    @override_settings(ACCESS_MANAGEMENT_ENABLED=False, SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
    def test_legacy_or_view_permission_never_authorizes_new_module_writes(self):
        current = self.create_product()
        user = get_user_model().objects.create_user(username="catalog_reader")
        Employee.objects.create(user=user, employee_code="PRODUCT_READER", display_name="产品只读")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="products", codename="view_productinformation"))
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="product_catalog", codename="view_productcatalog"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.assertEqual(self.client.get(ROOT).status_code, 200)
        self.assertEqual(self.client.get(f"{ROOT}options/").status_code, 200)
        self.assertEqual(self.client.post(ROOT, {"name_id": str(self.name.pk)}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{ROOT}names/", {"category_id": str(self.category.pk), "name": "新"}, format="json").status_code, 403)
        self.assertEqual(self.write(current, payload={"unit": "只"}).status_code, 403)
        self.assertEqual(self.write(current, "post", "colors/", {"value": "黑"}).status_code, 403)

    def test_permission_catalog_is_independent_and_available(self):
        from apps.access_control.catalog import catalog
        entries = [row for row in catalog() if row["code"].startswith("product_catalog.")]
        self.assertEqual({row["code"] for row in entries}, {"product_catalog.view_productcatalog", "product_catalog.add_productcatalog", "product_catalog.change_productcatalog"})
        self.assertTrue(all(row["available"] and row["resource_name"] == "产品管理" for row in entries))

    def test_anonymous_and_inactive_employee_cannot_access(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        self.employee.status = "INACTIVE"
        self.employee.save(update_fields=["status"])
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)

    def test_session_write_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        payload = {"name_id": str(self.name.pk), "product_code": "", "item_number": "", "specification": "", "unit": "", "scale": ""}
        self.assertEqual(client.post(ROOT, payload, format="json").status_code, 403)
        client.get("/api/auth/me/")
        response = client.post(ROOT, payload, format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.data)
