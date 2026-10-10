import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import pipe_plan
from apps.material_issues.tests import test_material_issue_api as issue_fixture
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft

from ..models import PublicStockBalance, PublicStockMovement, Warehouse, WarehouseZone
from ..public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity
from ..public_stock_services import available_public_stock, credit_public_stock, debit_public_stock


class PublicStockFixture:
    def setUp(self):
        # 复用既有资料准备方法，不继承其测试类，避免重复执行无关测试。
        issue_fixture.MaterialIssueApiTests.setUp(self)
        self.root_unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "PSROOT"})
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name="支", defaults={"unit_code": "PSPIECE"})
        self.raw_material.unit = self.root_unit
        self.raw_material.save(update_fields=["unit"])
        self.semi_warehouse = Warehouse.objects.create(
            warehouse_number="PSSEMI", warehouse_name="公共半成品测试仓", warehouse_type="SEMI_FINISHED",
        )
        self.semi_zone = WarehouseZone.objects.create(warehouse=self.semi_warehouse, zone_name="一楼")
        self.bom_line.section.section_type = "PROFILE"
        self.bom_line.section.save(update_fields=["section_type"])
        self.bom_line.category = "型材"
        self.bom_line.part_name = "前脚管"
        self.bom_line.material = "铁"
        self.bom_line.specification = "20*28*0.8*6140"
        plan = pipe_plan(cutting_length_mm=415, pieces_per_product=2, pieces_per_bar=6, order_quantity=500)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.raw_values = {
            "tube_shape": "矩形管", "tube_diameter": "20*28", "tube_thickness": "0.8",
            "tube_coating_color": "黑色",
        }
        self.bom_line.save()
        self.craft, _ = Craft.objects.get_or_create(
            outsourcing_code="POWDER_COATING",
            defaults={"name": "公共半成品喷塑", "craft_type": "EXTERNAL",
                      "created_by_employee": self.employee, "updated_by_employee": self.employee},
        )
        self.pipe_identity = self.pipe()
        self.semi_identity = build_semi_finished_identity(
            bom_line=self.bom_line, completed_craft=self.craft, unit=self.piece_unit,
        )

    def pipe(self, length="6.14"):
        return build_pipe_stock_identity(
            raw_material=self.raw_material, raw_bar_length_m=Decimal(length), unit=self.root_unit,
        )

    def source(self, **changes):
        return {
            "source_type": "TEST_PUBLIC_STOCK", "source_id": uuid.uuid4(), "source_line_id": uuid.uuid4(),
            "actor_employee": self.employee, **changes,
        }

    def credit(self, quantity=10, identity=None, zone=None, **source):
        return credit_public_stock(
            identity=identity or self.pipe_identity, zone=zone or self.zone,
            quantity=quantity, **(source or self.source()),
        )

    def debit(self, balance_id, quantity, **source):
        return debit_public_stock(balance_id=balance_id, quantity=quantity, **(source or self.source()))

    def assert_error(self, code, call):
        with self.assertRaises(ValidationError) as caught:
            call()
        self.assertEqual(caught.exception.api_error_code, code)


class PublicStockServiceTests(PublicStockFixture, TestCase):
    def test_json_string_identity_keys_match_database_uuids_on_credit_and_replay(self):
        self.assertIsInstance(self.pipe_identity["unit_id"], str)
        self.assertIsInstance(self.pipe_identity["raw_material_id"], str)
        source = self.source()
        first = self.credit(5, **source)
        self.assertEqual(self.credit(5, **source).pk, first.pk)
        self.assertEqual(self.credit(7).balance_id, first.balance_id)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 12)
        self.assertEqual(PublicStockMovement.objects.count(), 2)

    def test_orders_share_pipe_balance_and_keep_source_history(self):
        task2 = ProductionTask.objects.get(pk=self.task.pk)
        task2.pk = None
        task2.task_number = "PS-TASK-2"
        task2.contract_number = "PS-CONTRACT-2"
        task2.order_number = "PS-ORDER-2"
        task2.save()
        first = self.credit(5, **self.source(production_task=self.task, snapshot={"arrival": "订单 A"}))
        second = self.credit(7, **self.source(production_task=task2, snapshot={"arrival": "订单 B"}))
        self.assertEqual(first.balance_id, second.balance_id)
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual((balance.quantity, balance.meter_quantity), (12, Decimal("73.68")))
        self.assertEqual(set(balance.movements.values_list("production_task_id", flat=True)), {self.task.pk, task2.pk})
        self.assertEqual(first.snapshot, {"arrival": "订单 A"})
        self.assertEqual(second.snapshot, {"arrival": "订单 B"})

    def test_different_raw_bar_lengths_remain_separate(self):
        short = self.credit(5)
        long = self.credit(7, identity=self.pipe("6.20"))
        self.assertNotEqual(short.balance_id, long.balance_id)
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 5)
        self.assertEqual(available_public_stock(identity=self.pipe("6.20")), 7)

    def test_pipe_debit_updates_whole_bars_and_meters_together(self):
        inbound = self.credit(10)
        out = self.debit(inbound.balance_id, 3)
        self.assertEqual((out.before_quantity, out.after_quantity), (10, 7))
        self.assertEqual((out.meter_quantity, out.before_meter_quantity, out.after_meter_quantity),
                         (Decimal("18.42"), Decimal("61.40"), Decimal("42.98")))
        balance = PublicStockBalance.objects.get(pk=inbound.balance_id)
        self.assertEqual((balance.quantity, balance.meter_quantity), (7, Decimal("42.98")))

    def test_retry_returns_original_event_after_zero_balance(self):
        incoming = self.source()
        first = self.credit(10, **incoming)
        self.assertEqual(self.credit(10, **incoming).pk, first.pk)
        outgoing = self.source(snapshot={"requested_pieces": 60, "deducted_bars": 10})
        out = self.debit(first.balance_id, 10, **outgoing)
        self.assertEqual(self.debit(first.balance_id, 10, **outgoing).pk, out.pk)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)

    def test_credit_same_source_rejects_quantity_identity_order_or_snapshot_change(self):
        source = self.source(snapshot={"legacy_source": {"version": 1}})
        first = self.credit(10, **source)
        attempts = [
            lambda: self.credit(11, **source),
            lambda: self.credit(10, identity=self.pipe("6.20"), **source),
            lambda: self.credit(10, **{**source, "source_id": uuid.uuid4()}),
            lambda: self.credit(10, **{**source, "production_task": self.task}),
            lambda: self.credit(10, **{**source, "snapshot": {"legacy_source": {"version": 2}}}),
        ]
        for attempt in attempts:
            self.assert_error("IDEMPOTENCY_CONFLICT", attempt)
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 10)

    def test_same_source_cannot_be_replayed_against_a_different_zone_or_quality(self):
        other_zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="二楼")
        source = self.source()
        self.credit(10, **source)
        self.assert_error("IDEMPOTENCY_CONFLICT", lambda: self.credit(10, zone=other_zone, **source))
        self.assert_error("IDEMPOTENCY_CONFLICT", lambda: self.credit(10, **{**source, "quality": "DEFECTIVE"}))

    def test_debit_same_source_cannot_switch_balance(self):
        first = self.credit(10)
        second = self.credit(10, identity=self.pipe("6.20"))
        source = self.source()
        self.debit(first.balance_id, 2, **source)
        self.assert_error("IDEMPOTENCY_CONFLICT", lambda: self.debit(second.balance_id, 2, **source))
        self.assertEqual(PublicStockBalance.objects.get(pk=second.balance_id).quantity, 10)

    def test_insufficient_stock_rolls_back_without_new_movement(self):
        first = self.credit(10)
        self.assert_error("STOCK_INSUFFICIENT", lambda: self.debit(first.balance_id, 11))
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual((balance.quantity, balance.meter_quantity), (10, Decimal("61.40")))
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_outer_transaction_failure_rolls_back_all_prior_debits(self):
        first = self.credit(10)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.debit(first.balance_id, 3)
            self.debit(first.balance_id, 8)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 10)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_movement_failure_rolls_back_existing_quantity_meters_and_version(self):
        first = self.credit(10)
        original = PublicStockBalance.objects.values("quantity", "meter_quantity", "version").get(pk=first.balance_id)
        for operation, call in (("入库", lambda: self.credit(3)),
                                ("出库", lambda: self.debit(first.balance_id, 3))):
            with self.subTest(operation=operation):
                with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create",
                           side_effect=RuntimeError("模拟流水保存失败")):
                    with self.assertRaisesMessage(RuntimeError, "模拟流水保存失败"):
                        call()
                current = PublicStockBalance.objects.values("quantity", "meter_quantity", "version").get(pk=first.balance_id)
                self.assertEqual(current, original)
                self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_first_credit_movement_failure_leaves_no_zero_balance(self):
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create",
                   side_effect=RuntimeError("模拟首次流水保存失败")):
            with self.assertRaisesMessage(RuntimeError, "模拟首次流水保存失败"):
                self.credit(10)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_real_foreign_key_context_must_describe_the_same_order_and_product(self):
        other_task = ProductionTask.objects.get(pk=self.task.pk)
        other_task.pk = None
        other_task.task_number = "PS-CONTEXT-OTHER"
        other_task.contract_number = "PS-CONTEXT-CONTRACT"
        other_task.order_number = "PS-CONTEXT-ORDER"
        other_task.save()
        other_product = ProductionTaskProduct.objects.get(pk=self.product_line.pk)
        other_product.pk = None
        other_product.line_number = 2
        other_product.save()
        first = self.credit(10)
        contexts = [
            {"production_task": other_task, "product_line": self.product_line},
            {"production_task": other_task, "bom_line": self.bom_line},
            {"production_task": self.task, "product_line": other_product, "bom_line": self.bom_line},
        ]
        for context in contexts:
            with self.subTest(context=list(context)):
                self.assert_error("SOURCE_INVALID", lambda: self.credit(1, **self.source(**context)))
                self.assert_error("SOURCE_INVALID", lambda: self.debit(first.balance_id, 1, **self.source(**context)))
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.version),
                         (10, Decimal("61.40"), first.balance.version))
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_semi_counts_pieces_without_raw_pipe_fields(self):
        first = self.credit(30, identity=self.semi_identity, zone=self.semi_zone)
        out = self.debit(first.balance_id, 12)
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual(balance.quantity, 18)
        self.assertIsNone(balance.raw_material_id)
        self.assertIsNone(balance.raw_bar_length_m)
        self.assertIsNone(balance.meter_quantity)
        self.assertIsNone(out.meter_quantity)
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.debit(first.balance_id, Decimal("0.5")))

    def test_two_real_orders_share_semi_stock_and_second_order_uses_first_order_stock(self):
        other_task = ProductionTask.objects.get(pk=self.task.pk)
        other_task.pk = None
        other_task.task_number = "PS-SEMI-TASK-B"
        other_task.contract_number = "PS-SEMI-CONTRACT-B"
        other_task.order_number = "PS-SEMI-ORDER-B"
        other_task.save()
        first = self.credit(10, identity=self.semi_identity, zone=self.semi_zone,
                            **self.source(production_task=self.task, snapshot={"return_order": "A"}))
        second = self.credit(2, identity=self.semi_identity, zone=self.semi_zone,
                             **self.source(production_task=other_task, snapshot={"return_order": "B"}))
        self.assertEqual(first.balance_id, second.balance_id)
        # B 订单自身只回货 2 支，却可从公共池领 11 支，证明库存未按来源订单隔开。
        out = self.debit(first.balance_id, 11, **self.source(production_task=other_task, snapshot={"issue_order": "B"}))
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 1)
        self.assertEqual(available_public_stock(identity=self.semi_identity), 1)
        self.assertEqual(first.production_task_id, self.task.pk)
        self.assertEqual((second.production_task_id, out.production_task_id), (other_task.pk, other_task.pk))
        self.assertEqual(out.snapshot, {"issue_order": "B"})
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 3)

    def test_cutting_stock_receives_and_issues_whole_sets_without_meter_balance(self):
        set_unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "PSSET"})
        cutting_craft, _ = Craft.objects.get_or_create(
            outsourcing_code="CUTTING", defaults={"craft_type": "EXTERNAL", "name": "公共套库存裁剪"},
        )
        bom_id = uuid.uuid4()
        fabric = SimpleNamespace(
            section=SimpleNamespace(section_type="FABRIC", title="面料类", bom_id=bom_id),
            material="PE", specification="600D",
            raw_values={"fabric_color_name": "绿色", "fabric_color_code": "5865C", "fabric_color_card": "潘通"},
        )
        cutting = SimpleNamespace(
            section=SimpleNamespace(section_type="FABRIC", title="裁剪明细", bom_id=bom_id),
            category="委外布面", part_name="椅面", material="PE", specification="450*500",
            cutting_pieces_per_set=2, fabric_source_line=fabric,
            raw_values={"cutting_category": "委外布面", "cutting_color": "绿色"},
        )
        identity = build_semi_finished_identity(bom_line=cutting, completed_craft=cutting_craft, unit=set_unit)
        first = self.credit(10, identity=identity, zone=self.semi_zone)
        out = self.debit(first.balance_id, 4)
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual((balance.quantity, balance.unit_id), (6, set_unit.pk))
        self.assertEqual(balance.identity_snapshot["pieces_per_set"], 2)
        for row in (balance, first, out):
            self.assertIsNone(row.meter_quantity)
        self.assertIsNone(out.before_meter_quantity)
        self.assertIsNone(out.after_meter_quantity)
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.credit("0.5", identity=identity, zone=self.semi_zone))
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.debit(first.balance_id, "0.5"))
        self.assertEqual(available_public_stock(identity=identity), 6)

    def test_database_rejects_fractional_bar_or_inconsistent_meter_balance(self):
        first = self.credit(10)
        for changes in ({"quantity": Decimal("0.5"), "meter_quantity": Decimal("3.07")},
                        {"meter_quantity": Decimal("60.00")}):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    PublicStockBalance.objects.filter(pk=first.balance_id).update(**changes)
        balance = PublicStockBalance.objects.get(pk=first.balance_id)
        self.assertEqual((balance.quantity, balance.meter_quantity), (10, Decimal("61.40")))

    def test_database_rejects_wrong_movement_quantity_or_meter_equation(self):
        first = self.credit(10)
        for changes in ({"after_quantity": 11}, {"after_meter_quantity": Decimal("61.41")}):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    PublicStockMovement.objects.filter(pk=first.pk).update(**changes)
        first.refresh_from_db()
        self.assertEqual((first.before_quantity, first.after_quantity, first.after_meter_quantity),
                         (0, 10, Decimal("61.40")))

    def test_database_source_uniqueness_also_applies_across_different_balances(self):
        source = self.source()
        first = self.credit(10, **source)
        other = self.credit(10, identity=self.pipe("6.20"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            PublicStockMovement.objects.create(
                balance_id=other.balance_id, direction="IN", quantity=1,
                before_quantity=10, after_quantity=11, meter_quantity=Decimal("6.20"),
                before_meter_quantity=Decimal("62.00"), after_meter_quantity=Decimal("68.20"), **source,
            )
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(PublicStockMovement.objects.get(pk=first.pk).balance_id, first.balance_id)

    def test_invalid_or_fractional_quantities_never_create_balance(self):
        for value in (0, -1, "bad", "NaN", "sNaN", "Infinity", "-Infinity", True, 0.1,
                      "0.00001", "100000000000000"):
            with self.subTest(quantity=value):
                self.assert_error("QUANTITY_INVALID", lambda: self.credit(value))
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.credit("1.5"))
        self.assert_error("WHOLE_QUANTITY_REQUIRED", lambda: self.credit("1.5", identity=self.semi_identity, zone=self.semi_zone))
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_quantity_overflow_rolls_back_existing_balance(self):
        first = self.credit(Decimal("99999999999999"))
        self.assert_error("QUANTITY_OVERFLOW", lambda: self.credit(1))
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, Decimal("99999999999999"))
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_inactive_location_and_unit_cannot_be_used(self):
        first = self.credit(10)
        self.zone.status = "DISABLED"
        self.zone.save(update_fields=["status"])
        self.assert_error("ZONE_UNAVAILABLE", lambda: self.credit(1))
        self.assert_error("ZONE_UNAVAILABLE", lambda: self.debit(first.balance_id, 1))
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)
        self.zone.status = "ACTIVE"
        self.zone.save(update_fields=["status"])
        self.root_unit.status = "INACTIVE"
        self.root_unit.save(update_fields=["status"])
        self.assert_error("UNIT_UNAVAILABLE", lambda: self.credit(1))
        self.assert_error("UNIT_UNAVAILABLE", lambda: self.debit(first.balance_id, 1))

    def test_renamed_semi_unit_cannot_change_frozen_piece_meaning(self):
        first = self.credit(10, identity=self.semi_identity, zone=self.semi_zone)
        self.piece_unit.unit_name = "变更后的单位"
        self.piece_unit.save(update_fields=["unit_name"])
        self.assert_error("UNIT_MISMATCH", lambda: self.credit(1, identity=self.semi_identity, zone=self.semi_zone))
        self.assert_error("UNIT_MISMATCH", lambda: self.debit(first.balance_id, 1))
        self.assertEqual(available_public_stock(identity=self.semi_identity), 0)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 10)

    def test_archived_or_unit_changed_raw_material_cannot_receive_or_issue(self):
        first = self.credit(10)
        self.raw_material.unit = self.piece_unit
        self.raw_material.save(update_fields=["unit"])
        self.assert_error("UNIT_MISMATCH", lambda: self.credit(1))
        self.assert_error("UNIT_MISMATCH", lambda: self.debit(first.balance_id, 1))
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)
        self.raw_material.unit = self.root_unit
        self.raw_material.archived_at = timezone.now()
        self.raw_material.save(update_fields=["unit", "archived_at"])
        self.assert_error("MATERIAL_UNAVAILABLE", lambda: self.credit(1))
        self.assert_error("MATERIAL_UNAVAILABLE", lambda: self.debit(first.balance_id, 1))
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 10)

    def test_raw_bar_length_must_fit_database_precision_without_rounding(self):
        oversized = self.pipe("10000000000000000")
        self.assert_error("PIPE_LENGTH_INVALID", lambda: self.credit(1, identity=oversized))
        self.assertFalse(PublicStockBalance.objects.exists())
        largest = self.credit(1, identity=self.pipe("9999999999999999.99"))
        self.assertEqual(largest.after_meter_quantity, Decimal("9999999999999999.99"))

    def test_warehouse_scope_and_quality_are_validated(self):
        self.assert_error("WAREHOUSE_SCOPE_INVALID", lambda: self.credit(1, zone=self.semi_zone))
        self.assert_error("WAREHOUSE_SCOPE_INVALID", lambda: self.credit(1, identity=self.semi_identity))
        self.assert_error("QUALITY_INVALID", lambda: self.credit(1, **self.source(quality="UNKNOWN")))
        first = self.credit(3, **self.source(quality="DEFECTIVE"))
        self.assert_error("QUALITY_UNAVAILABLE", lambda: self.debit(first.balance_id, 1))
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)

    def test_only_public_balance_is_counted_and_zones_can_be_filtered(self):
        # 既有 fixture 已有 600 的旧普通库存，但公共可用量必须从零开始。
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 0)
        second_zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="二楼")
        self.credit(3)
        self.credit(7, zone=second_zone)
        self.assertEqual(available_public_stock(identity=self.pipe_identity), 10)
        self.assertEqual(available_public_stock(identity=self.pipe_identity, zone_id=self.zone.pk), 3)

    def test_invalid_context_and_snapshot_do_not_partially_write(self):
        self.assert_error("SOURCE_INVALID", lambda: self.credit(1, **self.source(actor_employee=uuid.uuid4())))
        self.assert_error("SOURCE_INVALID", lambda: self.credit(1, **self.source(source_line_id="bad")))
        self.assert_error("SOURCE_INVALID", lambda: self.credit(1, **self.source(source_type="")))
        self.assert_error("SNAPSHOT_INVALID", lambda: self.credit(1, **self.source(snapshot={"bad": float("nan")})))
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())


class PublicStockConcurrencyTests(PublicStockFixture, TransactionTestCase):
    serialized_rollback = True

    def run_together(self, calls):
        barrier = threading.Barrier(len(calls))
        results = []

        def run(call):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=5)
                movement = call()
                results.append(("OK", movement.pk))
            except ValidationError as error:
                results.append((error.api_error_code, None))
            except Exception as error:
                results.append((f"{type(error).__name__}: {error}", None))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        return results

    def test_concurrent_first_credits_create_one_balance(self):
        result = self.run_together([lambda: self.credit(10), lambda: self.credit(7)])
        self.assertCountEqual([item[0] for item in result], ["OK", "OK"])
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 17)
        self.assertEqual(PublicStockMovement.objects.count(), 2)

    def test_concurrent_debits_cannot_overspend(self):
        first = self.credit(10)
        result = self.run_together([
            lambda: self.debit(first.balance_id, 7), lambda: self.debit(first.balance_id, 7),
        ])
        self.assertCountEqual([item[0] for item in result], ["OK", "STOCK_INSUFFICIENT"])
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 3)
        self.assertEqual(PublicStockMovement.objects.count(), 2)

    def test_concurrent_identical_source_credits_record_once(self):
        source = self.source()
        result = self.run_together([lambda: self.credit(10, **source), lambda: self.credit(10, **source)])
        self.assertCountEqual([item[0] for item in result], ["OK", "OK"])
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual(PublicStockBalance.objects.get().quantity, 10)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_concurrent_same_event_cannot_credit_different_identities(self):
        source = self.source()
        other_identity = self.pipe("6.20")
        result = self.run_together([
            lambda: self.credit(10, **source), lambda: self.credit(10, identity=other_identity, **source),
        ])
        self.assertCountEqual([item[0] for item in result], ["OK", "IDEMPOTENCY_CONFLICT"])
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_concurrent_identical_debits_replay_after_stock_reaches_zero(self):
        first = self.credit(10)
        source = self.source()
        result = self.run_together([
            lambda: self.debit(first.balance_id, 10, **source),
            lambda: self.debit(first.balance_id, 10, **source),
        ])
        self.assertCountEqual([item[0] for item in result], ["OK", "OK"])
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual(PublicStockBalance.objects.get(pk=first.balance_id).quantity, 0)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
