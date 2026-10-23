"""隔离数据库验证：稳定工序、真实投入凭证与产品级共享额度。"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import PreconditionFailed
from apps.material_issues.models import (
    MaterialIssue, MaterialIssueAuditEvent, MaterialIssueLine,
    MaterialIssuePublicStockAllocation, MetalProcessingSource, OrderMaterialRequirement,
)
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import (
    ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft,
)
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Operation
from apps.workshop_reporting.models import (
    WageScheme, WageSchemeCraft, WageSchemeLine, WorkItem, WorkReport, WorkReportLine,
)
from apps.workshop_reporting.tests import test_workshop_reporting_api as reporting_fixture

from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, Warehouse, WarehouseZone
from ..public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity
from ..public_stock_services import credit_public_stock, debit_public_stock
from ..tube_processing_services import (
    assert_tube_quantity_available, assert_tube_reports_cover_usage,
    lock_tube_product_scope, metal_component_limits,
)


class TubeProcessingFixture:
    @transaction.atomic
    def setUp(self):
        # 只调用自建资料的准备方法，不继承其测试类，也不依赖主库种子数据。
        reporting_fixture.WorkshopReportingApiTests.setUp(self)
        self.today = timezone.localdate()
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name="支", defaults={"unit_code": "TUBE-PIECE"})
        self.root_unit, _ = ProductionUnit.objects.get_or_create(
            unit_name="根", defaults={"unit_code": "TUBE-ROOT"})
        self.operation.reporting_unit = self.piece_unit
        self.operation.save(update_fields=["reporting_unit"])
        category, _ = ProductCategory.objects.get_or_create(
            category_name="管材", item_type="MATERIAL")
        self.raw = RawMaterialInformation.objects.create(
            material_number="TUBE-RAW", item_type="MATERIAL", category=category,
            material_name="测试原管", specification="20*1.0*6000", material="铁",
            unit=self.root_unit, color_snapshot="本色", warehouse_number="TUBE-RAW-WH",
            warehouse_name="隔离原料仓")
        self.metal_bom_line.category = "型材"
        self.metal_bom_line.raw_values = {
            "source_inventory_material_id": str(self.raw.pk), "tube_shape": "圆管",
            "tube_diameter": "20", "tube_thickness": "1.0", "tube_coating_color": "黑色",
        }
        self.metal_bom_line.save(update_fields=["category", "raw_values"])
        self.component = str(self.metal_bom_line.component_identity)
        self.raw_zone = self.make_zone("RAW", "MATERIAL")
        self.semi_zone = self.make_zone("SEMI", "SEMI_FINISHED")
        identity = build_pipe_stock_identity(raw_material=self.raw, raw_bar_length_m=6, unit=self.root_unit)
        self.pipe_identity = json.loads(json.dumps(identity, cls=DjangoJSONEncoder))
        opening = credit_public_stock(
            identity=self.pipe_identity, zone=self.raw_zone, quantity=100,
            source_type="TEST_TUBE_OPENING", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee)
        self.raw_balance = opening.balance
        self.requirement = OrderMaterialRequirement.objects.create(
            production_task=self.task, product_line=self.product_line,
            component_identity=self.metal_bom_line.component_identity, measurement_kind="PIPE",
            pieces_per_bar=10, raw_bar_length_m=6, raw_material=self.raw, unit=self.piece_unit,
            line_type="RAW", section_code="PROFILE", required_quantity=200,
            source_revision_hash="r" * 64)
        self.issue_line = self.make_issue(100)
        self.source = self.make_source(self.issue_line)
        bend = Operation.objects.create(
            operation_number="TUBE-BEND", product_name="工价测试产品", craft=self.craft,
            name="弯管", reporting_unit=self.piece_unit)
        self.items = [self.make_item(self.operation), self.make_item(bend)]
        self.scheme, self.lines = self.make_scheme(effective_from=self.today - timedelta(days=10))

    def make_zone(self, code, kind):
        warehouse = Warehouse.objects.create(
            warehouse_number=f"TUBE-{code}", warehouse_name=f"隔离{code}仓", warehouse_type=kind)
        return WarehouseZone.objects.create(warehouse=warehouse, zone_name="测试区")

    def make_issue(self, quantity, *, plan=None, proof=True):
        number = MaterialIssue.objects.count() + 1
        issue = MaterialIssue.objects.create(
            issue_number=f"TUBE-ISSUE-{number}", stock_mode="PUBLIC_V2", status="ISSUED",
            client_request_id=uuid.uuid4(), request_payload_hash="i" * 64,
            production_task=self.task, product_line=self.product_line, workshop=self.workshop,
            recipient_workshop_employee=self.worker, issue_at=timezone.now(), issued_at=timezone.now(),
            issued_by_employee=self.employee, created_by_employee=self.employee,
            updated_by_employee=self.employee, source_revision_hash="i" * 64)
        frozen = {
            "kind": "PIPE", "component_identity": self.component,
            "raw_material_id": str(self.raw.pk), "product_line_id": str(self.product_line.pk),
            "bom_line_id": str(self.metal_bom_line.pk), "bom_id": str(self.bom.pk),
            "source_revision_hash": "b" * 64, "cutting_length_mm": 500,
            "pieces_per_bar": 10, "raw_bar_length_m": "6.00", "public_identity": self.pipe_identity,
        }
        line = MaterialIssueLine.objects.create(
            issue=issue, line_number=1, requirement=self.requirement, line_type="RAW",
            raw_material=self.raw, unit=self.piece_unit, unit_snapshot="支",
            section_code_snapshot="PROFILE", material_number_snapshot=self.raw.material_number,
            material_name_snapshot=self.raw.material_name, specification_snapshot=self.raw.specification,
            color_snapshot="本色", conversion_snapshot=frozen,
            requested_quantity=quantity, issued_quantity=quantity)
        MaterialIssueAuditEvent.objects.create(
            issue=issue, action="CREATED", issue_version=1, actor_employee=self.employee,
            snapshot={"plan_source": {"plan_category": "METAL",
                                     "schedule_product_id": str((plan or self.schedule_product).pk)}})
        if proof:
            bars = Decimal(quantity) / 10
            allocation = MaterialIssuePublicStockAllocation.objects.create(
                line=line, balance=self.raw_balance, requested_quantity=quantity,
                stock_quantity=bars, meter_quantity=bars * 6,
                snapshot={"identity_key": self.pipe_identity["identity_key"]})
            movement = debit_public_stock(
                balance_id=self.raw_balance.pk, quantity=bars, source_type="MATERIAL_ISSUE",
                source_id=issue.pk, source_line_id=allocation.pk, actor_employee=self.employee,
                production_task=self.task, product_line=self.product_line, bom_line=self.metal_bom_line,
                snapshot={"issue_line_id": str(line.pk), "public_identity": self.pipe_identity,
                          "conversion": frozen})
            allocation.movement = movement
            allocation.save(update_fields=["movement"])
        return line

    def make_source(self, line, **usage):
        return MetalProcessingSource.objects.create(
            issue_line=line, source_snapshot={}, source_hash="s" * 64,
            issued_pieces=line.issued_quantity, completed_pieces=line.issued_quantity, **usage)

    def make_item(self, operation):
        return WorkItem.objects.create(
            product_line=self.product_line, workshop=self.workshop, craft=self.craft,
            operation=operation, unit=self.piece_unit, identity_key=uuid.uuid4().hex,
            display_name=f"前脚管-{operation.name}",
            bom_component_identity=self.metal_bom_line.component_identity, counting_mode="PIECE")

    def make_scheme(self, *, effective_from, parent=None, items=None, price="2"):
        scheme = WageScheme.objects.create(
            scheme_number=f"TUBE-SCHEME-{WageScheme.objects.count() + 1}",
            product_line=self.product_line, schedule_product=self.schedule_product,
            workshop=self.workshop, scope_craft=self.craft, status="APPROVED",
            effective_from=effective_from, parent_scheme=parent, version=parent.version + 1 if parent else 1,
            approved_at=timezone.now(), approved_by_employee=self.employee,
            created_by_employee=self.employee, updated_by_employee=self.employee,
            product_name_snapshot="工价测试产品", product_number_snapshot="WG-PRODUCT",
            operation_product_name_snapshot="工价测试产品")
        WageSchemeCraft.objects.create(scheme=scheme, craft=self.craft)
        lines = []
        for index, item in enumerate(items or self.items, 1):
            lines.append(WageSchemeLine.objects.create(
                scheme=scheme, work_item=item, line_number=index, display_name_snapshot=item.display_name,
                craft_name_snapshot=self.craft.name, operation_name_snapshot=item.operation.name,
                operation_number_snapshot=item.operation.operation_number, unit_name_snapshot="支",
                bom_component_identity_snapshot=self.metal_bom_line.component_identity,
                counting_mode="PIECE", order_quantity_snapshot=100, required_quantity_snapshot=200,
                declared_price=Decimal(price), status="ACTIVE"))
        return scheme, lines

    def report(self, quantities=(100, 200), *, lines=None, day=None, plan=None):
        lines = lines or self.lines
        report = WorkReport.objects.create(
            report_number=f"TUBE-REPORT-{WorkReport.objects.count() + 1}",
            production_date=day or self.today, product_line=self.product_line,
            schedule_product=plan or self.schedule_product, workshop=self.workshop,
            scheme=lines[0].scheme, scheme_version_snapshot=lines[0].scheme.version,
            recorder_employee=self.employee, updated_by_employee=self.employee,
            total_amount=sum(Decimal(q) * line.declared_price for q, line in zip(quantities, lines)),
            client_request_id=uuid.uuid4(), request_payload_hash="w" * 64)
        for index, (quantity, line) in enumerate(zip(quantities, lines), 1):
            if quantity:
                WorkReportLine.objects.create(
                    report=report, line_number=index, scheme_line=line, work_item=line.work_item,
                    workshop_employee=self.worker, quantity=quantity, order_quantity_snapshot=100,
                    required_quantity_snapshot=200, unit_price_snapshot=line.declared_price,
                    amount=Decimal(quantity) * line.declared_price,
                    display_name_snapshot=line.display_name_snapshot, craft_name_snapshot=self.craft.name,
                    operation_name_snapshot=line.operation_name_snapshot, unit_name_snapshot="支",
                    employee_name_snapshot=self.worker.display_name)
        return report

    def receive(self, quantity, *, plan=None):
        receipt = InternalSemiFinishedReceipt.objects.create(
            receipt_number=f"TUBE-RECEIPT-{InternalSemiFinishedReceipt.objects.count() + 1}",
            request_id=uuid.uuid4(), request_payload_hash="c" * 64,
            schedule_product=plan or self.schedule_product, completed_craft=self.craft,
            plan_category="METAL", receipt_date=self.today, zone=self.semi_zone,
            actor_employee=self.employee, source_revision_hash="c" * 64, source_snapshot={})
        identity = build_semi_finished_identity(
            bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        line_id = uuid.uuid4()
        movement = credit_public_stock(
            identity=identity, zone=self.semi_zone, quantity=quantity,
            source_type="INTERNAL_SEMI_RECEIPT", source_id=receipt.pk, source_line_id=line_id,
            actor_employee=self.employee, production_task=self.task, product_line=self.product_line,
            bom_line=self.metal_bom_line)
        return InternalSemiFinishedReceiptLine.objects.create(
            id=line_id, receipt=receipt, bom_line=self.metal_bom_line,
            component_identity=self.metal_bom_line.component_identity, unit=self.piece_unit,
            input_requirement=self.requirement, input_unit_name="支", quantity=quantity,
            input_per_output=1, input_quantity=quantity, required_quantity_snapshot=200,
            received_before=0, received_after=quantity, stock_movement=movement,
            attribute_snapshot=identity["identity_snapshot"], input_snapshot={})

    def context(self, **kwargs):
        return metal_component_limits(self.product_line.pk, **kwargs)

    def allowance(self, **kwargs):
        row = self.context(**kwargs)["components"][self.component]
        self.assertTrue(row["basis_ready"], row["blockers"])
        return row["allowance"]

    def second_plan(self):
        self.schedule.record_status = "VOID"
        self.schedule.void_reason = "隔离测试跨计划归集"
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save(update_fields=["record_status", "void_reason", "voided_at", "voided_by_employee"])
        self.task.status = "READY"
        self.task.save(update_fields=["status"])
        schedule = ProductionSchedule.objects.create(
            schedule_number="PC-TUBE-SECOND", production_task=self.task, record_status="ACTIVE",
            version=2, source_snapshot={}, source_revision_hash="p" * 64,
            client_request_id=uuid.uuid4(), request_payload_hash="p" * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        product = ProductionScheduleProduct.objects.create(
            schedule=schedule, product_line=self.product_line, line_number=1, planned_quantity=100,
            source_quantity_snapshot=100, unit=self.unit, unit_name_snapshot=self.unit.unit_name,
            material_inbound_date=self.today, metal_return_date=self.today + timedelta(days=1),
            sewing_return_date=self.today + timedelta(days=2), finished_inbound_date=self.today + timedelta(days=3),
            product_snapshot={}, source_revision_hash="p" * 64)
        ProductionScheduleProductCraft.objects.create(
            schedule_product=product, craft=self.craft, craft_type_snapshot="INTERNAL",
            craft_name_snapshot=self.craft.name, plan_category="METAL")
        self.task.status = "IN_PRODUCTION"
        self.task.save(update_fields=["status"])
        return product


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeProcessingServiceTests(TubeProcessingFixture, TestCase):
    def test_each_current_operation_takes_minimum_and_real_input_caps_output(self):
        self.report()
        allowance = self.allowance()
        self.assertEqual((allowance["required"], allowance["issued"], allowance["reported_minimum"]), (200, 100, 100))
        self.assertEqual(allowance["remaining"], 100)

    def test_unitless_metal_reports_use_minimum_piece_count(self):
        WageSchemeLine.objects.filter(scheme=self.scheme).update(unit_name_snapshot="")
        WorkItem.objects.filter(pk__in=[item.pk for item in self.items]).update(unit=None)
        self.report((100, 80))

        allowance = self.allowance()
        self.assertEqual(allowance["reported_minimum"], 80)
        self.assertEqual(allowance["remaining"], 80)

    def test_explicit_non_piece_unit_still_blocks_metal_processing(self):
        WageSchemeLine.objects.filter(scheme=self.scheme).update(unit_name_snapshot="套")
        WorkItem.objects.filter(pk__in=[item.pk for item in self.items]).update(unit=self.root_unit)
        self.report((100, 80))

        row = self.context()["components"][self.component]
        self.assertFalse(row["basis_ready"])
        self.assertIn("报工单位", "".join(row["blockers"]))

    def test_unreported_operation_is_zero_not_ignored(self):
        self.report((100, 0))
        self.assertEqual(self.allowance()["remaining"], 0)

    def test_receipt_dispatch_and_reservation_share_one_remaining(self):
        self.report()
        receipt_line = self.receive(40)
        self.source.internal_received_pieces = 40
        self.source.dispatched_pieces = 20
        self.source.reserved_pieces = 10
        self.source.save()
        allowance = self.allowance()
        self.assertEqual((allowance["received"], allowance["used"], allowance["remaining"]), (40, 70, 30))
        # 库存已经领走不会释放首次产出的订单额度。
        debit_public_stock(
            balance_id=receipt_line.stock_movement.balance_id, quantity=40,
            source_type="TEST_TUBE_LATER_USE", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee)
        self.assertEqual(self.allowance()["remaining"], 30)

    def test_cancel_releases_and_dispatch_transfer_does_not_double_count(self):
        self.report()
        self.source.reserved_pieces = 60
        self.source.save()
        self.assertEqual(self.allowance()["remaining"], 40)
        self.source.reserved_pieces = 0
        self.source.save()
        self.assertEqual(self.allowance()["remaining"], 100)
        self.source.dispatched_pieces = 60
        self.source.save()
        self.assertEqual(self.allowance()["remaining"], 40)

    def test_same_operation_accumulates_across_price_versions_without_repricing(self):
        old_report = self.report((40, 80), day=self.today - timedelta(days=1))
        self.scheme.effective_to = self.today - timedelta(days=1)
        self.scheme.save(update_fields=["effective_to"])
        _, new_lines = self.make_scheme(effective_from=self.today, parent=self.scheme, price="3")
        self.report((60, 120), lines=new_lines)
        self.assertEqual(self.allowance()["reported_minimum"], 100)
        old_report.refresh_from_db()
        self.assertEqual(old_report.total_amount, Decimal("240.00"))
        self.assertEqual(set(old_report.lines.values_list("unit_price_snapshot", flat=True)), {Decimal("2")})

    def test_new_operation_cannot_inherit_retired_operations_total(self):
        self.report()
        self.scheme.effective_to = self.today - timedelta(days=1)
        self.scheme.save(update_fields=["effective_to"])
        new_operation = Operation.objects.create(
            operation_number="TUBE-DRILL", product_name="工价测试产品", craft=self.craft,
            name="冲孔", reporting_unit=self.piece_unit)
        new_item = self.make_item(new_operation)
        self.make_scheme(effective_from=self.today, parent=self.scheme, items=[self.items[0], new_item])
        row = self.context()["components"][self.component]
        self.assertEqual(row["allowance"]["reported_minimum"], 0)
        self.assertEqual({op["work_item_id"] for op in row["operations"]}, {str(self.items[0].pk), str(new_item.pk)})

    def test_multiple_plans_share_reports_and_receipts_without_duplicate_input(self):
        self.report((40, 80))
        plan = self.second_plan()
        self.report((60, 120), plan=plan)
        self.receive(40, plan=plan)
        MaterialIssueAuditEvent.objects.create(
            issue=self.issue_line.issue, action="CREATED", issue_version=1, actor_employee=self.employee,
            snapshot={"plan_source": {"plan_category": "METAL", "schedule_product_id": str(plan.pk)}})
        allowance = self.allowance()
        self.assertEqual((allowance["issued"], allowance["reported_minimum"], allowance["received"], allowance["remaining"]),
                         (100, 100, 40, 60))

    def test_future_report_does_not_support_todays_quantity(self):
        self.report((40, 80))
        self.report((60, 120), day=self.today + timedelta(days=1))
        self.assertEqual(self.allowance()["reported_minimum"], 40)
        self.assertEqual(self.allowance(as_of=self.today + timedelta(days=1))["reported_minimum"], 100)

    def test_scheme_effective_date_and_missing_operation_block_processing(self):
        self.report()
        row = self.context(as_of=self.today - timedelta(days=11))["components"][self.component]
        self.assertFalse(row["basis_ready"])
        self.lines[0].status = "VOID"
        self.lines[0].save(update_fields=["status"])
        self.lines[1].status = "VOID"
        self.lines[1].save(update_fields=["status"])
        self.assertFalse(self.context()["components"][self.component]["basis_ready"])

    def test_issued_status_without_actual_out_movement_is_blocked(self):
        self.report()
        self.make_issue(10, proof=False)
        row = self.context()["components"][self.component]
        self.assertFalse(row["basis_ready"])
        self.assertIsNone(row["allowance"])
        self.assertIn("实际出库凭证", "".join(row["blockers"]))

    def test_changed_cutting_or_current_raw_material_blocks_frozen_input(self):
        self.report()
        for values in ({"cutting_length_mm": 501}, {"raw_values": {"source_inventory_material_id": str(uuid.uuid4())}}):
            with self.subTest(values=values), transaction.atomic():
                for name, value in values.items():
                    setattr(self.metal_bom_line, name, value)
                self.metal_bom_line.save(update_fields=list(values))
                self.assertFalse(self.context()["components"][self.component]["basis_ready"])
                transaction.set_rollback(True)
        self.metal_bom_line.refresh_from_db()

    def test_fractional_historical_reports_cannot_hide_in_integer_sum(self):
        self.report((Decimal("40.5"), 100))
        self.report((Decimal("59.5"), 100))
        self.assertFalse(self.context()["components"][self.component]["basis_ready"])

    def test_future_unreported_operation_prevents_new_reservation_today(self):
        self.report()
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=["effective_to"])
        operation = Operation.objects.create(
            operation_number="TUBE-FUTURE", product_name="工价测试产品", craft=self.craft,
            name="未来新增冲孔", reporting_unit=self.piece_unit)
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme,
                         items=[self.items[0], self.make_item(operation)])
        revision = self.context()["revision"]
        self.assertEqual(self.allowance()["remaining"], 100)
        with self.assertRaises(ValidationError), transaction.atomic():
            assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                           requested={self.component: 60}, expected_revision=revision)
        self.source.refresh_from_db()
        self.assertEqual(self.source.reserved_pieces, 0)

    def test_future_price_only_revision_allows_current_reservation(self):
        self.report()
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=["effective_to"])
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, price="3")
        revision = self.context()["revision"]
        result = assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                               requested={self.component: 60}, expected_revision=revision)
        self.assertEqual(result["revision"], revision)

    def test_newly_approved_future_scheme_invalidates_existing_preview(self):
        self.report()
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=["effective_to"])
        before = self.context()["revision"]
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, price="3")
        self.assertNotEqual(self.context()["revision"], before)
        with self.assertRaises(PreconditionFailed), transaction.atomic():
            assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                           requested={self.component: 60}, expected_revision=before)

    def test_changed_usage_invalidates_preview_and_rejects_stale_write(self):
        self.report()
        revision = self.context()["revision"]
        self.source.reserved_pieces = 10
        self.source.save()
        self.assertNotEqual(self.context()["revision"], revision)
        with self.assertRaises(PreconditionFailed), transaction.atomic():
            assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                           requested={self.component: 60}, expected_revision=revision)
        self.source.refresh_from_db()
        self.assertEqual(self.source.reserved_pieces, 10)

    def test_validate_request_rejects_unknown_zero_fractional_and_excess(self):
        self.report()
        revision = self.context()["revision"]
        for requested in ({}, {str(uuid.uuid4()): 1}, {self.component: 0},
                          {self.component: "0.5"}, {self.component: True}, {self.component: 101},
                          {self.component: 60, uuid.UUID(self.component): 60}):
            with self.subTest(requested=requested), self.assertRaises(ValidationError), transaction.atomic():
                assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                               requested=requested, expected_revision=revision)
        accepted = assert_tube_quantity_available(product_line_id=self.product_line.pk,
                                                requested={self.component: 100}, expected_revision=revision)
        self.assertEqual(accepted["revision"], revision)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeProcessingConcurrencyTests(TubeProcessingFixture, TransactionTestCase):
    def test_lock_requires_explicit_transaction(self):
        with self.assertRaises(RuntimeError):
            lock_tube_product_scope(self.product_line.pk)

    def test_two_separate_sources_cannot_reserve_sixty_each_against_one_hundred(self):
        self.report()
        second_source = self.make_source(self.make_issue(100))
        revision = self.context()["revision"]
        self.assertEqual(self.allowance()["remaining"], 100)
        barrier = Barrier(2)
        product_id, component = self.product_line.pk, self.component

        def reserve(source_id):
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=10)
                try:
                    with transaction.atomic():
                        assert_tube_quantity_available(product_line_id=product_id,
                                                       requested={component: 60}, expected_revision=revision)
                        source = MetalProcessingSource.objects.get(pk=source_id)
                        source.reserved_pieces += 60
                        source.save(update_fields=["reserved_pieces"])
                    return "accepted"
                except (PreconditionFailed, ValidationError):
                    return "rejected"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve, source.pk) for source in (self.source, second_source)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ["accepted", "rejected"])
        self.assertEqual(sum(MetalProcessingSource.objects.values_list("reserved_pieces", flat=True)), 60)
        self.assertEqual(self.allowance()["remaining"], 40)

    def test_reservation_and_report_reduction_cannot_both_break_shared_coverage(self):
        report = self.report()
        report_line = report.lines.get(work_item=self.items[0])
        revision = self.context()["revision"]
        product_id, component, source_id = self.product_line.pk, self.component, self.source.pk
        barrier = Barrier(2)

        def attempt(action):
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=10)
                try:
                    with transaction.atomic():
                        if action == "reserve":
                            assert_tube_quantity_available(
                                product_line_id=product_id, requested={component: 60},
                                expected_revision=revision)
                            # 模拟 S3 调用者在同一事务落有效预留，未接入页面/API。
                            MetalProcessingSource.objects.filter(pk=source_id).update(reserved_pieces=60)
                        else:
                            lock_tube_product_scope(product_id)
                            WorkReportLine.objects.filter(pk=report_line.pk).update(quantity=50, amount=100)
                            WorkReport.objects.filter(pk=report.pk).update(total_amount=500, revision=2)
                            # 对应报工服务保存后、提交事务前的真实保护函数。
                            assert_tube_reports_cover_usage(product_id)
                    return action, "accepted"
                except (PreconditionFailed, ValidationError):
                    return action, "rejected"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, action) for action in ("reserve", "reduce")]
            results = dict(future.result(timeout=20) for future in futures)
        self.assertCountEqual(results.values(), ["accepted", "rejected"])
        allowance = self.allowance()
        self.assertLessEqual(allowance["used"], allowance["reported_minimum"])
        self.source.refresh_from_db()
        report_line.refresh_from_db()
        report.refresh_from_db()
        if results["reserve"] == "accepted":
            self.assertEqual((self.source.reserved_pieces, report_line.quantity, report.total_amount),
                             (60, Decimal("100"), Decimal("600")))
        else:
            self.assertEqual((self.source.reserved_pieces, report_line.quantity, report.total_amount),
                             (0, Decimal("50"), Decimal("500")))
