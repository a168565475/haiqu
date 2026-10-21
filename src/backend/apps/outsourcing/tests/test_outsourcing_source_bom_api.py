import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomSectionType, BomStatus
from apps.customers.models import CustomerAccount
from apps.files.models import BusinessFile, FileScanStatus
from apps.inventory.models import (
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockBalance,
    MaterialStockQuality,
    SemiFinishedStockBalance,
    Warehouse,
    WarehouseType,
    WarehouseZone,
)
from apps.inventory.stock_services import credit_confirmed_inbound_line, credit_material_stock, debit_material_stock
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.production_scheduling.models import (
    ProductionSchedule,
    ProductionScheduleProduct,
    ProductionScheduleProductCraft,
)
from apps.production_tasks.models import (
    DeliveryMethod,
    OrderSource,
    ProductionTask,
    ProductionTaskProduct,
    ProductionTaskStatus,
)
from apps.reference_data.models import (
    Currency,
    FabricMaterial,
    ProductCategory,
    ProductColor,
    ProductItem,
    ProductionUnit,
)
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus, Workshop

from ..models import (
    OutsourcingFactory,
    OutsourcingFactoryAllocation,
    OutsourcingFactoryCraft,
    OutsourcingDispatch,
    OutsourcingDispatchLine,
    OutsourcingMaterialItem,
    OutsourcingOrder,
    OutsourcingOrderStatus,
    OutsourcingProcessingItem,
    OutsourcingReturn,
)


class OutsourcingSourceBomApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="outsourcing-bom-user", is_staff=True, is_superuser=True,
        )
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="OUTSOURCING-BOM-USER",
            display_name="委外 BOM 测试员",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        currency, _ = Currency.objects.get_or_create(
            code="CNY",
            defaults={"numeric_code": "156", "chinese_name": "人民币"},
        )
        category = ProductCategory.objects.create(category_name="委外 BOM 测试成品", item_type="FINISHED")
        unit = ProductionUnit.objects.create(unit_code="OBM-SET", unit_name="委外测试套")
        self.processing_unit = ProductionUnit.objects.create(unit_code="OBM-PC", unit_name="委外测试片")
        item = ProductItem.objects.create(item_number="OBM-ITEM", category=category)
        product = ProductInformation.objects.create(
            product_number="OBM-PRODUCT-001",
            product_code="OBM-CODE-001",
            category=category,
            product_name="委外测试椅",
            specification="600×500",
            unit=unit,
            product_item=item,
            scale="REGULAR",
        )
        color = ProductColor.objects.create(
            color_card="OBM", color_code="001", color_name="卡其色",
        )
        customer = CustomerAccount.objects.create(
            account_code="OBM-CUSTOMER", account_name="委外 BOM 测试客户", primary_country_code="CN",
        )
        today = timezone.localdate()
        task = ProductionTask.objects.create(
            task_number="HT-OBM-001",
            contract_number="OBM-CONTRACT-001",
            order_source=OrderSource.NEW,
            order_number="OBM-ORDER-001",
            customer_account=customer,
            order_date=today,
            delivery_date=today + timedelta(days=30),
            salesperson=self.employee,
            currency=currency,
            includes_tax=True,
            order_tolerance_percent=Decimal("0"),
            is_repeat_order=False,
            preproduction_sample_required=False,
            delivery_method=DeliveryMethod.SINGLE,
            status=ProductionTaskStatus.READY,
            planned_start_date=today + timedelta(days=3),
            planned_end_date=today + timedelta(days=20),
            created_by_employee=self.employee,
        )
        self.product_line = ProductionTaskProduct.objects.create(
            production_task=task,
            line_number=1,
            product=product,
            product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            item_number_snapshot=item.item_number,
            product_name_snapshot=product.product_name,
            specification_snapshot=product.specification,
            product_color=color,
            color_card_snapshot=color.color_card,
            color_name_snapshot=color.color_name,
            color_code_snapshot=color.color_code,
            quantity=100,
            unit=unit,
            currency=currency,
            unit_price=Decimal("10"),
            total_amount=Decimal("1000"),
            exchange_rate=Decimal("1"),
        )
        schedule = ProductionSchedule.objects.create(
            schedule_number="PC-OBM-001",
            production_task=task,
            source_snapshot={},
            source_revision_hash="a" * 64,
            client_request_id=uuid.uuid4(),
            request_payload_hash="b" * 64,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.schedule_product = ProductionScheduleProduct.objects.create(
            schedule=schedule,
            product_line=self.product_line,
            line_number=1,
            planned_quantity=80,
            source_quantity_snapshot=100,
            unit=unit,
            unit_name_snapshot=unit.unit_name,
            material_inbound_date=today + timedelta(days=1),
            metal_return_date=today + timedelta(days=5),
            sewing_return_date=today + timedelta(days=8),
            finished_inbound_date=today + timedelta(days=12),
            product_snapshot={
                "product_number": product.product_number,
                "item_number": item.item_number,
                "product_name": product.product_name,
                "specification": product.specification,
                "color_name": color.color_name,
            },
            source_revision_hash="c" * 64,
        )
        self.sewing = self.create_craft("委外测试车缝", OutsourcingCode.SEWING)
        self.screen_printing = self.create_craft("委外测试丝印", OutsourcingCode.SCREEN_PRINTING)
        self.spray = self.create_craft("委外测试喷塑", OutsourcingCode.POWDER_COATING)
        for craft in (self.sewing, self.screen_printing, self.spray):
            ProductionScheduleProductCraft.objects.create(
                schedule_product=self.schedule_product,
                craft=craft,
                craft_type_snapshot=CraftType.EXTERNAL,
                craft_name_snapshot=craft.name,
            )
        self.bom = Bom.objects.create(
            bom_number="BOM-OBM-002",
            production_task=task,
            product_line=self.product_line,
            version_number=2,
            creation_method=BomCreationMethod.BLANK,
            product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            product_name_snapshot=product.product_name,
            specification_snapshot=product.specification,
            order_quantity=100,
            source_quantity=100,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.cutting = self.create_line(
            "裁剪明细", BomSectionType.FABRIC, "椅面裁片", "600×500",
            self.processing_unit.unit_name, "2", "200",
        )
        self.fabric = self.create_line("面料类", BomSectionType.FABRIC, "牛津布", "600D", "米", "1.5", "150")
        self.auxiliary = self.create_line("辅料类", BomSectionType.FABRIC, "包边带", "25mm", "米", "2", "200")
        self.profile = self.create_line("管材类", BomSectionType.PROFILE, "前脚管", "φ25×1.2", "支", "4", "400")
        self.profile.material = "铁"
        self.profile.branch_count = "25"
        self.profile.save(update_fields=["material", "branch_count"])
        self.hardware = self.create_line("五金件", BomSectionType.ACCESSORY, "铆钉", "M6", "个", "8", "800")
        self.hardware.total_consumption = ""
        self.hardware.save(update_fields=["total_consumption"])

    def create_craft(self, name, outsourcing_code):
        return Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name=name,
            outsourcing_code=outsourcing_code,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )

    def create_line(self, title, section_type, name, specification, unit, unit_consumption, total):
        section = BomSection.objects.create(
            bom=self.bom,
            line_number=BomSection.objects.filter(bom=self.bom).count() + 1,
            section_type=section_type,
            title=title,
        )
        return BomLine.objects.create(
            section=section,
            line_number=1,
            part_name=name,
            specification=specification,
            unit=unit,
            unit_consumption=unit_consumption,
            total_consumption=total,
            raw_values={
                "cutting_category": "委外布面" if title == "裁剪明细" else "",
                "cutting_color": "卡其色" if title == "裁剪明细" else "",
                "tube_coating_color": "哑黑" if title == "管材类" else "",
                "hardware_material_number": "HW-001" if title == "五金件" else "",
            },
        )

    def get_bom(self, craft):
        return self.client.get(
            f"/api/v1/outsourcing-orders/source-products/{self.schedule_product.pk}/bom/",
            {"craft_id": str(craft.pk)},
            HTTP_HOST="localhost",
        )

    def test_sewing_returns_latest_product_bom_cutting_and_fabric_materials_without_writes(self):
        before = (
            OutsourcingOrder.objects.count(),
            OutsourcingProcessingItem.objects.count(),
            OutsourcingMaterialItem.objects.count(),
        )
        response = self.get_bom(self.sewing)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["bom"]["bom_number"], "BOM-OBM-002")
        self.assertEqual(data["processing_section_label"], "裁剪明细")
        self.assertEqual([row["part_name"] for row in data["processing_items"]], ["椅面裁片"])
        self.assertEqual(data["processing_items"][0]["category"], "委外布面")
        self.assertEqual(data["processing_items"][0]["color"], "卡其色")
        self.assertEqual(data["processing_items"][0]["required_quantity"], Decimal("200.0000"))
        self.assertEqual(data["processing_items"][0]["unit"], self.processing_unit.unit_name)
        self.assertEqual({row["category"] for row in data["material_items"]}, {"FABRIC", "AUXILIARY"})
        self.assertEqual(data["material_items"][0]["reference_required_quantity"], Decimal("150"))
        self.assertEqual(before, (
            OutsourcingOrder.objects.count(),
            OutsourcingProcessingItem.objects.count(),
            OutsourcingMaterialItem.objects.count(),
        ))

    def test_spray_returns_profile_processing_and_profile_hardware_materials(self):
        response = self.get_bom(self.spray)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["processing_section_label"], "管材类")
        self.assertEqual([row["part_name"] for row in data["processing_items"]], ["前脚管"])
        self.assertEqual(data["processing_items"][0]["category"], "管材类")
        self.assertEqual(data["processing_items"][0]["material"], "铁")
        self.assertEqual(data["processing_items"][0]["color"], "哑黑")
        self.assertEqual(data["processing_items"][0]["required_quantity"], Decimal("400.0000"))
        self.assertEqual(data["processing_items"][0]["unit"], "支")
        self.assertEqual(data["processing_items"][0]["dispatched_quantity"], 0)
        self.assertEqual(data["processing_items"][0]["inbound_quantity"], Decimal("400.0000"))
        self.assertEqual(data["processing_items"][0]["inbound_unit"], "支")
        self.assertEqual({row["category"] for row in data["material_items"]}, {"PROFILE", "HARDWARE"})
        profile = next(row for row in data["material_items"] if row["category"] == "PROFILE")
        self.assertEqual(profile["reference_required_quantity"], Decimal("400.0000"))
        self.assertEqual(profile["default_issue_quantity"], Decimal("400.0000"))
        self.assertEqual(profile["quantity_source_field"], "unit_consumption*order_quantity")
        self.assertEqual(profile["quantity_source_text"], "4 × 100")
        self.assertEqual(profile["quantity_parse_status"], "READY")
        self.assertEqual(profile["procurement_required_quantity"], Decimal("25.0000"))
        self.assertEqual(profile["procurement_source_field"], "branch_count")
        self.assertEqual(profile["procurement_source_text"], "25")
        hardware = next(row for row in data["material_items"] if row["category"] == "HARDWARE")
        self.assertEqual(hardware["material_number"], "HW-001")
        self.assertEqual(hardware["reference_required_quantity"], Decimal("800.0000"))
        self.assertEqual(hardware["default_issue_quantity"], Decimal("800.0000"))
        self.assertEqual(hardware["quantity_source_field"], "unit_consumption*order_quantity")
        self.assertEqual(hardware["quantity_source_text"], "8 × 100")
        self.assertEqual(hardware["quantity_parse_status"], "READY")
        self.assertEqual(hardware["procurement_required_quantity"], Decimal("800.0000"))
        self.assertEqual(hardware["procurement_source_field"], "unit_consumption*order_quantity")

    def test_rejects_craft_not_linked_to_schedule_product(self):
        unlinked = self.create_craft("委外测试未关联裁剪", OutsourcingCode.CUTTING)
        response = self.get_bom(unlinked)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不包含所选厂外工艺", str(response.data))


class OutsourcingOrderWriteApiTests(OutsourcingSourceBomApiTests):
    def setUp(self):
        super().setUp()
        self.factory = OutsourcingFactory.objects.create(
            factory_number="JG-ORDER-TEST",
            name="委外测试加工厂",
            processing_type="车缝加工",
            contact_name="测试联系人",
            contact_phone="13800000000",
            address="测试地址",
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        OutsourcingFactoryCraft.objects.create(
            factory=self.factory,
            craft=self.sewing,
            craft_name_snapshot=self.sewing.name,
        )
        OutsourcingFactoryCraft.objects.create(
            factory=self.factory,
            craft=self.screen_printing,
            craft_name_snapshot=self.screen_printing.name,
        )
        OutsourcingFactoryCraft.objects.create(
            factory=self.factory,
            craft=self.spray,
            craft_name_snapshot=self.spray.name,
        )
        ProductionUnit.objects.get_or_create(
            unit_name="支",
            defaults={"unit_code": "OBM-TUBE"},
        )

    def payload(self, *, request_id=None, quantity=80, delivery_offset=20):
        return {
            "client_request_id": str(request_id or uuid.uuid4()),
            "schedule_id": str(self.schedule_product.schedule_id),
            "craft_id": str(self.sewing.pk),
            "delivery_date": str(timezone.localdate() + timedelta(days=delivery_offset)),
            "remark": "真实新增测试",
            "products": [{
                "schedule_product_id": str(self.schedule_product.pk),
                "bom_id": str(self.bom.pk),
                "processing_items": [{
                    "bom_line_id": str(self.cutting.pk),
                    "quantity": str(quantity),
                    "processing_requirement": "按样品车缝",
                    "allocations": [{
                        "factory_id": str(self.factory.pk),
                        "input_quantity": str(quantity),
                        "allocated_quantity": str(quantity),
                        "unit_price": "2.5000",
                        "remark": "",
                    }],
                }],
                "materials": [{
                    "bom_line_id": str(self.fabric.pk),
                    "processing_bom_line_id": str(self.cutting.pk),
                    "factory_id": str(self.factory.pk),
                    "planned_issue_quantity": "120.0000",
                    "difference_reason": "",
                    "remark": "",
                }],
            }],
        }

    def create_order(self, payload):
        return self.client.post(
            "/api/v1/outsourcing-orders/",
            payload,
            format="json",
            HTTP_HOST="localhost",
        )

    def current_fabric_payload(self):
        """仅为编号验收用例补齐已确认 BOM、米制投入和套制产出。"""
        self.bom.status = BomStatus.VERIFIED
        self.bom.save(update_fields=["status", "updated_at"])
        self.processing_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name="套", defaults={"unit_code": "OUT-CURRENT-SET"},
        )
        if not hasattr(self, "raw_material"):
            material_unit, _ = ProductionUnit.objects.get_or_create(
                unit_name="米", defaults={"unit_code": "OUT-CURRENT-M"},
            )
            category, _ = ProductCategory.objects.get_or_create(
                category_name="面料", defaults={"item_type": "MATERIAL"},
            )
            self.raw_material = RawMaterialInformation.objects.create(
                material_number="OUT-CURRENT-FABRIC", item_type="MATERIAL",
                category=category, material_name="编号验收面料", specification="600D",
                material="牛津布", unit=material_unit,
            )
        self.fabric.raw_values = {
            **(self.fabric.raw_values or {}),
            "source_inventory_material_id": str(self.raw_material.pk),
        }
        self.fabric.save(update_fields=["raw_values", "updated_at"])
        self.cutting.fabric_source_line = self.fabric
        self.cutting.fabric_meters_per_set = Decimal("1.5")
        self.cutting.cutting_pieces_per_set = 2
        self.cutting.fabric_meters_per_piece = Decimal("0.75")
        self.cutting.cutting_sets_per_product = 1
        self.cutting.unit = self.processing_unit.unit_name
        self.cutting.save(update_fields=[
            "fabric_source_line", "fabric_meters_per_set", "cutting_pieces_per_set",
            "fabric_meters_per_piece", "cutting_sets_per_product", "unit", "updated_at",
        ])
        payload = self.payload()
        payload["products"][0]["processing_items"][0]["allocations"][0]["input_quantity"] = None
        return payload

    def spray_payload(self):
        return {
            "client_request_id": str(uuid.uuid4()),
            "schedule_id": str(self.schedule_product.schedule_id),
            "craft_id": str(self.spray.pk),
            "delivery_date": str(timezone.localdate() + timedelta(days=20)),
            "remark": "喷塑换算测试",
            "products": [{
                "schedule_product_id": str(self.schedule_product.pk),
                "bom_id": str(self.bom.pk),
                "processing_items": [{
                    "bom_line_id": str(self.profile.pk),
                    "quantity": "400.0000",
                    "processing_requirement": "按 BOM 实物总需求喷塑",
                    "allocations": [{
                        "factory_id": str(self.factory.pk),
                        "input_quantity": "400.0000",
                        "allocated_quantity": "400.0000",
                        "unit_price": "1.0000",
                        "remark": "",
                    }],
                }],
                "materials": [{
                    "bom_line_id": str(self.profile.pk),
                    "processing_bom_line_id": str(self.profile.pk),
                    "factory_id": str(self.factory.pk),
                    "planned_issue_quantity": "400.0000",
                    "difference_reason": "",
                    "remark": "",
                }],
            }],
        }

    def test_create_persists_nested_order_without_inventory_write(self):
        response = self.create_order(self.current_fabric_payload())
        self.assertEqual(response.status_code, 201, response.data)
        order = OutsourcingOrder.objects.get(pk=response.data["data"]["id"])
        self.assertRegex(order.order_number, rf"^WF{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        self.assertEqual(order.status, OutsourcingOrderStatus.PENDING_DISPATCH)
        self.assertEqual(order.products.count(), 1)
        self.assertEqual(OutsourcingProcessingItem.objects.filter(order_product__order=order).count(), 1)
        self.assertEqual(OutsourcingFactoryAllocation.objects.filter(processing_item__order_product__order=order).count(), 1)
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order=order)
        processing = OutsourcingProcessingItem.objects.get(order_product__order=order)
        self.assertEqual(processing.quantity, Decimal("80.0000"))
        self.assertEqual(processing.unit_id, self.processing_unit.pk)
        self.assertEqual(material.planned_issue_quantity, Decimal("120.0000"))
        self.assertEqual(response.data["data"]["planned_amount"], "200.0000")
        allocation = response.data["data"]["products"][0]["processing_items"][0]["allocations"][0]
        self.assertEqual(allocation["unit_price"], "2.5000")
        self.assertEqual(allocation["materials"][0]["planned_issue_quantity"], "120.0000")
        self.assertIsNone(response.data["data"]["dispatch"])

    def test_create_persists_procurement_converted_material_total(self):
        response = self.create_order(self.spray_payload())
        self.assertEqual(response.status_code, 201, response.data)
        material = OutsourcingMaterialItem.objects.get(
            allocation__processing_item__order_product__order_id=response.data["data"]["id"]
        )
        self.assertEqual(material.reference_required_quantity, Decimal("400.0000"))
        self.assertEqual(material.planned_issue_quantity, Decimal("400.0000"))
        self.assertEqual(material.consumption_basis, "BOM_USAGE_X_ORDER")
        self.assertEqual(material.material_snapshot["quantity_source_text"], "4 × 100")
        self.assertEqual(material.material_snapshot["procurement_required_quantity"], "25.0000")
        self.assertEqual(material.material_snapshot["procurement_source_text"], "25")

    def test_create_is_idempotent_and_rejects_changed_payload_for_same_request_id(self):
        request_id = uuid.uuid4()
        payload = self.payload(request_id=request_id)
        first = self.create_order(payload)
        second = self.create_order(payload)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["data"]["id"], second.data["data"]["id"])
        self.assertEqual(OutsourcingOrder.objects.filter(client_request_id=request_id).count(), 1)

        changed = self.payload(request_id=request_id, delivery_offset=21)
        conflict = self.create_order(changed)
        self.assertEqual(conflict.status_code, 409, conflict.data)

    def test_quota_is_reserved_then_released_by_pending_dispatch_cancel(self):
        first = self.create_order(self.payload(quantity=80))
        self.assertEqual(first.status_code, 201, first.data)
        blocked = self.create_order(self.payload(quantity=121))
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertIn("最多可外发 120.0000 委外测试片", str(blocked.data))

        cancel = self.client.post(
            f"/api/v1/outsourcing-orders/{first.data['data']['id']}/cancel/",
            {"reason": "重新分配加工厂"},
            format="json",
            HTTP_IF_MATCH=first.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(cancel.status_code, 200, cancel.data)
        self.assertEqual(cancel.data["data"]["status"], OutsourcingOrderStatus.CANCELLED)

        repeated_cancel = self.client.post(
            f"/api/v1/outsourcing-orders/{first.data['data']['id']}/cancel/",
            {"reason": "重复作废"},
            format="json",
            HTTP_IF_MATCH=cancel.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(repeated_cancel.status_code, 409, repeated_cancel.data)

        replacement = self.create_order(self.payload(quantity=200))
        self.assertEqual(replacement.status_code, 201, replacement.data)

    def test_processing_quota_is_independent_between_crafts(self):
        sewing = self.create_order(self.payload(quantity=200))
        self.assertEqual(sewing.status_code, 201, sewing.data)

        source = self.get_bom(self.screen_printing)
        self.assertEqual(source.status_code, 200, source.data)
        candidate = source.data["data"]["processing_items"][0]
        self.assertEqual(candidate["outsourced_quantity"], 0)
        self.assertEqual(candidate["available_quantity"], Decimal("200.0000"))

        screen_printing_payload = self.payload(quantity=200)
        screen_printing_payload["craft_id"] = str(self.screen_printing.pk)
        screen_printing = self.create_order(screen_printing_payload)
        self.assertEqual(screen_printing.status_code, 201, screen_printing.data)

    def test_processing_candidate_separates_reserved_and_dispatched_quantity(self):
        created = self.create_order(self.payload(quantity=40))
        self.assertEqual(created.status_code, 201, created.data)

        pending_source = self.get_bom(self.sewing)
        self.assertEqual(pending_source.status_code, 200, pending_source.data)
        pending_candidate = pending_source.data["data"]["processing_items"][0]
        self.assertEqual(pending_candidate["outsourced_quantity"], 40)
        self.assertEqual(pending_candidate["dispatched_quantity"], 0)
        self.assertEqual(pending_candidate["available_quantity"], Decimal("160.0000"))

        OutsourcingOrder.objects.filter(pk=created.data["data"]["id"]).update(
            status=OutsourcingOrderStatus.PROCESSING,
        )
        dispatched_source = self.get_bom(self.sewing)
        self.assertEqual(dispatched_source.status_code, 200, dispatched_source.data)
        dispatched_candidate = dispatched_source.data["data"]["processing_items"][0]
        self.assertEqual(dispatched_candidate["outsourced_quantity"], 40)
        self.assertEqual(dispatched_candidate["dispatched_quantity"], 40)
        self.assertEqual(dispatched_candidate["available_quantity"], Decimal("160.0000"))

    def test_pending_dispatch_order_can_be_physically_deleted(self):
        created = self.create_order(self.current_fabric_payload())
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        self.assertTrue(created.data["data"]["can_delete"])

        deleted = self.client.delete(
            f"/api/v1/outsourcing-orders/{order_id}/",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )

        self.assertEqual(deleted.status_code, 204, getattr(deleted, "data", None))
        self.assertFalse(OutsourcingOrder.objects.filter(pk=order_id).exists())
        self.assertFalse(OutsourcingProcessingItem.objects.filter(order_product__order_id=order_id).exists())
        self.assertTrue(AuditLog.objects.filter(
            object_type="OUTSOURCING_ORDER",
            object_id=order_id,
            action="DELETED",
        ).exists())
        replacement = self.create_order(self.current_fabric_payload())
        self.assertEqual(replacement.status_code, 201, replacement.data)
        prefix = f"WF{timezone.localdate():%y%m%d}"
        self.assertEqual(replacement.data["data"]["order_number"],
            f"{prefix}{int(created.data['data']['order_number'][len(prefix):]) + 1:03d}")

    def test_order_cannot_be_deleted_after_dispatch_state(self):
        created = self.create_order(self.payload())
        self.assertEqual(created.status_code, 201, created.data)
        order = OutsourcingOrder.objects.get(pk=created.data["data"]["id"])
        order.status = OutsourcingOrderStatus.PROCESSING
        order.save(update_fields=["status", "updated_at"])
        refreshed = self.client.get(
            f"/api/v1/outsourcing-orders/{order.pk}/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        self.assertFalse(refreshed.data["data"]["can_delete"])

        deleted = self.client.delete(
            f"/api/v1/outsourcing-orders/{order.pk}/",
            HTTP_IF_MATCH=refreshed.headers["ETag"],
            HTTP_HOST="localhost",
        )

        self.assertEqual(deleted.status_code, 409, deleted.data)
        self.assertTrue(OutsourcingOrder.objects.filter(pk=order.pk).exists())

    def test_detail_hides_cancel_capability_without_cancel_permission(self):
        created = self.create_order(self.payload())
        self.assertEqual(created.status_code, 201, created.data)
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="outsourcing",
            codename="view_outsourcingorder",
        ))
        if hasattr(self.user, "_perm_cache"):
            del self.user._perm_cache

        response = self.client.get(
            f"/api/v1/outsourcing-orders/{created.data['data']['id']}/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["data"]["can_cancel"])
        self.assertFalse(response.data["data"]["can_delete"])
        self.assertEqual(
            response.data["data"]["production_task_id"],
            str(self.product_line.production_task_id),
        )
        self.assertEqual(
            response.data["data"]["customer_name"],
            self.product_line.production_task.customer_account.account_name,
        )
        self.assertEqual(
            response.data["data"]["order_date"],
            self.product_line.production_task.order_date.isoformat(),
        )
        self.assertEqual(
            response.data["data"]["products"][0]["unit_name"],
            self.product_line.unit.unit_name,
        )
        self.assertIsNone(response.data["data"]["products"][0]["image_file_id"])

    def test_product_image_is_available_with_outsourcing_view_permission_only(self):
        created = self.create_order(self.payload())
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image_path = Path(media_root) / "outsourcing-test-product.png"
            image_bytes = b"\x89PNG\r\n\x1a\noutsourcing-test"
            image_path.write_bytes(image_bytes)
            business_file = BusinessFile.objects.create(
                uploaded_by_employee=self.employee,
                original_name="outsourcing-test-product.png",
                storage_key=image_path.name,
                content_type="image/png",
                size_bytes=len(image_bytes),
                scan_status=FileScanStatus.CLEAN,
            )
            self.schedule_product.image_file = business_file
            self.schedule_product.save(update_fields=["image_file", "updated_at"])

            self.user.is_superuser = False
            self.user.save(update_fields=["is_superuser"])
            self.user.user_permissions.set([
                Permission.objects.get(
                    content_type__app_label="outsourcing",
                    codename="view_outsourcingorder",
                )
            ])
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

            detail = self.client.get(
                f"/api/v1/outsourcing-orders/{order_id}/",
                HTTP_HOST="localhost",
            )
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual(detail.data["data"]["products"][0]["image_file_id"], str(business_file.pk))

            response = self.client.get(
                f"/api/v1/outsourcing-orders/{order_id}/product-files/{business_file.pk}/",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(b"".join(response.streaming_content), image_bytes)


class OutsourcingWarehouseFlowApiTests(OutsourcingOrderWriteApiTests):
    def setUp(self):
        super().setUp()
        material_category, _ = ProductCategory.objects.get_or_create(
            category_name="面料",
            defaults={"item_type": "MATERIAL"},
        )
        self.material_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name="米",
            defaults={"unit_code": "OUT-M"},
        )
        self.raw_material = RawMaterialInformation.objects.create(
            material_number="OUT-MAT-001",
            item_type="MATERIAL",
            category=material_category,
            material_name="委外测试面料",
            specification="600D",
            unit=self.material_unit,
            material="牛津布",
            warehouse_number="OUT-MAT-WH",
            warehouse_name="委外材料仓",
        )
        self.fabric_material = FabricMaterial.objects.create(
            material_name="委外测试映射面料",
            inventory_raw_material=self.raw_material,
        )
        self.fabric.raw_values = {"source_fabric_material_id": str(self.fabric_material.pk)}
        self.fabric.save(update_fields=["raw_values", "updated_at"])
        self.bom.status = BomStatus.VERIFIED
        self.bom.save(update_fields=["status", "updated_at"])
        material_warehouse = Warehouse.objects.create(
            warehouse_number="OUTMAT",
            warehouse_name="委外材料仓",
            warehouse_type=WarehouseType.MATERIAL,
            status=RecordStatus.ACTIVE,
        )
        material_zone = WarehouseZone.objects.create(
            warehouse=material_warehouse,
            zone_name="材料一区",
            status=RecordStatus.ACTIVE,
        )
        self.material_balance = MaterialStockBalance.objects.create(
            raw_material=self.raw_material,
            zone=material_zone,
            unit=self.material_unit,
            quality=MaterialStockQuality.AVAILABLE,
            quantity=Decimal("0"),
        )
        self.material_inbound = MaterialInbound.objects.create(
            inbound_number="RK-OUT-001",
            status=MaterialInboundStatus.CONFIRMED,
            received_by_employee=self.employee,
            quality_confirmed_by_employee=self.employee,
            quality_confirmed_at=timezone.now(),
        )
        self.material_inbound_line = MaterialInboundLine.objects.create(
            inbound=self.material_inbound,
            raw_material_information=self.raw_material,
            zone=material_zone,
            received_quantity=Decimal("200"),
            return_quantity=Decimal("0"),
            accepted_quantity=Decimal("200"),
            purchase_order_number_snapshot="MANUAL-OUT-001",
            production_task_number_snapshot=self.product_line.production_task.task_number,
            sales_order_number_snapshot="",
            supplier_number_snapshot="",
            supplier_name_snapshot="",
            bom_number_snapshot=self.bom.bom_number,
            product_name_snapshot=self.product_line.product_name_snapshot,
            section_type_snapshot="FABRIC",
            section_title_snapshot="面料类",
            category_snapshot="面料",
            material_snapshot="牛津布",
            part_name_snapshot="委外测试面料",
            specification_snapshot="600D",
            raw_material_snapshot="牛津布",
            source_unit_text_snapshot=self.material_unit.unit_name,
            purchased_quantity_snapshot=Decimal("200"),
        )
        self.material_balance = credit_confirmed_inbound_line(
            line=self.material_inbound_line,
            actor_employee=self.employee,
        ).balance
        semi_warehouse = Warehouse.objects.create(
            warehouse_number="OUTSEMI",
            warehouse_name="委外半成品仓",
            warehouse_type=WarehouseType.SEMI_FINISHED,
            status=RecordStatus.ACTIVE,
        )
        self.semi_zone = WarehouseZone.objects.create(
            warehouse=semi_warehouse,
            zone_name="回厂一区",
            status=RecordStatus.ACTIVE,
        )
        defective_warehouse = Warehouse.objects.create(
            warehouse_number="OUTDEF",
            warehouse_name="委外不良品仓",
            warehouse_type=WarehouseType.DEFECTIVE,
            status=RecordStatus.ACTIVE,
        )
        self.defective_zone = WarehouseZone.objects.create(
            warehouse=defective_warehouse,
            zone_name="不良一区",
            status=RecordStatus.ACTIVE,
        )

    def dispatch_payload(self, order_id):
        material_item = OutsourcingMaterialItem.objects.get(
            allocation__processing_item__order_product__order_id=order_id
        )
        return {
            "request_id": str(uuid.uuid4()),
            "remark": "仓库按实际批次发料",
            "lines": [{
                "material_item_id": str(material_item.pk),
                "inbound_line_id": str(self.material_inbound_line.pk),
                "source_quantity": "120.0000",
                "material_quantity": "120.0000",
                "conversion_factor": "1.00000000",
                "conversion_evidence": "",
                "match_method": "REFERENCE_ID",
                "match_reason": "",
            }],
        }

    def test_profile_dispatch_uses_bom_total_but_deducts_converted_procurement_quantity(self):
        tube_unit = ProductionUnit.objects.get(unit_name="支")
        material_category, _ = ProductCategory.objects.get_or_create(
            category_name="管材",
            defaults={"item_type": "MATERIAL"},
        )
        tube_material = RawMaterialInformation.objects.create(
            material_number="OUT-TUBE-001",
            item_type="MATERIAL",
            category=material_category,
            material_name="委外测试原料管",
            specification="φ25×1.2",
            unit=tube_unit,
            material="铁",
            warehouse_number="OUT-TUBE-WH",
            warehouse_name="委外材料仓",
        )
        self.profile.raw_values = {
            **(self.profile.raw_values or {}),
            "source_inventory_material_id": str(tube_material.pk),
        }
        self.profile.save(update_fields=["raw_values", "updated_at"])
        tube_balance = MaterialStockBalance.objects.create(
            raw_material=tube_material,
            zone=self.material_balance.zone,
            unit=tube_unit,
            quality=MaterialStockQuality.AVAILABLE,
            quantity=Decimal("0"),
        )
        tube_inbound_line = MaterialInboundLine.objects.create(
            inbound=self.material_inbound,
            raw_material_information=tube_material,
            zone=self.material_balance.zone,
            received_quantity=Decimal("30"),
            return_quantity=Decimal("0"),
            accepted_quantity=Decimal("30"),
            purchase_order_number_snapshot="MANUAL-OUT-TUBE-001",
            production_task_number_snapshot=self.product_line.production_task.task_number,
            sales_order_number_snapshot="",
            supplier_number_snapshot="",
            supplier_name_snapshot="",
            bom_number_snapshot=self.bom.bom_number,
            product_name_snapshot=self.product_line.product_name_snapshot,
            section_type_snapshot="PROFILE",
            section_title_snapshot="管材类",
            category_snapshot="管材",
            material_snapshot="铁",
            part_name_snapshot=self.profile.part_name,
            specification_snapshot=self.profile.specification,
            raw_material_snapshot="铁",
            source_unit_text_snapshot=tube_unit.unit_name,
            purchased_quantity_snapshot=Decimal("30"),
        )
        credit_confirmed_inbound_line(line=tube_inbound_line, actor_employee=self.employee)

        created = self.create_order(self.spray_payload())
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        material_item = OutsourcingMaterialItem.objects.get(
            allocation__processing_item__order_product__order_id=order_id
        )
        dispatched = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            {
                "request_id": str(uuid.uuid4()),
                "remark": "25 根原料管换算为 400 根加工件",
                "lines": [{
                    "material_item_id": str(material_item.pk),
                    "inbound_line_id": str(tube_inbound_line.pk),
                    "source_quantity": "25.0000",
                    "material_quantity": "400.0000",
                    "conversion_factor": "16.00000000",
                    "conversion_evidence": "BOM 采购支数 25 根，外发加工总需求 400 根",
                    "match_method": "REFERENCE_ID",
                    "match_reason": "",
                }],
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )

        self.assertEqual(dispatched.status_code, 200, dispatched.data)
        tube_balance.refresh_from_db()
        self.assertEqual(tube_balance.quantity, Decimal("5.0000"))
        requirement = tube_material.order_requirements.get(production_task=self.product_line.production_task)
        self.assertEqual(requirement.outsourcing_issued_quantity, Decimal("25.0000"))
        dispatch_line = OutsourcingDispatchLine.objects.get(material_item=material_item)
        self.assertEqual(dispatch_line.source_quantity, Decimal("25.0000"))
        self.assertEqual(dispatch_line.material_quantity, Decimal("400.0000"))

    def test_dispatch_deducts_shared_allowance_and_return_creates_semi_finished_balance(self):
        created = self.create_order(self.current_fabric_payload())
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        dispatch_request_id = str(uuid.uuid4())
        dispatch_payload = self.dispatch_payload(order_id)
        dispatch_payload["lines"][0]["requested_quantity"] = "120.0000"
        dispatch_payload["lines"][0].pop("source_quantity")
        dispatch_payload["lines"][0].pop("material_quantity")
        dispatch_payload["request_id"] = dispatch_request_id
        dispatched = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            dispatch_payload,
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(dispatched.status_code, 200, dispatched.data)
        self.assertEqual(dispatched.data["data"]["status"], OutsourcingOrderStatus.PROCESSING)
        self.assertRegex(OutsourcingDispatch.objects.get(order_id=order_id).dispatch_number,
            rf"^FL{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        self.material_balance.refresh_from_db()
        self.assertEqual(self.material_balance.quantity, Decimal("80"))
        requirement = self.raw_material.order_requirements.get(production_task=self.product_line.production_task)
        self.assertEqual(requirement.outsourcing_issued_quantity, Decimal("120"))
        requirement_response = self.client.get(
            "/api/v1/material-issues/requirements/",
            {
                "production_task_id": str(self.product_line.production_task_id),
                "product_line_id": str(self.product_line.pk),
                "workshop_id": str(Workshop.objects.get(name="车缝车间").pk),
            },
        )
        self.assertEqual(requirement_response.status_code, 200, requirement_response.data)
        raw_requirement = next(
            item for item in requirement_response.data["data"]["items"]
            if item["stock_item_id"] == str(self.raw_material.pk)
        )
        self.assertEqual(raw_requirement["outsourcing_issued_quantity"], "120.0000")
        self.assertEqual(raw_requirement["order_remaining"], "30.0000")
        dispatch_retry = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            dispatch_payload,
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(dispatch_retry.status_code, 200, dispatch_retry.data)
        self.material_balance.refresh_from_db()
        self.assertEqual(self.material_balance.quantity, Decimal("80"))

        allocation = OutsourcingFactoryAllocation.objects.get(
            processing_item__order_product__order_id=order_id
        )
        dispatch_line = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
        return_request_id = str(uuid.uuid4())
        return_payload = {
            "request_id": return_request_id,
            "factory_id": str(allocation.factory_id),
            "good_zone_id": str(self.semi_zone.pk),
            "defective_zone_id": str(self.defective_zone.pk),
            "received_by_employee_id": str(self.employee.pk),
            "return_date": timezone.localdate().isoformat(),
            "delivery_note_number": "SH-001",
            "lines": [{
                "allocation_id": str(allocation.pk),
                "good_quantity": "28.0000",
                "defective_quantity": "2.0000",
                "defect_reason": "表面划伤",
            }],
            "raw_inputs": [{
                "allocation_id": str(allocation.pk),
                "dispatch_line_id": str(dispatch_line.pk),
                "kind": "RAW_INPUT", "quantity": "45.0000",
                "reason": "30 套按每套 1.5 米实际投入",
            }],
            "remark": "首批回厂",
        }
        returned = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-return/",
            return_payload,
            format="json",
            HTTP_IF_MATCH=dispatched.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(returned.data["data"]["status"], OutsourcingOrderStatus.PARTIAL_RETURN)
        self.assertRegex(OutsourcingReturn.objects.get(order_id=order_id).return_number,
            rf"^WH{timezone.localdate():%y%m%d}[0-9]{{3,}}$")
        balance = SemiFinishedStockBalance.objects.get(
            production_task=self.product_line.production_task,
            product_line=self.product_line,
            bom_line=self.cutting,
            completed_craft=self.sewing,
            zone=self.semi_zone,
            quality=MaterialStockQuality.AVAILABLE,
        )
        self.assertEqual(balance.quantity, Decimal("28"))
        self.assertEqual(balance.color_snapshot, "卡其色")
        self.assertEqual(balance.unit_id, self.processing_unit.pk)
        defective_balance = SemiFinishedStockBalance.objects.get(
            production_task=self.product_line.production_task,
            product_line=self.product_line,
            bom_line=self.cutting,
            completed_craft=self.sewing,
            zone=self.defective_zone,
            quality=MaterialStockQuality.DEFECTIVE,
        )
        self.assertEqual(defective_balance.quantity, Decimal("2"))
        return_retry = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-return/",
            return_payload,
            format="json",
            HTTP_IF_MATCH=dispatched.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(return_retry.status_code, 200, return_retry.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal("28"))

        defective_only = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-return/",
            {
                "request_id": str(uuid.uuid4()),
                "factory_id": str(allocation.factory_id),
                "good_zone_id": None,
                "defective_zone_id": str(self.defective_zone.pk),
                "received_by_employee_id": str(self.employee.pk),
                "return_date": timezone.localdate().isoformat(),
                "delivery_note_number": "SH-002",
                "lines": [{
                    "allocation_id": str(allocation.pk),
                    "good_quantity": "0.0000",
                    "defective_quantity": "5.0000",
                    "defect_reason": "焊点不良",
                }],
                "raw_inputs": [{
                    "allocation_id": str(allocation.pk),
                    "dispatch_line_id": str(dispatch_line.pk),
                    "kind": "RAW_INPUT", "quantity": "7.5000",
                    "reason": "5 套按每套 1.5 米实际投入",
                }],
                "remark": "纯不良批次",
            },
            format="json",
            HTTP_IF_MATCH=return_retry.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(defective_only.status_code, 200, defective_only.data)
        record = defective_only.data["data"]["returns"][-1]
        self.assertIsNone(record["zone_id"])
        self.assertEqual(record["zone_name"], "")
        self.assertEqual(record["defective_zone_name"], self.defective_zone.zone_name)
        defective_balance.refresh_from_db()
        self.assertEqual(defective_balance.quantity, Decimal("7"))

    def test_dispatch_context_exposes_confirmed_inbound_batch_without_writes(self):
        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]

        response = self.client.get(
            f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200, response.data)
        material = response.data["data"]["materials"][0]
        self.assertEqual(material["planned_issue_quantity"], "120.0000")
        self.assertEqual(material["candidates"][0]["inbound_line_id"], str(self.material_inbound_line.pk))
        self.assertEqual(material["candidates"][0]["available_quantity"], "200.0000")
        self.assertTrue(material["candidates"][0]["same_unit"])
        self.assertEqual(material["candidates"][0]["material_unit"], self.material_unit.unit_name)
        self.assertEqual(self.material_balance.quantity, Decimal("200"))

    def test_dispatch_supports_unit_code_alias_and_cross_unit_conversion(self):
        self.material_inbound_line.source_unit_text_snapshot = self.material_unit.unit_code
        self.material_inbound_line.save(update_fields=["source_unit_text_snapshot", "updated_at"])
        cross_unit_line = MaterialInboundLine.objects.get(pk=self.material_inbound_line.pk)
        cross_unit_line.pk = None
        cross_unit_line.id = None
        cross_unit_line.source_unit_text_snapshot = "卷"
        cross_unit_line.received_quantity = Decimal("120")
        cross_unit_line.accepted_quantity = Decimal("120")
        cross_unit_line.purchased_quantity_snapshot = Decimal("120")
        cross_unit_line.save()
        credit_material_stock(
            raw_material=self.raw_material,
            unit=self.material_unit,
            zone=cross_unit_line.zone,
            quantity=Decimal("120"),
            source_type="MATERIAL_INBOUND",
            source_id=cross_unit_line.inbound_id,
            source_line_id=cross_unit_line.pk,
            actor_employee=self.employee,
            production_task=self.product_line.production_task,
            snapshot={"source_unit": "卷", "conversion_evidence": "测试预换算入库"},
        )

        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]
        context = self.client.get(
            f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(context.status_code, 200, context.data)
        candidates = {
            row["inbound_line_id"]: row
            for row in context.data["data"]["materials"][0]["candidates"]
        }
        self.assertTrue(candidates[str(self.material_inbound_line.pk)]["same_unit"])
        self.assertFalse(candidates[str(cross_unit_line.pk)]["same_unit"])

        material_item = OutsourcingMaterialItem.objects.get(
            allocation__processing_item__order_product__order_id=order_id
        )
        response = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            {
                "request_id": str(uuid.uuid4()),
                "remark": "按卷换算为米",
                "lines": [{
                    "material_item_id": str(material_item.pk),
                    "inbound_line_id": str(cross_unit_line.pk),
                    "source_quantity": "60.0000",
                    "material_quantity": "120.0000",
                    "conversion_factor": "2.00000000",
                    "conversion_evidence": "每卷验收折合 2 米",
                    "match_method": "REFERENCE_ID",
                    "match_reason": "",
                }],
            },
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200, response.data)
        dispatch_line = OutsourcingDispatch.objects.get(order_id=order_id).lines.get()
        self.assertEqual(dispatch_line.source_quantity, Decimal("60"))
        self.assertEqual(dispatch_line.material_quantity, Decimal("120"))
        self.assertEqual(dispatch_line.conversion_factor, Decimal("2"))

    def test_dispatch_batch_available_quantity_includes_other_stock_outflows(self):
        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]
        debit_material_stock(
            raw_material=self.raw_material,
            unit=self.raw_material.unit,
            quantity=Decimal("50"),
            source_type="MATERIAL_ISSUE",
            source_id=uuid.uuid4(),
            source_line_id=uuid.uuid4(),
            actor_employee=self.employee,
            production_task=self.product_line.production_task,
            snapshot={"test": "其他领料先占用同批库存"},
        )

        context = self.client.get(
            f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/",
            HTTP_HOST="localhost",
        )
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(
            context.data["data"]["materials"][0]["candidates"][0]["available_quantity"],
            "150.0000",
        )
        dispatched = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            self.dispatch_payload(order_id),
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(dispatched.status_code, 200, dispatched.data)
        self.material_balance.refresh_from_db()
        self.assertEqual(self.material_balance.quantity, Decimal("30"))

    def test_return_rejects_quantity_above_factory_allocation(self):
        created = self.create_order(self.payload())
        dispatched = self.client.post(
            f"/api/v1/outsourcing-orders/{created.data['data']['id']}/confirm-dispatch/",
            self.dispatch_payload(created.data["data"]["id"]),
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )
        allocation = OutsourcingFactoryAllocation.objects.get(
            processing_item__order_product__order_id=created.data["data"]["id"]
        )
        response = self.client.post(
            f"/api/v1/outsourcing-orders/{created.data['data']['id']}/confirm-return/",
            {
                "request_id": str(uuid.uuid4()),
                "factory_id": str(allocation.factory_id),
                "good_zone_id": str(self.semi_zone.pk),
                "defective_zone_id": str(self.defective_zone.pk),
                "received_by_employee_id": str(self.employee.pk),
                "return_date": timezone.localdate().isoformat(),
                "delivery_note_number": "",
                "lines": [{
                    "allocation_id": str(allocation.pk),
                    "good_quantity": "81.0000",
                    "defective_quantity": "0.0000",
                    "defect_reason": "",
                }],
            },
            format="json",
            HTTP_IF_MATCH=dispatched.headers["ETag"],
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(SemiFinishedStockBalance.objects.exists())

    def test_warehouse_actions_require_their_dedicated_permissions(self):
        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        self.user.user_permissions.set([
            Permission.objects.get(
                content_type__app_label="outsourcing",
                codename="view_outsourcingorder",
            )
        ])
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

        detail = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertFalse(detail.data["data"]["can_confirm_dispatch"])
        self.assertFalse(detail.data["data"]["can_confirm_return"])
        self.assertEqual(
            self.client.get(
                f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/",
                HTTP_HOST="localhost",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
                self.dispatch_payload(order_id),
                format="json",
                HTTP_IF_MATCH=created.headers["ETag"],
                HTTP_HOST="localhost",
            ).status_code,
            403,
        )

    def test_dispatch_rejects_changed_bom_source_before_stock_write(self):
        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]
        self.fabric.notes = "外发单创建后变更"
        self.fabric.save(update_fields=["notes", "updated_at"])

        response = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            self.dispatch_payload(order_id),
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.material_balance.refresh_from_db()
        self.assertEqual(self.material_balance.quantity, Decimal("200"))
        self.assertFalse(OutsourcingDispatch.objects.filter(order_id=order_id).exists())

    def test_dispatch_rejects_changed_fabric_inventory_mapping_before_stock_write(self):
        created = self.create_order(self.payload())
        order_id = created.data["data"]["id"]
        replacement = RawMaterialInformation.objects.create(
            material_number="OUT-MAT-002",
            item_type="MATERIAL",
            category=self.raw_material.category,
            material_name="委外测试替代面料",
            specification="600D",
            unit=self.material_unit,
            material="替代牛津布",
            warehouse_number="OUT-MAT-WH",
            warehouse_name="委外材料仓",
        )
        self.fabric_material.inventory_raw_material = replacement
        self.fabric_material.save(update_fields=["inventory_raw_material", "updated_at"])

        response = self.client.post(
            f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/",
            self.dispatch_payload(order_id),
            format="json",
            HTTP_IF_MATCH=created.headers["ETag"],
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.material_balance.refresh_from_db()
        self.assertEqual(self.material_balance.quantity, Decimal("200"))
        self.assertFalse(OutsourcingDispatch.objects.filter(order_id=order_id).exists())
