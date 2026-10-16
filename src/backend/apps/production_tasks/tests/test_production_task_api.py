import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.api.serializers import BomListSerializer
from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomStatus
from apps.boms.selectors import boms_with_context
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus, PurchaseRequest, PurchaseRequestStatus
from apps.products.models import ProductInformation
from apps.reference_data.models import Currency, ProductColor, ProductionUnit

from ..models import ProductionTask, ProductionTaskProductImage, ProductionTaskStatus


class ProductionTaskApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="production_task_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="PRODUCTION_TASK_USER",
            display_name="生产任务单测试员工",
        )
        self.follower = Employee.objects.create(
            employee_code="PRODUCTION_TASK_FOLLOWER",
            display_name="测试跟单员",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="production_tasks")
        )
        self.customer = CustomerAccount.objects.create(
            account_code="PRODUCTION_TASK_CUSTOMER",
            account_name="生产任务单测试客户",
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        self.product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).select_related(
            "unit"
        ).first()
        self.currency = Currency.objects.get(status="ACTIVE", archived_at__isnull=True, code="CNY")
        self.unit = self.product.unit
        self.color = ProductColor.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        today = timezone.localdate()
        reserved = self.client.post(
            "/api/v1/production-tasks/reserve-contract-number/",
            {"order_date": today.isoformat()},
            format="json",
        )
        self.assertEqual(reserved.status_code, 200, reserved.data)
        data = {
            "task_number": f"HT{uuid4().int}",
            "contract_number_token": reserved.data["data"]["token"],
            "contract_number": reserved.data["data"]["contract_number"],
            "order_source": "NEW",
            "order_number": "ORDER-001",
            "customer_account_id": None,
            "order_date": today.isoformat(),
            "delivery_date": today.isoformat(),
            "salesperson_id": str(self.employee.pk),
            "follower_ids": [str(self.follower.pk)],
            "currency_id": str(self.currency.pk),
            "includes_tax": True,
            "tax_rate": 3,
            "order_tolerance_percent": "3.00",
            "is_repeat_order": False,
            "preproduction_sample_required": True,
            "delivery_method": "SINGLE",
            "special_requirements_html": "<p>重点要求</p><script>alert(1)</script>",
            "freight_amount": "25.0000",
            "other_fee_amount": "5.0000",
            "products": [
                {
                    "client_key": "product-1",
                    "product_id": str(self.product.pk),
                    "product_color_id": str(self.color.pk),
                    "color_code": self.color.color_code,
                    "quantity": 10,
                    "unit_id": str(self.unit.pk),
                    "currency_id": str(self.currency.pk),
                    "unit_price": "12.5000",
                    "exchange_rate": "1.000" if self.currency.code == "CNY" else "7.100",
                    "special_requirements": "包装牢固",
                    "packaging_method": "外箱包装",
                    "retained_image_ids": [],
                    "details": [
                        {
                            "client_key": "detail-1",
                            "template_key": "fabric",
                            "detail_type": "面料",
                            "category_label": "主体",
                            "is_selected": True,
                            "description": "按确认样",
                        }
                    ],
                }
            ],
            "delivery_batches": [],
        }
        data.update(overrides)
        return data

    def create_task(self, **overrides):
        response = self.client.post("/api/v1/production-tasks/", self.payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_preserves_manual_number_and_persists_multi_follower_shape(self):
        response = self.create_task(task_number="HT26199-1")
        data = response.data["data"]
        self.assertEqual(data["task_number"], "HT26199-1")
        self.assertTrue(data["contract_number"].startswith("HTC-"))
        self.assertEqual(data["followers"][0]["display_name"], "测试跟单员")
        self.assertEqual(data["total_quantity"], Decimal("10.0000"))
        self.assertEqual(data["products"][0]["total_amount"], "125.0000")
        self.assertEqual(data["product_total_amount"], Decimal("125.0000"))
        self.assertEqual(data["freight_amount"], "25.0000")
        self.assertEqual(data["other_fee_amount"], "5.0000")
        self.assertEqual(data["total_amount"], Decimal("155.0000"))
        expected_rate = Decimal("1") if self.currency.code == "CNY" else Decimal("7.1")
        self.assertEqual(Decimal(data["products"][0]["local_unit_price"]), Decimal("12.5") * expected_rate)
        self.assertEqual(Decimal(data["products"][0]["local_total_amount"]), Decimal("125") * expected_rate)
        self.assertNotIn("script", data["special_requirements_html"])
        self.assertEqual(data["products"][0]["packaging_method"], "外箱包装")
        self.assertTrue(response.has_header("ETag"))

    def test_manual_creation_accepts_unlinked_product_snapshots_without_fake_identifiers(self):
        product_line = self.payload()["products"][0]
        product_line.pop("product_id")
        product_line.pop("product_color_id")
        product_line["color_code"] = ""
        product_line["customer_product_name"] = "客户自填折叠椅"
        product_line["customer_specification"] = "客户规格 120×60"
        product_line["customer_color"] = "客户蓝"

        response = self.client.post("/api/v1/production-tasks/", self.payload(products=[product_line]), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        product = response.data["data"]["products"][0]
        self.assertIsNone(product["product_id"])
        self.assertEqual(product["product_number"], "")
        self.assertEqual(product["product_code"], "")
        self.assertEqual(product["item_number"], "")
        self.assertEqual(product["product_name"], "客户自填折叠椅")
        self.assertEqual(product["specification"], "客户规格 120×60")
        self.assertEqual(product["customer_color"], "客户蓝")
        line = ProductionTask.objects.get(pk=response.data["data"]["id"]).products.get()
        self.assertIsNone(line.product_id)
        self.assertEqual(line.product_number_snapshot, "")
        self.assertEqual(line.item_number_snapshot, "")
        self.assertEqual(line.customer_product_name_snapshot, "客户自填折叠椅")
        self.assertEqual(line.customer_specification_snapshot, "客户规格 120×60")
        self.assertEqual(line.customer_color_snapshot, "客户蓝")

    def test_reserve_contract_number_returns_immediate_unique_number(self):
        today = timezone.localdate().isoformat()
        first = self.client.post(
            "/api/v1/production-tasks/reserve-contract-number/",
            {"order_date": today},
            format="json",
        )
        second = self.client.post(
            "/api/v1/production-tasks/reserve-contract-number/",
            {"order_date": today},
            format="json",
        )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertRegex(first.data["data"]["contract_number"], r"^HTC-\d{6}-\d{6}$")
        self.assertNotEqual(first.data["data"]["contract_number"], second.data["data"]["contract_number"])
        self.assertTrue(first.data["data"]["token"])

    def test_create_rejects_missing_contract_number_token(self):
        payload = self.payload()
        payload.pop("contract_number_token")
        response = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("contract_number_token", response.data["error"]["field_errors"])

    def test_contract_number_can_be_edited_and_must_remain_unique(self):
        custom_number = "CUSTOM-CONTRACT-001"
        first = self.create_task(contract_number=custom_number)
        self.assertEqual(first.data["data"]["contract_number"], custom_number)

        duplicate = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(contract_number=custom_number),
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertIn("合同编号", duplicate.data["error"]["message"])

    def test_list_filters_stats_and_options_use_system_data(self):
        created = self.create_task()
        # 历史任务保留客户关联，继续覆盖既有筛选契约。
        ProductionTask.objects.filter(pk=created.data["data"]["id"]).update(customer_account=self.customer)
        listed = self.client.get(
            "/api/v1/production-tasks/",
            {
                "order_source": "NEW",
                "delivery_method": "SINGLE",
                "contract_number": created.data["data"]["contract_number"],
                "customer_id": str(self.customer.pk),
                "product_id": str(self.product.pk),
                "salesperson_id": str(self.employee.pk),
                "follower_id": str(self.follower.pk),
                "delivery_from": timezone.localdate().isoformat(),
                "delivery_to": timezone.localdate().isoformat(),
            },
        )
        stats = self.client.get("/api/v1/production-tasks/stats/")
        options = self.client.get("/api/v1/production-tasks/options/")

        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["meta"]["total"], 1)
        self.assertEqual(listed.data["data"][0]["currency_code"], self.currency.code)
        self.assertEqual(Decimal(listed.data["data"][0]["total_amount"]), Decimal("155"))
        self.assertEqual(stats.data["data"]["draft"], 1)
        self.assertEqual(stats.data["data"]["ready"], 0)
        self.assertEqual(stats.data["data"]["in_production"], 0)
        self.assertEqual(stats.data["data"]["completed"], 0)
        self.assertEqual(stats.data["data"]["paused"], 0)
        self.assertEqual(stats.data["data"]["cancelled"], 0)
        filtered_stats = self.client.get(
            "/api/v1/production-tasks/stats/",
            {"search": created.data["data"]["task_number"], "status": "COMPLETED"},
        )
        self.assertEqual(filtered_stats.status_code, 200, filtered_stats.data)
        self.assertEqual(filtered_stats.data["data"]["all"], 1)
        self.assertEqual(filtered_stats.data["data"]["draft"], 1)
        self.assertTrue(any(item["id"] == str(self.product.pk) for item in options.data["data"]["products"]))
        self.assertTrue(any(item["id"] == str(self.currency.pk) for item in options.data["data"]["currencies"]))
        self.assertTrue(any(item["id"] == str(self.unit.pk) for item in options.data["data"]["units"]))

        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        task.products.update(product_name_snapshot="=1+1")
        exported = self.client.post(
            "/api/v1/production-tasks/export/",
            {"ids": [str(task.pk)]},
            format="json",
            QUERY_STRING=f"status={ProductionTaskStatus.DRAFT}",
        )
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported["Content-Type"])
        self.assertEqual(exported["X-Export-Count"], "1")
        exported_text = exported.content.decode("utf-8-sig")
        self.assertIn("'=1+1", exported_text)
        self.assertIn(task.task_number, exported_text)
        self.assertNotIn("客户", exported_text)

        invalid_export = self.client.post(
            "/api/v1/production-tasks/export/", {"ids": ["not-a-uuid"]}, format="json"
        )
        self.assertEqual(invalid_export.status_code, 400, invalid_export.data)
        invalid_stats_status = self.client.get("/api/v1/production-tasks/stats/", {"status": "UNKNOWN"})
        self.assertEqual(invalid_stats_status.status_code, 400, invalid_stats_status.data)

        invalid = self.client.get("/api/v1/production-tasks/?customer_id=not-a-uuid")
        self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_list_exposes_latest_bom_and_purchase_progress(self):
        created = self.create_task()
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])

        initial = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertEqual(initial.data["data"][0]["bom_status"], "NOT_CREATED")
        self.assertEqual(initial.data["data"][0]["bom_status_display"], "未建立")
        self.assertEqual(initial.data["data"][0]["purchase_status"], "NOT_STARTED")
        self.assertEqual(initial.data["data"][0]["purchase_status_display"], "未发起")

        product_line = task.products.get()
        first_bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-LIST-STATUS-V1",
            production_task=task,
            product_line=product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.PENDING_CONFIRMATION,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            product_category_snapshot=product_line.product.category.category_name,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        purchase_order = PurchaseOrder.objects.create(
            order_number="CGDD2026091409",
            production_task=task,
            production_task_number_snapshot=task.task_number,
            sales_order_number_snapshot=task.order_number,
            customer_name_snapshot=task.customer_account.account_name if task.customer_account_id else "",
            source_revision="production-list-status-test",
            status=PurchaseOrderStatus.PURCHASING,
            created_by_employee=self.employee,
        )

        pending = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual(pending.data["data"][0]["bom_status"], "PENDING_CONFIRMATION")
        self.assertEqual(pending.data["data"][0]["bom_status_display"], "待确认")
        self.assertEqual(pending.data["data"][0]["purchase_status"], "ORDER_PURCHASING")
        self.assertEqual(pending.data["data"][0]["purchase_status_display"], "采购中")

        verified_bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-LIST-STATUS-V2",
            production_task=task,
            product_line=product_line,
            version_number=2,
            creation_method=BomCreationMethod.COPY,
            status=BomStatus.VERIFIED,
            copied_from=first_bom,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            product_category_snapshot=product_line.product.category.category_name,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        verified = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data["data"][0]["bom_status"], "VERIFIED")
        self.assertEqual(verified.data["data"][0]["bom_status_display"], "已确认")

        purchase_order.archived_at = timezone.now()
        purchase_order.save(update_fields=["archived_at", "updated_at"])
        PurchaseRequest.objects.create(
            request_number="CGRQ-PRODUCTION-LIST-STATUS-1",
            production_task=task,
            bom=first_bom,
            status=PurchaseRequestStatus.SUBMITTED,
            requested_by_employee=self.employee,
        )
        request_fallback = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(request_fallback.status_code, 200, request_fallback.data)
        self.assertEqual(request_fallback.data["data"][0]["purchase_status"], "REQUEST_SUBMITTED")
        self.assertEqual(request_fallback.data["data"][0]["purchase_status_display"], "采购申请已提交")

        PurchaseRequest.objects.create(
            request_number="CGRQ-PRODUCTION-LIST-STATUS-2",
            production_task=task,
            bom=verified_bom,
            status=PurchaseRequestStatus.DRAFT,
            requested_by_employee=self.employee,
        )
        mixed_requests = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(mixed_requests.status_code, 200, mixed_requests.data)
        self.assertEqual(mixed_requests.data["data"][0]["purchase_status"], "REQUEST_MIXED")
        self.assertEqual(mixed_requests.data["data"][0]["purchase_status_display"], "多状态")

        verified_bom.archived_at = timezone.now()
        verified_bom.save(update_fields=["archived_at", "updated_at"])
        archived_latest = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(archived_latest.status_code, 200, archived_latest.data)
        self.assertEqual(archived_latest.data["data"][0]["bom_status"], "PENDING_CONFIRMATION")

    def test_list_reports_partial_bom_for_multi_product_task(self):
        payload = self.payload()
        first_product = payload["products"][0]
        second_product = deepcopy(first_product)
        second_product.update(
            client_key="product-2",
            quantity=6,
            details=[{
                "client_key": "detail-2",
                "template_key": "hardware",
                "detail_type": "五金件",
                "category_label": "主体",
                "is_selected": True,
                "description": "第二条产品明细",
            }],
        )
        payload["products"] = [first_product, second_product]
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data["data"]["id"])
        first_line = task.products.order_by("line_number").first()
        Bom.objects.create(
            bom_number="BOM-PRODUCTION-LIST-PARTIAL",
            production_task=task,
            product_line=first_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=first_line.product_number_snapshot,
            product_code_snapshot=first_line.product_code_snapshot,
            product_name_snapshot=first_line.product_name_snapshot,
            specification_snapshot=first_line.specification_snapshot,
            product_category_snapshot=first_line.product.category.category_name,
            order_quantity=first_line.quantity,
            created_by_employee=self.employee,
        )

        listed = self.client.get("/api/v1/production-tasks/", {"search": task.task_number})
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["data"][0]["bom_status"], "PARTIAL")
        self.assertEqual(listed.data["data"][0]["bom_status_display"], "部分建立")

    def test_list_progress_prefetch_has_bounded_query_count(self):
        for index in range(5):
            self.create_task(order_number=f"QUERY-COUNT-{index}")

        with CaptureQueriesContext(connection) as queries:
            listed = self.client.get("/api/v1/production-tasks/", {"search": "QUERY-COUNT"})

        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(len(listed.data["data"]), 5)
        self.assertLessEqual(len(queries), 20, [query["sql"] for query in queries])

    def test_submit_rejects_batch_difference_without_auto_correction(self):
        payload = self.payload(
            delivery_method="SPLIT",
            delivery_batches=[
                {
                    "quantity": "9.0000",
                    "delivery_date": timezone.localdate().isoformat(),
                    "note": "第一批",
                }
            ],
        )
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_id = created.data["data"]["id"]
        quantity_pending = self.client.get("/api/v1/production-tasks/?quantity_pending=true")
        due_soon = self.client.get("/api/v1/production-tasks/?due_within_days=30")
        self.assertEqual(quantity_pending.status_code, 200, quantity_pending.data)
        self.assertEqual([item["id"] for item in quantity_pending.data["data"]], [task_id])
        self.assertEqual(due_soon.status_code, 200, due_soon.data)
        self.assertIn(task_id, [item["id"] for item in due_soon.data["data"]])
        submitted = self.client.post(
            f"/api/v1/production-tasks/{task_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(submitted.status_code, 400, submitted.data)
        self.assertIn("不一致", submitted.data["error"]["message"])
        self.assertEqual(ProductionTask.objects.get(pk=task_id).status, ProductionTaskStatus.DRAFT)

    def test_submit_requires_etag_and_moves_valid_draft_to_pending_validation(self):
        created = self.create_task()
        task_id = created.data["data"]["id"]
        missing = self.client.post(f"/api/v1/production-tasks/{task_id}/submit/", {}, format="json")
        submitted = self.client.post(
            f"/api/v1/production-tasks/{task_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(missing.status_code, 428, missing.data)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["data"]["status"], ProductionTaskStatus.PENDING_VALIDATION)

    def test_cancel_and_finish_require_reason_and_preserve_audit_trail(self):
        created = self.create_task()
        task_id = created.data["data"]["id"]

        missing_etag = self.client.post(
            f"/api/v1/production-tasks/{task_id}/cancel/",
            {"reason": "客户取消采购"},
            format="json",
        )
        blank_reason = self.client.post(
            f"/api/v1/production-tasks/{task_id}/cancel/",
            {"reason": "   "},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        cancelled = self.client.post(
            f"/api/v1/production-tasks/{task_id}/cancel/",
            {"reason": "客户取消采购"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)
        self.assertEqual(blank_reason.status_code, 400, blank_reason.data)
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["data"]["status"], ProductionTaskStatus.CANCELLED)
        self.assertEqual(cancelled.data["data"]["status_reason"], "客户取消采购")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="PRODUCTION_TASK",
                object_id=task_id,
                action="CANCELLED",
                after_data__status_reason="客户取消采购",
            ).exists()
        )

        finish_created = self.create_task(order_number="ORDER-002")
        finished = self.client.post(
            f"/api/v1/production-tasks/{finish_created.data['data']['id']}/finish/",
            {"reason": "订单已全部交付"},
            format="json",
            HTTP_IF_MATCH=finish_created["ETag"],
        )
        self.assertEqual(finished.status_code, 200, finished.data)
        self.assertEqual(finished.data["data"]["status"], ProductionTaskStatus.COMPLETED)
        self.assertEqual(finished.data["data"]["status_reason"], "订单已全部交付")

    def test_rejects_invalid_dates_and_allows_salesperson_as_selected_follower(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        bad_date = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(delivery_date=yesterday.isoformat()),
            format="json",
        )
        duplicate_follower = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(follower_ids=[str(self.employee.pk)]),
            format="json",
        )
        self.assertEqual(bad_date.status_code, 400, bad_date.data)
        self.assertEqual(duplicate_follower.status_code, 201, duplicate_follower.data)

    def test_allows_multiple_products_with_details_on_each_color_line(self):
        another_product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).exclude(
            pk=self.product.pk
        ).first()
        if not another_product:
            self.skipTest("测试数据没有第二个产品。")
        product_lines = self.payload()["products"]
        second = dict(product_lines[0])
        second.update(
            client_key="product-2",
            product_id=str(another_product.pk),
            unit_id=str(another_product.unit_id),
            special_requirements="第二个产品要求",
            packaging_method="第二个产品包装",
            details=[{
                "client_key": "detail-2",
                "template_key": "hardware",
                "detail_type": "五金件",
                "category_label": "主体",
                "is_selected": True,
                "description": "按确认样",
            }],
        )
        response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[product_lines[0], second]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        saved_products = response.data["data"]["products"]
        self.assertEqual({item["product_id"] for item in saved_products}, {str(self.product.pk), str(another_product.pk)})
        self.assertEqual([len(item["details"]) for item in saved_products], [1, 1])

    def test_same_product_color_lines_keep_independent_details_and_requirements(self):
        product_lines = self.payload()["products"]
        first = product_lines[0]
        second = dict(first)
        second.update(
            client_key="product-2",
            quantity=6,
            special_requirements="第二条颜色要求",
            packaging_method="第二条颜色包装",
            details=[{
                "client_key": "detail-2",
                "template_key": "hardware",
                "detail_type": "五金件",
                "category_label": "主体",
                "is_selected": True,
                "description": "第二条颜色明细",
            }],
        )
        response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[first, second]),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        saved_products = response.data["data"]["products"]
        self.assertEqual(len(saved_products), 2)
        self.assertEqual(
            [item["special_requirements"] for item in saved_products],
            ["包装牢固", "第二条颜色要求"],
        )
        self.assertEqual(
            [item["details"][0]["detail_type"] for item in saved_products],
            ["面料", "五金件"],
        )

    def test_rejects_wrong_unit_color_and_missing_product_details(self):

        another_unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).exclude(pk=self.unit.pk).first()
        if another_unit:
            wrong_unit_product = dict(self.payload()["products"][0])
            wrong_unit_product["unit_id"] = str(another_unit.pk)
            wrong_unit = self.client.post(
                "/api/v1/production-tasks/",
                self.payload(products=[wrong_unit_product]),
                format="json",
            )
            self.assertEqual(wrong_unit.status_code, 400, wrong_unit.data)
            self.assertIn("生产维护单位", wrong_unit.data["error"]["message"])

        wrong_color_product = dict(self.payload()["products"][0])
        wrong_color_product["color_code"] = "NOT-MATCHED"
        wrong_color = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[wrong_color_product]),
            format="json",
        )
        self.assertEqual(wrong_color.status_code, 400, wrong_color.data)
        self.assertIn("色号", wrong_color.data["error"]["message"])

        blank_special_product = dict(self.payload()["products"][0])
        blank_special_product["special_requirements"] = ""
        blank_special = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[blank_special_product]),
            format="json",
        )
        self.assertEqual(blank_special.status_code, 201, blank_special.data)
        self.assertEqual(blank_special.data["data"]["products"][0]["special_requirements"], "")

        missing_details_product = dict(self.payload()["products"][0])
        missing_details_product["details"] = []
        missing_details = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[missing_details_product]),
            format="json",
        )
        self.assertEqual(missing_details.status_code, 400, missing_details.data)
        self.assertIn("第 1 条颜色明细", missing_details.data["error"]["message"])

    def test_detail_selection_respects_manual_choice(self):
        described_product = dict(self.payload()["products"][0])
        described_detail = dict(described_product["details"][0])
        described_detail["is_selected"] = False
        described_detail["description"] = "按确认样"
        described_product["details"] = [described_detail]
        described_response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[described_product]),
            format="json",
        )
        self.assertEqual(described_response.status_code, 201, described_response.data)
        self.assertFalse(described_response.data["data"]["products"][0]["details"][0]["is_selected"])

        blank_product = dict(self.payload()["products"][0])
        blank_detail = dict(blank_product["details"][0])
        blank_detail["is_selected"] = True
        blank_detail["description"] = ""
        blank_product["details"] = [blank_detail]
        blank_response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[blank_product]),
            format="json",
        )
        self.assertEqual(blank_response.status_code, 201, blank_response.data)
        self.assertTrue(blank_response.data["data"]["products"][0]["details"][0]["is_selected"])

    def test_quantity_must_be_integer_and_exchange_rate_has_at_most_eight_decimals(self):
        fractional_quantity = dict(self.payload()["products"][0])
        fractional_quantity["quantity"] = "1.5"
        quantity_response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[fractional_quantity]),
            format="json",
        )
        self.assertEqual(quantity_response.status_code, 400, quantity_response.data)

        precise_rate = dict(self.payload()["products"][0])
        precise_rate["exchange_rate"] = "1.000000001"
        rate_response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(products=[precise_rate]),
            format="json",
        )
        self.assertEqual(rate_response.status_code, 400, rate_response.data)

    def test_cny_exchange_rate_must_equal_one(self):
        cny = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True, code="CNY").first()
        if not cny:
            self.skipTest("测试数据没有 CNY 币种。")
        product = dict(self.payload()["products"][0])
        product.update(currency_id=str(cny.pk), exchange_rate="7.100")
        response = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(currency_id=str(cny.pk), products=[product]),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("汇率必须为 1", response.data["error"]["message"])

    def test_rejects_negative_fees_and_product_currency_different_from_basic_information(self):
        negative_fee = self.client.post(
            "/api/v1/production-tasks/",
            self.payload(freight_amount="-0.0001"),
            format="json",
        )
        self.assertEqual(negative_fee.status_code, 400, negative_fee.data)

        another_currency = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True).exclude(
            pk=self.currency.pk
        ).first()
        if another_currency:
            product = dict(self.payload()["products"][0])
            product["currency_id"] = str(another_currency.pk)
            mismatched = self.client.post(
                "/api/v1/production-tasks/",
                self.payload(products=[product]),
                format="json",
            )
            self.assertEqual(mismatched.status_code, 400, mismatched.data)
            self.assertIn("基础信息一致", mismatched.data["error"]["message"])

    @patch("apps.production_tasks.services.save_scanned_image")
    def test_each_color_line_can_save_multiple_images(self, save_scanned_image):
        first_image = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="front.png",
            storage_key="production_tasks/test-front.png",
            content_type="image/png",
            size_bytes=4,
            scan_status=FileScanStatus.CLEAN,
        )
        second_image = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="detail.png",
            storage_key="production_tasks/test-detail.png",
            content_type="image/png",
            size_bytes=4,
            scan_status=FileScanStatus.CLEAN,
        )
        save_scanned_image.side_effect = [first_image, second_image]
        payload = self.payload()
        response = self.client.post(
            "/api/v1/production-tasks/",
            {
                "payload": json.dumps(payload),
                "product_image_product-1": [
                    SimpleUploadedFile("front.png", b"test", content_type="image/png"),
                    SimpleUploadedFile("detail.png", b"test", content_type="image/png"),
                ],
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([item["name"] for item in response.data["data"]["products"][0]["images"]], ["front.png", "detail.png"])
        self.assertEqual(ProductionTaskProductImage.objects.count(), 2)

        third_image = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="package.png",
            storage_key="production_tasks/test-package.png",
            content_type="image/png",
            size_bytes=4,
            scan_status=FileScanStatus.CLEAN,
        )
        save_scanned_image.side_effect = [third_image]
        task_data = response.data["data"]
        update_payload = {"products": [dict(payload["products"][0])]}
        update_payload["products"][0]["client_key"] = task_data["products"][0]["id"]
        update_payload["products"][0]["retained_image_ids"] = [task_data["products"][0]["images"][1]["id"]]
        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            {
                "payload": json.dumps(update_payload),
                f"product_image_{task_data['products'][0]['id']}": [
                    SimpleUploadedFile("package.png", b"test", content_type="image/png"),
                ],
            },
            format="multipart",
            HTTP_IF_MATCH=response["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(
            [item["name"] for item in updated.data["data"]["products"][0]["images"]],
            ["detail.png", "package.png"],
        )
        self.assertEqual(ProductionTaskProductImage.objects.count(), 2)

    def test_edit_preserves_product_line_referenced_by_bom(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        product_line = ProductionTask.objects.get(pk=task_data["id"]).products.get(pk=product_data["id"])
        bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-TASK-EDIT-001",
            production_task=product_line.production_task,
            product_line=product_line,
            creation_method=BomCreationMethod.BLANK,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["quantity"] = 11
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_detail["description"] = "编辑后仍保留 BOM 关联"
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 409, updated.data)
        self.assertEqual(updated.data["error"]["code"], "BOM_SYNC_CONFIRMATION_REQUIRED")
        confirmation_token = updated.data["error"]["meta"]["confirmation_token"]
        self.assertTrue(confirmation_token)
        product_line.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(product_line.quantity, 10)
        self.assertEqual(bom.order_quantity, 10)

        update_payload["bom_sync_mode"] = "KEEP"
        update_payload["bom_sync_token"] = confirmation_token
        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["products"][0]["id"], product_data["id"])
        product_line.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(product_line.quantity, 11)
        self.assertEqual(product_line.details.get().description, "编辑后仍保留 BOM 关联")
        self.assertEqual(bom.product_line_id, product_line.pk)
        self.assertEqual(bom.order_quantity, 10)
        serialized_bom = BomListSerializer(boms_with_context().get(pk=bom.pk)).data
        self.assertEqual(Decimal(serialized_bom["current_order_quantity"]), Decimal("11"))
        self.assertTrue(serialized_bom["is_order_quantity_outdated"])
        self.assertTrue(serialized_bom["quantity_requires_confirmation"])

        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="boms", codename="change_bom")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        update_payload.pop("bom_sync_mode")
        update_payload.pop("bom_sync_token")
        repair_confirmation = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(repair_confirmation.status_code, 409, repair_confirmation.data)
        repair_line = repair_confirmation.data["error"]["meta"]["affected_lines"][0]
        self.assertEqual(repair_line["old_quantity"], "11")
        self.assertEqual(repair_line["new_quantity"], "11")
        self.assertEqual(Decimal(repair_line["bom_quantity"]), Decimal("10"))

        update_payload["bom_sync_mode"] = "SYNC"
        update_payload["bom_sync_token"] = repair_confirmation.data["error"]["meta"]["confirmation_token"]
        repaired = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(repaired.status_code, 200, repaired.data)
        bom.refresh_from_db()
        self.assertEqual(bom.order_quantity, 11)

    def test_product_change_with_bom_requires_confirmation_and_can_sync_snapshot(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        product_line = ProductionTask.objects.get(pk=task_data["id"]).products.get(pk=product_data["id"])
        bom = Bom.objects.create(
            bom_number="BOM-PRODUCT-CHANGE-001",
            production_task=product_line.production_task,
            product_line=product_line,
            creation_method=BomCreationMethod.BLANK,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        replacement = ProductInformation.objects.create(
            product_number="PRODUCTION-TASK-REPLACEMENT-001",
            product_code="PRODUCTION-TASK-REPLACEMENT-CODE",
            category=self.product.category,
            product_name="替换后的产品",
            specification="替换后的规格",
            unit=self.product.unit,
            product_item=self.product.product_item,
            scale=self.product.scale,
            status="ACTIVE",
        )
        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["product_id"] = str(replacement.pk)
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        confirmation = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmation.status_code, 409, confirmation.data)
        affected = confirmation.data["error"]["meta"]["affected_lines"][0]
        self.assertIn("PRODUCT", affected["change_types"])
        self.assertEqual(affected["new_product_name"], replacement.product_name)

        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="boms", codename="change_bom")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        update_payload["bom_sync_mode"] = "SYNC"
        update_payload["bom_sync_token"] = confirmation.data["error"]["meta"]["confirmation_token"]
        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        product_line.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(product_line.product_id, replacement.pk)
        self.assertEqual(bom.product_name_snapshot, replacement.product_name)
        self.assertEqual(bom.specification_snapshot, replacement.specification)
        serialized_bom = BomListSerializer(boms_with_context().get(pk=bom.pk)).data
        self.assertFalse(serialized_bom["is_order_product_outdated"])

    def test_partial_update_without_delivery_batches_preserves_existing_batches(self):
        payload = self.payload(
            delivery_method="SPLIT",
            delivery_batches=[
                {
                    "quantity": "10.0000",
                    "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
                    "note": "保留的批次",
                }
            ],
        )
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = task_data["products"][0]["id"]
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = task_data["products"][0]["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(len(updated.data["data"]["delivery_batches"]), 1)
        self.assertEqual(updated.data["data"]["delivery_batches"][0]["note"], "保留的批次")

    def test_precise_partial_update_preserves_omitted_relations_and_hidden_fields(self):
        payload = self.payload(
            delivery_method="SPLIT",
            delivery_batches=[
                {
                    "quantity": "10.0000",
                    "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
                    "note": "不能被精确 PATCH 清空",
                }
            ],
        )
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        original_product_id = task_data["products"][0]["id"]
        original_follower_ids = [item["id"] for item in task_data["followers"]]
        new_delivery_date = (timezone.localdate() + timedelta(days=15)).isoformat()

        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            {"delivery_date": new_delivery_date},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        result = updated.data["data"]
        self.assertEqual(result["delivery_date"], new_delivery_date)
        self.assertEqual(result["contract_number"], task_data["contract_number"])
        self.assertEqual([item["id"] for item in result["followers"]], original_follower_ids)
        self.assertEqual([item["id"] for item in result["products"]], [original_product_id])
        self.assertEqual(len(result["delivery_batches"]), 1)
        self.assertEqual(result["delivery_batches"][0]["note"], "不能被精确 PATCH 清空")

    def test_empty_partial_update_is_rejected(self):
        created = self.client.post("/api/v1/production-tasks/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)

        updated = self.client.patch(
            f"/api/v1/production-tasks/{created.data['data']['id']}/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 400, updated.data)

        controls_only = self.client.patch(
            f"/api/v1/production-tasks/{created.data['data']['id']}/",
            {"bom_sync_mode": "KEEP"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(controls_only.status_code, 400, controls_only.data)

        batches_only = self.client.patch(
            f"/api/v1/production-tasks/{created.data['data']['id']}/",
            {
                "delivery_batches": [
                    {
                        "quantity": "10.0000",
                        "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
                        "note": "不能单独更新",
                    }
                ]
            },
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(batches_only.status_code, 400, batches_only.data)

    def test_partial_update_rejects_fields_outside_v3_edit_contract(self):
        created = self.client.post("/api/v1/production-tasks/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]

        updated = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            {"order_number": "BYPASS-ORDER-001"},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )

        self.assertEqual(updated.status_code, 400, updated.data)
        self.assertIn("order_number", updated.data["error"]["field_errors"])
        task = ProductionTask.objects.get(pk=task_data["id"])
        self.assertEqual(task.order_number, task_data["order_number"])

    def test_quantity_change_can_sync_bom_and_recalculate_profile_lines(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        product_line = ProductionTask.objects.get(pk=task_data["id"]).products.get(pk=product_data["id"])
        bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-TASK-SYNC-001",
            production_task=product_line.production_task,
            product_line=product_line,
            creation_method=BomCreationMethod.BLANK,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            product_category_snapshot=product_line.product.category.category_name,
            order_quantity=product_line.quantity,
            section_count=1,
            line_count=2,
            created_by_employee=self.employee,
        )
        section = BomSection.objects.create(
            bom=bom,
            line_number=1,
            section_type="PROFILE",
            title="管材类",
        )
        line = BomLine.objects.create(
            section=section,
            line_number=1,
            part_name="主管",
            length_value="1000",
            unit_consumption="2",
            total_consumption="20",
            branch_count="5.05",
            raw_values={"tube_cut_piece_count": "4", "long_material_total_weight_kg": "9.49"},
        )
        unresolved_line = BomLine.objects.create(
            section=section,
            line_number=2,
            part_name="缺少计算依据的管材",
            unit_consumption="",
            total_consumption="人工值",
            branch_count="人工支数",
            raw_values={"long_material_total_weight_kg": "人工重量"},
        )
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="boms", codename="change_bom")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["quantity"] = 12
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        confirmation = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmation.status_code, 409, confirmation.data)
        self.assertEqual(confirmation.data["error"]["meta"]["affected_bom_count"], 1)
        self.assertEqual(confirmation.data["error"]["meta"]["affected_lines"][0]["old_quantity"], "10")
        self.assertEqual(confirmation.data["error"]["meta"]["affected_lines"][0]["new_quantity"], "12")
        confirmation_token = confirmation.data["error"]["meta"]["confirmation_token"]
        self.assertTrue(confirmation_token)

        update_payload["bom_sync_mode"] = "SYNC"
        update_payload["bom_sync_token"] = confirmation_token
        synced = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(synced.status_code, 200, synced.data)
        product_line.refresh_from_db()
        bom.refresh_from_db()
        line.refresh_from_db()
        unresolved_line.refresh_from_db()
        self.assertEqual(product_line.quantity, 12)
        self.assertEqual(bom.order_quantity, 12)
        self.assertEqual(bom.status, BomStatus.PENDING_CONFIRMATION)
        self.assertEqual(line.total_consumption, "24")
        # 当前管材规则按整根向上取整：24 × 1.01 / 4 得到 7 根。
        self.assertEqual(line.branch_count, "7")
        self.assertEqual(line.raw_values["long_material_total_weight_kg"], "13.1544")
        # 当前缺参草稿规则清空无法重新计算的值，待补齐依据后再确认。
        self.assertEqual(unresolved_line.total_consumption, "")
        self.assertEqual(unresolved_line.branch_count, "")
        self.assertEqual(unresolved_line.raw_values["long_material_total_weight_kg"], "")
        self.assertTrue(
            AuditLog.objects.filter(
                object_type="BOM",
                object_id=bom.pk,
                action="SYNC_FROM_PRODUCTION_TASK",
            ).exists()
        )

    def test_syncing_verified_bom_creates_new_version_and_keeps_history(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        product_line = ProductionTask.objects.get(pk=task_data["id"]).products.get(pk=product_data["id"])
        verified_bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-TASK-SYNC-HISTORY-V1",
            production_task=product_line.production_task,
            product_line=product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            product_category_snapshot=product_line.product.category.category_name,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        BomSection.objects.create(
            bom=verified_bom,
            line_number=1,
            section_type="PROFILE",
            title="管材类",
        )
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="boms",
                codename__in=["add_bom", "change_bom"],
            )
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["quantity"] = 15
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        confirmation = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmation.status_code, 409, confirmation.data)
        confirmation_token = confirmation.data["error"]["meta"]["confirmation_token"]
        self.assertTrue(confirmation_token)

        update_payload["bom_sync_mode"] = "SYNC"
        update_payload["bom_sync_token"] = confirmation_token
        synced = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(synced.status_code, 200, synced.data)
        verified_bom.refresh_from_db()
        newest = Bom.objects.exclude(pk=verified_bom.pk).get(product_line=product_line)
        self.assertEqual(verified_bom.order_quantity, 10)
        self.assertEqual(verified_bom.status, BomStatus.VERIFIED)
        self.assertEqual(newest.version_number, 2)
        self.assertEqual(newest.order_quantity, 15)
        self.assertEqual(newest.status, BomStatus.PENDING_CONFIRMATION)
        self.assertEqual(newest.copied_from_id, verified_bom.pk)

    def test_bom_sync_mode_requires_valid_confirmation_token_without_writing(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        task = ProductionTask.objects.get(pk=task_data["id"])
        product_line = task.products.get(pk=product_data["id"])
        bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-TASK-TOKEN-001",
            production_task=task,
            product_line=product_line,
            creation_method=BomCreationMethod.BLANK,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="boms", codename="change_bom")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["quantity"] = 13
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}
        update_payload["bom_sync_mode"] = "SYNC"

        missing_token = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(missing_token.status_code, 409, missing_token.data)
        self.assertEqual(missing_token.data["error"]["code"], "BOM_SYNC_CONFIRMATION_REQUIRED")
        valid_token = missing_token.data["error"]["meta"]["confirmation_token"]
        self.assertTrue(valid_token)

        bom.updated_at = timezone.now() + timedelta(seconds=1)
        bom.save(update_fields=["updated_at"])
        update_payload["bom_sync_token"] = valid_token
        stale_token = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(stale_token.status_code, 409, stale_token.data)
        self.assertEqual(stale_token.data["error"]["code"], "BOM_SYNC_CONFIRMATION_REQUIRED")
        self.assertNotEqual(
            stale_token.data["error"]["meta"]["confirmation_token"],
            valid_token,
        )

        update_payload["bom_sync_token"] = "forged-token"
        forged_token = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(forged_token.status_code, 409, forged_token.data)
        self.assertEqual(forged_token.data["error"]["code"], "BOM_SYNC_CONFIRMATION_REQUIRED")
        self.assertTrue(forged_token.data["error"]["meta"]["confirmation_token"])

        product_line.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(product_line.quantity, 10)
        self.assertEqual(bom.order_quantity, 10)
        self.assertFalse(
            AuditLog.objects.filter(
                object_type="BOM",
                object_id=bom.pk,
                action="SYNC_FROM_PRODUCTION_TASK",
            ).exists()
        )

    def test_syncing_verified_bom_without_add_permission_is_forbidden_without_writing(self):
        payload = self.payload()
        created = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        task_data = created.data["data"]
        product_data = task_data["products"][0]
        task = ProductionTask.objects.get(pk=task_data["id"])
        product_line = task.products.get(pk=product_data["id"])
        verified_bom = Bom.objects.create(
            bom_number="BOM-PRODUCTION-TASK-PERMISSION-V1",
            production_task=task,
            product_line=product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=product_line.product_number_snapshot,
            product_code_snapshot=product_line.product_code_snapshot,
            product_name_snapshot=product_line.product_name_snapshot,
            specification_snapshot=product_line.specification_snapshot,
            order_quantity=product_line.quantity,
            created_by_employee=self.employee,
        )
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="boms", codename="change_bom")
        )
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

        updated_product = dict(payload["products"][0])
        updated_product["client_key"] = product_data["id"]
        updated_product["quantity"] = 14
        updated_detail = dict(updated_product["details"][0])
        updated_detail["client_key"] = product_data["details"][0]["id"]
        updated_product["details"] = [updated_detail]
        update_payload = {"products": [updated_product]}

        confirmation = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmation.status_code, 409, confirmation.data)
        update_payload["bom_sync_mode"] = "SYNC"
        update_payload["bom_sync_token"] = confirmation.data["error"]["meta"]["confirmation_token"]

        forbidden = self.client.patch(
            f"/api/v1/production-tasks/{task_data['id']}/",
            update_payload,
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.data)

        product_line.refresh_from_db()
        verified_bom.refresh_from_db()
        self.assertEqual(product_line.quantity, 10)
        self.assertEqual(verified_bom.order_quantity, 10)
        self.assertEqual(verified_bom.status, BomStatus.VERIFIED)
        self.assertEqual(Bom.objects.filter(product_line=product_line).count(), 1)
        self.assertFalse(
            AuditLog.objects.filter(
                object_type="BOM",
                object_id=verified_bom.pk,
                action="SYNC_FROM_PRODUCTION_TASK",
            ).exists()
        )
