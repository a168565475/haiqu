from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.crm.models import CustomerTimelineEvent
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.reference_data.models import ReferenceDictionary

from ..models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerComplaint,
    CustomerComplaintAttachment,
    CustomerContact,
)


class ComplaintApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="complaint_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="COMPLAINT_API_USER",
            display_name="客诉接口测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="customers").exclude(
                codename="view_all_customer"
            )
        )
        self.other_user = user_model.objects.create_user(username="complaint_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="COMPLAINT_API_OTHER",
            display_name="其他客诉员工",
        )
        self.customer = self.create_customer("COMPLAINT-CUSTOMER-001", "客诉测试客户", self.employee)
        self.other_customer = self.create_customer(
            "COMPLAINT-CUSTOMER-002",
            "其他范围客户",
            self.other_employee,
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            display_name="采购经理",
        )
        self.type_item = ReferenceDictionary.objects.get(
            category_code="COMPLAINT_TYPE",
            item_code="QUALITY",
        )
        self.severity_item = ReferenceDictionary.objects.get(
            category_code="COMPLAINT_SEVERITY",
            item_code="GENERAL",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @staticmethod
    def create_customer(code, name, owner):
        customer = CustomerAccount.objects.create(
            account_code=code,
            account_name=name,
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=customer,
            employee=owner,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        return customer

    def complaint_payload(self, **overrides):
        payload = {
            "customer_id": str(self.customer.pk),
            "contact_id": str(self.contact.pk),
            "complaint_type_item_id": str(self.type_item.pk),
            "severity_item_id": str(self.severity_item.pk),
            "title": "产品到货后发现表面划伤",
            "source_order_reference": "SO-2026-TEST-001",
            "source_order_snapshot": {
                "order_date": "2026-08-20",
                "product_name": "户外折叠椅",
                "product_sku": "CHAIR-001",
            },
            "issue_description": "客户反馈部分产品表面有划伤，要求确认原因和补救方案。",
        }
        payload.update(overrides)
        return payload

    def create_complaint(self, **overrides):
        response = self.client.post("/api/v1/complaints/", self.complaint_payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def grant_only(self, *codenames):
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="customers", codename__in=codenames)
        )
        for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)

    def test_create_generates_number_sla_audit_timeline_and_summary_count(self):
        response = self.create_complaint(owner_employee_id=str(self.other_employee.pk))
        complaint = CustomerComplaint.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(complaint.complaint_code, r"^CS-\d{4}-\d{4,}$")
        self.assertEqual(complaint.status, "ACCEPTED")
        self.assertEqual(complaint.owner_employee, self.other_employee)
        self.assertEqual(complaint.original_customer_account, self.customer)
        self.assertEqual(response.data["data"]["created_by"]["id"], str(self.employee.pk))
        self.assertGreater(complaint.target_completion_at, complaint.first_response_due_at)
        self.assertIn("ETag", response)
        self.assertTrue(AuditLog.objects.filter(object_type="CUSTOMER_COMPLAINT", object_id=complaint.pk).exists())
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                event_type="CUSTOMER_COMPLAINT_CREATED",
            ).exists()
        )
        summary = self.client.get(f"/api/v1/customers/{self.customer.pk}/summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["counts"]["open_complaints"], 1)

    def test_options_are_dictionary_backed_and_list_respects_customer_scope(self):
        own = self.create_complaint()
        CustomerComplaint.objects.create(
            customer_account=self.other_customer,
            original_customer_account=self.other_customer,
            complaint_code="CS-2026-9999",
            complaint_type_item=self.type_item,
            severity_item=self.severity_item,
            title="范围外客诉",
            issue_description="不可见",
            owner_employee=self.other_employee,
            first_response_due_at=timezone.now() + timedelta(hours=24),
            target_completion_at=timezone.now() + timedelta(days=7),
        )

        options = self.client.get("/api/v1/complaints/options/")
        listing = self.client.get("/api/v1/complaints/")

        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(
            {item["display_name"] for item in options.data["data"]["severities"]},
            {"一般", "重要", "严重", "重大"},
        )
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["meta"]["total"], 1)
        self.assertEqual(listing.data["data"][0]["id"], own.data["data"]["id"])
        stats = self.client.get("/api/v1/complaints/stats/")
        self.assertEqual(stats.status_code, 200, stats.data)
        self.assertEqual(stats.data["data"]["waiting_customer_feedback"], 0)
        self.assertEqual(stats.data["data"]["closed_this_month"], 0)

    def test_unpublished_complaint_dictionary_item_is_rejected_but_current_history_is_preserved(self):
        draft_type = ReferenceDictionary.objects.create(
            dictionary_type=self.type_item.dictionary_type,
            category_code="COMPLAINT_TYPE",
            item_code="DRAFT_ONLY",
            display_name="尚未发布类型",
            sort_order=999,
        )
        rejected = self.client.post(
            "/api/v1/complaints/",
            self.complaint_payload(complaint_type_item_id=str(draft_type.pk)),
            format="json",
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)

        created = self.create_complaint()
        complaint = CustomerComplaint.objects.get(pk=created.data["data"]["id"])
        self.type_item.status = "INACTIVE"
        self.type_item.save(update_fields=["status", "updated_at"])
        preserved = self.client.patch(
            f"/api/v1/complaints/{complaint.pk}/",
            {"complaint_type_item_id": str(self.type_item.pk), "title": "保留历史停用类型"},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(complaint),
        )
        self.assertEqual(preserved.status_code, 200, preserved.data)

    def test_action_permissions_separate_view_create_process_and_close(self):
        self.grant_only("view_customercomplaint")
        self.assertEqual(self.client.get("/api/v1/complaints/").status_code, 200)
        self.assertEqual(
            self.client.post("/api/v1/complaints/", self.complaint_payload(), format="json").status_code,
            403,
        )

        self.grant_only("add_customercomplaint")
        created = self.client.post("/api/v1/complaints/", self.complaint_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        video = self.client.post(
            f"/api/v1/complaints/{created.data['data']['id']}/attachments/",
            {"file": SimpleUploadedFile("evidence.mp4", b"not-a-video", content_type="video/mp4")},
            format="multipart",
        )
        self.assertEqual(video.status_code, 400, video.data)

        complaint = CustomerComplaint.objects.get(pk=created.data["data"]["id"])
        complaint.status = "CUSTOMER_CONFIRMATION"
        complaint.save(update_fields=["status", "updated_at"])
        self.grant_only("process_customer_complaint")
        closed = self.client.post(
            f"/api/v1/complaints/{complaint.pk}/progress/",
            {"to_status": "CLOSED", "progress_note": "客户已经确认处理结果。"},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(complaint),
        )
        self.assertEqual(closed.status_code, 403, closed.data)

    def test_contact_must_belong_to_customer(self):
        other_contact = CustomerContact.objects.create(
            customer_account=self.other_customer,
            display_name="其他客户联系人",
        )
        response = self.client.post(
            "/api/v1/complaints/",
            self.complaint_payload(contact_id=str(other_contact.pk)),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_progress_requires_etag_and_enforces_linear_status(self):
        created = self.create_complaint()
        complaint_id = created.data["data"]["id"]
        missing_etag = self.client.post(
            f"/api/v1/complaints/{complaint_id}/progress/",
            {"to_status": "RESPONSIBILITY_CONFIRMATION", "progress_note": "完成初步确认"},
            format="json",
        )
        invalid = self.client.post(
            f"/api/v1/complaints/{complaint_id}/progress/",
            {"to_status": "CLOSED", "progress_note": "跳级关闭"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        accepted = self.client.post(
            f"/api/v1/complaints/{complaint_id}/progress/",
            {
                "to_status": "RESPONSIBILITY_CONFIRMATION",
                "progress_note": "已与仓库核实批次和包装记录。",
                "root_cause": "运输过程中外箱受压。",
                "responsibility": "承运环节待最终确认。",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )

        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data["data"]["status"], "RESPONSIBILITY_CONFIRMATION")
        self.assertIsNotNone(accepted.data["data"]["first_responded_at"])
        self.assertIn("Complaint-Progress-Id", accepted)

    def test_video_attachment_is_rejected(self):
        created = self.create_complaint()
        response = self.client.post(
            f"/api/v1/complaints/{created.data['data']['id']}/attachments/",
            {"file": SimpleUploadedFile("evidence.mp4", b"not-a-video", content_type="video/mp4")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(CustomerComplaint.objects.count(), 1)

    def test_clean_image_attachment_can_be_previewed_inline(self):
        created = self.create_complaint()
        complaint = CustomerComplaint.objects.get(pk=created.data["data"]["id"])
        with TemporaryDirectory() as media_root:
            storage_key = "tests/complaints/evidence.png"
            file_path = Path(media_root) / storage_key
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
            business_file = BusinessFile.objects.create(
                uploaded_by_employee=self.employee,
                original_name="evidence.png",
                storage_key=storage_key,
                content_type="image/png",
                size_bytes=file_path.stat().st_size,
                scan_status=FileScanStatus.CLEAN,
            )
            attachment = CustomerComplaintAttachment.objects.create(
                complaint=complaint,
                business_file=business_file,
                uploaded_by_employee=self.employee,
            )
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    f"/api/v1/complaints/{complaint.pk}/attachments/{attachment.pk}/preview/"
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response["Content-Disposition"], 'inline; filename="evidence.png"')
