"""管材仓库确认只排除本单预占，继续保留其他待入库单及外发占用。"""
from datetime import timedelta
from decimal import Decimal
import threading
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from apps.workshop_reporting.models import WorkReportLine

from ..models import InternalSemiFinishedReceipt, PublicStockMovement
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_services import credit_public_stock
from ..stock_services import InventoryStockValidationError
from ..tube_processing_services import metal_component_limits
from .test_pending_receipt_deletion import DeletePermissionFixture
from .test_tube_d1_receipts import D1Fixture, URL


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubePendingConfirmationTests(D1Fixture, APITestCase):
    def submit_pending(self, quantity):
        etag = self.d1_preview()['etag']
        response = self.d1_post(self.d1_payload(str(quantity)), etag=etag)
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        self.assertEqual(receipt.status, 'PENDING')
        self.assertFalse(receipt.lines.exclude(stock_movement=None).exists())
        return receipt, etag

    def confirm_pending(self, receipt, etag):
        response = self.client.post(URL + f'{receipt.pk}/confirm/', format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_full_allowance_pending_receipt_confirms_once(self):
        receipt, etag = self.submit_pending(100)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '0')

        self.confirm_pending(receipt, etag)
        receipt.refresh_from_db()
        line = receipt.lines.get()
        self.assertEqual(receipt.status, 'CONFIRMED')
        self.assertEqual(line.stock_movement.quantity, 100)
        self.assertEqual(line.stock_movement.balance.quantity, 100)
        self.assertTrue(self.confirm_pending(receipt, etag).data['data']['replayed'])
        self.assertEqual(PublicStockMovement.objects.filter(
            source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk, direction='IN').count(), 1)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '0')

    def test_future_scheme_does_not_count_confirming_receipt_twice(self):
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=['effective_to'])
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, price='3')

        receipt, etag = self.submit_pending(80)
        self.confirm_pending(receipt, etag)
        self.assertEqual(receipt.lines.get().stock_movement.quantity, 80)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '20')

    def test_confirmation_keeps_other_pending_receipts_reserved(self):
        first, first_etag = self.submit_pending(60)
        second, etag = self.submit_pending(20)
        row = metal_component_limits(self.product_line,
            exclude_receipt_id=second.pk)['components'][self.component]
        self.assertEqual(Decimal(row['usage']['received']), 60)
        self.assertEqual(row['allowance']['remaining'], 40)

        self.confirm_pending(second, etag)
        first.refresh_from_db()
        self.assertEqual(first.status, 'PENDING')
        self.assertEqual(second.lines.get().stock_movement.quantity, 20)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '20')
        self.confirm_pending(first, first_etag)
        first.refresh_from_db()
        self.assertEqual(first.status, 'CONFIRMED')
        self.assertEqual(first.lines.get().stock_movement.balance.quantity, 80)

    def test_earlier_pending_receipt_can_confirm_before_later_receipt(self):
        first, first_etag = self.submit_pending(60)
        second, second_etag = self.submit_pending(20)
        self.confirm_pending(first, first_etag)
        self.confirm_pending(second, second_etag)
        self.assertEqual(second.lines.get().stock_movement.balance.quantity, 80)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '20')

    def test_confirmation_rechecks_current_reported_quantity(self):
        receipt, etag = self.submit_pending(80)
        WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=79, amount=158)
        response = self.client.post(URL + f'{receipt.pk}/confirm/', format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 400, response.data)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'PENDING')
        self.assertFalse(receipt.lines.exclude(stock_movement=None).exists())

    def test_confirmation_rejects_changed_bom_physical_attributes(self):
        receipt, etag = self.submit_pending(80)
        self.metal_bom_line.part_name = '变更后的管材部位'
        self.metal_bom_line.save(update_fields=['part_name'])
        response = self.client.post(URL + f'{receipt.pk}/confirm/', format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 412, response.data)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'PENDING')
        self.assertFalse(receipt.lines.exclude(stock_movement=None).exists())

    def test_unmatched_line_cannot_borrow_pending_receipt_exclusion(self):
        receipt, _ = self.submit_pending(100)
        identity = build_semi_finished_identity(
            bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        with self.assertRaises(InventoryStockValidationError), transaction.atomic():
            credit_public_stock(identity=identity, zone=self.semi_zone, quantity=1,
                source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk,
                source_line_id=uuid.uuid4(), actor_employee=self.employee,
                production_task=self.task, product_line=self.product_line, bom_line=self.metal_bom_line)
        self.assertFalse(PublicStockMovement.objects.filter(
            source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk).exists())


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubePendingDeleteConfirmConcurrencyTests(DeletePermissionFixture, D1Fixture, TransactionTestCase):
    def race_delete_confirm(self, first_action):
        from ..tube_processing_services import lock_tube_product_scope
        etag = self.d1_preview()['etag']
        response = self.d1_post(self.d1_payload('80'), etag=etag)
        receipt_id = response.data['data']['receipt_id']
        operator = self.warehouse_with_template()
        acquired, second_attempt, release = threading.Event(), threading.Event(), threading.Event()
        local = threading.local()
        results, failures, backend_pids = {}, {}, {}
        second_action = 'delete' if first_action == 'confirm' else 'confirm'

        def ordered_lock(product_line_id):
            action = threading.current_thread().name
            first_call = not getattr(local, 'entered', False)
            local.entered = True
            if first_call and action == second_action:
                second_attempt.set()
            product = lock_tube_product_scope(product_line_id)
            if first_call and action == first_action:
                acquired.set()
                if not release.wait(timeout=15):
                    raise AssertionError('等待释放产品锁超时。')
            return product

        def run(action):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '15s'")
                    cursor.execute("SET statement_timeout = '20s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pids[action] = cursor.fetchone()[0]
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=operator.pk))
                if action == 'confirm':
                    result = client.post(URL + f'{receipt_id}/confirm/', format='json',
                        HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
                else:
                    result = client.delete(URL + f'{receipt_id}/',
                        HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
                results[action] = result.status_code
            except Exception as error:
                failures[action] = repr(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(action,), name=action)
                   for action in [first_action, second_action]]
        with patch('apps.inventory.tube_processing_services.lock_tube_product_scope', side_effect=ordered_lock):
            try:
                threads[0].start()
                self.assertTrue(acquired.wait(timeout=10), failures)
                threads[1].start()
                self.assertTrue(second_attempt.wait(timeout=10), failures)
                waiting = False
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s',
                                       [backend_pids[second_action]])
                        state = cursor.fetchone()
                    if state and state[0] == 'Lock':
                        waiting = True
                        break
                    time.sleep(0.02)
                self.assertTrue(waiting, '第二连接必须真实等待第一连接持有的数据库锁。')
            finally:
                release.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(timeout=25)
        self.assertFalse(any(thread.is_alive() for thread in threads), failures)
        self.assertEqual(failures, {})
        self.assertEqual(len(set(backend_pids.values())), 2)
        return receipt_id, results

    def test_confirmation_wins_and_concurrent_delete_cannot_remove_stock(self):
        receipt_id, results = self.race_delete_confirm('confirm')
        self.assertEqual(results, {'confirm': 200, 'delete': 409})
        receipt = InternalSemiFinishedReceipt.objects.get(pk=receipt_id)
        self.assertEqual(receipt.status, 'CONFIRMED')
        self.assertEqual(receipt.lines.get().stock_movement.balance.quantity, 80)

    def test_deletion_wins_and_concurrent_confirmation_cannot_create_stock(self):
        receipt_id, results = self.race_delete_confirm('delete')
        self.assertEqual(results, {'delete': 204, 'confirm': 404})
        self.assertFalse(InternalSemiFinishedReceipt.objects.filter(pk=receipt_id).exists())
        self.assertFalse(PublicStockMovement.objects.filter(
            source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt_id).exists())
