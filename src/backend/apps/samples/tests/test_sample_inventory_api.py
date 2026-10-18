from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee

from ..models import (
    SampleInventoryLine,
    SampleInventoryLoan,
    SampleInventoryLoanLine,
    SampleInventoryOutbound,
    SampleInventoryOutboundLine,
    SampleInventoryReceipt,
    SampleItem,
    SampleProduct,
    SampleRequest,
    SampleRequestStatus,
    SampleOutboundMethod,
)
from ..loan_services import delete_sample_inventory_loan
from ..outbound_services import delete_sample_inventory_outbound


class SampleInventoryApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_inventory_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_INVENTORY_USER",
            display_name="样品库存测试员工",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryline",
            )
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SAMPLE_INVENTORY_CUSTOMER",
            account_name="样品库存测试客户",
            primary_country_code="CN",
        )
        self.sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            request_number="SYGJ-20260902-001",
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
        self.sample_item = SampleItem.objects.create(
            sample_request=self.sample_request,
            sample_product=self.sample_product,
            line_number=1,
            product_description_snapshot="铝框休闲椅",
            specification_snapshot="620×680×820",
            requested_quantity="10.0000",
            unit_code="PCS",
            color_name_snapshot="蓝灰",
            sample_quantity=10,
            cutting_reported_quantity=10,
            metalwork_reported_quantity=10,
            cutting_completed=True,
            metalwork_completed=True,
        )
        self.receipt = SampleInventoryReceipt.objects.create(
            receipt_number="RK-20260902-001",
            submitted_by_employee=self.employee,
            submitted_at=timezone.now(),
        )
        self.inventory_line = SampleInventoryLine.objects.create(
            receipt=self.receipt,
            sample_item=self.sample_item,
            category_name_snapshot="户外桌椅",
            product_name_snapshot="铝框休闲椅",
            specification_snapshot="620×680×820",
            color_name_snapshot="蓝灰",
            sampling_quantity=10,
            received_quantity=10,
            outbound_quantity=2,
            loaned_quantity=2,
            location="样品库",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_returns_only_available_inventory_with_expected_fields(self):
        response = self.client.get("/api/v1/sample-inventory/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["receipt_number"], "RK-20260902-001")
        self.assertEqual(row["sample_request_number"], "SYGJ-20260902-001")
        self.assertEqual(row["product_category"], "户外桌椅")
        self.assertEqual(row["available_quantity"], 6)
        self.assertEqual(row["location"], "样品库")

    def test_list_supports_keyword_category_and_location_filters(self):
        matched = self.client.get(
            "/api/v1/sample-inventory/",
            {"q": "铝框", "category_name": "户外桌椅", "location": "样品库"},
        )
        missing = self.client.get("/api/v1/sample-inventory/", {"q": "不存在的产品"})

        self.assertEqual(matched.status_code, 200, matched.data)
        self.assertEqual(matched.data["meta"]["total"], 1)
        self.assertEqual(missing.status_code, 200, missing.data)
        self.assertEqual(missing.data["meta"]["total"], 0)

    def test_list_supports_inventory_status_filters(self):
        depleted_item = SampleItem.objects.create(
            sample_request=self.sample_request,
            sample_product=self.sample_product,
            line_number=2,
            product_description_snapshot="库存已用完样品",
            requested_quantity="2.0000",
            unit_code="PCS",
            sample_quantity=2,
        )
        SampleInventoryLine.objects.create(
            receipt=self.receipt,
            sample_item=depleted_item,
            product_name_snapshot="库存已用完样品",
            sampling_quantity=2,
            received_quantity=2,
            outbound_quantity=2,
            location="样品库",
        )
        available = self.client.get(
            "/api/v1/sample-inventory/",
            {"inventory_status": "AVAILABLE"},
        )
        depleted = self.client.get(
            "/api/v1/sample-inventory/",
            {"inventory_status": "DEPLETED"},
        )
        invalid = self.client.get(
            "/api/v1/sample-inventory/",
            {"inventory_status": "UNKNOWN"},
        )

        self.assertEqual(available.status_code, 200, available.data)
        self.assertEqual(available.data["meta"]["total"], 1)
        self.assertEqual(depleted.status_code, 200, depleted.data)
        self.assertEqual(depleted.data["meta"]["total"], 1)
        self.assertEqual(depleted.data["data"][0]["available_quantity"], 0)
        self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_fully_depleted_inventory_is_not_listed(self):
        second_item = SampleItem.objects.create(
            sample_request=self.sample_request,
            sample_product=self.sample_product,
            line_number=2,
            product_description_snapshot="库存已用完样品",
            requested_quantity="2.0000",
            unit_code="PCS",
            sample_quantity=2,
        )
        SampleInventoryLine.objects.create(
            receipt=self.receipt,
            sample_item=second_item,
            product_name_snapshot="库存已用完样品",
            sampling_quantity=2,
            received_quantity=2,
            outbound_quantity=2,
            location="样品库",
        )

        response = self.client.get("/api/v1/sample-inventory/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)

    def test_summary_and_options_come_from_inventory_records(self):
        summary = self.client.get("/api/v1/sample-inventory/summary/")
        options = self.client.get("/api/v1/sample-inventory/options/")

        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(
            summary.data["data"],
            {
                "month": timezone.localdate().strftime("%Y-%m"),
                "current_available": 6,
                "borrowed": 2,
                "inbound_today": 10,
                "outbound_today": 0,
                "inbound_this_month": 10,
                "outbound_this_month": 0,
                "loaned_this_month": 0,
            },
        )
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(options.data["data"]["product_categories"], ["户外桌椅"])
        self.assertEqual(options.data["data"]["locations"], ["样品库"])

    @patch("apps.samples.api.inventory_views.timezone.localdate", return_value=date(2026, 10, 17))
    def test_month_summary_uses_local_month_boundaries_and_quantities(self, _localdate):
        # 上海月界限对应 UTC 前一日 16:00；月末最后一秒计入，下月零点排除。
        moments = [
            "2026-09-30T15:59:59+00:00",
            "2026-09-30T16:00:00+00:00",
            "2026-10-31T15:59:59+00:00",
            "2026-10-31T16:00:00+00:00",
        ]
        self.receipt.submitted_at = datetime.fromisoformat(moments[0])
        self.receipt.save(update_fields=["submitted_at"])
        for index, moment in enumerate(moments):
            timestamp = datetime.fromisoformat(moment)
            receipt = SampleInventoryReceipt.objects.create(
                receipt_number=f"RK-MONTH-{index}",
                submitted_by_employee=self.employee,
                submitted_at=timestamp,
            )
            line = SampleInventoryLine.objects.create(
                receipt=receipt, sample_item=self.sample_item,
                product_name_snapshot="月份边界样品", sampling_quantity=10,
                received_quantity=10, outbound_quantity=2, loaned_quantity=3,
            )
            outbound = SampleInventoryOutbound.objects.create(
                outbound_number=f"CK-MONTH-{index}",
                operated_by_employee=self.employee, operated_at=timestamp,
            )
            SampleInventoryOutboundLine.objects.create(
                outbound=outbound, inventory_line=line, outbound_quantity=2,
                outbound_method=SampleOutboundMethod.SALESPERSON_CARRY,
            )
            loan = SampleInventoryLoan.objects.create(
                loan_number=f"JC-MONTH-{index}",
                operated_by_employee=self.employee, operated_at=timestamp,
            )
            SampleInventoryLoanLine.objects.create(
                loan=loan, inventory_line=line, loan_quantity=3,
                borrower_name="测试借用人", purpose_note="测试用途",
            )

        with timezone.override("Asia/Shanghai"):
            response = self.client.get("/api/v1/sample-inventory/summary/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["month"], "2026-10")
        self.assertEqual(response.data["data"]["inbound_this_month"], 20)
        self.assertEqual(response.data["data"]["outbound_this_month"], 4)
        self.assertEqual(response.data["data"]["loaned_this_month"], 6)
        self.assertEqual(response.data["data"]["current_available"], 26)

    @patch("apps.samples.api.inventory_views.timezone.localdate", return_value=date(2027, 1, 15))
    def test_month_summary_returns_real_zero_and_keeps_current_stock(self, _localdate):
        self.receipt.submitted_at = datetime.fromisoformat("2026-12-31T15:59:59+00:00")
        self.receipt.save(update_fields=["submitted_at"])
        with timezone.override("Asia/Shanghai"):
            response = self.client.get("/api/v1/sample-inventory/summary/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["month"], "2027-01")
        self.assertEqual(response.data["data"]["inbound_this_month"], 0)
        self.assertEqual(response.data["data"]["outbound_this_month"], 0)
        self.assertEqual(response.data["data"]["loaned_this_month"], 0)
        self.assertEqual(response.data["data"]["current_available"], 6)

    def test_deleted_documents_no_longer_contribute_to_monthly_totals(self):
        outbound = SampleInventoryOutbound.objects.create(
            outbound_number="CK-MONTH-DELETE", operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        SampleInventoryOutboundLine.objects.create(
            outbound=outbound, inventory_line=self.inventory_line, outbound_quantity=2,
            outbound_method=SampleOutboundMethod.SALESPERSON_CARRY,
        )
        loan = SampleInventoryLoan.objects.create(
            loan_number="JC-MONTH-DELETE", operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        SampleInventoryLoanLine.objects.create(
            loan=loan, inventory_line=self.inventory_line, loan_quantity=2,
            borrower_name="测试借用人", purpose_note="测试用途",
        )
        before = self.client.get("/api/v1/sample-inventory/summary/").data["data"]
        self.assertEqual(before["outbound_this_month"], 2)
        self.assertEqual(before["loaned_this_month"], 2)
        delete_sample_inventory_outbound(outbound_id=outbound.pk, actor_employee=self.employee)
        delete_sample_inventory_loan(loan_id=loan.pk, actor_employee=self.employee)
        after = self.client.get("/api/v1/sample-inventory/summary/").data["data"]
        self.assertEqual(after["outbound_this_month"], 0)
        self.assertEqual(after["loaned_this_month"], 0)
        self.assertEqual(after["current_available"], 10)

    def test_inventory_permission_is_required(self):
        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="sample_inventory_no_permission")
        Employee.objects.create(
            user=other_user,
            employee_code="SAMPLE_INVENTORY_NO_PERMISSION",
            display_name="无库存权限员工",
        )
        self.client.force_authenticate(other_user)

        response = self.client.get("/api/v1/sample-inventory/")

        self.assertEqual(response.status_code, 403, response.data)
        summary = self.client.get("/api/v1/sample-inventory/summary/")
        self.assertEqual(summary.status_code, 403, summary.data)
