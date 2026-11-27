"""总单真实数据库/API回归；只通过任务专用隔离测试库运行。"""
import copy
import uuid

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tube_processing_services import _usage, assert_tube_reports_cover_usage
from apps.inventory.tube_outsourcing_reservations import tube_raw_reserved_quantities
from apps.workshop_reporting.models import WorkReportLine
from ..models import TubeOutsourcingOrder, TubePlanReceipt, TubePlanReceiptLine
from .test_tube_orders_api import BASE, TubeApiFixture


class PlanApiFixture(TubeApiFixture):
    def plan_context(self, source='METAL', *, order=None, client=None):
        query = {'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source}
        query['plan_id' if order else 'is_plan'] = order['id'] if order else 'true'
        if source != 'METAL':
            query['zone_id'] = str((self.raw_zone if source == 'RAW_PIPE' else self.semi_zone).pk)
        response = (client or self.client).get(BASE + 'source-context/', query, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def plan(self, source='METAL', quantity='200'):
        context = self.plan_context(source)
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': source, 'zone_id': context['zone_id'],
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': quantity,
                'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}
        return self.post_order(payload).data['data']

    def dispatch_payload(self, source='METAL', quantity='100'):
        return {'client_request_id': str(uuid.uuid4()), 'source_kind': source,
            'zone_id': str(self.raw_zone.pk) if source == 'RAW_PIPE' else str(self.semi_zone.pk) if source == 'PUBLIC_SEMI' else None,
            'actual_dispatch_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': quantity,
                'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}

    def receipt_payload(self, order, quantity='100'):
        return {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [
                {'order_line_id': order['lines'][0]['id'], 'received_quantity': quantity, 'zone_id': str(self.semi_zone.pk)}]}

    def write_plan(self, order, action, payload, *, expected=200, client=None, etag=None):
        response = (client or self.client).post(BASE + f"{order['id']}/plan-{action}/", payload,
            format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag or order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response.data['data'] if expected == 200 else response


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanOrdersApiTests(PlanApiFixture, APITestCase):
    def test_demand_plan_loads_and_saves_without_selecting_stock_source(self):
        from apps.inventory.models import RecordStatus, WarehouseZone
        WarehouseZone.objects.update(status=RecordStatus.DISABLED)
        WorkReportLine.objects.all().delete()
        response = self.client.get(BASE + 'source-context/', {
            'schedule_product_id': str(self.schedule_product.pk), 'is_plan': 'true', 'category': 'tube'},
            HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        context = response.data['data']
        self.assertTrue(context['ready'], context['blockers'])
        self.assertEqual(context['source_kind'], 'METAL')
        self.assertIsNone(context['zone_id'])
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': context['source_kind'], 'zone_id': None,
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': '8000',
                'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}
        movements = PublicStockMovement.objects.count()
        first = self.post_order(payload).data['data']
        replay = self.client.post(BASE, payload, format='json', HTTP_HOST='localhost')
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(first['id'], replay.data['data']['id'])
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(tube_raw_reserved_quantities([(self.product_line.pk, self.component)]), {})
        self.assertIsNone(TubeOutsourcingOrder.objects.get(pk=first['id']).zone_id)

    def test_actual_source_query_still_requires_source_and_rejects_plan_category(self):
        base = {'schedule_product_id': str(self.schedule_product.pk)}
        for extra in ({}, {'category': 'tube'}, {'category': 'tube', 'is_plan': 'true',
                'zone_id': str(self.raw_zone.pk)}):
            with self.subTest(extra=extra):
                response = self.client.get(BASE + 'source-context/', {**base, **extra}, HTTP_HOST='localhost')
                self.assertEqual(response.status_code, 400, response.data)

    def test_plan_quantity_overrides_bom_without_reports_or_stock_reservation(self):
        WorkReportLine.objects.all().delete()
        movements = PublicStockMovement.objects.count()
        order = self.plan('RAW_PIPE', '8000')
        self.assertEqual(order['plan_summary']['bom_quantity'], '200')
        self.assertEqual(order['plan_summary']['planned_quantity'], '8000')
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '0')
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(tube_raw_reserved_quantities([(self.product_line.pk, self.component)]), {})
        self.assertFalse(_usage(self.product_line.pk)[self.component]['reserved'])

    def test_two_dispatches_one_independent_receipt_and_replenishment_beyond_bom(self):
        WorkReportLine.objects.all().delete()
        order = self.plan(quantity='230')
        for _ in range(2):
            order = self.write_plan(order, 'dispatch', self.dispatch_payload())
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '200')
        self.assertEqual(len(order['dispatch_records']), 2)
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '200'))
        self.assertEqual(order['status'], 'COMPLETED')
        self.assertEqual(order['plan_summary']['receipt_progress'], 100)
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='30'))
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '30'))
        self.assertEqual(order['plan_summary']['received_quantity'], '230')
        self.assertEqual(order['plan_summary']['bom_quantity'], '200')
        self.assertEqual(order['plan_summary']['receipt_progress'], 100)
        self.assertEqual(TubePlanReceipt.objects.count(), 2)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN').count(), 2)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
        usage = _usage(self.product_line.pk)[self.component]
        self.assertEqual(usage['dispatched'], 230)
        self.assertEqual(usage['legacy_dispatched'], 230)
        assert_tube_reports_cover_usage(self.product_line.pk)

    def test_dispatch_cumulative_quantity_is_limited_by_entered_plan_quantity(self):
        order = self.plan(quantity='300')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='200'))
        response = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='101'), expected=400)
        self.assertIn('本次最多可发100支', str(response.data))
        self.assertEqual(TubeOutsourcingOrder.objects.filter(plan_id=order['id']).count(), 1)
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='100'))
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '300')

    def test_dispatch_from_workshop_and_two_stock_zones_is_atomic_and_replay_safe(self):
        first_stock = self.receive(45).stock_movement.balance
        second_zone = self.make_zone('SECOND-SEMI', 'SEMI_FINISHED')
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        second_stock = credit_public_stock(identity=identity, zone=second_zone, quantity=25,
            source_type='TEST_TUBE_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        order = self.plan()
        self.assertTrue(order['plan_options']['per_line_sources'])
        payload = self.dispatch_payload(quantity='10')
        first_batch = {key: payload.pop(key) for key in ('source_kind', 'zone_id', 'lines')}
        stock_batch = {**first_batch, 'source_kind': 'PUBLIC_SEMI', 'zone_id': str(self.semi_zone.pk),
            'lines': [{**first_batch['lines'][0], 'quantity': '16'}]}
        payload['batches'] = [first_batch, stock_batch, {**stock_batch, 'zone_id': str(second_zone.pk),
            'lines': [{**stock_batch['lines'][0], 'quantity': '26'}]}]

        self.write_plan(order, 'dispatch', payload, expected=400)
        self.assertFalse(TubeOutsourcingOrder.objects.filter(plan_id=order['id']).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
        first_stock.refresh_from_db()
        second_stock.refresh_from_db()
        self.assertEqual((first_stock.quantity, second_stock.quantity), (45, 25))

        payload['batches'][2]['lines'][0]['quantity'] = '20'
        saved = self.write_plan(order, 'dispatch', payload)
        replay = self.write_plan(order, 'dispatch', payload)
        self.assertEqual(saved['version'], replay['version'])
        self.assertEqual(replay['plan_summary']['dispatched_quantity'], '46')
        self.assertCountEqual(
            TubeOutsourcingOrder.objects.filter(plan_id=order['id']).values_list('source_kind', 'zone_id'),
            [('METAL', None), ('PUBLIC_SEMI', self.semi_zone.pk), ('PUBLIC_SEMI', second_zone.pk)])
        first_stock.refresh_from_db()
        second_stock.refresh_from_db()
        self.assertEqual((first_stock.quantity, second_stock.quantity), (29, 5))
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').count(), 2)

    @override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
    def test_metal_receipt_and_outsourcing_use_processed_stock_in_the_raw_pipe_warehouse(self):
        warehouse = self.raw_zone.warehouse
        warehouse.warehouse_name = '原料管材仓'
        warehouse.save(update_fields=['warehouse_name'])
        self.source.completed_pieces = 0
        self.source.save(update_fields=['completed_pieces'])
        raw_quantity = self.raw_balance.quantity
        receipt_url = '/api/v1/semi-finished-receipts/'
        zone_id = str(self.raw_zone.pk)
        preview = self.client.get(receipt_url + 'preview/', {
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'METAL'}, HTTP_HOST='localhost')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertIn(zone_id, [zone['id'] for zone in preview.data['data']['zones']])
        submitted = self.client.post(receipt_url, {'request_id': str(uuid.uuid4()),
            'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'METAL',
            'receipt_date': str(timezone.localdate()), 'lines': [
                {'bom_line_id': str(self.metal_bom_line.pk), 'quantity': '30'}]},
            format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=preview['ETag'])
        self.assertEqual(submitted.status_code, 201, submitted.data)
        detail_url = receipt_url + submitted.data['data']['receipt_id'] + '/'
        detail = self.client.get(detail_url, HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertIn(zone_id, [zone['id'] for zone in detail.data['data']['zones']])
        confirmed = self.client.post(detail_url + 'confirm/', {'zone_id': zone_id},
            format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=detail.data['data']['etag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        order = self.plan()
        sources = [item['value'] for item in order['plan_options']['source_kinds']]
        self.assertEqual(sources, ['METAL', 'PUBLIC_SEMI'])
        query = {'plan_id': order['id'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'PUBLIC_SEMI', 'zone_id': zone_id}
        preview = self.client.get(BASE + 'source-context/', query, HTTP_HOST='localhost')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['data']['rows'][0]['max_quantity'], '30')
        outside = self.make_zone('OTHER-RAW', 'MATERIAL')
        invalid = self.client.get(BASE + 'source-context/', {**query, 'zone_id': str(outside.pk)}, HTTP_HOST='localhost')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        payload = {**self.dispatch_payload(source='PUBLIC_SEMI', quantity='12'), 'zone_id': zone_id}
        sent = self.write_plan(order, 'dispatch', payload)
        self.assertEqual(sent['plan_summary']['dispatched_quantity'], '12')
        balance = PublicStockBalance.objects.get(zone=self.raw_zone, stock_kind='SEMI',
            identity_snapshot__completed_craft__code='METAL')
        self.assertEqual(balance.quantity, 18)
        self.raw_balance.refresh_from_db()
        self.assertEqual(self.raw_balance.quantity, raw_quantity)

    def test_receipt_above_dispatch_and_target_keeps_actual_stock_and_can_continue(self):
        order = self.plan(quantity='1000')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='1000'))
        payload = self.receipt_payload(order, '10001')
        received = self.write_plan(order, 'receipt', payload)
        replay = self.write_plan(order, 'receipt', payload)
        self.assertEqual(received['version'], replay['version'])
        self.assertEqual(received['plan_summary']['received_quantity'], '10001')
        self.assertEqual(received['status'], 'COMPLETED')
        self.assertEqual(TubePlanReceipt.objects.count(), 1)
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.quantity, 10001)
        self.assertEqual(movement.after_quantity - movement.before_quantity, 10001)
        preview = self.client.get(BASE + received['id'] + '/receipt-preview/', HTTP_HOST='localhost')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data['data']['can_receive'])
        listing = self.client.get('/api/v1/unified-outsourcing-orders/', {'warehouse_stage': 'all'}, HTTP_HOST='localhost')
        self.assertEqual(listing.status_code, 200, listing.data)
        row = next(row for row in listing.data['data'] if row['id'] == order['id'])
        self.assertIn('return', row['warehouse_actions'])
        continued = self.write_plan(received, 'receipt', self.receipt_payload(received, '1'))
        self.assertEqual(continued['plan_summary']['received_quantity'], '10002')
        self.assertEqual(TubePlanReceipt.objects.count(), 2)

    def test_receipt_without_dispatch_has_no_quantity_gate(self):
        order = self.plan()
        listing = self.client.get('/api/v1/unified-outsourcing-orders/', {'warehouse_stage': 'all'}, HTTP_HOST='localhost')
        self.assertEqual(listing.status_code, 200, listing.data)
        row = next(row for row in listing.data['data'] if row['id'] == order['id'])
        self.assertIn('return', row['warehouse_actions'])
        preview = self.client.get(BASE + order['id'] + '/receipt-preview/', HTTP_HOST='localhost')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data['data']['can_receive'])
        received = self.write_plan(order, 'receipt', self.receipt_payload(order, '1'))
        self.assertEqual(received['plan_summary']['dispatched_quantity'], '0')
        self.assertEqual(received['plan_summary']['received_quantity'], '1')

    def test_receipt_and_dispatch_cannot_use_foreign_component(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='100'))
        foreign = self.receipt_payload(order, '10')
        foreign['lines'][0]['order_line_id'] = str(uuid.uuid4())
        self.write_plan(order, 'receipt', foreign, expected=400)
        self.assertFalse(TubePlanReceiptLine.objects.exists())
        payload = self.dispatch_payload()
        payload['lines'][0]['component_identity'] = str(uuid.uuid4())
        self.write_plan(order, 'dispatch', payload, expected=400)

    def test_idempotent_replays_and_stale_new_request(self):
        order = self.plan()
        dispatch = self.dispatch_payload()
        sent = self.write_plan(order, 'dispatch', dispatch)
        replay = self.write_plan(order, 'dispatch', dispatch)
        self.assertEqual(sent['version'], replay['version'])
        self.assertEqual(len(replay['dispatch_records']), 1)
        self.write_plan(order, 'dispatch', self.dispatch_payload(), expected=412)
        changed = copy.deepcopy(dispatch)
        changed['lines'][0]['quantity'] = '90'
        self.write_plan(sent, 'dispatch', changed, expected=409)
        receipt = self.receipt_payload(sent, '80')
        received = self.write_plan(sent, 'receipt', receipt)
        replay = self.write_plan(sent, 'receipt', receipt)
        self.assertEqual(received['version'], replay['version'])
        self.assertEqual(TubePlanReceipt.objects.count(), 1)
        self.assertEqual(TubeOutsourcingOrder.objects.filter(plan_id=order['id']).count(), 1)

    def test_stock_source_debits_real_stock_and_rejects_insufficient_stock(self):
        order = self.plan('RAW_PIPE', '2000')
        self.raw_balance.refresh_from_db()
        before = self.raw_balance.quantity
        order = self.write_plan(order, 'dispatch', self.dispatch_payload('RAW_PIPE', '20'))
        self.raw_balance.refresh_from_db()
        self.assertEqual(self.raw_balance.quantity, before - 2)
        self.write_plan(order, 'dispatch', self.dispatch_payload('RAW_PIPE', '1980'), expected=400)
        self.assertEqual(TubeOutsourcingOrder.objects.filter(plan_id=order['id']).count(), 1)

    def test_raw_replenishment_after_bom_overage_keeps_history_and_stock_debits(self):
        from apps.material_issues.pipe_requirements import sync_pipe_requirement
        from rest_framework.exceptions import ValidationError
        order = self.plan('RAW_PIPE', '250')
        self.raw_balance.refresh_from_db()
        before = self.raw_balance.quantity
        for quantity in ('200', '30', '20'):
            order = self.write_plan(order, 'dispatch', self.dispatch_payload('RAW_PIPE', quantity))
        self.raw_balance.refresh_from_db()
        self.requirement.refresh_from_db()
        self.assertEqual(self.raw_balance.quantity, before - 25)
        self.assertEqual(self.requirement.outsourcing_issued_quantity, 250)
        self.assertEqual(order['plan_summary']['bom_quantity'], '200')
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '250')
        self.assertEqual(len(order['dispatch_records']), 3)
        # 同步不应因合法计划补料阻断其他流程，但旧实际发料仍无剩余额度。
        synced = sync_pipe_requirement(self.metal_bom_line.pk)
        self.assertEqual(synced.outsourcing_issued_quantity, 250)
        self.assertEqual(self.context('RAW_PIPE')['rows'][0]['max_quantity'], '0')
        self.post_order(self.order_payload('RAW_PIPE', '10'), expected=400)
        self.requirement.outsourcing_issued_quantity = 1000
        self.requirement.save(update_fields=['outsourcing_issued_quantity'])
        # 没有计划DISPATCH凭证支持的额外数量仍触发原下限守卫。
        with self.assertRaises(ValidationError):
            sync_pipe_requirement(self.metal_bom_line.pk)

    def test_parent_and_child_cannot_use_legacy_final_receipt(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload())
        for target in [order, {'id': order['dispatch_records'][0]['id'], 'etag': order['etag']}]:
            response = self.client.post(BASE + f"{target['id']}/confirm-receipt/", self.receipt_payload(order),
                format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=target['etag'])
            self.assertEqual(response.status_code, 409, response.data)

    def test_receipt_etag_and_warehouse_validation_preserve_stock(self):
        pending = self.plan()
        order = self.write_plan(pending, 'dispatch', self.dispatch_payload())
        receipt = self.receipt_payload(order)
        response = self.client.post(BASE + f"{order['id']}/plan-receipt/", receipt,
            format='json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 428, response.data)
        self.write_plan(pending, 'receipt', receipt, expected=412)
        wrong = copy.deepcopy(receipt)
        wrong['warehouse_id'] = str(self.raw_zone.warehouse_id)
        self.write_plan(order, 'receipt', wrong, expected=400)
        self.assertFalse(TubePlanReceipt.objects.exists())

    def test_real_session_requires_csrf_for_dispatch_and_receipt(self):
        order = self.plan()
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.user)
        response = session.get('/api/auth/me/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        token = session.cookies['csrftoken'].value
        for action in ('dispatch', 'receipt'):
            payload = self.dispatch_payload() if action == 'dispatch' else self.receipt_payload(order)
            url = BASE + f"{order['id']}/plan-{action}/"
            response = session.post(url, payload, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(response.status_code, 403, response.data)
            response = session.post(url, payload, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=order['etag'], HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 200, response.data)
            order = response.data['data']

    def test_list_hides_children_and_inventory_record_is_readable(self):
        order = self.plan()
        order = self.write_plan(order, 'dispatch', self.dispatch_payload())
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '80'))
        listed = self.client.get('/api/v1/unified-outsourcing-orders/', HTTP_HOST='localhost')
        self.assertEqual(listed.status_code, 200, listed.data)
        entries = [row for row in listed.data['data'] if row['record_type'] == 'TUBE']
        self.assertEqual([row['id'] for row in entries], [order['id']])
        self.assertEqual(entries[0]['plan_summary']['received_quantity'], '80')
        rows = self.client.get('/api/v1/semi-finished-receipts/', {'source': 'EXTERNAL'}, HTTP_HOST='localhost')
        self.assertEqual(rows.status_code, 200, rows.data)
        row = next(row for row in rows.data['data']['items'] if row['receipt_number'] == order['receipt_records'][0]['receipt_number'])
        detail = self.client.get(f"/api/v1/semi-finished-receipts/{row['id']}/", HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertTrue(detail.data['data']['source_detail']['is_plan'])
        self.assertEqual(detail.data['data']['source_detail']['source_number'], order['order_number'])

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
        SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_warehouse_dispatch_permission_does_not_require_create_permission(self):
        order = self.plan()
        ScopedActorMixin.scoped_actor(self)
        self.write_plan(order, 'dispatch', self.dispatch_payload(), expected=403)
        ScopedActorMixin.grant(self, 'outsourcing.confirm_dispatch_outsourcingorder', 'CRAFT', [self.spray])
        self.plan_context(order=order)
        order = self.write_plan(order, 'dispatch', self.dispatch_payload())
        self.write_plan(order, 'receipt', self.receipt_payload(order), expected=403)
        ScopedActorMixin.grant(self, 'outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.spray])
        self.write_plan(order, 'receipt', self.receipt_payload(order))
