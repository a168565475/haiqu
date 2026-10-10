from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerTimelineEvent
from ..models import Inquiry
from . import test_inquiry_api


class InquiryPriorityTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def test_unset_high_low_clear_and_audit_preserve_business_status(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        self.assertEqual(created.data["data"]["priority"], "")
        tag = created["ETag"]
        for priority in ["HIGH", "LOW", ""]:
            response = self.client.post(f"/api/v1/inquiries/{inquiry_id}/priority/", {"priority": priority}, format="json", HTTP_IF_MATCH=tag)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"]["priority"], priority)
            self.assertEqual(response.data["data"]["status"], "DRAFT")
            self.assertNotEqual(response["ETag"], tag)
            tag = response["ETag"]
        self.assertEqual(AuditLog.objects.filter(object_id=inquiry_id, action="PRIORITY_CHANGED").count(), 3)
        self.assertEqual(CustomerTimelineEvent.objects.filter(source_id=inquiry_id, event_type="INQUIRY_PRIORITY_CHANGED").count(), 3)

    def test_invalid_missing_stale_and_idempotent_updates(self):
        created = self.create_inquiry(); inquiry_id = created.data["data"]["id"]; url = f"/api/v1/inquiries/{inquiry_id}/priority/"
        self.assertEqual(self.client.post(url, {"priority": "HIGH"}, format="json").status_code, 428)
        for payload in [{}, {"priority": "URGENT"}, {"priority": None}]:
            self.assertEqual(self.client.post(url, payload, format="json", HTTP_IF_MATCH=created["ETag"]).status_code, 400)
        response = self.client.post(url, {"priority": "MEDIUM"}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(url, {"priority": "LOW"}, format="json", HTTP_IF_MATCH=created["ETag"]).status_code, 412)
        unchanged = self.client.post(url, {"priority": "MEDIUM"}, format="json", HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(unchanged["ETag"], response["ETag"])
        self.assertEqual(AuditLog.objects.filter(object_id=inquiry_id, action="PRIORITY_CHANGED").count(), 1)

    def test_permission_and_scope_and_archive(self):
        created = self.create_inquiry(); inquiry_id = created.data["data"]["id"]
        Inquiry.objects.filter(pk=inquiry_id).update(archived_at=timezone.now())
        self.assertEqual(self.client.post(f"/api/v1/inquiries/{inquiry_id}/priority/", {"priority": "HIGH"}, format="json", HTTP_IF_MATCH=created["ETag"]).status_code, 404)
        hidden = Inquiry.objects.create(customer_account=self.other_customer, inquiry_number="INQ-PRIORITY-HIDDEN", subject="隐藏", received_at=timezone.now())
        self.assertEqual(self.client.post(f"/api/v1/inquiries/{hidden.pk}/priority/", {"priority": "HIGH"}, format="json", HTTP_IF_MATCH='"anything"').status_code, 404)
        self.client.force_authenticate(user=self.other_user)
        self.assertEqual(self.client.post(f"/api/v1/inquiries/{inquiry_id}/priority/", {"priority": "HIGH"}, format="json").status_code, 403)

    def test_filter_saved_view_export_and_database_constraint(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="preferences"))
        created = self.create_inquiry(); inquiry_id = created.data["data"]["id"]
        Inquiry.objects.filter(pk=inquiry_id).update(priority="HIGH")
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"priority": "HIGH"}).data["meta"]["total"], 1)
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"priority": "UNSET"}).data["meta"]["total"], 0)
        self.assertEqual(self.client.get("/api/v1/inquiries/", {"priority": "invalid"}).status_code, 400)
        self.assertIn("高", self.client.get("/api/v1/inquiries/export/", {"priority": "HIGH"}).content.decode("utf-8-sig"))
        saved = self.client.post("/api/v1/saved-views/", {"module_code": "INQUIRY", "view_name": "高优先级且已转报价", "filter_definition": {"priority": "HIGH", "has_quotation": "true"}, "column_definition": ["priority"], "sort_definition": []}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inquiry.objects.filter(pk=inquiry_id).update(priority="UNKNOWN")
