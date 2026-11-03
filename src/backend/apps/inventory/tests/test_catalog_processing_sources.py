from copy import deepcopy
from decimal import Decimal
import json
from uuid import uuid4

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.catalog_requirements import catalog_requirement_specs
from apps.material_issues.tests import test_catalog_issue_api as issue_fixture

from .test_public_stock_services import PublicStockFixture
from ..catalog_processing_sources import freeze_catalog_pipe_source
from ..catalog_stock_identity import build_catalog_stock_identity
from ..models import PublicStockBalance, PublicStockMovement, WarehouseZone


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class CatalogProcessingSourceTests(PublicStockFixture, APITestCase):
    # 借用真实领料 API 流程，不继承其测试类，避免重复执行无关用例。
    payload = issue_fixture.CatalogIssueApiTests.payload
    create = issue_fixture.CatalogIssueApiTests.create
    issue = issue_fixture.CatalogIssueApiTests.issue

    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="加工投入管材")
        self.saved = {
            "schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name,
            "scope": "BASE", "processing_state": "RAW", "processing_stage": "RAW",
            "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "矩形管", "section_size": "20*28", "thickness": "0.8", "length": "6000"},
            "unit_id": str(self.root_unit.pk), "unit_name": "根", "display_name": "加工投入管材 / 根",
        }
        self.set_source()

    def set_source(self):
        self.bom_line.material_catalog = self.catalog
        self.bom_line.raw_values["pipe_plan_version"] = 3
        self.bom_line.material_selection_snapshot = self.saved
        self.bom_line.material_quantity = None
        self.bom_line.unit = "根"
        self.bom_line.save()
        self.identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.saved, raw_bar_length_m=self.bom_line.raw_bar_length_m)
        specs, blockers = catalog_requirement_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        self.spec = specs[0]

    def issued_line(self):
        self.credit(10, identity=self.identity)
        issue, _ = self.issue(self.create("12"))
        return issue.lines.get()

    def assert_source_invalid(self, line):
        with self.assertRaises(ValidationError) as caught:
            freeze_catalog_pipe_source(line)
        self.assertIn("source", caught.exception.detail)

    def test_actual_root_and_meter_movements_preserve_saved_length(self):
        line = self.issued_line()
        result = freeze_catalog_pipe_source(line)
        self.assertEqual((result["issued_pieces"], result["bar_count"]), (12, 2))
        self.assertEqual(Decimal(result["meters"]), 2 * Decimal(line.conversion_snapshot["raw_bar_length_m"]))
        self.assertEqual(result["input_material_selection_snapshot"], self.saved)
        self.assertEqual(result["public_bom_snapshot"], line.conversion_snapshot["public_bom_snapshot"])
        allocation = line.public_stock_allocations.get()
        self.assertEqual(result["allocations"][0]["movement_id"], str(allocation.movement_id))
        self.assertEqual(result["raw_bar_length_m"], "2.54")
        self.assertEqual(result["meters"], "5.08")
        self.assertEqual(result["allocations"][0]["raw_bar_length_m"], "2.54")
        self.assertEqual(result["allocations"][0]["meter_quantity"], "5.08")
        self.assertEqual(allocation.meter_quantity, Decimal("5.08"))
        self.assertEqual(allocation.movement.meter_quantity, Decimal("5.08"))
        self.assertEqual((allocation.movement.before_meter_quantity, allocation.movement.after_meter_quantity),
                         (Decimal("25.40"), Decimal("20.32")))
        self.assertEqual(result["input_material_selection_snapshot"]["attributes"]["length"], "6000")
        self.assertEqual(result["public_stock_allocations"], result["allocations"])
        json.dumps(result, allow_nan=False)
        movement = allocation.movement
        changed = deepcopy(movement.snapshot)
        changed["public_identity"]["raw_bar_length_m"] = "2.540"
        changed["conversion"]["public_identity"]["raw_bar_length_m"] = "2.540"
        PublicStockMovement.objects.filter(pk=movement.pk).update(snapshot=changed)
        self.assertEqual(freeze_catalog_pipe_source(line)["meters"], "5.08")
        result["conversion_snapshot"]["material_selection_snapshot"]["name"] = "不得回写原凭证"
        self.assertEqual(line.conversion_snapshot["material_selection_snapshot"]["name"], self.saved["name"])

    def test_multiple_real_allocations_are_all_proven(self):
        other_zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name="加工投入第二库区")
        self.credit(1, identity=self.identity)
        self.credit(1, identity=self.identity, zone=other_zone)
        issue, _ = self.issue(self.create("12"))
        result = freeze_catalog_pipe_source(issue.lines.get())
        self.assertEqual(len(result["allocations"]), 2)
        self.assertEqual([(row["pieces"], row["bar_count"]) for row in result["allocations"]], [(6, 1), (6, 1)])
        self.assertEqual([row["meter_quantity"] for row in result["allocations"]], ["2.54", "2.54"])
        self.assertEqual(result["meters"], "5.08")

    def test_pool_metadata_and_later_catalog_or_bom_changes_do_not_rewrite_issue(self):
        previous = deepcopy(self.saved)
        previous.update(name="同池首单旧名称", catalog_version="原始保存版本", display_name="首单旧展示")
        previous_identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=previous, raw_bar_length_m=self.bom_line.raw_bar_length_m)
        self.assertEqual(previous_identity["identity_key"], self.identity["identity_key"])
        self.credit(10, identity=previous_identity)
        issue, _ = self.issue(self.create("12"))
        line = issue.lines.get()
        MaterialCatalog.objects.filter(pk=self.catalog.pk).update(name="目录后续改名", archived_at=timezone.now())
        type(self.bom_line).objects.filter(pk=self.bom_line.pk).update(part_name="后续 BOM 部位名称", cutting_length_mm=100)
        with CaptureQueriesContext(connection) as queries:
            result = freeze_catalog_pipe_source(line)
        self.assertEqual(result["input_material_selection_snapshot"], self.saved)
        self.assertEqual(result["part_name"], "前脚管")
        self.assertFalse(any('FROM "material_catalog"' in query["sql"] for query in queries))
        self.assertEqual(PublicStockBalance.objects.get().identity_snapshot["material_selection_snapshot"]["name"], previous["name"])

    def test_exhausted_current_balance_does_not_remove_proven_input(self):
        line = self.issued_line()
        balance = PublicStockBalance.objects.get()
        self.debit(balance.pk, balance.quantity)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 0)
        self.assertEqual(PublicStockBalance.objects.get().meter_quantity, 0)
        result = freeze_catalog_pipe_source(line)
        self.assertEqual((result["issued_pieces"], result["bar_count"], result["meters"]), (12, 2, "5.08"))

    def test_missing_actual_movement_is_rejected(self):
        line = self.issued_line()
        line.public_stock_allocations.update(movement=None)
        self.assert_source_invalid(line)

    def test_other_source_or_task_movement_is_rejected(self):
        line = self.issued_line()
        movement = line.public_stock_allocations.get().movement
        for change in ({"source_id": uuid4()}, {"source_line_id": uuid4()}, {"production_task_id": None},
                       {"product_line_id": None}, {"bom_line_id": None}):
            with self.subTest(change=change):
                PublicStockMovement.objects.filter(pk=movement.pk).update(**change)
                self.assert_source_invalid(line)
                PublicStockMovement.objects.filter(pk=movement.pk).update(**{key: getattr(movement, key) for key in change})

    def test_forged_out_snapshot_or_allocation_quantity_is_rejected(self):
        line = self.issued_line()
        allocation = line.public_stock_allocations.get()
        movement = allocation.movement
        for key, value in (("issue_line_id", str(uuid4())), ("requested_quantity", "6"), ("stock_quantity", "1"),
                           ("public_identity", {}), ("conversion", {})):
            with self.subTest(field=key):
                altered = {**movement.snapshot, key: value}
                PublicStockMovement.objects.filter(pk=movement.pk).update(snapshot=altered)
                self.assert_source_invalid(line)
        PublicStockMovement.objects.filter(pk=movement.pk).update(snapshot=movement.snapshot)
        line.public_stock_allocations.update(requested_quantity=18)
        self.assert_source_invalid(line)
        line.public_stock_allocations.update(requested_quantity=allocation.requested_quantity)
        for meters in (None, Decimal("1.00")):
            with self.subTest(allocation_meters=meters):
                line.public_stock_allocations.update(meter_quantity=meters)
                self.assert_source_invalid(line)
        line.public_stock_allocations.update(meter_quantity=allocation.meter_quantity)
        # 保持数据库的米数增减约束成立，仍须拒绝不符合实际原长的流水。
        PublicStockMovement.objects.filter(pk=movement.pk).update(meter_quantity=movement.meter_quantity * 2,
            before_meter_quantity=movement.before_meter_quantity * 2,
            after_meter_quantity=movement.after_meter_quantity * 2)
        self.assert_source_invalid(line)

    def test_malformed_or_inconsistent_frozen_values_are_controlled_errors(self):
        line = self.issued_line()
        original = deepcopy(line.conversion_snapshot)
        changes = (
            ("kind", "CATALOG"), ("physical_issued_quantity", "1"), ("physical_issued_quantity", "NaN"),
            ("manufacturing_issued_pieces", None), ("manufacturing_quantity_source", "UNKNOWN"),
            ("pieces_per_bar", "0"), ("raw_bar_length_m", "Infinity"), ("quantity_unit_name", "根"),
            ("quantity_unit_id", str(uuid4())), ("component_identity", str(uuid4())),
            ("manufacturing_plan", []), ("public_bom_snapshot", {}), ("public_identity", {}),
        )
        for key, value in changes:
            with self.subTest(field=key, value=value):
                line.conversion_snapshot = {**deepcopy(original), key: value}
                self.assert_source_invalid(line)
        line.conversion_snapshot = original
        different_length = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.saved, raw_bar_length_m="6.00")
        line.conversion_snapshot = {**deepcopy(original), "public_identity": different_length}
        self.assert_source_invalid(line)
        line.conversion_snapshot = original
        line.material_selection_snapshot = {**line.material_selection_snapshot, "name": "仅改本行保存名称"}
        self.assert_source_invalid(line)
