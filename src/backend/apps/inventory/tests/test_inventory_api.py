import copy
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomSectionType, BomStatus
from apps.core.models import DailyBusinessNumberCounter
from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseQuantityParseStatus,
    PurchaseReturn,
    PurchaseReturnStatus,
    Supplier,
    SupplierCategory,
    SupplierType,
)
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.production_tasks.models import DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.reference_data.models import Currency, FabricMaterial, ProductCategory, ProductColor, ProductionUnit

from ..models import (
    FinishedGoodsReceipt,
    FinishedGoodsReceiptSource,
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockBalance,
    MaterialStockMovement,
    WarehouseLocation,
)
from ..services import packaging_values, create_finished_goods_receipt
from ..api.serializers import FinishedGoodsReceiptSerializer
from ..selectors import receipt_batches
from .finished_receipt_fixture import historical_finished_receipt


class FinishedGoodsInventoryApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="inventory_user")
        self.employee = Employee.objects.create(user=self.user, employee_code="INVENTORY_USER", display_name="仓库测试员工")
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=["inventory", "production_tasks"]))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).select_related("unit").first()
        self.currency = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.assertIsNotNone(self.product)
        self.assertIsNotNone(self.currency)
        self.customer = CustomerAccount.objects.create(account_code="INV_TEST_CUSTOMER", account_name="库存测试客户", primary_country_code="CN")
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT-INV-0001", contract_number="HTC-INV-0001", order_source=OrderSource.NEW,
            order_number="ORDER-INV-001", customer_account=self.customer, order_date=today, delivery_date=today,
            salesperson=self.employee, currency=self.currency, includes_tax=True, order_tolerance_percent=Decimal("10"),
            is_repeat_order=False, preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.IN_PRODUCTION, created_by_employee=self.employee,
        )
        self.line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=self.product,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification, color_name_snapshot="炭黑色", quantity=10,
            unit=self.product.unit, currency=self.currency, unit_price=Decimal("1"), total_amount=Decimal("10"), exchange_rate=Decimal("1"),
        )
        warehouse_response = self.client.post("/api/v1/warehouses/", {
            "warehouse_number": "CKT01", "warehouse_name": "测试成品仓", "warehouse_type": "FINISHED",
            "address": "一楼", "status": "ACTIVE", "responsible_person_name": "测试员", "contact_phone": "",
        }, format="json")
        self.assertEqual(warehouse_response.status_code, 201, warehouse_response.data)
        self.warehouse_id = warehouse_response.data["data"]["id"]
        zone_response = self.client.post("/api/v1/warehouse-zones/", {"warehouse": self.warehouse_id, "zone_name": "一楼", "status": "ACTIVE"}, format="json")
        self.assertEqual(zone_response.status_code, 201, zone_response.data)
        self.zone_id = zone_response.data["data"]["id"]
        location_response = self.client.post("/api/v1/warehouse-locations/", {"zone": self.zone_id, "location_number": "A1-1-1", "capacity_box_slots": 2, "status": "ACTIVE"}, format="json")
        self.assertEqual(location_response.status_code, 201, location_response.data)
        self.location_id = location_response.data["data"]["id"]
        self.color, _ = ProductColor.objects.get_or_create(
            color_card="仓库测试色卡",
            color_code="INV-BLACK",
            color_name="库存测试黑",
        )
        self.supplier, _ = Supplier.objects.get_or_create(
            supplier_number="GYS99999",
            defaults={
                "supplier_type": SupplierType.FINISHED,
                "supplier_categories": [SupplierCategory.FINISHED_GOODS],
                "supplier_name": "库存测试成品供应商",
            },
        )

    def receipt_payload(self, **overrides):
        values = {
            "production_task_product_id": str(self.line.pk), "location_id": self.location_id,
            "supplier_id": None, "expected_received_total": 0, "received_quantity": 6,
            "quantity_per_box": 5, "unit_id": str(self.product.unit_id), "actual_color": "实际黑色", "remark": "首批",
        }
        values.update(overrides)
        from .assembly_reporting_fixture import seed_reported_assembly
        product_line = ProductionTaskProduct.objects.filter(pk=values['production_task_product_id']).first()
        if product_line:
            seed_reported_assembly(product_line, self.employee)
        return values

    def create_receipt(self):
        # 历史批次用于库存查询与出库测试，不代表新入库业务已经完成。
        receipt = historical_finished_receipt(product_line=self.line, actor=self.employee,
                                               location_id=self.location_id)
        return FinishedGoodsReceiptSerializer(receipt_batches().get(pk=receipt.pk)).data

    def create_pending_receipt(self, **changes):
        data = self.receipt_payload(**changes)
        for key in ('production_task_product_id', 'location_id', 'unit_id'):
            data[key] = uuid.UUID(str(data[key]))
        return create_finished_goods_receipt(validated_data=data, actor_employee=self.employee, request=None)

    def create_second_line(self):
        return ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=2, product=self.product,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification, color_name_snapshot="沙色", quantity=10,
            unit=self.product.unit, currency=self.currency, unit_price=Decimal("1"), total_amount=Decimal("10"),
            exchange_rate=Decimal("1"),
        )

    def test_packaging_calculation_and_inventory_aggregation(self):
        self.assertEqual(packaging_values(11, 5), (2, 1, 3))
        self.assertEqual(packaging_values(11, None), (None, None, None))
        receipt = self.create_receipt()
        response = self.client.get("/api/v1/finished-goods-inventory/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["inventory_quantity"], 6)
        self.assertEqual(row["batch_count"], 1)
        self.assertEqual(row["occupied_box_slots"], 2)
        self.assertTrue(row["latest_inbound_time"])
        self.assertEqual(str(row["receipt_ids"][0]), receipt["id"])
        self.assertEqual(str(row["product_id"]), str(self.product.pk))
        self.assertNotIn("order_number", row)
        self.assertEqual(row["task_number"], self.task.task_number)

    def test_inventory_separates_production_tasks_and_receipts_keep_sources(self):
        historical_finished_receipt(product_line=self.line, actor=self.employee,
                                    location_id=self.location_id, quantity=2, quantity_per_box=None)

        second_task = copy.copy(self.task)
        second_task.pk = uuid.uuid4()
        second_task._state.adding = True
        second_task.task_number = "HT-INV-0002"
        second_task.contract_number = "HTC-INV-0002"
        second_task.order_number = "ORDER-INV-002"
        second_task.save(force_insert=True)
        second_line = self.create_second_line()
        second_line.production_task = second_task
        second_line.line_number = 1
        second_line.save(update_fields=["production_task", "line_number", "updated_at"])
        historical_finished_receipt(product_line=second_line, actor=self.employee,
                                    location_id=self.location_id, quantity=3, quantity_per_box=None)

        inventory = self.client.get("/api/v1/finished-goods-inventory/")
        self.assertEqual(inventory.status_code, 200, inventory.data)
        self.assertEqual(inventory.data["count"], 2)
        self.assertEqual(sorted(row["inventory_quantity"] for row in inventory.data["results"]), [2, 3])
        self.assertTrue(all(row["batch_count"] == 1 for row in inventory.data["results"]))

        receipts = self.client.get("/api/v1/finished-goods-inventory/receipts/")
        self.assertEqual(receipts.status_code, 200, receipts.data)
        self.assertEqual(
            {item["order_number_snapshot"] for item in receipts.data["data"]},
            {"ORDER-INV-001", "ORDER-INV-002"},
        )

    def test_pending_receipt_allows_empty_packaging_without_inventory(self):
        receipt = self.create_pending_receipt(quantity_per_box=None)
        self.assertEqual(receipt.status, 'PENDING')
        self.assertEqual(receipt.remaining_quantity, 0)
        self.assertEqual(receipt.remaining_box_slots, 0)
        self.assertIsNone(receipt.confirmed_at)
        self.assertIsNone(receipt.quantity_per_box)
        self.assertIsNone(receipt.box_count)
        self.assertIsNone(receipt.tail_quantity)
        self.assertIsNone(receipt.occupied_box_slots)
        self.assertEqual(self.client.get('/api/v1/finished-goods-inventory/').data['count'], 0)

    def test_pending_service_keeps_packaging_but_does_not_credit_stock(self):
        receipt = self.create_pending_receipt()
        self.assertEqual(receipt.status, 'PENDING')
        self.assertEqual((receipt.received_quantity, receipt.occupied_box_slots), (6, 2))
        self.assertEqual((receipt.remaining_quantity, receipt.remaining_box_slots), (0, 0))
        self.assertIsNotNone(receipt.submitted_at)
        self.assertIsNone(receipt.confirmed_by_employee_id)
        self.assertEqual(self.client.get('/api/v1/finished-goods-inventory/').data['count'], 0)

    def test_legacy_batch_receipt_entry_is_removed(self):
        response = self.client.post(
            "/api/v1/finished-goods-inventory/batch-receipts/",
            {"items": [self.receipt_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(FinishedGoodsReceipt.objects.exists())

    def test_legacy_single_receipt_entry_is_read_only(self):
        response = self.client.post(
            "/api/v1/finished-goods-inventory/receipts/",
            self.receipt_payload(),
            format="json",
        )
        # 已移除的写动作先被业务权限门禁拒绝，不能创建记录。
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(FinishedGoodsReceipt.objects.count(), 0)
        receipt = self.create_receipt()
        history = self.client.get('/api/v1/finished-goods-inventory/receipts/')
        self.assertEqual(history.status_code, 200, history.data)
        self.assertEqual(history.data['data'][0]['id'], receipt['id'])

    def test_options_use_procurement_supplier_and_production_color(self):
        response = self.client.get("/api/v1/finished-goods-inventory/options/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertIn(str(self.supplier.pk), {str(item["id"]) for item in data["suppliers"]})
        self.assertIn(str(self.color.pk), {str(item["id"]) for item in data["product_colors"]})

    def test_pending_service_rejects_tolerance_limit_without_extra_record(self):
        self.create_receipt()
        with self.assertRaises(ValidationError):
            self.create_pending_receipt(expected_received_total=6, received_quantity=6)
        self.assertEqual(FinishedGoodsReceipt.objects.count(), 1)

    def test_partial_outbound_recalculates_slots_and_stale_stock_returns_409(self):
        department, _ = OrganizationUnit.objects.get_or_create(
            unit_code="DEPT_WAREHOUSE", defaults={"unit_name": "测试仓库部门"},
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=self.employee,
            organization_unit=department,
            effective_from=timezone.now() - timedelta(days=1),
        )
        receipt = self.create_receipt()
        payload = {"responsible_employee_id": str(self.employee.pk), "shipment_date": str(timezone.localdate()), "receiver_name": "领用人", "used_for_order_number": "EXT-001", "remark": "测试", "items": [{"receipt_id": receipt["id"], "expected_remaining_quantity": 6, "outbound_quantity": 4, "quantity_per_box": 3}]}
        response = self.client.post("/api/v1/finished-goods-inventory/outbounds/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        current = FinishedGoodsReceipt.objects.get(pk=receipt["id"])
        self.assertEqual(current.remaining_quantity, 2)
        self.assertEqual(current.remaining_box_slots, 1)
        stale = self.client.post("/api/v1/finished-goods-inventory/outbounds/", payload, format="json")
        self.assertEqual(stale.status_code, 409, stale.data)

    def test_sample_source_receipt_must_be_operated_from_sample_inventory(self):
        receipt = self.create_receipt()
        FinishedGoodsReceipt.objects.filter(pk=receipt["id"]).update(
            source_type=FinishedGoodsReceiptSource.SAMPLE_INVENTORY,
            source_document_number="SYGJ-20260909-001",
        )
        payload = {
            "responsible_employee_id": str(self.employee.pk), "shipment_date": str(timezone.localdate()), "receiver_name": "领用人",
            "used_for_order_number": "",
            "remark": "测试重复扣减保护",
            "items": [{
                "receipt_id": receipt["id"],
                "expected_remaining_quantity": 6,
                "outbound_quantity": 1,
                "quantity_per_box": 3,
            }],
        }

        response = self.client.post(
            "/api/v1/finished-goods-inventory/outbounds/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("样品库", response.data["error"]["message"])
        current = FinishedGoodsReceipt.objects.get(pk=receipt["id"])
        self.assertEqual(current.remaining_quantity, 6)

    def test_configuration_update_requires_etag_and_stock_blocks_disable(self):
        self.create_receipt()
        without_etag = self.client.patch(f"/api/v1/warehouse-locations/{self.location_id}/", {"status": "DISABLED"}, format="json")
        self.assertEqual(without_etag.status_code, 428, without_etag.data)
        detail = self.client.get(f"/api/v1/warehouse-locations/{self.location_id}/")
        blocked = self.client.patch(f"/api/v1/warehouse-locations/{self.location_id}/", {"status": "DISABLED"}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(blocked.status_code, 409, blocked.data)

    def test_legacy_candidate_routes_are_removed(self):
        for path in ('eligible-products', 'eligible-orders'):
            with self.subTest(path=path):
                response = self.client.get(f'/api/v1/finished-goods-inventory/{path}/')
                self.assertEqual(response.status_code, 404)


class MaterialInventoryApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="material_inventory_user")
        self.employee = Employee.objects.create(user=self.user, employee_code="MATERIAL_INV", display_name="材料仓测试员工")
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=["inventory", "procurement", "production_tasks"]))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.product = ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True).select_related("unit").first()
        self.currency = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.customer = CustomerAccount.objects.create(account_code="MAT_INV_CUSTOMER", account_name="材料库存客户", primary_country_code="CN")
        today = timezone.localdate()
        self.task = ProductionTask.objects.create(
            task_number="HT-MAT-0001", contract_number="HTC-MAT-0001", order_source=OrderSource.NEW,
            order_number="ORDER-MAT-001", customer_account=self.customer, order_date=today, delivery_date=today,
            salesperson=self.employee, currency=self.currency, includes_tax=True, order_tolerance_percent=Decimal("0"),
            is_repeat_order=False, preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.IN_PRODUCTION, created_by_employee=self.employee,
        )
        self.product_line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=1, product=self.product,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            item_number_snapshot=self.product.product_item.item_number, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification, quantity=10, unit=self.product.unit,
            currency=self.currency, unit_price=Decimal("1"), total_amount=Decimal("10"), exchange_rate=Decimal("1"),
        )
        self.bom = Bom.objects.create(
            bom_number="BOM-MAT-TEST-1", production_task=self.task, product_line=self.product_line, version_number=1,
            creation_method=BomCreationMethod.BLANK, status=BomStatus.VERIFIED,
            product_number_snapshot=self.product.product_number, product_code_snapshot=self.product.product_code,
            product_name_snapshot=self.product.product_name, specification_snapshot=self.product.specification,
            order_quantity=Decimal("10"), quantity_difference=Decimal("0"), section_count=1, line_count=1,
            created_by_employee=self.employee,
        )
        section = BomSection.objects.create(bom=self.bom, line_number=1, section_type=BomSectionType.PROFILE, title="管材类")
        self.bom_line = BomLine.objects.create(
            section=section, line_number=1, category="管材", material="黑管", part_name="测试钢管",
            specification="Φ25×1.0", raw_material="测试钢管", unit="PCS", branch_count="10",
        )
        material_category = ProductCategory.objects.filter(category_name="管材", item_type="MATERIAL").first()
        stock_unit = ProductionUnit.objects.filter(unit_name="PCS").first()
        self.assertIsNotNone(material_category)
        self.assertIsNotNone(stock_unit)
        self.raw_material = RawMaterialInformation.objects.create(
            material_number="MAT-INV-TEST-001",
            item_type="MATERIAL",
            category=material_category,
            material_name="测试钢管",
            specification="Φ25×1.0",
            unit=stock_unit,
            material="黑管",
            warehouse_number="CKM01",
            warehouse_name="测试材料仓",
        )
        self.bom_line.raw_values = {"source_raw_material_id": str(self.raw_material.pk)}
        self.bom_line.save(update_fields=["raw_values", "updated_at"])
        self.supplier = Supplier.objects.create(
            supplier_number="GYS98888", supplier_type=SupplierType.MATERIAL,
            supplier_categories=[SupplierCategory.TUBE], supplier_name="材料测试供应商", is_disabled=False,
        )
        self.order = PurchaseOrder.objects.create(
            order_number="CGDD2026090701", production_task=self.task,
            production_task_number_snapshot=self.task.task_number, sales_order_number_snapshot=self.task.order_number,
            customer_name_snapshot=self.customer.account_name, source_revision="test", currency=self.currency,
            currency_code_snapshot=self.currency.code, status=PurchaseOrderStatus.PURCHASING,
            created_by_employee=self.employee,
        )
        self.purchase_line = PurchaseOrderLine.objects.create(
            purchase_order=self.order, line_number=1, bom=self.bom, bom_line=self.bom_line,
            source_bom_line_id_snapshot=self.bom_line.pk, product_line_id_snapshot=self.product_line.pk,
            bom_number_snapshot=self.bom.bom_number, product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code, product_name_snapshot=self.product.product_name,
            product_specification_snapshot=self.product.specification, section_type_snapshot=BomSectionType.PROFILE,
            section_title_snapshot="管材类", category_snapshot="管材", material_snapshot="黑管",
            part_name_snapshot="测试钢管", specification_snapshot="Φ25×1.0", raw_material_snapshot=self.raw_material.material_number,
            required_quantity=Decimal("10.5000"), source_quantity_field="branch_count", source_quantity_text="10.5",
            source_unit_text="PCS", quantity_parse_status=PurchaseQuantityParseStatus.READY, supplier=self.supplier,
            supplier_number_snapshot=self.supplier.supplier_number, supplier_name_snapshot=self.supplier.supplier_name,
            supplier_type_snapshot=self.supplier.supplier_type, supplier_categories_snapshot=list(self.supplier.supplier_categories),
            actual_purchase_quantity=Decimal("10.5000"), unit_price=Decimal("2"), amount=Decimal("21"),
        )
        warehouse = self.client.post("/api/v1/warehouses/", {
            "warehouse_number": "CKM01", "warehouse_name": "测试材料仓", "warehouse_type": "MATERIAL",
            "address": "一楼", "status": "ACTIVE", "responsible_person_name": "测试员", "contact_phone": "",
        }, format="json").data["data"]
        zone = self.client.post("/api/v1/warehouse-zones/", {"warehouse": warehouse["id"], "zone_name": "一楼", "status": "ACTIVE"}, format="json").data["data"]
        self.zone_id = zone["id"]
        self.location_id = self.client.post("/api/v1/warehouse-locations/", {"zone": zone["id"], "location_number": "M-A-01", "capacity_box_slots": None, "status": "ACTIVE"}, format="json").data["data"]["id"]
        self.second_location_id = self.client.post("/api/v1/warehouse-locations/", {"zone": zone["id"], "location_number": "M-A-02", "capacity_box_slots": None, "status": "ACTIVE"}, format="json").data["data"]["id"]

    def payload(self, quantity="4.2500", expected="10.5000", location_id=None, inbound_date=None):
        return {
            "inbound_date": inbound_date or timezone.localdate().isoformat(), "remark": "测试入库",
            "items": [{
                "purchase_order_line_id": str(self.purchase_line.pk), "zone_id": self.zone_id,
                "location_id": self.location_id if location_id is None else location_id,
                "expected_remaining_quantity": expected, "received_quantity": quantity, "remark": "首批",
            }],
        }

    def confirm_quality(self, response, return_quantity="0.0000", quality_remark="检验合格"):
        inbound = response.data["data"]
        return self.client.post(
            f"/api/v1/material-inventory/quality-batches/{inbound['id']}/confirm/",
            {
                "items": [
                    {
                        "line_id": line["id"],
                        "expected_received_quantity": line["received_quantity"],
                        "return_quantity": return_quantity,
                        "quality_remark": quality_remark,
                    }
                    for line in inbound["lines"]
                ]
            },
            format="json",
        )

    def test_options_returns_material_warehouse_configuration(self):
        response = self.client.get("/api/v1/material-inventory/options/")

        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(len(data["warehouses"]), 1)
        self.assertEqual(len(data["zones"]), 1)
        self.assertEqual(len(data["locations"]), 2)

    def test_options_does_not_fall_back_to_finished_locations_when_material_locations_are_empty(self):
        WarehouseLocation.objects.filter(pk__in=[self.location_id, self.second_location_id]).delete()
        response = self.client.get("/api/v1/material-inventory/options/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["locations"], [])

    def use_general_material(self):
        # 本组通用收货断言使用小数数量，明确为配件，避免混入管材根米专用门禁。
        self.raw_material.category, _ = ProductCategory.objects.get_or_create(
            category_name="五金", defaults={"item_type": "MATERIAL"},
        )
        self.raw_material.material_name = "测试连接件"
        self.raw_material.specification = "连接件规格"
        self.raw_material.material = "铁"
        self.raw_material.save(update_fields=["category", "material_name", "specification", "material"])
        section = self.bom_line.section
        section.section_type, section.title = BomSectionType.ACCESSORY, "配件类"
        section.save(update_fields=["section_type", "title"])
        source_values = {
            "category": "五金", "material": "铁", "part_name": "测试连接件",
            "specification": "连接件规格", "raw_material": "测试连接件",
            "branch_count": "", "budget_quantity": "10.5",
        }
        for field, value in source_values.items():
            setattr(self.bom_line, field, value)
        self.bom_line.save(update_fields=list(source_values))
        self.supplier.supplier_categories = ["HARDWARE"]
        self.supplier.save(update_fields=["supplier_categories"])
        purchase_values = {
            "section_type_snapshot": BomSectionType.ACCESSORY, "section_title_snapshot": "配件类",
            "category_snapshot": "五金", "material_snapshot": "铁", "part_name_snapshot": "测试连接件",
            "specification_snapshot": "连接件规格", "raw_material_snapshot": self.raw_material.material_number,
            "source_quantity_field": "budget_quantity", "supplier_categories_snapshot": ["HARDWARE"],
        }
        for field, value in purchase_values.items():
            setattr(self.purchase_line, field, value)
        self.purchase_line.save(update_fields=list(purchase_values))

    def test_receipt_allows_material_zone_without_location(self):
        self.use_general_material()
        WarehouseLocation.objects.filter(pk__in=[self.location_id, self.second_location_id]).delete()
        payload = self.payload()
        payload["items"][0].pop("location_id")

        response = self.client.post("/api/v1/material-inventory/receipts/", payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertIsNone(MaterialInboundLine.objects.get().location_id)

    def test_receipt_freezes_universal_inventory_material_identity(self):
        self.bom_line.raw_values = {
            "source_inventory_material_id": str(self.raw_material.pk)
        }
        self.bom_line.save(update_fields=["raw_values", "updated_at"])

        response = self.client.post(
            "/api/v1/material-inventory/receipts/",
            self.payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        inbound_line = MaterialInboundLine.objects.get(
            inbound_id=response.data["data"]["id"]
        )
        self.assertEqual(
            inbound_line.raw_material_information_id,
            self.raw_material.pk,
        )

    def test_partial_receipt_remains_eligible_and_supports_pinyin_search(self):
        eligible = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": str(self.order.pk)})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(eligible.data["data"][0]["remaining_quantity"], "10.5000")
        created = self.client.post("/api/v1/material-inventory/receipts/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["status"], MaterialInboundStatus.PENDING_QUALITY)
        after = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": str(self.order.pk)})
        self.assertEqual(after.data["data"][0]["remaining_quantity"], "6.2500")
        before_quality = self.client.get("/api/v1/material-inventory/")
        self.assertEqual(before_quality.data["count"], 0)
        confirmed = self.confirm_quality(created)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["status"], MaterialInboundStatus.CONFIRMED)
        searched = self.client.get("/api/v1/material-inventory/", {"q": "csgg"})
        self.assertEqual(searched.status_code, 200, searched.data)
        self.assertEqual(searched.data["count"], 1)
        row = searched.data["results"][0]
        self.assertEqual(row["inventory_quantity"], Decimal("4.2500"))
        self.assertEqual(row["stock_item_id"], self.raw_material.pk)
        self.assertNotIn("purchase_order_number", row)
        self.assertNotIn("production_task_number", row)
        self.assertNotIn("supplier_name", row)
        summary = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/summary/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["data"]["current_quantity"], "4.2500")
        purchases = self.client.get(f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/")
        self.assertEqual(purchases.status_code, 200, purchases.data)
        self.assertEqual(purchases.data["data"][0]["purchase_order_number"], self.order.order_number)
        self.assertEqual(purchases.data["data"][0]["actual_inbound_quantity"], "4.2500")

    def test_zero_quantity_legacy_balance_is_hidden_from_inventory_list(self):
        created = self.client.post("/api/v1/material-inventory/receipts/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.confirm_quality(created)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balance = MaterialStockBalance.objects.get(raw_material=self.raw_material)
        balance.quantity = 0
        balance.save(update_fields=["quantity", "updated_at"])

        response = self.client.get("/api/v1/material-inventory/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_order_purchase_trace_resolves_fabric_material_mapping(self):
        fabric_material = FabricMaterial.objects.create(
            material_name="库存追溯映射面料",
            inventory_raw_material=self.raw_material,
        )
        self.bom_line.raw_values = {"source_fabric_material_id": str(fabric_material.pk)}
        self.bom_line.save(update_fields=["raw_values", "updated_at"])

        before_receipt = self.client.get(
            f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/"
        )
        self.assertEqual(before_receipt.status_code, 200, before_receipt.data)
        self.assertEqual(before_receipt.data["data"][0]["purchase_order_number"], self.order.order_number)

        receipt = self.client.post("/api/v1/material-inventory/receipts/", self.payload(), format="json")
        self.assertEqual(receipt.status_code, 201, receipt.data)
        inbound_line = MaterialInboundLine.objects.get(inbound_id=receipt.data["data"]["id"])
        self.assertEqual(inbound_line.raw_material_information_id, self.raw_material.pk)

        replacement = RawMaterialInformation.objects.create(
            material_number="MAT-INV-TEST-002",
            item_type="MATERIAL",
            category=self.raw_material.category,
            material_name="库存追溯替换原料",
            specification="600D",
            unit=self.raw_material.unit,
            material="替换面料",
            warehouse_number="CKM01",
            warehouse_name="测试材料仓",
        )
        fabric_material.inventory_raw_material = replacement
        fabric_material.save(update_fields=["inventory_raw_material", "updated_at"])

        historical = self.client.get(
            f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/"
        )
        remapped = self.client.get(
            f"/api/v1/material-inventory/{replacement.pk}/order-purchases/"
        )
        self.assertEqual(historical.status_code, 200, historical.data)
        self.assertEqual(historical.data["data"][0]["purchase_order_number"], self.order.order_number)
        self.assertEqual(remapped.status_code, 200, remapped.data)
        self.assertEqual(remapped.data["data"], [])

        confirmed = self.confirm_quality(receipt)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        inbound_line.refresh_from_db()
        self.assertEqual(inbound_line.raw_material_information_id, self.raw_material.pk)
        movement = MaterialStockMovement.objects.get(
            source_type="MATERIAL_INBOUND",
            source_line_id=inbound_line.pk,
        )
        self.assertEqual(movement.balance.raw_material_id, self.raw_material.pk)
        confirmed_historical = self.client.get(
            f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/"
        )
        confirmed_remapped = self.client.get(
            f"/api/v1/material-inventory/{replacement.pk}/order-purchases/"
        )
        self.assertEqual(confirmed_historical.data["data"][0]["actual_inbound_quantity"], "4.2500")
        self.assertEqual(confirmed_remapped.data["data"], [])

        second_receipt = self.client.post(
            "/api/v1/material-inventory/receipts/",
            self.payload(quantity="1.0000", expected="6.2500"),
            format="json",
        )
        self.assertEqual(second_receipt.status_code, 201, second_receipt.data)
        second_line = MaterialInboundLine.objects.get(inbound_id=second_receipt.data["data"]["id"])
        self.assertEqual(second_line.raw_material_information_id, self.raw_material.pk)
        second_confirmed = self.confirm_quality(second_receipt)
        self.assertEqual(second_confirmed.status_code, 200, second_confirmed.data)
        final_historical = self.client.get(
            f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/"
        )
        final_remapped = self.client.get(
            f"/api/v1/material-inventory/{replacement.pk}/order-purchases/"
        )
        self.assertEqual(final_historical.data["data"][0]["actual_inbound_quantity"], "5.2500")
        self.assertEqual(final_remapped.data["data"], [])

        second_line.raw_material_information = replacement
        second_line.save(update_fields=["raw_material_information", "updated_at"])
        conflicted_old = self.client.get(
            f"/api/v1/material-inventory/{self.raw_material.pk}/order-purchases/"
        )
        conflicted_new = self.client.get(
            f"/api/v1/material-inventory/{replacement.pk}/order-purchases/"
        )
        self.assertEqual(conflicted_old.status_code, 409, conflicted_old.data)
        self.assertEqual(conflicted_new.status_code, 409, conflicted_new.data)

    def test_batch_allows_same_line_split_across_locations(self):
        payload = self.payload()
        payload["items"] = [
            {**payload["items"][0], "received_quantity": "3.0000"},
            {**payload["items"][0], "location_id": self.second_location_id, "received_quantity": "2.0000"},
        ]
        response = self.client.post("/api/v1/material-inventory/batch-receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertEqual(MaterialInboundLine.objects.count(), 2)
        self.assertEqual(MaterialInbound.objects.get().status, MaterialInboundStatus.PENDING_QUALITY)

    def test_inventory_merges_identical_material_from_different_purchase_lines(self):
        first = self.client.post("/api/v1/material-inventory/receipts/", self.payload(quantity="4.2500"), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.confirm_quality(first).status_code, 200)
        second_line = copy.copy(self.purchase_line)
        second_line.pk = uuid.uuid4()
        second_line._state.adding = True
        second_line.line_number = 2
        second_line.source_bom_line_id_snapshot = uuid.uuid4()
        second_line.actual_purchase_quantity = Decimal("3.0000")
        second_line.required_quantity = Decimal("3.0000")
        second_line.save(force_insert=True)
        second_payload = self.payload(quantity="1.0000", expected="3.0000")
        second_payload["items"][0]["purchase_order_line_id"] = str(second_line.pk)
        second = self.client.post("/api/v1/material-inventory/receipts/", second_payload, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(self.confirm_quality(second).status_code, 200)

        inventory = self.client.get("/api/v1/material-inventory/")
        self.assertEqual(inventory.status_code, 200, inventory.data)
        self.assertEqual(inventory.data["count"], 1)
        self.assertEqual(inventory.data["results"][0]["inventory_quantity"], Decimal("5.2500"))
        self.assertEqual(inventory.data["results"][0]["inbound_count"], 2)

    def test_over_receipt_rolls_back_and_stale_remaining_returns_conflict(self):
        over = self.client.post("/api/v1/material-inventory/batch-receipts/", self.payload(quantity="11.0000"), format="json")
        self.assertEqual(over.status_code, 400, over.data)
        self.assertEqual(MaterialInbound.objects.count(), 0)
        first = self.client.post("/api/v1/material-inventory/receipts/", self.payload(), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        stale = self.client.post("/api/v1/material-inventory/receipts/", self.payload(quantity="1.0000", expected="10.5000"), format="json")
        self.assertEqual(stale.status_code, 409, stale.data)

    def test_future_date_is_rejected(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        response = self.client.post("/api/v1/material-inventory/receipts/", self.payload(inbound_date=future), format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_receipt_date_before_short_year_range_returns_400_without_writes(self):
        self.use_general_material()
        counters = list(DailyBusinessNumberCounter.objects.order_by("pk").values())
        response = self.client.post(
            "/api/v1/material-inventory/receipts/", self.payload(inbound_date="1999-12-31"), format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("2000–2099", str(response.data))
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(MaterialInboundLine.objects.exists())
        self.assertFalse(MaterialStockMovement.objects.exists())
        self.assertEqual(list(DailyBusinessNumberCounter.objects.order_by("pk").values()), counters)

    def test_only_purchasing_order_can_receive_material(self):
        for order_status in (PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.COMPLETED):
            self.order.status = order_status
            self.order.save(update_fields=["status", "updated_at"])
            eligible = self.client.get(
                "/api/v1/material-inventory/eligible-purchase-orders/",
                {"purchase_order_id": str(self.order.pk)},
            )
            self.assertEqual(eligible.status_code, 200, eligible.data)
            self.assertEqual(eligible.data["data"], [])
            response = self.client.post(
                "/api/v1/material-inventory/receipts/", self.payload(), format="json",
            )
            self.assertEqual(response.status_code, 409, response.data)
            self.assertEqual(MaterialInbound.objects.count(), 0)

    def test_superuser_without_employee_is_rejected_before_inventory_write(self):
        user = get_user_model().objects.create_superuser(
            username="inventory_superuser_without_employee",
            password="unused-test-password",
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.post("/api/v1/material-inventory/receipts/", self.payload(), format="json")

        self.assertEqual(response.status_code, 403, response.data)

    def test_manual_receipt_is_confirmed_immediately_and_requires_remark(self):
        material = RawMaterialInformation.objects.filter(
            archived_at__isnull=True,
            category__status="ACTIVE",
            unit__status="ACTIVE",
        ).select_related("category", "unit").first()
        self.assertIsNotNone(material)
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "inbound_date": timezone.localdate().isoformat(),
            "remark": "盘点发现的额外材料",
            "items": [{
                "raw_material_id": str(material.pk),
                "zone_id": self.zone_id,
                "received_quantity": "2.5000",
            }],
        }

        missing_remark = self.client.post(
            "/api/v1/material-inventory/manual-receipts/",
            {**payload, "remark": ""},
            format="json",
        )
        self.assertEqual(missing_remark.status_code, 400, missing_remark.data)

        missing_date = self.client.post(
            "/api/v1/material-inventory/manual-receipts/",
            {key: value for key, value in payload.items() if key != "inbound_date"},
            format="json",
        )
        self.assertEqual(missing_date.status_code, 400, missing_date.data)

        response = self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], MaterialInboundStatus.CONFIRMED)
        self.assertEqual(response.data["data"]["source_type"], "MANUAL")
        inbound = MaterialInbound.objects.get(pk=response.data["data"]["id"])
        line = inbound.lines.get()
        self.assertIsNone(inbound.purchase_order_id)
        self.assertIsNone(line.purchase_order_line_id)
        self.assertEqual(line.raw_material_information_id, material.pk)
        self.assertEqual(line.accepted_quantity, Decimal("2.5000"))
        self.assertEqual(self.client.get("/api/v1/material-inventory/quality-batches/").data["data"], [])
        self.assertEqual(self.client.get("/api/v1/material-inventory/").data["count"], 1)

        duplicate = self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")
        self.assertEqual(duplicate.status_code, 201, duplicate.data)
        self.assertEqual(duplicate.data["data"]["id"], response.data["data"]["id"])
        self.assertEqual(MaterialInbound.objects.count(), 1)

        conflicting_payload = copy.deepcopy(payload)
        conflicting_payload["remark"] = "同一提交标识的不同内容"
        conflict = self.client.post(
            "/api/v1/material-inventory/manual-receipts/", conflicting_payload, format="json",
        )
        self.assertEqual(conflict.status_code, 409, conflict.data)

    def test_procurement_inbound_list_contains_workflow_orders_and_quality_can_view(self):
        self.order.status = PurchaseOrderStatus.PURCHASING
        self.order.save(update_fields=["status", "updated_at"])
        response = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([str(row["id"]) for row in response.data["data"]], [str(self.order.pk)])
        self.assertEqual(response.data["data"][0]["workflow_status"], "PENDING_RECEIPT")
        self.assertEqual(response.data["data"][0]["workflow_status_display"], "等待入库")

        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=["quality_confirm_material", "view_productiontask"],
        ))
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache
        quality_response = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(quality_response.status_code, 200, quality_response.data)

    def test_quality_return_is_deducted_before_inventory_and_frees_remaining_quantity(self):
        received = self.client.post(
            "/api/v1/material-inventory/receivings/",
            self.payload(quantity="4.2500"),
            format="json",
        )
        self.assertEqual(received.status_code, 201, received.data)
        pending = self.client.get("/api/v1/material-inventory/quality-batches/")
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual(len(pending.data["data"]), 1)

        confirmed = self.confirm_quality(received, return_quantity="1.2500", quality_remark="表面损伤，退回供应商")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["data"]["total_received_quantity"], "4.2500")
        self.assertEqual(confirmed.data["data"]["total_return_quantity"], "1.2500")
        self.assertEqual(confirmed.data["data"]["total_accepted_quantity"], "3.0000")

        inventory = self.client.get("/api/v1/material-inventory/")
        self.assertEqual(inventory.data["results"][0]["inventory_quantity"], Decimal("3.0000"))
        eligible = self.client.get(
            "/api/v1/material-inventory/eligible-lines/",
            {"purchase_order_id": str(self.order.pk)},
        )
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(eligible.data["data"], [])
        blocked_replacement = self.client.post(
            "/api/v1/material-inventory/receivings/",
            self.payload(quantity="1.2500", expected="7.5000"),
            format="json",
        )
        self.assertEqual(blocked_replacement.status_code, 409, blocked_replacement.data)
        self.assertIn("等待确认退货或退货完成", str(blocked_replacement.data))

        sibling_line = copy.copy(self.purchase_line)
        sibling_line.pk = uuid.uuid4()
        sibling_line._state.adding = True
        sibling_line.line_number = 2
        sibling_line.source_bom_line_id_snapshot = uuid.uuid4()
        sibling_line.save(force_insert=True)
        sibling_payload = self.payload(quantity="1.0000", expected="10.5000")
        sibling_payload["items"][0]["purchase_order_line_id"] = str(sibling_line.pk)
        blocked_sibling = self.client.post(
            "/api/v1/material-inventory/receivings/",
            sibling_payload,
            format="json",
        )
        self.assertEqual(blocked_sibling.status_code, 409, blocked_sibling.data)
        self.assertIn("等待确认退货或退货完成", str(blocked_sibling.data))

        status_before_confirmation = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(status_before_confirmation.data["data"][0]["workflow_status"], "PENDING_PROCUREMENT_CONFIRMATION")
        self.assertEqual(status_before_confirmation.data["data"][0]["return_status"], "QUALITY_GENERATED")
        PurchaseReturn.objects.update(status=PurchaseReturnStatus.PROCUREMENT_CONFIRMED)
        status_after_confirmation = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(status_after_confirmation.data["data"][0]["workflow_status"], "PENDING_RETURN")
        self.assertEqual(status_after_confirmation.data["data"][0]["return_status"], "PROCUREMENT_CONFIRMED")

        PurchaseReturn.objects.update(status=PurchaseReturnStatus.COMPLETED)
        eligible_after_completion = self.client.get(
            "/api/v1/material-inventory/eligible-lines/",
            {"purchase_order_id": str(self.order.pk)},
        )
        self.assertEqual(eligible_after_completion.data["data"][0]["remaining_quantity"], "7.5000")
        replacement = self.client.post(
            "/api/v1/material-inventory/receivings/",
            self.payload(quantity="1.2500", expected="7.5000"),
            format="json",
        )
        self.assertEqual(replacement.status_code, 201, replacement.data)
        status_before_completion = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(status_before_completion.data["data"][0]["workflow_status"], "PENDING_QUALITY")
        MaterialInboundLine.objects.filter(inbound_id=replacement.data["data"]["id"]).delete()
        MaterialInbound.objects.filter(pk=replacement.data["data"]["id"]).delete()
        status_after_completion = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/")
        self.assertEqual(status_after_completion.data["data"][0]["workflow_status"], "PARTIAL_RECEIVED")
        self.assertEqual(status_after_completion.data["data"][0]["return_status"], "COMPLETED")

    def test_quality_confirmation_rejects_over_return_and_is_idempotent(self):
        received = self.client.post("/api/v1/material-inventory/receivings/", self.payload(), format="json")
        over = self.confirm_quality(received, return_quantity="5.0000")
        self.assertEqual(over.status_code, 400, over.data)
        self.assertEqual(MaterialInbound.objects.get().status, MaterialInboundStatus.PENDING_QUALITY)
        confirmed = self.confirm_quality(received)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        duplicate = self.confirm_quality(received)
        self.assertEqual(duplicate.status_code, 409, duplicate.data)

    def test_inbound_details_filters_date_and_displayed_material_snapshot(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        received = self.client.post(
            "/api/v1/material-inventory/receivings/",
            self.payload(inbound_date=yesterday), format="json",
        )
        self.assertEqual(received.status_code, 201, received.data)
        endpoint = "/api/v1/material-inventory/inbound-details/"
        self.assertEqual(self.client.get(endpoint).data["data"], [])
        confirmed = self.confirm_quality(received, return_quantity="0.0001")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        MaterialInboundLine.objects.filter(inbound_id=received.data["data"]["id"]).update(
            part_name_snapshot="", raw_material_snapshot="", material_snapshot="备用物料名称",
            purchase_order_number_snapshot="历史采购单快照",
        )
        for keyword in ("备用物料名称", "历史采购单快照"):
            response = self.client.get(endpoint, {"q": keyword, "inbound_date": yesterday})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["data"]), 1)
            self.assertEqual(response.data["data"][0]["lines"][0]["accepted_quantity"], "4.2499")
        exact = self.client.get(endpoint, {
            "zone_id": self.zone_id,
            "section_type": self.purchase_line.section_type_snapshot,
            "section_title": self.purchase_line.section_title_snapshot,
            "category": self.purchase_line.category_snapshot,
            "material": "备用物料名称",
            "part_name": "",
            "specification": self.purchase_line.specification_snapshot,
            "raw_material": "",
            "unit": self.purchase_line.source_unit_text,
        })
        self.assertEqual(len(exact.data["data"]), 1)
        self.assertEqual(self.client.get(endpoint, {"specification": "不存在的规格"}).data["data"], [])
        self.assertEqual(self.client.get(endpoint, {"inbound_date": timezone.localdate().isoformat()}).data["data"], [])
        self.assertEqual(self.client.get(endpoint, {"inbound_date": "2026-02-30"}).status_code, 400)
