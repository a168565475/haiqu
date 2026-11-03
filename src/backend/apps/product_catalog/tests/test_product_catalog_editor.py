from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit

from ..editing import _check_external_references
from ..models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName


ROOT = "/api/v1/product-catalog/"


class ProductCatalogEditorTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="product_editor_admin", password="EditorTest123!", email="")
        self.employee = Employee.objects.create(user=self.user, employee_code="PRODUCT_EDITOR_ADMIN", display_name="产品编辑测试")
        self.client.force_authenticate(self.user)
        self.category = ProductCatalogCategory.objects.create(name="编辑测试类")
        self.name = ProductCatalogName.objects.create(category=self.category, name="休闲椅")
        self.first = ProductCatalog.objects.create(name=self.name, item_number="A", specification="100", unit="套")
        self.second = ProductCatalog.objects.create(name=self.name, item_number="B", specification="120", unit="套")
        for product in (self.first, self.second):
            ProductCatalogColor.objects.create(product=product, value="无颜色")
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "PC-EDITOR-SET"})
        self.url = f"{ROOT}names/{self.name.pk}/editor/"

    def read(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def save(self, data, *, version=None):
        version = version or self.read()["ETag"]
        return self.client.patch(self.url, {"name": self.name.name, **data}, format="json", HTTP_IF_MATCH=version)

    def test_independent_options_atomic_name_and_product_save(self):
        response = self.save({"name": "新的品名", "products": [
            {"id": str(self.first.pk), "materials": ["铁", "铝"], "thicknesses": ["0.7", "0.8"], "colors": ["黑", "白"]},
            {"id": str(self.second.pk), "materials": ["塑料"], "thicknesses": ["2"], "colors": ["蓝"]},
        ]})
        self.assertEqual(response.status_code, 200, response.data)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.name.refresh_from_db()
        self.assertEqual(self.name.name, "新的品名")
        self.assertEqual(self.first.materials, ["铁", "铝"])
        self.assertEqual(self.second.materials, ["塑料"])
        self.assertEqual(self.first.thicknesses, ["0.7", "0.8"])
        self.assertEqual(set(self.first.colors.filter(archived_at=None).values_list("value", flat=True)), {"黑", "白"})
        self.assertEqual(self.read().data, response.data)

    def test_omitted_products_are_preserved_and_single_delete_is_exact(self):
        second_before = ProductCatalog.objects.filter(pk=self.second.pk).values().get()
        response = self.save({"delete_product_ids": [str(self.first.pk)]})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(ProductCatalog.objects.filter(pk=self.first.pk).exists())
        self.assertFalse(ProductCatalogColor.objects.filter(product_id=self.first.pk).exists())
        self.assertEqual(ProductCatalog.objects.filter(pk=self.second.pk).values().get(), second_before)
        self.assertTrue(ProductCatalogName.objects.filter(pk=self.name.pk).exists())
        self.assertEqual(response.data["data"]["name"]["product_count"], 1)
        self.assertTrue(AuditLog.objects.filter(object_id=self.first.pk, action="DELETED", actor_employee=self.employee).exists())

    def test_delete_whole_name_covers_more_than_fifty_rows_and_allows_recreate(self):
        ProductCatalog.objects.bulk_create([ProductCatalog(name=self.name, item_number=str(index)) for index in range(55)])
        current = self.read()
        self.assertEqual(len(current.data["data"]["products"]), 57)
        response = self.client.delete(f"{ROOT}names/{self.name.pk}/", HTTP_IF_MATCH=current["ETag"])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(ProductCatalog.objects.filter(name_id=self.name.pk).exists())
        self.assertFalse(ProductCatalogName.objects.filter(pk=self.name.pk).exists())
        self.assertEqual(ProductCatalogColor.objects.count(), 0)
        recreated = self.client.post(f"{ROOT}names/editor/", {"category_id": str(self.category.pk), "name": self.name.name,
            "products": [{"item_number": "A", "specification": "100", "unit": "套", "materials": ["铁"]}]}, format="json")
        self.assertEqual(recreated.status_code, 201, recreated.data)
        self.assertNotEqual(recreated.data["data"]["name"]["id"], str(self.name.pk))
        self.assertEqual(recreated.data["data"]["products"][0]["materials"], ["铁"])

    def test_missing_and_stale_version_and_legacy_color_write_invalidate_group(self):
        version = self.read()["ETag"]
        self.assertEqual(self.client.patch(self.url, {"name": "无版本"}, format="json").status_code, 428)
        product = self.client.get(f"{ROOT}{self.first.pk}/")
        self.assertEqual(self.client.post(f"{ROOT}{self.first.pk}/colors/", {"value": "红"}, format="json", HTTP_IF_MATCH=product["ETag"]).status_code, 200)
        self.assertEqual(self.save({"name": "过期"}, version=version).status_code, 412)
        self.assertEqual(self.client.delete(f"{ROOT}names/{self.name.pk}/", HTTP_IF_MATCH=version).status_code, 412)
        self.name.refresh_from_db()
        self.assertEqual(self.name.name, "休闲椅")

    def test_foreign_missing_and_duplicate_ids_reject_entire_request(self):
        other_name = ProductCatalogName.objects.create(category=self.category, name="别的品名")
        other_product = ProductCatalog.objects.create(name=other_name)
        payloads = [
            {"products": [{"id": str(other_product.pk), "materials": ["错误"]}]},
            {"delete_product_ids": [str(other_product.pk)]},
            {"products": [{"id": str(uuid4())}]},
            {"products": [{"id": str(self.first.pk)}, {"id": str(self.first.pk)}]},
            {"products": [{"id": str(self.first.pk)}], "delete_product_ids": [str(self.first.pk)]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                before = self.read()
                self.assertEqual(self.save({"name": "不应改名", **payload}, version=before["ETag"]).status_code, 400)
                self.assertEqual(self.read().data, before.data)

    def test_options_reject_non_list_non_text_blank_duplicate_or_unknown_fields(self):
        for value in ("铁", [7], [""], ["铁", " 铁 "], {"value": "铁"}):
            with self.subTest(value=value):
                response = self.save({"products": [{"id": str(self.first.pk), "materials": value}]})
                self.assertEqual(response.status_code, 400, response.data)
        response = self.save({"products": [{"id": str(self.first.pk), "source_raw_fields": {}}]})
        self.assertEqual(response.status_code, 400)

    def test_units_come_from_active_production_and_unchanged_legacy_unit_survives(self):
        ProductionUnit.objects.create(unit_code="PC-EDITOR-INACTIVE", unit_name="停用单位", status="INACTIVE")
        ProductCatalog.objects.filter(pk=self.first.pk).update(unit="旧单位")
        options = self.client.get(f"{ROOT}options/").data["data"]["units"]
        self.assertIn("套", options)
        self.assertNotIn("旧单位", options)
        self.assertNotIn("停用单位", options)
        self.assertEqual(self.save({"products": [{"id": str(self.first.pk), "unit": "旧单位", "materials": ["铁"]}]}).status_code, 200)
        for unit in ("自造单位", "停用单位"):
            response = self.save({"products": [{"id": str(self.first.pk), "unit": unit}]})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.save({"products": [{"item_number": "新产品", "unit": "旧单位"}]}).status_code, 400)

    def test_invalid_second_product_rolls_back_name_first_product_and_deletion(self):
        before = self.read()
        response = self.save({"name": "不能部分保存", "products": [
            {"id": str(self.second.pk), "materials": ["铁"]}, {"item_number": "新", "unit": "未配置单位"}],
            "delete_product_ids": [str(self.first.pk)]}, version=before["ETag"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.read().data, before.data)
        self.assertEqual(self.read()["ETag"], before["ETag"])

    def test_create_editor_fails_atomically_without_leaving_empty_name(self):
        name_count, product_count = ProductCatalogName.objects.count(), ProductCatalog.objects.count()
        response = self.client.post(f"{ROOT}names/editor/", {
            "category_id": str(self.category.pk), "name": "不应留下空品名", "products": [
                {"item_number": "第一条", "unit": "套"}, {"item_number": "第二条", "unit": "未维护单位"},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ProductCatalogName.objects.count(), name_count)
        self.assertEqual(ProductCatalog.objects.count(), product_count)

    def test_name_conflict_and_audit_failure_roll_back_all_products(self):
        ProductCatalogName.objects.create(category=self.category, name="已存在")
        before = self.read()
        self.assertEqual(self.save({"name": "已存在", "delete_product_ids": [str(self.first.pk)]}, version=before["ETag"]).status_code, 400)
        with patch("apps.product_catalog.services.write_audit_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.save({"name": "不应保存", "delete_product_ids": [str(self.first.pk)]}, version=before["ETag"])
        self.assertEqual(self.read().data, before.data)

    def test_reference_guard_queries_real_reverse_relations_and_group_delete_is_atomic(self):
        with self.assertRaises(ValidationError):
            _check_external_references(self.name)
        before = self.read()
        with patch("apps.product_catalog.editing._check_product_delete", side_effect=[None, ValidationError("被单据引用")]):
            response = self.client.delete(f"{ROOT}names/{self.name.pk}/", HTTP_IF_MATCH=before["ETag"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.read().data, before.data)

    @override_settings(ACCESS_MANAGEMENT_ENABLED=False, SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
    def test_readonly_cannot_write_and_change_only_cannot_create_inside_batch(self):
        current = self.read()
        user = get_user_model().objects.create_user(username="product_editor_reader")
        Employee.objects.create(user=user, employee_code="PRODUCT_EDITOR_READER", display_name="只读产品")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="product_catalog", codename="view_productcatalog"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.save({}, version=current["ETag"]).status_code, 403)
        self.assertEqual(self.client.delete(f"{ROOT}names/{self.name.pk}/", HTTP_IF_MATCH=current["ETag"]).status_code, 403)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="product_catalog", codename="change_productcatalog"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        response = self.save({"name": "不能偷偷新增", "products": [{"item_number": "无新增权限"}]}, version=current["ETag"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.read().data, current.data)
        self.assertEqual(self.save({"products": [{"id": str(self.first.pk), "materials": ["铁"]}]}).status_code, 200)

    def test_session_batch_write_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        current = self.read()
        payload = {"name": self.name.name, "products": [{"id": str(self.first.pk), "thicknesses": ["0.8"]}]}
        self.assertEqual(client.patch(self.url, payload, format="json", HTTP_IF_MATCH=current["ETag"]).status_code, 403)
        client.get("/api/auth/me/")
        response = client.patch(self.url, payload, format="json", HTTP_IF_MATCH=current["ETag"], HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200, response.data)
