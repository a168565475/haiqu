import copy
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.models import FinishedGoodsOutbound, FinishedGoodsOutboundLine, MaterialInbound
from apps.procurement.models import PurchaseOrder
from .finished_receipt_fixture import historical_finished_receipt
from .test_inventory_api import FinishedGoodsInventoryApiTests as InventoryFixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class FollowedInventoryRecordAccessTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        InventoryFixture.setUp(self)
        self.scoped_actor()
        self.task.followers.add(self.scope_employee)
        self.other_task = copy.copy(self.task)
        self.other_task.pk = None
        self.other_task.task_number = 'HT-FOLLOWED-OTHER'
        self.other_task.contract_number = 'FOLLOWED-OTHER'
        self.other_task.salesperson = self.scope_employee
        self.other_task.created_by_employee = self.scope_employee
        self.other_task.save()
        self.other_line = copy.copy(self.line)
        self.other_line.pk = None
        self.other_line.production_task = self.other_task
        self.other_line.save()
        self.own_receipt = historical_finished_receipt(product_line=self.line, actor=self.employee, location_id=self.location_id)
        self.other_receipt = historical_finished_receipt(product_line=self.other_line, actor=self.employee, location_id=self.location_id)

    def outbound(self, number, receipts):
        outbound = FinishedGoodsOutbound.objects.create(outbound_number=number, outbound_by_employee=self.employee)
        for receipt in receipts:
            FinishedGoodsOutboundLine.objects.create(outbound=outbound, receipt=receipt, outbound_quantity=1,
                quantity_per_box=1, box_count=1, tail_quantity=0, before_quantity=6, after_quantity=5)
        return outbound

    def purchase(self, task, number):
        return PurchaseOrder.objects.create(order_number=number, production_task=task,
            production_task_number_snapshot=task.task_number, sales_order_number_snapshot='',
            customer_name_snapshot='跟单范围客户', source_revision='1', created_by_employee=self.employee)

    def test_finished_records_aggregation_detail_and_transfer_follow_current_task(self):
        self.grant('inventory.view_finishedgoodsreceipt', 'FOLLOWED')
        records = self.client.get('/api/v1/finished-goods-records/')
        self.assertEqual(records.status_code, 200, records.data)
        self.assertEqual([row['id'] for row in records.data['data']['items']], [str(self.own_receipt.pk)])
        self.assertEqual(self.client.get(f'/api/v1/finished-goods-records/{self.other_receipt.pk}/').status_code, 404)
        inventory = self.client.get('/api/v1/finished-goods-inventory/')
        self.assertEqual(inventory.status_code, 200, inventory.data)
        self.assertEqual(inventory.data['count'], 1)
        self.assertEqual(inventory.data['results'][0]['inventory_quantity'], 6)
        self.task.followers.clear()
        self.assertEqual(self.client.get('/api/v1/finished-goods-records/').data['data']['total'], 0)
        self.assertEqual(self.client.get(f'/api/v1/finished-goods-records/{self.own_receipt.pk}/').status_code, 404)

    def test_mixed_outbound_and_attachment_do_not_reveal_other_task(self):
        self.grant('inventory.view_finishedgoodsoutbound', 'FOLLOWED')
        own = self.outbound('FOLLOWED-OUT-ONE', [self.own_receipt])
        other = self.outbound('FOLLOWED-OUT-OTHER', [self.other_receipt])
        mixed = self.outbound('FOLLOWED-OUT-MIXED', [self.own_receipt, self.other_receipt])
        root = '/api/v1/finished-goods-inventory/outbounds/'
        response = self.client.get(root)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['data']['items']], [str(own.pk)])
        for record in (other, mixed):
            self.assertEqual(self.client.get(root + f'{record.pk}/').status_code, 404)
            self.assertEqual(self.client.get(root + f'{record.pk}/attachments/{uuid4()}/').status_code, 404)

    def test_material_receipts_exclude_manual_and_other_tasks(self):
        self.grant('inventory.view_material_receipt', 'FOLLOWED')
        own_order = self.purchase(self.task, 'CGDD261102001')
        other_order = self.purchase(self.other_task, 'CGDD261102002')
        own = MaterialInbound.objects.create(inbound_number='FOLLOWED-IN-ONE', purchase_order=own_order, status='CONFIRMED', received_by_employee=self.employee)
        MaterialInbound.objects.create(inbound_number='FOLLOWED-IN-OTHER', purchase_order=other_order, status='CONFIRMED', received_by_employee=self.employee)
        MaterialInbound.objects.create(inbound_number='FOLLOWED-IN-MANUAL', status='CONFIRMED', received_by_employee=self.employee)
        response = self.client.get('/api/v1/material-inventory/receipts/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['data']], [str(own.pk)])

    def test_purchase_detail_tuple_uses_only_granted_operations(self):
        self.grant('procurement.view_purchaseorder', 'FOLLOWED')
        self.grant('inventory.view_finishedgoodsreceipt', 'MODULE')
        own = self.purchase(self.task, 'CGDD261102003')
        other = self.purchase(self.other_task, 'CGDD261102004')
        root = '/api/v1/purchase-orders/'
        self.assertEqual(self.client.get(root + f'{own.pk}/details/').status_code, 200)
        self.assertEqual(self.client.get(root + f'{other.pk}/details/').status_code, 404)
        self.grant('inventory.receive_material', 'MODULE')
        self.assertEqual(self.client.get(root + f'{other.pk}/details/').status_code, 404)
        other.status = 'PURCHASING'
        other.save(update_fields=['status'])
        # 当前详情动作明确允许仓库读取，独立MODULE授权才可并入全厂范围。
        self.assertEqual(self.client.get(root + f'{other.pk}/details/').status_code, 200)

    def test_followed_has_no_global_raw_inventory_but_independent_module_grant_restores_it(self):
        self.grant('inventory.view_materialinbound', 'FOLLOWED')
        self.assertEqual(self.client.get('/api/v1/material-inventory/').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/material-inventory/options/').status_code, 403)
        self.grant('inventory.view_materialinbound', 'MODULE')
        self.assertEqual(self.client.get('/api/v1/material-inventory/').status_code, 200)
