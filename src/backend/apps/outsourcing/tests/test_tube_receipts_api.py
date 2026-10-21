"""D3隔离验证：真实发出凭证、一次结单、公共库存与权限/并发。"""
import copy
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

from apps.audit.models import AuditLog
from apps.boms.models import BomLine
from apps.inventory.models import PublicStockBalance, PublicStockMovement, WarehouseZone
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.inventory.tests.test_tube_d1_legacy_handoff import TubeD1LegacyHandoffFixture
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.tube_processing_services import metal_component_limits, assert_tube_reports_cover_usage
from apps.inventory.tube_receipt_services import uses_tube_receipt
from apps.material_issues.models import OrderMaterialRequirement
from apps.organizations.models import EmployeeRoleAssignment
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Craft, Operation
from apps.workshop_reporting.models import WorkReportLine
from ..models import (OutsourcingFactory, OutsourcingFactoryCraft, TubeOutsourcingAction,
    TubeOutsourcingOrder, TubeOutsourcingReceipt, TubeOutsourcingReceiptLine)
from .test_tube_orders_api import BASE
from .test_tube_actions_api import TubeActionFixture, ScopedActorMixin
from . import test_tube_actions_api as action_fixture


class TubeReceiptFixture(TubeActionFixture):
    def dispatched(self, source='RAW_PIPE', quantity='20'):
        return self.act(self.saved_order(source, quantity)).data['data']

    def receipt_payload(self, order, quantity='18', reason='少回支数，按实收一次结束'):
        return {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id) if quantity not in ('', '0', None) else None,
            'remark': 'D3隔离回货', 'lines': [{'order_line_id': row['id'], 'received_quantity': quantity,
                'shortage_reason': reason, 'zone_id': str(self.semi_zone.pk)} for row in order['lines']]}

    def receive_final(self, order, payload=None, *, expected=201, client=None, etag=None):
        response = (client or self.client).post(BASE + f"{order['id']}/confirm-receipt/",
            payload or self.receipt_payload(order), format='json', HTTP_HOST='localhost',
            HTTP_IF_MATCH=etag if etag is not None else order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def preview(self, order, *, client=None, expected=200):
        response = (client or self.client).get(BASE + f"{order['id']}/receipt-preview/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, expected, response.data)
        return response.data['data'] if expected == 200 else response

    def receipt_snapshot(self):
        return (list(PublicStockBalance.objects.order_by('pk').values('pk', 'quantity', 'meter_quantity')),
            list(OrderMaterialRequirement.objects.order_by('pk').values('pk', 'outsourcing_issued_quantity')),
            PublicStockMovement.objects.count(), TubeOutsourcingReceipt.objects.count(),
            TubeOutsourcingReceiptLine.objects.count(), AuditLog.objects.count())

    def multi_part_order(self):
        second = BomLine.objects.get(pk=self.metal_bom_line.pk)
        second.pk, second.component_identity, second.line_number = uuid.uuid4(), uuid.uuid4(), 2
        second.part_name = '后脚管'
        second.save(force_insert=True)
        factory = OutsourcingFactory.objects.get(pk=self.factory.pk)
        factory.pk, factory.factory_number, factory.name = uuid.uuid4(), 'D3-SECOND-FACTORY', '第二喷塑厂'
        factory.save(force_insert=True)
        OutsourcingFactoryCraft.objects.create(factory=factory, craft=self.spray, craft_name_snapshot=self.spray.name)
        payload = self.order_payload()
        payload['lines'].append({'component_identity': str(second.component_identity), 'quantity': '10',
                                 'factory_id': str(factory.pk)})
        return self.act(self.post_order(payload).data['data']).data['data']


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeReceiptsApiTests(TubeReceiptFixture, APITestCase):
    def test_final_tube_receipt_is_visible_in_semi_receipt_records_with_source_details(self):
        order = self.dispatched('RAW_PIPE', '20')
        response = self.receive_final(order, self.receipt_payload(order, '18', '少回2支，按本单结束'))
        self.assertEqual(response.status_code, 201)
        records = self.client.get('/api/v1/semi-finished-receipts/', HTTP_HOST='localhost')
        self.assertEqual(records.status_code, 200, records.data)
        row = records.data['data']['items'][0]
        receipt = TubeOutsourcingReceipt.objects.get(order_id=order['id'])
        self.assertRegex(receipt.receipt_number, rf'^WFHK{timezone.localdate():%y%m%d}[0-9]{{3,}}$')
        self.assertEqual(row['source_display'], '外发入库')
        self.assertEqual(row['receipt_date'], str(timezone.localdate()))
        detail = self.client.get(f"/api/v1/semi-finished-receipts/{row['id']}/", HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200, detail.data)
        source = detail.data['data']['source_detail']
        self.assertEqual(source['source_type'], 'TUBE_OUTSOURCING_RETURN')
        self.assertEqual(source['source_kind_label'], '原材料')
        self.assertEqual(source['dispatched_quantity'], '20')
        self.assertEqual(source['received_quantity'], '18')
        self.assertEqual(source['shortage_quantity'], '2')
        self.assertEqual(source['shortage_reason'], '少回2支，按本单结束')

    def test_three_sources_merge_same_frozen_sprayed_stock_without_second_raw_debit(self):
        self.receive(30)
        orders = [self.dispatched(source) for source in ['RAW_PIPE', 'PUBLIC_SEMI', 'METAL']]
        before = self.receipt_snapshot()
        self.raw_balance.refresh_from_db()
        raw = self.raw_balance.quantity, self.raw_balance.meter_quantity
        usage = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        outcomes = []
        for order, quantity in zip(orders, ['20', '18', '']):
            outcomes.append(self.receive_final(order, self.receipt_payload(order, quantity)).data['data'])
        incoming = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(incoming.count(), 2)
        self.assertEqual(len(set(incoming.values_list('balance_id', flat=True))), 1)
        self.assertEqual(incoming.first().balance.quantity, 38)
        self.raw_balance.refresh_from_db()
        self.assertEqual(raw, (self.raw_balance.quantity, self.raw_balance.meter_quantity))
        self.assertEqual(before[1], self.receipt_snapshot()[1])
        self.assertEqual(usage, metal_component_limits(self.product_line)['components'][self.component]['allowance'])
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 3)
        self.assertEqual(TubeOutsourcingReceiptLine.objects.count(), 3)
        self.assertEqual(TubeOutsourcingOrder.objects.filter(status='COMPLETED').count(), 3)
        self.assertEqual(outcomes[-1]['warehouse_id'], None)
        self.assertEqual(outcomes[-1]['lines'][0]['stock_movement_id'], None)
        self.assertEqual(outcomes[1]['total_shortage_quantity'], '2')
        self.assertEqual(AuditLog.objects.filter(action='RETURN_COMPLETED').count(), 3)

    def test_all_zero_blank_and_null_finish_without_location_or_stock(self):
        for quantity in ['0', '', None]:
            order = self.dispatched('METAL', '20')
            payload = self.receipt_payload(order, quantity)
            payload.pop('warehouse_id')
            payload['lines'][0].pop('zone_id')
            before = self.receipt_snapshot()
            data = self.receive_final(order, payload).data['data']
            self.assertEqual(before[:3], self.receipt_snapshot()[:3])
            self.assertEqual(data['total_received_quantity'], '0')
            self.assertEqual(data['total_shortage_quantity'], '20')
            self.assertIsNone(data['warehouse_id'])
            self.assertIsNone(data['lines'][0]['zone_id'])
        records = self.client.get('/api/v1/semi-finished-receipts/', HTTP_HOST='localhost')
        self.assertEqual(records.status_code, 200, records.data)
        self.assertEqual(records.data['data']['total'], 0)
        self.assertEqual(metal_component_limits(self.product_line)['components'][self.component]['usage']['dispatched'], '60')

    def test_candidates_search_filter_pagination_and_preview_are_read_only(self):
        pending = self.saved_order()
        cancelled = self.act(self.saved_order(), 'cancel').data['data']
        raw, metal = self.dispatched(), self.dispatched('METAL')
        ended = self.dispatched('METAL')
        self.receive_final(ended, self.receipt_payload(ended, '0'))
        before = self.receipt_snapshot()
        response = self.client.get(BASE + 'receipt-candidates/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row['id'] for row in response.data['data']['items']}, {raw['id'], metal['id']})
        filtered = self.client.get(BASE + 'receipt-candidates/', {'source_kind': 'METAL',
            'search': metal['order_number'], 'page_size': 1}, HTTP_HOST='localhost')
        self.assertEqual(filtered.data['data']['total'], 1)
        self.assertEqual(filtered.data['data']['items'][0]['id'], metal['id'])
        by_factory = self.client.get(BASE + 'receipt-candidates/', {'search': '管材加工厂'}, HTTP_HOST='localhost')
        self.assertEqual(by_factory.data['data']['total'], 2)
        preview = self.preview(raw)
        self.assertTrue(preview['can_receive'])
        self.assertEqual(preview['etag'], raw['etag'])
        self.assertEqual(preview['actor_name'], self.employee.display_name)
        self.assertEqual(preview['today'], str(timezone.localdate()))
        self.assertIn(str(self.semi_zone.pk), [zone['id'] for zone in preview['zones']])
        for order in [pending, cancelled, ended]:
            self.assertFalse(self.preview(order)['can_receive'])
        self.assertIsNotNone(self.preview(ended)['receipt'])
        self.assertEqual(before, self.receipt_snapshot())

    def test_status_without_real_dispatch_action_is_not_eligible(self):
        order = self.saved_order('METAL')
        TubeOutsourcingOrder.objects.filter(pk=order['id']).update(status='PROCESSING')
        latest = self.detail(order).data['data']
        self.assertFalse(self.preview(latest)['can_receive'])
        response = self.client.get(BASE + 'receipt-candidates/', HTTP_HOST='localhost')
        self.assertEqual(response.data['data']['items'], [])
        self.receive_final(latest, expected=400)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 0)

    def test_corrupt_frozen_meter_or_identity_is_blocker_without_server_error(self):
        order = self.dispatched()
        original = TubeOutsourcingOrder.objects.get(pk=order['id']).lines.get()
        for field, value in [('meters', 'bad-meter'), ('public_output_identity', {'invalid': True})]:
            snapshot = copy.deepcopy(original.snapshot)
            snapshot[field] = value
            TubeOutsourcingOrder.objects.get(pk=order['id']).lines.update(snapshot=snapshot)
            self.assertFalse(self.preview(order)['can_receive'])
            self.receive_final(order, expected=400)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 0)

    def test_result_and_preview_contract_serializers_match_real_api_fields(self):
        from ..api.tube_serializers import (TubeReceiptPreviewSerializer, TubeReceiptResultSerializer,
                                            TubeReceiptCandidatesSerializer)
        order = self.dispatched()
        preview = self.preview(order)
        validator = TubeReceiptPreviewSerializer(data=preview)
        self.assertTrue(validator.is_valid(), validator.errors)
        candidates = self.client.get(BASE + 'receipt-candidates/', HTTP_HOST='localhost').data['data']
        validator = TubeReceiptCandidatesSerializer(data=candidates)
        self.assertTrue(validator.is_valid(), validator.errors)
        final = self.receive_final(order).data['data']
        validator = TubeReceiptResultSerializer(data=final)
        self.assertTrue(validator.is_valid(), validator.errors)
        final_fields = set(TubeReceiptResultSerializer().fields)
        self.assertEqual(set(final), final_fields)

    def test_multi_part_multi_factory_once_complete_and_different_zones_same_warehouse(self):
        order = self.multi_part_order()
        zone = WarehouseZone.objects.create(warehouse=self.semi_zone.warehouse, zone_name='第二区')
        payload = self.receipt_payload(order)
        for row, original in zip(payload['lines'], order['lines']):
            row['received_quantity'] = original['quantity']
            row['shortage_reason'] = ''
        payload['lines'][1]['zone_id'] = str(zone.pk)
        result = self.receive_final(order, payload).data['data']
        self.assertEqual(result['total_received_quantity'], '30')
        self.assertEqual(len(result['lines']), 2)
        self.assertEqual({row['factory_name'] for row in result['lines']}, {'管材加工厂', '第二喷塑厂'})
        self.assertEqual({row['zone_id'] for row in result['lines']}, {str(zone.pk), str(self.semi_zone.pk)})
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN').count(), 2)
        self.receive_final(order, self.receipt_payload(order), expected=412)

    def test_mixed_zero_line_is_recorded_with_reason_but_no_zone_or_movement(self):
        order = self.multi_part_order()
        payload = self.receipt_payload(order)
        payload['lines'][0]['received_quantity'] = order['lines'][0]['quantity']
        payload['lines'][1]['received_quantity'] = ''
        result = self.receive_final(order, payload).data['data']
        empty = next(row for row in result['lines'] if row['received_quantity'] == '0')
        self.assertIsNone(empty['zone_id'])
        self.assertIsNone(empty['stock_movement_id'])
        self.assertTrue(empty['shortage_reason'])
        self.assertEqual(len(result['lines']), 2)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN').count(), 1)

    def test_all_original_lines_required_unique_no_foreign_line(self):
        order = self.multi_part_order()
        good = self.receipt_payload(order)
        for replacement in [good['lines'][:1], good['lines'] + [good['lines'][0]],
                            [dict(row, order_line_id=str(uuid.uuid4())) for row in good['lines']]]:
            payload = copy.deepcopy(good)
            payload['lines'] = replacement
            self.receive_final(order, payload, expected=400)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 0)

    def test_negative_fraction_boolean_overlarge_and_overdispatch_rejected(self):
        order = self.dispatched()
        before = self.receipt_snapshot()
        for quantity in ['-1', '1.2', True, '100000000000000', '21']:
            self.receive_final(order, self.receipt_payload(order, quantity), expected=400)
        self.assertEqual(before, self.receipt_snapshot())

    def test_each_shortage_requires_reason_and_full_return_does_not(self):
        order = self.multi_part_order()
        payload = self.receipt_payload(order)
        payload['lines'][0]['received_quantity'] = order['lines'][0]['quantity']
        payload['lines'][1]['received_quantity'] = '0'
        payload['lines'][1]['shortage_reason'] = '  '
        self.receive_final(order, payload, expected=400)
        for row, original in zip(payload['lines'], order['lines']):
            row['received_quantity'], row['shortage_reason'] = original['quantity'], ''
        self.receive_final(order, payload)

    def test_positive_requires_valid_one_warehouse_and_each_zone(self):
        order = self.dispatched()
        original = self.receipt_payload(order)
        other = self.make_zone('D3-OTHER', 'SEMI_FINISHED')
        for field, value in [('warehouse_id', None), ('zone_id', None), ('zone_id', str(other.pk)),
                             ('zone_id', str(self.raw_zone.pk)), ('warehouse_id', str(uuid.uuid4()))]:
            payload = copy.deepcopy(original)
            target = payload if field == 'warehouse_id' else payload['lines'][0]
            target[field] = value
            self.receive_final(order, payload, expected=400)
        WarehouseZone.objects.filter(pk=self.semi_zone.pk).update(status='DISABLED')
        self.receive_final(order, original, expected=400)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 0)

    def test_no_identity_factory_color_quantity_injection(self):
        order = self.dispatched()
        for field in ['quantity', 'source_kind', 'factory_id', 'public_output_identity', 'spray_color']:
            payload = self.receipt_payload(order)
            payload[field] = 'inject'
            self.receive_final(order, payload, expected=400)
            payload = self.receipt_payload(order)
            payload['lines'][0][field] = 'inject'
            self.receive_final(order, payload, expected=400)

    def test_etag_idempotency_read_recovery_and_cross_order_request_conflict(self):
        order = self.dispatched()
        payload = self.receipt_payload(order)
        for tag, status in [('', 428), ('"stale"', 412)]:
            self.receive_final(order, payload, etag=tag, expected=status)
        first = self.receive_final(order, payload).data['data']
        before = self.receipt_snapshot()
        replay = self.receive_final(order, payload, expected=200).data['data']
        self.assertEqual(first['id'], replay['id'])
        self.assertFalse(replay['created'])
        for suffix in ['receipt/', f"receipt-by-request/{payload['client_request_id']}/"]:
            response = self.client.get(BASE + f"{order['id']}/{suffix}", HTTP_HOST='localhost')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['data']['id'], first['id'])
            self.assertEqual(response['ETag'], first['etag'])
        self.receive_final(order, self.receipt_payload(order), expected=412)
        fresh = self.detail(order).data['data']
        self.receive_final(fresh, expected=409)
        changed = copy.deepcopy(payload)
        changed['lines'][0]['shortage_reason'] = '改变原请求'
        self.receive_final(order, changed, expected=409)
        second = self.dispatched()
        before_second = self.receipt_snapshot()
        self.receive_final(second, payload, expected=409)
        self.assertEqual(before_second, self.receipt_snapshot())
        unknown = self.client.get(BASE + f"{order['id']}/receipt-by-request/{uuid.uuid4()}/", HTTP_HOST='localhost')
        self.assertEqual(unknown.status_code, 404)

    def test_second_line_credit_failure_rolls_back_entire_receipt_stock_and_status(self):
        order = self.multi_part_order()
        payload = self.receipt_payload(order)
        for row, original in zip(payload['lines'], order['lines']):
            row['received_quantity'] = original['quantity']
        before = self.receipt_snapshot()
        count = [0]
        def credit(**kwargs):
            count[0] += 1
            if count[0] == 2:
                raise ValidationError('隔离验证第二行失败')
            return credit_public_stock(**kwargs)
        with patch('apps.outsourcing.tube_receipt_services.credit_public_stock', side_effect=credit):
            self.receive_final(order, payload, expected=400)
        self.assertEqual(before, self.receipt_snapshot())
        self.assertEqual(self.detail(order).data['data']['status'], 'PROCESSING')
        self.receive_final(order, payload)

    def test_saved_paint_identity_survives_current_bom_and_factory_changes(self):
        order = self.dispatched('METAL')
        self.metal_bom_line.raw_values['tube_coating_color'] = '红色'
        self.metal_bom_line.cutting_length_mm = 555
        self.metal_bom_line.save(update_fields=['raw_values', 'cutting_length_mm'])
        self.factory.name = '后来修改的厂家名'
        self.factory.save(update_fields=['name'])
        data = self.receive_final(order).data['data']
        self.assertEqual(data['lines'][0]['spray_color'], '黑色')
        self.assertEqual(data['lines'][0]['factory_name'], '管材加工厂')
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.balance.identity_snapshot['color'], '黑色')
        self.assertEqual(movement.balance.identity_snapshot['cutting_length_mm'], 500)

    def test_profile_powder_color_is_frozen_for_external_return(self):
        values = dict(self.metal_bom_line.raw_values or {})
        values['tube_coating_color'] = ''
        values['powder_coating_color'] = '铁-中光'
        self.metal_bom_line.raw_values = values
        self.metal_bom_line.save(update_fields=['raw_values'])

        order = self.dispatched('RAW_PIPE', '20')
        data = self.receive_final(order, self.receipt_payload(order, '18')).data['data']

        self.assertEqual(data['lines'][0]['spray_color'], '铁-中光')
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.balance.identity_snapshot['color'], '铁-中光')

    def test_raw_whole_bar_surplus_can_return_more_than_net_demand_but_not_actual_dispatch(self):
        self.schedule_product = action_fixture.TubeActionConcurrencyTests.make_other_plan(self)
        order = self.dispatched('RAW_PIPE', '210')
        self.assertEqual(order['lines'][0]['order_required'], '200')
        payload = self.receipt_payload(order, '210', '')
        result = self.receive_final(order, payload).data['data']
        self.assertEqual(result['total_received_quantity'], '210')
        self.assertEqual(PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN').quantity, 210)

    def test_metal_completed_zero_keeps_current_future_report_protection_and_flag_off_guard(self):
        order = self.dispatched('METAL', '80')
        self.receive_final(order, self.receipt_payload(order, '0'))
        allowance = metal_component_limits(self.product_line)['components'][self.component]['allowance']
        self.assertEqual((allowance['dispatched'], allowance['remaining']), (80, 20))
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                WorkReportLine.objects.filter(work_item=self.items[0]).update(quantity=79)
                assert_tube_reports_cover_usage(self.product_line.pk)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertTrue(uses_tube_receipt(schedule_product_id=self.schedule_product.pk))
        self.scheme.effective_to = self.today
        self.scheme.save(update_fields=['effective_to'])
        op = Operation.objects.create(operation_number='D3-FUTURE', product_name='工价测试产品', craft=self.craft,
                                      name='未来冲孔', reporting_unit=self.piece_unit)
        item = self.make_item(op)
        self.make_scheme(effective_from=self.today + timedelta(days=1), parent=self.scheme, items=[item])
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                assert_tube_reports_cover_usage(self.product_line.pk)

    def test_all_sources_completed_shortage_do_not_restore_shared_external_allowance(self):
        self.receive(30)
        for source, quantity in [('RAW_PIPE', '110'), ('PUBLIC_SEMI', '30'), ('METAL', '60')]:
            order = self.dispatched(source, quantity)
            self.receive_final(order, self.receipt_payload(order, '0'))
        for source in ['RAW_PIPE', 'PUBLIC_SEMI', 'METAL']:
            self.assertEqual(self.context(source)['rows'][0]['max_quantity'], '0')

    def test_real_session_requires_csrf_on_receipt(self):
        order = self.dispatched()
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.user)
        self.receive_final(order, client=session, expected=403)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 0)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TubeReceiptScopeTests(ScopedActorMixin, TubeReceiptFixture, APITestCase):
    def test_return_craft_scope_does_not_require_task_read_and_survives_removed_plan_craft(self):
        order = self.dispatched()
        ProductionScheduleProductCraft.objects.filter(schedule_product=self.schedule_product, craft=self.spray).update(
            removed_at=timezone.now(), removed_by_employee=self.employee)
        self.scoped_actor()
        self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        self.assertFalse(self.scope_user.has_perm('production_tasks.view_productiontask'))
        self.assertTrue(self.preview(order)['can_receive'])
        candidates = self.client.get(BASE + 'receipt-candidates/', HTTP_HOST='localhost')
        self.assertEqual(candidates.data['data']['total'], 1)
        payload = self.receipt_payload(order)
        first = self.receive_final(order, payload).data['data']
        response = self.client.get(BASE + f"{order['id']}/receipt-by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['id'], first['id'])

    def test_ungranted_craft_and_revoked_return_reject_preview_confirm_and_recovery(self):
        order = self.dispatched()
        self.scoped_actor()
        unrelated = Craft.objects.create(name='D3其它工艺', craft_type='EXTERNAL', outsourcing_code='SEWING')
        grant = self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [unrelated])
        self.preview(order, expected=403)
        self.receive_final(order, expected=403)
        candidates = self.client.get(BASE + 'receipt-candidates/', HTTP_HOST='localhost')
        self.assertEqual(candidates.data['data']['items'], [])
        EmployeeRoleAssignment.objects.filter(role_profile=grant.role).update(effective_to=timezone.now())
        grant = self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        payload = self.receipt_payload(order)
        self.receive_final(order, payload)
        EmployeeRoleAssignment.objects.filter(role_profile=grant.role).update(effective_to=timezone.now())
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        self.receive_final(order, payload, expected=403)
        response = self.client.get(BASE + f"{order['id']}/receipt-by-request/{payload['client_request_id']}/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 403)

    def test_readonly_receipt_view_or_return_scope_independent_union(self):
        order = self.dispatched()
        self.receive_final(order)
        self.scoped_actor()
        unrelated = Craft.objects.create(name='D3只看车缝', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        grant = self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [unrelated])
        response = self.client.get(BASE + f"{order['id']}/receipt/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        preview = self.preview(order)
        self.assertFalse(preview['can_receive'])
        self.assertIsNotNone(preview['receipt'])
        EmployeeRoleAssignment.objects.filter(role_profile=grant.role).update(effective_to=timezone.now())
        self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        response = self.client.get(BASE + f"{order['id']}/receipt/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)

    def test_view_only_can_preview_completed_but_cannot_preview_processing_or_confirm(self):
        processing = self.dispatched()
        completed = self.dispatched()
        self.receive_final(completed)
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        self.preview(processing, expected=403)
        preview = self.preview(completed)
        self.assertFalse(preview['can_receive'])
        self.assertEqual(preview['receipt']['status'], 'COMPLETED')
        self.receive_final(processing, expected=403)

    def test_other_craft_view_does_not_read_completed_receipt_preview(self):
        order = self.dispatched()
        self.receive_final(order)
        self.scoped_actor()
        unrelated = Craft.objects.create(name='D3越范围查看', craft_type='EXTERNAL', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated])
        self.preview(order, expected=403)
        response = self.client.get(BASE + f"{order['id']}/receipt/", HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 403)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeReceiptConcurrencyTests(TubeReceiptFixture, TransactionTestCase):
    def concurrent_receipts(self, inputs):
        barrier, results = threading.Barrier(len(inputs)), []
        def run(order, payload):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                barrier.wait(timeout=10)
                response = client.post(BASE + f"{order['id']}/confirm-receipt/", payload, format='json',
                    HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
                results.append(response.status_code)
            except Exception as error:
                results.append(repr(error))
            finally:
                connections.close_all()
        threads = [threading.Thread(target=run, args=args) for args in inputs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), '整单回货并发等待超过30秒。')
        return sorted(results, key=str)

    def test_same_request_concurrent_creates_one_receipt_one_movement(self):
        order = self.dispatched()
        payload = self.receipt_payload(order)
        self.assertEqual(self.concurrent_receipts([(order, payload), (order, payload)]), [200, 201])
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 1)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN').count(), 1)

    def test_different_requests_same_order_only_one_final_receipt(self):
        order = self.dispatched()
        self.assertEqual(self.concurrent_receipts([(order, self.receipt_payload(order)),
                                                   (order, self.receipt_payload(order))]), [201, 412])
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 1)

    def test_two_different_task_orders_same_output_pool_merge_concurrently(self):
        first = self.dispatched()
        self.schedule_product = action_fixture.TubeActionConcurrencyTests.make_other_plan(self)
        second = self.dispatched()
        self.assertEqual(self.concurrent_receipts([(order, self.receipt_payload(order))
                                                   for order in [first, second]]), [201, 201])
        moves = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(moves.count(), 2)
        self.assertEqual(len(set(moves.values_list('balance_id', flat=True))), 1)
        self.assertEqual(moves.first().balance.quantity, 36)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class TubeFinalReceiptD1Tests(D1Fixture, TubeReceiptFixture, APITestCase):
    def test_completed_metal_shortage_still_leaves_only_unconsumed_first_output_for_d1(self):
        order = self.dispatched('METAL', '80')
        self.receive_final(order, self.receipt_payload(order, '0'))
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '20')
        self.d1_post(self.d1_payload('20'))
        self.d1_post(self.d1_payload('1'), expected=400)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '0')

    def test_completed_metal_guard_also_blocks_direct_legacy_internal_stock_credit(self):
        order = self.dispatched('METAL', '100')
        self.receive_final(order, self.receipt_payload(order, '0'))
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft,
                                                unit=self.piece_unit)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    credit_public_stock(identity=identity, zone=self.semi_zone, quantity=1,
                        source_type='INTERNAL_SEMI_RECEIPT', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                        actor_employee=self.employee, production_task=self.task, product_line=self.product_line,
                        bom_line=self.metal_bom_line)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').count(), 0)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class TubeFinalReceiptLegacyGuardTests(TubeReceiptFixture, TubeD1LegacyHandoffFixture, APITestCase):
    def test_completed_metal_all_zero_keeps_old_handoff_guard_even_when_new_entry_disabled(self):
        order = self.dispatched('METAL', '80')
        self.receive_final(order, self.receipt_payload(order, '0'))
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.handoff(21, expected=400)
            self.handoff(20)
        allowance = self.metal_allowance()
        self.assertEqual((allowance['dispatched'], allowance['remaining']), (100, 0))
