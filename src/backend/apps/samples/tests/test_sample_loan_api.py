import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee

from ..models import (
    SampleInventoryLine,
    SampleInventoryLoan,
    SampleInventoryLoanLine,
    SampleInventoryReceipt,
    SampleItem,
    SampleProduct,
    SampleRequest,
    SampleRequestStatus,
)


class SampleLoanApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_loan_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_LOAN_USER",
            display_name="样品借出测试员工",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryloanline",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="add_sampleinventoryloan",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryline",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="delete_sampleinventoryloan",
            ),
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SAMPLE_LOAN_CUSTOMER",
            account_name="样品借出测试客户",
            primary_country_code="CN",
        )
        self.sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            request_number="SYGJ-20260902-021",
            status=SampleRequestStatus.FINISHED,
            requested_at=timezone.now(),
        )
        self.sample_product = SampleProduct.objects.create(
            sample_request=self.sample_request,
            line_number=1,
            category_name_snapshot="户外桌椅",
            product_name="铝框休闲椅",
            specification="620×680×820",
        )
        self.receipt = SampleInventoryReceipt.objects.create(
            receipt_number="RK-20260902-021",
            submitted_by_employee=self.employee,
            submitted_at=timezone.now(),
        )
        self.inventory_lines = []
        for line_number, product_name, color, loaned_quantity in [
            (1, "铝框休闲椅", "蓝灰", 1),
            (2, "藤编双人椅", "沙棕", 2),
        ]:
            sample_item = SampleItem.objects.create(
                sample_request=self.sample_request,
                sample_product=self.sample_product,
                line_number=line_number,
                product_description_snapshot=product_name,
                specification_snapshot="620×680×820",
                requested_quantity="10.0000",
                unit_code="PCS",
                color_name_snapshot=color,
                sample_quantity=10,
            )
            self.inventory_lines.append(
                SampleInventoryLine.objects.create(
                    receipt=self.receipt,
                    sample_item=sample_item,
                    category_name_snapshot="户外桌椅",
                    product_name_snapshot=product_name,
                    specification_snapshot="620×680×820",
                    color_name_snapshot=color,
                    sampling_quantity=10,
                    received_quantity=10,
                    loaned_quantity=loaned_quantity,
                    location="样品库",
                )
            )

        self.loan = SampleInventoryLoan.objects.create(
            loan_number="JC-20260902-001",
            operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        SampleInventoryLoanLine.objects.create(
            loan=self.loan,
            inventory_line=self.inventory_lines[0],
            loan_quantity=1,
            borrower_name="王立新",
            purpose_note="客户现场材质确认",
        )
        SampleInventoryLoanLine.objects.create(
            loan=self.loan,
            inventory_line=self.inventory_lines[1],
            loan_quantity=2,
            borrower_name="赵倩",
            purpose_note="展厅陈列拍摄",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_payload(self, **overrides):
        item = {
            "inventory_line_id": str(self.inventory_lines[0].pk),
            "loan_quantity": 2,
            "borrower_name": "陈佳",
            "purpose_note": "客户现场确认材质",
            "expected_available_quantity": 9,
        }
        item.update(overrides)
        return {"items": [item]}

    def test_list_returns_loan_detail_rows_with_repeated_document_number(self):
        response = self.client.get("/api/v1/sample-loans/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        rows = response.data["data"]
        self.assertEqual([row["loan_number"] for row in rows], ["JC-20260902-001"] * 2)
        self.assertEqual(rows[0]["operator_name"], "样品借出测试员工")
        self.assertEqual(rows[0]["sample_request_number"], "SYGJ-20260902-021")
        self.assertEqual(rows[0]["product_category"], "户外桌椅")
        self.assertEqual({row["borrower_name"] for row in rows}, {"王立新", "赵倩"})

    def test_list_supports_keyword_borrower_category_and_time_filters(self):
        matched = self.client.get(
            "/api/v1/sample-loans/",
            {
                "q": "客户现场",
                "borrower_name": "王立新",
                "category_name": "户外桌椅",
                "operated_period": "TODAY",
            },
        )
        missing = self.client.get("/api/v1/sample-loans/", {"q": "不存在的用途"})

        self.assertEqual(matched.status_code, 200, matched.data)
        self.assertEqual(matched.data["meta"]["total"], 1)
        self.assertEqual(matched.data["data"][0]["loan_quantity"], 1)
        self.assertEqual(missing.status_code, 200, missing.data)
        self.assertEqual(missing.data["meta"]["total"], 0)

    def test_summary_and_options_come_from_loan_records(self):
        summary = self.client.get("/api/v1/sample-loans/summary/")
        options = self.client.get("/api/v1/sample-loans/options/")

        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(
            summary.data["data"],
            {
                "active_documents": 1,
                "cumulative_borrowed": 3,
                "customer_confirmation": 1,
                "showroom_or_photo": 2,
            },
        )
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data["data"]["borrower_names"], ["王立新", "赵倩"])
        self.assertEqual(options.data["data"]["product_categories"], ["户外桌椅"])

    def test_borrower_and_purpose_are_required_by_the_model(self):
        invalid_line = SampleInventoryLoanLine(
            loan=self.loan,
            inventory_line=self.inventory_lines[0],
            loan_quantity=1,
            borrower_name=" ",
            purpose_note=" ",
        )

        with self.assertRaises(ValidationError) as error:
            invalid_line.full_clean(validate_unique=False, validate_constraints=False)

        self.assertIn("borrower_name", error.exception.message_dict)
        self.assertIn("purpose_note", error.exception.message_dict)

    def test_eligible_returns_only_inventory_lines_with_available_quantity(self):
        response = self.client.get("/api/v1/sample-loans/eligible/", {"page_size": 100})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        first = next(
            row
            for row in response.data["data"]
            if row["inventory_line_id"] == str(self.inventory_lines[0].pk)
        )
        self.assertEqual(first["receipt_number"], "RK-20260902-021")
        self.assertEqual(first["sample_request_number"], "SYGJ-20260902-021")
        self.assertEqual(first["product_name"], "铝框休闲椅")
        self.assertEqual(first["available_quantity"], 9)

    def test_create_loan_updates_inventory_in_one_transaction(self):
        response = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["data"]["loan_number"].startswith("JC-"))
        self.assertEqual(response.data["data"]["operated_by"], "样品借出测试员工")
        self.assertEqual(response.data["data"]["line_count"], 1)
        self.inventory_lines[0].refresh_from_db()
        self.assertEqual(self.inventory_lines[0].loaned_quantity, 3)
        created_line = SampleInventoryLoanLine.objects.exclude(loan=self.loan).get()
        self.assertEqual(created_line.loan_quantity, 2)
        self.assertEqual(created_line.borrower_name, "陈佳")
        self.assertEqual(created_line.purpose_note, "客户现场确认材质")
        inventory_response = self.client.get(
            "/api/v1/sample-inventory/",
            {"q": "铝框休闲椅"},
        )
        self.assertEqual(inventory_response.status_code, 200, inventory_response.data)
        inventory_row = inventory_response.data["data"][0]
        self.assertEqual(inventory_row["received_quantity"], 10)
        self.assertEqual(inventory_row["loaned_quantity"], 3)
        self.assertEqual(inventory_row["available_quantity"], 7)

    def test_create_loan_rejects_overdraw_and_stale_inventory(self):
        overdraw = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(loan_quantity=10),
            format="json",
        )
        stale = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(expected_available_quantity=8),
            format="json",
        )

        self.assertEqual(overdraw.status_code, 409, overdraw.data)
        self.assertEqual(stale.status_code, 409, stale.data)
        self.assertIn("已变化", stale.data["error"]["message"])
        self.assertEqual(SampleInventoryLoan.objects.count(), 1)

    def test_create_loan_validates_required_fields_and_duplicates(self):
        zero_quantity = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(loan_quantity=0),
            format="json",
        )
        missing_borrower = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(borrower_name=" "),
            format="json",
        )
        missing_purpose = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(purpose_note=" "),
            format="json",
        )
        duplicate_items = self.create_payload()["items"] * 2
        duplicate = self.client.post(
            "/api/v1/sample-loans/documents/",
            {"items": duplicate_items},
            format="json",
        )

        self.assertEqual(zero_quantity.status_code, 400, zero_quantity.data)
        self.assertEqual(missing_borrower.status_code, 400, missing_borrower.data)
        self.assertEqual(missing_purpose.status_code, 400, missing_purpose.data)
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

    def test_loan_detail_returns_header_and_all_borrowing_fields(self):
        response = self.client.get(f"/api/v1/sample-loans/documents/{self.loan.pk}/")

        self.assertEqual(response.status_code, 200, response.data)
        detail = response.data["data"]
        self.assertEqual(detail["loan_id"], str(self.loan.pk))
        self.assertEqual(detail["loan_number"], "JC-20260902-001")
        self.assertEqual(detail["document_type"], "样品借出")
        self.assertEqual(detail["submitted_by"], "样品借出测试员工")
        self.assertEqual(detail["operation_source"], "样品库")
        self.assertEqual(detail["status"], "ACTIVE")
        self.assertEqual(detail["status_display"], "借出中")
        self.assertEqual(detail["inventory_status_display"], "库存占用中")
        self.assertEqual(detail["line_count"], 2)
        lines_by_borrower = {line["borrower_name"]: line for line in detail["lines"]}
        self.assertEqual(lines_by_borrower["王立新"]["receipt_number"], "RK-20260902-021")
        self.assertEqual(
            lines_by_borrower["王立新"]["sample_request_number"],
            "SYGJ-20260902-021",
        )
        self.assertEqual(lines_by_borrower["王立新"]["purpose_note"], "客户现场材质确认")
        self.assertEqual(lines_by_borrower["王立新"]["inventory_impact"], "可用库存 -1")
        self.assertEqual(lines_by_borrower["赵倩"]["inventory_impact"], "可用库存 -2")

    def test_loan_detail_returns_not_found_for_unknown_document(self):
        response = self.client.get(f"/api/v1/sample-loans/documents/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, 404, response.data)

    def test_delete_loan_removes_document_and_restores_inventory(self):
        response = self.client.delete(f"/api/v1/sample-loans/documents/{self.loan.pk}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(SampleInventoryLoan.objects.filter(pk=self.loan.pk).exists())
        self.assertFalse(
            SampleInventoryLoanLine.objects.filter(loan_id=self.loan.pk).exists()
        )
        for inventory_line in self.inventory_lines:
            inventory_line.refresh_from_db()
            self.assertEqual(inventory_line.loaned_quantity, 0)

    def test_loan_permission_is_required(self):
        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="sample_loan_no_permission")
        Employee.objects.create(
            user=other_user,
            employee_code="SAMPLE_LOAN_NO_PERMISSION",
            display_name="无借出权限员工",
        )
        self.client.force_authenticate(other_user)

        response = self.client.get("/api/v1/sample-loans/")
        eligible = self.client.get("/api/v1/sample-loans/eligible/")
        created = self.client.post(
            "/api/v1/sample-loans/documents/",
            self.create_payload(),
            format="json",
        )
        detail = self.client.get(f"/api/v1/sample-loans/documents/{self.loan.pk}/")
        deleted = self.client.delete(f"/api/v1/sample-loans/documents/{self.loan.pk}/")

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(eligible.status_code, 403, eligible.data)
        self.assertEqual(created.status_code, 403, created.data)
        self.assertEqual(detail.status_code, 403, detail.data)
        self.assertEqual(deleted.status_code, 403, deleted.data)
