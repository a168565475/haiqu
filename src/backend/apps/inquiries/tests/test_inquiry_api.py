from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import CustomerTimelineEvent
from apps.customers.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerFileLink,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from apps.workflow.models import BusinessTask, SlaPolicy, SlaTrackingStatus

from ..models import Inquiry, InquiryItem, InquiryTaskLink


class InquiryApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="inquiry_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="INQUIRY_API_USER",
            display_name="询价接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="inquiry_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="INQUIRY_API_OTHER",
            display_name="其他询价测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=["inquiries", "workflow"])
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("INQUIRY_CUSTOMER", "询价客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_INQUIRY_CUSTOMER",
            "其他询价客户",
            self.other_employee,
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="INQUIRY_ENTITY",
            legal_name="询价交易主体",
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            display_name="询价联系人",
        )

    def create_customer(self, code, name, owner):
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

    def inquiry_payload(self, **overrides):
        payload = {
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "customer_contact_id": str(self.contact.pk),
            "owner_employee_id": str(self.employee.pk),
            "inquiry_source": "EMAIL",
            "subject": "测试询价",
            "description": "需要核价",
            "received_at": timezone.now().isoformat(),
            "items": [
                {
                    "product_description": "测试产品",
                    "quantity": "10.0000",
                    "unit_code": "PCS",
                    "target_currency_code": "USD",
                }
            ],
        }
        payload.update(overrides)
        return payload

    def create_inquiry(self, **overrides):
        response = self.client.post("/api/v1/inquiries/", self.inquiry_payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_nested_items_generates_number_audit_and_timeline(self):
        response = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(inquiry.inquiry_number, r"^INQ-\d{6}-\d{6,}$")
        self.assertEqual(inquiry.items.get().line_number, 1)
        self.assertEqual(inquiry.status, "DRAFT")
        self.assertIn("ETag", response)
        self.assertTrue(
            AuditLog.objects.filter(object_type="INQUIRY", object_id=inquiry.pk, action="CREATED").exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=inquiry.pk,
                event_type="INQUIRY_CREATED",
            ).exists()
        )

    def test_cross_customer_entity_is_rejected_without_leaking_record(self):
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="FOREIGN_INQUIRY_ENTITY",
            legal_name="其他客户主体",
        )
        response = self.client.post(
            "/api/v1/inquiries/",
            self.inquiry_payload(transaction_entity_id=str(foreign_entity.pk)),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("transaction_entity_id", response.data["error"]["field_errors"])

    def test_list_does_not_leak_unassigned_customer_inquiries(self):
        visible = Inquiry.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            inquiry_number="VISIBLE_INQUIRY",
            subject="可见询价",
            received_at=timezone.now(),
        )
        hidden = Inquiry.objects.create(
            customer_account=self.other_customer,
            owner_employee=self.other_employee,
            inquiry_number="HIDDEN_INQUIRY",
            subject="不可见询价",
            received_at=timezone.now(),
        )

        response = self.client.get("/api/v1/inquiries/")
        returned_ids = {item["id"] for item in response.data["data"]}

        self.assertIn(str(visible.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_draft_update_requires_etag_and_submitted_inquiry_is_read_only(self):
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        url = f"/api/v1/inquiries/{inquiry_id}/"

        missing = self.client.patch(url, {"subject": "缺少 ETag"}, format="json")
        updated = self.client.patch(
            url,
            {"subject": "已更新标题"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        submitted = self.client.post(
            f"{url}submit/",
            {"note": "资料完整"},
            format="json",
            HTTP_IF_MATCH=updated.headers["ETag"],
        )
        rejected = self.client.patch(
            url,
            {"subject": "提交后修改"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(rejected.status_code, 409, rejected.data)

    def test_item_crud_uses_parent_etag_and_locks_after_submit(self):
        created = self.create_inquiry(items=[])
        inquiry_id = created.data["data"]["id"]
        items_url = f"/api/v1/inquiries/{inquiry_id}/items/"
        added = self.client.post(
            items_url,
            {
                "product_description": "新增产品",
                "quantity": "2.0000",
                "unit_code": "PCS",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        item_id = added.data["data"]["id"]
        stale = self.client.patch(
            f"/api/v1/inquiry-items/{item_id}/",
            {"quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        changed = self.client.patch(
            f"/api/v1/inquiry-items/{item_id}/",
            {"quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=added.headers["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/inquiries/{inquiry_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=changed.headers["ETag"],
        )
        locked = self.client.delete(
            f"/api/v1/inquiry-items/{item_id}/",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(locked.status_code, 409, locked.data)

    def test_state_machine_creates_and_completes_sla(self):
        SlaPolicy.objects.create(
            policy_code="INQUIRY_STANDARD",
            display_name="询价标准 SLA",
            target_type="INQUIRY",
            response_minutes=30,
            resolution_minutes=120,
            is_enabled=True,
        )
        created = self.create_inquiry()
        inquiry_id = created.data["data"]["id"]
        base = f"/api/v1/inquiries/{inquiry_id}/"
        submitted = self.client.post(base + "submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])
        started = self.client.post(base + "start/", {}, format="json", HTTP_IF_MATCH=submitted.headers["ETag"])
        quoted = self.client.post(
            base + "mark-quoted/", {}, format="json", HTTP_IF_MATCH=started.headers["ETag"]
        )

        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(quoted.status_code, 200, quoted.data)
        inquiry = Inquiry.objects.get(pk=inquiry_id)
        tracking = inquiry.sla_links.get().sla_tracking
        self.assertEqual(tracking.tracking_data["target_kind"], "RESOLUTION")
        self.assertEqual(tracking.status, SlaTrackingStatus.MET)
        self.assertIsNotNone(tracking.completed_at)

    def test_submit_without_items_and_invalid_transition_are_rejected(self):
        created = self.create_inquiry(items=[])
        base = f"/api/v1/inquiries/{created.data['data']['id']}/"
        submit = self.client.post(base + "submit/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])
        start = self.client.post(base + "start/", {}, format="json", HTTP_IF_MATCH=created.headers["ETag"])

        self.assertEqual(submit.status_code, 409, submit.data)
        self.assertEqual(start.status_code, 409, start.data)

    def test_file_link_prevents_cross_customer_reuse_and_tasks_are_queryable(self):
        created = self.create_inquiry()
        inquiry = Inquiry.objects.get(pk=created.data["data"]["id"])
        available_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="inquiry.pdf",
            storage_key="tests/inquiries/inquiry.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        foreign_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="foreign.pdf",
            storage_key="tests/inquiries/foreign.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        CustomerFileLink.objects.create(
            customer_account=self.other_customer,
            business_file=foreign_file,
            file_role="ATTACHMENT",
        )
        linked = self.client.post(
            f"/api/v1/inquiries/{inquiry.pk}/files/",
            {"file_id": str(available_file.pk), "file_role": "ATTACHMENT"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        rejected = self.client.post(
            f"/api/v1/inquiries/{inquiry.pk}/files/",
            {"file_id": str(foreign_file.pk), "file_role": "ATTACHMENT"},
            format="json",
            HTTP_IF_MATCH=linked.headers["ETag"],
        )
        task = BusinessTask.objects.create(
            assignee_employee=self.employee,
            created_by_employee=self.employee,
            title="处理询价",
        )
        InquiryTaskLink.objects.create(inquiry=inquiry, business_task=task)
        tasks = self.client.get(f"/api/v1/inquiries/{inquiry.pk}/tasks/")

        self.assertEqual(linked.status_code, 201, linked.data)
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("file_id", rejected.data["error"]["field_errors"])
        self.assertEqual(tasks.status_code, 200, tasks.data)
        self.assertEqual(tasks.data["data"][0]["id"], str(task.pk))
