from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from .test_part_flow_plan_api import BASE, PartFlowPlanFixture


PRINT = '/api/v1/cut-piece-printing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class CutPiecePrintingAccessTests(PartFlowPlanFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.scoped_actor()
        self.source = {'schedule_product_id': str(self.schedule_product.pk), 'craft_id': str(self.print_craft.pk)}
        self.task = self.schedule_product.schedule.production_task

    def test_only_dedicated_permission_opens_entry_and_only_owned_task_is_readable(self):
        self.task.followers.add(self.scope_employee)
        self.grant('outsourcing.add_outsourcingorder')
        self.assertEqual(self.client.get(PRINT + 'options/').status_code, 403)
        self.grant(CUT_PIECE_PRINTING, 'FOLLOWED')
        response = self.client.get(PRINT + 'options/', {'category': 'screen_printing'})
        self.assertEqual(response.status_code, 200, response.data)
        options = response.data['data']
        self.assertEqual([row['id'] for row in options['tasks']], [str(self.task.pk)])
        self.assertEqual({row['outsourcing_code'] for row in options['crafts']}, {'SCREEN_PRINTING'})
        bad_craft = {**self.source, 'craft_id': str(self.external_sewing.pk)}
        self.assertEqual(self.client.get(PRINT + 'source-context/', bad_craft).status_code, 400)
        self.assertEqual(self.client.get(PRINT + 'source-context/', {**self.source, 'source_kind': 'SEWING'}).status_code, 400)
        self.task.followers.remove(self.scope_employee)
        self.assertEqual(self.client.get(PRINT + 'options/').data['data']['tasks'], [])
        self.assertEqual(self.client.get(PRINT + 'source-context/', self.source).status_code, 404)

    def test_create_list_detail_retry_and_warehouse_are_independently_authorized(self):
        self.grant(CUT_PIECE_PRINTING, 'FOLLOWED')
        self.task.followers.add(self.scope_employee)
        resp = self.client.get(PRINT + 'source-context/', self.source)
        self.assertEqual(resp.status_code, 200, resp.data)
        context = resp.data['data']
        self.assertTrue(context['screen_print_pieces'])
        self.assertEqual(context['material_rows'], [])
        row = context['rows'][0]
        payload = {**self.source, 'client_request_id': str(uuid4()), 'is_plan': True, 'source_kind': 'CUTTING',
                   'source_revision': context['source_revision'], 'planned_dispatch_date': str(timezone.localdate()),
                   'expected_return_date': str(timezone.localdate()), 'lines': [{'component_identity': row['component_identity'],
                       'quantity': row['order_required'], 'unit_price': '1.00', 'factory_id': str(self.factory.pk)}]}
        response = self.client.post(PRINT, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        detail = response.data['data']
        pk = detail['id']
        self.assertFalse(detail['permissions']['can_dispatch'])
        self.assertFalse(detail['permissions']['can_receive'])
        self.assertEqual(self.client.get(PRINT + pk + '/').status_code, 200)
        self.assertEqual(self.client.get(PRINT + 'by-request/' + payload['client_request_id'] + '/').status_code, 200)
        self.assertEqual(self.client.get(PRINT).data['meta']['total'], 1)
        self.assertEqual(self.client.post(BASE + pk + '/plan-dispatch/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post(BASE + pk + '/plan-receipt/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post(BASE, payload, format='json').status_code, 403)
        self.task.followers.remove(self.scope_employee)
        for path in (pk + '/', 'by-request/' + payload['client_request_id'] + '/'):
            self.assertEqual(self.client.get(PRINT + path).status_code, 404)
        self.assertEqual(self.client.post(PRINT, payload, format='json').status_code, 404)
        self.assertEqual(self.client.get(PRINT, {'warehouse_stage': 'all'}).data['meta']['total'], 0)
