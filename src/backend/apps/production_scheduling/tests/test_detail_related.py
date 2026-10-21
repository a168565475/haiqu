"""排产详情关联摘要：只验证本次聚合口径与来源权限，不写业务库。"""
import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.access_control.resource_scopes import current_permission
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.material_issues.models import MaterialIssue
from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4Fixture
from apps.outsourcing.models import (
    OutsourcingFactory, OutsourcingFactoryAllocation, OutsourcingOrderProduct, OutsourcingProcessingItem,
    TubeOutsourcingOrder,
)
from apps.outsourcing.tests.test_tube_receipts_api import TubeReceiptFixture
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_tasks.models import ProductionTaskProduct
from apps.workshop_config.models import Workshop

from ..detail_related import ISSUE_PERMISSION, _read_request, _set_dispatched, related_summary


def request_for(user, employee):
    return SimpleNamespace(user=user, employee=employee, method="GET", parser_context={
        "view": SimpleNamespace(action="retrieve", action_permission_map={"retrieve": "production_scheduling.view_productionschedule"}),
    })


class RelatedSummaryBoundaryTests(SimpleTestCase):
    def test_no_source_permissions_returns_denied_without_querying(self):
        request = request_for(SimpleNamespace(has_perm=lambda _permission: False), None)
        product = SimpleNamespace(pk="product", product_line_id="line")
        result = related_summary(request, SimpleNamespace(production_task_id="task"), [product])["product"]
        self.assertEqual(result["outsourcing"], {"allowed": False, "records": [], "planned_amount": None})
        self.assertEqual(result["material_issues"], {"allowed": False, "records": []})

    def test_source_read_context_does_not_mutate_schedule_permission(self):
        request = request_for(None, None)
        source = _read_request(request, ISSUE_PERMISSION)
        self.assertEqual(current_permission(source, ISSUE_PERMISSION), ISSUE_PERMISSION)
        self.assertEqual(current_permission(request, ISSUE_PERMISSION), "production_scheduling.view_productionschedule")

    def test_different_dispatch_units_are_not_added_together(self):
        record = {"dispatched_quantity": None, "dispatched_unit": None, "reason": ""}
        _set_dispatched(record, {"米": Decimal("12"), "个": Decimal("3")})
        self.assertIsNone(record["dispatched_quantity"])
        self.assertEqual(record["dispatched_unit"], "多种单位")
        self.assertTrue(record["reason"])


# 旧单人审批夹具只用于隔离数据准备；范围权限用例在方法内重新启用现行策略。
@override_settings(TUBE_OUTSOURCING_ENABLED=False, MODULE_ACCESS_ENABLED=False,
                   SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class RelatedLegacySummaryTests(ScopedActorMixin, MetalProcessingP4Fixture, APITestCase):
    def summary(self):
        product = self.f.schedule_product
        user = get_user_model().objects.get(pk=self.f.user.pk)
        return related_summary(request_for(user, self.f.employee), product.schedule, [product])[str(product.pk)]

    def only_permissions(self, *names):
        user = self.f.user
        user.is_superuser = False
        user.save(update_fields=["is_superuser"])
        user.user_permissions.set([Permission.objects.get(
            content_type__app_label=name.split(".")[0], codename=name.split(".")[1]) for name in names])

    def test_regular_order_expands_factories_and_excludes_another_product(self):
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        factory = OutsourcingFactory.objects.get(pk=allocation.factory_id)
        factory.pk, factory.factory_number, factory.name = uuid.uuid4(), "DETAIL-SECOND", "第二家加工厂"
        factory.save(force_insert=True)
        OutsourcingFactoryAllocation.objects.create(processing_item=allocation.processing_item, factory=factory,
            allocated_quantity=20, unit_price=Decimal("2.50"), factory_snapshot={"name": factory.name})
        # 同单的另一个产品有更大的金额，摘要不能因整单已匹配而把它并入本产品。
        product_line = ProductionTaskProduct.objects.get(pk=self.f.product_line.pk)
        product_line.pk, product_line.line_number = uuid.uuid4(), 2
        product_line.save(force_insert=True)
        schedule_product = ProductionScheduleProduct.objects.get(pk=self.f.schedule_product.pk)
        schedule_product.pk, schedule_product.product_line, schedule_product.line_number = uuid.uuid4(), product_line, 2
        with transaction.atomic():
            schedule_product.save(force_insert=True)
            for craft_link in self.f.schedule_product.crafts.filter(removed_at__isnull=True):
                ProductionScheduleProductCraft.objects.create(
                    schedule_product=schedule_product, craft_id=craft_link.craft_id,
                    craft_type_snapshot=craft_link.craft_type_snapshot,
                    craft_name_snapshot=craft_link.craft_name_snapshot, plan_category=craft_link.plan_category,
                )
        order_product = OutsourcingOrderProduct.objects.get(pk=allocation.processing_item.order_product_id)
        order_product.pk, order_product.schedule_product, order_product.line_number = uuid.uuid4(), schedule_product, 2
        order_product.save(force_insert=True)
        item = OutsourcingProcessingItem.objects.get(pk=allocation.processing_item_id)
        item.pk, item.order_product = uuid.uuid4(), order_product
        item.save(force_insert=True)
        OutsourcingFactoryAllocation.objects.create(processing_item=item, factory=factory, allocated_quantity=999,
            unit_price=Decimal("99"), factory_snapshot={"name": factory.name})
        summary = self.summary()["outsourcing"]
        self.assertEqual(len(summary["records"]), 2)
        self.assertEqual({row["factory_name"] for row in summary["records"]}, {self.f.factory.name, factory.name})
        self.assertEqual(Decimal(summary["planned_amount"]), allocation.allocated_quantity * allocation.unit_price + Decimal("50"))

    def test_original_and_p4_are_distinct_and_legacy_missing_price_stays_unknown(self):
        order = self.create_order()
        summary = self.summary()["outsourcing"]
        self.assertEqual(len(summary["records"]), 2)
        self.assertEqual({row["order_kind"] for row in summary["records"]}, {"REGULAR", "P4"})
        p4 = next(row for row in summary["records"] if row["order_kind"] == "P4")
        self.assertEqual(p4["order_id"], str(order.pk))
        self.assertIsNone(p4["unit_price"])
        self.assertIsNone(summary["planned_amount"])
        original = next(row for row in summary["records"] if row["order_kind"] == "REGULAR")
        self.assertEqual(original["dispatched_quantity"], "8")

    def test_regular_amount_total_rounds_after_summing_four_decimal_lines(self):
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=self.original_order)
        allocation.allocated_quantity, allocation.input_quantity, allocation.unit_price = Decimal("1"), Decimal("1"), Decimal("1.0050")
        allocation.save(update_fields=["allocated_quantity", "input_quantity", "unit_price"])
        item = allocation.processing_item
        item.quantity = Decimal("2")
        item.save(update_fields=["quantity"])
        factory = OutsourcingFactory.objects.get(pk=allocation.factory_id)
        factory.pk, factory.factory_number, factory.name = uuid.uuid4(), "DETAIL-ROUNDING", "历史四位价格加工厂"
        factory.save(force_insert=True)
        OutsourcingFactoryAllocation.objects.create(processing_item=item, factory=factory,
            allocated_quantity=Decimal("1"), input_quantity=Decimal("1"), unit_price=Decimal("1.0050"),
            factory_snapshot={"name": factory.name})
        summary = self.summary()["outsourcing"]
        self.assertEqual(len(summary["records"]), 2)
        self.assertEqual([row["planned_amount"] for row in summary["records"]], ["1.0050", "1.0050"])
        self.assertEqual(summary["planned_amount"], "2.01")

    def test_metal_only_projection_never_exposes_regular_price_or_delivery(self):
        self.create_original_handoff()
        self.only_permissions("material_issues.view_metalprocessingsource")
        summary = self.summary()
        rows = summary["outsourcing"]["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail_access"], "METAL")
        self.assertEqual(rows[0]["dispatched_quantity"], "8")
        for field in ("planned_quantity", "unit_price", "planned_amount", "expected_return_date"):
            self.assertIsNone(rows[0][field], field)
        self.assertFalse(summary["material_issues"]["allowed"])
        self.assertEqual(summary["material_issues"]["records"], [])

    def test_material_issues_use_product_relation_and_keep_issue_and_stock_times_separate(self):
        original = MaterialIssue.objects.get(pk=self.line.issue_id)
        other = MaterialIssue.objects.get(pk=original.pk)
        other.pk, other.issue_number, other.client_request_id = uuid.uuid4(), "DETAIL-UNASSIGNED", uuid.uuid4()
        other.product_line = None
        other.save(force_insert=True)
        self.only_permissions(ISSUE_PERMISSION)
        summary = self.summary()
        self.assertFalse(summary["outsourcing"]["allowed"])
        rows = summary["material_issues"]["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], str(original.pk))
        self.assertEqual(rows[0]["line_count"], 1)
        self.assertEqual(rows[0]["issue_at"], original.issue_at)
        self.assertEqual(rows[0]["issued_at"], original.issued_at)

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
                       SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_schedule_module_grant_cannot_expand_source_workshop_or_craft(self):
        self.scoped_actor()
        other_workshop = Workshop.objects.get_or_create(name="车缝车间")[0]
        other_craft = self.f.screen_printing
        self.grant("production_scheduling.view_productionschedule", "MODULE")
        self.grant(ISSUE_PERMISSION, "WORKSHOP", [other_workshop])
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [other_craft])
        product = self.f.schedule_product
        user = get_user_model().objects.get(pk=self.scope_user.pk)
        result = related_summary(request_for(user, self.scope_employee), product.schedule, [product])[str(product.pk)]
        self.assertTrue(result["outsourcing"]["allowed"])
        self.assertEqual(result["outsourcing"]["records"], [])
        self.assertTrue(result["material_issues"]["allowed"])
        self.assertEqual(result["material_issues"]["records"], [])


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class RelatedTubeSummaryTests(TubeReceiptFixture, APITestCase):
    def summary(self):
        product = self.schedule_product
        return related_summary(request_for(self.user, self.employee), product.schedule, [product])[str(product.pk)]["outsourcing"]

    def test_tube_amount_uses_planned_quantity_and_valid_receipt_keeps_shortage(self):
        payload = self.order_payload()
        payload["lines"][0]["unit_price"] = "2.50"
        order = self.post_order(payload).data["data"]
        order = self.act(order).data["data"]
        self.receive_final(order, self.receipt_payload(order, "18", "少回两支"))
        record = self.summary()["records"][0]
        self.assertEqual((record["dispatched_quantity"], record["received_quantity"], record["shortage_quantity"]), ("20", "18", "2"))
        self.assertEqual(record["planned_amount"], "50.00")
        self.assertEqual(record["price_unit"], "元/支")

    def test_status_alone_cannot_create_dispatch_or_receipt_quantities(self):
        order = self.post_order(self.order_payload()).data["data"]
        TubeOutsourcingOrder.objects.filter(pk=order["id"]).update(status="COMPLETED")
        summary = self.summary()
        record = summary["records"][0]
        self.assertIsNone(record["dispatched_quantity"])
        self.assertIsNone(record["received_quantity"])
        self.assertIsNone(record["shortage_quantity"])
        self.assertIsNone(summary["planned_amount"])
        self.assertIn("凭证", record["reason"])
