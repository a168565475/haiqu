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
    CustomerEntityAddress,
    CustomerTransactionEntity,
)
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.workflow.models import ApprovalStatus

from ..models import Quotation, QuotationTemplate, QuotationVersionStatus


class QuotationApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="quotation_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="QUOTATION_API_USER",
            display_name="报价接口测试员工",
        )
        self.approver_user = user_model.objects.create_user(username="quotation_approver")
        self.approver = Employee.objects.create(
            user=self.approver_user,
            employee_code="QUOTATION_APPROVER",
            display_name="报价审批员工",
        )
        self.other_user = user_model.objects.create_user(username="quotation_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="QUOTATION_OTHER",
            display_name="其他报价员工",
        )
        permissions = Permission.objects.filter(
            content_type__app_label__in=["quotations", "workflow"]
        )
        self.user.user_permissions.set(permissions)
        self.approver_user.user_permissions.set(permissions)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("QUOTE_CUSTOMER", "报价客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_QUOTE_CUSTOMER",
            "其他报价客户",
            self.other_employee,
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="QUOTE_ENTITY",
            legal_name="报价交易主体",
            registration_country_code="CN",
        )
        self.address = CustomerEntityAddress.objects.create(
            transaction_entity=self.entity,
            address_code="QUOTE_ADDRESS",
            country_code="CN",
            city="深圳",
            address_line1="测试路 1 号",
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            display_name="报价联系人",
        )
        self.inquiry = Inquiry.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            customer_contact=self.contact,
            owner_employee=self.employee,
            inquiry_number="QUOTE_SOURCE_INQUIRY",
            subject="报价来源询价",
            received_at=timezone.now(),
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

    def create_quotation(self):
        response = self.client.post(
            "/api/v1/quotations/",
            {
                "customer_account_id": str(self.customer.pk),
                "transaction_entity_id": str(self.entity.pk),
                "source_inquiry_id": str(self.inquiry.pk),
                "owner_employee_id": str(self.employee.pk),
                "subject": "标准报价",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def create_version(self, quotation_id, quotation_etag, template=None, from_version=None):
        payload = {"currency_code": "USD", "language_code": "zh-hans"}
        if template:
            payload["quotation_template_id"] = str(template.pk)
        if from_version:
            payload = {"from_version_id": str(from_version)}
        response = self.client.post(
            f"/api/v1/quotations/{quotation_id}/versions/",
            payload,
            format="json",
            HTTP_IF_MATCH=quotation_etag,
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def add_line(self, version_id, etag):
        response = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/lines/",
            {
                "product_description_snapshot": "测试产品",
                "specification_snapshot": "规格 A",
                "quantity": "10.0000",
                "unit_code": "PCS",
                "unit_price": "20.0000",
                "discount_rate": "0.100000",
            },
            format="json",
            HTTP_IF_MATCH=etag,
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def lock_version(self, version_id, etag):
        return self.client.post(
            f"/api/v1/quotation-versions/{version_id}/lock/",
            {
                "address_id": str(self.address.pk),
                "contact_id": str(self.contact.pk),
                "tax_rate": "0.100000",
                "terms": {"payment": "T/T 30 days"},
            },
            format="json",
            HTTP_IF_MATCH=etag,
        )

    def test_create_quotation_generates_number_audit_and_timeline(self):
        response = self.create_quotation()
        quotation = Quotation.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(quotation.quotation_number, r"^QUO-\d{6}-\d{6,}$")
        self.assertEqual(quotation.outcome_status, "OPEN")
        self.assertTrue(
            AuditLog.objects.filter(object_type="QUOTATION", object_id=quotation.pk, action="CREATED").exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=quotation.pk,
                event_type="QUOTATION_CREATED",
            ).exists()
        )

    def test_list_does_not_leak_unassigned_customer_quotations(self):
        visible_response = self.create_quotation()
        hidden_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="HIDDEN_QUOTE_ENTITY",
            legal_name="隐藏主体",
        )
        hidden = Quotation.objects.create(
            customer_account=self.other_customer,
            transaction_entity=hidden_entity,
            owner_employee=self.other_employee,
            quotation_number="HIDDEN_QUOTATION",
            subject="不可见报价",
        )

        response = self.client.get("/api/v1/quotations/")
        returned_ids = {item["id"] for item in response.data["data"]}

        self.assertIn(visible_response.data["data"]["id"], returned_ids)
        self.assertNotIn(str(hidden.pk), returned_ids)

    def test_line_total_tiers_lock_and_amounts_are_server_calculated(self):
        quotation = self.create_quotation()
        quotation_id = quotation.data["data"]["id"]
        version = self.create_version(quotation_id, quotation.headers["ETag"])
        version_id = version.data["data"]["id"]
        line = self.add_line(version_id, version.headers["ETag"])
        line_id = line.data["data"]["id"]
        tier = self.client.post(
            f"/api/v1/quotation-lines/{line_id}/quantity-tiers/",
            {"min_quantity": "1.0000", "max_quantity": "100.0000", "unit_price": "19.0000"},
            format="json",
            HTTP_IF_MATCH=line.headers["ETag"],
        )
        locked = self.lock_version(version_id, tier.headers["ETag"])
        locked_line = self.client.patch(
            f"/api/v1/quotation-lines/{line_id}/",
            {"unit_price": "1.0000"},
            format="json",
            HTTP_IF_MATCH=locked.headers["ETag"],
        )

        self.assertEqual(tier.status_code, 201, tier.data)
        self.assertEqual(locked.status_code, 200, locked.data)
        self.assertEqual(locked.data["data"]["subtotal_amount"], "180.0000")
        self.assertEqual(locked.data["data"]["discount_amount"], "20.0000")
        self.assertEqual(locked.data["data"]["tax_amount"], "18.0000")
        self.assertEqual(locked.data["data"]["total_amount"], "198.0000")
        self.assertEqual(locked_line.status_code, 409, locked_line.data)

    def test_overlapping_quantity_tier_is_rejected(self):
        quotation = self.create_quotation()
        version = self.create_version(quotation.data["data"]["id"], quotation.headers["ETag"])
        line = self.add_line(version.data["data"]["id"], version.headers["ETag"])
        url = f"/api/v1/quotation-lines/{line.data['data']['id']}/quantity-tiers/"
        first = self.client.post(
            url,
            {"min_quantity": "1", "max_quantity": "100", "unit_price": "19"},
            format="json",
            HTTP_IF_MATCH=line.headers["ETag"],
        )
        overlap = self.client.post(
            url,
            {"min_quantity": "50", "max_quantity": "150", "unit_price": "18"},
            format="json",
            HTTP_IF_MATCH=first.headers["ETag"],
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(overlap.status_code, 409, overlap.data)

    def test_copy_version_copies_lines_and_tiers_with_new_ids(self):
        quotation = self.create_quotation()
        quotation_id = quotation.data["data"]["id"]
        first = self.create_version(quotation_id, quotation.headers["ETag"])
        line = self.add_line(first.data["data"]["id"], first.headers["ETag"])
        tier = self.client.post(
            f"/api/v1/quotation-lines/{line.data['data']['id']}/quantity-tiers/",
            {"min_quantity": "1", "unit_price": "18"},
            format="json",
            HTTP_IF_MATCH=line.headers["ETag"],
        )
        quotation_etag = self.client.get(f"/api/v1/quotations/{quotation_id}/").headers["ETag"]
        copied = self.create_version(
            quotation_id,
            quotation_etag,
            from_version=first.data["data"]["id"],
        )

        self.assertEqual(copied.data["data"]["version_number"], 2)
        self.assertEqual(len(copied.data["data"]["lines"]), 1)
        self.assertNotEqual(copied.data["data"]["lines"][0]["id"], line.data["data"]["id"])
        self.assertEqual(len(copied.data["data"]["lines"][0]["quantity_tiers"]), 1)

    def test_required_approval_blocks_issue_until_approver_accepts(self):
        template = QuotationTemplate.objects.create(
            template_code="APPROVAL_TEMPLATE",
            template_name="需审批模板",
            requires_approval=True,
        )
        quotation = self.create_quotation()
        version = self.create_version(
            quotation.data["data"]["id"], quotation.headers["ETag"], template=template
        )
        version_id = version.data["data"]["id"]
        line = self.add_line(version_id, version.headers["ETag"])
        locked = self.lock_version(version_id, line.headers["ETag"])
        submitted = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/submit-approval/",
            {"approver_employee_id": str(self.approver.pk), "reason": "请审批价格"},
            format="json",
            HTTP_IF_MATCH=locked.headers["ETag"],
        )
        blocked = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/issue/",
            {},
            format="json",
            HTTP_IF_MATCH=submitted.headers["Quotation-Version-ETag"],
        )
        self.client.force_authenticate(user=self.approver_user)
        approved = self.client.post(
            f"/api/v1/approvals/{submitted.data['data']['id']}/approve/",
            {"note": "价格合理"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        self.client.force_authenticate(user=self.user)
        issued = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/issue/",
            {},
            format="json",
            HTTP_IF_MATCH=approved.headers["Quotation-Version-ETag"],
        )

        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["data"]["status"], ApprovalStatus.APPROVED)
        self.assertEqual(issued.status_code, 200, issued.data)
        self.assertEqual(issued.data["data"]["status"], QuotationVersionStatus.ISSUED)

    def test_document_dispatch_and_accept_flow(self):
        quotation = self.create_quotation()
        quotation_id = quotation.data["data"]["id"]
        version = self.create_version(quotation_id, quotation.headers["ETag"])
        version_id = version.data["data"]["id"]
        line = self.add_line(version_id, version.headers["ETag"])
        locked = self.lock_version(version_id, line.headers["ETag"])
        issued = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/issue/",
            {},
            format="json",
            HTTP_IF_MATCH=locked.headers["ETag"],
        )
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="quotation.pdf",
            storage_key="tests/quotations/quotation.pdf",
            content_type="application/pdf",
            size_bytes=100,
            scan_status="CLEAN",
        )
        document = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/generate-document/",
            {"file_id": str(business_file.pk)},
            format="json",
            HTTP_IF_MATCH=issued.headers["ETag"],
        )
        dispatched = self.client.post(
            f"/api/v1/quotation-versions/{version_id}/dispatch/",
            {
                "channel": "EMAIL",
                "recipient_snapshot": {"name": "报价联系人", "email": "buyer@example.com"},
            },
            format="json",
            HTTP_IF_MATCH=document.headers["ETag"],
        )
        quote_etag = self.client.get(f"/api/v1/quotations/{quotation_id}/").headers["ETag"]
        accepted = self.client.post(
            f"/api/v1/quotations/{quotation_id}/accept/",
            {"accepted_version_id": version_id, "note": "客户接受"},
            format="json",
            HTTP_IF_MATCH=quote_etag,
        )

        self.assertEqual(issued.status_code, 200, issued.data)
        self.assertEqual(document.status_code, 200, document.data)
        self.assertEqual(len(document.data["data"]["documents"]), 1)
        self.assertEqual(dispatched.status_code, 200, dispatched.data)
        self.assertEqual(dispatched.data["data"]["status"], QuotationVersionStatus.SENT)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data["data"]["outcome_status"], "WON")
        self.assertEqual(str(accepted.data["data"]["accepted_version"]), version_id)

    def test_stale_etag_and_cross_customer_entity_are_rejected(self):
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="FOREIGN_QUOTE_ENTITY",
            legal_name="其他客户主体",
        )
        rejected = self.client.post(
            "/api/v1/quotations/",
            {
                "customer_account_id": str(self.customer.pk),
                "transaction_entity_id": str(foreign_entity.pk),
                "owner_employee_id": str(self.employee.pk),
                "subject": "跨客户报价",
            },
            format="json",
        )
        quotation = self.create_quotation()
        url = f"/api/v1/quotations/{quotation.data['data']['id']}/"
        changed = self.client.patch(
            url,
            {"subject": "已修改"},
            format="json",
            HTTP_IF_MATCH=quotation.headers["ETag"],
        )
        stale = self.client.patch(
            url,
            {"subject": "旧版本修改"},
            format="json",
            HTTP_IF_MATCH=quotation.headers["ETag"],
        )

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("transaction_entity_id", rejected.data["error"]["field_errors"])
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(stale.status_code, 412, stale.data)
