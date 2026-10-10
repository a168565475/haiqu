import copy
import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import APIException
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomLine, BomSection
from apps.boms.material_flow_calculations import pipe_plan
from apps.core.api.concurrency import etag_for_instance
from apps.inventory.models import PublicStockBalance, PublicStockMovement, MaterialStockMovement
from apps.inventory.public_stock_identity import build_pipe_stock_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.stock_services import credit_material_stock
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.requirements import sync_order_requirements
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit

from ..dispatch_services import confirm_flow_dispatch
from ..models import OutsourcingDispatchLine, OutsourcingMaterialItem, OutsourcingOrder, OutsourcingReturnLine
from .test_material_flow import MaterialFlowFixture


class PublicOutsourcingFixture(MaterialFlowFixture):
    @transaction.atomic
    def setUp(self):
        # 历史入库只作隔离回归夹具；新公共期初由独立事件建立，不同时供业务读取。
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False):
            super().setUp()
        self.f.profile.category = "管材"
        self.f.profile.raw_values.update(tube_shape="圆管", tube_diameter="25", tube_thickness="1.2", tube_coating_color="哑黑")
        self.f.profile.save()
        self.f.fabric.material = "牛津布"
        self.f.fabric.raw_values.update(fabric_color_name="卡其色", fabric_color_code="5865C", fabric_color_card="潘通")
        self.f.fabric.save()
        self.f.cutting.category = "委外布面"
        self.f.cutting.material = "牛津布"
        self.f.cutting.cutting_pieces_per_set = 2
        self.f.cutting.cutting_sets_per_product = 1
        self.f.cutting.fabric_meters_per_piece = Decimal("0.75")
        self.f.cutting.save()
        self.identity = build_pipe_stock_identity(raw_material=self.raw_pipe, raw_bar_length_m=Decimal("3.05"), unit=self.raw_pipe.unit)
        self.public_balance = credit_public_stock(identity=self.identity, zone=self.pipe_batch.zone,
            quantity=100, source_type="S5_TEST_OPENING", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.f.employee).balance

    def dispatch(self, order_id, kind="PIPE", amount="402", expected=200):
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        payload = {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "zone_id": str(self.pipe_batch.zone_id), "requested_quantity": amount}]}
        self.post(order_id, "confirm-dispatch", payload, expected)
        return payload, OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).first()

    def revoke(self, order_id, request_id=None, expected=200):
        payload = {"request_id": request_id or str(uuid.uuid4()), "reason": "未投入原料退回"}
        response = self.post(order_id, "revoke-dispatched", payload, expected)
        return payload, response

    def small_pool(self, bars):
        self.public_balance.quantity = Decimal(bars)
        self.public_balance.meter_quantity = Decimal(bars) * Decimal("3.05")
        self.public_balance.save(update_fields=["quantity", "meter_quantity"])

    @transaction.atomic
    def clone_scope(self):
        suffix = uuid.uuid4().hex[:8].upper()
        mapping = {}

        def duplicate(model, source_id, **values):
            row = model.objects.get(pk=source_id)
            old_id = row.pk
            row.pk = uuid.uuid4()
            for key, value in values.items():
                setattr(row, key, value)
            row.save(force_insert=True)
            mapping[str(old_id)] = str(row.pk)
            return row

        task = duplicate(ProductionTask, self.f.product_line.production_task_id,
            task_number=f"S5TASK{suffix}", order_number=f"S5ORDER{suffix}", contract_number=f"S5CONTRACT{suffix}")
        product = duplicate(ProductionTaskProduct, self.f.product_line.pk, production_task=task)
        bom = duplicate(Bom, self.f.bom.pk, production_task=task, product_line=product, bom_number=f"S5BOM{suffix}")
        new_lines = {}
        for section in BomSection.objects.filter(bom=self.f.bom):
            current = duplicate(BomSection, section.pk, bom=bom)
            for line in BomLine.objects.filter(section=section):
                new_lines[line.pk] = duplicate(BomLine, line.pk, section=current, component_identity=uuid.uuid4())
        cutting = new_lines[self.f.cutting.pk]
        cutting.fabric_source_line = new_lines[self.f.fabric.pk]
        cutting.save(update_fields=["fabric_source_line"])
        schedule = duplicate(ProductionSchedule, self.f.schedule_product.schedule_id,
            production_task=task, schedule_number=f"S5PC{suffix}", client_request_id=uuid.uuid4())
        schedule_product = duplicate(ProductionScheduleProduct, self.f.schedule_product.pk, schedule=schedule, product_line=product)
        for link in ProductionScheduleProductCraft.objects.filter(schedule_product=self.f.schedule_product):
            duplicate(ProductionScheduleProductCraft, link.pk, schedule_product=schedule_product)
        return SimpleNamespace(task=task, product=product, bom=bom, schedule_product=schedule_product,
            pipe=new_lines[self.f.profile.pk], fabric=new_lines[self.f.fabric.pk], mapping=mapping)

    def scoped_payload(self, scope, kind="PIPE", amount="12"):
        payload = self.payload(kind, amount)
        payload["schedule_id"] = str(scope.schedule_product.schedule_id)
        product = payload["products"][0]
        product["schedule_product_id"] = str(scope.schedule_product.pk)
        product["bom_id"] = str(scope.bom.pk)
        for item in product["processing_items"]:
            item["bom_line_id"] = scope.mapping[item["bom_line_id"]]
        for item in product["materials"]:
            item["bom_line_id"] = scope.mapping[item["bom_line_id"]]
            item["processing_bom_line_id"] = scope.mapping[item["processing_bom_line_id"]]
        return payload

    def other_order(self, scope, kind="PIPE", amount="12"):
        response = self.f.create_order(self.scoped_payload(scope, kind, amount))
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]["id"]

    def pending(self, requirement, amount, *, scope=None, pipe=True):
        task = scope.task if scope else self.f.product_line.production_task
        product = scope.product if scope else self.f.product_line
        issue = MaterialIssue.objects.create(stock_mode="PUBLIC_V2", issue_number=f"S5PENDING{uuid.uuid4().hex[:8]}",
            client_request_id=uuid.uuid4(), request_payload_hash="p" * 64, status="PENDING_REVIEW",
            production_task=task, product_line=product, created_by_employee=self.f.employee, updated_by_employee=self.f.employee)
        snapshot = {"kind": "PIPE", "pieces_per_bar": 6, "raw_bar_length_m": "3.05",
            "public_identity": {**self.identity, "raw_bar_length_m": "3.05"}} if pipe else {}
        return MaterialIssueLine.objects.create(issue=issue, line_number=1, line_type="RAW", requirement=requirement,
            raw_material=requirement.raw_material, unit=requirement.unit, requested_quantity=Decimal(amount),
            conversion_snapshot=snapshot)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicOutsourcingFlowTests(PublicOutsourcingFixture, APITestCase):
    def test_one_incomplete_processing_row_does_not_break_other_public_candidates(self):
        incomplete = BomLine.objects.get(pk=self.f.profile.pk)
        incomplete.pk, incomplete.component_identity = uuid.uuid4(), uuid.uuid4()
        incomplete.line_number = 99
        incomplete.part_name = "缺少切割参数的部位"
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(incomplete, field, None)
        incomplete.save(force_insert=True)
        response = self.f.get_bom(self.f.spray)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        good = next(row for row in data["material_items"] if row["id"] == str(self.f.profile.pk))
        bad = next(row for row in data["processing_items"] if row["id"] == str(incomplete.pk))
        self.assertTrue(good["zones"])
        self.assertTrue(bad["quantity_error"])

    def test_public_candidates_creation_dispatch_never_read_inbound_batches(self):
        with patch("apps.outsourcing.dispatch_services.confirmed_batches", side_effect=AssertionError("不可读取采购批次")):
            with CaptureQueriesContext(connection) as queries:
                order_id = self.create(amount="12")
                context = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/", HTTP_HOST="localhost")
                self.assertEqual(context.status_code, 200, context.data)
                self.dispatch(order_id, amount="12")
            self.assertFalse(any("inventory_material_inbound" in row["sql"] or "material_inbound_line" in row["sql"] for row in queries))
        source = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
        self.assertIsNone(source.inbound_line_id)
        self.assertIsNone(source.stock_balance_id)
        self.assertEqual(source.public_stock_balance_id, self.public_balance.pk)
        self.assertEqual((source.issued_piece_count, source.issued_quantity, source.issued_meters), (12, 2, Decimal("6.10")))
        self.public_balance.refresh_from_db()
        self.pipe_balance.refresh_from_db()
        self.assertEqual((self.public_balance.quantity, self.pipe_balance.quantity), (98, 100))

    def test_source_bom_candidates_have_zones_and_no_batches(self):
        with patch("apps.outsourcing.dispatch_services.confirmed_batches", side_effect=AssertionError("不可读取采购批次")):
            response = self.f.get_bom(self.f.spray)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["stock_mode"], "PUBLIC_V2")
        row = next(row for row in response.data["data"]["material_items"] if row["id"] == str(self.f.profile.pk))
        self.assertEqual(row["candidates"], [])
        self.assertEqual(len(row["zones"]), 1)

    def test_pipe_partial_raw_return_and_revoke_restore_once(self):
        order_id = self.create(amount="12")
        dispatched, source = self.dispatch(order_id, amount="12")
        self.post(order_id, "confirm-dispatch", dispatched)
        returned = self.raw_return(order_id, source, 1)
        self.post(order_id, "confirm-raw-return", returned)
        payload, _ = self.revoke(order_id)
        self.revoke(order_id, request_id=payload["request_id"])
        self.public_balance.refresh_from_db()
        self.assertEqual((self.public_balance.quantity, self.public_balance.meter_quantity), (100, Decimal("305.00")))
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=source.requirement_id).outsourcing_issued_quantity, 0)
        moves = PublicStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN")
        self.assertEqual(moves.count(), 2)
        self.assertTrue(all(move.quantity == 1 and move.meter_quantity == Decimal("3.05") for move in moves))

    def test_whole_bar_and_same_quota_include_internal_and_pending(self):
        order_id = self.create(amount="12")
        self.dispatch(order_id, amount="7", expected=400)
        requirement = sync_pipe_requirement(self.f.profile.pk)
        requirement.internal_issued_quantity = Decimal("396")
        requirement.save(update_fields=["internal_issued_quantity"])
        self.pending(requirement, "6")
        self.dispatch(order_id, amount="12", expected=409)
        self.assertFalse(OutsourcingDispatchLine.objects.exists())
        self.public_balance.refresh_from_db()
        self.assertEqual(self.public_balance.quantity, 100)

    def test_cross_order_pending_reserves_physical_roots(self):
        scope = self.clone_scope()
        self.small_pool(3)
        requirement = sync_pipe_requirement(scope.pipe.pk)
        self.pending(requirement, "12", scope=scope)
        order_id = self.create(amount="12")
        context = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/dispatch-context/", HTTP_HOST="localhost")
        row = context.data["data"]["materials"][0]
        self.assertEqual((Decimal(row["available_stock"]), Decimal(row["public_pending_quantity"]),
                          Decimal(row["max_issue_quantity"])), (18, 12, 6))
        self.dispatch(order_id, amount="12", expected=409)

    def test_cross_order_raw_dispatch_and_semi_return_share_pools(self):
        scope = self.clone_scope()
        first = self.create(amount="12")
        second = self.other_order(scope, amount="12")
        _, a = self.dispatch(first, amount="12")
        _, b = self.dispatch(second, amount="12")
        self.return_goods(first, a, 12, raw_inputs=[self.entry(a, "RAW_INPUT", 2)])
        self.return_goods(second, b, 12, raw_inputs=[self.entry(b, "RAW_INPUT", 2)])
        balances = PublicStockBalance.objects.filter(stock_kind="SEMI")
        self.assertEqual(balances.count(), 1)
        self.assertEqual(balances.get().quantity, 24)
        self.assertEqual(set(PublicStockMovement.objects.filter(source_type="OUTSOURCING_RETURN").values_list("production_task_id", flat=True)),
            {self.f.product_line.production_task_id, scope.task.pk})
        self.assertEqual(OutsourcingReturnLine.objects.filter(semi_finished_balance__isnull=False).count(), 0)

    def test_fabric_meters_out_and_sets_return_frozen_after_bom_change(self):
        order_id = self.create("FABRIC", "90")
        _, source = self.dispatch(order_id, "FABRIC", "90")
        self.f.material_balance.refresh_from_db()
        self.assertEqual(self.f.material_balance.quantity, 110)
        self.f.cutting.raw_values["cutting_color"] = "后来改为黑色"
        self.f.cutting.save()
        payload = self.return_goods(order_id, source, 60, raw_inputs=[self.entry(source, "RAW_INPUT", 90)])
        self.post(order_id, "confirm-return", payload)
        balance = PublicStockBalance.objects.get(stock_kind="SEMI")
        self.assertEqual((balance.quantity, balance.unit.unit_name, balance.meter_quantity), (60, "套", None))
        self.assertEqual(balance.identity_snapshot["color"], "卡其色")
        self.assertEqual(PublicStockMovement.objects.filter(source_type="OUTSOURCING_RETURN").count(), 1)
        self.return_goods(order_id, source, 1, expected=409)

    def test_fabric_unused_return_and_revoke_restores_ordinary_without_batch(self):
        order_id = self.create("FABRIC", "90")
        _, source = self.dispatch(order_id, "FABRIC", "90")
        self.raw_return(order_id, source, "1.5")
        self.revoke(order_id)
        self.f.material_balance.refresh_from_db()
        self.assertEqual(self.f.material_balance.quantity, 200)
        self.assertEqual(OrderMaterialRequirement.objects.get(pk=source.requirement_id).outsourcing_issued_quantity, 0)
        self.assertTrue(all("inbound_line_id" not in row.snapshot for row in MaterialStockMovement.objects.filter(source_type="OUTSOURCING_RAW_RETURN")))

    def test_ordinary_cross_order_pending_blocks_dispatch(self):
        scope = self.clone_scope()
        _, requirements, _, _ = sync_order_requirements(scope.task.pk)
        requirement = next(row for row in requirements if row.raw_material_id == self.f.raw_material.pk)
        self.pending(requirement, "140", scope=scope, pipe=False)
        order_id = self.create("FABRIC", "90")
        self.dispatch(order_id, "FABRIC", "90", expected=409)

    def test_hardware_keeps_original_unit_and_shared_balance(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "S5COUNT"})
        category, _ = ProductCategory.objects.get_or_create(category_name="五金", defaults={"item_type": "MATERIAL"})
        raw = RawMaterialInformation.objects.create(material_number="S5RIVET", item_type="MATERIAL", category=category,
            material_name="公共铆钉", specification="M6", unit=unit)
        self.f.hardware.raw_values["source_inventory_material_id"] = str(raw.pk)
        self.f.hardware.save()
        balance = credit_material_stock(raw_material=raw, unit=unit, zone=self.pipe_batch.zone, quantity=500,
            source_type="S5_TEST_ORDINARY", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.f.employee).balance
        payload = self.payload(amount="12")
        item = copy.deepcopy(payload["products"][0]["materials"][0])
        item.update(bom_line_id=str(self.f.hardware.pk), planned_issue_quantity="50")
        payload["products"][0]["materials"].append(item)
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        materials = OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [
            {"material_item_id": str(row.pk), "zone_id": str(self.pipe_batch.zone_id),
             "requested_quantity": "50" if row.bom_material_line_id == self.f.hardware.pk else "12"} for row in materials]})
        hardware = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id, raw_material=raw)
        self.assertEqual((hardware.issued_quantity, hardware.unit.unit_name, hardware.inbound_line_id), (50, "个", None))
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 450)
        self.revoke(order_id)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 500)

    def test_same_pool_multiple_parts_accumulate_roots_before_debit(self):
        second = BomLine.objects.get(pk=self.f.profile.pk)
        second.pk, second.component_identity, second.line_number, second.part_name = uuid.uuid4(), uuid.uuid4(), 2, "后脚管"
        plan = pipe_plan(cutting_length_mm=750, pieces_per_product=4, pieces_per_bar=4, order_quantity=100)
        for name in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters"):
            setattr(second, name, plan[name])
        second.save(force_insert=True)
        payload = self.payload(amount="12")
        product = payload["products"][0]
        processing = copy.deepcopy(product["processing_items"][0])
        processing["bom_line_id"], processing["quantity"] = str(second.pk), "8"
        processing["allocations"][0].update(input_quantity="8", allocated_quantity="8")
        product["processing_items"].append(processing)
        material = copy.deepcopy(product["materials"][0])
        material.update(bom_line_id=str(second.pk), processing_bom_line_id=str(second.pk), planned_issue_quantity="8")
        product["materials"].append(material)
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        self.small_pool(3)
        sources = list(OutsourcingMaterialItem.objects.filter(allocation__processing_item__order_product__order_id=order_id))
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [
            {"material_item_id": str(item.pk), "zone_id": str(self.pipe_batch.zone_id),
             "requested_quantity": "12" if item.bom_material_line_id == self.f.profile.pk else "8"} for item in sources]}, expected=409)
        self.public_balance.refresh_from_db()
        self.assertEqual(self.public_balance.quantity, 3)
        self.assertFalse(OutsourcingDispatchLine.objects.exists())

    def test_public_mode_rejects_batch_choice_and_invalid_output_properties(self):
        order_id = self.create(amount="12")
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        self.post(order_id, "confirm-dispatch", {"request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.pipe_batch.pk), "requested_quantity": "12"}]}, expected=400)
        self.f.profile.raw_values.pop("tube_thickness")
        self.f.profile.save()
        response = self.f.create_order(self.payload(amount="12"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(OutsourcingOrder.objects.count(), 1)

    def test_mode_gate_blocks_new_writes_but_allows_confirmed_retry(self):
        order_id = self.create(amount="12")
        request_payload, source = self.dispatch(order_id, amount="12")
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            self.post(order_id, "confirm-dispatch", request_payload)
            self.raw_return(order_id, source, 1, expected=400)
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False):
            legacy = self.create(amount="12")
        self.assertEqual(OutsourcingOrder.objects.get(pk=legacy).stock_mode, "LEGACY")
        self.dispatch(legacy, amount="12", expected=400)

    def test_ledger_failure_rolls_back_dispatch_quota_and_balance(self):
        order_id = self.create(amount="12")
        before = (self.public_balance.quantity, self.public_balance.meter_quantity, self.public_balance.version)
        with patch("apps.inventory.public_stock_services.PublicStockMovement.objects.create", side_effect=RuntimeError("账本写入失败")):
            with self.assertRaises(RuntimeError):
                self.dispatch(order_id, amount="12")
        self.public_balance.refresh_from_db()
        self.assertEqual((self.public_balance.quantity, self.public_balance.meter_quantity, self.public_balance.version), before)
        self.assertFalse(OutsourcingDispatchLine.objects.exists())
        self.assertFalse(OrderMaterialRequirement.objects.filter(outsourcing_issued_quantity__gt=0).exists())


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicOutsourcingConcurrencyTests(PublicOutsourcingFixture, TransactionTestCase):
    serialized_rollback = True

    def test_raw_return_and_another_dispatch_lock_schedule_before_task(self):
        from ..reconciliation_services import confirm_raw_return
        first = self.create(amount="12")
        _, source = self.dispatch(first, amount="12")
        second = self.create(amount="12")
        schedule_held, dispatch_at_schedule = threading.Event(), threading.Event()
        results = []
        schedule_table = ProductionSchedule._meta.db_table

        def run(returning):
            connections.close_all()
            observed = False

            def coordinate(execute, sql, params, many, context):
                nonlocal observed
                if not observed and f'"{schedule_table}"' in sql and "FOR UPDATE" in sql:
                    observed = True
                    if returning:
                        result = execute(sql, params, many, context)
                        schedule_held.set()
                        if not dispatch_at_schedule.wait(8):
                            raise AssertionError("外发没有进入排产锁等待")
                        return result
                    dispatch_at_schedule.set()
                return execute(sql, params, many, context)

            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                if not returning and not schedule_held.wait(8):
                    raise AssertionError("退料没有取得排产锁")
                order = OutsourcingOrder.objects.get(pk=first if returning else second)
                request = SimpleNamespace(headers={"If-Match": etag_for_instance(order)}, META={})
                with connections["default"].execute_wrapper(coordinate):
                    if returning:
                        confirm_raw_return(order_id=order.pk, request_id=uuid.uuid4(),
                            factory_id=source.material_item.allocation.factory_id,
                            lines=[{"dispatch_line_id": source.pk, "quantity": Decimal(1)}], reason="退回未投入的一根",
                            actor_employee=self.f.employee, request=request)
                    else:
                        item = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order=order)
                        confirm_flow_dispatch(order_id=order.pk, request_id=uuid.uuid4(), line_inputs=[{
                            "material_item_id": item.pk, "zone_id": self.pipe_batch.zone_id, "requested_quantity": Decimal(12)}],
                            remark="另一张单发料", actor_employee=self.f.employee, request=request)
                results.append("RETURN_OK" if returning else "DISPATCH_OK")
            except Exception as error:
                results.append(f"{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(returning,)) for returning in (True, False)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertCountEqual(results, ["RETURN_OK", "DISPATCH_OK"])
        self.public_balance.refresh_from_db()
        self.assertEqual((self.public_balance.quantity, self.public_balance.meter_quantity), (97, Decimal("295.85")))

    def test_two_orders_cannot_dispatch_same_remaining_roots(self):
        self.small_pool(3)
        first = self.create(amount="12")
        second = self.other_order(self.clone_scope(), amount="12")
        barrier = threading.Barrier(2)
        results = []

        def run(order_id):
            connections.close_all()
            try:
                order = OutsourcingOrder.objects.get(pk=order_id)
                item = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order=order)
                request = SimpleNamespace(headers={"If-Match": etag_for_instance(order)}, META={})
                barrier.wait(timeout=10)
                confirm_flow_dispatch(order_id=order.pk, request_id=uuid.uuid4(), line_inputs=[{
                    "material_item_id": item.pk, "zone_id": self.pipe_batch.zone_id, "requested_quantity": Decimal(12)}],
                    remark="并发公共库存测试", actor_employee=self.f.employee, request=request)
                results.append("ok")
            except APIException:
                results.append("blocked")
            except Exception as error:
                results.append(repr(error))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(order_id,)) for order_id in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), "并发发料未在时限内结束")
        self.assertCountEqual(results, ["ok", "blocked"])
        self.public_balance.refresh_from_db()
        self.assertEqual((self.public_balance.quantity, self.public_balance.meter_quantity), (1, Decimal("3.05")))
