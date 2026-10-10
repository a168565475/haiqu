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
    SampleInventoryOutbound,
    SampleInventoryOutboundLine,
    SampleInventoryReceipt,
    SampleItem,
    SampleOutboundMethod,
    SampleProduct,
    SampleRequest,
    SampleRequestStatus,
)


class SampleOutboundApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_outbound_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_OUTBOUND_USER",
            display_name="样品出库测试员工",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryoutboundline",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="add_sampleinventoryoutbound",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryline",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="delete_sampleinventoryoutbound",
            ),
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SAMPLE_OUTBOUND_CUSTOMER",
            account_name="样品出库测试客户",
            primary_country_code="CN",
        )
        self.sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            request_number="SYGJ-20260902-011",
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
            receipt_number="RK-20260902-011",
            submitted_by_employee=self.employee,
            submitted_at=timezone.now(),
        )
        self.inventory_lines = []
        for line_number, product_name, color, outbound_quantity in [
            (1, "铝框休闲椅", "蓝灰", 1),
            (2, "藤编双人椅", "卡其", 2),
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
                    outbound_quantity=outbound_quantity,
                    location="样品库",
                )
            )

        self.outbound = SampleInventoryOutbound.objects.create(
            outbound_number="CK-20260902-001",
            operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        self.outbound_lines = [
            SampleInventoryOutboundLine.objects.create(
                outbound=self.outbound,
                inventory_line=self.inventory_lines[0],
                outbound_quantity=1,
                outbound_method=SampleOutboundMethod.MERCHANDISER_MAIL,
                courier_company="顺丰速运",
                tracking_number="SF1234567890",
            ),
            SampleInventoryOutboundLine.objects.create(
                outbound=self.outbound,
                inventory_line=self.inventory_lines[1],
                outbound_quantity=2,
                outbound_method=SampleOutboundMethod.SALESPERSON_CARRY,
            ),
        ]
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_payload(self, **overrides):
        item = {
            "inventory_line_id": str(self.inventory_lines[0].pk),
            "outbound_quantity": 2,
            "outbound_method": SampleOutboundMethod.MERCHANDISER_MAIL,
            "courier_company": "顺丰速运",
            "tracking_number": "SF9876543210",
            "remark": "",
            "expected_available_quantity": 9,
        }
        item.update(overrides)
        return {"items": [item]}

    def test_list_returns_outbound_detail_rows_with_repeated_document_number(self):
        response = self.client.get("/api/v1/sample-outbound/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        rows = response.data["data"]
        self.assertEqual([row["outbound_number"] for row in rows], ["CK-20260902-001"] * 2)
        self.assertEqual(rows[0]["operator_name"], "样品出库测试员工")
        self.assertEqual(rows[0]["sample_request_number"], "SYGJ-20260902-011")
        self.assertEqual(rows[0]["product_category"], "户外桌椅")
        self.assertEqual({row["outbound_method_display"] for row in rows}, {"跟单员邮寄", "业务员带走"})

    def test_list_supports_keyword_method_category_and_time_filters(self):
        mailed = self.client.get(
            "/api/v1/sample-outbound/",
            {
                "q": "SF1234567890",
                "outbound_method": SampleOutboundMethod.MERCHANDISER_MAIL,
                "category_name": "户外桌椅",
                "operated_period": "TODAY",
            },
        )
        missing = self.client.get("/api/v1/sample-outbound/", {"q": "不存在的快递单号"})

        self.assertEqual(mailed.status_code, 200, mailed.data)
        self.assertEqual(mailed.data["meta"]["total"], 1)
        self.assertEqual(mailed.data["data"][0]["courier_company"], "顺丰速运")
        self.assertEqual(missing.status_code, 200, missing.data)
        self.assertEqual(missing.data["meta"]["total"], 0)

    def test_summary_and_options_come_from_outbound_records(self):
        summary = self.client.get("/api/v1/sample-outbound/summary/")
        options = self.client.get("/api/v1/sample-outbound/options/")

        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(
            summary.data["data"],
            {
                "outbound_today": 3,
                "outbound_this_month": 3,
                "mailed": 1,
                "salesperson_carried": 2,
            },
        )
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data["data"]["product_categories"], ["户外桌椅"])
        self.assertEqual(
            options.data["data"]["outbound_methods"],
            [
                {"value": "MERCHANDISER_MAIL", "label": "跟单员邮寄"},
                {"value": "SALESPERSON_CARRY", "label": "业务员带走"},
                {"value": "OTHER", "label": "其他"},
            ],
        )

    def test_conditional_fields_are_validated_by_the_model(self):
        missing_delivery_fields = SampleInventoryOutboundLine(
            outbound=self.outbound,
            inventory_line=self.inventory_lines[0],
            outbound_quantity=1,
            outbound_method=SampleOutboundMethod.MERCHANDISER_MAIL,
        )
        missing_other_remark = SampleInventoryOutboundLine(
            outbound=self.outbound,
            inventory_line=self.inventory_lines[1],
            outbound_quantity=1,
            outbound_method=SampleOutboundMethod.OTHER,
        )

        with self.assertRaises(ValidationError) as delivery_error:
            missing_delivery_fields.full_clean(validate_unique=False, validate_constraints=False)
        with self.assertRaises(ValidationError) as remark_error:
            missing_other_remark.full_clean(validate_unique=False, validate_constraints=False)

        self.assertIn("courier_company", delivery_error.exception.message_dict)
        self.assertIn("tracking_number", delivery_error.exception.message_dict)
        self.assertIn("remark", remark_error.exception.message_dict)

    def test_eligible_returns_only_inventory_lines_with_available_quantity(self):
        response = self.client.get("/api/v1/sample-outbound/eligible/", {"page_size": 100})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        first = next(
            row
            for row in response.data["data"]
            if row["inventory_line_id"] == str(self.inventory_lines[0].pk)
        )
        self.assertEqual(first["receipt_number"], "RK-20260902-011")
        self.assertEqual(first["sample_request_number"], "SYGJ-20260902-011")
        self.assertEqual(first["product_name"], "铝框休闲椅")
        self.assertEqual(first["available_quantity"], 9)

    def test_create_outbound_updates_inventory_in_one_transaction(self):
        response = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["data"]["outbound_number"].startswith("CK-"))
        self.assertEqual(response.data["data"]["operated_by"], "样品出库测试员工")
        self.assertEqual(response.data["data"]["line_count"], 1)
        self.inventory_lines[0].refresh_from_db()
        self.assertEqual(self.inventory_lines[0].outbound_quantity, 3)
        created_line = SampleInventoryOutboundLine.objects.exclude(outbound=self.outbound).get()
        self.assertEqual(created_line.outbound_quantity, 2)
        self.assertEqual(created_line.outbound_method, SampleOutboundMethod.MERCHANDISER_MAIL)
        self.assertEqual(created_line.courier_company, "顺丰速运")
        self.assertEqual(created_line.tracking_number, "SF9876543210")
        inventory_response = self.client.get(
            "/api/v1/sample-inventory/",
            {"q": "铝框休闲椅"},
        )
        self.assertEqual(inventory_response.status_code, 200, inventory_response.data)
        inventory_row = inventory_response.data["data"][0]
        self.assertEqual(inventory_row["received_quantity"], 10)
        self.assertEqual(inventory_row["outbound_quantity"], 3)
        self.assertEqual(inventory_row["available_quantity"], 7)

    def test_create_outbound_rejects_overdraw_and_stale_inventory(self):
        overdraw = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(outbound_quantity=10),
            format="json",
        )
        stale = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(expected_available_quantity=8),
            format="json",
        )

        self.assertEqual(overdraw.status_code, 409, overdraw.data)
        self.assertEqual(stale.status_code, 409, stale.data)
        self.assertIn("已变化", stale.data["error"]["message"])
        self.assertEqual(SampleInventoryOutbound.objects.count(), 1)

    def test_create_outbound_validates_conditional_fields_and_duplicates(self):
        missing_mail_fields = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(courier_company="", tracking_number=""),
            format="json",
        )
        missing_other_remark = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(
                outbound_method=SampleOutboundMethod.OTHER,
                courier_company="",
                tracking_number="",
                remark="",
            ),
            format="json",
        )
        duplicate_item = self.create_payload()["items"] * 2
        duplicate = self.client.post(
            "/api/v1/sample-outbound/documents/",
            {"items": duplicate_item},
            format="json",
        )

        self.assertEqual(missing_mail_fields.status_code, 400, missing_mail_fields.data)
        self.assertEqual(missing_other_remark.status_code, 400, missing_other_remark.data)
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

    def test_outbound_detail_returns_header_and_all_method_fields(self):
        response = self.client.get(
            f"/api/v1/sample-outbound/documents/{self.outbound.pk}/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        detail = response.data["data"]
        self.assertEqual(detail["outbound_id"], str(self.outbound.pk))
        self.assertEqual(detail["outbound_number"], "CK-20260902-001")
        self.assertEqual(detail["document_type"], "样品出库")
        self.assertEqual(detail["submitted_by"], "样品出库测试员工")
        self.assertEqual(detail["operation_source"], "样品库")
        self.assertEqual(detail["status"], "COMPLETED")
        self.assertEqual(detail["line_count"], 2)
        mailed = next(
            line
            for line in detail["lines"]
            if line["outbound_method"] == SampleOutboundMethod.MERCHANDISER_MAIL
        )
        carried = next(
            line
            for line in detail["lines"]
            if line["outbound_method"] == SampleOutboundMethod.SALESPERSON_CARRY
        )
        self.assertEqual(mailed["receipt_number"], "RK-20260902-011")
        self.assertEqual(mailed["sample_request_number"], "SYGJ-20260902-011")
        self.assertEqual(mailed["outbound_method_display"], "跟单员邮寄")
        self.assertEqual(mailed["courier_company"], "顺丰速运")
        self.assertEqual(mailed["tracking_number"], "SF1234567890")
        self.assertEqual(carried["outbound_method_display"], "业务员带走")
        self.assertEqual(carried["courier_company"], "")
        self.assertEqual(carried["tracking_number"], "")

    def test_outbound_detail_returns_not_found_for_unknown_document(self):
        response = self.client.get(f"/api/v1/sample-outbound/documents/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, 404, response.data)

    def test_delete_outbound_removes_document_and_restores_inventory(self):
        response = self.client.delete(
            f"/api/v1/sample-outbound/documents/{self.outbound.pk}/"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            SampleInventoryOutbound.objects.filter(pk=self.outbound.pk).exists()
        )
        self.assertFalse(
            SampleInventoryOutboundLine.objects.filter(outbound_id=self.outbound.pk).exists()
        )
        for inventory_line in self.inventory_lines:
            inventory_line.refresh_from_db()
            self.assertEqual(inventory_line.outbound_quantity, 0)

    def test_outbound_permission_is_required(self):
        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="sample_outbound_no_permission")
        Employee.objects.create(
            user=other_user,
            employee_code="SAMPLE_OUTBOUND_NO_PERMISSION",
            display_name="无出库权限员工",
        )
        self.client.force_authenticate(other_user)

        response = self.client.get("/api/v1/sample-outbound/")
        eligible = self.client.get("/api/v1/sample-outbound/eligible/")
        created = self.client.post(
            "/api/v1/sample-outbound/documents/",
            self.create_payload(),
            format="json",
        )
        detail = self.client.get(
            f"/api/v1/sample-outbound/documents/{self.outbound.pk}/"
        )
        deleted = self.client.delete(
            f"/api/v1/sample-outbound/documents/{self.outbound.pk}/"
        )

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(eligible.status_code, 403, eligible.data)
        self.assertEqual(created.status_code, 403, created.data)
        self.assertEqual(detail.status_code, 403, detail.data)
        self.assertEqual(deleted.status_code, 403, deleted.data)
