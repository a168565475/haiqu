"""实际加工厂变化后，总单筛选保留整单收发量，不分摊无关联入库。"""
import uuid

from django.test import override_settings
from rest_framework.test import APITestCase

from ..models import OutsourcingFactory, OutsourcingFactoryCraft
from .test_plan_orders_api import PlanApiFixture


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanFactoryFilterTests(PlanApiFixture, APITestCase):
    def test_actual_factory_filter_finds_parent_without_attributing_receipts(self):
        order = self.plan()
        other = OutsourcingFactory.objects.get(pk=self.factory.pk)
        other.pk, other.factory_number, other.name = uuid.uuid4(), 'PLAN-OTHER-FACTORY', '实际补料加工厂'
        other.save(force_insert=True)
        OutsourcingFactoryCraft.objects.create(factory=other, craft=self.spray, craft_name_snapshot=self.spray.name)
        payload = self.dispatch_payload(quantity='20')
        payload['lines'][0]['factory_id'] = str(other.pk)
        order = self.write_plan(order, 'dispatch', payload)
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '10'))
        response = self.client.get('/api/v1/unified-outsourcing-orders/', {'factory_id': str(other.pk)}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        rows = [row for row in response.data['data'] if row['record_type'] == 'TUBE']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['id'], order['id'])
        self.assertEqual(row['plan_summary']['dispatched_quantity'], '20')
        self.assertEqual(row['plan_summary']['received_quantity'], '10')
        self.assertIsNone(row['factory_returned_quantity'])
        self.assertIn(other.name, row['factory_names'])
        self.assertEqual(row['planned_amount'], '250.00')
