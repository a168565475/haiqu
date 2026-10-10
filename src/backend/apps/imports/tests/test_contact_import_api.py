from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import CustomerAccount, CustomerAssignment, CustomerContact
from apps.files.models import BusinessFile, FileScanStatus
from apps.imports.models import ImportBatch
from apps.organizations.models import Employee


class ContactImportApiTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="contact_import_user")
        self.employee = Employee.objects.create(
            user=user,
            employee_code="CONTACT_IMPORT_USER",
            display_name="联系人导入测试员工",
        )
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="customers"))
        self.client = APIClient()
        self.client.force_authenticate(user)
        self.customer = CustomerAccount.objects.create(
            account_code="IMPORT-CUSTOMER-001",
            account_name="导入测试客户",
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        self.csv_path = Path(settings.MEDIA_ROOT) / "test_contact_import.csv"
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path.write_text(
            "customer_account_code,display_name,position_title,status,is_key_contact,email,mobile,phone,wechat,whatsapp,role_types,notes\n"
            "IMPORT-CUSTOMER-001,李采购,采购经理,ACTIVE,是,li@example.com,,,,,BUYER,测试导入\n",
            encoding="utf-8",
        )
        self.business_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="contacts.csv",
            storage_key="imports/tests/contacts.csv",
            content_type="text/csv",
            size_bytes=self.csv_path.stat().st_size,
            content_hash="test-hash",
            scan_status=FileScanStatus.CLEAN,
            scanned_at=timezone.now(),
        )

    def tearDown(self):
        if self.csv_path.exists():
            self.csv_path.unlink()

    @patch("apps.imports.api.views.save_and_scan_upload")
    def test_contact_csv_import_creates_batch_record_and_contact(self, scan_mock):
        scan_mock.return_value = (self.business_file, self.csv_path)
        response = self.client.post(
            "/api/v1/contact-imports/",
            {
                "file": SimpleUploadedFile("contacts.csv", b"placeholder", content_type="text/csv"),
                "customer_id": str(self.customer.pk),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], "COMPLETED")
        self.assertEqual(response.data["data"]["success_count"], 1)
        contact = CustomerContact.objects.get(display_name="李采购")
        self.assertTrue(contact.is_key_contact)
        self.assertEqual(contact.methods.get().normalized_value, "li@example.com")

        records = self.client.get(f"/api/v1/contact-imports/{response.data['data']['id']}/records/")
        self.assertEqual(records.status_code, 200, records.data)
        self.assertEqual(records.data["data"][0]["status"], "SUCCEEDED")

    def test_template_is_xlsx(self):
        response = self.client.get("/api/v1/contact-imports/template/?scope=customer")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))

    @patch("apps.imports.api.views.save_and_scan_upload")
    def test_invalid_customer_does_not_leave_processing_batch(self, scan_mock):
        scan_mock.return_value = (self.business_file, self.csv_path)

        response = self.client.post(
            "/api/v1/contact-imports/",
            {
                "file": SimpleUploadedFile("contacts.csv", b"placeholder", content_type="text/csv"),
                "customer_id": str(uuid4()),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ImportBatch.objects.exists())
