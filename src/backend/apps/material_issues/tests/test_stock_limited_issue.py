"""领料以扣占用后的真实库存为上限，BOM 数量仅作建议。"""

import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomLine
from apps.boms.material_flow_calculations import pipe_plan
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import MaterialInboundLine, MaterialStockBalance, MaterialStockMovement, PublicStockMovement, Warehouse, WarehouseZone
from apps.inventory.pipe_stock_services import credit_pipe_inbound, issue_pipe_material
from apps.inventory.stock_services import credit_confirmed_inbound_line
from apps.outsourcing.models import OutsourcingDispatchLine, OutsourcingMaterialItem
from apps.outsourcing.tests import test_material_flow as outsourcing_fixtures
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_scheduling.tests import test_production_scheduling_api as schedule_fixtures
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_config.tests.factories import production_employee

from ..models import MaterialIssue, OrderMaterialRequirement
from ..pipe_requirements import sync_pipe_requirement
from ..public_issue_services import public_line_quantities
from ..public_semi_requirements import build_public_semi_specs
from ..requirements import sync_order_requirements
from ..services import submit_issue
from . import test_material_issue_api as ordinary_fixtures
from . import test_public_issue_services as public_fixtures


def ensure_stock_test_references():
    schedule_fixtures.ensure_schedule_test_references()
    ProductionUnit.objects.get_or_create(unit_name="PCS", defaults={"unit_code": "U3-PCS"})
    ProductCategory.objects.get_or_create(category_name="管材", item_type="MATERIAL")
    for name in ("金工车间", "车缝车间", "装配车间"):
        Workshop.objects.get_or_create(name=name, defaults={"status": "ACTIVE"})


class StockLimitedApiMixin:
    def scope(self):
        return SimpleNamespace(task=self.task, product_line=self.product_line,
                               bom_line=self.bom_line, schedule_product=self.schedule_product)

    def rows(self, *, semi=False, scope=None, issue=None):
        scope = scope or self.scope()
        query = {
            "production_task_id": str(scope.task.pk), "product_line_id": str(scope.product_line.pk),
            "workshop_id": str((self.assembly if semi else self.workshop).pk),
            "plan_category": "ASSEMBLY" if semi else "METAL",
        }
        if issue:
            query["issue_id"] = str(issue.pk)
        response = self.client.get("/api/v1/material-issues/requirements/", query)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["blockers"], [], response.data)
        return [row for row in response.data["data"]["items"]
                if row["line_type"] == ("SEMI" if semi else "RAW")]

    def issue_payload(self, quantity, *, semi=False, scope=None, row=None, recipient=None):
        scope = scope or self.scope()
        row = row or self.rows(semi=semi, scope=scope)[0]
        return {
            "client_request_id": str(uuid.uuid4()), "schedule_product_id": str(scope.schedule_product.pk),
            "plan_category": "ASSEMBLY" if semi else "METAL", "production_task_id": str(scope.task.pk),
            "product_line_id": str(scope.product_line.pk),
            "workshop_id": str((self.assembly if semi else self.workshop).pk),
            "recipient_workshop_employee_id": str((recipient or (
                self.assembly_recipient if semi else self.recipient)).pk),
            "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": row["requirement_id"], "requested_quantity": str(quantity)}],
        }

    def create_api(self, quantity, **kwargs):
        response = self.client.post("/api/v1/material-issues/", self.issue_payload(quantity, **kwargs), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return MaterialIssue.objects.get(pk=response.data["data"]["id"])

    def action_api(self, issue, action, payload=None):
        path = f"/api/v1/material-issues/{issue.pk}/"
        detail = self.client.get(path)
        self.assertEqual(detail.status_code, 200, detail.data)
        response = self.client.post(path + action + "/", payload or {}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def issue_api(self, quantity, **kwargs):
        issue = self.create_api(quantity, **kwargs)
        self.action_api(issue, "submit")
        self.assertTrue(self.action_api(issue, "preview-issue").data["data"]["can_confirm"])
        self.action_api(issue, "confirm-issue", {"request_id": str(uuid.uuid4())})
        issue.refresh_from_db()
        self.assertEqual(issue.status, "ISSUED")
        return issue

    def assert_create_error(self, quantity, code, **kwargs):
        before = MaterialIssue.objects.count()
        response = self.client.post("/api/v1/material-issues/", self.issue_payload(quantity, **kwargs), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], code, response.data)
        self.assertEqual(MaterialIssue.objects.count(), before)


class PublicStockFixture(StockLimitedApiMixin, public_fixtures.PublicIssueFixture):
    def setUp(self):
        ensure_stock_test_references()
        super().setUp()


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicStockLimitedIssueTests(PublicStockFixture, APITestCase):
    def test_pipe_two_rounds_above_bom_keep_source_and_exact_root_meter_debits(self):
        self.credit(self.pipe_identity, self.zone, 400)
        self.assertEqual(Decimal(self.rows()[0]["required_quantity"]), 2022)
        self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 2460)
        first = self.issue_api(2040)
        after_first = self.rows()[0]
        self.assertEqual(Decimal(after_first["order_remaining"]), 0)
        self.assertEqual(Decimal(after_first["max_issue_quantity"]), 420)
        second = self.issue_api(12)
        after_second = self.rows()[0]
        self.assertEqual(Decimal(after_second["max_issue_quantity"]), 408)
        self.requirement.refresh_from_db()
        self.assertEqual((self.requirement.required_quantity, self.requirement.internal_issued_quantity), (2022, 2052))
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (68, Decimal("207.40")))
        self.assertEqual(self.balance().quantity, 337)
        allocations = list(first.lines.get().public_stock_allocations.all()) + list(second.lines.get().public_stock_allocations.all())
        self.assertEqual(sum(row.stock_quantity for row in allocations), 342)
        self.assertEqual(sum(row.meter_quantity for row in allocations), Decimal("1043.10"))
        self.assert_create_error(414, "STOCK_INSUFFICIENT")

    def test_public_semi_two_rounds_above_bom_do_not_debit_raw_again(self):
        self.credit(self.semi_identity, self.semi_zone, 2500)
        first = self.issue_api(2100, semi=True)
        row = self.rows(semi=True)[0]
        self.assertEqual((Decimal(row["required_quantity"]), Decimal(row["order_remaining"]),
                          Decimal(row["max_issue_quantity"])), (2000, 0, 500))
        second = self.issue_api(200, semi=True)
        self.assertEqual(Decimal(self.rows(semi=True)[0]["max_issue_quantity"]), 300)
        self.public_semi.refresh_from_db()
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_semi.quantity, self.public_pipe.quantity), (300, 10))
        for issue in (first, second):
            allocation = issue.lines.get().public_stock_allocations.get()
            self.assertIsNone(allocation.meter_quantity)
        requirement = second.lines.get().semi_requirement
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity), (2000, 2300))
        # 仅领料放开，非领料来源构建默认仍报告已领超过建议量。
        _, blockers = build_public_semi_specs(self.task.pk, self.product_line.pk)
        self.assertIn("REQUIREMENT_BELOW_ISSUED", [item["code"] for item in blockers])
        self.assert_create_error(301, "STOCK_INSUFFICIENT", semi=True)

    def test_shared_quantity_default_keeps_order_limit_but_issue_uses_stock(self):
        self.credit(self.pipe_identity, self.zone, 400)
        issued = self.issue_api(2040)
        line = issued.lines.get()
        self.assertEqual(Decimal(public_line_quantities(line)["max_issue_quantity"]), 0)
        self.assertEqual(Decimal(public_line_quantities(line, limit_to_order=False)["max_issue_quantity"]), 420)
        with self.assertRaises(ValidationError) as caught:
            sync_pipe_requirement(self.bom_line.pk)
        self.assertEqual(caught.exception.api_error_code, "REQUIREMENT_BELOW_ISSUED")

    def test_pipe_whole_root_and_used_source_identity_guards_remain(self):
        self.assert_create_error(7, "PIPE_WHOLE_BAR_REQUIRED")
        self.assert_create_error("0.5", "INTEGER_REQUIRED", semi=True)
        self.issue_api(12)
        old_row = self.rows()[0]
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=3,
                         order_quantity=1000, calculation_version=2)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.save()
        self.assert_create_error(6, "SOURCE_REVISION_CHANGED", row=old_row)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 8)

    def test_pipe_database_still_rejects_fractional_or_negative_counts(self):
        for changes in ({"required_quantity": Decimal("2022.5")},
                        {"internal_issued_quantity": Decimal("0.5")},
                        {"outsourcing_issued_quantity": Decimal("0.5")},
                        {"internal_issued_quantity": -1}, {"outsourcing_issued_quantity": -1}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(**changes)
        with transaction.atomic():
            OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(internal_issued_quantity=2028)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.internal_issued_quantity, 2028)
        self.assertEqual(self.requirement.required_quantity, 2022)


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
class LegacyPipeStockLimitedIssueTests(PublicStockFixture, APITestCase):
    def test_legacy_pipe_two_rounds_above_bom_continue_from_api_source(self):
        extra = self.make_batch(bars=10)
        credit_pipe_inbound(inbound_line_id=extra.pk, actor_employee=self.employee)
        self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 2082)
        first = self.issue_api(2040)
        self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 42)
        second = self.issue_api(12)
        self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 30)
        balances = MaterialStockBalance.objects.filter(measurement_kind="PIPE", raw_material=self.raw_material)
        self.assertEqual(sum(row.quantity for row in balances), 5)
        self.assertEqual(sum(row.meter_quantity for row in balances), Decimal("15.25"))
        self.requirement.refresh_from_db()
        self.assertEqual((self.requirement.required_quantity, self.requirement.internal_issued_quantity), (2022, 2052))
        self.assertEqual(sum(row.bar_count for issue in (first, second) for row in issue.lines.get().batch_allocations.all()), 342)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
        self.assert_create_error(36, "STOCK_INSUFFICIENT")

    def test_outsourcing_default_still_cannot_exceed_bom_allowance(self):
        extra = self.make_batch(bars=10)
        credit_pipe_inbound(inbound_line_id=extra.pk, actor_employee=self.employee)
        with self.assertRaises(ValidationError) as caught:
            issue_pipe_material(**self.args(2040, "OUTSOURCING_DISPATCH"))
        self.assertEqual(caught.exception.api_error_code, "ORDER_ALLOWANCE_EXCEEDED")
        self.assertEqual(self.balance().quantity, 337)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="OUTSOURCING_DISPATCH").exists())


class OrdinaryStockFixture(StockLimitedApiMixin):
    def setUp(self):
        ensure_stock_test_references()
        ordinary_fixtures.MaterialIssueApiTests.setUp(self)
        # 克隆另一任务只需原金工工艺；不引入额外排产或装配业务。
        self.assembly_craft = self.plan_craft

    other_scope = public_fixtures.PublicIssueFixture.other_scope

    def ordinary_balance(self):
        return MaterialStockBalance.objects.get(raw_material=self.raw_material, unit=self.raw_material.unit, zone=self.zone)


class OrdinaryStockLimitedIssueTests(OrdinaryStockFixture, APITestCase):
    def assert_inactive_location_blocks_every_stage(self, location):
        for public_mode in (False, True):
            with self.subTest(public_mode=public_mode), override_settings(PUBLIC_STOCK_ISSUES_ENABLED=public_mode), transaction.atomic():
                draft = self.create_api(1)
                pending = self.create_api(1)
                self.action_api(pending, "submit")
                location.status = "DISABLED"
                location.save(update_fields=["status"])
                try:
                    self.assertEqual(Decimal(self.rows()[0]["available_stock"]), 0)
                    self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 0)
                    self.assert_create_error(1, "PENDING_ISSUE_CONFLICT")
                    for issue, action, payload, expected_code, expected_status in (
                        (draft, "submit", {}, "PENDING_ISSUE_CONFLICT", "DRAFT"),
                        (pending, "confirm-issue", {"request_id": str(uuid.uuid4())}, "STOCK_INSUFFICIENT", "PENDING_REVIEW"),
                    ):
                        detail = self.client.get(f"/api/v1/material-issues/{issue.pk}/")
                        self.assertEqual(detail.status_code, 200, detail.data)
                        self.assertEqual(Decimal(detail.data["data"]["lines"][0]["max_issue_quantity"]), 0)
                        response = self.client.post(f"/api/v1/material-issues/{issue.pk}/{action}/",
                            payload, format="json", HTTP_IF_MATCH=detail["ETag"])
                        self.assertEqual(response.status_code, 400, response.data)
                        self.assertEqual(response.data["error"]["code"], expected_code, response.data)
                        issue.refresh_from_db()
                        self.assertEqual(issue.status, expected_status)
                    preview = self.action_api(pending, "preview-issue")
                    self.assertFalse(preview.data["data"]["can_confirm"], preview.data)
                    self.assertEqual(self.ordinary_balance().quantity, 600)
                    self.assertFalse(MaterialStockMovement.objects.filter(source_type="MATERIAL_ISSUE").exists())
                finally:
                    location.status = "ACTIVE"
                    location.save(update_fields=["status"])
                    transaction.set_rollback(True)

    def test_inactive_zone_is_not_available_to_either_stock_mode(self):
        self.assert_inactive_location_blocks_every_stage(self.zone)

    def test_inactive_warehouse_is_not_available_to_either_stock_mode(self):
        self.assert_inactive_location_blocks_every_stage(self.warehouse)

    def test_both_modes_only_debit_material_warehouse_when_other_type_sorts_first(self):
        warehouse = Warehouse.objects.create(
            warehouse_number="U3-MIXED-SEMI", warehouse_name="其他有效仓", warehouse_type="SEMI_FINISHED",
            status="ACTIVE",
        )
        zone = WarehouseZone.objects.create(
            id=uuid.UUID(int=1), warehouse=warehouse, zone_name="顺序在前的非材料库区", status="ACTIVE",
        )
        other = MaterialStockBalance.objects.create(
            raw_material=self.raw_material, unit=self.raw_material.unit, zone=zone,
            measurement_kind="OTHER", quality="AVAILABLE", quantity=100,
        )
        self.assertLess(zone.pk, self.zone.pk)
        for public_mode, quantity, expected in ((False, 550, 50), (True, 20, 30)):
            with self.subTest(public_mode=public_mode), override_settings(PUBLIC_STOCK_ISSUES_ENABLED=public_mode):
                self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), expected + quantity)
                issue = self.issue_api(quantity)
                movements = MaterialStockMovement.objects.filter(
                    source_type="MATERIAL_ISSUE", source_id=issue.pk, direction="OUT",
                )
                self.assertEqual(sum(row.quantity for row in movements), quantity)
                self.assertEqual(set(movements.values_list("balance__zone_id", flat=True)), {self.zone.pk})
                self.assertEqual(self.ordinary_balance().quantity, expected)
                other.refresh_from_db()
                self.assertEqual(other.quantity, 100)

    def test_public_then_legacy_rounds_above_bom_keep_one_stock_and_history(self):
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True):
            first = self.issue_api(550)
            self.assertEqual(first.stock_mode, "PUBLIC_V2")
            row = self.rows()[0]
            self.assertEqual((Decimal(row["required_quantity"]), Decimal(row["order_remaining"]),
                              Decimal(row["max_issue_quantity"])), (500, 0, 50))
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False):
            second = self.issue_api(20)
            self.assertEqual(second.stock_mode, "LEGACY")
            self.assertEqual(Decimal(self.rows()[0]["max_issue_quantity"]), 30)
        requirement = second.lines.get().requirement
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity), (500, 570))
        self.assertEqual(self.ordinary_balance().quantity, 30)
        self.assertEqual(MaterialStockMovement.objects.filter(source_type="MATERIAL_ISSUE", direction="OUT").count(), 2)

    def test_cross_order_cross_mode_pending_is_stock_scoped_and_excludes_self(self):
        other = self.other_scope()
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False):
            first = self.create_api(400)
            self.action_api(first, "submit")
            self.assertEqual(Decimal(self.rows(issue=first)[0]["max_issue_quantity"]), 600)
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True):
            other_row = self.rows(scope=other)[0]
            self.assertNotEqual(other_row["requirement_id"], str(first.lines.get().requirement_id))
            self.assertEqual(Decimal(other_row["max_issue_quantity"]), 200)
            self.assert_create_error(201, "PENDING_ISSUE_CONFLICT", scope=other)
            second = self.create_api(200, scope=other)
            self.action_api(second, "submit")
            self.assertEqual(Decimal(self.rows(scope=other, issue=second)[0]["max_issue_quantity"]), 200)
            self.assertEqual(Decimal(self.rows(scope=other)[0]["max_issue_quantity"]), 0)
            self.action_api(second, "confirm-issue", {"request_id": str(uuid.uuid4())})
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False):
            self.action_api(first, "confirm-issue", {"request_id": str(uuid.uuid4())})
        self.assertEqual(self.ordinary_balance().quantity, 0)

    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
    def test_used_material_disappearance_is_blocked_after_excess_issue(self):
        self.issue_api(550)
        old_row = self.rows()[0]
        newer = Bom.objects.get(pk=self.bom.pk)
        newer.pk, newer.version_number, newer.bom_number = None, 2, "U3-BOM-WITHOUT-USED-MATERIAL"
        newer.save()
        response = self.client.get("/api/v1/material-issues/requirements/", {
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk),
            "workshop_id": str(self.workshop.pk), "plan_category": "METAL",
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("REQUIREMENT_REMOVED_AFTER_ISSUE", [row["code"] for row in response.data["data"]["blockers"]])
        denied = self.client.post("/api/v1/material-issues/", self.issue_payload(6, row=old_row), format="json")
        self.assertEqual(denied.status_code, 400, denied.data)
        self.assertEqual(self.ordinary_balance().quantity, 50)
        self.assertEqual(MaterialIssue.objects.count(), 1)

    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
    def test_default_sync_keeps_existing_excess_but_rejects_true_suggestion_reduction(self):
        self.issue_api(550)
        _, requirements, _, _ = sync_order_requirements(self.task.pk)
        requirement = next(row for row in requirements if row.raw_material_id == self.raw_material.pk)
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity), (500, 550))
        self.bom_line.budget_quantity = "499"
        self.bom_line.save(update_fields=["budget_quantity", "updated_at"])
        with self.assertRaisesMessage(ValidationError, "REQUIREMENT_BELOW_ISSUED"):
            sync_order_requirements(self.task.pk)
        requirement.refresh_from_db()
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity), (500, 550))
        self.assertEqual(self.ordinary_balance().quantity, 50)


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
class UnrelatedMaterialOutsourcingTests(StockLimitedApiMixin, outsourcing_fixtures.MaterialFlowFixture, APITestCase):
    def setUp(self):
        ensure_stock_test_references()
        super().setUp()
        self.user, self.employee = self.f.user, self.f.employee
        self.task, self.product_line = self.f.bom.production_task, self.f.product_line
        self.schedule_product, self.bom = self.f.schedule_product, self.f.bom
        self.workshop = Workshop.objects.get(name="金工车间")
        self.recipient = production_employee(workshop=self.workshop, name="U3跨材料领料员", position="领料员",
                                             is_supervisor=False, status="ACTIVE")
        craft = Craft.objects.create(craft_type="INTERNAL", name="U3跨材料金工作业", workshop=self.workshop,
                                     plan_category="METAL", status="ACTIVE")
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=craft,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category="METAL")
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "U3-EACH"})
        category, _ = ProductCategory.objects.get_or_create(category_name="五金", defaults={"item_type": "MATERIAL"})
        self.raw_a = RawMaterialInformation.objects.create(material_number="U3-OUT-A", item_type="MATERIAL",
            category=category, material_name="已超领材料A", specification="A", unit=unit)
        self.raw_b = RawMaterialInformation.objects.create(material_number="U3-OUT-B", item_type="MATERIAL",
            category=category, material_name="未超领材料B", specification="B", unit=unit)
        self.f.hardware.raw_values = {"source_inventory_material_id": str(self.raw_b.pk)}
        self.f.hardware.save(update_fields=["raw_values", "updated_at"])
        self.bom_line = BomLine.objects.create(section=self.f.hardware.section, line_number=2,
            part_name="已超领材料A", unit="个", budget_quantity="500",
            raw_values={"source_inventory_material_id": str(self.raw_a.pk)})
        self.batches = {}
        for raw, quantity in ((self.raw_a, 600), (self.raw_b, 10)):
            batch = MaterialInboundLine.objects.create(inbound=self.f.material_inbound,
                raw_material_information=raw, zone=self.f.material_balance.zone, received_quantity=quantity,
                accepted_quantity=quantity, return_quantity=0, source_unit_text_snapshot="个",
                purchased_quantity_snapshot=quantity)
            credit_confirmed_inbound_line(line=batch, actor_employee=self.employee)
            self.batches[raw.pk] = batch

    def test_excess_material_a_does_not_block_material_b_outsourcing(self):
        row_a = next(row for row in self.rows() if row["stock_item_id"] == str(self.raw_a.pk))
        self.issue_api(550, row=row_a)
        payload = self.payload(amount="6")
        product = payload["products"][0]
        template = product["materials"][0]
        product["materials"].extend([
            {**template, "bom_line_id": str(self.f.hardware.pk), "planned_issue_quantity": "2"},
            {**template, "bom_line_id": str(self.bom_line.pk), "planned_issue_quantity": "6"},
        ])
        # 旧单建立沿用明确的历史 ORM 夹具，后续来源和发料均调用真实 API。
        created = self.f.create_order(payload)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        materials = list(OutsourcingMaterialItem.objects.filter(
            allocation__processing_item__order_product__order_id=order_id))
        by_raw = {item.conversion_snapshot["raw_material_id"]: item for item in materials}
        context = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/", HTTP_HOST="localhost")
        self.assertEqual(context.status_code, 200, context.data)
        rows = {row["material_item_id"]: row for row in context.data["data"]["materials"]}
        self.assertEqual(Decimal(rows[str(by_raw[str(self.raw_a.pk)].pk)]["max_issue_quantity"]), 0)
        self.assertEqual(Decimal(rows[str(by_raw[str(self.raw_b.pk)].pk)]["max_issue_quantity"]), 2)
        lines = [{"material_item_id": str(by_raw[str(raw.pk)].pk), "inbound_line_id": str(batch.pk),
                  "requested_quantity": quantity} for raw, batch, quantity in (
                      (self.raw_pipe, self.pipe_batch, "6"),
                      (self.raw_b, self.batches[self.raw_b.pk], "2"),
                      (self.raw_a, self.batches[self.raw_a.pk], "6"))]
        failed = self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": lines}, expected=409)
        self.assertIn("剩余额度", failed.data["error"]["message"])
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).exists())
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": lines[:2]})
        self.assertEqual(OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id, raw_material=self.raw_b).issued_quantity, 2)
        self.assertFalse(OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id, raw_material=self.raw_a).exists())
        requirement_a = OrderMaterialRequirement.objects.get(production_task=self.task, raw_material=self.raw_a)
        requirement_b = OrderMaterialRequirement.objects.get(production_task=self.task, raw_material=self.raw_b)
        self.assertEqual((requirement_a.required_quantity, requirement_a.internal_issued_quantity,
                          requirement_a.outsourcing_issued_quantity), (500, 550, 0))
        self.assertEqual(requirement_b.outsourcing_issued_quantity, 2)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_a).quantity, 50)
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_b).quantity, 8)


class ConcurrentSubmitMixin:
    def compete(self, first, second):
        barrier = threading.Barrier(2)
        results, connection_ids = [], []

        def submit(issue_id):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    connection_ids.append(cursor.fetchone()[0])
                issue = MaterialIssue.objects.get(pk=issue_id)
                request = SimpleNamespace(user=self.user, headers={"If-Match": etag_for_instance(issue)})
                barrier.wait(timeout=5)
                submit_issue(issue_id=issue_id, actor_employee=self.employee, request=request)
                results.append("OK")
            except ValidationError as error:
                results.append(getattr(error, "api_error_code", str(error)))
            except Exception as error:
                results.append(f"{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=submit, args=(issue.pk,)) for issue in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertEqual(len(set(connection_ids)), 2, connection_ids)
        self.assertCountEqual(results, ["OK", "PENDING_ISSUE_CONFLICT"])
        self.assertEqual(MaterialIssue.objects.filter(status="PENDING_REVIEW").count(), 1)
        self.assertEqual(MaterialIssue.objects.filter(status="DRAFT").count(), 1)

    def different_recipient(self):
        return production_employee(workshop=self.workshop, name="U3并发另一领料员", position="领料员",
                                   is_supervisor=False, status="ACTIVE")


class PipeStockSubmitConcurrencyTests(ConcurrentSubmitMixin, PublicStockFixture, TransactionTestCase):
    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
    def test_public_cross_order_competing_submits_reserve_physical_roots_once(self):
        other = self.other_scope()
        first = self.create_api(42)
        second = self.create_api(42, scope=other, recipient=self.different_recipient())
        self.compete(first, second)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
        self.assertFalse(PublicStockMovement.objects.filter(direction="OUT").exists())

    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
    def test_legacy_cross_order_competing_submits_reserve_same_batches_once(self):
        other = self.other_scope()
        first = self.create_api(1200)
        second = self.create_api(1200, scope=other, recipient=self.different_recipient())
        self.assertNotEqual(first.lines.get().requirement_id, second.lines.get().requirement_id)
        self.compete(first, second)
        self.assertEqual(self.balance().quantity, 337)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="MATERIAL_ISSUE").exists())


class OrdinaryStockSubmitConcurrencyTests(ConcurrentSubmitMixin, OrdinaryStockFixture, TransactionTestCase):
    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False)
    def test_legacy_cross_order_competing_submits_reserve_raw_and_unit_once(self):
        other = self.other_scope()
        first = self.create_api(400)
        second = self.create_api(400, scope=other, recipient=self.different_recipient())
        self.assertNotEqual(first.lines.get().requirement_id, second.lines.get().requirement_id)
        self.compete(first, second)
        self.assertEqual(self.ordinary_balance().quantity, 600)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type="MATERIAL_ISSUE").exists())
