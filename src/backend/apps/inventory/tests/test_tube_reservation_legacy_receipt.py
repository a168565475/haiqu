"""新外发预留与旧厂内入库真实接口的交叉回归。"""
import uuid
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.outsourcing.models import TubeOutsourcingLine
from apps.outsourcing.tests.test_tube_orders_api import TubeApiFixture

from ..models import InternalSemiFinishedReceiptLine, PublicStockMovement
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_services import credit_public_stock
from ..stock_services import InventoryStockValidationError


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeReservationLegacyReceiptTests(TubeApiFixture, APITestCase):
    receipt_url = "/api/v1/semi-finished-receipts/"

    def setUp(self):
        super().setUp()
        # D2夹具已有真实领料扣库凭证；补齐旧入库查询使用的现行BOM贡献和来源冻结哈希。
        self.requirement = sync_pipe_requirement(self.metal_bom_line.pk)
        self.issue_line.refresh_from_db()
        self.source.source_snapshot = frozen_source(self.issue_line)
        self.source.source_hash = digest(self.source.source_snapshot)
        self.source.save(update_fields=["source_snapshot", "source_hash"])

    def receipt_preview(self, plan):
        response = self.client.get(self.receipt_url + "preview/", {
            "schedule_product_id": str(plan.pk), "plan_category": "METAL",
        }, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def receipt_confirm(self, plan, quantity, etag):
        return self.client.post(self.receipt_url, {
            "request_id": str(uuid.uuid4()), "schedule_product_id": str(plan.pk), "plan_category": "METAL",
            "zone_id": str(self.semi_zone.pk), "receipt_date": str(timezone.localdate()),
            "lines": [{"bom_line_id": str(self.metal_bom_line.pk), "quantity": str(quantity)}],
        }, format="json", HTTP_IF_MATCH=etag, HTTP_HOST="localhost")

    def test_without_new_reservation_old_preview_and_confirm_keep_available_input(self):
        plan = self.second_plan()
        preview = self.receipt_preview(plan)
        self.assertEqual(Decimal(preview["lines"][0]["can_receive"]), 100)
        response = self.receipt_confirm(plan, 100, preview["etag"])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.get().quantity, 100)
        self.assertEqual(Decimal(self.receipt_preview(plan)["lines"][0]["can_receive"]), 0)

    def test_saved_metal_reservation_reduces_cross_plan_old_preview_and_blocks_excess(self):
        self.post_order(self.order_payload("METAL", "60"))
        # 原外发计划作废后，新无喷塑计划仍复用同产品投入；已保存预留不能随计划隐藏。
        plan = self.second_plan()
        preview = self.receipt_preview(plan)
        self.assertEqual(Decimal(preview["lines"][0]["can_receive"]), 40)
        movement_count = PublicStockMovement.objects.count()
        rejected = self.receipt_confirm(plan, 41, preview["etag"])
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertFalse(InternalSemiFinishedReceiptLine.objects.exists())
        self.assertEqual(PublicStockMovement.objects.count(), movement_count)
        accepted = self.receipt_confirm(plan, 40, preview["etag"])
        self.assertEqual(accepted.status_code, 201, accepted.data)
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.get().quantity, 40)
        self.assertEqual(TubeOutsourcingLine.objects.get().quantity, 60)
        self.assertEqual(Decimal(self.receipt_preview(plan)["lines"][0]["can_receive"]), 0)

    def test_repeated_direct_credits_cannot_reuse_reported_unreserved_output(self):
        self.post_order(self.order_payload("METAL", "60"))
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line,
            completed_craft=self.craft, unit=self.piece_unit)

        def credit(quantity):
            return credit_public_stock(identity=identity, zone=self.semi_zone, quantity=quantity,
                source_type="INTERNAL_SEMI_RECEIPT", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                actor_employee=self.employee, production_task=self.task,
                product_line=self.product_line, bom_line=self.metal_bom_line)

        first = credit(40)
        with self.assertRaises(InventoryStockValidationError) as caught:
            credit(1)
        self.assertEqual(caught.exception.api_error_code, "TUBE_OUTSOURCING_OUTPUT_RESERVED")
        first.balance.refresh_from_db()
        self.assertEqual(first.balance.quantity, 40)
