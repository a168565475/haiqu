from apps.workshop_config.tests.factories import production_employee
import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine, BomSection
from apps.boms.material_flow_calculations import pipe_plan
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone
from apps.inventory.public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_pipe_stock_foundation import PipeFixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_scheduling.services import create_schedule
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.procurement.models import PurchaseOrder
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft, Workshop

from ..material_flow import pipe_specs
from ..models import MaterialIssue, MaterialIssueBatchAllocation, MaterialIssuePublicStockAllocation
from ..public_issue_services import public_issue_quantity_context, public_line_quantities, public_pipe_requirement_rows
from ..public_semi_requirements import build_public_semi_specs
from ..services import confirm_issue, create_issue, preview_issue, return_issue, submit_issue


class PublicIssueFixture(PipeFixture):
    def setUp(self):
        super().setUp()
        self.bom_line.section.section_type = "PROFILE"
        self.bom_line.section.save(update_fields=["section_type"])
        self.bom_line.raw_values.update(tube_shape="圆管", tube_diameter="25", tube_thickness="1.0", tube_coating_color="黑色")
        self.bom_line.save(update_fields=["raw_values"])
        self.pipe_identity = build_pipe_stock_identity(raw_material=self.raw_material,
            raw_bar_length_m=self.bom_line.raw_bar_length_m, unit=self.raw_material.unit)
        self.public_pipe = self.credit(self.pipe_identity, self.zone, 10).balance
        self.semi_warehouse = Warehouse.objects.create(warehouse_number="S4SEMI", warehouse_name="公共半成品仓", warehouse_type="SEMI_FINISHED")
        self.semi_zone = WarehouseZone.objects.create(warehouse=self.semi_warehouse, zone_name="公共区")
        self.coating, _ = Craft.objects.get_or_create(outsourcing_code="POWDER_COATING", defaults={"name": "公共喷塑", "craft_type": "EXTERNAL"})
        self.piece_unit = ProductionUnit.objects.get(unit_name="支")
        self.semi_identity = build_semi_finished_identity(bom_line=self.bom_line, completed_craft=self.coating, unit=self.piece_unit)
        self.public_semi = self.credit(self.semi_identity, self.semi_zone, 100).balance
        self.assembly = Workshop.objects.get(name="装配车间")
        self.assembly_recipient = production_employee(workshop=self.assembly, position="领料员", name="公共半成品领料员", status="ACTIVE", is_supervisor=False)
        self.assembly_craft, _ = Craft.objects.get_or_create(plan_category="ASSEMBLY", defaults={"name": "公共装配", "craft_type": "INTERNAL", "workshop": self.assembly})
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.assembly_craft,
            defaults={"craft_type_snapshot": "INTERNAL", "craft_name_snapshot": self.assembly_craft.name, "plan_category": "ASSEMBLY"})

    def credit(self, identity, zone, quantity):
        return credit_public_stock(identity=identity, zone=zone, quantity=quantity, source_type="S4_FIXTURE",
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)

    def request(self, issue):
        return SimpleNamespace(user=self.user, headers={"If-Match": etag_for_instance(issue)})

    def scope(self):
        return SimpleNamespace(task=self.task, product_line=self.product_line, bom_line=self.bom_line, schedule_product=self.schedule_product)

    def other_scope(self):
        suffix = uuid.uuid4().hex[:8].upper()
        task = ProductionTask.objects.get(pk=self.task.pk)
        task.pk = None
        task.task_number, task.contract_number, task.order_number = f"S4TASK{suffix}", f"S4CONTRACT{suffix}", f"S4ORDER{suffix}"
        task.status = "READY"
        task.save()
        product = ProductionTaskProduct.objects.get(pk=self.product_line.pk)
        product.pk, product.production_task = None, task
        product.save()
        bom = Bom.objects.get(pk=self.bom.pk)
        bom.pk, bom.production_task, bom.product_line, bom.bom_number = None, task, product, f"S4BOM{suffix}"
        bom.save()
        section = BomSection.objects.get(pk=self.bom_line.section_id)
        section.pk, section.bom = None, bom
        section.save()
        line = BomLine.objects.get(pk=self.bom_line.pk)
        line.pk, line.section, line.component_identity = None, section, uuid.uuid4()
        line.save()
        purchase = PurchaseOrder.objects.get(production_task=self.task, status="COMPLETED")
        purchase.pk, purchase.production_task, purchase.order_number = None, task, f"S4PURCHASE{suffix}"
        purchase.production_task_number_snapshot = task.task_number
        purchase.sales_order_number_snapshot = task.order_number
        purchase.save()
        today = timezone.localdate()
        schedule = create_schedule(validated_data={"client_request_id": uuid.uuid4(), "production_task_id": task.pk,
            "source_revision_hash": "", "items": [{"product_line_id": product.pk, "planned_quantity": product.quantity,
                "craft_ids": {self.plan_craft.pk, self.assembly_craft.pk}, "material_inbound_date": today,
                "metal_return_date": today, "sewing_return_date": today, "finished_inbound_date": today}]}, actor_employee=self.employee)
        return SimpleNamespace(task=task, product_line=product, bom_line=line,
                               schedule_product=schedule.products.get(product_line=product, removed_at__isnull=True))

    def create(self, quantity="12", *, semi=False, scope=None, rows=None):
        scope = scope or self.scope()
        specs, blockers = (build_public_semi_specs if semi else pipe_specs)(scope.task.pk, scope.product_line.pk)
        self.assertFalse(blockers, blockers)
        return create_issue(validated_data={"client_request_id": uuid.uuid4(), "schedule_product_id": scope.schedule_product.pk,
            "plan_category": "ASSEMBLY" if semi else "METAL", "production_task_id": scope.task.pk,
            "product_line_id": scope.product_line.pk, "workshop_id": (self.assembly if semi else self.workshop).pk,
            "recipient_workshop_employee_id": (self.assembly_recipient if semi else self.recipient).pk,
            "issue_at": timezone.now(), "remark": "公共库存事务测试",
            "lines": rows or [{"requirement_id": specs[0]["id"], "requested_quantity": Decimal(quantity)}]}, actor_employee=self.employee)

    def submit(self, issue):
        issue.refresh_from_db()
        return submit_issue(issue_id=issue.pk, actor_employee=self.employee, request=self.request(issue))

    def confirm(self, issue, request_id=None):
        issue.refresh_from_db()
        return confirm_issue(issue_id=issue.pk, request_id=request_id or uuid.uuid4(), actor_employee=self.employee, request=self.request(issue))

    def assert_code(self, code, callback):
        with self.assertRaises(ValidationError) as caught:
            callback()
        self.assertEqual(caught.exception.api_error_code, code)


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicIssueServiceTests(PublicIssueFixture, TestCase):
    def test_pipe_candidates_use_current_confirmed_bom_allowance_without_writing_requirement(self):
        self.requirement.internal_issued_quantity = 12
        self.requirement.outsourcing_issued_quantity = 6
        self.requirement.save(update_fields=["internal_issued_quantity", "outsourcing_issued_quantity"])
        old_required = self.requirement.required_quantity
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=3, pieces_per_bar=6, order_quantity=1000)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.save()
        with CaptureQueriesContext(connection) as queries:
            rows, blockers = public_pipe_requirement_rows(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        self.assertEqual(Decimal(rows[0]["required_quantity"]), plan["allowance_pieces"])
        self.assertEqual(Decimal(rows[0]["order_remaining"]), plan["allowance_pieces"] - 18)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.required_quantity, old_required)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for query in queries))

    def test_pipe_create_submit_preview_confirm_uses_public_balance_and_freezes_actuals(self):
        legacy_before = self.balance().quantity
        with patch("apps.material_issues.material_flow.batch_candidates", side_effect=AssertionError("不可查询采购批次")):
            issue = self.submit(self.create("12"))
            preview = preview_issue(issue)
            self.assertTrue(preview["can_confirm"], preview)
            self.assertEqual(Decimal(preview["lines"][0]["bar_count"]), 2)
            issue = self.confirm(issue)
        self.assertEqual((issue.stock_mode, issue.status), ("PUBLIC_V2", "ISSUED"))
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (8, Decimal("24.40")))
        self.assertEqual(self.balance().quantity, legacy_before)
        self.assertFalse(MaterialIssueBatchAllocation.objects.filter(line__issue=issue).exists())
        row = issue.lines.get()
        self.assertEqual(row.issued_quantity, 12)
        allocation = row.public_stock_allocations.get()
        self.assertEqual((allocation.requested_quantity, allocation.stock_quantity, allocation.meter_quantity), (12, 2, Decimal("6.10")))
        frozen = issue.audit_events.get(action="ISSUED").snapshot["issued_line_snapshots"][0]
        self.assertEqual((Decimal(frozen["stock_before"]), Decimal(frozen["stock_after"])), (60, 48))
        self.assertNotIn("inbound_line_id", str(frozen))

    def test_pending_reserves_without_deducting_and_return_releases_it(self):
        first = self.submit(self.create("36"))
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)
        second = self.create("30")
        self.assert_code("PENDING_ISSUE_CONFLICT", lambda: self.submit(second))
        first.refresh_from_db()
        return_issue(issue_id=first.pk, reason="调整领料", actor_employee=self.employee, request=self.request(first))
        self.assertEqual(self.submit(second).status, "PENDING_REVIEW")

    def test_stock_quantity_is_physical_and_pending_is_displayed_separately(self):
        self.submit(self.create("12"))
        second = self.create("6")
        values = public_line_quantities(second.lines.get(), context=public_issue_quantity_context(second, exclude_issue_id=second.pk))
        self.assertEqual((Decimal(values["available_stock"]), Decimal(values["public_pending_quantity"]), Decimal(values["max_issue_quantity"])), (60, 12, 48))

    def test_legacy_issued_outsourcing_and_pending_reduce_the_same_raw_allowance(self):
        self.requirement.internal_issued_quantity = 1980
        self.requirement.outsourcing_issued_quantity = 24
        self.requirement.save(update_fields=["internal_issued_quantity", "outsourcing_issued_quantity"])
        with override_settings(PUBLIC_STOCK_ISSUES_ENABLED=False):
            legacy = self.submit(self.create("12"))
        self.assertEqual(legacy.stock_mode, "LEGACY")
        public = self.create("12")
        self.assert_code("PENDING_ISSUE_CONFLICT", lambda: self.submit(public))
        public_small = self.submit(self.create("6"))
        self.confirm(public_small)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.internal_issued_quantity, 1986)

    def test_pipe_must_be_whole_bar_and_multiple_components_share_one_stock_pool(self):
        self.assert_code("PIPE_WHOLE_BAR_REQUIRED", lambda: self.create("7"))
        second = BomLine.objects.get(pk=self.bom_line.pk)
        second.pk, second.line_number, second.component_identity = None, 2, uuid.uuid4()
        second.save()
        specs, _ = pipe_specs(self.task.pk, self.product_line.pk)
        issue = self.create(rows=[{"requirement_id": item["id"], "requested_quantity": Decimal(36)} for item in specs])
        self.assert_code("STOCK_INSUFFICIENT", lambda: self.submit(issue))

    def test_multiple_public_zones_are_recorded_without_purchase_batch(self):
        other_zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="二楼")
        self.credit(self.pipe_identity, other_zone, 2)
        issue = self.confirm(self.submit(self.create("72")))
        allocations = list(issue.lines.get().public_stock_allocations.all())
        self.assertEqual(len(allocations), 2)
        self.assertEqual(sum(row.stock_quantity for row in allocations), 12)
        self.assertEqual(sum(row.meter_quantity for row in allocations), Decimal("36.60"))
        self.assertTrue(all(row.movement_id for row in allocations))

    def test_different_cutting_ratios_in_one_raw_pool_reserve_and_debit_total_bars(self):
        second = BomLine.objects.get(pk=self.bom_line.pk)
        second.pk, second.line_number, second.component_identity = None, 2, uuid.uuid4()
        plan = pipe_plan(cutting_length_mm=600, pieces_per_product=2, pieces_per_bar=5, order_quantity=1000)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(second, field, plan[field])
        second.save()
        specs, blockers = pipe_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        by_line = {item["line"].pk: item for item in specs}
        original_id = by_line[self.bom_line.pk]["id"]
        second_id = by_line[second.pk]["id"]
        issue = self.submit(self.create(rows=[
            {"requirement_id": original_id, "requested_quantity": Decimal(18)},
            {"requirement_id": second_id, "requested_quantity": Decimal(20)},
        ]))
        excess = self.create(rows=[{"requirement_id": original_id, "requested_quantity": Decimal(24)}])
        self.assert_code("PENDING_ISSUE_CONFLICT", lambda: self.submit(excess))
        self.confirm(issue)
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (3, Decimal("9.15")))
        allocations = list(MaterialIssuePublicStockAllocation.objects.filter(line__issue=issue))
        self.assertCountEqual([(row.requested_quantity, row.stock_quantity) for row in allocations], [(18, 3), (20, 4)])

    def test_semi_uses_receiving_order_quota_without_second_raw_deduction(self):
        self.requirement.internal_issued_quantity = self.requirement.required_quantity
        self.requirement.save(update_fields=["internal_issued_quantity"])
        issue = self.confirm(self.submit(self.create("20", semi=True)))
        line = issue.lines.get()
        line.semi_requirement.refresh_from_db()
        self.assertEqual((line.semi_requirement.required_quantity, line.semi_requirement.internal_issued_quantity), (2000, 20))
        self.public_pipe.refresh_from_db()
        self.public_semi.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_semi.quantity), (10, 80))
        allocation = line.public_stock_allocations.get()
        self.assertIsNone(allocation.meter_quantity)
        self.assertEqual(allocation.stock_quantity, 20)

    def test_cross_order_semi_uses_common_stock_with_independent_demand(self):
        other = self.other_scope()
        issue = self.confirm(self.submit(self.create("20", semi=True, scope=other)))
        line = issue.lines.get()
        self.assertEqual(line.semi_requirement.production_task_id, other.task.pk)
        movement = line.public_stock_allocations.get().movement
        self.assertEqual((movement.production_task_id, movement.product_line_id), (other.task.pk, other.product_line.pk))
        self.public_semi.refresh_from_db()
        self.assertEqual(self.public_semi.quantity, 80)

    def test_semi_stock_and_order_pending_are_both_checked(self):
        too_large = self.create("2001", semi=True)
        self.assert_code("ORDER_ALLOWANCE_EXCEEDED", lambda: self.submit(too_large))
        self.submit(self.create("70", semi=True))
        second = self.create("40", semi=True)
        self.assert_code("PENDING_ISSUE_CONFLICT", lambda: self.submit(second))
        self.assert_code("INTEGER_REQUIRED", lambda: self.create("0.5", semi=True))
        self.assert_code("PENDING_ISSUE_CONFLICT", lambda: self.submit(too_large))

    def test_same_component_coated_and_uncoated_requests_share_one_order_quota(self):
        self.raw_material.color_snapshot = "黑色"
        self.raw_material.save(update_fields=["color_snapshot"])
        self.bom_line.raw_values["source_inventory_material_id"] = str(self.raw_material.pk)
        self.bom_line.save(update_fields=["raw_values"])
        metal, _ = Craft.objects.get_or_create(
            plan_category="METAL",
            defaults={"name": "公共金工半成品", "craft_type": "INTERNAL", "workshop": self.workshop},
        )
        metal_identity = build_semi_finished_identity(
            bom_line=self.bom_line, completed_craft=metal, unit=self.piece_unit,
        )
        # 两个状态共用同一 BOM 部位额度，但库存池彼此独立。
        self.public_semi.quantity = 2000
        self.public_semi.save(update_fields=["quantity"])
        self.credit(metal_identity, self.semi_zone, 2000)
        specs, blockers = build_public_semi_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        self.assertEqual(len(specs), 2)
        issue = self.create("1100", semi=True, rows=[
            {"requirement_id": spec["id"], "requested_quantity": Decimal("1100")}
            for spec in specs
        ])
        self.assertEqual(issue.lines.count(), 2)
        self.assertEqual({line.semi_requirement.required_quantity for line in issue.lines.all()}, {Decimal("2000")})
        self.assert_code("ORDER_ALLOWANCE_EXCEEDED", lambda: self.submit(issue))

    def test_confirm_repeat_returns_original_success_without_second_debit(self):
        issue = self.submit(self.create("12"))
        request_id = uuid.uuid4()
        self.confirm(issue, request_id)
        self.confirm(issue, request_id)
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 8)
        self.assertEqual(PublicStockMovement.objects.filter(source_type="MATERIAL_ISSUE", source_id=issue.pk).count(), 1)

    def test_late_ledger_failure_rolls_back_stock_quota_allocations_and_status(self):
        issue = self.submit(self.create("12"))
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create", side_effect=RuntimeError("模拟记账失败")):
            with self.assertRaisesMessage(RuntimeError, "模拟记账失败"):
                self.confirm(issue)
        self.public_pipe.refresh_from_db()
        self.requirement.refresh_from_db()
        issue.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.requirement.internal_issued_quantity, issue.status), (10, 0, "PENDING_REVIEW"))
        self.assertFalse(MaterialIssuePublicStockAllocation.objects.filter(line__issue=issue).exists())
        self.assertFalse(issue.audit_events.filter(action="ISSUED").exists())


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class PublicIssueConcurrencyTests(PublicIssueFixture, TransactionTestCase):
    serialized_rollback = True

    def together(self, calls):
        barrier, results = threading.Barrier(len(calls)), []

        def worker(callback):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                barrier.wait(timeout=5)
                results.append(("OK", callback().pk))
            except ValidationError as error:
                results.append((error.api_error_code, None))
            except Exception as error:
                results.append((f"{type(error).__name__}: {error}", None))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(callback,)) for callback in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        return results

    def test_cross_order_submissions_cannot_reserve_the_same_public_stock_twice(self):
        other = self.other_scope()
        first, second = self.create("42"), self.create("42", scope=other)
        results = self.together([lambda: self.submit(first), lambda: self.submit(second)])
        self.assertCountEqual([row[0] for row in results], ["OK", "PENDING_ISSUE_CONFLICT"])
        self.public_pipe.refresh_from_db()
        self.assertEqual(self.public_pipe.quantity, 10)

    def test_cross_order_semi_submissions_cannot_reserve_same_public_pool_twice(self):
        other = self.other_scope()
        first, second = self.create("70", semi=True), self.create("70", semi=True, scope=other)
        results = self.together([lambda: self.submit(first), lambda: self.submit(second)])
        self.assertCountEqual([row[0] for row in results], ["OK", "PENDING_ISSUE_CONFLICT"])
        self.public_semi.refresh_from_db()
        self.assertEqual(self.public_semi.quantity, 100)

    def test_credit_holds_source_and_location_before_balance_and_issue_waits_safely(self):
        from apps.inventory import public_stock_services as ledger
        issue = self.submit(self.create("12"))
        credit_has_balance, issue_has_zone = threading.Event(), threading.Event()
        results = []
        original_record = ledger._record

        def paused_record(**kwargs):
            if kwargs["source"]["source_type"] == "S4_CONCURRENT_CREDIT":
                credit_has_balance.set()
                if not issue_has_zone.wait(timeout=8):
                    raise AssertionError("领料事务未能取得库区锁")
            return original_record(**kwargs)

        def receive():
            connections.close_all()
            try:
                credit_public_stock(identity=self.pipe_identity, zone=self.zone, quantity=2,
                    source_type="S4_CONCURRENT_CREDIT", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee,
                    production_task=self.task, product_line=self.product_line, bom_line=self.bom_line)
                results.append("CREDIT_OK")
            except Exception as error:
                results.append(f"CREDIT_{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        def issue_stock():
            connections.close_all()
            try:
                if not credit_has_balance.wait(timeout=8):
                    raise AssertionError("入库事务未取得余额锁")
                with transaction.atomic():
                    with connections["default"].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                    # 新完整流程在余额之前固定锁父仓与区，阻止回货期间停用空库区。
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        Warehouse.objects.select_for_update(of=("self",), nowait=True).get(pk=self.zone.warehouse_id)
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        WarehouseZone.objects.select_for_update(of=("self",), nowait=True).get(pk=self.zone.pk)
                    # 来源订单同样在余额之前锁定；失败保存点不保留任何逆序锁。
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        ProductionTask.objects.select_for_update(of=("self",), nowait=True).get(pk=self.task.pk)
                    issue_has_zone.set()
                    self.confirm(issue)
                results.append("ISSUE_OK")
            except Exception as error:
                results.append(f"ISSUE_{type(error).__name__}: {error}")
            finally:
                issue_has_zone.set()
                connections.close_all()

        with patch.object(ledger, "_record", side_effect=paused_record):
            threads = [threading.Thread(target=receive), threading.Thread(target=issue_stock)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertCountEqual(results, ["CREDIT_OK", "ISSUE_OK"])
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (10, Decimal("30.50")))

    def test_two_orders_confirm_separate_pending_requests_without_overdraw(self):
        other = self.other_scope()
        first, second = self.submit(self.create("30")), self.submit(self.create("30", scope=other))
        results = self.together([lambda: self.confirm(first), lambda: self.confirm(second)])
        self.assertCountEqual([row[0] for row in results], ["OK", "OK"])
        self.public_pipe.refresh_from_db()
        self.assertEqual((self.public_pipe.quantity, self.public_pipe.meter_quantity), (0, Decimal("0.00")))
        self.assertEqual(MaterialIssue.objects.filter(pk__in=[first.pk, second.pk], status="ISSUED").count(), 2)

    def test_semi_issue_locks_bom_line_before_pool_when_credit_has_only_bom_source(self):
        from apps.material_issues import public_issue_services as issue_services
        issue = self.submit(self.create("20", semi=True))
        issue_before_pool, credit_attempting_bom = threading.Event(), threading.Event()
        results = []
        original_lock = issue_services._lock_public_issue_stock
        bom_table = BomLine._meta.db_table

        def paused_issue_lock(current_issue, lines):
            issue_before_pool.set()
            if not credit_attempting_bom.wait(timeout=8):
                raise AssertionError("半成品回货未进入 BOM 明细锁等待")
            return original_lock(current_issue, lines)

        def confirm():
            connections.close_all()
            try:
                self.confirm(issue)
                results.append("ISSUE_OK")
            except Exception as error:
                results.append(f"ISSUE_{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        def receive():
            connections.close_all()
            try:
                if not issue_before_pool.wait(timeout=8):
                    raise AssertionError("领料未进入公共库存池锁之前的阶段")
                with self.assertRaises(DatabaseError), transaction.atomic():
                    BomLine.objects.select_for_update(of=("self",), nowait=True).get(pk=self.bom_line.pk)

                def observe_parent_lock(execute, sql, params, many, context):
                    if f'FROM "{bom_table}"' in sql and "FOR NO KEY UPDATE" in sql:
                        credit_attempting_bom.set()
                    return execute(sql, params, many, context)

                with connections["default"].execute_wrapper(observe_parent_lock):
                    credit_public_stock(identity=self.semi_identity, zone=self.semi_zone, quantity=2,
                        source_type="S4_SEMI_BOM_ONLY", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                        actor_employee=self.employee, bom_line=self.bom_line)
                results.append("CREDIT_OK")
            except Exception as error:
                results.append(f"CREDIT_{type(error).__name__}: {error}")
            finally:
                credit_attempting_bom.set()
                connections.close_all()

        with patch.object(issue_services, "_lock_public_issue_stock", side_effect=paused_issue_lock):
            threads = [threading.Thread(target=confirm), threading.Thread(target=receive)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertCountEqual(results, ["ISSUE_OK", "CREDIT_OK"])
        self.public_semi.refresh_from_db()
        self.assertEqual(self.public_semi.quantity, 82)
