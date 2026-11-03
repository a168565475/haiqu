from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inquiries.models import InquiryItem
from apps.inquiries.services import prepare_inquiry_item_data
from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from apps.product_catalog.tests.test_product_entry_drafts import typed_product_draft
from apps.production_tasks.models import ProductionTask
from apps.quotations.models import Quotation, QuotationLine, QuotationVersion
from apps.quotations.services import _apply_line_product_snapshots, _copy_version_content, quotation_line_values_from_inquiry_item
from apps.reference_data.models import ProductionUnit
from apps.sales_orders.models import SalesOrderLine
from apps.sales_orders.services import _line_identity

from . import test_catalog_product_flow as fixtures
from . import test_sales_order_api as sales_fixtures


class ProductEntryCommercialTests(APITestCase):
    setUp = fixtures.CatalogCommercialFlowTests.setUp

    def counts(self):
        return tuple(model.objects.count() for model in (
            ProductCatalogCategory, ProductCatalogName, ProductCatalog, ProductCatalogColor, ProductionUnit,
        ))

    def create_inquiry(self):
        response = self.client.post("/api/v1/inquiries/", {
            "customer_account_id": str(self.customer.pk), "subject": "逐项草稿询盘", "inquiry_source": "EMAIL",
            "received_at": timezone.now().isoformat(),
            "items": [{"product_catalog_id": None, "product_selection": {"draft": typed_product_draft()},
                       "product_description": "临时名称", "specification": "临时规格", "unit_code": "",
                       "quantity": "10", "target_unit_price": "20", "target_currency_code": "CNY"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return InquiryItem.objects.get(inquiry_id=response.data["data"]["id"])

    def test_inquiry_quote_revision_and_sales_conversion_keep_draft_without_master_write(self):
        before = self.counts()
        item = self.create_inquiry()
        snapshot = deepcopy(item.product_selection_snapshot)
        self.assertIsNone(item.product_catalog_id)
        self.assertEqual(item.product_code_snapshot, "DRAFT-CODE")
        self.assertEqual(item.unit_code, "")
        edited = prepare_inquiry_item_data({"quantity": Decimal("12")}, existing=item)
        self.assertEqual(edited["product_selection_snapshot"], snapshot)
        quotation = Quotation.objects.create(quotation_number="DRAFT-QUOTE", customer_account=self.customer,
                                            transaction_entity=self.entity, owner_employee=self.employee, subject="草稿报价")
        version = QuotationVersion.objects.create(quotation=quotation, version_number=1, currency_code="CNY")
        line = QuotationLine.objects.create(quotation_version=version, line_number=1, **quotation_line_values_from_inquiry_item(item))
        self.assertEqual(line.specification_snapshot, "60*80")
        self.assertEqual(_apply_line_product_snapshots({"quantity": Decimal("12")}, current=line)["product_selection_snapshot"], snapshot)
        next_version = QuotationVersion.objects.create(quotation=quotation, version_number=2, currency_code="CNY")
        _copy_version_content(version, next_version)
        copied = next_version.lines.get()
        self.assertEqual(copied.product_selection_snapshot, snapshot)
        identity = _line_identity({}, None, copied)
        self.assertEqual(identity["product_selection_snapshot"], snapshot)
        self.assertEqual(identity["item_number_snapshot"], "DRAFT-01")
        self.assertIsNone(identity["product_unit"])
        self.assertEqual(self.counts(), before)

    def test_sales_draft_edit_and_production_transfer_allow_typed_unit(self):
        before = self.counts()
        payload = sales_fixtures.SalesOrderApiTests.direct_payload(self)
        payload["lines"][0].update(product_id=None, product_catalog_id=None,
                                   product_selection={"draft": typed_product_draft()}, unit_code="")
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        line = SalesOrderLine.objects.get(sales_order_id=created.data["data"]["id"])
        snapshot = deepcopy(line.product_selection_snapshot)
        payload["lines"][0].pop("product_selection")
        payload["lines"][0].update(client_key=str(line.pk), customer_product_name_snapshot="草稿折叠椅", customer_specification_snapshot="60*80")
        payload["delivery_batches"][0]["lines"][0]["sales_order_line_client_key"] = str(line.pk)
        # 数量等商业字段重存，不应丢弃尚未建档的产品身份。
        updated = self.client.patch(f"/api/v1/sales-orders/{line.sales_order_id}/", payload,
                                    format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(updated.status_code, 200, updated.data)
        # 草稿订单保存会重建明细，client_key 只用于继承原快照和重建批次关联。
        line = SalesOrderLine.objects.get(sales_order_id=line.sales_order_id)
        self.assertEqual(line.product_selection_snapshot, snapshot)
        confirmed = self.client.post(f"/api/v1/sales-orders/{line.sales_order_id}/confirm/", {},
                                     format="json", HTTP_IF_MATCH=updated["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        response = self.client.post("/api/v1/production-tasks/create-from-sales-order/", {
            **sales_fixtures.SalesOrderApiTests.production_fields(self),
            "task_number": "HT26992", "request_key": str(uuid4()),
            "delivery_batch_line_id": confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"],
            "quantity": 10, "planned_start_date": timezone.localdate().isoformat(),
            "planned_end_date": timezone.localdate().isoformat(), "production_priority": "NORMAL",
            "planner_id": str(self.planner.pk),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        product = ProductionTask.objects.get(pk=response.data["data"]["id"]).products.get()
        self.assertIsNone(product.unit_id)
        self.assertIsNone(product.product_catalog_id)
        self.assertEqual(product.product_selection_snapshot, snapshot)
        self.assertEqual(product.unit_name, "未建档单位")
        self.assertEqual(product.unit_code, "")
        self.assertIsNone(response.data["data"]["products"][0]["unit_id"])
        self.assertEqual(self.counts(), before)
