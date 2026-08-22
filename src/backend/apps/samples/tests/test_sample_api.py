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
from apps.organizations.models import Employee
from apps.workflow.models import SlaPolicy, SlaTrackingStatus

from ..models import SampleFeeRecord, SampleRequest, SampleRequestStatus


class SampleApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_api_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_API_USER",
            display_name="样品接口测试员工",
        )
        self.other_user = user_model.objects.create_user(username="sample_api_other")
        self.other_employee = Employee.objects.create(
            user=self.other_user,
            employee_code="SAMPLE_API_OTHER",
            display_name="其他样品员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label__in=["samples", "workflow"])
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.customer = self.create_customer("SAMPLE_CUSTOMER", "样品客户", self.employee)
        self.other_customer = self.create_customer(
            "OTHER_SAMPLE_CUSTOMER", "其他样品客户", self.other_employee
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="SAMPLE_ENTITY",
            legal_name="样品交易主体",
        )
        self.address = CustomerEntityAddress.objects.create(
            transaction_entity=self.entity,
            address_code="SAMPLE_ADDRESS",
            country_code="CN",
            city="深圳",
            address_line1="样品路 1 号",
        )
        self.contact = CustomerContact.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            display_name="样品联系人",
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

    def payload(self, **overrides):
        data = {
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "customer_contact_id": str(self.contact.pk),
            "owner_employee_id": str(self.employee.pk),
            "purpose": "客户测试",
            "requested_at": timezone.now().isoformat(),
            "items": [
                {
                    "product_description_snapshot": "测试样品",
                    "requested_quantity": "2.0000",
                    "unit_code": "PCS",
                }
            ],
        }
        data.update(overrides)
        return data

    def create_sample(self, **overrides):
        response = self.client.post("/api/v1/sample-requests/", self.payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def advance_to_preparing(self, created):
        sample_id = created.data["data"]["id"]
        submitted = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        started = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/start-preparing/",
            {},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )
        self.assertEqual(started.status_code, 200, started.data)
        return started

    def create_shipment(self, prepared):
        sample_id = prepared.data["data"]["id"]
        item_id = prepared.data["data"]["items"][0]["id"]
        response = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/shipments/",
            {"items": [{"sample_item_id": item_id, "shipped_quantity": "1.0000"}]},
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_nested_items_generates_number_audit_and_timeline(self):
        response = self.create_sample()
        sample_request = SampleRequest.objects.get(pk=response.data["data"]["id"])

        self.assertRegex(sample_request.request_number, r"^SMP-\d{6}-\d{6,}$")
        self.assertEqual(sample_request.items.get().line_number, 1)
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="SAMPLE_REQUEST", object_id=sample_request.pk, action="CREATED"
            ).exists()
        )
        self.assertTrue(
            CustomerTimelineEvent.objects.filter(
                customer_account=self.customer,
                source_id=sample_request.pk,
                event_type="SAMPLE_CREATED",
            ).exists()
        )

    def test_cross_customer_entity_and_unassigned_list_are_scoped(self):
        foreign_entity = CustomerTransactionEntity.objects.create(
            customer_account=self.other_customer,
            entity_code="FOREIGN_SAMPLE_ENTITY",
            legal_name="其他客户主体",
        )
        rejected = self.client.post(
            "/api/v1/sample-requests/",
            self.payload(transaction_entity_id=str(foreign_entity.pk)),
            format="json",
        )
        visible = self.create_sample()
        hidden = SampleRequest.objects.create(
            customer_account=self.other_customer,
            transaction_entity=foreign_entity,
            owner_employee=self.other_employee,
            request_number="HIDDEN_SAMPLE_REQUEST",
            requested_at=timezone.now(),
        )
        listed = self.client.get("/api/v1/sample-requests/")
        ids = {item["id"] for item in listed.data["data"]}

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("transaction_entity_id", rejected.data["error"]["field_errors"])
        self.assertIn(visible.data["data"]["id"], ids)
        self.assertNotIn(str(hidden.pk), ids)

    def test_item_changes_require_parent_etag_and_lock_after_submit(self):
        created = self.create_sample(items=[])
        sample_id = created.data["data"]["id"]
        added = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/items/",
            {
                "product_description_snapshot": "后加样品",
                "requested_quantity": "1.0000",
                "unit_code": "PCS",
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        stale = self.client.patch(
            f"/api/v1/sample-items/{added.data['data']['id']}/",
            {"requested_quantity": "2.0000"},
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
        )
        submitted = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=added.headers["ETag"],
        )
        locked = self.client.patch(
            f"/api/v1/sample-items/{added.data['data']['id']}/",
            {"requested_quantity": "3.0000"},
            format="json",
            HTTP_IF_MATCH=submitted.headers["ETag"],
        )

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(locked.status_code, 409, locked.data)

    def test_fee_decision_supersedes_history_and_evidence_requires_file(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        no_evidence = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "verification_status": "EVIDENCE_UPLOADED",
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        free = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        paid = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "verification_status": "MANUALLY_CONFIRMED",
            },
            format="json",
            HTTP_IF_MATCH=free.headers["ETag"],
        )

        self.assertEqual(no_evidence.status_code, 409, no_evidence.data)
        self.assertEqual(free.status_code, 201, free.data)
        self.assertEqual(paid.status_code, 201, paid.data)
        records = SampleFeeRecord.objects.filter(sample_request_id=sample_id).order_by("created_at")
        self.assertIsNotNone(records[0].superseded_at)
        self.assertIsNone(records[1].superseded_at)

    def test_unconfirmed_paid_fee_requires_explicit_warning_and_reason(self):
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        evidence_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="fee-proof.png",
            storage_key="tests/samples/fee-proof.png",
            content_type="image/png",
            size_bytes=10,
            scan_status="CLEAN",
        )
        linked = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/files/",
            {"file_id": str(evidence_file.pk), "file_role": "FEE_EVIDENCE"},
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "PAID",
                "amount": "100.0000",
                "currency_code": "USD",
                "verification_status": "EVIDENCE_UPLOADED",
            },
            format="json",
            HTTP_IF_MATCH=linked.headers["ETag"],
        )
        prepared_after_fee = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        shipment = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/shipments/",
            {
                "items": [
                    {
                        "sample_item_id": prepared_after_fee.data["data"]["items"][0]["id"],
                        "shipped_quantity": "1.0000",
                    }
                ]
            },
            format="json",
            HTTP_IF_MATCH=prepared_after_fee.headers["ETag"],
        )
        ship_url = f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/"
        ship_payload = {
            "address_id": str(self.address.pk),
            "contact_id": str(self.contact.pk),
            "carrier_code": "SF",
            "tracking_number": "SF123456",
        }
        blocked = self.client.post(
            ship_url,
            ship_payload,
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        shipped = self.client.post(
            ship_url,
            {
                **ship_payload,
                "fee_warning_acknowledged": True,
                "fee_warning_reason": "客户已确认先寄样后核销费用",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )

        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(shipment.status_code, 201, shipment.data)
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertEqual(shipped.status_code, 200, shipped.data)
        self.assertTrue(shipped.data["data"]["fee_warning_acknowledged"])

    def test_full_ship_deliver_feedback_complete_flow_finishes_sla(self):
        SlaPolicy.objects.create(
            policy_code="SAMPLE_STANDARD",
            display_name="样品标准 SLA",
            target_type="SAMPLE_REQUEST",
            resolution_minutes=120,
            is_enabled=True,
        )
        prepared = self.advance_to_preparing(self.create_sample())
        sample_id = prepared.data["data"]["id"]
        fee = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/fee-records/",
            {
                "fee_decision": "FREE",
                "amount": "0",
                "currency_code": "USD",
                "verification_status": "NOT_REQUIRED",
            },
            format="json",
            HTTP_IF_MATCH=prepared.headers["ETag"],
        )
        current = self.client.get(f"/api/v1/sample-requests/{sample_id}/")
        shipment = self.create_shipment(current)
        ship = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/ship/",
            {
                "address_id": str(self.address.pk),
                "contact_id": str(self.contact.pk),
                "carrier_code": "DHL",
                "tracking_number": "DHL123456",
            },
            format="json",
            HTTP_IF_MATCH=shipment.headers["ETag"],
        )
        delivered = self.client.post(
            f"/api/v1/sample-shipments/{shipment.data['data']['id']}/deliver/",
            {"note": "客户签收"},
            format="json",
            HTTP_IF_MATCH=ship.headers["ETag"],
        )
        feedback = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/feedback/",
            {
                "customer_contact_id": str(self.contact.pk),
                "feedback_type": "POSITIVE",
                "feedback_content": "样品测试通过",
                "occurred_at": timezone.now().isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=delivered.headers["Sample-Request-ETag"],
        )
        completed = self.client.post(
            f"/api/v1/sample-requests/{sample_id}/complete/",
            {},
            format="json",
            HTTP_IF_MATCH=feedback.headers["ETag"],
        )

        self.assertEqual(fee.status_code, 201, fee.data)
        self.assertEqual(ship.status_code, 200, ship.data)
        self.assertEqual(delivered.status_code, 200, delivered.data)
        self.assertEqual(feedback.status_code, 201, feedback.data)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["status"], SampleRequestStatus.COMPLETED)
        tracking = SampleRequest.objects.get(pk=sample_id).sla_links.get().sla_tracking
        self.assertEqual(tracking.status, SlaTrackingStatus.MET)
        sla_list = self.client.get("/api/v1/sla-trackings/?target_type=SAMPLE_REQUEST")
        self.assertEqual(sla_list.status_code, 200, sla_list.data)
        self.assertEqual(sla_list.data["data"][0]["source"]["id"], sample_id)

    def test_submit_without_items_and_complete_without_feedback_are_rejected(self):
        empty = self.create_sample(items=[])
        submit = self.client.post(
            f"/api/v1/sample-requests/{empty.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=empty.headers["ETag"],
        )
        sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            transaction_entity=self.entity,
            customer_contact=self.contact,
            owner_employee=self.employee,
            request_number="NO_FEEDBACK_SAMPLE",
            requested_at=timezone.now(),
        )
        sample_request.items.create(
            line_number=1,
            product_description_snapshot="测试",
            requested_quantity=1,
            unit_code="PCS",
        )
        sample_request.status = SampleRequestStatus.FEEDBACK_PENDING
        sample_request.save(update_fields=["status", "updated_at"])
        detail = self.client.get(f"/api/v1/sample-requests/{sample_request.pk}/")
        complete = self.client.post(
            f"/api/v1/sample-requests/{sample_request.pk}/complete/",
            {},
            format="json",
            HTTP_IF_MATCH=detail.headers["ETag"],
        )

        self.assertEqual(submit.status_code, 409, submit.data)
        self.assertEqual(complete.status_code, 409, complete.data)
