import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import CustomerAccount
from apps.inventory.models import (
    FinishedGoodsReceipt,
    FinishedGoodsReceiptSource,
    RecordStatus,
    Warehouse,
    WarehouseLocation,
    WarehouseType,
    WarehouseZone,
)
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit, ReferenceStatus

from ..models import (
    SampleInventoryLine,
    SampleInventoryLoan,
    SampleInventoryOutbound,
    SampleInventoryReceipt,
    SampleItem,
    SampleOutboundMethod,
    SampleProduct,
    SampleRequest,
    SampleRequestStatus,
    SampleWorkflowRecord,
    SampleWorkflowStage,
)


class SampleInventoryReceiptApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="sample_inventory_receipt_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="SAMPLE_INVENTORY_RECEIPT_USER",
            display_name="样品入库测试员工",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="samples",
                codename="add_sampleinventoryreceipt",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="view_sampleinventoryline",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="delete_sampleinventoryreceipt",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="add_sampleinventoryoutbound",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="delete_sampleinventoryoutbound",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="add_sampleinventoryloan",
            ),
            Permission.objects.get(
                content_type__app_label="samples",
                codename="delete_sampleinventoryloan",
            ),
        )
        self.customer = CustomerAccount.objects.create(
            account_code="SAMPLE_INVENTORY_RECEIPT_CUSTOMER",
            account_name="样品入库测试客户",
            primary_country_code="CN",
        )
        self.sample_request = SampleRequest.objects.create(
            customer_account=self.customer,
            owner_employee=self.employee,
            request_number="SYGJ-20260902-031",
            status=SampleRequestStatus.FINISHED,
            requested_at=timezone.now(),
        )
        self.sample_product = SampleProduct.objects.create(
            sample_request=self.sample_request,
            line_number=1,
            category_name_snapshot="户外桌椅",
            product_name="铝框单椅",
            specification="620×680×820",
        )
        self.sample_item = SampleItem.objects.create(
            sample_request=self.sample_request,
            sample_product=self.sample_product,
            line_number=1,
            product_description_snapshot="铝框单椅",
            specification_snapshot="620×680×820",
            requested_quantity="6.0000",
            unit_code="PCS",
            color_name_snapshot="岩灰",
            sample_quantity=6,
            cutting_reported_quantity=6,
            metalwork_reported_quantity=6,
            cutting_completed=True,
            metalwork_completed=True,
        )
        SampleWorkflowRecord.objects.create(
            sample_request=self.sample_request,
            stage=SampleWorkflowStage.PMC_APPROVED,
            operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        SampleWorkflowRecord.objects.create(
            sample_request=self.sample_request,
            stage=SampleWorkflowStage.WORKFLOW_FINISHED,
            operated_by_employee=self.employee,
            operated_at=timezone.now(),
        )
        self.initial_receipt = SampleInventoryReceipt.objects.create(
            receipt_number="RK-20260902-031",
            submitted_by_employee=self.employee,
            submitted_at=timezone.now(),
        )
        self.initial_line = SampleInventoryLine.objects.create(
            receipt=self.initial_receipt,
            sample_item=self.sample_item,
            category_name_snapshot="户外桌椅",
            product_name_snapshot="铝框单椅",
            specification_snapshot="620×680×820",
            color_name_snapshot="岩灰",
            sampling_quantity=6,
            received_quantity=2,
            location="样品库",
        )
        ProductionUnit.objects.get_or_create(
            unit_name="PCS",
            defaults={
                "unit_code": "PCS_SAMPLE",
                "status": ReferenceStatus.ACTIVE,
            },
        )
        self.finished_warehouse = Warehouse.objects.create(
            warehouse_number="CK-SAMPLE-FINISHED",
            warehouse_name="样品成品仓",
            warehouse_type=WarehouseType.FINISHED,
            status=RecordStatus.ACTIVE,
        )
        self.finished_zone = WarehouseZone.objects.create(
            warehouse=self.finished_warehouse,
            zone_name="一楼",
            status=RecordStatus.ACTIVE,
        )
        self.finished_location = WarehouseLocation.objects.create(
            zone=self.finished_zone,
            location_number="A-001",
            status=RecordStatus.ACTIVE,
        )
        self.ineligible_item = SampleItem.objects.create(
            sample_request=self.sample_request,
            sample_product=self.sample_product,
            line_number=2,
            product_description_snapshot="流程未完整的样品",
            requested_quantity="2.0000",
            unit_code="PCS",
            sample_quantity=2,
            cutting_completed=True,
            metalwork_completed=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        line = {
            "sample_item_id": str(self.sample_item.pk),
            "received_quantity": 2,
            "location": "样品库",
            "expected_cumulative_received": 2,
        }
        line.update(overrides)
        return {
            "items": [line],
            "finished_goods_destination": {
                "warehouse_id": str(self.finished_warehouse.pk),
                "zone_id": str(self.finished_zone.pk),
                "location_id": str(self.finished_location.pk),
            },
        }

    def test_finished_goods_options_returns_active_finished_locations(self):
        response = self.client.get("/api/v1/sample-inventory/finished-goods-options/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["warehouses"][0]["warehouse_name"], "样品成品仓")
        self.assertEqual(response.data["data"]["zones"][0]["zone_name"], "一楼")
        self.assertEqual(response.data["data"]["locations"][0]["location_number"], "A-001")

    def test_eligible_returns_only_completed_items_with_remaining_quantity(self):
        response = self.client.get("/api/v1/sample-inventory/eligible/", {"page_size": 100})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["sample_item_id"], str(self.sample_item.pk))
        self.assertEqual(row["sample_request_number"], "SYGJ-20260902-031")
        self.assertEqual(row["flow_condition"], "PMC✓ 金工✓ 裁剪✓")
        self.assertEqual(row["sampling_quantity"], 6)
        self.assertEqual(row["cumulative_received"], 2)
        self.assertEqual(row["remaining_quantity"], 4)

    def test_create_receipt_supports_partial_multiple_inbound(self):
        response = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["data"]["receipt_number"].startswith("RK-"))
        self.assertEqual(response.data["data"]["submitted_by"], "样品入库测试员工")
        self.assertEqual(response.data["data"]["line_count"], 1)
        self.assertEqual(
            SampleInventoryLine.objects.filter(sample_item=self.sample_item).count(),
            2,
        )
        created_line = SampleInventoryLine.objects.exclude(receipt=self.initial_receipt).get()
        self.assertEqual(created_line.received_quantity, 2)
        self.assertEqual(created_line.location, "样品库")
        finished_receipt = FinishedGoodsReceipt.objects.get(
            source_sample_inventory_line=created_line
        )
        self.assertEqual(finished_receipt.source_type, FinishedGoodsReceiptSource.SAMPLE_INVENTORY)
        self.assertEqual(finished_receipt.source_document_number, "SYGJ-20260902-031")
        self.assertEqual(finished_receipt.product_name_snapshot, "铝框单椅")
        self.assertEqual(finished_receipt.remaining_quantity, 2)
        self.assertEqual(finished_receipt.location, self.finished_location)

        eligible = self.client.get("/api/v1/sample-inventory/eligible/", {"page_size": 100})
        self.assertEqual(eligible.data["data"][0]["cumulative_received"], 4)
        self.assertEqual(eligible.data["data"][0]["remaining_quantity"], 2)
        created_receipt = SampleInventoryReceipt.objects.exclude(pk=self.initial_receipt.pk).get()
        detail = self.client.get(f"/api/v1/sample-inventory/receipts/{created_receipt.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["lines"][0]["cumulative_received"], 4)
        self.assertEqual(
            detail.data["data"]["lines"][0]["finished_goods_receipt_number"],
            finished_receipt.receipt_number,
        )
        self.assertEqual(detail.data["data"]["lines"][0]["finished_goods_warehouse"], "样品成品仓")
        self.assertEqual(detail.data["data"]["lines"][0]["finished_goods_zone"], "一楼")
        self.assertEqual(detail.data["data"]["lines"][0]["finished_goods_location"], "A-001")

    def test_create_receipt_rejects_quantity_over_remaining(self):
        response = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(received_quantity=5),
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(SampleInventoryReceipt.objects.count(), 1)

    def test_create_receipt_rejects_stale_cumulative_quantity(self):
        response = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(expected_cumulative_received=0),
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("已变化", response.data["error"]["message"])

    def test_create_receipt_rejects_blank_location_and_duplicate_items(self):
        blank_location = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(location=" "),
            format="json",
        )
        duplicate_payload = self.payload()
        duplicate_payload["items"] = duplicate_payload["items"] * 2
        duplicate = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            duplicate_payload,
            format="json",
        )

        self.assertEqual(blank_location.status_code, 400, blank_location.data)
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

    def test_create_receipt_rejects_mismatched_finished_goods_location(self):
        other_zone = WarehouseZone.objects.create(
            warehouse=self.finished_warehouse,
            zone_name="四楼",
            status=RecordStatus.ACTIVE,
        )
        payload = self.payload()
        payload["finished_goods_destination"]["zone_id"] = str(other_zone.pk)

        response = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(FinishedGoodsReceipt.objects.count(), 0)

    def test_sample_outbound_synchronizes_linked_finished_goods_quantity(self):
        created = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        inventory_line = SampleInventoryLine.objects.exclude(receipt=self.initial_receipt).get()
        finished_receipt = FinishedGoodsReceipt.objects.get(
            source_sample_inventory_line=inventory_line
        )

        outbound = self.client.post(
            "/api/v1/sample-outbound/documents/",
            {
                "items": [{
                    "inventory_line_id": str(inventory_line.pk),
                    "outbound_quantity": 1,
                    "outbound_method": SampleOutboundMethod.MERCHANDISER_MAIL,
                    "courier_company": "顺丰速运",
                    "tracking_number": "SF-SAMPLE-001",
                    "remark": "",
                    "expected_available_quantity": 2,
                }],
            },
            format="json",
        )

        self.assertEqual(outbound.status_code, 201, outbound.data)
        finished_receipt.refresh_from_db()
        self.assertEqual(finished_receipt.remaining_quantity, 1)
        outbound_document = SampleInventoryOutbound.objects.get(
            lines__inventory_line=inventory_line
        )
        deleted = self.client.delete(
            f"/api/v1/sample-outbound/documents/{outbound_document.pk}/"
        )
        self.assertEqual(deleted.status_code, 204)
        finished_receipt.refresh_from_db()
        self.assertEqual(finished_receipt.remaining_quantity, 2)

    def test_sample_loan_synchronizes_linked_finished_goods_quantity(self):
        created = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(),
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        inventory_line = SampleInventoryLine.objects.exclude(receipt=self.initial_receipt).get()
        finished_receipt = FinishedGoodsReceipt.objects.get(
            source_sample_inventory_line=inventory_line
        )

        loan = self.client.post(
            "/api/v1/sample-loans/documents/",
            {
                "items": [{
                    "inventory_line_id": str(inventory_line.pk),
                    "loan_quantity": 1,
                    "borrower_name": "样品测试借用人",
                    "purpose_note": "验证成品库存同步",
                    "expected_available_quantity": 2,
                }],
            },
            format="json",
        )

        self.assertEqual(loan.status_code, 201, loan.data)
        finished_receipt.refresh_from_db()
        self.assertEqual(finished_receipt.remaining_quantity, 1)
        loan_document = SampleInventoryLoan.objects.get(lines__inventory_line=inventory_line)
        deleted = self.client.delete(
            f"/api/v1/sample-loans/documents/{loan_document.pk}/"
        )
        self.assertEqual(deleted.status_code, 204)
        finished_receipt.refresh_from_db()
        self.assertEqual(finished_receipt.remaining_quantity, 2)

    def test_receipt_detail_returns_header_lines_and_source_workflow(self):
        response = self.client.get(
            f"/api/v1/sample-inventory/receipts/{self.initial_receipt.pk}/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        detail = response.data["data"]
        self.assertEqual(detail["receipt_id"], str(self.initial_receipt.pk))
        self.assertEqual(detail["receipt_number"], "RK-20260902-031")
        self.assertEqual(detail["document_type"], "样品入库")
        self.assertEqual(detail["submitted_by"], "样品入库测试员工")
        self.assertEqual(detail["operation_source"], "样品库")
        self.assertEqual(detail["status"], "COMPLETED")
        self.assertEqual(detail["line_count"], 1)
        line = detail["lines"][0]
        self.assertEqual(line["id"], str(self.initial_line.pk))
        self.assertEqual(line["sample_request_number"], "SYGJ-20260902-031")
        self.assertEqual(line["sampling_quantity"], 6)
        self.assertEqual(line["received_quantity"], 2)
        self.assertEqual(line["cumulative_received"], 2)
        self.assertEqual(line["flow_condition"], "PMC✓ 金工✓ 裁剪✓")
        self.assertEqual(line["source_status"], "流程已结束")

    def test_receipt_detail_returns_not_found_for_unknown_receipt(self):
        response = self.client.get(f"/api/v1/sample-inventory/receipts/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, 404, response.data)

    def test_delete_unused_receipt_removes_lines_and_restores_inbound_capacity(self):
        response = self.client.delete(
            f"/api/v1/sample-inventory/receipts/{self.initial_receipt.pk}/"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            SampleInventoryReceipt.objects.filter(pk=self.initial_receipt.pk).exists()
        )
        self.assertFalse(SampleInventoryLine.objects.filter(pk=self.initial_line.pk).exists())
        eligible = self.client.get("/api/v1/sample-inventory/eligible/", {"page_size": 100})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(eligible.data["data"][0]["cumulative_received"], 0)
        self.assertEqual(eligible.data["data"][0]["remaining_quantity"], 6)

    def test_delete_receipt_rejects_inventory_with_outbound_or_loan_usage(self):
        self.initial_line.outbound_quantity = 1
        self.initial_line.save(update_fields=["outbound_quantity", "updated_at"])

        response = self.client.delete(
            f"/api/v1/sample-inventory/receipts/{self.initial_receipt.pk}/"
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("不能删除", response.data["error"]["message"])
        self.assertTrue(
            SampleInventoryReceipt.objects.filter(pk=self.initial_receipt.pk).exists()
        )

    def test_add_receipt_permission_is_required(self):
        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="sample_inventory_receipt_no_permission")
        Employee.objects.create(
            user=other_user,
            employee_code="SAMPLE_INVENTORY_RECEIPT_NO_PERMISSION",
            display_name="无入库权限员工",
        )
        self.client.force_authenticate(other_user)

        eligible = self.client.get("/api/v1/sample-inventory/eligible/")
        created = self.client.post(
            "/api/v1/sample-inventory/receipts/",
            self.payload(),
            format="json",
        )
        detail = self.client.get(
            f"/api/v1/sample-inventory/receipts/{self.initial_receipt.pk}/"
        )
        deleted = self.client.delete(
            f"/api/v1/sample-inventory/receipts/{self.initial_receipt.pk}/"
        )

        self.assertEqual(eligible.status_code, 403, eligible.data)
        options = self.client.get("/api/v1/sample-inventory/finished-goods-options/")
        self.assertEqual(created.status_code, 403, created.data)
        self.assertEqual(detail.status_code, 403, detail.data)
        self.assertEqual(deleted.status_code, 403, deleted.data)
        self.assertEqual(options.status_code, 403, options.data)
