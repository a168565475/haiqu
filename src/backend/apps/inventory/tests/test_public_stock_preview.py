import copy
import io
import threading
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.boms.models import BomLine
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft
from ..models import MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement, SemiFinishedStockMovement, Warehouse, WarehouseZone
from ..pipe_stock_services import credit_pipe_inbound
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_preview import OPENING_SOURCE_TYPE, PublicStockPreviewError, assert_isolated_database, preview_public_stock
from ..public_stock_services import credit_public_stock
from ..stock_services import credit_semi_finished_stock
from .test_pipe_stock_foundation import PipeFixture


class PublicStockPreviewTests(PipeFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.piece_unit = ProductionUnit.objects.get(unit_name="支")
        self.semi_warehouse = Warehouse.objects.create(warehouse_number="PREVIEWSEMI", warehouse_name="预演半成品仓", warehouse_type="SEMI_FINISHED")
        self.semi_zone = WarehouseZone.objects.create(warehouse=self.semi_warehouse, zone_name="一楼")
        self.bom_line.section.section_type = "PROFILE"
        self.bom_line.section.save(update_fields=["section_type"])
        self.bom_line.part_name = "前脚管"
        self.bom_line.material = "铁"
        self.bom_line.specification = "20*28*0.8*6140"
        self.bom_line.raw_values = {"tube_shape": "矩形管", "tube_diameter": "20*28", "tube_thickness": "0.8", "tube_coating_color": "黑色"}
        self.bom_line.save()
        self.craft, _ = Craft.objects.get_or_create(outsourcing_code="POWDER_COATING", defaults={"name": "预演喷塑", "craft_type": "EXTERNAL"})

    def second_pipe(self, bars=3, length="3.05"):
        line = self.make_batch(bars=bars, length=length)
        credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
        return MaterialStockBalance.objects.get(inbound_line=line)

    def semi(self, *, frozen=True, bom_line=None):
        line = bom_line or self.bom_line
        identity = build_semi_finished_identity(bom_line=line, completed_craft=self.craft, unit=self.piece_unit)
        movement = credit_semi_finished_stock(production_task=self.task, product_line=self.product_line, bom_line=line,
            completed_craft=self.craft, color_snapshot="黑色", unit=self.piece_unit, zone=self.semi_zone,
            quality="AVAILABLE", quantity=20, source_type="PREVIEW_TEST_RETURN", source_id=uuid.uuid4(),
            source_line_id=uuid.uuid4(), actor_employee=self.employee,
            snapshot={"public_stock_identity": identity} if frozen else {"component": "前脚管"})
        return movement

    def apply(self):
        return preview_public_stock(apply_isolated=True, actor_employee=self.employee)

    def exhaust_pipe(self, balance):
        MaterialStockMovement.objects.create(balance=balance, direction="OUT", quantity=balance.quantity,
            meter_quantity=balance.meter_quantity, before_quantity=balance.quantity, after_quantity=0,
            before_meter_quantity=balance.meter_quantity, after_meter_quantity=0,
            source_type="PREVIEW_TEST_ISSUE", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        MaterialStockBalance.objects.filter(pk=balance.pk).update(quantity=0, meter_quantity=0)

    def test_default_preview_merges_pipe_batches_without_writing_or_counting_ordinary_stock(self):
        self.second_pipe()
        before = list(MaterialStockBalance.objects.values("id", "quantity", "meter_quantity", "version"))
        report = preview_public_stock()
        self.assertTrue(report["ready"], report["blockers"])
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(Decimal(report["groups"][0]["quantity"]), 340)
        self.assertEqual(Decimal(report["groups"][0]["meter_quantity"]), Decimal("1037.00"))
        self.assertEqual(len(report["groups"][0]["sources"]), 2)
        self.assertIn("LEGACY_METER_PIPE_EXCLUDED", [item["reason"] for item in report["excluded"]])
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertEqual(before, list(MaterialStockBalance.objects.values("id", "quantity", "meter_quantity", "version")))

    def test_pipe_lengths_stay_separate_and_zero_balance_is_reported(self):
        second = self.second_pipe(length="3.06")
        zero = self.second_pipe()
        self.exhaust_pipe(zero)
        report = preview_public_stock()
        self.assertEqual(len(report["groups"]), 2)
        self.assertEqual(report["zero_balances"][0]["source_id"], str(zero.pk))
        self.assertEqual({item["identity_snapshot"]["raw_bar_length_m"] for item in report["groups"]}, {"3.05", "3.06"})

    def test_non_pipe_material_is_explicitly_excluded_from_new_opening(self):
        unit = ProductionUnit.objects.get(unit_name="PCS")
        category = ProductCategory.objects.filter(item_type="MATERIAL").exclude(category_name="管材").first()
        material = RawMaterialInformation.objects.create(material_number="PREVIEW-NORMAL", material_name="普通配件", item_type="MATERIAL",
            category=category, specification="普通规格", unit=unit, warehouse_number=self.warehouse.warehouse_number, warehouse_name=self.warehouse.warehouse_name)
        balance = MaterialStockBalance.objects.create(raw_material=material, unit=unit, zone=self.zone, quantity=99)
        report = self.apply()
        self.assertIn({"source_id": str(balance.pk), "reason": "ORDINARY_MATERIAL_UNCHANGED", "quantity": "99.0000", "unit": "PCS"}, report["excluded"])
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 99)

    def test_read_query_count_does_not_grow_per_balance(self):
        with CaptureQueriesContext(connection) as first:
            preview_public_stock()
        for _ in range(8):
            self.second_pipe()
        with CaptureQueriesContext(connection) as many:
            preview_public_stock()
        self.assertEqual(len(first), len(many))

    def test_apply_is_idempotent_and_keeps_legacy_balance_unchanged(self):
        self.second_pipe()
        before = list(MaterialStockBalance.objects.values("id", "quantity", "meter_quantity", "version"))
        first, second = self.apply(), self.apply()
        self.assertEqual(first["opening_movement_ids"], second["opening_movement_ids"])
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 340)
        self.assertEqual(AuditLog.objects.filter(object_type=OPENING_SOURCE_TYPE).count(), 1)
        self.assertEqual(before, list(MaterialStockBalance.objects.values("id", "quantity", "meter_quantity", "version")))

    def test_changed_old_quantity_or_version_conflicts_instead_of_adding(self):
        self.apply()
        old = self.balance()
        MaterialStockBalance.objects.filter(pk=old.pk).update(quantity=336, meter_quantity=Decimal("1024.80"), version=old.version + 1)
        with self.assertRaises(PublicStockPreviewError) as caught:
            self.apply()
        codes = {item["code"] for item in caught.exception.report["blockers"]}
        self.assertIn("LEGACY_SOURCE_CHANGED", codes)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 337)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_zero_to_positive_change_is_detected_by_manifest(self):
        zero = self.second_pipe()
        self.exhaust_pipe(zero)
        self.apply()
        MaterialStockBalance.objects.filter(pk=zero.pk).update(quantity=1, meter_quantity=Decimal("3.05"))
        with self.assertRaises(PublicStockPreviewError) as caught:
            self.apply()
        self.assertIn("LEGACY_MANIFEST_CHANGED", {item["code"] for item in caught.exception.report["blockers"]})
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_ordinary_material_quantity_change_does_not_invalidate_opening_manifest(self):
        self.apply()
        MaterialStockBalance.objects.filter(measurement_kind="OTHER").update(quantity=599)
        self.assertTrue(self.apply()["applied"])
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_missing_semi_snapshot_blocks_entire_apply_before_any_opening(self):
        self.semi(frozen=False)
        report = preview_public_stock()
        self.assertIn("SEMI_SNAPSHOT_REQUIRED", {item["code"] for item in report["blockers"]})
        with self.assertRaises(PublicStockPreviewError):
            self.apply()
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(AuditLog.objects.filter(object_type=OPENING_SOURCE_TYPE).exists())

    def test_frozen_semi_identity_survives_later_bom_change_and_merges_sources(self):
        first = self.semi()
        other_line = BomLine.objects.get(pk=self.bom_line.pk)
        other_line.pk = uuid.uuid4()
        other_line.line_number = 2
        other_line.component_identity = uuid.uuid4()
        other_line.save(force_insert=True)
        self.semi(bom_line=other_line)
        self.bom_line.cutting_length_mm = 888
        self.bom_line.save(update_fields=["cutting_length_mm"])
        report = self.apply()
        groups = [group for group in report["groups"] if group["stock_kind"] == "SEMI"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(Decimal(groups[0]["quantity"]), 40)
        self.assertEqual(groups[0]["identity_snapshot"]["cutting_length_mm"], 500)
        self.assertEqual(len(groups[0]["sources"]), 2)

    def test_semi_snapshot_color_and_unit_conflict_is_blocked(self):
        movement = self.semi()
        movement.balance.color_snapshot = "白色"
        movement.balance.save(update_fields=["color_snapshot"])
        report = preview_public_stock()
        self.assertIn("SEMI_SNAPSHOT_CONFLICT", {item["code"] for item in report["blockers"]})

    def test_semi_incomplete_quantity_history_is_blocked(self):
        movement = self.semi()
        SemiFinishedStockMovement.objects.filter(pk=movement.pk).update(before_quantity=1, after_quantity=21)
        report = preview_public_stock()
        self.assertIn("SEMI_AMOUNT_MISMATCH", {item["code"] for item in report["blockers"]})

    def test_changed_frozen_semi_attribute_is_blocked(self):
        movement = self.semi()
        broken = copy.deepcopy(movement.snapshot)
        broken["public_stock_identity"]["identity_snapshot"]["cutting_length_mm"] = 999
        SemiFinishedStockMovement.objects.filter(pk=movement.pk).update(snapshot=broken)
        self.assertFalse(preview_public_stock()["ready"])

    def test_mid_apply_failure_rolls_back_all_openings_and_audit(self):
        self.second_pipe(length="3.06")
        calls = []
        def fail_second(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("模拟第二条记账失败")
            return credit_public_stock(**kwargs)
        with patch("apps.inventory.public_stock_services.credit_public_stock", side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, "模拟第二条记账失败"):
                self.apply()
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertFalse(AuditLog.objects.filter(object_type=OPENING_SOURCE_TYPE).exists())
        self.assertEqual(self.balance().quantity, 337)

    def test_wrong_host_or_cluster_is_rejected_even_with_allowed_database_name(self):
        with patch.dict(connection.settings_dict, {"HOST": "postgres"}):
            with self.assertRaisesMessage(PublicStockPreviewError, "ISOLATED_DATABASE_REQUIRED"):
                assert_isolated_database()
        with patch("apps.inventory.public_stock_preview.connection.cursor") as mocked:
            mocked.return_value.__enter__.return_value.fetchone.return_value = ("test_public_stock_s3", "7676413601110605859")
            with self.assertRaisesMessage(PublicStockPreviewError, "ISOLATED_DATABASE_REQUIRED"):
                assert_isolated_database()
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_cli_defaults_to_read_only_and_apply_requires_actor(self):
        output = io.StringIO()
        call_command("preview_public_stock", stdout=output)
        self.assertIn('"mode": "DRY_RUN"', output.getvalue())
        self.assertFalse(PublicStockMovement.objects.exists())
        with self.assertRaises(CommandError):
            call_command("preview_public_stock", "--apply-isolated")

    def test_pipe_balance_inbound_identity_mismatch_is_blocked(self):
        MaterialStockBalance.objects.filter(pk=self.balance().pk).update(raw_bar_length_m=Decimal("3.06"), meter_quantity=Decimal("1031.22"))
        report = preview_public_stock()
        self.assertIn("PIPE_SOURCE_MISMATCH", {item["code"] for item in report["blockers"]})

    def test_first_preview_rejects_self_consistent_pipe_balance_that_disagrees_with_history(self):
        MaterialStockBalance.objects.filter(pk=self.balance().pk).update(quantity=336, meter_quantity=Decimal("1024.80"))
        report = preview_public_stock()
        self.assertIn("PIPE_HISTORY_MISMATCH", {item["code"] for item in report["blockers"]})
        with self.assertRaises(PublicStockPreviewError):
            self.apply()
        self.assertFalse(PublicStockMovement.objects.exists())

    def test_first_preview_rejects_pipe_meter_history_not_matching_raw_length(self):
        movement = MaterialStockMovement.objects.get(balance=self.balance())
        MaterialStockMovement.objects.filter(pk=movement.pk).update(meter_quantity=Decimal("1027.86"), after_meter_quantity=Decimal("1027.86"))
        report = preview_public_stock()
        self.assertIn("PIPE_HISTORY_MISMATCH", {item["code"] for item in report["blockers"]})

    def test_first_preview_requires_pipe_inbound_history(self):
        MaterialStockMovement.objects.filter(balance=self.balance()).delete()
        report = preview_public_stock()
        self.assertIn("PIPE_HISTORY_REQUIRED", {item["code"] for item in report["blockers"]})

    def test_non_object_historical_snapshots_report_source_blockers(self):
        MaterialStockMovement.objects.filter(balance=self.balance()).update(snapshot=["错误旧快照"])
        movement = self.semi()
        SemiFinishedStockMovement.objects.filter(pk=movement.pk).update(snapshot="错误旧快照")
        report = preview_public_stock()
        self.assertIn("PIPE_INBOUND_HISTORY_MISMATCH", {item["code"] for item in report["blockers"]})
        self.assertIn("SEMI_SNAPSHOT_REQUIRED", {item["code"] for item in report["blockers"]})


class PublicStockPreviewConcurrencyTests(PipeFixture, TransactionTestCase):
    serialized_rollback = True

    def test_concurrent_first_apply_creates_each_opening_and_manifest_once(self):
        barrier = threading.Barrier(2)
        results = []

        def run():
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=5)
                report = preview_public_stock(apply_isolated=True, actor_employee=self.employee)
                results.append(("OK", report["opening_movement_ids"]))
            except Exception as error:
                results.append((f"{type(error).__name__}: {error}", []))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run), threading.Thread(target=run)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertCountEqual([result[0] for result in results], ["OK", "OK"])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(PublicStockBalance.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 337)
        self.assertEqual(PublicStockMovement.objects.filter(source_type=OPENING_SOURCE_TYPE).count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_type=OPENING_SOURCE_TYPE).count(), 1)
        self.assertEqual(self.balance().quantity, 337)
