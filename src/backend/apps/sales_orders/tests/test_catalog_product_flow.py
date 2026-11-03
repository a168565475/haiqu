from copy import deepcopy
from decimal import Decimal

from django.utils import timezone
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.inquiries.models import Inquiry, InquiryItem
from apps.inquiries.services import prepare_inquiry_item_data
from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from apps.product_catalog.editing import _check_product_delete
from apps.quotations.models import Quotation, QuotationLine, QuotationVersion
from apps.quotations.services import _apply_line_product_snapshots, _copy_version_content, quotation_line_values_from_inquiry_item
from apps.quotations.product_writeback import save_bom_product_information
from apps.reference_data.models import ProductionUnit
from apps.sales_orders.models import SalesOrder, SalesOrderLine
from apps.sales_orders.services import _line_identity
from apps.sales_orders.tests import test_sales_order_api


class CatalogCommercialFlowTests(APITestCase):
    def setUp(self):
        test_sales_order_api.SalesOrderApiTests.setUp(self)
        self.unit, _ = ProductionUnit.objects.get_or_create(
            unit_code="CATALOG-FLOW", defaults={"unit_name": "目录测试套"},
        )
        category = ProductCatalogCategory.objects.create(name="目录订单测试")
        self.name = ProductCatalogName.objects.create(category=category, name="目录折叠椅")
        self.catalog = ProductCatalog.objects.create(
            name=self.name, product_code="C-01", item_number="ITEM-01", specification="60×80",
            unit=self.unit.unit_name, materials=["铝", "铁"], thicknesses=["0.8", "1.0"],
        )
        self.color = ProductCatalogColor.objects.create(product=self.catalog, value="蓝色")

    def selection(self, **overrides):
        return {
            "catalog_version": self.catalog.updated_at.isoformat(), "color_id": str(self.color.pk),
            "material": "铝", "thickness": "0.8", **overrides,
        }

    def order_payload(self):
        payload = test_sales_order_api.SalesOrderApiTests.direct_payload(self)
        payload["lines"][0].update(
            product_id=None, product_catalog_id=str(self.catalog.pk), product_selection=self.selection(),
        )
        return payload

    def inquiry_item(self):
        inquiry = Inquiry.objects.create(
            inquiry_number="CATALOG-INQ", subject="目录询价", received_at=timezone.now(),
            customer_account=self.customer, owner_employee=self.employee,
        )
        values = prepare_inquiry_item_data({
            "product_catalog_id": self.catalog.pk, "product_selection": self.selection(),
            "quantity": Decimal("10"), "target_unit_price": Decimal("20"), "target_currency_code": "CNY",
        })
        return InquiryItem.objects.create(inquiry=inquiry, line_number=1, **values)

    def quote_line(self):
        item = self.inquiry_item()
        quotation = Quotation.objects.create(
            quotation_number="CATALOG-QUOTE", customer_account=self.customer,
            transaction_entity=self.entity, owner_employee=self.employee, subject="目录报价",
        )
        version = QuotationVersion.objects.create(quotation=quotation, version_number=1, currency_code="CNY")
        return QuotationLine.objects.create(
            quotation_version=version, line_number=1, **quotation_line_values_from_inquiry_item(item),
        )

    def test_inquiry_api_uses_server_validated_selection_and_preserves_snapshot(self):
        response = self.client.post("/api/v1/inquiries/", {
            "customer_account_id": str(self.customer.pk), "subject": "新目录询盘", "inquiry_source": "EMAIL",
            "received_at": timezone.now().isoformat(),
            "items": [{"product_catalog_id": str(self.catalog.pk), "product_selection": self.selection(),
                       "product_description": "客户端旧名称", "specification": "客户端旧规格", "unit_code": self.unit.unit_code,
                       "quantity": "10"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        item = InquiryItem.objects.get(inquiry_id=response.data["data"]["id"])
        self.assertEqual(item.product_description, self.name.name)
        self.assertEqual(item.specification, self.catalog.specification)
        self.assertIsNone(item.product_id)
        original = deepcopy(item.product_selection_snapshot)
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(specification="新规格")
        data = prepare_inquiry_item_data({"quantity": Decimal("12")}, existing=item)
        self.assertEqual(data["product_selection_snapshot"], original)
        self.assertEqual(data["specification"], "60×80")

    def test_inquiry_to_quote_and_new_quote_version_keep_selection(self):
        line = self.quote_line()
        original = deepcopy(line.product_selection_snapshot)
        ProductCatalogName.objects.filter(pk=self.name.pk).update(name="后来改名")
        self.assertEqual(line.product_description_snapshot, "目录折叠椅")
        self.assertEqual(line.specification_snapshot, "60×80")
        values = _apply_line_product_snapshots({"quantity": Decimal("12")}, current=line)
        self.assertEqual(values["product_selection_snapshot"], original)
        target = QuotationVersion.objects.create(quotation=line.quotation_version.quotation, version_number=2, currency_code="CNY")
        _copy_version_content(line.quotation_version, target)
        copied = target.lines.get()
        self.assertEqual(copied.product_catalog_id, self.catalog.pk)
        self.assertEqual(copied.product_selection_snapshot, original)

    def test_sales_order_create_freezes_selected_options_without_legacy_product(self):
        response = self.client.post("/api/v1/sales-orders/", self.order_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        line = SalesOrderLine.objects.get(sales_order_id=response.data["data"]["id"])
        self.assertEqual(line.product_catalog_id, self.catalog.pk)
        self.assertIsNone(line.product_id)
        self.assertIsNone(line.product_category_id)
        self.assertIsNone(line.product_color_id)
        self.assertEqual(line.product_unit_id, self.unit.pk)
        self.assertEqual(line.product_selection_snapshot["thickness"], "0.8")
        self.assertEqual(line.material_snapshot, "铝")
        self.assertEqual(line.customer_color_snapshot, "蓝色")
        self.assertEqual(line.line_total, Decimal("200"))

    def test_sales_draft_quantity_change_keeps_catalog_snapshot_after_master_change(self):
        payload = self.order_payload()
        created = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        line = SalesOrderLine.objects.get(sales_order_id=created.data["data"]["id"])
        original = deepcopy(line.product_selection_snapshot)
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(specification="后改规格", materials=["木"])
        payload["lines"][0].pop("product_selection")
        payload["lines"][0].update(client_key=str(line.pk), quantity="12")
        payload["delivery_batches"][0]["lines"][0].update(sales_order_line_client_key=str(line.pk), quantity="12")
        updated = self.client.patch(f"/api/v1/sales-orders/{line.sales_order_id}/", payload,
                                    format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(updated.status_code, 200, updated.data)
        saved = SalesOrderLine.objects.get(sales_order_id=line.sales_order_id)
        self.assertEqual(saved.product_selection_snapshot, original)
        self.assertEqual(saved.specification_snapshot, "60×80")
        self.assertEqual(saved.quantity, Decimal("12"))

    def test_foreign_attribute_rolls_back_whole_sales_order(self):
        payload = self.order_payload()
        payload["lines"][0]["product_selection"]["material"] = "不属于产品的材质"
        before = SalesOrder.objects.count()
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("product_selection", response.data["error"]["field_errors"])
        self.assertEqual(SalesOrder.objects.count(), before)
        self.assertFalse(SalesOrderLine.objects.filter(product_catalog=self.catalog).exists())

    def test_quote_to_order_copies_saved_selection_even_after_master_archive(self):
        line = self.quote_line()
        original = deepcopy(line.product_selection_snapshot)
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(archived_at=timezone.now(), specification="变化")
        identity = _line_identity({}, None, line)
        self.assertEqual(identity["product_catalog"].pk, self.catalog.pk)
        self.assertEqual(identity["product_selection_snapshot"], original)
        self.assertEqual(identity["specification_snapshot"], "60×80")

    def test_used_catalog_product_cannot_be_deleted(self):
        self.inquiry_item()
        with self.assertRaisesMessage(ValidationError, "引用"):
            _check_product_delete(self.catalog)
        self.assertTrue(ProductCatalog.objects.filter(pk=self.catalog.pk).exists())

    def test_locked_quote_allows_catalog_writeback_but_still_blocks_price_changes(self):
        line = self.quote_line()
        QuotationVersion.objects.filter(pk=line.quotation_version_id).update(status="LOCKED", locked_at=timezone.now())
        line.product_selection_snapshot = {**line.product_selection_snapshot, "thickness": "1.0"}
        save_bom_product_information(line)
        line.refresh_from_db()
        self.assertEqual(line.product_selection_snapshot["thickness"], "1.0")
        with self.assertRaises(IntegrityError), transaction.atomic():
            line.unit_price = Decimal("1")
            line.save(update_fields=["unit_price"])
        line.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal("20"))
