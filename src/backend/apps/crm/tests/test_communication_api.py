from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.customers.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerFileLink,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.quotations.models import Quotation, QuotationVersion
from apps.samples.models import SampleRequest

from ..models import CustomerCommunication, CustomerTimelineEvent


class CommunicationApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="communication_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="COMMUNICATION_API_USER",
            display_name="沟通接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="communication_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="COMMUNICATION_API_OTHER",
            display_name="其他沟通测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="crm")
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("COMM_CUSTOMER", "沟通客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_COMM_CUSTOMER",
            "其他沟通客户",
            self.other_employee,
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

    def test_create_communication_writes_participants_file_audit_and_timeline(self):
        contact = CustomerContact.objects.create(
            customer_account=self.customer,
            display_name="沟通联系人",
        )
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="meeting.txt",
            storage_key="tests/communication/meeting.txt",
            content_type="text/plain",
            size_bytes=12,
            scan_status="CLEAN",
        )
        entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="COMMUNICATION_TEST_ENTITY",
            legal_name="沟通测试主体",
        )
        inquiry = Inquiry.objects.create(
            customer_account=self.customer,
            transaction_entity=entity,
            customer_contact=contact,
            owner_employee=self.employee,
            inquiry_number="COMMUNICATION_TEST_INQUIRY",
            subject="沟通测试询价",
            received_at=timezone.now(),
        )
        quotation = Quotation.objects.create(
            customer_account=self.customer,
            transaction_entity=entity,
            source_inquiry=inquiry,
            owner_employee=self.employee,
            quotation_number="COMMUNICATION_TEST_QUOTE",
            subject="沟通测试报价",
        )
        quotation_version = QuotationVersion.objects.create(
            quotation=quotation,
            version_number=1,
            currency_code="USD",
        )
        sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            transaction_entity=entity,
            customer_contact=contact,
            owner_employee=self.employee,
            request_number="COMMUNICATION_TEST_SAMPLE",
            requested_at=timezone.now(),
        )

        response = self.client.post(
            "/api/v1/communications/",
            {
                "customer_account_id": str(self.customer.pk),
                "communication_type": "EMAIL",
                "direction": "INBOUND",
                "subject": "价格沟通",
                "content": "客户询问最新价格。",
                "occurred_at": timezone.now().isoformat(),
                "employee_participant_ids": [str(self.other_employee.pk)],
                "contact_participant_ids": [str(contact.pk)],
                "inquiry_id": str(inquiry.pk),
                "quotation_version_id": str(quotation_version.pk),
                "sample_request_id": str(sample_request.pk),
                "file_ids": [str(business_file.pk)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        communication = CustomerCommunication.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(communication.employee_participants.count(), 2)
        self.assertEqual(communication.contact_participants.count(), 1)
        self.assertEqual(communication.file_links.count(), 1)
        self.assertEqual(communication.inquiry_links.count(), 1)
        self.assertEqual(communication.quotation_links.count(), 1)
        self.assertEqual(communication.sample_links.count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="CUSTOMER_COMMUNICATION",
                object_id=communication.pk,
                action="CREATED",
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=communication.pk,
                event_type="COMMUNICATION_CREATED",
            ).exists()
        )
        self.assertIn("ETag", response)

    def test_cross_customer_contact_is_rejected(self):
        foreign_contact = CustomerContact.objects.create(
            customer_account=self.other_customer,
            display_name="其他客户联系人",
        )

        response = self.client.post(
            "/api/v1/communications/",
            {
                "customer_account_id": str(self.customer.pk),
                "communication_type": "PHONE",
                "direction": "OUTBOUND",
                "content": "测试跨客户联系人。",
                "occurred_at": timezone.now().isoformat(),
                "contact_participant_ids": [str(foreign_contact.pk)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("contact_participant_ids", response.data["error"]["field_errors"])

    def test_file_linked_to_another_customer_is_rejected(self):
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="other.pdf",
            storage_key="tests/communication/other.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        CustomerFileLink.objects.create(
            customer_account=self.other_customer,
            business_file=business_file,
            file_role="ATTACHMENT",
        )

        response = self.client.post(
            "/api/v1/communications/",
            {
                "customer_account_id": str(self.customer.pk),
                "communication_type": "EMAIL",
                "direction": "INBOUND",
                "content": "测试跨客户附件。",
                "occurred_at": timezone.now().isoformat(),
                "file_ids": [str(business_file.pk)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file_ids", response.data["error"]["field_errors"])

    def test_list_does_not_leak_unassigned_customer_communications(self):
        visible = CustomerCommunication.objects.create(
            customer_account=self.customer,
            created_by_employee=self.employee,
            communication_type="EMAIL",
            direction="INBOUND",
            content="可见沟通",
            occurred_at=timezone.now(),
        )
        hidden = CustomerCommunication.objects.create(
            customer_account=self.other_customer,
            created_by_employee=self.other_employee,
            communication_type="EMAIL",
            direction="INBOUND",
            content="不可见沟通",
            occurred_at=timezone.now(),
        )

        response = self.client.get("/api/v1/communications/")

        returned_ids = {item["id"] for item in response.data["data"]}
        self.assertIn(str(visible.pk), returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_update_and_archive_require_current_etag(self):
        communication = CustomerCommunication.objects.create(
            customer_account=self.customer,
            created_by_employee=self.employee,
            communication_type="MEETING",
            direction="OUTBOUND",
            subject="修改前",
            content="会议记录",
            occurred_at=timezone.now(),
        )
        url = f"/api/v1/communications/{communication.pk}/"
        etag = self.client.get(url).headers["ETag"]

        missing = self.client.patch(url, {"subject": "缺少 ETag"}, format="json")
        updated = self.client.patch(
            url,
            {"subject": "修改后"},
            format="json",
            HTTP_IF_MATCH=etag,
        )
        archived = self.client.post(
            f"{url}archive/",
            {"reason": "记录作废"},
            format="json",
            HTTP_IF_MATCH=updated.headers["ETag"],
        )

        self.assertEqual(missing.status_code, 428)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(archived.status_code, 200, archived.data)
        communication.refresh_from_db()
        self.assertIsNotNone(communication.archived_at)

    def test_customer_timeline_is_scoped_and_cursor_paginated(self):
        CustomerTimelineEvent.objects.create(
            customer_account=self.customer,
            event_key="test:timeline:visible",
            source_type="CUSTOMER_ACCOUNT",
            source_id=self.customer.pk,
            event_type="CUSTOMER_UPDATED",
            title="可见事件",
            occurred_at=timezone.now(),
        )

        response = self.client.get(f"/api/v1/customers/{self.customer.pk}/timeline/")
        hidden = self.client.get(f"/api/v1/customers/{self.other_customer.pk}/timeline/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["title"], "可见事件")
        self.assertIn("next", response.data["meta"])
        self.assertEqual(hidden.status_code, 404)
