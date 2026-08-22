import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import (
    PreconditionFailed,
    PreconditionRequired,
    etag_for_instance,
    require_matching_etag,
)
from apps.core.api.exceptions import api_exception_handler
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee


class ApiFoundationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="api_user",
            password="StrongTestPassword123!",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="API_USER",
            display_name="API 测试员工",
        )
        self.client = APIClient()

    def test_api_v1_requires_login_and_returns_standard_error(self):
        response = self.client.get("/api/v1/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "AUTHENTICATION_REQUIRED")
        self.assertIn("request_id", response.data["error"])
        self.assertEqual(response.headers["X-Request-ID"], response.data["error"]["request_id"])

    def test_api_v1_rejects_user_without_active_employee(self):
        user_model = get_user_model()
        user_without_employee = user_model.objects.create_user(username="no_employee")
        self.client.force_authenticate(user=user_without_employee)

        response = self.client.get("/api/v1/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "PERMISSION_DENIED")

    def test_api_v1_allows_active_employee(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/v1/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["version"], "1.0")

    def test_request_id_accepts_uuid_and_replaces_invalid_value(self):
        self.client.force_authenticate(user=self.user)
        request_id = str(uuid.uuid4())

        valid_response = self.client.get("/api/v1/", HTTP_X_REQUEST_ID=request_id)
        invalid_response = self.client.get("/api/v1/", HTTP_X_REQUEST_ID="not-a-uuid")

        self.assertEqual(valid_response.headers["X-Request-ID"], request_id)
        self.assertNotEqual(invalid_response.headers["X-Request-ID"], "not-a-uuid")
        uuid.UUID(invalid_response.headers["X-Request-ID"])

    def test_business_numbers_are_unique_and_match_confirmed_formats(self):
        customer_number = next_business_number("CUSTOMER")
        first_inquiry = next_business_number("INQUIRY")
        second_inquiry = next_business_number("INQUIRY")

        self.assertRegex(customer_number, r"^CUS-\d{6,}$")
        self.assertRegex(first_inquiry, r"^INQ-\d{6}-\d{6,}$")
        self.assertNotEqual(first_inquiry, second_inquiry)

    def test_etag_rejects_missing_or_stale_precondition(self):
        customer = CustomerAccount.objects.create(
            account_code="ETAG_CUSTOMER",
            account_name="ETag 测试客户",
        )
        factory = RequestFactory()

        with self.assertRaises(PreconditionRequired):
            require_matching_etag(factory.patch("/api/v1/customers/test/"), customer)

        with self.assertRaises(PreconditionFailed):
            require_matching_etag(
                factory.patch("/api/v1/customers/test/", HTTP_IF_MATCH='"stale"'),
                customer,
            )

        request = factory.patch(
            "/api/v1/customers/test/",
            HTTP_IF_MATCH=etag_for_instance(customer),
        )
        require_matching_etag(request, customer)

    def test_audit_service_captures_actor_and_request_context(self):
        request_id = str(uuid.uuid4())
        request = RequestFactory().post(
            "/api/v1/customers/",
            HTTP_X_REQUEST_ID=request_id,
            HTTP_USER_AGENT="haiqu-test",
            REMOTE_ADDR="127.0.0.1",
        )
        request.request_id = request_id
        object_id = uuid.uuid4()

        audit_log = write_audit_log(
            object_type="CUSTOMER_ACCOUNT",
            object_id=object_id,
            action="CREATED",
            actor_employee=self.employee,
            after_data={"id": object_id},
            request=request,
        )

        self.assertEqual(audit_log.actor_employee_code_snapshot, "API_USER")
        self.assertEqual(audit_log.request_id, uuid.UUID(request_id))
        self.assertEqual(audit_log.after_data["id"], str(object_id))
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_validation_error_is_normalized_for_api_v1(self):
        request = RequestFactory().post("/api/v1/test/")
        request.request_id = str(uuid.uuid4())
        exception = ValidationError({"name": ["请输入名称"]})

        response = api_exception_handler(exception, {"request": request})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(response.data["error"]["field_errors"]["name"], ["请输入名称"])

    def test_openapi_schema_contains_api_v1_root(self):
        response = self.client.get("/api/schema/", HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/v1/", response.data["paths"])

    def test_confirmed_business_permissions_are_created(self):
        expected_permissions = {
            "view_all_customer",
            "transfer_customer",
            "approve_customer_transfer",
            "merge_customer",
            "manage_customer_access",
            "issue_quotation",
            "dispatch_quotation",
            "accept_quotation",
            "approve_quotation",
            "decide_sample_fee",
            "ship_sample",
            "manage_sla_policy",
            "view_all_auditlog",
        }

        existing_permissions = set(
            Permission.objects.filter(codename__in=expected_permissions).values_list(
                "codename",
                flat=True,
            )
        )
        self.assertEqual(existing_permissions, expected_permissions)
