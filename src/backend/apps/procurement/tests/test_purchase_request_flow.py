from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomStatus
from apps.customers.models import CustomerAccount, CustomerEntityAddress, CustomerTransactionEntity
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.procurement.models import (
    PurchaseAllocationStatus,
    PurchaseContractTemplate,
    PurchaseRequest,
    Supplier,
    SupplierPurchaseSheet,
)
from apps.products.models import ProductInformation


class PurchaseRequestFlowApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(username="purchase_request_admin", password="test")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="PURCHASE_REQUEST_ADMIN",
            display_name="采购申请测试员工",
        )
        self.customer = CustomerAccount.objects.create(
            account_code="PURCHASE_REQUEST_CUSTOMER",
            account_name="采购申请测试客户",
            primary_country_code="CN",
        )
        self.entity = CustomerTransactionEntity.objects.create(
            customer_account=self.customer,
            entity_code="PURCHASE_REQUEST_BUYER",
            legal_name="采购申请测试买方",
        )
        self.buyer_address = CustomerEntityAddress.objects.create(
            transaction_entity=self.entity,
            address_code="PURCHASE_REQUEST_ADDRESS",
            label="采购申请测试地址",
            country_code="CN",
            city="金华市",
            address_line1="采购申请测试路 1 号",
            is_verified=True,
        )
        self.product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).select_related(
            "unit", "category"
        ).first()
        self.assertIsNotNone(self.product, "基础迁移必须至少提供一个有效产品供订单链路测试。")
        self.evidence = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="customer-confirmation.pdf",
            storage_key="tests/customer-confirmation.pdf",
            content_type="application/pdf",
            size_bytes=10,
            scan_status=FileScanStatus.SKIPPED,
        )
        self.supplier = Supplier.objects.create(
            supplier_number="GYS99998",
            supplier_type="MATERIAL",
            supplier_categories=["FABRIC"],
            supplier_name="采购申请测试供应商",
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _confirmed_order(self):
        today = timezone.localdate().isoformat()
        payload = {
            "source_type": "DIRECT",
            "source_quotation_version_id": None,
            "customer_account_id": str(self.customer.pk),
            "transaction_entity_id": str(self.entity.pk),
            "buyer_address_id": str(self.buyer_address.pk),
            "salesperson_id": str(self.employee.pk),
            "merchandiser_id": str(self.employee.pk),
            "customer_po_number": "PO-PR-FLOW-001",
            "contract_number": "CONTRACT-PR-FLOW-001",
            "order_date": today,
            "direct_order_reason": "客户直接书面下单",
            "currency_code": "CNY",
            "exchange_rate": "1.000000",
            "seller_snapshot": {"template_config": {"seller_company_name": "HAIQU TEST SELLER CO., LTD."}},
            "confirmation_method": "CUSTOMER_PO",
            "customer_confirmer": "Buyer",
            "customer_confirmed_at": timezone.now().isoformat(),
            "confirmation_summary": "客户确认产品、数量、价格和交期",
            "evidence_file_ids": [str(self.evidence.pk)],
            "lines": [{
                "client_key": "line-1",
                "source_quotation_line_id": None,
                "product_id": str(self.product.pk),
                "quantity": "10.0000",
                "unit_price": "20.0000",
            }],
            "delivery_batches": [{
                "planned_delivery_date": today,
                "notes": "首批",
                "lines": [{"sales_order_line_client_key": "line-1", "quantity": "10.0000"}],
            }],
        }
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return confirmed

    def _ready_production_order(self, confirmed_order):
        today = timezone.localdate().isoformat()
        batch_line_id = confirmed_order.data["data"]["delivery_batches"][0]["lines"][0]["id"]
        created = self.client.post(
            "/api/v1/production-tasks/create-from-sales-order/",
            {
                "task_number": "HT26199-1",
                "follower_ids": [str(self.employee.pk)],
                "delivery_date": today,
                "includes_tax": False,
                "order_tolerance_percent": "0",
                "is_repeat_order": False,
                "delivery_method": "SINGLE",
                "delivery_batch_line_id": batch_line_id,
                "quantity": 10,
                "planned_start_date": today,
                "planned_end_date": today,
                "production_priority": "NORMAL",
                "production_batch_number": "PB-PR-FLOW-001",
                "planner_id": str(self.employee.pk),
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        submitted = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(
            f"/api/v1/production-tasks/{created.data['data']['id']}/pmc-decision/",
            {
                "decision": "CONFIRM",
                "follower_ids": [str(self.employee.pk)],
                "tax_rate": None,
                "planned_start_date": today,
                "planned_end_date": today,
                "production_priority": "NORMAL",
                "production_batch_number": "PB-PR-FLOW-001",
                "planner_id": str(self.employee.pk),
            },
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], "READY")
        return confirmed

    def test_confirmed_bom_to_purchase_request_and_one_supplier_order(self):
        production = self._ready_production_order(self._confirmed_order())
        product_line_id = production.data["data"]["products"][0]["id"]
        task_id = production.data["data"]["id"]
        product_line = self.product.production_task_lines.get(pk=product_line_id)
        bom = Bom.objects.create(
            bom_number="BOM-PR-FLOW-001-V1",
            production_task_id=task_id,
            product_line=product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED,
            product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code,
            product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification,
            product_category_snapshot=self.product.category.category_name,
            order_quantity=Decimal("10"),
            confirmed_by_employee=self.employee,
            confirmed_at=timezone.now(),
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        section = BomSection.objects.create(
            bom=bom,
            line_number=1,
            section_type="FABRIC",
            title="面料类",
        )
        BomLine.objects.create(
            section=section,
            line_number=1,
            part_name="测试面料",
            specification="600D",
            unit="米",
            total_purchase_quantity="12",
        )

        created = self.client.post("/api/v1/purchase-requests/", {"bom_id": str(bom.pk)}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Decimal(created.data["data"]["lines"][0]["gross_requirement_quantity"]), Decimal("12"))
        request_id = created.data["data"]["id"]
        line_id = created.data["data"]["lines"][0]["id"]
        updated = self.client.patch(
            f"/api/v1/purchase-requests/{request_id}/",
            {"lines": [{
                "id": line_id,
                "actual_request_quantity": "10.0000",
                "difference_reason": "库存可用 2 米，本期只申请 10 米",
                "required_date": timezone.localdate().isoformat(),
                "suggested_supplier_id": str(self.supplier.pk),
            }]},
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        submitted = self.client.post(
            f"/api/v1/purchase-requests/{request_id}/submit/",
            {},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        allocated = self.client.post(
            f"/api/v1/purchase-requests/{request_id}/allocate/",
            {
                "purchase_request_line_id": line_id,
                "supplier_id": str(self.supplier.pk),
                "procurement_batch_number": "PC-PR-FLOW-001",
                "quantity": "10.0000",
                "expected_arrival_date": timezone.localdate().isoformat(),
            },
            format="json",
            HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(allocated.status_code, 201, allocated.data)

        template = PurchaseContractTemplate.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.assertIsNotNone(template)
        template_version = template.versions.get(version_number=template.current_version_number)
        generated = self.client.post(
            f"/api/v1/purchase-requests/{request_id}/generate-supplier-order/",
            {
                "supplier_id": str(self.supplier.pk),
                "procurement_batch_number": "PC-PR-FLOW-001",
                "template_version_id": str(template_version.pk),
            },
            format="json",
            HTTP_IF_MATCH=allocated["ETag"],
        )
        self.assertEqual(generated.status_code, 201, generated.data)

        purchase_request = PurchaseRequest.objects.get(pk=request_id)
        sheet = SupplierPurchaseSheet.objects.get(pk=generated.data["data"]["id"])
        allocation = purchase_request.lines.get(pk=line_id).allocations.get()
        self.assertEqual(sheet.purchase_request_id, purchase_request.pk)
        self.assertIsNone(sheet.purchase_order_id)
        self.assertEqual(sheet.supplier_id, self.supplier.pk)
        self.assertEqual(sheet.procurement_batch_number, "PC-PR-FLOW-001")
        self.assertEqual(allocation.status, PurchaseAllocationStatus.ORDERED)
        self.assertEqual(allocation.supplier_purchase_sheet_id, sheet.pk)
