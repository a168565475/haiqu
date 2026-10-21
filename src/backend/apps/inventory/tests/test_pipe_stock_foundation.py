import threading
import uuid
from decimal import Decimal

from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import pipe_plan
from apps.boms.models import BomLine, BomSection
from apps.material_issues.models import OrderMaterialRequirement
from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.requirements import build_requirement_specs, sync_order_requirements
from apps.material_issues.scopes import filter_blockers_for_scope
from apps.material_issues.tests import test_material_issue_api as issue_test_fixture
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.products.models import RawMaterialInformation
from apps.workshop_config.models import Workshop, WorkshopEmployee
from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialStockBalance, MaterialStockMovement
from apps.inventory.pipe_stock_services import credit_pipe_inbound, issue_pipe_material
from apps.inventory.stock_services import available_stock, debit_material_stock


class PipeFixture:
    def setUp(self):
        issue_test_fixture.MaterialIssueApiTests.setUp(self)
        root_unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "S3ROOT"})
        ProductionUnit.objects.get_or_create(unit_name="支", defaults={"unit_code": "S3PIECE"})
        self.raw_material.unit = root_unit
        self.raw_material.save(update_fields=["unit"])
        self.product_line.quantity = 1000
        self.product_line.save(update_fields=["quantity"])
        self.bom.order_quantity = 1000
        self.bom.save(update_fields=["order_quantity"])
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=1000, calculation_version=2)
        for field in ["cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters"]:
            setattr(self.bom_line, field, plan[field])
        self.bom_line.save()
        self.requirement = sync_pipe_requirement(self.bom_line.pk)
        self.batch = self.make_batch()
        credit_pipe_inbound(inbound_line_id=self.batch.pk, actor_employee=self.employee)

    def make_batch(self, bars=337, length="3.05"):
        inbound = MaterialInbound.objects.create(inbound_number="S3-" + uuid.uuid4().hex.upper(), status="CONFIRMED", received_by_employee=self.employee)
        meters = Decimal(length) * bars
        return MaterialInboundLine.objects.create(inbound=inbound, raw_material_information=self.raw_material, zone=self.zone,
            measurement_kind="PIPE", raw_bar_length_m=length, received_bar_count=bars, accepted_bar_count=bars,
            return_bar_count=0, received_quantity=meters, accepted_quantity=meters, return_quantity=0,
            purchased_quantity_snapshot=meters, source_unit_text_snapshot="米")

    def args(self, pieces=600, kind="MATERIAL_ISSUE", batch=None):
        return {"bom_line_id": self.bom_line.pk, "allocations": [{"inbound_line_id": (batch or self.batch).pk,
                    "source_line_id": uuid.uuid4(), "requested_pieces": pieces}],
                "source_type": kind, "source_id": uuid.uuid4(), "source_revision_hash": self.requirement.source_revision_hash,
                "actor_employee": self.employee}

    def balance(self):
        return MaterialStockBalance.objects.get(measurement_kind="PIPE", inbound_line=self.batch)


class PipeStockFoundationTests(PipeFixture, TestCase):
    def test_inbound_and_retry_have_one_root_meter_entry(self):
        credit_pipe_inbound(inbound_line_id=self.batch.pk, actor_employee=self.employee)
        self.assertEqual((self.balance().quantity, self.balance().meter_quantity), (Decimal(337), Decimal("1027.85")))
        self.assertEqual(MaterialStockMovement.objects.filter(source_line_id=self.batch.pk).count(), 1)

    def test_joint_allowance_and_exact_batch_debits(self):
        issue_pipe_material(**self.args(1200, "OUTSOURCING_DISPATCH"))
        movements = issue_pipe_material(**self.args(600))
        self.requirement.refresh_from_db()
        self.assertEqual((self.requirement.internal_issued_quantity, self.requirement.outsourcing_issued_quantity), (600, 1200))
        self.assertEqual((self.balance().quantity, self.balance().meter_quantity), (37, Decimal("112.85")))
        self.assertEqual(movements[0].snapshot["requested_pieces"], 600)
        with self.assertRaisesMessage(ValidationError, "ORDER_ALLOWANCE_EXCEEDED"):
            issue_pipe_material(**self.args(228))

    def test_retry_does_not_double_deduct_and_changed_payload_conflicts(self):
        args = self.args()
        first = issue_pipe_material(**args)
        self.assertEqual(issue_pipe_material(**args)[0].pk, first[0].pk)
        args["allocations"][0]["requested_pieces"] = 606
        with self.assertRaisesMessage(ValidationError, "IDEMPOTENCY_CONFLICT"):
            issue_pipe_material(**args)
        self.assertEqual(self.balance().quantity, 237)

    def test_whole_bar_length_and_duplicate_selection_guards(self):
        with self.assertRaisesMessage(ValidationError, "PIPE_WHOLE_BAR_REQUIRED"):
            issue_pipe_material(**self.args(2000))
        other = self.make_batch(length="3.06")
        credit_pipe_inbound(inbound_line_id=other.pk, actor_employee=self.employee)
        with self.assertRaisesMessage(ValidationError, "PIPE_LENGTH_MISMATCH"):
            issue_pipe_material(**self.args(batch=other))
        args = self.args()
        args["allocations"].append({**args["allocations"][0], "source_line_id": uuid.uuid4()})
        with self.assertRaisesMessage(ValidationError, "DUPLICATE_ALLOCATION"):
            issue_pipe_material(**args)
        self.assertEqual(self.balance().quantity, 337)

    def test_multi_batch_failure_rolls_back_all_and_quota(self):
        other = self.make_batch(bars=1)
        credit_pipe_inbound(inbound_line_id=other.pk, actor_employee=self.employee)
        args = self.args()
        args["allocations"].append({"inbound_line_id": other.pk, "source_line_id": uuid.uuid4(), "requested_pieces": 12})
        with self.assertRaisesMessage(ValidationError, "STOCK_INSUFFICIENT"):
            issue_pipe_material(**args)
        self.assertEqual(self.balance().quantity, 337)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.internal_issued_quantity, 0)

    def test_same_material_components_keep_separate_allowance(self):
        second = BomLine.objects.get(pk=self.bom_line.pk)
        second.pk = None
        second.line_number = 2
        second.component_identity = uuid.uuid4()
        second.save()
        second_requirement = sync_pipe_requirement(second.pk)
        self.assertNotEqual(second_requirement.pk, self.requirement.pk)
        self.assertEqual(second_requirement.required_quantity, 2022)

    def test_source_change_and_allowance_reduction_are_blocked_after_issue(self):
        issue_pipe_material(**self.args())
        self.bom_line.pieces_per_bar = 3
        self.bom_line.save(update_fields=["pieces_per_bar"])
        with self.assertRaisesMessage(ValidationError, "SOURCE_REVISION_CHANGED"):
            sync_pipe_requirement(self.bom_line.pk)
        self.assertEqual(self.balance().quantity, 237)

    def test_database_rejects_half_root_and_bad_meter_balance(self):
        balance = self.balance()
        for changes in [{"quantity": Decimal("1.5"), "meter_quantity": Decimal("4.575")}, {"meter_quantity": 1}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                MaterialStockBalance.objects.filter(pk=balance.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(internal_issued_quantity=2023)

    def test_old_quantity_service_cannot_consume_new_pipe_balance(self):
        self.assertEqual(available_stock(self.raw_material.pk, self.raw_material.unit_id), 0)
        with self.assertRaises(ValidationError), transaction.atomic():
            debit_material_stock(raw_material=self.raw_material, unit=self.raw_material.unit, quantity=1,
                source_type="MATERIAL_ISSUE", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                actor_employee=self.employee, production_task=self.task)
        self.assertEqual(self.balance().quantity, 337)

    def test_pipe_issue_does_not_block_other_material_sections(self):
        issue_pipe_material(**self.args())
        _, _, blockers, _ = build_requirement_specs(self.task.pk)
        self.assertNotIn("REQUIREMENT_REMOVED_AFTER_ISSUE", [row["code"] for row in blockers])
        self.assertEqual(filter_blockers_for_scope(blockers, product_line_id=self.product_line.pk,
                         section_codes={"PACKAGING", "SEMI"}), [])
        sync_order_requirements(self.task.pk)
        self.assertTrue(self.requirement.contributions.filter(is_current=True).exists())

    def test_pipe_blocker_identifies_only_the_pipe_source_line(self):
        _, _, blockers, _ = build_requirement_specs(self.task.pk)
        pipe_blockers = [row for row in blockers if row["code"] == "PIPE_SERVICE_REQUIRED"]
        self.assertEqual(len(pipe_blockers), 1)
        self.assertEqual(pipe_blockers[0]["bom_line_id"], str(self.bom_line.pk))
        unrelated_material_line_id = str(uuid.uuid4())
        selected_blockers = [row for row in blockers if not row.get("bom_line_id")
                             or row["bom_line_id"] == unrelated_material_line_id]
        self.assertEqual(selected_blockers, [])

    def test_replay_keeps_original_success_after_bom_change(self):
        args = self.args()
        first = issue_pipe_material(**args)[0]
        self.bom.status = "PENDING_CONFIRMATION"
        self.bom.save(update_fields=["status"])
        self.assertEqual(issue_pipe_material(**args)[0].pk, first.pk)
        self.assertEqual(self.balance().quantity, 237)

    def test_independent_batch_stock_does_not_satisfy_short_selected_batch(self):
        other = self.make_batch(bars=1)
        credit_pipe_inbound(inbound_line_id=other.pk, actor_employee=self.employee)
        with self.assertRaisesMessage(ValidationError, "STOCK_INSUFFICIENT"):
            issue_pipe_material(**self.args(12, batch=other))
        self.assertEqual(self.balance().quantity, 337)

    def test_other_material_can_submit_and_confirm_after_pipe_issue(self):
        issue_pipe_material(**self.args())
        meters, _ = ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "S3METER"})
        fabric = RawMaterialInformation.objects.create(material_number="S3FABRIC", item_type="MATERIAL",
            category=ProductCategory.objects.get(category_name="面料", item_type="MATERIAL"),
            material_name="测试面料", specification="测试幅宽", unit=meters,
            warehouse_number=self.warehouse.warehouse_number, warehouse_name=self.warehouse.warehouse_name)
        section = BomSection.objects.create(bom=self.bom, line_number=2, section_type="FABRIC", title="面料类")
        BomLine.objects.create(section=section, line_number=1, part_name="测试面料", unit="米",
            total_purchase_quantity="100", raw_values={"source_raw_material_id": str(fabric.pk)})
        stock = MaterialStockBalance.objects.create(raw_material=fabric, unit=meters, zone=self.zone, quantity=100)
        workshop = Workshop.objects.get(name="车缝车间")
        recipient = WorkshopEmployee.objects.create(workshop=workshop, position="领料员", name="S3车缝领料", status="ACTIVE", is_supervisor=False)
        choices = self.client.get("/api/v1/material-issues/requirements/", {
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(workshop.pk)})
        self.assertEqual(choices.status_code, 200, choices.data)
        self.assertEqual(choices.data["data"]["blockers"], [])
        created = self.client.post("/api/v1/material-issues/", {
            "client_request_id": str(uuid.uuid4()), "schedule_product_id": str(self.schedule_product.pk), "plan_category": "SEWING",
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(workshop.pk),
            "recipient_workshop_employee_id": str(recipient.pk), "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": choices.data["data"]["items"][0]["requirement_id"], "requested_quantity": "5"}]}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        path = f"/api/v1/material-issues/{created.data['data']['id']}/"
        submitted = self.client.post(path + "submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.client.post(path + "confirm-issue/", {"request_id": str(uuid.uuid4())}, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 95)
        self.assertEqual(self.balance().quantity, 237)


class PipeStockConcurrencyTests(PipeFixture, TransactionTestCase):
    serialized_rollback = True

    def test_outsourcing_and_internal_issue_cannot_spend_same_allowance(self):
        barrier = threading.Barrier(2)
        results = []
        args = [self.args(1200, "MATERIAL_ISSUE"), self.args(1200, "OUTSOURCING_DISPATCH")]
        def run(data):
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=5)
                issue_pipe_material(**data)
                results.append("OK")
            except ValidationError as error:
                results.append(str(error.api_error_code))
            except Exception as error:
                results.append(type(error).__name__ + ": " + str(error))
            finally:
                connections.close_all()
        threads = [threading.Thread(target=run, args=(data,)) for data in args]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(results, ["OK", "ORDER_ALLOWANCE_EXCEEDED"])
        self.assertEqual(self.balance().quantity, 137)
