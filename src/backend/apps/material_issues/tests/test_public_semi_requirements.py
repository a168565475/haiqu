from decimal import Decimal
from types import SimpleNamespace
import uuid

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.boms.material_flow_calculations import pipe_plan
from apps.boms.models import Bom, BomLine, BomSection
from apps.inventory.models import PublicStockBalance, SemiFinishedStockBalance, WarehouseZone
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.stock_services import InventoryStockValidationError
from apps.inventory.tests.test_public_stock_services import PublicStockFixture
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft

from ..models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement, OrderSemiFinishedRequirement
from ..public_semi_requirements import (
    build_public_semi_specs, legacy_pending_semi_quantities, public_semi_identity,
    public_semi_requirement_rows, sync_public_semi_requirements,
)


class PublicSemiRequirementTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.credit(5000, identity=self.semi_identity, zone=self.semi_zone)

    def rows(self, *, task=None, product=None, exclude=None):
        return public_semi_requirement_rows((task or self.task).pk, (product or self.product_line).pk,
                                            exclude_issue_id=exclude)

    def header(self, *, status="DRAFT", stock_mode="PUBLIC_V2", task=None, product=None):
        return MaterialIssue.objects.create(issue_number="PSREQ-" + uuid.uuid4().hex,
            client_request_id=uuid.uuid4(), request_payload_hash="test", production_task=task or self.task,
            product_line=product or self.product_line, status=status, stock_mode=stock_mode,
            created_by_employee=self.employee, updated_by_employee=self.employee)

    def sync(self, issue=None):
        issue = issue or self.header()
        specs, blockers = build_public_semi_specs(issue.production_task_id, issue.product_line_id)
        self.assertFalse(blockers, blockers)
        return next(iter(sync_public_semi_requirements(issue, {specs[0]["id"]}).values()))

    def public_line(self, issue, requirement, quantity):
        return MaterialIssueLine.objects.create(issue=issue, line_number=1, semi_requirement=requirement,
            line_type="SEMI", unit=requirement.unit, section_code_snapshot="SEMI", material_number_snapshot="",
            material_name_snapshot="前脚管", specification_snapshot="20*28*0.8", color_snapshot="黑色",
            unit_snapshot="支", requested_quantity=quantity)

    def legacy_line(self, *, quantity=20, status="ISSUED", component=None):
        balance, _ = SemiFinishedStockBalance.objects.get_or_create(production_task=self.task,
            product_line=self.product_line, bom_line=self.bom_line, completed_craft=self.craft,
            color_snapshot="黑色", unit=self.piece_unit, zone=self.semi_zone, quality="AVAILABLE",
            defaults={"quantity": 0})
        issue = self.header(status=status, stock_mode="LEGACY")
        return MaterialIssueLine.objects.create(issue=issue, line_number=1, semi_finished_balance=balance,
            line_type="SEMI", unit=self.piece_unit, section_code_snapshot="SEMI", material_number_snapshot="旧单",
            material_name_snapshot="前脚管", specification_snapshot="20*28*0.8*6140", color_snapshot="黑色",
            unit_snapshot="支", requested_quantity=quantity, issued_quantity=quantity if status == "ISSUED" else None,
            conversion_snapshot={"component_identity": str(component or self.bom_line.component_identity)})

    def other_order(self):
        task = ProductionTask.objects.get(pk=self.task.pk)
        task.pk = uuid.uuid4()
        task.task_number, task.contract_number, task.order_number = "PSREQ-OTHER", "PSREQ-CONTRACT", "PSREQ-ORDER"
        task.save(force_insert=True)
        product = ProductionTaskProduct.objects.get(pk=self.product_line.pk)
        product.pk, product.production_task = uuid.uuid4(), task
        product.save(force_insert=True)
        bom = Bom.objects.get(pk=self.bom.pk)
        bom.pk, bom.production_task, bom.product_line, bom.bom_number = uuid.uuid4(), task, product, "PSREQ-BOM2"
        bom.save(force_insert=True)
        section = BomSection.objects.create(bom=bom, line_number=1, section_type="PROFILE", title="管材类")
        line = BomLine.objects.get(pk=self.bom_line.pk)
        line.pk, line.section, line.component_identity = uuid.uuid4(), section, uuid.uuid4()
        line.save(force_insert=True)
        return task, product

    def test_get_is_read_only_and_pipe_quota_uses_net_pieces_not_raw_allowance(self):
        raw_before = list(OrderMaterialRequirement.objects.values())
        with CaptureQueriesContext(connection) as captured:
            rows, blockers = self.rows()
        self.assertFalse(blockers, blockers)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(rows[0]["required_quantity"]), 1000)
        self.assertEqual(Decimal(rows[0]["available_stock"]), 5000)
        self.assertEqual(Decimal(rows[0]["max_issue_quantity"]), 1000)
        self.assertFalse(OrderSemiFinishedRequirement.objects.exists())
        self.assertEqual(list(OrderMaterialRequirement.objects.values()), raw_before)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in captured))
        self.assertNotIn("semi_balance_allocations", rows[0])
        self.assertEqual(rows[0]["material_number"], "")

    def test_same_public_part_is_eligible_for_other_order_with_independent_quota(self):
        task, product = self.other_order()
        first, _ = self.rows()
        second, blockers = self.rows(task=task, product=product)
        self.assertFalse(blockers, blockers)
        self.assertEqual(first[0]["stock_item_id"], second[0]["stock_item_id"])
        self.assertNotEqual(first[0]["requirement_id"], second[0]["requirement_id"])
        self.assertEqual(Decimal(second[0]["available_stock"]), 5000)
        self.assertFalse(SemiFinishedStockBalance.objects.filter(production_task=task).exists())

    def test_public_inventory_shortage_caps_each_order_below_its_quota(self):
        PublicStockBalance.objects.filter(stock_kind="SEMI").update(quantity=125)
        rows, blockers = self.rows()
        self.assertFalse(blockers)
        self.assertEqual(Decimal(rows[0]["required_quantity"]), 1000)
        self.assertEqual(Decimal(rows[0]["max_issue_quantity"]), 125)

    def test_legacy_zero_stock_still_inherits_issued_and_pending_order_quantity(self):
        self.legacy_line(quantity=20)
        pending_line = self.legacy_line(quantity=30, status="PENDING_REVIEW")
        rows, blockers = self.rows()
        self.assertFalse(blockers, blockers)
        self.assertEqual(Decimal(rows[0]["internal_issued_quantity"]), 20)
        self.assertEqual(Decimal(rows[0]["pending_issue_quantity"]), 30)
        self.assertEqual(Decimal(rows[0]["order_remaining"]), 950)
        requirement = self.sync()
        self.assertEqual(requirement.internal_issued_quantity, 20)
        self.assertEqual(legacy_pending_semi_quantities([requirement])[requirement.pk], 30)
        self.assertEqual(legacy_pending_semi_quantities([requirement], pending_line.issue_id)[requirement.pk], 0)
        self.assertEqual(public_semi_identity(requirement), self.semi_identity)

    def test_repeated_sync_preserves_public_issued_and_inherits_only_new_legacy_increment(self):
        self.legacy_line(quantity=20)
        requirement = self.sync()
        OrderSemiFinishedRequirement.objects.filter(pk=requirement.pk).update(internal_issued_quantity=25)
        self.legacy_line(quantity=10)
        self.assertEqual(self.sync().internal_issued_quantity, 35)
        self.assertEqual(self.sync().internal_issued_quantity, 35)

    def test_legacy_component_conflict_blocks_instead_of_resetting_counter(self):
        self.legacy_line(component=uuid.uuid4())
        _, blockers = self.rows()
        self.assertIn("SEMI_LEGACY_HISTORY_UNRESOLVED", {row["code"] for row in blockers})
        valid_specs, _ = build_public_semi_specs(self.task.pk, self.product_line.pk)
        with self.assertRaises(InventoryStockValidationError):
            sync_public_semi_requirements(self.header(), {valid_specs[0]["id"]})
        self.assertFalse(OrderSemiFinishedRequirement.objects.exists())

    def test_changed_inherited_history_is_not_silently_recomputed(self):
        old = self.legacy_line(quantity=20)
        requirement = self.sync()
        MaterialIssueLine.objects.filter(pk=old.pk).update(issued_quantity=15)
        with self.assertRaises(InventoryStockValidationError) as raised:
            sync_public_semi_requirements(self.header(), {requirement.pk})
        self.assertEqual(raised.exception.api_error_code, "SEMI_LEGACY_HISTORY_CHANGED")
        requirement.refresh_from_db()
        self.assertEqual(requirement.internal_issued_quantity, 20)

    def test_own_pending_excluded_from_order_and_pool_but_other_orders_still_reserve(self):
        first_issue = self.header(status="PENDING_REVIEW")
        first = self.sync(first_issue)
        self.public_line(first_issue, first, 40)
        task, product = self.other_order()
        second_issue = self.header(status="PENDING_REVIEW", task=task, product=product)
        second = self.sync(second_issue)
        self.public_line(second_issue, second, 50)
        rows, blockers = self.rows()
        self.assertFalse(blockers)
        self.assertEqual(Decimal(rows[0]["pending_issue_quantity"]), 40)
        self.assertEqual(Decimal(rows[0]["public_pending_quantity"]), 90)
        self.assertEqual(Decimal(rows[0]["available_stock"]), 5000)
        self.assertEqual(Decimal(rows[0]["order_remaining"]), 960)
        rows, _ = self.rows(exclude=first_issue.pk)
        self.assertEqual(Decimal(rows[0]["pending_issue_quantity"]), 0)
        self.assertEqual(Decimal(rows[0]["public_pending_quantity"]), 50)

    def test_issued_identity_change_is_blocked_without_new_allowance(self):
        requirement = self.sync()
        OrderSemiFinishedRequirement.objects.filter(pk=requirement.pk).update(internal_issued_quantity=5)
        self.bom_line.raw_values["tube_coating_color"] = "白色"
        self.bom_line.save(update_fields=["raw_values"])
        with self.assertRaises(InventoryStockValidationError) as raised:
            sync_public_semi_requirements(self.header(), {requirement.pk})
        self.assertEqual(raised.exception.api_error_code, "SOURCE_CHANGED")
        self.assertEqual(OrderSemiFinishedRequirement.objects.count(), 1)
        requirement.refresh_from_db()
        self.assertEqual(requirement.identity_key, self.semi_identity["identity_key"])

    def test_requirement_reduction_below_issued_is_blocked(self):
        requirement = self.sync()
        OrderSemiFinishedRequirement.objects.filter(pk=requirement.pk).update(internal_issued_quantity=900)
        # 保留已有 500 件排产；改单耗使半成品净需求由 1000 支降至 500 支。
        # 同步重算原料备料字段，避免用无效 BOM 或绕过排产保护来制造测试条件。
        plan = pipe_plan(cutting_length_mm=self.bom_line.cutting_length_mm, pieces_per_product=1,
                         pieces_per_bar=self.bom_line.pieces_per_bar, order_quantity=self.bom.order_quantity)
        for field in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m",
                      "suggested_bar_count", "suggested_purchase_meters"):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.save()
        with self.assertRaises(InventoryStockValidationError) as raised:
            sync_public_semi_requirements(self.header(), {requirement.pk})
        self.assertEqual(raised.exception.api_error_code, "REQUIREMENT_BELOW_ISSUED")

    def test_missing_bom_field_is_a_specific_blocker_not_matching_blank_inventory(self):
        self.bom_line.raw_values["tube_coating_color"] = "/"
        self.bom_line.save(update_fields=["raw_values"])
        rows, blockers = self.rows()
        self.assertEqual(rows, [])
        self.assertIn("PUBLIC_STOCK_IDENTITY_INCOMPLETE", {row["code"] for row in blockers})
        self.assertEqual(blockers[0]["bom_line_id"], str(self.bom_line.pk))

    def test_latest_unconfirmed_bom_is_not_replaced_with_older_verified_version(self):
        new = Bom.objects.get(pk=self.bom.pk)
        new.pk, new.bom_number, new.version_number, new.status = uuid.uuid4(), "PSREQ-BOM-NEW", 2, "PENDING_CONFIRMATION"
        new.save(force_insert=True)
        rows, blockers = self.rows()
        self.assertEqual(rows, [])
        self.assertEqual(blockers[0]["code"], "BOM_NOT_VERIFIED")

    def test_stock_across_zones_is_one_candidate_without_duplicate_quota(self):
        zone = WarehouseZone.objects.create(warehouse=self.semi_warehouse, zone_name="二楼")
        self.credit(25, identity=self.semi_identity, zone=zone)
        rows, blockers = self.rows()
        self.assertFalse(blockers)
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(rows[0]["available_stock"]), 5025)
        self.assertEqual(len(rows[0]["warehouse_zones"]), 2)

    def test_same_pipe_component_keeps_both_uncoated_and_coated_public_candidates(self):
        # 厂内金工半成品颜色来自原材料档案，测试夹具补齐实物属性。
        self.raw_material.color_snapshot = "黑色"
        self.raw_material.save(update_fields=["color_snapshot"])
        self.bom_line.raw_values["source_inventory_material_id"] = str(self.raw_material.pk)
        self.bom_line.save(update_fields=["raw_values"])
        metal, _ = Craft.objects.get_or_create(
            plan_category="METAL",
            defaults={"name": "公共半成品金工", "craft_type": "INTERNAL", "workshop": self.workshop},
        )
        identity = build_semi_finished_identity(
            bom_line=self.bom_line, completed_craft=metal, unit=self.piece_unit,
        )
        self.credit(1000, identity=identity, zone=self.semi_zone)
        rows, blockers = self.rows()
        self.assertFalse(blockers, blockers)
        self.assertEqual({row["processing_status"] for row in rows}, {"未喷塑", "已喷塑"})
        self.assertEqual(len(rows), 2)

    def test_rows_have_bounded_queries_as_component_count_grows(self):
        with CaptureQueriesContext(connection) as first:
            self.rows()
        for index in range(2, 12):
            line = BomLine.objects.get(pk=self.bom_line.pk)
            line.pk, line.line_number, line.component_identity = uuid.uuid4(), index, uuid.uuid4()
            line.save(force_insert=True)
        with CaptureQueriesContext(connection) as many:
            rows, blockers = self.rows()
        self.assertFalse(blockers)
        self.assertEqual(len(rows), 11)
        self.assertEqual(len(first), len(many))

    def test_sync_ignores_raw_ids_and_does_not_write_raw_requirement(self):
        before = list(OrderMaterialRequirement.objects.values())
        self.assertEqual(sync_public_semi_requirements(self.header(), {uuid.uuid4()}), {})
        self.assertFalse(OrderSemiFinishedRequirement.objects.exists())
        self.assertEqual(before, list(OrderMaterialRequirement.objects.values()))

    def test_cutting_uses_sets_per_product_and_does_not_treat_meter_usage_as_sets(self):
        fabric_section = BomSection.objects.create(bom=self.bom, line_number=2, section_type="FABRIC", title="面料类")
        cutting_section = BomSection.objects.create(bom=self.bom, line_number=3, section_type="FABRIC", title="裁剪明细")
        fabric = BomLine.objects.create(section=fabric_section, line_number=1, category="面料", part_name="面料",
            material="PE", specification="600D", unit="米", raw_values={"fabric_color_name": "绿色", "fabric_color_code": "5865C"})
        line = BomLine.objects.create(section=cutting_section, line_number=1, category="布面", part_name="椅面",
            material="PE", specification="450*500", unit="套", fabric_source_line=fabric,
            cutting_pieces_per_set=2, cutting_sets_per_product=3, fabric_meters_per_piece=Decimal("0.5"),
            raw_values={"cutting_category": "布面", "cutting_color": "绿色"})
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", defaults={"unit_code": "PSREQSET"})
        craft, _ = Craft.objects.get_or_create(outsourcing_code="SEWING", defaults={"name": "半成品额度车缝", "craft_type": "EXTERNAL"})
        identity = build_semi_finished_identity(bom_line=line, completed_craft=craft, unit=unit)
        self.credit(2000, identity=identity, zone=self.semi_zone)
        rows, blockers = self.rows()
        self.assertFalse(blockers, blockers)
        cutting = next(row for row in rows if row["unit"] == "套")
        self.assertEqual(Decimal(cutting["required_quantity"]), 1500)
        self.assertEqual(Decimal(cutting["max_issue_quantity"]), 1500)
        self.assertTrue(cutting["conversion_snapshot"]["integer_required"])
