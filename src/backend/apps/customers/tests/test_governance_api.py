from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.crm.models import (
    CommunicationContactParticipant,
    CommunicationInquiryLink,
    CommunicationSampleRequestLink,
    CustomerCommunication,
)
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.quotations.models import Quotation
from apps.reference_data.models import ReferenceDictionary
from apps.samples.models import SampleRequest

from ..models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerComplaint,
    CustomerDataAccessGrant,
    CustomerMergeOperation,
    CustomerTransactionEntity,
)


class CustomerGovernanceApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="governance_user")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="GOVERNANCE_USER", display_name="治理测试员工"
        )
        self.new_owner = Employee.objects.create(
            employee_code="GOVERNANCE_NEW_OWNER", display_name="新负责人"
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=["customers", "inquiries", "audit", "preferences"])
            .exclude(codename__in=["view_all_customer", "view_all_auditlog"])
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_customer(self, code, name):
        customer = CustomerAccount.objects.create(
            account_code=code, account_name=name, primary_country_code="CN"
        )
        CustomerAssignment.objects.create(
            customer_account=customer, employee=self.employee,
            assignment_role="PRIMARY_OWNER", effective_from=timezone.now(),
        )
        return customer

    def create_complaint(self, customer, owner, code):
        now = timezone.now()
        return CustomerComplaint.objects.create(
            customer_account=customer,
            original_customer_account=customer,
            complaint_code=code,
            complaint_type_item=ReferenceDictionary.objects.get(
                category_code="COMPLAINT_TYPE", item_code="QUALITY"
            ),
            severity_item=ReferenceDictionary.objects.get(
                category_code="COMPLAINT_SEVERITY", item_code="GENERAL"
            ),
            title="治理流程客诉",
            issue_description="验证客户转移和合并行为。",
            owner_employee=owner,
            first_response_due_at=now + timedelta(hours=24),
            target_completion_at=now + timedelta(days=7),
        )

    def test_transfer_approval_preserves_owner_history(self):
        customer = self.create_customer("GOV_TRANSFER", "转移客户")
        complaint = self.create_complaint(customer, self.employee, "CS-2026-9101")
        created = self.client.post(
            "/api/v1/customer-transfer-requests/",
            {"customer_id": str(customer.pk), "to_employee_id": str(self.new_owner.pk), "reason": "区域调整"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        approved = self.client.post(
            f"/api/v1/customer-transfer-requests/{created.data['data']['id']}/approve/",
            {"decision_note": "确认转交"}, format="json", HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        assignments = customer.assignments.order_by("effective_from")
        self.assertEqual(assignments.count(), 2)
        self.assertIsNotNone(assignments.first().effective_to)
        self.assertEqual(assignments.last().employee_id, self.new_owner.pk)
        self.assertIsNone(assignments.last().effective_to)
        complaint.refresh_from_db()
        self.assertEqual(complaint.owner_employee_id, self.employee.pk)

    def test_customer_access_grant_and_revoke_use_exact_permission(self):
        customer = self.create_customer("GOV_GRANT", "授权客户")
        created = self.client.post(
            f"/api/v1/customers/{customer.pk}/access-grants/",
            {
                "employee_id": str(self.new_owner.pk),
                "permission_code": "inquiries.view_inquiry",
                "reason": "临时协助询价",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        grant = CustomerDataAccessGrant.objects.get(pk=created.data["data"]["id"])
        self.assertEqual(grant.permission.codename, "view_inquiry")

        revoked = self.client.post(
            f"/api/v1/customer-access-grants/{grant.pk}/revoke/",
            {}, format="json", HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(revoked.status_code, 200, revoked.data)
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)
        self.assertIsNotNone(grant.effective_to)

    def test_duplicate_case_decision_and_merge_are_transactional(self):
        survivor = self.create_customer("GOV_SURVIVOR", "合并后客户")
        source = self.create_customer("GOV_SOURCE", "来源客户")
        complaint = self.create_complaint(source, self.new_owner, "CS-2026-9102")
        entity = CustomerTransactionEntity.objects.create(
            customer_account=source, entity_code="GOV_SOURCE_ENTITY", legal_name="来源主体"
        )
        contact = CustomerContact.objects.create(
            customer_account=source, transaction_entity=entity, display_name="来源联系人"
        )
        successor_contact = CustomerContact.objects.create(
            customer_account=source, transaction_entity=entity, source_contact=contact,
            display_name="来源联系人接任者",
        )
        inquiry = Inquiry.objects.create(
            customer_account=source, transaction_entity=entity, customer_contact=contact,
            owner_employee=self.employee, inquiry_number="GOV-INQ-001", subject="合并询价",
            received_at=timezone.now(),
        )
        quotation = Quotation.objects.create(
            customer_account=source, transaction_entity=entity, source_inquiry=inquiry,
            owner_employee=self.employee, quotation_number="GOV-QUO-001", subject="合并报价",
        )
        sample = SampleRequest.objects.create(
            customer_account=source, transaction_entity=entity, customer_contact=contact,
            owner_employee=self.employee, source_inquiry=inquiry,
            request_number="GOV-SAM-001", purpose="合并测试", requested_at=timezone.now(),
        )
        communication = CustomerCommunication.objects.create(
            customer_account=source, created_by_employee=self.employee, communication_type="EMAIL",
            direction="OUTBOUND", subject="合并沟通", content="测试", occurred_at=timezone.now(),
        )
        CommunicationContactParticipant.objects.create(
            communication=communication, customer_contact=contact, participant_role="RECIPIENT"
        )
        CommunicationInquiryLink.objects.create(communication=communication, inquiry=inquiry)
        CommunicationSampleRequestLink.objects.create(communication=communication, sample_request=sample)
        created = self.client.post(
            "/api/v1/customer-duplicate-cases/",
            {
                "matching_strategy_version": "MANUAL_V1",
                "notes": "人工发现重复",
                "candidates": [
                    {"customer_id": str(survivor.pk), "confidence_score": "1.0000", "matched_fields": {"name": True}},
                    {"customer_id": str(source.pk), "confidence_score": "0.9500", "matched_fields": {"name": True}},
                ],
            }, format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        case_id = created.data["data"]["id"]
        candidates = {item["customer"]["id"]: item for item in created.data["data"]["candidates"]}

        survivor_decision = self.client.post(
            f"/api/v1/customer-duplicate-candidates/{candidates[str(survivor.pk)]['id']}/decide/",
            {"decision": "SURVIVOR"}, format="json",
            HTTP_IF_MATCH=candidates[str(survivor.pk)]["etag"],
        )
        source_decision = self.client.post(
            f"/api/v1/customer-duplicate-candidates/{candidates[str(source.pk)]['id']}/decide/",
            {"decision": "DUPLICATE"}, format="json",
            HTTP_IF_MATCH=candidates[str(source.pk)]["etag"],
        )
        self.assertEqual(survivor_decision.status_code, 200, survivor_decision.data)
        self.assertEqual(source_decision.status_code, 200, source_decision.data)

        case_detail = self.client.get(f"/api/v1/customer-duplicate-cases/{case_id}/")
        preview = self.client.post(
            f"/api/v1/customer-duplicate-cases/{case_id}/merge-preview/",
            {
                "survivor_customer_id": str(survivor.pk), "source_customer_ids": [str(source.pk)],
                "reason": "确认同一客户", "field_decisions": {"notes": str(source.pk)},
            }, format="json",
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["data"]["move_counts"]["transaction_entities"], 1)
        self.assertEqual(preview.data["data"]["move_counts"]["complaints"], 1)

        merged = self.client.post(
            f"/api/v1/customer-duplicate-cases/{case_id}/merge/",
            {
                "survivor_customer_id": str(survivor.pk), "source_customer_ids": [str(source.pk)],
                "reason": "确认同一客户", "field_decisions": {"notes": str(source.pk)},
            }, format="json", HTTP_IF_MATCH=case_detail.headers["ETag"],
        )
        self.assertEqual(merged.status_code, 201, merged.data)
        source.refresh_from_db()
        entity.refresh_from_db()
        contact.refresh_from_db()
        successor_contact.refresh_from_db()
        inquiry.refresh_from_db()
        quotation.refresh_from_db()
        sample.refresh_from_db()
        communication.refresh_from_db()
        complaint.refresh_from_db()
        self.assertIsNotNone(source.archived_at)
        self.assertEqual(entity.customer_account_id, survivor.pk)
        self.assertEqual(contact.customer_account_id, survivor.pk)
        self.assertEqual(successor_contact.customer_account_id, survivor.pk)
        self.assertEqual(successor_contact.source_contact_id, contact.pk)
        self.assertEqual(inquiry.customer_account_id, survivor.pk)
        self.assertEqual(quotation.customer_account_id, survivor.pk)
        self.assertEqual(sample.customer_account_id, survivor.pk)
        self.assertEqual(communication.customer_account_id, survivor.pk)
        self.assertEqual(complaint.customer_account_id, survivor.pk)
        self.assertEqual(complaint.original_customer_account_id, source.pk)
        self.assertEqual(complaint.owner_employee_id, self.new_owner.pk)
        self.assertTrue(CustomerMergeOperation.objects.filter(pk=merged.data["data"]["id"], status="COMPLETED").exists())
        self.assertTrue(AuditLog.objects.filter(object_type="CUSTOMER_MERGE_OPERATION", action="COMPLETED").exists())
        merge_detail = self.client.get(f"/api/v1/customer-merges/{merged.data['data']['id']}/")
        resolved_case = self.client.get(f"/api/v1/customer-duplicate-cases/{case_id}/")
        self.assertEqual(merge_detail.status_code, 200, merge_detail.data)
        self.assertEqual(resolved_case.status_code, 200, resolved_case.data)
