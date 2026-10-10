import hashlib
import io
import json
import tempfile
import threading
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft
from ..models import (
    MaterialStockBalance, MaterialStockMovement, PublicStockBalance, PublicStockMovement,
    Warehouse, WarehouseZone,
)
from ..pipe_stock_services import credit_pipe_inbound
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_opening import (
    FORMAL_OPENING_ACTION, FORMAL_OPENING_TYPE, PublicStockOpeningError,
    apply_public_stock_opening, build_public_stock_opening_manifest,
)
from ..public_stock_preview import OPENING_SOURCE_TYPE, _load_plan
from ..public_stock_services import credit_public_stock
from ..stock_services import credit_semi_finished_stock
from .test_pipe_stock_foundation import PipeFixture


class PublicStockOpeningFixture(PipeFixture):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        from ..models import PublicStockCutoverControl
        self.control_model = PublicStockCutoverControl
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), system_identifier::text FROM pg_control_system()")
            database, identifier = cursor.fetchone()
        self.target = {"host": connection.settings_dict["HOST"], "database": database, "system_identifier": identifier}
        allowed = self.settings(PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS=[self.target])
        allowed.enable()
        self.addCleanup(allowed.disable)
        self.control = self.control_model.objects.create(state="MAINTENANCE", reason="工具测试",
                                                       started_at=timezone.now() - timedelta(minutes=5))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backup_path = Path(self.temp.name) / "fixture.backup"
        self.backup_path.write_bytes(b"only a test fixture; not a real operational backup")
        self.evidence_path = Path(self.temp.name) / "backup-evidence.json"
        self.evidence = {
            "schema_version": 1, "target": self.target, "backup_file": str(self.backup_path),
            "backup_sha256": hashlib.sha256(self.backup_path.read_bytes()).hexdigest(),
            "backup_completed_at": (timezone.now() - timedelta(minutes=3)).isoformat(),
            "restore_verified_at": (timezone.now() - timedelta(minutes=1)).isoformat(), "restore_verified": True,
        }
        self.write_evidence()

    def write_evidence(self):
        self.evidence_path.write_text(json.dumps(self.evidence), encoding="utf-8")

    def preview(self, **changes):
        arguments = {"actor_employee": self.employee, "backup_evidence_path": self.evidence_path}
        arguments.update(changes)
        return build_public_stock_opening_manifest(**arguments)

    def apply(self, manifest=None, **changes):
        manifest = manifest or self.preview()
        arguments = {"actor_employee": self.employee, "backup_evidence_path": self.evidence_path,
                     "expected_target": self.target, "expected_manifest_sha256": manifest["manifest_sha256"]}
        arguments.update(changes)
        return apply_public_stock_opening(**arguments)

    def codes(self, report):
        return {blocker["code"] for blocker in report["blockers"]}

    def assert_no_opening(self):
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PublicStockMovement.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=FORMAL_OPENING_ACTION).exists())

    def second_pipe(self, bars=3, length="3.05"):
        # 先在旧账模式构造测试数据，再回到维护状态；正式工具没有此旁路。
        self.control_model.objects.filter(pk=self.control.pk).delete()
        try:
            line = self.make_batch(bars=bars, length=length)
            credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=self.employee)
        finally:
            self.control.save(force_insert=True)
        return MaterialStockBalance.objects.get(inbound_line=line)

    def semi(self, frozen):
        self.control_model.objects.filter(pk=self.control.pk).delete()
        try:
            unit = ProductionUnit.objects.get(unit_name="支")
            warehouse = Warehouse.objects.create(warehouse_number="FORMALSEMI", warehouse_name="正式工具测试半成品仓", warehouse_type="SEMI_FINISHED")
            zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="一楼")
            self.bom_line.section.section_type = "PROFILE"
            self.bom_line.section.save(update_fields=["section_type"])
            self.bom_line.part_name = "前脚管"
            self.bom_line.material = "铁"
            self.bom_line.specification = "20*28*0.8*6140"
            self.bom_line.raw_values = {"tube_shape": "矩形管", "tube_diameter": "20*28", "tube_thickness": "0.8", "tube_coating_color": "黑色"}
            self.bom_line.save()
            craft, _ = Craft.objects.get_or_create(outsourcing_code="POWDER_COATING", defaults={"name": "正式工具测试喷塑", "craft_type": "EXTERNAL"})
            identity = build_semi_finished_identity(bom_line=self.bom_line, completed_craft=craft, unit=unit)
            return credit_semi_finished_stock(
                production_task=self.task, product_line=self.product_line, bom_line=self.bom_line,
                completed_craft=craft, color_snapshot="黑色", unit=unit, zone=zone, quality="AVAILABLE",
                quantity=20, source_type="FORMAL_TEST_RETURN", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                actor_employee=self.employee, snapshot={"public_stock_identity": identity} if frozen else {})
        finally:
            self.control.save(force_insert=True)


class PublicStockOpeningTests(PublicStockOpeningFixture, TestCase):
    def test_default_service_and_cli_only_read_and_include_review_evidence(self):
        with CaptureQueriesContext(connection) as queries:
            report = self.preview()
        self.assertTrue(report["ready"], report["blockers"])
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertEqual(report["manifest"]["target"], self.target)
        self.assertEqual(report["manifest"]["actor"]["id"], str(self.employee.pk))
        self.assertEqual(report["manifest"]["backup"]["backup_sha256"], self.evidence["backup_sha256"])
        self.assertEqual(len(report["manifest"]["groups"]), 1)
        self.assertTrue(all(query["sql"].lstrip().startswith("SELECT") for query in queries), list(queries))
        output = io.StringIO()
        call_command("import_public_stock_opening", stdout=output)
        default = json.loads(output.getvalue())
        self.assertFalse(default["ready"])
        self.assertIn("ACTOR_REQUIRED", self.codes(default))
        self.assertIn("BACKUP_EVIDENCE_REQUIRED", self.codes(default))
        self.assert_no_opening()

    def test_success_replay_zero_increment_and_one_audit_preserves_legacy(self):
        self.second_pipe()
        legacy = list(MaterialStockBalance.objects.order_by("id").values("id", "quantity", "meter_quantity", "version"))
        manifest = self.preview()
        first = self.apply(manifest)
        second = self.apply(manifest)
        self.assertEqual(first["created_movement_count"], 2)
        self.assertEqual(second["created_movement_count"], 0)
        self.assertEqual(first["opening_movement_ids"], second["opening_movement_ids"])
        self.assertEqual(PublicStockBalance.objects.get().quantity, 340)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(object_type=FORMAL_OPENING_TYPE, action=FORMAL_OPENING_ACTION).count(), 1)
        self.assertEqual(legacy, list(MaterialStockBalance.objects.order_by("id").values("id", "quantity", "meter_quantity", "version")))

    def test_actor_and_target_are_required_and_target_must_match_real_cluster(self):
        self.assertIn("ACTOR_REQUIRED", self.codes(self.preview(actor_employee=uuid.uuid4())))
        for field, wrong in [("host", "postgres"), ("database", "haiqu_erp"), ("system_identifier", "7676413601110605859")]:
            with self.subTest(field=field):
                with self.assertRaisesMessage(PublicStockOpeningError, "TARGET_MISMATCH"):
                    self.apply(expected_target={**self.target, field: wrong})
        with self.settings(PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS=[]):
            self.assertFalse(self.preview()["ready"])
        self.assert_no_opening()

    def test_non_admin_employee_cannot_approve_or_apply_opening(self):
        manifest = self.preview()
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        report = self.preview()
        self.assertIn("PUBLIC_STOCK_CUTOVER_OPERATOR_INVALID", self.codes(report))
        with self.assertRaises(PublicStockOpeningError):
            self.apply(manifest)
        self.assert_no_opening()

    def test_missing_future_wrong_target_or_modified_backup_blocks(self):
        missing = self.preview(backup_evidence_path=None)
        self.assertIn("BACKUP_EVIDENCE_REQUIRED", self.codes(missing))
        original = dict(self.evidence)
        cases = [
            ({"backup_completed_at": (self.control.started_at - timedelta(seconds=1)).isoformat()}, "BACKUP_BEFORE_MAINTENANCE"),
            ({"restore_verified_at": (timezone.now() + timedelta(days=2)).isoformat()}, "BACKUP_TIME_INVALID"),
            ({"restore_verified": False}, "BACKUP_RESTORE_UNVERIFIED"),
            ({"target": {**self.target, "database": "haiqu_erp"}}, "BACKUP_TARGET_MISMATCH"),
            ({"backup_sha256": "0" * 64}, "BACKUP_HASH_MISMATCH"),
        ]
        for changes, code in cases:
            with self.subTest(code=code):
                self.evidence = {**original, **changes}
                self.write_evidence()
                report = self.preview()
                self.assertIn(code, self.codes(report))
                with self.assertRaises(PublicStockOpeningError):
                    self.apply(report)
                self.assert_no_opening()

    def test_expected_manifest_and_maintenance_are_required(self):
        with self.assertRaisesMessage(PublicStockOpeningError, "EXPECTED_MANIFEST_REQUIRED"):
            self.apply(expected_manifest_sha256="")
        with self.assertRaisesMessage(PublicStockOpeningError, "MANIFEST_STALE"):
            self.apply(expected_manifest_sha256="0" * 64)
        self.control_model.objects.filter(pk=self.control.pk).delete()
        self.assertIn("MAINTENANCE_REQUIRED", self.codes(self.preview()))
        with self.assertRaises(Exception):
            self.apply()
        self.assert_no_opening()

    def test_source_change_after_review_rejected_before_any_credit(self):
        manifest = self.preview()
        balance = self.balance()
        MaterialStockBalance.objects.filter(pk=balance.pk).update(version=balance.version + 1)
        with self.assertRaisesMessage(PublicStockOpeningError, "MANIFEST_STALE"):
            self.apply(manifest)
        self.assert_no_opening()

    def test_missing_pipe_history_or_missing_semi_identity_blocks_whole_import(self):
        self.semi(frozen=False)
        report = self.preview()
        self.assertIn("SEMI_SNAPSHOT_REQUIRED", self.codes(report))
        with self.assertRaises(PublicStockOpeningError):
            self.apply(report)
        MaterialStockMovement.objects.filter(balance=self.balance()).delete()
        report = self.preview()
        self.assertIn("PIPE_HISTORY_REQUIRED", self.codes(report))
        self.assert_no_opening()

    def test_frozen_semi_and_pipe_are_credited_but_meter_and_ordinary_are_excluded(self):
        self.semi(frozen=True)
        unit = ProductionUnit.objects.get(unit_name="PCS")
        category = ProductCategory.objects.filter(item_type="MATERIAL").exclude(category_name="管材").first()
        material = RawMaterialInformation.objects.create(material_number="FORMAL-NORMAL", material_name="普通配件",
            item_type="MATERIAL", category=category, specification="规格", unit=unit,
            warehouse_number=self.warehouse.warehouse_number, warehouse_name=self.warehouse.warehouse_name)
        old = MaterialStockBalance.objects.create(raw_material=material, unit=unit, zone=self.zone, quantity=99)
        report = self.apply()
        reasons = {source["reason"] for source in report["manifest"]["excluded"]}
        self.assertIn("LEGACY_METER_PIPE_EXCLUDED", reasons)
        self.assertIn("ORDINARY_MATERIAL_UNCHANGED", reasons)
        self.assertEqual(PublicStockMovement.objects.count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.quantity, 99)

    def test_existing_isolated_opening_cannot_be_relabelled_formal(self):
        from ..public_stock_cutover import allow_opening_stock_credit
        _, candidates, _ = _load_plan()
        row, identity, source, _ = candidates[0]
        with allow_opening_stock_credit():
            credit_public_stock(identity=identity, zone=row.zone, quality=row.quality, quantity=row.quantity,
                source_type=OPENING_SOURCE_TYPE, source_id=row.pk, source_line_id=row.pk,
                actor_employee=self.employee, snapshot={"legacy_source": source, "opening_only": True})
        report = self.preview()
        self.assertIn("EXISTING_PUBLIC_STOCK", self.codes(report))
        with self.assertRaises(PublicStockOpeningError):
            self.apply(report)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action=FORMAL_OPENING_ACTION).exists())

    def test_second_credit_failure_rolls_back_balance_movements_and_audit(self):
        self.second_pipe(length="3.06")
        manifest = self.preview()
        calls = []
        def fail_second(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("模拟第二笔期初失败")
            return credit_public_stock(**kwargs)
        with patch("apps.inventory.public_stock_services.credit_public_stock", side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, "模拟第二笔期初失败"):
                self.apply(manifest)
        self.assert_no_opening()

    def test_changed_backup_after_review_is_not_an_authorization_to_write(self):
        manifest = self.preview()
        self.backup_path.write_bytes(b"changed backup fixture")
        with self.assertRaises(PublicStockOpeningError):
            self.apply(manifest)
        self.assert_no_opening()

    def test_changed_public_balance_is_not_reported_as_successful_replay(self):
        manifest = self.preview()
        self.apply(manifest)
        balance = PublicStockBalance.objects.get()
        PublicStockBalance.objects.filter(pk=balance.pk).update(
            quantity=balance.quantity + 1, meter_quantity=balance.meter_quantity + balance.raw_bar_length_m)
        report = self.preview()
        self.assertIn("FORMAL_OPENING_LEDGER_CHANGED", self.codes(report))
        with self.assertRaises(PublicStockOpeningError):
            self.apply(manifest)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_cli_refuses_incomplete_apply_and_existing_evidence_output(self):
        with self.assertRaises(CommandError):
            call_command("import_public_stock_opening", "--apply")
        with self.assertRaises(CommandError):
            call_command("import_public_stock_opening", "--output", str(self.evidence_path))
        self.assert_no_opening()


class PublicStockOpeningConcurrencyTests(PublicStockOpeningFixture, TransactionTestCase):
    serialized_rollback = True

    def test_concurrent_same_review_creates_one_opening_and_one_audit(self):
        manifest = self.preview()
        barrier = threading.Barrier(2)
        results = []

        def run():
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                barrier.wait(timeout=5)
                report = self.apply(manifest)
                results.append(("OK", report["created_movement_count"], report["opening_movement_ids"]))
            except Exception as error:
                results.append((f"{type(error).__name__}: {error}", None, []))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run), threading.Thread(target=run)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        self.assertCountEqual([result[0] for result in results], ["OK", "OK"])
        self.assertCountEqual([result[1] for result in results], [0, 1])
        self.assertEqual(results[0][2], results[1][2])
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 337)
        self.assertEqual(AuditLog.objects.filter(action=FORMAL_OPENING_ACTION).count(), 1)
