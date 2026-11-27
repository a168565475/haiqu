from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.inventory.models import Warehouse, WarehouseZone
from apps.production_tasks.models import ProductionTask
from ..merchandiser_workbench import purchase_activity, purchase_activity_rows, purchase_queues
from ..models import PurchaseOrder, PurchaseReturn, PurchaseReturnLine
from ..tracking_rules import BEIJING, beijing_today
from . import test_packaging_purchase as pack
from . import test_tracking_queries as tracking


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
class MerchandiserPurchaseTests(APITestCase):
    make_task = pack.PackagingPurchaseTests.make_task
    make_product_line = pack.PackagingPurchaseTests.make_product_line
    make_bom = pack.PackagingPurchaseTests.make_bom
    get_source = pack.PackagingPurchaseTests.get_source
    prepare = pack.PackagingPurchaseTests.prepare
    grant_packaging = pack.PackagingPurchaseTests.grant_packaging
    inbound = tracking.TrackingQueryTests.inbound

    def setUp(self):
        pack.PackagingPurchaseTests.setUp(self)
        self.grant_packaging()
        self.request = SimpleNamespace(user=get_user_model().objects.get(pk=self.user.pk), employee=self.employee)
        self.own = ProductionTask.objects.filter(followers=self.employee)
        self.today = beijing_today()

    def confirm_orders(self):
        groups = self.prepare()
        query = {'group_ids': [group['id'] for group in groups], 'batch_session_id': str(uuid4())}
        page = self.client.get(pack.PACKAGING + 'batch-page/', query)
        self.assertEqual(page.status_code, 200, page.data)
        lines = [{'purchase_group_line_id': group['progress']['lines'][0]['id'], 'actual_purchase_quantity': '4',
                  'unit_price': '2.5', 'supplier_id': str(self.supplier.pk),
                  'delivery_date': (self.today + timedelta(days=3)).isoformat()} for group in groups]
        batch = {'batch_type': 'NORMAL', 'request_id': str(uuid4()), 'currency_id': str(self.cny.pk), 'lines': lines}
        saved = self.client.post(pack.PACKAGING + 'save-page/', {**query, 'batch': batch}, format='json', HTTP_IF_MATCH=page['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        confirmed = self.client.post(pack.PACKAGING + 'confirm-page/', query, format='json', HTTP_IF_MATCH=saved['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return list(PurchaseOrder.objects.filter(purchase_group_id__in=query['group_ids']).order_by('production_task__task_number'))

    def test_follower_material_shortage_due_partial_arrival_and_return(self):
        first, second = self.confirm_orders()
        warehouse = Warehouse.objects.create(warehouse_number='MD-WH', warehouse_name='跟单材料仓', warehouse_type='MATERIAL')
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='包材')
        first.lines.update(delivery_date=self.today - timedelta(days=1))
        inbound, item = self.inbound({'id': first.pk}, '3', accepted='2')
        record = PurchaseReturn.objects.create(return_number='MD-RETURN', purchase_order=first, inbound=inbound,
            supplier=self.supplier, supplier_name_snapshot=self.supplier.supplier_name, generated_by_employee=self.employee)
        PurchaseReturnLine.objects.create(return_order=record, inbound_line=item, quantity=1)
        queues = purchase_queues(self.request, self.own, self.today)
        self.assertIsNone(queues['ordinary'])
        self.assertEqual({r['task_id'] for r in queues['need']}, {str(first.production_task_id), str(second.production_task_id)})
        bought = [r for r in queues['need'] if Decimal(r['cells']['ordered']) > 0]
        self.assertEqual([Decimal(row['cells']['remaining']) for row in bought], [6, 6])
        self.assertEqual([r['task_id'] for r in queues['soon']], [str(second.production_task_id)])
        self.assertEqual(Decimal(queues['late'][0]['cells']['remaining']), 1)
        self.assertEqual(Decimal(queues['returns'][0]['cells']['quantity']), 1)
        first.production_task.followers.remove(self.employee)
        after = purchase_queues(self.request, self.own, self.today)
        self.assertEqual((after['late'], after['returns']), ([], []))

    def test_period_first_confirmation_amounts_detail_and_revoked_scope(self):
        first, second = self.confirm_orders()
        first_time = datetime.combine(self.today.replace(day=1) - timedelta(days=1), time(12), tzinfo=BEIJING)
        first_events = AuditLog.objects.filter(object_type='PURCHASE_ORDER', object_id=first.pk, action='CONFIRMED')
        self.assertTrue(first_events.exists())
        AuditLog.objects.create(object_type='PURCHASE_ORDER', object_id=first.pk, action='CONFIRMED', occurred_at=first_time)
        current = purchase_activity(self.request, self.own, self.today.replace(day=1), self.today)
        self.assertEqual((current['purchase_order_count'], current['supplier_count']), (1, 1))
        self.assertEqual(Decimal(current['amounts'][0]['amount']), 10)
        rows = purchase_activity_rows(self.request, self.own, self.today.replace(day=1), self.today, self.supplier.pk)
        self.assertEqual([r['task_id'] for r in rows], [str(second.production_task_id)])
        second.lines.update(unit_price=None, amount=None)
        pending = purchase_activity(self.request, self.own, self.today.replace(day=1), self.today)
        self.assertEqual((pending['amounts'], pending['unpriced_count']), ([], 1))
        second.production_task.followers.remove(self.employee)
        self.assertEqual(purchase_activity(self.request, self.own, self.today, self.today)['supplier_count'], 0)
