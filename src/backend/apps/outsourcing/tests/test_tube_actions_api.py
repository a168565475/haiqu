"""D4整单事务、真实公共出库、取消释放及原请求恢复。"""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomLine, BomSection
from apps.inventory.models import InternalSemiFinishedReceipt, PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_services import debit_public_stock
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.inventory.tube_processing_services import assert_tube_reports_cover_usage, metal_component_limits
from apps.inventory.tube_receipt_services import uses_tube_receipt
from apps.material_issues.models import OrderMaterialRequirement
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Craft, Operation
from apps.workshop_reporting.models import WorkReportLine
from ..models import TubeOutsourcingAction, TubeOutsourcingOrder
from .test_tube_orders_api import BASE, TubeApiFixture


class TubeActionFixture(TubeApiFixture):
    def saved_order(self, source='RAW_PIPE', quantity='20'):
        return self.post_order(self.order_payload(source, quantity)).data['data']

    def action_payload(self, kind='dispatch'):
        data = {'client_request_id': str(uuid.uuid4())}
        data['actual_dispatch_date' if kind == 'dispatch' else 'remark'] = (
            str(timezone.localdate()) if kind == 'dispatch' else '待发调整后重新创建')
        return data

    def act(self, order, kind='dispatch', payload=None, *, expected=200, client=None, etag=None):
        response = (client or self.client).post(BASE + f"{order['id']}/{kind}/",
            payload or self.action_payload(kind), format='json', HTTP_HOST='localhost',
            HTTP_IF_MATCH=etag if etag is not None else order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def detail(self, order, *, client=None, expected=200):
        response = (client or self.client).get(BASE + f"{order['id']}/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def snapshot(self):
        return (list(PublicStockBalance.objects.order_by('pk').values('pk', 'quantity', 'meter_quantity')),
            list(OrderMaterialRequirement.objects.order_by('pk').values('pk', 'outsourcing_issued_quantity')),
            PublicStockMovement.objects.count(), TubeOutsourcingAction.objects.count())


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeActionsApiTests(TubeActionFixture, APITestCase):
    def test_raw_whole_saved_quantity_dispatch_debits_roots_meters_and_requirement_once(self):
        order = self.saved_order()
        before = self.raw_balance.quantity, self.raw_balance.meter_quantity
        data = self.act(order).data['data']
        self.raw_balance.refresh_from_db()
        self.requirement.refresh_from_db()
        self.assertEqual((self.raw_balance.quantity, self.raw_balance.meter_quantity),
                         (before[0] - 2, before[1] - Decimal('10.10')))
        self.assertEqual(self.requirement.outsourcing_issued_quantity, 20)
        self.assertEqual((data['status'], data['version'], data['total_quantity'], data['total_meters']),
                         ('PROCESSING', 2, '20', '10.10'))
        self.assertEqual(data['actual_dispatch_date'], str(timezone.localdate()))
        self.assertEqual(data['dispatched_by_name'], self.employee.display_name)
        self.assertFalse(data['permissions']['can_dispatch'])
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_DISPATCH')
        self.assertEqual((movement.quantity, movement.meter_quantity), (2, Decimal('10.10')))
        self.assertEqual(movement.source_id, uuid.UUID(order['id']))
        self.assertTrue(AuditLog.objects.filter(object_id=order['id'], action='DISPATCH_CONFIRMED').exists())

    def test_pending_cancel_preserves_lines_releases_reservations_without_stock_movement(self):
        order = self.saved_order('METAL', '40')
        before = self.snapshot()
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '60')
        result = self.act(order, 'cancel').data['data']
        after = self.snapshot()
        self.assertEqual(before[:3], after[:3])
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '100')
        self.assertEqual((result['status'], result['total_quantity']), ('CANCELLED', '40'))
        self.assertEqual(result['cancel_remark'], '待发调整后重新创建')
        self.assertEqual(result['cancelled_by_name'], self.employee.display_name)
        self.assertTrue(result['lines'])
        self.assertEqual(self.detail(order).data['data']['remark'], '隔离测试')
        self.act(result, expected=409)

    def test_raw_and_public_cancel_release_only_own_stock_reservation(self):
        self.receive(30)
        for source in ['RAW_PIPE', 'PUBLIC_SEMI']:
            order = self.saved_order(source, '20')
            before = self.snapshot()
            free = int(self.context(source)['rows'][0]['max_quantity'])
            self.act(order, 'cancel')
            self.assertEqual(before[:3], self.snapshot()[:3])
            self.assertEqual(int(self.context(source)['rows'][0]['max_quantity']), free + 20)

    def test_public_semi_dispatch_is_pieces_no_second_raw_debit_or_first_output_use(self):
        receipt = self.receive(30)
        balance = receipt.stock_movement.balance
        order = self.saved_order('PUBLIC_SEMI', '7')
        allowance = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        before_raw = self.raw_balance.quantity, self.raw_balance.meter_quantity
        result = self.act(order).data['data']
        balance.refresh_from_db()
        self.raw_balance.refresh_from_db()
        self.assertEqual(balance.quantity, 23)
        self.assertEqual(before_raw, (self.raw_balance.quantity, self.raw_balance.meter_quantity))
        self.assertEqual(allowance, metal_component_limits(self.product_line)['components'][self.component]['allowance'])
        self.assertEqual(result['total_stock_quantity'], '7')
        self.assertIsNone(result['total_meters'])
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '70')

    def test_metal_dispatch_converts_reservation_to_actual_keeps_shared_cap_and_old_counters(self):
        order = self.saved_order('METAL', '80')
        before = self.snapshot()
        old = self.source.completed_pieces, self.source.reserved_pieces, self.source.dispatched_pieces
        result = self.act(order).data['data']
        self.assertEqual(before[:3], self.snapshot()[:3])
        allowance = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        self.assertEqual((allowance['reserved'], allowance['dispatched'], allowance['remaining']), (0, 80, 20))
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '20')
        self.source.refresh_from_db()
        self.assertEqual(old, (self.source.completed_pieces, self.source.reserved_pieces, self.source.dispatched_pieces))
        self.assertIsNone(result['total_stock_quantity'])
        self.assertEqual(result['lines'][0]['current_reported_minimum'], '100')

    def test_three_sources_actual_dispatch_continue_sharing_external_cap(self):
        self.receive(30)
        for source, quantity in [('RAW_PIPE', '110'), ('PUBLIC_SEMI', '30'), ('METAL', '60')]:
            self.act(self.saved_order(source, quantity))
        self.assertEqual(self.context('RAW_PIPE')['rows'][0]['max_quantity'], '0')
        self.assertEqual(self.context('PUBLIC_SEMI')['rows'][0]['max_quantity'], '0')
        self.assertEqual(self.context('METAL')['rows'][0]['max_quantity'], '0')

    def test_idempotent_original_request_replay_and_read_recovery_have_no_second_debit(self):
        order = self.saved_order()
        payload = self.action_payload()
        first = self.act(order, payload=payload).data['data']
        before = self.snapshot()
        retry = self.act(order, payload=payload).data['data']
        self.assertEqual(first['action']['id'], retry['action']['id'])
        recovered = self.client.get(BASE + f"{order['id']}/action-by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(recovered.status_code, 200, recovered.data)
        self.assertEqual(recovered.data['data']['action']['id'], first['action']['id'])
        self.assertEqual(before, self.snapshot())
        payload['actual_dispatch_date'] = str(timezone.localdate() + timedelta(days=1))
        self.act(order, payload=payload, expected=409)
        self.assertEqual(before, self.snapshot())

    def test_same_request_cannot_switch_action_or_order(self):
        first, second = self.saved_order(), self.saved_order()
        payload = self.action_payload('cancel')
        self.act(first, 'cancel', payload)
        self.act(second, 'cancel', payload, expected=409)
        payload = {'client_request_id': payload['client_request_id'], 'actual_dispatch_date': str(timezone.localdate())}
        self.act(first, 'dispatch', payload, expected=409)

    def test_missing_or_stale_etag_and_new_second_action_are_rejected(self):
        order = self.saved_order()
        for etag, status in [('', 428), ('"stale"', 412)]:
            self.act(order, etag=etag, expected=status)
        result = self.act(order).data['data']
        before = self.snapshot()
        self.act(result, 'cancel', expected=409)
        self.act(result, expected=409)
        self.assertEqual(before, self.snapshot())

    def test_quantity_factory_source_zone_injection_is_not_ignored(self):
        order = self.saved_order()
        before = self.snapshot()
        for key, value in [('lines', [{'quantity': 1}]), ('quantity', -1), ('quantity', '1.5'),
                           ('factory_id', str(uuid.uuid4())), ('zone_id', str(uuid.uuid4())), ('source_kind', 'METAL')]:
            payload = self.action_payload()
            payload[key] = value
            self.act(order, payload=payload, expected=400)
        self.assertEqual(before, self.snapshot())

    def test_invalid_dates_request_ids_and_cancel_note_over_limit_rejected(self):
        order = self.saved_order()
        for value in ['', 'bad-date', None]:
            payload = self.action_payload()
            payload['actual_dispatch_date'] = value
            self.act(order, payload=payload, expected=400)
        self.act(order, payload={'client_request_id': 'not-a-uuid', 'actual_dispatch_date': '2026-09-30'}, expected=400)
        self.act(order, 'cancel', {'client_request_id': str(uuid.uuid4()), 'remark': '字' * 2001}, expected=400)
        self.act(order, 'cancel', {'client_request_id': str(uuid.uuid4()), 'remark': ''})

    def test_actual_date_does_not_overwrite_saved_dates_or_add_extra_date_restriction(self):
        order = self.saved_order()
        payload = self.action_payload()
        payload['actual_dispatch_date'] = str(timezone.localdate() + timedelta(days=3))
        data = self.act(order, payload=payload).data['data']
        self.assertEqual(data['planned_dispatch_date'], order['planned_dispatch_date'])
        self.assertEqual(data['expected_return_date'], order['expected_return_date'])
        self.assertEqual(data['actual_dispatch_date'], payload['actual_dispatch_date'])

    def test_insufficient_stock_rolls_back_state_all_lines_and_action(self):
        second = BomLine.objects.get(pk=self.metal_bom_line.pk)
        second.pk, second.component_identity, second.line_number = uuid.uuid4(), uuid.uuid4(), 2
        second.part_name = '后脚管'
        second.save(force_insert=True)
        payload = self.order_payload()
        payload['lines'].append({'component_identity': str(second.component_identity), 'quantity': '20',
                                'factory_id': str(self.factory.pk)})
        order = self.post_order(payload).data['data']
        before = self.snapshot()
        attempts = []
        def debit_then_fail(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 2:
                raise RuntimeError('模拟第二行库存服务故障')
            return debit_public_stock(**kwargs)
        with patch('apps.outsourcing.tube_action_services.debit_public_stock', side_effect=debit_then_fail):
            with self.assertRaises(RuntimeError):
                self.act(order)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.detail(order).data['data']['status'], 'PENDING_DISPATCH')
        self.act(order)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').count(), 2)

    def test_audit_failure_after_debit_rolls_back_everything_and_same_request_can_retry(self):
        order = self.saved_order()
        payload, before = self.action_payload(), self.snapshot()
        with patch('apps.outsourcing.tube_action_services.write_audit_log', side_effect=RuntimeError('模拟审计故障')):
            with self.assertRaises(RuntimeError):
                self.act(order, payload=payload)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.detail(order).data['data']['version'], 1)
        self.act(order, payload=payload)

    def test_saved_revision_does_not_reject_own_reservation_or_other_source_quantity_change(self):
        first, second = self.saved_order(), self.saved_order('METAL', '20')
        self.act(second, 'cancel')
        self.act(first)

    def test_changed_raw_conversion_or_output_identity_requires_cancel_and_recreate(self):
        order = self.saved_order()
        values = dict(self.metal_bom_line.raw_values)
        values['tube_coating_color'] = '白色'
        self.metal_bom_line.raw_values = values
        self.metal_bom_line.save(update_fields=['raw_values'])
        before = self.snapshot()
        self.act(order, expected=409)
        self.assertEqual(before, self.snapshot())
        self.act(order, 'cancel')

    def test_public_processed_stock_does_not_require_unchanged_raw_bar_cutting_parameters(self):
        self.receive(30)
        order = self.saved_order('PUBLIC_SEMI', '7')
        self.metal_bom_line.pieces_per_bar = 5
        self.metal_bom_line.raw_bar_length_m = Decimal('2.55')
        self.metal_bom_line.suggested_bar_count = 41
        self.metal_bom_line.suggested_purchase_meters = Decimal('104.55')
        self.metal_bom_line.save(update_fields=['pieces_per_bar', 'raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters'])
        self.act(order)

    def test_inactive_factory_or_location_blocks_dispatch_but_allows_pending_cancel(self):
        order = self.saved_order()
        self.factory.status = 'DISABLED'
        self.factory.save(update_fields=['status'])
        self.act(order, expected=400)
        self.raw_zone.status = 'DISABLED'
        self.raw_zone.save(update_fields=['status'])
        self.act(order, expected=400)
        self.act(order, 'cancel')

    def test_current_report_and_future_approved_operations_are_rechecked_at_dispatch(self):
        order = self.saved_order('METAL', '80')
        WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=70)
        self.act(order, expected=400)
        WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=100)
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=['effective_to'])
        op = Operation.objects.create(operation_number='D4-FUTURE', product_name='工价测试产品',
            craft=self.craft, name='未来冲孔', reporting_unit=self.piece_unit)
        item = self.make_item(op)
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, items=[item])
        self.act(order, expected=400)
        self.assertEqual(self.detail(order).data['data']['status'], 'PENDING_DISPATCH')

    def test_actual_metal_dispatch_keeps_report_delete_guard_and_feature_off_receipt_guard(self):
        order = self.saved_order('METAL', '80')
        self.act(order)
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=79)
                assert_tube_reports_cover_usage(self.product_line.pk)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertTrue(uses_tube_receipt(schedule_product_id=self.schedule_product.pk))
        self.assertEqual(WorkReportLine.objects.get(work_item=self.items[0]).quantity, 100)

    def test_real_session_requires_csrf_and_outsider_cannot_detail_dispatch_or_cancel(self):
        order = self.saved_order()
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.user)
        response = session.post(BASE + f"{order['id']}/dispatch/", self.action_payload(), format='json',
                                HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 403, response.data)
        outsider = get_user_model().objects.create_user(username='d4-outsider')
        from apps.organizations.models import Employee
        Employee.objects.create(user=outsider, employee_code='D4-OUTSIDER', display_name='无权限')
        client = APIClient()
        client.force_authenticate(outsider)
        self.detail(order, client=client, expected=403)
        self.act(order, client=client, expected=403)
        self.act(order, 'cancel', client=client, expected=403)
        self.assertEqual(TubeOutsourcingAction.objects.count(), 0)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TubeActionsScopedTests(ScopedActorMixin, TubeActionFixture, APITestCase):
    def test_saved_history_craft_scope_survives_removed_current_spray_for_detail_cancel_and_recovery(self):
        order = self.saved_order()
        create_request_id = order['client_request_id']
        ProductionScheduleProductCraft.objects.filter(schedule_product=self.schedule_product, craft=self.spray).update(
            removed_at=timezone.now(), removed_by_employee=self.employee)
        self.scoped_actor()
        for permission in ['outsourcing.view_outsourcingorder', 'outsourcing.cancel_outsourcingorder',
                           'outsourcing.confirm_dispatch_outsourcingorder']:
            self.grant(permission, 'CRAFT', [self.spray])
        self.detail(order)
        recovered = self.client.get(BASE + f'by-request/{create_request_id}/', HTTP_HOST='localhost')
        self.assertEqual(recovered.status_code, 200, recovered.data)
        self.act(order, expected=404)
        payload = self.action_payload('cancel')
        self.act(order, 'cancel', payload)
        recovered = self.client.get(BASE + f"{order['id']}/action-by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(recovered.status_code, 200, recovered.data)
        self.assertEqual(recovered.data['data']['status'], 'CANCELLED')

    def test_craft_scope_with_unrelated_legacy_permission_does_not_expand_other_saved_orders(self):
        order = self.saved_order()
        self.scoped_actor()
        unrelated = Craft.objects.create(name='混合只看车缝', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated])
        from django.contrib.auth.models import Permission
        self.scope_user.user_permissions.add(Permission.objects.get(content_type__app_label='outsourcing',
            codename='view_outsourcingorder'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        self.detail(order, expected=404)

    def test_view_and_dispatch_scope_are_independent_and_not_task_read_permission(self):
        order = self.saved_order()
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        unrelated = Craft.objects.create(name='仅车缝', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.confirm_dispatch_outsourcingorder', 'CRAFT', [unrelated])
        data = self.detail(order).data['data']
        self.assertFalse(data['permissions']['can_dispatch'])
        self.act(order, expected=403)
        self.grant('outsourcing.confirm_dispatch_outsourcingorder', 'CRAFT', [self.spray])
        self.assertTrue(self.detail(order).data['data']['permissions']['can_dispatch'])
        self.assertFalse(self.scope_user.has_perm('production_tasks.view_productiontask'))
        self.act(order)

    def test_cancel_scope_and_history_recovery_still_checked(self):
        order = self.saved_order()
        payload = self.action_payload('cancel')
        self.act(order, 'cancel', payload)
        self.scoped_actor()
        unrelated = Craft.objects.create(name='只看车缝', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated])
        self.grant('outsourcing.cancel_outsourcingorder', 'CRAFT', [unrelated])
        self.detail(order, expected=403)
        response = self.client.get(BASE + f"{order['id']}/action-by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 403, response.data)
        self.act(order, 'cancel', payload, expected=403)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeActionConcurrencyTests(TubeActionFixture, TransactionTestCase):
    def concurrent(self, actions):
        barrier, results = threading.Barrier(len(actions)), []

        def run(order, kind, payload):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                barrier.wait(timeout=10)
                response = client.post(BASE + f"{order['id']}/{kind}/", payload, format='json',
                    HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
                results.append(response.status_code)
            except Exception as error:
                results.append(repr(error))
            finally:
                connections.close_all()
        threads = [threading.Thread(target=run, args=args) for args in actions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), '并发动作等待超过30秒。')
        return sorted(results, key=str)

    def test_dispatch_and_cancel_only_one_can_change_same_order(self):
        order = self.saved_order()
        results = self.concurrent([(order, 'dispatch', self.action_payload()), (order, 'cancel', self.action_payload('cancel'))])
        self.assertEqual(results, [200, 412])
        self.assertEqual(TubeOutsourcingAction.objects.count(), 1)
        count = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').count()
        self.assertEqual(count, 1 if TubeOutsourcingOrder.objects.get().status == 'PROCESSING' else 0)

    def test_same_request_concurrent_retries_debit_once(self):
        order, payload = self.saved_order(), self.action_payload()
        self.assertEqual(self.concurrent([(order, 'dispatch', payload), (order, 'dispatch', payload)]), [200, 200])
        self.assertEqual(TubeOutsourcingAction.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').count(), 1)

    def test_two_reserved_orders_using_same_pool_can_both_dispatch_exact_stock_without_overdraw(self):
        orders = self.saved_order(), self.saved_order()
        PublicStockBalance.objects.filter(pk=self.raw_balance.pk).update(quantity=4, meter_quantity=Decimal('20.20'))
        self.assertEqual(self.concurrent([(order, 'dispatch', self.action_payload()) for order in orders]), [200, 200])
        self.raw_balance.refresh_from_db()
        self.assertEqual((self.raw_balance.quantity, self.raw_balance.meter_quantity), (0, 0))
        self.assertEqual(TubeOutsourcingAction.objects.count(), 2)
        self.assertEqual(self.context()['rows'][0]['max_quantity'], '0')

    @transaction.atomic
    def make_other_plan(self):
        task = ProductionTask.objects.get(pk=self.task.pk)
        task.pk, task.task_number, task.contract_number = uuid.uuid4(), 'D4-SECOND-TASK', 'D4-SECOND-CONTRACT'
        task.status, task.source_request_key = 'READY', None
        task.save(force_insert=True)
        product = ProductionTaskProduct.objects.get(pk=self.product_line.pk)
        product.pk, product.production_task = uuid.uuid4(), task
        product.save(force_insert=True)
        bom = Bom.objects.get(pk=self.bom.pk)
        bom.pk, bom.bom_number, bom.production_task, bom.product_line = uuid.uuid4(), 'D4-SECOND-BOM', task, product
        bom.save(force_insert=True)
        section = BomSection.objects.get(pk=self.metal_bom_line.section_id)
        section.pk, section.bom = uuid.uuid4(), bom
        section.save(force_insert=True)
        line = BomLine.objects.get(pk=self.metal_bom_line.pk)
        line.pk, line.section = uuid.uuid4(), section
        line.save(force_insert=True)
        plan = ProductionSchedule.objects.get(pk=self.schedule.pk)
        plan.pk, plan.schedule_number, plan.production_task = uuid.uuid4(), 'D4-SECOND-SCHEDULE', task
        plan.client_request_id = uuid.uuid4()
        plan.save(force_insert=True)
        planned = ProductionScheduleProduct.objects.get(pk=self.schedule_product.pk)
        planned.pk, planned.schedule, planned.product_line = uuid.uuid4(), plan, product
        planned.save(force_insert=True)
        ProductionScheduleProductCraft.objects.create(schedule_product=planned, craft=self.spray,
            craft_type_snapshot='EXTERNAL', craft_name_snapshot=self.spray.name)
        ProductionTask.objects.filter(pk=task.pk).update(status='IN_PRODUCTION')
        return planned

    def test_different_task_orders_share_pool_and_pending_protection(self):
        first = self.saved_order()
        self.schedule_product = self.make_other_plan()
        second = self.saved_order()
        PublicStockBalance.objects.filter(pk=self.raw_balance.pk).update(quantity=4, meter_quantity=Decimal('20.20'))
        self.assertEqual(self.concurrent([(order, 'dispatch', self.action_payload()) for order in [first, second]]), [200, 200])
        self.raw_balance.refresh_from_db()
        self.assertEqual((self.raw_balance.quantity, self.raw_balance.meter_quantity), (0, 0))
        self.assertEqual(set(TubeOutsourcingAction.objects.values_list('order__product_line_id', flat=True)),
                         {uuid.UUID(first['product_line_id']), uuid.UUID(second['product_line_id'])})


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeDispatchReceiptConcurrencyTests(D1Fixture, TubeActionFixture, TransactionTestCase):
    def test_dispatch_does_not_release_first_output_allowance_to_concurrent_receipt(self):
        order = self.saved_order('METAL', '60')
        payload, etag = self.d1_payload('40'), self.d1_preview()['etag']
        barrier, results = threading.Barrier(2), []
        def run(path, data, tag):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                barrier.wait(timeout=10)
                response = client.post(path, data, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=tag)
                results.append((path, response.status_code))
            except Exception as error:
                results.append((path, repr(error)))
            finally:
                connections.close_all()
        paths = [BASE + f"{order['id']}/dispatch/", '/api/v1/semi-finished-receipts/']
        threads = [threading.Thread(target=run, args=(paths[0], self.action_payload(), order['etag'])),
                   threading.Thread(target=run, args=(paths[1], payload, etag))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        codes = dict(results)
        self.assertEqual(codes[paths[0]], 200, results)
        self.assertIn(codes[paths[1]], [201, 412], results)
        if codes[paths[1]] == 412:
            self.d1_post(payload)
        basis = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        self.assertEqual((basis['received'], basis['dispatched'], basis['reserved'], basis['remaining']), (40, 60, 0, 0))
        self.assertEqual(InternalSemiFinishedReceipt.objects.count(), 1)
        self.d1_post(self.d1_payload('1'), expected=400)
