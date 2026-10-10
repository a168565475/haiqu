import csv
import io
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.preferences.models import SavedView
from ..models import Inquiry
from . import test_inquiry_api


class InquiryListGapTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def test_list_returns_real_budget_range_zero_and_missing_values(self):
        inquiry_id = self.create_inquiry().data["data"]["id"]
        Inquiry.objects.filter(pk=inquiry_id).update(
            estimated_amount_min="0.00", estimated_amount_max="1234567890123456.78",
            estimated_currency_code="USD",
        )
        response = self.client.get("/api/v1/inquiries/")
        self.assertEqual(response.status_code, 200)
        row = response.data["data"][0]
        self.assertEqual(row["estimated_amount_min"], "0.00")
        self.assertEqual(row["estimated_amount_max"], "1234567890123456.78")
        self.assertEqual(row["estimated_currency_code"], "USD")
        Inquiry.objects.filter(pk=inquiry_id).update(
            estimated_amount_min=None, estimated_amount_max=None, estimated_currency_code="",
        )
        row = self.client.get("/api/v1/inquiries/").data["data"][0]
        self.assertIsNone(row["estimated_amount_min"])
        self.assertIsNone(row["estimated_amount_max"])

    def test_export_respects_scope_filters_and_does_not_truncate_to_page(self):
        first = self.create_inquiry(subject="要导出的询盘一").data["data"]["inquiry_number"]
        second = self.create_inquiry(subject="要导出的询盘二").data["data"]["inquiry_number"]
        self.create_inquiry(subject="不匹配的记录")
        Inquiry.objects.create(
            customer_account=self.other_customer, inquiry_number="INQ-HIDDEN-EXPORT",
            subject="要导出的其他客户询盘", received_at=timezone.now(),
        )
        response = self.client.get("/api/v1/inquiries/export/", {"q": "要导出", "country_code": "CN", "page_size": 1, "page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 3)
        self.assertEqual({row[0] for row in rows[1:]}, {first, second})
        self.assertNotIn("INQ-HIDDEN-EXPORT", response.content.decode("utf-8-sig"))

    def test_export_neutralizes_formula_prefix_and_preserves_zero_amount(self):
        inquiry_id = self.create_inquiry().data["data"]["id"]
        self.customer.account_name = "  =1+1"
        self.customer.save(update_fields=["account_name"])
        Inquiry.objects.filter(pk=inquiry_id).update(estimated_amount_min="0.00", estimated_amount_max="0.00", estimated_currency_code="USD")
        response = self.client.get("/api/v1/inquiries/export/")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][1], "'  =1+1")
        self.assertEqual(rows[1][-3:], ["USD", "0.00", "0.00"])

    def test_export_requires_permission_and_valid_filters(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get("/api/v1/inquiries/export/").status_code, 403)

    def test_export_invalid_uuid_and_oversize_are_rejected(self):
        self.assertEqual(self.client.get("/api/v1/inquiries/export/", {"owner_employee_id": "invalid"}).status_code, 400)
        with patch("django.db.models.query.QuerySet.count", return_value=5001):
            self.assertEqual(self.client.get("/api/v1/inquiries/export/").status_code, 400)

    def test_country_saved_view_round_trip_stays_personal_and_rejects_unknown_fields(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="preferences"))
        payload = {"module_code": "INQUIRY", "view_name": "中国询盘", "filter_definition": {"country_code": "CN", "status": "NEW"}, "column_definition": ["country", "amount"], "sort_definition": ["-received_at"]}
        response = self.client.post("/api/v1/saved-views/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        saved = SavedView.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(saved.filter_definition["country_code"], "CN")
        self.assertEqual(saved.employee, self.employee)
        result = self.client.get("/api/v1/saved-views/", {"module_code": "INQUIRY"})
        self.assertEqual(result.data["data"][0]["filter_definition"]["country_code"], "CN")
        payload["view_name"] = "非法字段"
        payload["filter_definition"]["private_field"] = "secret"
        self.assertEqual(self.client.post("/api/v1/saved-views/", payload, format="json").status_code, 400)
        self.other_user.user_permissions.add(*Permission.objects.filter(content_type__app_label="preferences"))
        self.client.force_authenticate(user=self.other_user)
        self.assertEqual(self.client.get("/api/v1/saved-views/", {"module_code": "INQUIRY"}).data["data"], [])
