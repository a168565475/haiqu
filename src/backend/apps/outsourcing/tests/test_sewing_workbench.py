from datetime import timedelta
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.outsourcing.models import TubeOutsourcingAction, TubeOutsourcingOrder
from . import test_part_flow_plan_api as plans


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class SewingWorkbenchTests(plans.PartFlowPlanFixture, APITestCase):
    part_context = plans.PartFlowPlanApiTests.part_context
    create_part_plan = plans.PartFlowPlanApiTests.create_part_plan
    dispatch_part = plans.PartFlowPlanApiTests.dispatch_part
    receive_part = plans.PartFlowPlanApiTests.receive_part
    sewing_assignment = plans.PartFlowPlanApiTests.sewing_assignment
    url = '/api/v1/sewing-outsourcing-workbench/'

    def get(self, action='', **params):
        response = self.client.get(self.url + action, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_dispatch_shortage_partial_receipt_and_due_dates_use_parent_order(self):
        order = self.create_part_plan()
        today = timezone.localdate()
        self.assertEqual(self.get()['counts']['today_send'], 1)
        order, _ = self.dispatch_part(order, 20)
        order, _ = self.dispatch_part(order, 1, piece=self.cotton)
        self.receive_part(order, 3)
        for offset, key in ((-1, 'overdue'), (0, 'today'), (3, 'soon'), (4, 'working')):
            TubeOutsourcingOrder.objects.filter(pk=order['id']).update(expected_return_date=today+timedelta(days=offset))
            counts = self.get()['counts']
            self.assertEqual((counts['send'], counts['working'], counts['partial'], counts[key]), (1, 1, 1, 1))
            self.assertEqual(counts['soon'], int(offset == 3))
        row, = self.get('items/', category='working')
        self.assertEqual((row['id'], row['parts'][0]['actual'], row['parts'][0]['unit']), (order['id'], '3', '个'))
        self.assertEqual(row['parts'][0]['remaining'], str(int(order['lines'][0]['bom_quantity'])-3))
        self.assertTrue(any(r['actual'] == '20' and r['remaining'] == '180' and r['unit'] == '片' for r in row['materials']))
        self.assertEqual(self.get('items/', category='upcoming', date=today+timedelta(days=4))[0]['id'], order['id'])
        for period in ('month','quarter','year'):
            activity = self.get('activity/', period=period)
            self.assertEqual((activity['dispatch_orders'], activity['receipt_orders'], activity['receipt_events']), (1,1,1))
            self.assertEqual(activity['quantities'], [{'unit':'个', 'quantity':'3'}])
            self.assertEqual(activity['factories'][0]['order_count'], 1)
        TubeOutsourcingOrder.objects.get(pk=order['id']).plan_receipts.update(voided_at=timezone.now())
        self.assertEqual(self.get('activity/')['receipt_events'], 0)

    def test_partial_receipt_is_due_even_without_a_dispatch_for_that_part(self):
        order = self.create_part_plan()
        self.assertEqual(self.get()['counts']['working'], 0)
        self.receive_part(order, 3)
        TubeOutsourcingOrder.objects.filter(pk=order['id']).update(
            expected_return_date=timezone.localdate() - timedelta(days=1))
        counts = self.get()['counts']
        self.assertEqual((counts['overdue'], counts['send'], counts['partial']), (1, 1, 0))
        row, = self.get('items/', category='overdue')
        part, = row['parts']
        self.assertEqual((part['actual'], part['remaining']), ('3', str(int(order['lines'][0]['bom_quantity']) - 3)))

    def test_internal_assignment_and_invalid_parameters(self):
        self.assertEqual(self.sewing_assignment().status_code, 201)
        self.assertFalse(any(self.get()['counts'].values()))
        self.assertEqual(self.get('items/', category='send'), [])
        for url, params in (('', {'warehouse_stage':'all'}), ('items/', {'category':'other'}),
                            ('items/', {'category':'send','page':0}), ('activity/', {'period':'week'})):
            self.assertEqual(self.client.get(self.url+url, params).status_code, 400)

    def test_old_standalone_order_counts_once_at_actual_shipment_date(self):
        # 旧裁片整套单只有加工明细，一次实发，来源快照没有新版的多裁片投入清单。
        data = self.create_part_plan()
        order = TubeOutsourcingOrder.objects.get(pk=data['id'])
        order.is_plan, order.source_snapshot = False, {}
        order.save(update_fields=['is_plan', 'source_snapshot'])
        line = order.lines.get()
        line.snapshot = {'part_name': '老款布套'}
        line.save(update_fields=['snapshot'])
        self.assertEqual(self.get('items/', category='send')[0]['materials'][0]['unit'], '套')
        today = timezone.localdate()
        prior_year = today.replace(month=1, day=1) - timedelta(days=1)
        action = TubeOutsourcingAction.objects.create(order=order, kind='DISPATCH',
            actual_dispatch_date=prior_year, actor_employee=self.employee, client_request_id=uuid4(),
            request_payload_hash='workbench-history')
        order.status = 'PROCESSING'
        order.save(update_fields=['status'])
        self.assertEqual(self.get()['counts']['send'], 0)
        row, = self.get('items/', category='today')
        self.assertEqual((row['is_plan'], row['parts'][0]['remaining']), (False, str(line.quantity)))
        self.assertEqual(self.get('activity/', period='year')['dispatch_orders'], 0)
        action.actual_dispatch_date = today
        action.save(update_fields=['actual_dispatch_date'])
        self.assertEqual(self.get('activity/')['dispatch_orders'], 1)
        order.status = 'COMPLETED'
        order.save(update_fields=['status'])
        self.assertFalse(any(self.get()['counts'].values()))
        self.assertEqual(self.get('activity/')['dispatch_orders'], 1)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_ordinary_scopes_isolate_rows_on_all_endpoints(self):
        order, _ = self.dispatch_part(self.create_part_plan(), 4)
        self.receive_part(order, 1)
        self.scoped_actor()
        code = 'outsourcing.view_outsourcingorder'
        self.grant(code, 'FOLLOWED')
        for path in ('','items/?category=send','activity/'):
            self.assertEqual(self.client.get(self.url + path).status_code, 403)
        self.grant(code, 'CRAFT', [self.print_craft])
        self.assertEqual(self.get()['counts']['send'], 0)
        self.assertEqual(self.get('items/', category='send'), [])
        self.assertEqual(self.get('activity/')['dispatch_orders'], 0)
        self.grant(code, 'CRAFT', [self.external_sewing])
        self.assertEqual(self.get()['counts']['send'], 1)
        self.assertEqual(self.get('activity/')['receipt_orders'], 1)
