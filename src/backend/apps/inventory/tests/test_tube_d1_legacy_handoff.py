"""D1真实入库、新待发预留与旧金工直交共用首次产出额度。"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.material_issues.models import MetalProcessingOriginalHandoff
from apps.material_issues.pipe_requirements import sync_pipe_requirement
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.outsourcing.models import (
    OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingOrderProduct,
    OutsourcingProcessingItem,
)
from apps.outsourcing.tests.test_tube_orders_api import TubeApiFixture
from apps.workshop_reporting.models import WorkReportLine

from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockMovement
from ..public_bom_snapshot import freeze_bom_line
from ..tube_processing_services import metal_component_limits


class TubeD1LegacyHandoffFixture(TubeApiFixture):
    receipt_url = '/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        self.task.status = 'IN_PRODUCTION'
        self.task.save(update_fields=['status'])
        self.requirement = sync_pipe_requirement(self.metal_bom_line.pk)
        self.issue_line.refresh_from_db()
        # 补齐S2夹具未使用的旧直交冻结属性，实际领料流水保留同一份冻结凭证。
        self.issue_line.conversion_snapshot = {
            **self.issue_line.conversion_snapshot,
            'public_bom_snapshot': freeze_bom_line(self.metal_bom_line),
        }
        self.issue_line.color_snapshot = '本色'
        self.issue_line.save(update_fields=['conversion_snapshot', 'color_snapshot'])
        allocation = self.issue_line.public_stock_allocations.get()
        allocation.movement.snapshot = {
            **allocation.movement.snapshot, 'conversion': self.issue_line.conversion_snapshot,
        }
        allocation.movement.save(update_fields=['snapshot'])
        self.issue_line.refresh_from_db()
        self.source.source_snapshot = frozen_source(self.issue_line)
        self.source.source_hash = digest(self.source.source_snapshot)
        self.source.save(update_fields=['source_snapshot', 'source_hash'])
        self.original_order = OutsourcingOrder.objects.create(
            order_number='D1-LEGACY-HANDOFF', stock_mode='PUBLIC_V2', schedule=self.schedule,
            craft=self.spray, craft_name_snapshot=self.spray.name,
            craft_code_snapshot='POWDER_COATING', delivery_date=self.today,
            source_revision_hash='o' * 64, client_request_id=uuid.uuid4(), request_payload_hash='o' * 64,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        product = OutsourcingOrderProduct.objects.create(
            order=self.original_order, schedule_product=self.schedule_product, bom=self.bom,
            line_number=1, order_quantity_snapshot=100, planned_quantity_snapshot=100,
            bom_number_snapshot=self.bom.bom_number, bom_version_snapshot=self.bom.version_number,
            source_revision_hash='p' * 64,
        )
        item = OutsourcingProcessingItem.objects.create(
            order_product=product, bom_line=self.metal_bom_line, component_key=self.component,
            line_number=1, quantity=100, unit=self.piece_unit, unit_snapshot='支',
            component_snapshot={'part_name': self.metal_bom_line.part_name},
        )
        OutsourcingFactoryAllocation.objects.create(
            processing_item=item, factory=self.factory, allocated_quantity=100,
            input_quantity=100, input_unit_snapshot='支', unit_price=1,
            factory_snapshot={'name': self.factory.name},
        )
        self.handoff_url = f'/api/v1/metal-processing-sources/{self.issue_line.pk}/handoffs/'

    def receipt_preview(self):
        response = self.client.get(self.receipt_url + 'preview/', {
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'METAL',
        }, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def receipt_payload(self, quantity):
        return {
            'request_id': str(uuid.uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'METAL', 'zone_id': str(self.semi_zone.pk),
            'receipt_date': str(timezone.localdate()),
            'lines': [{'bom_line_id': str(self.metal_bom_line.pk), 'quantity': str(quantity)}],
        }

    def receive(self, quantity):
        self.source.refresh_from_db()
        old_quantities = (self.source.completed_pieces, self.source.internal_received_pieces)
        preview = self.receipt_preview()
        response = self.client.post(self.receipt_url, self.receipt_payload(quantity), format='json',
            HTTP_IF_MATCH=preview['etag'], HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 201, response.data)
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        self.assertEqual(receipt.source_snapshot['quantity_basis'], 'WORK_REPORT_MINIMUM')
        self.source.refresh_from_db()
        self.assertEqual((self.source.completed_pieces, self.source.internal_received_pieces), old_quantities)
        return receipt

    def source_etag(self):
        response = self.client.get(f'/api/v1/metal-processing-sources/{self.issue_line.pk}/',
            HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response['ETag']

    def handoff_payload(self, quantity):
        return {
            'request_id': str(uuid.uuid4()), 'original_order_id': str(self.original_order.pk),
            'factory_id': str(self.factory.pk), 'handoff_pieces': quantity,
            'handoff_date': str(timezone.localdate()),
        }

    def handoff(self, quantity, *, expected=200, payload=None, etag=None):
        response = self.client.post(self.handoff_url, payload or self.handoff_payload(quantity),
            format='json', HTTP_IF_MATCH=etag or self.source_etag(), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def metal_allowance(self):
        return metal_component_limits(self.product_line)['components'][self.component]['allowance']


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeD1LegacyHandoffTests(TubeD1LegacyHandoffFixture, APITestCase):
    def test_d1_receipt_does_not_raise_zero_legacy_handmade_completion(self):
        self.source.completed_pieces = 0
        self.source.save(update_fields=['completed_pieces'])
        self.receive(60)
        self.assertEqual((self.source.completed_pieces, self.source.internal_received_pieces), (0, 0))
        self.assertEqual(self.metal_allowance()['remaining'], 40)
        self.handoff(1, expected=409)

    def test_d1_receipt_prevents_old_handoff_reusing_received_output(self):
        self.receive(60)
        movements = PublicStockMovement.objects.count()
        result = self.handoff(41, expected=400)
        self.assertIn('40', str(result.data))
        self.assertFalse(MetalProcessingOriginalHandoff.objects.exists())
        self.source.refresh_from_db()
        self.assertEqual(self.source.dispatched_pieces, 0)
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(self.metal_allowance()['remaining'], 40)

    def test_remaining_output_can_handoff_without_another_stock_debit(self):
        self.receive(60)
        movements = PublicStockMovement.objects.count()
        self.handoff(40)
        self.assertEqual(MetalProcessingOriginalHandoff.objects.get().handoff_pieces, 40)
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.get().quantity, 60)
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(self.metal_allowance()['remaining'], 0)
        self.source.refresh_from_db()
        self.assertEqual((self.source.completed_pieces, self.source.internal_received_pieces), (100, 0))

    def test_d1_receipt_and_d2_pending_share_old_handoff_limit(self):
        self.receive(30)
        self.post_order(self.order_payload('METAL', '40'))
        self.handoff(31, expected=400)
        self.handoff(30)
        allowance = self.metal_allowance()
        self.assertEqual((allowance['received'], allowance['reserved'], allowance['dispatched']), (30, 40, 30))
        self.assertEqual(allowance['remaining'], 0)

    def test_saved_d1_receipt_remains_protected_when_new_entry_flag_is_off(self):
        self.receive(60)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.handoff(41, expected=400)
            self.handoff(40)
        self.assertEqual(self.metal_allowance()['used'], 100)

    def test_saved_d2_pending_remains_protected_when_new_entry_flag_is_off(self):
        self.post_order(self.order_payload('METAL', '60'))
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.handoff(41, expected=400)
            self.handoff(40)
        self.assertEqual(self.metal_allowance()['used'], 100)

    def test_without_new_records_and_with_flag_off_legacy_cap_is_unchanged(self):
        WorkReportLine.objects.all().delete()
        before = (self.source.source_snapshot, self.source.source_hash, self.source.completed_pieces)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.handoff(100)
        self.source.refresh_from_db()
        self.assertEqual((self.source.source_snapshot, self.source.source_hash, self.source.completed_pieces), before)
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertEqual(self.source.dispatched_pieces, 100)

    def test_flag_on_checks_report_basis_before_any_new_receipt_or_reservation(self):
        WorkReportLine.objects.all().update(quantity=50)
        self.handoff(51, expected=400)
        self.handoff(50)
        self.assertEqual(self.metal_allowance()['remaining'], 0)

    def test_original_request_replay_succeeds_after_shared_limit_is_exhausted(self):
        self.receive(60)
        payload, etag = self.handoff_payload(40), self.source_etag()
        self.handoff(40, payload=payload, etag=etag)
        movements = PublicStockMovement.objects.count()
        self.handoff(40, payload=payload, etag=etag)
        self.handoff(39, payload={**payload, 'handoff_pieces': 39}, etag=etag, expected=409)
        self.assertEqual(MetalProcessingOriginalHandoff.objects.count(), 1)
        self.source.refresh_from_db()
        self.assertEqual(self.source.dispatched_pieces, 40)
        self.assertEqual(PublicStockMovement.objects.count(), movements)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeD1LegacyHandoffConcurrencyTests(TubeD1LegacyHandoffFixture, APITransactionTestCase):
    serialized_rollback = True

    def test_first_d1_receipt_racing_old_handoff_cannot_spend_same_output(self):
        receipt_payload, receipt_etag = self.receipt_payload(60), self.receipt_preview()['etag']
        handoff_payload, handoff_etag = self.handoff_payload(60), self.source_etag()
        barrier = Barrier(2)

        def submit(url, payload, etag):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait(timeout=8)
                response = client.post(url, payload, format='json', HTTP_IF_MATCH=etag, HTTP_HOST='localhost')
                return response.status_code, response.data
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit, self.receipt_url, receipt_payload, receipt_etag)
            second = pool.submit(submit, self.handoff_url, handoff_payload, handoff_etag)
            responses = [first.result(timeout=15), second.result(timeout=15)]
        statuses = [status for status, _ in responses]
        self.assertEqual(sum(status in {200, 201} for status in statuses), 1, responses)
        self.assertEqual(sum(status in {400, 412} for status in statuses), 1, responses)
        receipt_total = sum(InternalSemiFinishedReceiptLine.objects.values_list('quantity', flat=True), Decimal(0))
        handed_total = sum(MetalProcessingOriginalHandoff.objects.values_list('handoff_pieces', flat=True))
        self.assertEqual(receipt_total + handed_total, 60)
        self.assertEqual(self.metal_allowance()['remaining'], 40)
