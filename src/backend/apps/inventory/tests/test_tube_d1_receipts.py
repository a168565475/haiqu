"""D1真实报工入库、状态解释、幂等与共享额度并发。"""
import copy
from datetime import timedelta
import threading
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework.exceptions import ValidationError

from apps.boms.models import BomLine
from apps.organizations.models import Employee
from apps.outsourcing.tests import test_tube_orders_api as tube_fixture
from apps.workshop_config.models import Operation
from apps.workshop_reporting.models import WorkReportLine
from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockMovement
from ..public_stock_services import debit_public_stock, credit_public_stock
from ..public_stock_identity import build_semi_finished_identity
from ..tube_processing_services import metal_component_limits, lock_tube_product_scope, assert_tube_reports_cover_usage

URL = '/api/v1/semi-finished-receipts/'


class D1Fixture(tube_fixture.TubeApiFixture):
    def setUp(self):
        super().setUp()
        self.source.completed_pieces = 0
        self.source.save(update_fields=['completed_pieces'])

    def d1_preview(self):
        response = self.client.get(URL + 'preview/', {'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'METAL'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response['ETag'], response.data['data']['etag'])
        return response.data['data']

    def d1_payload(self, quantity='7'):
        return {'request_id': str(uuid.uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'METAL', 'zone_id': str(self.semi_zone.pk), 'receipt_date': str(timezone.localdate()),
            'remark': 'D1隔离验收', 'lines': [{'bom_line_id': str(self.metal_bom_line.pk), 'quantity': quantity}]}

    def d1_post(self, payload=None, *, expected=201, etag=None):
        response = self.client.post(URL, payload or self.d1_payload(), format='json', HTTP_HOST='localhost',
            HTTP_IF_MATCH=etag or self.d1_preview()['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeD1ReceiptTests(D1Fixture, APITestCase):
    def test_powder_plan_preview_has_fifteen_columns_and_real_basis(self):
        preview = self.d1_preview()
        row = preview['lines'][0]
        meta = row['metal_processing']
        self.assertEqual(preview['excluded'], [])
        self.assertEqual((preview['order_number'], preview['schedule_number'], preview['product_unit']),
            (self.task.order_number, self.schedule.schedule_number, self.unit.unit_name))
        # 厂内金工半成品尚未喷塑，不使用原料档案颜色作为库存身份。
        self.assertEqual(row['attributes']['color'], '')
        self.assertEqual((row['usage'], row['required'], meta['issued'], meta['reported_minimum'], row['can_receive']),
            ('2', '200', '100', '100', '100'))
        self.assertTrue(meta['basis_ready'])
        self.assertEqual(len(meta['operations']), 2)
        self.assertEqual(meta['schemes'][0]['scheme_number'], self.scheme.scheme_number)
        self.assertIn('warehouse_id', preview['zones'][0])

    def test_partial_receipt_writes_once_without_raw_debit_or_manual_completion(self):
        raw_before = self.raw_balance.quantity
        raw_out_before = PublicStockMovement.objects.filter(direction='OUT').count()
        self.d1_post()
        receipt = InternalSemiFinishedReceipt.objects.get()
        line = InternalSemiFinishedReceiptLine.objects.get()
        self.assertEqual(receipt.source_snapshot['quantity_basis'], 'WORK_REPORT_MINIMUM')
        self.assertEqual((line.quantity, line.input_quantity, line.received_after), (7, 7, 7))
        self.assertEqual(line.stock_movement.balance.quantity, 7)
        self.source.refresh_from_db()
        self.raw_balance.refresh_from_db()
        self.assertEqual((self.source.completed_pieces, self.source.internal_received_pieces), (0, 0))
        self.assertEqual(self.raw_balance.quantity, raw_before)
        self.assertEqual(PublicStockMovement.objects.filter(direction='OUT').count(), raw_out_before)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '93')

    def test_missing_scheme_is_not_valid_zero_report_and_other_part_can_receive(self):
        incomplete = BomLine.objects.get(pk=self.metal_bom_line.pk)
        incomplete.pk, incomplete.component_identity, incomplete.line_number = uuid.uuid4(), uuid.uuid4(), 2
        incomplete.part_name = '尚无工价的后脚管'
        incomplete.save(force_insert=True)
        preview = self.d1_preview()
        bad = next(row for row in preview['lines'] if row['bom_line_id'] == str(incomplete.pk))
        self.assertFalse(bad['metal_processing']['basis_ready'])
        self.assertIsNone(bad['metal_processing']['reported_minimum'])
        self.assertTrue(bad['metal_processing']['blockers'])
        self.assertEqual(preview['metal_processing']['blockers'], [])
        self.d1_post()

    def test_unreported_operation_is_real_zero_and_cannot_receive(self):
        WorkReportLine.objects.filter(work_item=self.items[0]).delete()
        row = self.d1_preview()['lines'][0]
        self.assertTrue(row['metal_processing']['basis_ready'])
        self.assertEqual(row['metal_processing']['reported_minimum'], '0')
        self.assertEqual(row['can_receive'], '0')
        self.d1_post(expected=400)

    def test_missing_raw_color_does_not_block_internal_metal_receipt(self):
        self.raw.color_snapshot = ''
        self.raw.save(update_fields=['color_snapshot'])
        row = self.d1_preview()['lines'][0]
        self.assertTrue(row['metal_processing']['basis_ready'])
        self.assertEqual(row['attributes']['color'], '')
        self.d1_post(expected=201)

    def test_zero_blank_and_null_rows_skip_but_all_empty_and_invalid_values_reject(self):
        for value in ['', '0', None, '-1', '1.5', True, 'x', '9' * 5000]:
            self.d1_post(self.d1_payload(value), expected=400)
        payload = self.d1_payload()
        payload['lines'].append({'bom_line_id': str(uuid.uuid4()), 'quantity': ''})
        self.d1_post(payload)
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(), 1)

    def test_duplicate_or_unknown_part_and_over_limit_reject(self):
        payload = self.d1_payload()
        payload['lines'].append(dict(payload['lines'][0]))
        self.d1_post(payload, expected=400)
        payload = self.d1_payload()
        payload['lines'][0]['bom_line_id'] = str(uuid.uuid4())
        self.d1_post(payload, expected=400)
        self.d1_post(self.d1_payload('101'), expected=400)
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())

    def test_idempotent_retry_recovery_and_changed_request(self):
        payload, etag = self.d1_payload(), self.d1_preview()['etag']
        first = self.d1_post(payload, etag=etag)
        self.d1_post(payload, expected=200, etag=etag)
        recovered = self.client.get(URL + f"by-request/{payload['request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(recovered.status_code, 200, recovered.data)
        self.assertEqual(recovered.data['data']['receipt_id'], first.data['data']['receipt_id'])
        payload['lines'][0]['quantity'] = '8'
        self.d1_post(payload, expected=409, etag=etag)
        self.assertEqual(InternalSemiFinishedReceipt.objects.count(), 1)

    def test_report_change_invalidates_preview_and_missing_etag_rejects(self):
        payload, etag = self.d1_payload(), self.d1_preview()['etag']
        WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=80, amount=160)
        self.d1_post(payload, expected=412, etag=etag)
        response = self.client.post(URL, payload, format='json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 428, response.data)

    def test_saved_metal_outsourcing_reservation_reduces_d1_allowance(self):
        self.post_order(self.order_payload('METAL', '40'))
        row = self.d1_preview()['lines'][0]
        self.assertEqual((row['metal_processing']['reserved'], row['can_receive']), ('40', '60'))
        self.d1_post(self.d1_payload('61'), expected=400)
        self.d1_post(self.d1_payload('60'))

    def test_public_semi_outbound_does_not_consume_first_output_twice(self):
        self.d1_post(self.d1_payload('30'))
        self.post_order(self.order_payload('PUBLIC_SEMI', '7'))
        row = self.d1_preview()['lines'][0]
        self.assertEqual((row['received'], row['metal_processing']['reserved'], row['can_receive']), ('30', '0', '70'))

    def test_later_plan_shares_first_receipts_and_valid_historical_reports(self):
        self.d1_post(self.d1_payload('40'))
        self.schedule_product = self.second_plan()
        row = self.d1_preview()['lines'][0]
        self.assertEqual((row['received'], row['metal_processing']['reported_minimum'], row['can_receive']), ('40', '100', '60'))
        self.d1_post(self.d1_payload('60'))
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(), 2)

    def test_old_receipt_ledger_and_source_counter_are_not_counted_twice(self):
        self.receive(40)
        self.source.completed_pieces, self.source.internal_received_pieces = 40, 40
        self.source.save(update_fields=['completed_pieces', 'internal_received_pieces'])
        row = self.d1_preview()['lines'][0]
        self.assertEqual((row['received'], row['can_receive']), ('40', '60'))
        self.d1_post(self.d1_payload('60'))
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '0')
        self.source.refresh_from_db()
        self.assertEqual((self.source.completed_pieces, self.source.internal_received_pieces), (40, 40))

    def test_future_new_operation_blocks_and_price_only_revision_does_not(self):
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=['effective_to'])
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, price='3')
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '100')
        future_scheme = self.scheme.child_schemes.first() if hasattr(self.scheme, 'child_schemes') else None
        if future_scheme is None:
            from apps.workshop_reporting.models import WageScheme
            future_scheme = WageScheme.objects.get(parent_scheme=self.scheme)
        operation = Operation.objects.create(operation_number='D1-FUTURE', product_name='工价测试产品',
            craft=self.craft, name='未来冲孔', reporting_unit=self.piece_unit)
        from apps.workshop_reporting.models import WageSchemeLine
        line = WageSchemeLine.objects.filter(scheme=future_scheme).last()
        line.work_item = self.make_item(operation)
        line.operation_name_snapshot = operation.name
        line.save(update_fields=['work_item', 'operation_name_snapshot'])
        preview = self.d1_preview()
        self.assertEqual(preview['lines'][0]['metal_processing']['reported_minimum'], '100')
        self.assertEqual(preview['lines'][0]['can_receive'], '0')
        self.assertTrue(preview['metal_processing']['future_blockers'])
        self.d1_post(expected=400)

    def test_feature_off_keeps_new_quantity_rules_and_replay_after_plan_void(self):
        WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=50, amount=100)
        payload, etag = self.d1_payload('40'), self.d1_preview()['etag']
        self.d1_post(payload, etag=etag)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '10')
            self.d1_post(self.d1_payload('11'), expected=400)
            self.schedule.record_status, self.schedule.void_reason = 'VOID', '测试改计划'
            self.schedule.voided_at, self.schedule.voided_by_employee = timezone.now(), self.employee
            self.schedule.save(update_fields=['record_status', 'void_reason', 'voided_at', 'voided_by_employee'])
            self.d1_post(payload, expected=200, etag=etag)
            self.assertEqual(self.client.get(URL + f"by-request/{payload['request_id']}/", HTTP_HOST='localhost').status_code, 200)

    def test_stock_out_does_not_restore_first_output_and_report_decrease_is_protected(self):
        self.d1_post(self.d1_payload('80'))
        line = InternalSemiFinishedReceiptLine.objects.get()
        debit_public_stock(balance_id=line.stock_movement.balance_id, quantity=80, source_type='TEST_D1_OUT',
            source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '20')
        with self.assertRaises(ValidationError), transaction.atomic():
            lock_tube_product_scope(self.product_line.pk)
            WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=79, amount=158)
            assert_tube_reports_cover_usage(self.product_line.pk)

    def test_public_credit_guard_checks_new_marker_and_unlinked_in_transaction_movements(self):
        self.d1_post(self.d1_payload('80'))
        receipt = InternalSemiFinishedReceipt.objects.get()
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        def credit(quantity):
            return credit_public_stock(identity=identity, zone=self.semi_zone, quantity=quantity,
                source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk, source_line_id=uuid.uuid4(),
                actor_employee=self.employee, production_task=self.task, product_line=self.product_line,
                bom_line=self.metal_bom_line)
        with self.assertRaises(ValidationError), transaction.atomic():
            credit(21)
        with self.assertRaises(ValidationError), transaction.atomic():
            credit(20)
            credit(1)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').count(), 1)

    def test_failed_stock_credit_rolls_back_and_invalid_zone_cannot_create_header(self):
        payload = self.d1_payload()
        payload['zone_id'] = str(self.raw_zone.pk)
        self.d1_post(payload, expected=404)
        payload = self.d1_payload()
        with patch('apps.inventory.tube_receipt_services.credit_public_stock', side_effect=RuntimeError('模拟记账故障')):
            with self.assertRaises(RuntimeError):
                self.d1_post(payload)
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertFalse(InternalSemiFinishedReceiptLine.objects.exists())

    def test_permission_and_other_operator_recovery_are_rejected(self):
        payload = self.d1_payload()
        self.d1_post(payload)
        outsider = get_user_model().objects.create_user(username='d1-outsider')
        Employee.objects.create(user=outsider, employee_code='D1-OUTSIDER', display_name='其他操作员')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(URL + 'preview/', {'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'METAL'}, HTTP_HOST='localhost').status_code, 403)
        outsider.user_permissions.add(*Permission.objects.filter(content_type__app_label='inventory', codename='view_internalsemifinishedreceipt'))
        self.client.force_authenticate(get_user_model().objects.get(pk=outsider.pk))
        self.assertEqual(self.client.get(URL + f"by-request/{payload['request_id']}/", HTTP_HOST='localhost').status_code, 403)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeD1ConcurrencyTests(D1Fixture, TransactionTestCase):
    def race(self, calls):
        barrier, results = threading.Barrier(len(calls)), []
        def run(call):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                barrier.wait(timeout=10)
                response = call(client)
                results.append(response.status_code)
            except Exception as error:
                results.append(repr(error))
            finally:
                connections.close_all()
        threads = [threading.Thread(target=run, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), results)
        return results

    def test_same_request_concurrent_retry_writes_once(self):
        payload, etag = self.d1_payload('80'), self.d1_preview()['etag']
        call = lambda client: client.post(URL, payload, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
        self.assertCountEqual(self.race([call, call]), [201, 200])
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(), 1)

    def test_receipt_and_metal_outsourcing_cannot_use_same_report_twice(self):
        payload, etag = self.d1_payload('80'), self.d1_preview()['etag']
        order = self.order_payload('METAL', '80')
        calls = [lambda client: client.post(URL, payload, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag),
            lambda client: client.post('/api/v1/tube-outsourcing-orders/', order, format='json', HTTP_HOST='localhost')]
        self.assertCountEqual(self.race(calls), [201, 412])
        self.assertEqual(metal_component_limits(self.product_line)['components'][self.component]['allowance']['used'], 80)
