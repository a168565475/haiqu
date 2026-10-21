"""本次资料更正的精确匹配和实际库存事务回归；夹具只写隔离测试库。"""

from copy import deepcopy
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.inventory.public_bom_snapshot import freeze_bom_line
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.material_issues.models import MaterialIssueLine
from apps.material_issues.processing_selectors import frozen_source
from apps.outsourcing.tests.test_tube_orders_api import TubeApiFixture

from .. import ht26011_component_correction as correction


class CorrectionSnapshotTests(SimpleTestCase):
    def attributes(self):
        return {"fields": [{"key": "part_name", "value": correction.OLD_NAME},
                           {"key": "material", "value": "铁-硬管"}]}

    def test_supplier_sheet_matches_source_id_not_array_position_or_name(self):
        other = {"source_purchase_order_line_id": str(uuid4()), "part_name": correction.OLD_NAME,
                 "material_attributes_snapshot": self.attributes(), "quantity": "808", "amount": "4363.2"}
        target = {**deepcopy(other), "source_purchase_order_line_id": correction.PURCHASE_ID}
        content = {"lines": [other, target], "total_amount": "8726.4", "remark": correction.OLD_NAME}
        original = deepcopy(content)
        updated = correction.rename_sheet_content(content)
        self.assertEqual(content, original)
        self.assertEqual(updated["lines"][0], other)
        self.assertEqual(updated["lines"][1]["part_name"], correction.NEW_NAME)
        self.assertEqual(updated["lines"][1]["quantity"], "808")
        self.assertEqual(updated["total_amount"], original["total_amount"])
        self.assertEqual(updated["remark"], correction.OLD_NAME)

    def test_duplicate_or_missing_sheet_source_is_rejected(self):
        target = {"source_purchase_order_line_id": correction.PURCHASE_ID,
                  "part_name": correction.OLD_NAME, "material_attributes_snapshot": self.attributes()}
        for rows in ([], [target, deepcopy(target)]):
            with self.subTest(rows=len(rows)), self.assertRaises(CommandError):
                correction.rename_sheet_content({"lines": rows})

    def test_conversion_changes_only_three_name_locations(self):
        value = {"bom_line_id": correction.LINE_ID, "component_identity": correction.COMPONENT_ID,
                 "part_name": correction.OLD_NAME, "bom_attributes": self.attributes()["fields"],
                 "pieces_per_bar": 5, "public_identity": {"identity_key": "unchanged-raw-stock"},
                 "public_bom_snapshot": {"line": {"id": correction.LINE_ID, "part_name": correction.OLD_NAME}}}
        original = deepcopy(value)
        updated = correction.rename_conversion(value)
        self.assertEqual(value, original)
        self.assertEqual(updated["part_name"], correction.NEW_NAME)
        self.assertEqual(updated["public_bom_snapshot"]["line"]["part_name"], correction.NEW_NAME)
        self.assertEqual(updated["bom_attributes"][0]["value"], correction.NEW_NAME)
        self.assertEqual(updated["public_identity"], original["public_identity"])
        self.assertEqual(updated["pieces_per_bar"], 5)
        value["component_identity"] = str(uuid4())
        with self.assertRaises(CommandError):
            correction.rename_conversion(value)

    def test_command_defaults_to_dry_run(self):
        with patch("apps.boms.management.commands.correct_ht26011_tube_component.correct_component",
                   return_value={"status": "DRY_RUN"}) as corrected:
            call_command("correct_ht26011_tube_component", stdout=StringIO())
        self.assertFalse(corrected.call_args.kwargs["apply"])


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class CorrectionTransactionTests(TubeApiFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.metal_bom_line.part_name = correction.OLD_NAME
        self.metal_bom_line.save(update_fields=["part_name"])
        old_identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        self.old_stock = credit_public_stock(identity=old_identity, zone=self.semi_zone, quantity=4000,
            source_type="TEST_CORRECTION_OPENING", source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee).balance
        self.metal_bom_line.part_name = correction.NEW_NAME
        new_identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        self.metal_bom_line.part_name = correction.OLD_NAME
        snapshot = deepcopy(self.issue_line.conversion_snapshot)
        snapshot["part_name"] = correction.OLD_NAME
        snapshot["public_bom_snapshot"] = freeze_bom_line(self.metal_bom_line)
        snapshot["bom_attributes"] = [{"key": "part_name", "value": correction.OLD_NAME}]
        self.issue_line.conversion_snapshot = snapshot
        self.issue_line.save(update_fields=["conversion_snapshot"])
        movement = self.issue_line.public_stock_allocations.get().movement
        movement.snapshot["conversion"] = deepcopy(snapshot)
        movement.save(update_fields=["snapshot"])
        changed = deepcopy(snapshot)
        changed["part_name"] = correction.NEW_NAME
        changed["public_bom_snapshot"]["line"]["part_name"] = correction.NEW_NAME
        changed["bom_attributes"][0]["value"] = correction.NEW_NAME
        moved_snapshot = deepcopy(movement.snapshot)
        moved_snapshot["conversion"] = changed
        self.raw_before = correction.record(PublicStockBalance.objects.get(pk=self.raw_balance.pk))
        self.original_movement = correction.record(movement)
        self.plan = {"changes": [(self.metal_bom_line, {"part_name": correction.NEW_NAME}),
                                 (self.issue_line, {"conversion_snapshot": changed}), (movement, {"snapshot": moved_snapshot})],
            "payload": {"evidence": [{"model": "inventory.PublicStockBalance", "record": self.raw_before}]},
            "manifest_sha256": "reviewed-manifest", "balance": self.old_stock, "identity": new_identity,
            "task": self.task, "product": self.product_line, "line": self.metal_bom_line,
            "issue": self.issue_line, "receipt": None}
        self.load_patch = patch.object(correction, "load_plan", return_value=self.plan)
        self.load_patch.start()
        self.addCleanup(self.load_patch.stop)
        self.id_patch = patch.object(correction, "LINE_ID", str(self.metal_bom_line.pk))
        self.id_patch.start()
        self.addCleanup(self.id_patch.stop)

    def apply(self, expected="reviewed-manifest"):
        return correction.correct_component(apply=True, actor_id=self.employee.pk, expected_manifest=expected)

    def assert_rolled_back(self):
        self.metal_bom_line.refresh_from_db()
        self.old_stock.refresh_from_db()
        self.assertEqual(self.metal_bom_line.part_name, correction.OLD_NAME)
        self.assertEqual(self.old_stock.quantity, 4000)
        self.assertFalse(PublicStockMovement.objects.filter(source_type=correction.SOURCE_TYPE).exists())
        self.assertFalse(AuditLog.objects.filter(object_type=correction.AUDIT_TYPE).exists())
        actual = correction.record(PublicStockMovement.objects.get(pk=self.original_movement["id"]))
        self.assertEqual(actual, self.original_movement)

    def test_default_preflight_and_stale_manifest_never_write(self):
        self.assertEqual(correction.correct_component()["status"], "DRY_RUN")
        with self.assertRaises(CommandError):
            self.apply("stale-manifest")
        self.assert_rolled_back()

    def test_transfer_preserves_total_raw_stock_and_frozen_issue_and_replays_once(self):
        first = self.apply()
        self.assertEqual(first["status"], "APPLIED")
        self.old_stock.refresh_from_db()
        new_stock = PublicStockBalance.objects.get(pk=first["new_balance_id"])
        self.assertEqual((self.old_stock.quantity, new_stock.quantity), (2000, 2000))
        self.assertEqual(correction.record(PublicStockBalance.objects.get(pk=self.raw_balance.pk)), self.raw_before)
        line = MaterialIssueLine.objects.select_related("issue__product_line", "requirement").get(pk=self.issue_line.pk)
        self.assertEqual(frozen_source(line)["part_name"], correction.NEW_NAME)
        self.assertEqual(self.apply()["status"], "ALREADY_APPLIED")
        self.assertEqual(PublicStockMovement.objects.filter(source_type=correction.SOURCE_TYPE).count(), 2)
        self.assertEqual(AuditLog.objects.filter(object_type=correction.AUDIT_TYPE).count(), 1)

    def test_credit_failure_rolls_back_names_snapshots_and_debit(self):
        with patch.object(correction, "credit_public_stock", side_effect=RuntimeError("模拟新身份入账失败")):
            with self.assertRaisesMessage(RuntimeError, "模拟新身份入账失败"):
                self.apply()
        self.assert_rolled_back()

    def test_audit_failure_rolls_back_both_stock_movements(self):
        with patch.object(correction, "write_audit_log", side_effect=RuntimeError("模拟审计失败")):
            with self.assertRaisesMessage(RuntimeError, "模拟审计失败"):
                self.apply()
        self.assert_rolled_back()
