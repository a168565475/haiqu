"""总单真实数据库/API回归；只通过任务专用隔离测试库运行。"""
import copy
import uuid

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.models import PublicStockMovement
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

    def test_receipt_cannot_exceed_actual_dispatch_or_use_foreign_component(self):
        order = self.plan()
        self.write_plan(order, 'receipt', self.receipt_payload(order, '1'), expected=400)
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='100'))
        self.write_plan(order, 'receipt', self.receipt_payload(order, '101'), expected=400)
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
