from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee

from ..models import Supplier


class SupplierApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="supplier_admin")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SUPPLIER_ADMIN",
            display_name="供应商管理员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="procurement")
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def valid_payload(self, name="浙江弘达环保科技有限公司"):
        return {
            "supplier_type": "MATERIAL",
            "supplier_categories": ["FABRIC", "AUXILIARY"],
            "supplier_name": name,
            "payment_cycle": "MONTHLY",
            "remark": "长期合作供应商",
            "phone": "13586081399",
            "is_disabled": False,
        }

    def test_options_create_list_filters_and_stats(self):
        options = self.client.get("/api/v1/suppliers/options/")
        self.assertEqual(options.status_code, 200, options.data)
        next_number = options.data["data"]["next_supplier_number"]
        self.assertRegex(next_number, r"^GYS[0-9]{5}$")
        self.assertEqual(len(options.data["data"]["supplier_categories"]), 7)

        created = self.client.post("/api/v1/suppliers/", self.valid_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["supplier_number"], next_number)
        self.assertEqual(created.data["data"]["submitted_by_name"], "供应商管理员")
        self.assertTrue(created.headers.get("ETag"))

        searched = self.client.get("/api/v1/suppliers/?q=弘达&category=FABRIC")
        excluded = self.client.get("/api/v1/suppliers/?category=TUBE")
        stats = self.client.get("/api/v1/suppliers/stats/")
        self.assertEqual(searched.status_code, 200, searched.data)
        self.assertEqual(searched.data["meta"]["total"], 1)
        self.assertEqual(excluded.data["meta"]["total"], 0)
        self.assertEqual(stats.data["data"], {"total": 1, "material": 1, "finished": 0, "disabled": 0})

    def test_input_validation_rejects_empty_categories_and_bad_phone(self):
        payload = self.valid_payload()
        payload["supplier_categories"] = []
        empty_categories = self.client.post("/api/v1/suppliers/", payload, format="json")

        payload = self.valid_payload()
        payload["phone"] = "联系电话abc"
        bad_phone = self.client.post("/api/v1/suppliers/", payload, format="json")

        self.assertEqual(empty_categories.status_code, 400)
        self.assertIn("supplier_categories", empty_categories.data["error"]["field_errors"])
        self.assertEqual(bad_phone.status_code, 400)
        self.assertIn("phone", bad_phone.data["error"]["field_errors"])

    def test_update_requires_etag_and_writes_audit_log(self):
        created = self.client.post("/api/v1/suppliers/", self.valid_payload(), format="json")
        supplier_id = created.data["data"]["id"]
        detail_url = f"/api/v1/suppliers/{supplier_id}/"
        etag = self.client.get(detail_url)["ETag"]

        missing = self.client.patch(detail_url, {"remark": "不应更新"}, format="json")
        updated = self.client.patch(
            detail_url,
            {"remark": "已更新备注", "is_disabled": True},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        stale = self.client.patch(
            detail_url,
            {"remark": "过期更新"},
            format="json",
            HTTP_IF_MATCH=etag,
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertTrue(updated.data["data"]["is_disabled"])
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="SUPPLIER",
                object_id=supplier_id,
                action="UPDATED",
            ).exists()
        )

    def test_detail_reports_exact_duplicate_supplier_names(self):
        first = self.client.post("/api/v1/suppliers/", self.valid_payload(), format="json")
        second = self.client.post("/api/v1/suppliers/", self.valid_payload(), format="json")

        detail = self.client.get(f"/api/v1/suppliers/{first.data['data']['id']}/")

        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(len(detail.data["data"]["duplicate_suppliers"]), 1)
        self.assertEqual(
            detail.data["data"]["duplicate_suppliers"][0]["supplier_number"],
            second.data["data"]["supplier_number"],
        )

    def test_supplier_cannot_be_physically_deleted(self):
        created = self.client.post("/api/v1/suppliers/", self.valid_payload(), format="json")
        supplier = Supplier.objects.get(pk=created.data["data"]["id"])
        with self.assertRaisesMessage(ValidationError, "供应商不允许物理删除"):
            supplier.delete()

    def test_view_permission_is_required(self):
        self.user.user_permissions.clear()
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.get("/api/v1/suppliers/")

        self.assertEqual(response.status_code, 403)
