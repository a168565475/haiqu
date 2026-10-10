"""仅测试数据库夹具；不操作 S6 业务副本，备份链由独立专项验证。"""

import io
import json
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.boms.material_flow_calculations import pipe_plan
from apps.boms.models import BomLine, BomSection
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Craft
from ..models import PublicStockBalance, PublicStockMovement, PublicStockCutoverControl
from ..public_stock_activation import (ACTION, OPERATION, PublicStockActivationError,
    _active_boms, _build_manifest, _legacy_transit, _quotas, apply_public_stock_activation,
    build_public_stock_activation_manifest, legacy_plan_snapshot)
from .test_public_stock_opening import PublicStockOpeningFixture


class ActivationFixture(PublicStockOpeningFixture):
    def setUp(self):
        super().setUp()
        self.schedule_product.source_quantity_snapshot = self.product_line.quantity
        self.schedule_product.planned_quantity = self.product_line.quantity
        self.schedule_product.save()
        section = self.bom_line.section
        section.section_type = "PROFILE"
        section.save(update_fields=["section_type"])
        self.apply()  # 实际运行既有正式期初服务，只有测试库数据。
        self.activation_backup = {"fixture": "backup validation covered by its own test module",
                                  "target": self.target, "control_id": str(self.control.pk)}
        self.backup_patch = patch("apps.inventory.public_stock_activation_backup.validate_activation_backup",
                                 return_value=self.activation_backup)
        self.backup_patch.start()
        self.addCleanup(self.backup_patch.stop)
        self.runtime_settings = self.settings(PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
        self.runtime_settings.enable()
        self.addCleanup(self.runtime_settings.disable)
        self.authorization_path = Path(self.temp.name) / "activation-authorization.json"
        self.retention_path = Path(self.temp.name) / "retention-confirmation.json"

    def activation_preview(self, **changes):
        return _build_manifest(actor_employee=self.employee, backup_evidence_path=self.evidence_path, **changes)

    def authorization(self, report, *, request_id=None, **changes):
        value = {"schema_version": 1, "operation": OPERATION, "confirmed": True,
            "confirmed_by": "测试确认人", "confirmation_text": "明确同意在此测试目标按所列摘要启用公共库存。",
            "confirmed_at": timezone.now().isoformat(), "target": self.target, "control_id": str(self.control.pk),
            "actor_employee_id": str(self.employee.pk), "request_id": str(request_id or uuid.uuid4()),
            "manifest_sha256": report["manifest_sha256"]}
        value.update(changes)
        self.authorization_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def activate(self, report, authorization, **changes):
        arguments = {"actor_employee": self.employee, "expected_target": self.target,
            "expected_control_id": self.control.pk, "expected_manifest_sha256": report["manifest_sha256"],
            "request_id": authorization["request_id"], "authorization_path": self.authorization_path,
            "backup_evidence_path": self.evidence_path}
        arguments.update(changes)
        return apply_public_stock_activation(**arguments)

    def assert_maintenance(self):
        self.control.refresh_from_db()
        self.assertEqual(self.control.state, "MAINTENANCE")
        self.assertFalse(AuditLog.objects.filter(action=ACTION).exists())

    def make_plan(self, status="DRAFT"):
        return MaterialIssue.objects.create(issue_number="ACT-" + uuid.uuid4().hex.upper(),
            client_request_id=uuid.uuid4(), request_payload_hash="x" * 64,
            production_task=self.task, product_line=self.product_line, status=status,
            created_by_employee=self.employee, updated_by_employee=self.employee)

    def seed_actual_consumption(self):
        issue = self.make_plan("ISSUED")
        MaterialIssueLine.objects.create(issue=issue, line_number=1, line_type="RAW", requirement=self.requirement,
            raw_material=self.raw_material, unit=self.requirement.unit, requested_quantity=6, issued_quantity=6,
            section_code_snapshot="PROFILE", material_number_snapshot=self.raw_material.material_number,
            material_name_snapshot=self.raw_material.material_name, unit_snapshot="支")
        OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(internal_issued_quantity=6)

    def make_cutting(self):
        ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "ACTSET"})
        fabric_section = BomSection.objects.create(bom=self.bom, section_type="FABRIC", title="面料类", line_number=2)
        cutting_section = BomSection.objects.create(bom=self.bom, section_type="FABRIC", title="裁剪明细", line_number=3)
        fabric = BomLine.objects.create(section=fabric_section, line_number=1, category="面料", part_name="面料",
            material="PE", specification="600D", unit="米", raw_values={"fabric_color_name": "绿色"})
        cutting = BomLine.objects.create(section=cutting_section, line_number=1, category="委外布面", part_name="椅面",
            material="PE", specification="450*500", unit="套", fabric_source_line=fabric,
            cutting_pieces_per_set=2, cutting_sets_per_product=1, fabric_meters_per_piece=Decimal("0.5"),
            fabric_meters_per_set=Decimal("1"), raw_values={"cutting_color": "绿色", "cutting_category": "委外布面"})
        return fabric, cutting

    def retain(self, plans):
        value = {"schema_version": 1, "operation": "RETAIN_LEGACY_UNISSUED_PLANS", "confirmed": True,
            "confirmed_by": "测试确认人", "confirmation_text": "同意保留这些旧未执行计划及审批，之后按有效 BOM 重建。",
            "confirmed_at": timezone.now().isoformat(), "target": self.target, "control_id": str(self.control.pk),
            "plans": [{"id": row["id"], "snapshot_sha256": row["snapshot_sha256"]}
                      for row in sorted((legacy_plan_snapshot(plan) for plan in plans), key=lambda value: value["id"])]}
        self.retention_path.write_text(json.dumps(value), encoding="utf-8")


class PublicStockActivationTests(ActivationFixture, TransactionTestCase):
    serialized_rollback = True

    def test_real_manifest_is_read_only_stable_and_success_is_once(self):
        stock = list(PublicStockBalance.objects.order_by("id").values())
        with CaptureQueriesContext(connection) as queries:
            report = self.activation_preview()
        self.assertTrue(report["ready"], report["blockers"])
        self.assertEqual(report["manifest_sha256"], self.activation_preview()["manifest_sha256"])
        self.assertTrue(all(query["sql"].lstrip().startswith("SELECT") for query in queries), list(queries))
        authorization = self.authorization(report)
        first, second = self.activate(report, authorization), self.activate(report, authorization)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["audit_id"], second["audit_id"])
        self.assertEqual(AuditLog.objects.filter(action=ACTION).count(), 1)
        self.assertEqual(stock, list(PublicStockBalance.objects.order_by("id").values()))

    def test_new_request_or_changed_authorization_cannot_override_activation(self):
        report = self.activation_preview()
        original = self.authorization(report)
        self.activate(report, original)
        other = self.authorization(report)
        with self.assertRaises(PublicStockActivationError):
            self.activate(report, other)
        self.assertEqual(AuditLog.objects.filter(action=ACTION).count(), 1)

    def test_missing_explicit_authorization_and_wrong_session_or_target_fail(self):
        report = self.activation_preview()
        for extra in ({"confirmed": False}, {"operation": "CONTINUE_PREPARATION"},
                      {"manifest_sha256": "0" * 64}, {"confirmed_by": ""}):
            with self.subTest(extra=extra):
                authorization = self.authorization(report, **extra)
                with self.assertRaises(PublicStockActivationError):
                    self.activate(report, authorization)
        authorization = self.authorization(report)
        with self.assertRaises(PublicStockActivationError):
            self.activate(report, authorization, expected_control_id=uuid.uuid4())
        with self.assertRaises(Exception) as error:
            self.activate(report, authorization, expected_target={**self.target, "database": "another_database"})
        self.assertIn("目标", str(error.exception))
        self.assert_maintenance()

    def test_inactive_administrator_is_rechecked_after_review(self):
        report = self.activation_preview()
        authorization = self.authorization(report)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(Exception):
            self.activate(report, authorization)
        self.assert_maintenance()

    def test_pending_review_and_missing_retention_block_and_do_not_apply(self):
        draft = self.make_plan()
        self.make_plan("PENDING_REVIEW")
        report = self.activation_preview()
        self.assertIn("LEGACY_PENDING_REVIEW", self.codes(report))
        self.assertIn("EVIDENCE_REQUIRED", self.codes(report))
        self.retain([draft])
        report = self.activation_preview(retention_evidence_path=self.retention_path)
        self.assertIn("LEGACY_PENDING_REVIEW", self.codes(report))
        authorization = self.authorization(report)
        with self.assertRaises(PublicStockActivationError):
            self.activate(report, authorization, retention_evidence_path=self.retention_path)
        self.assert_maintenance()

    def test_retention_binds_all_draft_and_returned_contents(self):
        first, second = self.make_plan(), self.make_plan("RETURNED")
        self.retain([first])
        self.assertIn("LEGACY_PLAN_REVIEW_STALE", self.codes(self.activation_preview(retention_evidence_path=self.retention_path)))
        self.retain([first, second])
        report = self.activation_preview(retention_evidence_path=self.retention_path)
        self.assertTrue(report["ready"], report["blockers"])
        second.remark = "确认以后修改的草稿"
        second.save(update_fields=["remark"])
        self.assertIn("LEGACY_PLAN_REVIEW_STALE", self.codes(self.activation_preview(retention_evidence_path=self.retention_path)))

    def test_zero_semi_stock_still_checks_selected_pipe_identity(self):
        self.assertFalse(PublicStockBalance.objects.filter(stock_kind="SEMI").exists())
        spray = Craft.objects.create(craft_type="EXTERNAL", name="启用检查喷塑", outsourcing_code="POWDER_COATING")
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
            craft=spray, craft_type_snapshot="EXTERNAL", craft_name_snapshot=spray.name)
        self.bom_line.raw_values = {**self.bom_line.raw_values, "tube_shape": "圆管", "tube_diameter": "25",
                                   "tube_thickness": "1", "tube_coating_color": "/"}
        self.bom_line.save(update_fields=["raw_values"])
        report = self.activation_preview()
        self.assertFalse(report["ready"])
        self.assertTrue(any(row.get("bom_line_id") == str(self.bom_line.pk) and row.get("craft_id") == str(spray.pk)
                            for row in report["blockers"]), report["blockers"])

    def test_all_active_schedule_products_are_checked_without_client_scope(self):
        for number in (2, 3):
            product = type(self.product_line).objects.get(pk=self.product_line.pk)
            product.pk, product.line_number = None, number
            product.save(force_insert=True)
            scheduled = ProductionScheduleProduct.objects.get(pk=self.schedule_product.pk)
            scheduled.pk, scheduled.product_line, scheduled.line_number = None, product, number
            with transaction.atomic():
                scheduled.save(force_insert=True)
                ProductionScheduleProductCraft.objects.create(schedule_product=scheduled, craft=self.plan_craft,
                    craft_type_snapshot="INTERNAL", craft_name_snapshot=self.plan_craft.name, plan_category="METAL")
        report = self.activation_preview()
        self.assertEqual(report["summary"]["active_schedule_product_count"], 3)
        self.assertEqual(sum(row["code"] == "ACTIVE_BOM_NOT_READY" for row in report["blockers"]), 2)
        with self.assertRaises(TypeError):
            self.activation_preview(scope=[str(self.product_line.pk)])

    def test_actual_quota_counters_cannot_be_reset_or_fabricated(self):
        OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(internal_issued_quantity=6)
        report = self.activation_preview()
        self.assertIn("QUOTA_HISTORY_MISMATCH", self.codes(report))
        authorization = self.authorization(report)
        with self.assertRaises(PublicStockActivationError):
            self.activate(report, authorization)
        self.assert_maintenance()

    def test_changed_opening_balance_rejects_reviewed_manifest(self):
        report = self.activation_preview()
        authorization = self.authorization(report)
        balance = PublicStockBalance.objects.get()
        PublicStockBalance.objects.filter(pk=balance.pk).update(quantity=balance.quantity + 1,
            meter_quantity=balance.meter_quantity + balance.raw_bar_length_m)
        current = self.activation_preview()
        self.assertIn("FORMAL_OPENING_BALANCES_CHANGED", self.codes(current))
        with self.assertRaises(PublicStockActivationError):
            self.activate(report, authorization)
        self.assert_maintenance()

    def test_changed_bom_after_review_is_stale_even_when_still_valid(self):
        report = self.activation_preview()
        authorization = self.authorization(report)
        self.bom_line.part_name = "现场改变的部位名"
        self.bom_line.save(update_fields=["part_name"])
        with self.assertRaisesMessage(PublicStockActivationError, "ACTIVATION_MANIFEST_STALE"):
            self.activate(report, authorization)
        self.assert_maintenance()

    def test_trial_switch_does_not_authorize_activation(self):
        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            self.assertIn("TRIAL_SWITCH_ENABLED", self.codes(self.activation_preview()))
        self.assert_maintenance()

    def test_nested_transaction_is_rejected_before_using_its_old_snapshot(self):
        report = self.activation_preview()
        authorization = self.authorization(report)
        with transaction.atomic():
            with self.assertRaisesMessage(PublicStockActivationError, "ACTIVATION_TOP_LEVEL_REQUIRED"):
                self.activate(report, authorization)
        self.assert_maintenance()

    def test_self_consistent_meter_movement_cannot_disagree_with_balance(self):
        move = PublicStockMovement.objects.get()
        PublicStockMovement.objects.filter(pk=move.pk).update(meter_quantity=move.meter_quantity + Decimal("1"),
            after_meter_quantity=move.after_meter_quantity + Decimal("1"))
        report = self.activation_preview()
        self.assertIn("FORMAL_OPENING_LEDGER_TAIL", self.codes(report))
        self.assertIn("FORMAL_OPENING_METER_INVALID", self.codes(report))

    def test_used_component_removal_or_changed_pipe_conversion_is_blocked(self):
        self.seed_actual_consumption()
        original_component = self.bom_line.component_identity
        self.bom_line.component_identity = uuid.uuid4()
        self.bom_line.save(update_fields=["component_identity"])
        blockers = []
        boms, limits = _active_boms(blockers)
        _quotas(blockers, limits, {row["product_id"] for row in boms})
        self.assertIn("QUOTA_USED_COMPONENT_CHANGED", {row["code"] for row in blockers})
        self.bom_line.component_identity = original_component
        plan = pipe_plan(cutting_length_mm=501, pieces_per_product=2, pieces_per_bar=6, order_quantity=1000)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.save()
        blockers = []
        boms, limits = _active_boms(blockers)
        _quotas(blockers, limits, {row["product_id"] for row in boms})
        self.assertIn("QUOTA_USED_COMPONENT_CHANGED", {row["code"] for row in blockers})

    def test_complete_cutting_text_and_usage_still_require_real_fabric_mapping(self):
        fabric, cutting = self.make_cutting()
        for mapping in (None, self.raw_material.pk):
            fabric.raw_values = {"fabric_color_name": "绿色"}
            if mapping:
                fabric.raw_values["source_raw_material_id"] = str(mapping)
            fabric.save(update_fields=["raw_values"])
            report = self.activation_preview()
            self.assertTrue(any(row["code"] == "CUTTING_MATERIAL_INVALID" and row.get("bom_line_id") == str(cutting.pk)
                                for row in report["blockers"]), report["blockers"])

    def test_complete_historical_pipe_basis_and_hash_must_match(self):
        self.seed_actual_consumption()
        contribution = self.requirement.contributions.get(is_current=True)
        original = dict(contribution.calculation_basis)
        for changed in ({**original, "pieces_per_bar": 99}, {**original, "raw_material_id": str(uuid.uuid4())}):
            contribution.calculation_basis = changed
            contribution.save(update_fields=["calculation_basis"])
            blockers = []
            boms, limits = _active_boms(blockers)
            _quotas(blockers, limits, {row["product_id"] for row in boms})
            self.assertIn("QUOTA_SOURCE_EVIDENCE_CHANGED", {row["code"] for row in blockers})

    def test_valid_fabric_mapping_change_alone_changes_reviewed_manifest(self):
        fabric, _ = self.make_cutting()
        category = ProductCategory.objects.get(category_name="面料", item_type="MATERIAL")
        unit = ProductionUnit.objects.get(unit_name="米")
        reports = []
        for suffix in ("A", "B"):
            raw = RawMaterialInformation.objects.create(material_number="ACT-FABRIC-" + suffix,
                item_type="MATERIAL", category=category, unit=unit, material_name="激活测试面料" + suffix,
                specification="600D", material="PE")
            fabric.raw_values = {"fabric_color_name": "绿色", "source_inventory_material_id": str(raw.pk)}
            # 不更新 BOM 单头，用以验证摘要直接绑定实际扣料映射。
            fabric.save(update_fields=["raw_values"])
            reports.append(self.activation_preview())
        for report in reports:
            self.assertTrue(report["ready"], report["blockers"])
        self.assertNotEqual(reports[0]["manifest_sha256"], reports[1]["manifest_sha256"])

    def test_metal_only_pipe_requires_active_piece_unit_before_any_semi_stock(self):
        self.assertFalse(self.schedule_product.crafts.filter(craft__outsourcing_code="POWDER_COATING").exists())
        self.assertFalse(PublicStockBalance.objects.filter(stock_kind="SEMI").exists())
        ProductionUnit.objects.filter(unit_name="支").update(status="INACTIVE")
        report = self.activation_preview()
        self.assertIn("PIPE_UNIT_INVALID", self.codes(report))

    def test_latest_verified_bom_without_real_lines_is_blocked(self):
        empty = type(self.bom).objects.get(pk=self.bom.pk)
        empty.pk, empty.bom_number, empty.version_number = None, "BOM-ACT-EMPTY", 2
        empty.line_count = 0
        empty.save(force_insert=True)
        report = self.activation_preview()
        self.assertIn("ACTIVE_BOM_EMPTY", self.codes(report))

    def test_audit_failure_rolls_back_public_state(self):
        report = self.activation_preview()
        authorization = self.authorization(report)
        with patch("apps.inventory.public_stock_activation.AuditLog.objects.create", side_effect=RuntimeError("审计失败")):
            with self.assertRaises(RuntimeError):
                self.activate(report, authorization)
        self.assert_maintenance()

    def test_cli_refuses_incomplete_apply_and_output_overwrite(self):
        with self.assertRaises(CommandError):
            call_command("activate_public_stock", "--apply")
        with self.assertRaises(CommandError):
            call_command("activate_public_stock", "--output", str(self.evidence_path))
        self.assert_maintenance()


class PublicStockActivationTransactionTests(ActivationFixture, TransactionTestCase):
    serialized_rollback = True

    def test_default_cli_is_a_real_read_only_repeatable_read_transaction(self):
        statements = []
        def record(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)
        output = io.StringIO()
        with connection.execute_wrapper(record):
            call_command("activate_public_stock", "--actor-employee", str(self.employee.pk),
                         "--backup-evidence", str(self.evidence_path), stdout=output)
        result = json.loads(output.getvalue())
        self.assertTrue(result["read_only"])
        self.assertTrue(result["ready"], result["blockers"])
        self.assertTrue(any("REPEATABLE READ, READ ONLY" in sql for sql in statements))
        self.assertFalse(any(sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for sql in statements))
        self.assert_maintenance()

    def test_concurrent_identical_authorization_has_one_activation_audit(self):
        report = build_public_stock_activation_manifest(actor_employee=self.employee, backup_evidence_path=self.evidence_path)
        self.assertTrue(report["ready"], report["blockers"])
        authorization = self.authorization(report)
        barrier, results = threading.Barrier(2), []
        def run():
            connections.close_all()
            try:
                barrier.wait(timeout=5)
                results.append(self.activate(report, authorization))
            except Exception as error:
                results.append(error)
            finally:
                connections.close_all()
        workers = [threading.Thread(target=run) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(25)
        self.assertFalse(any(worker.is_alive() for worker in workers), results)
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertCountEqual([result["replayed"] for result in results], [False, True])
        self.assertEqual(AuditLog.objects.filter(action=ACTION).count(), 1)


# 使用原接续专项的实际历史凭证构造方法，不模拟接续校验结果。
from apps.material_issues.tests import test_legacy_public_transition as legacy_fixture
from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4Fixture


class PublicStockActivationTransitTests(MetalProcessingP4Fixture, APITestCase):
    make_manifest = legacy_fixture.LegacyPublicTransitionTests.make_manifest
    adopt = legacy_fixture.LegacyPublicTransitionTests.adopt
    context = legacy_fixture.LegacyPublicTransitionTests.context
    good_payload = legacy_fixture.LegacyPublicTransitionTests.good_payload
    good_return = legacy_fixture.LegacyPublicTransitionTests.good_return

    def setUp(self):
        super().setUp()
        # 父夹具实际已领 210 支，初始只完工 12 支；把余下 198 支也真实完工再交接。
        self.write("completions", self.complete_payload(198))
        self.handoff = self.create_original_handoff(210)
        self.manifest = self.make_manifest()
        self.manifest["handoff_total_pieces"] = 210

    def test_trusted_in_transit_handoff_does_not_need_fake_return_or_zeroing(self):
        self.adopt()
        before = list(PublicStockMovement.objects.values())
        blockers = []
        report = _legacy_transit(blockers)
        self.assertEqual(len(report["handoffs"]), 1)
        self.assertEqual(report["handoffs"][0]["totals"]["handoff_pieces"], 210)
        self.assertEqual(report["handoffs"][0]["totals"]["returned_pieces"], 0)
        self.assertNotIn("LEGACY_HANDOFF_NOT_ADOPTED", {row["code"] for row in blockers})
        self.assertNotIn("LEGACY_PROCESSING_REMAINDER_UNRESOLVED", {row["code"] for row in blockers})
        self.assertEqual(before, list(PublicStockMovement.objects.values()))

    def test_missing_transition_is_reported_as_blocker(self):
        blockers = []
        _legacy_transit(blockers)
        self.assertIn("LEGACY_HANDOFF_NOT_ADOPTED", {row["code"] for row in blockers})

    def test_fully_returned_historical_handoff_does_not_require_bridge(self):
        self.good_return(self.good_payload(210))
        blockers = []
        report = _legacy_transit(blockers)
        self.assertTrue(report["handoffs"][0]["settled"])
        self.assertIsNone(report["handoffs"][0]["transition_id"])
        self.assertNotIn("LEGACY_HANDOFF_NOT_ADOPTED", {row["code"] for row in blockers})
        self.assertNotIn("LEGACY_PROCESSING_REMAINDER_UNRESOLVED", {row["code"] for row in blockers})
