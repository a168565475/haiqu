from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from apps.audit.models import AuditLog
from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.customers.models import CustomerAccount, CustomerTransactionEntity
from apps.files.models import BusinessFile, FileScanStatus
from apps.inquiries.models import Inquiry, InquiryItem
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.quotations.models import (
    Quotation,
    QuotationAcceptance,
    QuotationLine,
    QuotationPriceBasis,
    QuotationVersion,
)
from apps.reference_data.models import (
    Currency,
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductionUnit,
)
from apps.sales_orders.models import (
    SalesOrder,
    SalesOrderDeliveryBatch,
    SalesOrderDeliveryBatchLine,
    SalesOrderLine,
)

from .. import services as bom_services
from ..models import Bom, BomLine, BomSection
from ..services import create_bom, verify_bom


class BomProductWritebackTests(APITestCase):
    """使用真实外键链和数据库触发器，验证产品确认的写入范围及事务。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="bom_writeback_admin", password="test")
        cls.employee = Employee.objects.create(
            user=cls.user, employee_code="BOM_WRITEBACK", display_name="BOM 回写测试员工",
        )
        cls.customer = CustomerAccount.objects.create(
            account_code="BOM_WRITEBACK", account_name="BOM 回写测试客户", primary_country_code="CN",
        )
        cls.entity = CustomerTransactionEntity.objects.create(
            customer_account=cls.customer, entity_code="BOM_WRITEBACK_BUYER", legal_name="回写测试买方",
        )
        cls.currency = Currency.objects.get(code="CNY")
        cls.category = ProductCategory.objects.create(item_type="FINISHED", category_name="回写测试成品")
        cls.old_unit = ProductionUnit.objects.create(unit_code="WBPCS", unit_name="回写测试件")
        cls.new_unit = ProductionUnit.objects.create(unit_code="WBSET", unit_name="回写测试套")
        cls.old_color = ProductColor.objects.create(color_card="WB", color_code="BLACK", color_name="回写测试黑色")
        cls.new_color = ProductColor.objects.create(color_card="WB", color_code="MATTE", color_name="回写测试亚黑")
        cls.old_product = cls.make_product("OLD", "原产品", "原规格", cls.old_unit)
        cls.new_product = cls.make_product("NEW", "确认产品", "确认规格", cls.new_unit)
        material_category = ProductCategory.objects.create(item_type="MATERIAL", category_name="回写测试五金")
        cls.accessory = RawMaterialInformation.objects.create(
            material_number="WB-ACCESSORY", item_type="MATERIAL", category=material_category,
            material_name="回写测试铆钉", specification="Φ4×20", unit=cls.old_unit,
            material="钢", warehouse_number="WB", warehouse_name="回写测试仓",
        )
        cls.image = BusinessFile.objects.create(
            uploaded_by_employee=cls.employee, original_name="customer-product.png",
            storage_key="tests/bom-writeback/customer-product.png", content_type="image/png",
            size_bytes=10, scan_status=FileScanStatus.SKIPPED,
        )
        cls.inquiry = Inquiry.objects.create(
            customer_account=cls.customer, transaction_entity=cls.entity, owner_employee=cls.employee,
            inquiry_number="INQ-WRITEBACK", subject="产品回写测试", received_at=timezone.now(),
        )
        cls.inquiry_item = InquiryItem.objects.create(
            inquiry=cls.inquiry, line_number=1, product=cls.old_product,
            product_category=cls.category, product_unit=cls.old_unit, product_color=cls.old_color,
            product_description="原产品", specification="原规格", color=cls.old_color.color_name,
            material="客户原材质", unit_code=cls.old_unit.unit_code, quantity=Decimal("24"),
            target_unit_price=Decimal("8.1234"), target_currency_code="USD",
            expected_date=timezone.localdate() + timedelta(days=45), product_image=cls.image,
        )
        # 同一产品的另一明细不在当前业务链中，不能因产品 ID 相同而被更新。
        cls.unrelated_item = InquiryItem.objects.create(
            inquiry=cls.inquiry, line_number=2, product=cls.old_product,
            product_description="另一需求", specification="另一规格", quantity=Decimal("3"),
            unit_code=cls.old_unit.unit_code,
        )
        cls.quotation = Quotation.objects.create(
            customer_account=cls.customer, transaction_entity=cls.entity, owner_employee=cls.employee,
            source_inquiry=cls.inquiry, quotation_number="QUO-WRITEBACK", subject="已接受报价回写",
        )
        cls.version = QuotationVersion.objects.create(
            quotation=cls.quotation, version_number=1, status="DRAFT", currency_code="CNY",
            transaction_entity_snapshot={"legal_name": cls.entity.legal_name},
            address_snapshot={"country_code": "CN", "address_line1": "测试地址"},
            contact_snapshot={"name": "测试联系人"},
        )
        cls.quote_line = QuotationLine.objects.create(
            quotation_version=cls.version, line_number=1, source_inquiry_item=cls.inquiry_item,
            product=cls.old_product, product_category=cls.category, product_unit=cls.old_unit,
            product_color=cls.old_color, product_description_snapshot="原产品",
            specification_snapshot="原规格", color_snapshot=cls.old_color.color_name,
            material_snapshot="报价原材质", unit_code=cls.old_unit.unit_code,
            quantity=Decimal("20"), unit_price=Decimal("12.3456"), line_total=Decimal("246.9120"),
            product_image=cls.image,
        )
        cls.unrelated_quote_line = QuotationLine.objects.create(
            quotation_version=cls.version, line_number=2, product=cls.old_product,
            product_description_snapshot="其他报价产品", quantity=Decimal("3"),
            unit_code=cls.old_unit.unit_code, unit_price=Decimal("2"), line_total=Decimal("6"),
        )
        cls.version.status = "SENT"
        cls.version.locked_at = timezone.now()
        cls.version.save(update_fields=["status", "locked_at", "updated_at"])
        basis = QuotationPriceBasis.objects.create(
            quotation_version=cls.version, label="回写测试 EXW", incoterm_code="EXW",
            named_place="金华", currency_code="CNY", is_default=True,
        )
        QuotationAcceptance.objects.create(
            quotation=cls.quotation, quotation_version=cls.version, price_basis=basis,
            accepted_at=timezone.now(), source="EMAIL", recorded_by_employee=cls.employee,
        )
        cls.quotation.outcome_status = "WON"
        cls.quotation.accepted_version = cls.version
        cls.quotation.save(update_fields=["outcome_status", "accepted_version", "updated_at"])
        cls.order = SalesOrder.objects.create(
            order_number="SO-WRITEBACK", source_type="QUOTATION", source_quotation_version=cls.version,
            customer_account=cls.customer, transaction_entity=cls.entity, salesperson=cls.employee,
            order_date=timezone.localdate(), currency_code="CNY", exchange_rate=Decimal("1"),
            status="CONFIRMED", total_amount=Decimal("246.9120"),
        )
        cls.sales_line = SalesOrderLine.objects.create(
            sales_order=cls.order, line_number=1, source_quotation_line=cls.quote_line,
            product=cls.old_product, product_category=cls.category, product_unit=cls.old_unit,
            product_color=cls.old_color, product_number_snapshot=cls.old_product.product_number,
            product_code_snapshot=cls.old_product.product_code,
            item_number_snapshot=cls.old_product.product_item.item_number,
            product_name_snapshot="原产品", specification_snapshot="原规格",
            customer_product_name_snapshot="原产品", customer_specification_snapshot="原规格",
            customer_color_snapshot=cls.old_color.color_name, material_snapshot="销售原材质",
            unit_code_snapshot=cls.old_unit.unit_code, quantity=Decimal("20"),
            unit_price=Decimal("12.3456"), line_total=Decimal("246.9120"), product_image=cls.image,
        )
        cls.task_line, cls.bom = cls.make_task_bom(1)

    @classmethod
    def make_product(cls, suffix, name, specification, unit):
        item = ProductItem.objects.create(item_number=f"WB-ITEM-{suffix}", category=cls.category)
        return ProductInformation.objects.create(
            product_number=f"WB-{suffix}", product_code=f"WB-CODE-{suffix}", category=cls.category,
            product_name=name, specification=specification, unit=unit, product_item=item, scale="CUSTOM",
        )

    @classmethod
    def make_task_bom(cls, sequence, *, order=None, sales_line=None, product=None, color=None):
        order = order or cls.order
        sales_line = sales_line or cls.sales_line
        product = product or cls.old_product
        color = color or cls.old_color
        delivery_date = timezone.localdate() + timedelta(days=30)
        batch = SalesOrderDeliveryBatch.objects.create(
            sales_order=order, line_number=sequence, batch_number=f"WB-BATCH-{sequence}",
            planned_delivery_date=delivery_date,
        )
        batch_line = SalesOrderDeliveryBatchLine.objects.create(
            delivery_batch=batch, sales_order_line=sales_line, quantity=Decimal("10"),
        )
        task = ProductionTask.objects.create(
            task_number=f"WB-TASK-{sequence}", contract_number=f"WB-CONTRACT-{sequence}",
            order_source="NEW", order_number=order.order_number, sales_order=order,
            sales_order_delivery_batch=batch, sales_order_line=sales_line,
            customer_account=cls.customer, salesperson=cls.employee, currency=cls.currency,
            order_date=timezone.localdate(), delivery_date=delivery_date, includes_tax=False,
            order_tolerance_percent=Decimal("0"), is_repeat_order=False,
            preproduction_sample_required=False, delivery_method="SPLIT", status="READY",
            created_by_employee=cls.employee,
        )
        task_line = ProductionTaskProduct.objects.create(
            production_task=task, line_number=1, sales_order_delivery_batch_line=batch_line,
            product=product, product_category=product.category, unit=product.unit,
            product_color=color, product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            item_number_snapshot=product.product_item.item_number,
            product_name_snapshot=product.product_name, specification_snapshot=product.specification,
            customer_product_name_snapshot=product.product_name, customer_specification_snapshot=product.specification,
            customer_color_snapshot=color.color_name, color_card_snapshot=color.color_card,
            color_name_snapshot=color.color_name, color_code_snapshot=color.color_code,
            material_snapshot="BOM 确认铝合金", quantity=10, currency=cls.currency,
            unit_price=Decimal("12.3456"), total_amount=Decimal("123.4560"), exchange_rate=Decimal("1"),
            image_file=cls.image,
        )
        bom = Bom.objects.create(
            bom_number=f"WB-BOM-{sequence}", production_task=task, product_line=task_line,
            version_number=1, creation_method="BLANK", product=product,
            product_category=product.category, product_unit=product.unit, product_color=color,
            product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            item_number_snapshot=product.product_item.item_number,
            product_name_snapshot=product.product_name, specification_snapshot=product.specification,
            material_snapshot=task_line.material_snapshot, order_quantity=Decimal("10"),
            created_by_employee=cls.employee, section_count=1, line_count=1,
        )
        section = BomSection.objects.create(bom=bom, line_number=1, section_type="ACCESSORY", title="五金件")
        BomLine.objects.create(
            section=section, line_number=1, part_name=cls.accessory.material_name,
            specification=cls.accessory.specification, material=cls.accessory.material,
            unit=cls.old_unit.unit_name, unit_consumption="2", total_consumption="20",
            raw_values={"source_inventory_material_id": str(cls.accessory.pk)},
        )
        return task_line, bom

    def setUp(self):
        self.client.force_authenticate(self.user)

    def review(self, bom=None, *, product=None, color=None, material=None, etag=None):
        bom = bom or self.bom
        product = product or self.new_product
        color = color or self.new_color
        payload = {"product_id": str(product.pk), "product_color_id": str(color.pk), "color_code": color.color_code}
        if material is not None:
            payload["material"] = material
        return self.client.post(
            f"/api/v1/boms/{bom.pk}/confirm-product/",
            payload,
            format="json", HTTP_IF_MATCH=etag or etag_for_instance(bom),
        )

    def verify(self, bom=None, *, etag=None):
        bom = bom or self.bom
        return self.client.post(
            f"/api/v1/boms/{bom.pk}/verify/", {},
            format="json", HTTP_IF_MATCH=etag or etag_for_instance(bom),
        )

    def new_product_payload(self, **changes):
        return {
            "product_number": "WB-CREATED", "product_code": "WB-CREATED-CODE",
            "category": str(self.category.pk), "unit": str(self.new_unit.pk),
            "product_item": str(self.new_product.product_item_id),
            "product_name": "BOM 原子建档产品", "specification": "新建规格", "scale": "CUSTOM",
            **changes,
        }

    def review_new_product(self, payload=None, *, etag=None):
        return self.client.post(
            f"/api/v1/boms/{self.bom.pk}/confirm-product/",
            {"new_product": payload or self.new_product_payload(), "product_color_id": str(self.new_color.pk),
             "color_code": self.new_color.color_code, "material": "新建产品确认材质"},
            format="json", HTTP_IF_MATCH=etag or etag_for_instance(self.bom),
        )

    def confirm(self, bom=None, *, product=None, color=None):
        bom = bom or self.bom
        reviewed = self.review(bom, product=product, color=color)
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        return self.verify(bom, etag=reviewed["ETag"])

    def chain_snapshot(self):
        objects = (self.inquiry, self.inquiry_item, self.unrelated_item, self.quotation, self.version,
                   self.quote_line, self.order, self.sales_line, self.task_line, self.bom)
        return {obj._meta.label: type(obj).objects.filter(pk=obj.pk).values().get() for obj in objects
                if obj is not self.unrelated_item} | {
            "unrelated_item": InquiryItem.objects.filter(pk=self.unrelated_item.pk).values().get(),
            "bom_lines": list(BomLine.objects.filter(section__bom=self.bom).values()),
        }

    def assert_identity(self, obj, *, name_field, specification_field, unit_field, color_field, material_field):
        obj.refresh_from_db()
        self.assertEqual(obj.product_id, self.new_product.pk)
        self.assertEqual(obj.product_category_id, self.category.pk)
        self.assertEqual(obj.product_unit_id, self.new_unit.pk)
        self.assertEqual(obj.product_color_id, self.new_color.pk)
        self.assertEqual(obj.product_number_snapshot, self.new_product.product_number)
        self.assertEqual(obj.product_code_snapshot, self.new_product.product_code)
        self.assertEqual(obj.item_number_snapshot, self.new_product.product_item.item_number)
        self.assertEqual(getattr(obj, name_field), self.new_product.product_name)
        self.assertEqual(getattr(obj, specification_field), self.new_product.specification)
        self.assertEqual(getattr(obj, unit_field), self.new_unit.unit_code)
        self.assertEqual(getattr(obj, color_field), self.new_color.color_name)
        self.assertEqual(getattr(obj, material_field), "BOM 确认铝合金")

    def test_first_confirmation_updates_accepted_quote_chain_without_changing_business_fields(self):
        before = self.chain_snapshot()
        masters_before = list(ProductInformation.objects.filter(pk__in=[self.old_product.pk, self.new_product.pk]).values())

        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.data)
        self.assert_identity(self.inquiry_item, name_field="product_description", specification_field="specification",
                             unit_field="unit_code", color_field="color", material_field="material")
        self.assert_identity(self.quote_line, name_field="product_description_snapshot", specification_field="specification_snapshot",
                             unit_field="unit_code", color_field="color_snapshot", material_field="material_snapshot")
        self.assert_identity(self.sales_line, name_field="product_name_snapshot", specification_field="specification_snapshot",
                             unit_field="unit_code_snapshot", color_field="customer_color_snapshot", material_field="material_snapshot")
        self.task_line.refresh_from_db()
        self.bom.refresh_from_db()
        for obj in (self.task_line, self.bom):
            self.assertEqual(obj.product_id, self.new_product.pk)
            self.assertEqual(obj.product_color_id, self.new_color.pk)
            self.assertEqual(obj.item_number_snapshot, self.new_product.product_item.item_number)
            self.assertEqual(obj.product_name_snapshot, self.new_product.product_name)
            self.assertEqual(obj.specification_snapshot, self.new_product.specification)
            self.assertEqual(obj.material_snapshot, "BOM 确认铝合金")
        self.assertEqual(self.task_line.unit_id, self.new_unit.pk)
        self.assertEqual(self.bom.product_unit_id, self.new_unit.pk)
        after = self.chain_snapshot()
        protected = {
            "inquiries.InquiryItem": ("quantity", "target_unit_price", "target_currency_code", "expected_date", "product_image_id"),
            "quotations.QuotationLine": ("quantity", "unit_price", "line_total", "discount_rate", "product_image_id", "source_inquiry_item_id"),
            "quotations.QuotationVersion": ("currency_code", "status", "locked_at"),
            "sales_orders.SalesOrderLine": ("quantity", "unit_price", "line_total", "product_image_id", "source_quotation_line_id"),
            "sales_orders.SalesOrder": ("currency_code", "exchange_rate", "total_amount", "status"),
            "production_tasks.ProductionTaskProduct": ("quantity", "unit_price", "total_amount", "currency_id", "image_file_id"),
            "boms.Bom": ("order_quantity",),
        }
        for model, fields in protected.items():
            for field in fields:
                with self.subTest(model=model, field=field):
                    self.assertEqual(after[model][field], before[model][field])
        self.assertEqual(after["unrelated_item"], before["unrelated_item"])
        self.assertEqual(list(ProductInformation.objects.filter(pk__in=[self.old_product.pk, self.new_product.pk]).values()), masters_before)
        audit = AuditLog.objects.get(object_type="BOM", object_id=self.bom.pk, action="CONFIRM_PRODUCT")
        self.assertEqual(audit.after_data["sales_order_line_id"], str(self.sales_line.pk))
        self.assertEqual(audit.after_data["quotation_line_id"], str(self.quote_line.pk))
        self.assertEqual(audit.after_data["inquiry_item_id"], str(self.inquiry_item.pk))
        for target in ("bom", "production_task_product", "sales_order_line", "quotation_line", "inquiry_item"):
            before_product = self.new_product if target == "bom" else self.old_product
            self.assertEqual(audit.before_data["targets"][target]["product_id"], str(before_product.pk))
            self.assertEqual(audit.after_data["targets"][target]["product_id"], str(self.new_product.pk))
        self.assertEqual(audit.before_data["targets"]["inquiry_item"]["material"], "客户原材质")
        self.assertEqual(audit.after_data["targets"]["inquiry_item"]["material"], "BOM 确认铝合金")
        self.assertNotEqual(before["quotations.QuotationVersion"]["updated_at"], after["quotations.QuotationVersion"]["updated_at"])

    def test_second_task_bom_for_same_sales_line_does_not_overwrite_first_confirmation(self):
        second_line, second_bom = self.make_task_bom(2)
        first = self.confirm()
        self.assertEqual(first.status_code, 200, first.data)
        before = self.chain_snapshot()

        second = self.confirm(second_bom, product=self.old_product, color=self.old_color)

        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(self.chain_snapshot(), before)
        second_bom.refresh_from_db()
        second_line.refresh_from_db()
        self.assertEqual(second_bom.product_id, self.old_product.pk)
        self.assertEqual(second_bom.product_color_id, self.old_color.pk)
        self.assertEqual(second_line.product_id, self.old_product.pk)
        audit = AuditLog.objects.get(object_type="BOM", object_id=second_bom.pk, action="CONFIRM_PRODUCT")
        self.assertEqual(audit.after_data["writeback_scope"], "BOM_ONLY")

    def test_stale_etag_rejects_confirmation_without_writing_any_chain_record(self):
        reviewed = self.review()
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        stale_etag = reviewed["ETag"]
        Bom.objects.filter(pk=self.bom.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
        before = self.chain_snapshot()

        response = self.verify(etag=stale_etag)

        self.assertEqual(response.status_code, 412, response.data)
        sync = self.client.post(
            f"/api/v1/boms/{self.bom.pk}/sync-order-quantity/", {},
            format="json", HTTP_IF_MATCH=stale_etag,
        )
        self.assertEqual(sync.status_code, 412, sync.data)
        self.assertEqual(self.chain_snapshot(), before)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())

    def test_audit_failure_rolls_back_bom_and_every_upstream_record(self):
        reviewed = self.review()
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        before = self.chain_snapshot()
        real_audit = bom_services.write_audit_log

        def fail_writeback_audit(**values):
            if values["action"] == "CONFIRM_PRODUCT":
                raise RuntimeError("审计写入失败")
            return real_audit(**values)

        with patch("apps.boms.services.write_audit_log", side_effect=fail_writeback_audit) as audit:
            with self.assertRaisesMessage(RuntimeError, "审计写入失败"):
                self.verify(etag=reviewed["ETag"])

        self.assertIn("CONFIRM_PRODUCT", [call.kwargs["action"] for call in audit.call_args_list])
        self.assertEqual(self.chain_snapshot(), before)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="VERIFY").exists())

    def test_service_checks_etag_again_after_locking_the_current_bom(self):
        reviewed = self.review()
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        self.bom.refresh_from_db()
        stale_bom = self.bom
        request = APIRequestFactory().post(
            f"/api/v1/boms/{stale_bom.pk}/verify/",
            HTTP_IF_MATCH=etag_for_instance(stale_bom),
        )
        Bom.objects.filter(pk=stale_bom.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
        before = self.chain_snapshot()

        # 模拟视图检查以后其他请求已提交：服务必须用锁内重新读取的 BOM 检查版本。
        with self.assertRaises(PreconditionFailed):
            verify_bom(
                bom=stale_bom, quantity_confirmation_reason="", actor_employee=self.employee, request=request,
            )

        self.assertEqual(self.chain_snapshot(), before)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())

    def test_independent_order_confirms_itself_without_rewriting_shared_quote_and_inquiry(self):
        second_order = SalesOrder.objects.create(
            order_number="SO-WRITEBACK-SECOND", source_type="QUOTATION", source_quotation_version=self.version,
            customer_account=self.customer, transaction_entity=self.entity, salesperson=self.employee,
            order_date=timezone.localdate(), currency_code="CNY", exchange_rate=Decimal("1"),
            status="CONFIRMED", total_amount=Decimal("123.4560"),
        )
        second_sales_line = SalesOrderLine.objects.create(
            sales_order=second_order, line_number=1, source_quotation_line=self.quote_line,
            product=self.old_product, product_category=self.category, product_unit=self.old_unit,
            product_color=self.old_color, product_number_snapshot=self.old_product.product_number,
            product_code_snapshot=self.old_product.product_code,
            item_number_snapshot=self.old_product.product_item.item_number,
            product_name_snapshot="原产品", specification_snapshot="原规格",
            customer_product_name_snapshot="原产品", customer_specification_snapshot="原规格",
            customer_color_snapshot=self.old_color.color_name, material_snapshot="第二单原材质",
            unit_code_snapshot=self.old_unit.unit_code, quantity=Decimal("10"),
            unit_price=Decimal("12.3456"), line_total=Decimal("123.4560"), product_image=self.image,
        )
        second_line, second_bom = self.make_task_bom(2, order=second_order, sales_line=second_sales_line)
        second_product = self.make_product("SECOND", "第二单确认产品", "第二单确认规格", self.old_unit)
        first = self.confirm()
        self.assertEqual(first.status_code, 200, first.data)
        first_chain = self.chain_snapshot()

        second = self.confirm(second_bom, product=second_product, color=self.old_color)

        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(self.chain_snapshot(), first_chain)
        for obj in (second_sales_line, second_line, second_bom):
            obj.refresh_from_db()
            self.assertEqual(obj.product_id, second_product.pk)
            self.assertEqual(obj.product_name_snapshot, second_product.product_name)
            self.assertEqual(obj.specification_snapshot, second_product.specification)
            self.assertEqual(obj.item_number_snapshot, second_product.product_item.item_number)
            self.assertEqual(obj.product_color_id, self.old_color.pk)
            self.assertEqual(obj.material_snapshot, "BOM 确认铝合金")
        self.assertEqual(second_sales_line.source_quotation_line_id, self.quote_line.pk)
        self.assertEqual(second_sales_line.quantity, Decimal("10"))
        self.assertEqual(second_sales_line.unit_price, Decimal("12.3456"))
        self.assertEqual(second_sales_line.product_image_id, self.image.pk)
        self.assertEqual(second_line.quantity, 10)
        self.assertEqual(second_line.image_file_id, self.image.pk)
        audit = AuditLog.objects.get(object_type="BOM", object_id=second_bom.pk, action="CONFIRM_PRODUCT")
        self.assertEqual(audit.after_data["writeback_scope"], "FIRST_CONFIRMATION")
        self.assertEqual(audit.after_data["sales_order_line_id"], str(second_sales_line.pk))
        self.assertIsNone(audit.after_data["quotation_line_id"])
        self.assertIsNone(audit.after_data["inquiry_item_id"])
        self.assertEqual(set(audit.after_data["targets"]), {"bom", "production_task_product", "sales_order_line"})

    def test_locked_quote_line_still_rejects_ordinary_product_edits(self):
        before = self.chain_snapshot()
        # 保存点隔离触发器抛出的数据库异常，随后仍能读取并核对原记录。
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                self.quote_line.product_description_snapshot = "绕过 BOM 的改名"
                self.quote_line.specification_snapshot = "绕过 BOM 的规格"
                self.quote_line.save(update_fields=["product_description_snapshot", "specification_snapshot", "updated_at"])

        self.assertEqual(self.chain_snapshot(), before)

    def test_review_saves_only_bom_product_snapshots_without_upstream_writeback(self):
        before = self.chain_snapshot()

        response = self.review(material="本 BOM 核对材质")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["product_information_confirmed"])
        self.assertFalse(response.data["data"]["is_order_product_outdated"])
        self.assertFalse(response.data["data"]["quantity_requires_confirmation"])
        after = self.chain_snapshot()
        for model, snapshot in before.items():
            if model != "boms.Bom":
                with self.subTest(model=model):
                    self.assertEqual(after[model], snapshot)
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.status, "PENDING_CONFIRMATION")
        self.assertEqual(self.bom.product_id, self.new_product.pk)
        self.assertEqual(self.bom.product_information_confirmed_by_employee_id, self.employee.pk)
        self.assertIsNotNone(self.bom.product_information_confirmed_at)
        self.assertEqual(self.bom.product_unit_code_snapshot, self.new_unit.unit_code)
        self.assertEqual(self.bom.product_unit_name_snapshot, self.new_unit.unit_name)
        self.assertEqual(self.bom.product_color_name_snapshot, self.new_color.color_name)
        self.assertEqual(self.bom.product_color_code_snapshot, self.new_color.color_code)
        self.assertEqual(self.bom.product_color_card_snapshot, self.new_color.color_card)
        self.assertEqual(self.bom.material_snapshot, "本 BOM 核对材质")
        self.assertTrue(AuditLog.objects.filter(object_type="BOM", object_id=self.bom.pk, action="REVIEW_PRODUCT").exists())
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())

    def test_unreviewed_unlinked_bom_cannot_be_verified(self):
        Bom.objects.filter(pk=self.bom.pk).update(product=None)
        self.bom.refresh_from_db()
        before = self.chain_snapshot()

        response = self.verify()

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.chain_snapshot(), before)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="VERIFY").exists())
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())

    def test_existing_product_id_does_not_count_as_product_review(self):
        self.assertIsNotNone(self.bom.product_id)
        self.assertIsNone(self.bom.product_information_confirmed_at)
        detail = self.client.get(f"/api/v1/boms/{self.bom.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["production_task_id"], str(self.task_line.production_task_id))
        self.assertEqual(detail.data["data"]["production_task_product_id"], str(self.task_line.pk))
        self.assertFalse(detail.data["data"]["product_information_confirmed"])
        before = self.chain_snapshot()

        response = self.verify(etag=detail["ETag"])

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.chain_snapshot(), before)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", action="CONFIRM_PRODUCT").exists())

    def test_verified_bom_can_review_product_again_without_rewriting_upstream(self):
        verified = self.confirm()
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data["data"]["status"], "VERIFIED")
        before = self.chain_snapshot()

        reviewed = self.review(
            product=self.old_product, color=self.old_color, material="后续仅本 BOM 材质", etag=verified["ETag"],
        )

        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        after = self.chain_snapshot()
        for model, snapshot in before.items():
            if model != "boms.Bom":
                with self.subTest(model=model):
                    self.assertEqual(after[model], snapshot)
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.product_id, self.old_product.pk)
        self.assertEqual(self.bom.product_color_id, self.old_color.pk)
        self.assertEqual(self.bom.product_unit_code_snapshot, self.old_unit.unit_code)
        self.assertEqual(self.bom.product_color_name_snapshot, self.old_color.color_name)
        self.assertEqual(self.bom.material_snapshot, "后续仅本 BOM 材质")
        self.assertEqual(AuditLog.objects.filter(object_type="BOM", object_id=self.bom.pk, action="REVIEW_PRODUCT").count(), 2)
        # 若编辑使 BOM 回到待确认，重新确认也只能使用第一次回写的上游信息。
        if self.bom.status == "PENDING_CONFIRMATION":
            verified_again = self.verify(etag=reviewed["ETag"])
            self.assertEqual(verified_again.status_code, 200, verified_again.data)
            after = self.chain_snapshot()
            for model, snapshot in before.items():
                if model not in {"boms.Bom", "bom_lines"}:
                    with self.subTest(model=model):
                        self.assertEqual(after[model], snapshot)
        self.assertEqual(AuditLog.objects.filter(
            object_type="BOM", object_id=self.bom.pk, action="CONFIRM_PRODUCT",
            after_data__writeback_scope="FIRST_CONFIRMATION",
        ).count(), 1)

    def test_bom_transaction_scope_cannot_change_price_image_or_another_quote_line(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('haiqu.bom_product_writeback_line', %s, true)", [str(self.quote_line.pk)])
        for values in ({"unit_price": Decimal("99")}, {"product_image_id": None}, {"source_inquiry_item_id": None}):
            with self.subTest(values=values), self.assertRaises(DatabaseError), transaction.atomic():
                QuotationLine.objects.filter(pk=self.quote_line.pk).update(**values)
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuotationLine.objects.filter(pk=self.unrelated_quote_line.pk).update(product_description_snapshot="其他行不能回写")

    def test_new_product_review_creates_and_links_only_bom_and_filters_by_reviewed_category(self):
        category = ProductCategory.objects.create(item_type="FINISHED", category_name="BOM 新建产品类别")
        item = ProductItem.objects.create(item_number="WB-CREATED-ITEM", category=category)
        before = self.chain_snapshot()
        count = ProductInformation.objects.count()

        response = self.review_new_product(self.new_product_payload(category=str(category.pk), product_item=str(item.pk)))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ProductInformation.objects.count(), count + 1)
        created = ProductInformation.objects.get(product_number="WB-CREATED")
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.product_id, created.pk)
        self.assertEqual(self.bom.product_category_id, category.pk)
        self.assertEqual(self.bom.material_snapshot, "新建产品确认材质")
        self.assertFalse(response.data["data"]["is_order_product_outdated"])
        self.assertFalse(response.data["data"]["quantity_requires_confirmation"])
        after = self.chain_snapshot()
        for model, snapshot in before.items():
            if model != "boms.Bom":
                self.assertEqual(after[model], snapshot, model)
        current_category = self.client.get("/api/v1/boms/", {"product_category_id": str(category.pk)})
        old_category = self.client.get("/api/v1/boms/", {"product_category_id": str(self.category.pk)})
        self.assertEqual(current_category.status_code, 200, current_category.data)
        self.assertEqual(old_category.status_code, 200, old_category.data)
        self.assertIn(str(self.bom.pk), [str(row["id"]) for row in current_category.data["data"]])
        self.assertNotIn(str(self.bom.pk), [str(row["id"]) for row in old_category.data["data"]])

    def test_new_product_review_audit_failure_rolls_back_product_and_bom(self):
        before = self.chain_snapshot()
        product_count, audit_count = ProductInformation.objects.count(), AuditLog.objects.count()
        real_audit = bom_services.write_audit_log

        def fail_review_audit(**values):
            if values["action"] == "REVIEW_PRODUCT":
                raise RuntimeError("产品核对审计失败")
            return real_audit(**values)

        with patch("apps.boms.services.write_audit_log", side_effect=fail_review_audit):
            with self.assertRaisesMessage(RuntimeError, "产品核对审计失败"):
                self.review_new_product()

        self.assertEqual(self.chain_snapshot(), before)
        self.assertEqual(ProductInformation.objects.count(), product_count)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        self.assertFalse(ProductInformation.objects.filter(product_number="WB-CREATED").exists())

    def test_new_product_stale_retry_does_not_create_duplicate_product(self):
        stale_etag = etag_for_instance(self.bom)
        product_count = ProductInformation.objects.count()
        saved = self.review_new_product(etag=stale_etag)
        self.assertEqual(saved.status_code, 200, saved.data)
        before_retry = self.chain_snapshot()

        retry = self.review_new_product(etag=stale_etag)

        self.assertEqual(retry.status_code, 412, retry.data)
        self.assertEqual(ProductInformation.objects.count(), product_count + 1)
        self.assertEqual(self.chain_snapshot(), before_retry)
        self.assertEqual(AuditLog.objects.filter(object_type="BOM", object_id=self.bom.pk, action="REVIEW_PRODUCT").count(), 1)

    def test_new_product_duplicate_number_and_conflicting_modes_are_rejected(self):
        before = self.chain_snapshot()
        product_count = ProductInformation.objects.count()
        duplicate = self.review_new_product(self.new_product_payload(product_number=self.old_product.product_number))
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        for choice in (
            {},
            {"product_id": str(self.old_product.pk), "new_product": self.new_product_payload()},
        ):
            with self.subTest(choice=choice):
                response = self.client.post(
                    f"/api/v1/boms/{self.bom.pk}/confirm-product/",
                    {**choice, "product_color_id": str(self.new_color.pk)},
                    format="json", HTTP_IF_MATCH=etag_for_instance(self.bom),
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(ProductInformation.objects.count(), product_count)
        self.assertEqual(self.chain_snapshot(), before)

    def test_new_product_requires_product_creation_permission(self):
        user = get_user_model().objects.create_user(username="bom_review_without_product_permission")
        Employee.objects.create(user=user, employee_code="WB_NO_CREATE", display_name="只能核对员工")
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="boms"))
        self.client.force_authenticate(user)
        before = self.chain_snapshot()
        product_count = ProductInformation.objects.count()

        response = self.review_new_product()

        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn("新增产品信息", str(response.data))
        self.assertEqual(ProductInformation.objects.count(), product_count)
        self.assertEqual(self.chain_snapshot(), before)

    def test_verification_uses_saved_review_snapshot_when_product_master_changes(self):
        reviewed = self.review()
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        ProductInformation.objects.filter(pk=self.new_product.pk).update(
            product_name="主档后来修改的名称", specification="主档后来修改的规格",
        )

        verified = self.verify(etag=reviewed["ETag"])

        self.assertEqual(verified.status_code, 200, verified.data)
        for obj, name_field, specification_field in (
            (self.bom, "product_name_snapshot", "specification_snapshot"),
            (self.task_line, "product_name_snapshot", "specification_snapshot"),
            (self.sales_line, "product_name_snapshot", "specification_snapshot"),
            (self.quote_line, "product_description_snapshot", "specification_snapshot"),
            (self.inquiry_item, "product_description", "specification"),
        ):
            obj.refresh_from_db()
            self.assertEqual(getattr(obj, name_field), "确认产品")
            self.assertEqual(getattr(obj, specification_field), "确认规格")
        self.new_product.refresh_from_db()
        self.assertEqual(self.new_product.product_name, "主档后来修改的名称")

    def test_create_bom_reuses_review_only_for_identical_same_sales_line(self):
        verified = self.confirm()
        self.assertEqual(verified.status_code, 200, verified.data)
        next_task_line, _ = self.make_task_bom(2, product=self.new_product, color=self.new_color)

        reused = create_bom(product_line=next_task_line, creation_method="BLANK", actor_employee=self.employee)

        self.assertIsNotNone(reused.product_information_confirmed_at)
        self.assertEqual(reused.product_information_confirmed_by_employee_id, self.employee.pk)
        self.assertTrue(AuditLog.objects.filter(object_type="BOM", object_id=reused.pk, action="REUSE_PRODUCT_REVIEW").exists())
        ProductionTaskProduct.objects.filter(pk=next_task_line.pk).update(material_snapshot="后续批次不同材质")
        changed = create_bom(product_line=next_task_line, creation_method="BLANK", actor_employee=self.employee)
        self.assertIsNone(changed.product_information_confirmed_at)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", object_id=changed.pk, action="REUSE_PRODUCT_REVIEW").exists())

    def test_create_bom_for_new_order_with_same_product_never_reuses_other_order_review(self):
        verified = self.confirm()
        self.assertEqual(verified.status_code, 200, verified.data)
        second_order = SalesOrder.objects.get(pk=self.order.pk)
        second_order.pk = None
        second_order.order_number = "SO-WRITEBACK-REPEAT"
        second_order.save(force_insert=True)
        second_sales_line = SalesOrderLine.objects.get(pk=self.sales_line.pk)
        second_sales_line.pk = None
        second_sales_line.sales_order = second_order
        second_sales_line.save(force_insert=True)
        next_task_line, _ = self.make_task_bom(
            2, order=second_order, sales_line=second_sales_line, product=self.new_product, color=self.new_color,
        )

        created = create_bom(
            product_line=next_task_line, creation_method="COPY", source_bom=self.bom, actor_employee=self.employee,
        )

        self.assertEqual(created.product_id, self.new_product.pk)
        self.assertIsNone(created.product_information_confirmed_at)
        self.assertEqual(created.copied_from_id, self.bom.pk)
        self.assertFalse(AuditLog.objects.filter(object_type="BOM", object_id=created.pk, action="REUSE_PRODUCT_REVIEW").exists())

    def test_writeback_permission_is_removed_after_success_and_failure(self):
        from apps.quotations.product_writeback import save_bom_product_information

        self.quote_line.product_description_snapshot = "允许的产品确认"
        save_bom_product_information(self.quote_line)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('haiqu.bom_product_writeback_line', true)")
            self.assertEqual(cursor.fetchone()[0], "")
        self.quote_line.unit_code = "X" * 31
        with self.assertRaises(DatabaseError):
            save_bom_product_information(self.quote_line)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('haiqu.bom_product_writeback_line', true)")
            self.assertEqual(cursor.fetchone()[0], "")

    def make_manual_bom(self):
        task_line, bom = self.make_task_bom(3)
        ProductionTaskProduct.objects.filter(pk=task_line.pk).update(
            sales_order_delivery_batch_line=None, product=None,
            product_number_snapshot="", product_code_snapshot="", item_number_snapshot="",
        )
        ProductionTask.objects.filter(pk=task_line.production_task_id).update(
            sales_order=None, sales_order_delivery_batch=None, sales_order_line=None,
            customer_account=None, order_number="WB-MANUAL-3",
        )
        task_line.refresh_from_db()
        bom.refresh_from_db()
        return task_line, bom

    def test_manual_first_bom_updates_current_product_without_upstream_writeback(self):
        task_line, bom = self.make_manual_bom()
        before = self.chain_snapshot()
        original_values = ProductionTaskProduct.objects.filter(pk=task_line.pk).values().get()

        response = self.confirm(bom)

        self.assertEqual(response.status_code, 200, response.data)
        task_line.refresh_from_db()
        self.assertEqual(task_line.product_id, self.new_product.pk)
        self.assertEqual(task_line.product_number_snapshot, self.new_product.product_number)
        self.assertEqual(task_line.item_number_snapshot, self.new_product.product_item.item_number)
        self.assertEqual(task_line.unit_id, self.new_unit.pk)
        self.assertEqual(task_line.product_color_id, self.new_color.pk)
        self.assertEqual(self.chain_snapshot(), before)
        for field in ("quantity", "unit_price", "total_amount", "currency_id", "image_file_id"):
            self.assertEqual(getattr(task_line, field), original_values[field])
        audit = AuditLog.objects.get(object_type="BOM", object_id=bom.pk, action="CONFIRM_PRODUCT")
        self.assertEqual(audit.after_data["writeback_scope"], "FIRST_CONFIRMATION")
        self.assertEqual(set(audit.after_data["targets"]), {"bom", "production_task_product"})
        for field in ("sales_order_line_id", "quotation_line_id", "inquiry_item_id"):
            self.assertIsNone(audit.after_data[field])

    def test_manual_later_bom_keeps_first_confirmed_current_product(self):
        task_line, first_bom = self.make_manual_bom()
        first = self.confirm(first_bom)
        self.assertEqual(first.status_code, 200, first.data)
        before = ProductionTaskProduct.objects.filter(pk=task_line.pk).values().get()
        second_bom = create_bom(
            product_line=task_line, creation_method="COPY", source_bom=first_bom,
            actor_employee=self.employee,
        )

        second = self.confirm(second_bom, product=self.old_product, color=self.old_color)

        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(ProductionTaskProduct.objects.filter(pk=task_line.pk).values().get(), before)
        second_bom.refresh_from_db()
        self.assertEqual(second_bom.product_id, self.old_product.pk)
        audit = AuditLog.objects.get(object_type="BOM", object_id=second_bom.pk, action="CONFIRM_PRODUCT")
        self.assertEqual(audit.after_data["writeback_scope"], "BOM_ONLY")
        self.assertEqual(set(audit.after_data["targets"]), {"bom"})
