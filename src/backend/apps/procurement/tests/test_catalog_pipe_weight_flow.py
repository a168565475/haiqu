"""目录管材 KG 来源、总单采购及公共库存的真实 API 测试。"""
from decimal import Decimal

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.boms.material_flow_calculations import pipe_plan
from apps.inventory.models import MaterialInboundLine, PublicStockBalance, PublicStockMovement
from apps.procurement.models import PurchaseOrder, PurchaseReturnLine, SupplierPurchaseSheet
from apps.procurement.selectors import purchase_return_amount
from . import test_catalog_purchase_flow as catalog_fixture
from .pipe_receipt_fixtures import historical_weighed_return


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class CatalogPipeWeightFlowTests(APITestCase):
    make_task = catalog_fixture.CatalogPurchaseFlowTests.make_task
    make_product_line = catalog_fixture.CatalogPurchaseFlowTests.make_product_line
    make_bom = catalog_fixture.CatalogPurchaseFlowTests.make_bom
    get_source = catalog_fixture.CatalogPurchaseFlowTests.get_source
    detail = catalog_fixture.CatalogPurchaseFlowTests.detail
    batch_payload = catalog_fixture.CatalogPurchaseFlowTests.batch_payload

    def setUp(self):
        # 仅借用资料准备方法，不继承旧测试类，避免重复收集旧米制测试。
        catalog_fixture.CatalogPurchaseFlowTests.setUp(self)
        self.bom_line.raw_values.update(long_material_unit_weight_kg='2.5000', long_material_total_weight_kg='10.0000')
        self.bom_line.save(update_fields=['raw_values'])

    def create_batch(self, weight='4.1001', *, weighed_history=False):
        source_response = self.get_source(self.task)
        self.assertEqual(source_response.status_code, 200, source_response.data)
        source = source_response.data['data']
        self.assertTrue(source['can_create'], source)
        source_line = source['lines'][0]
        self.assertEqual(str(source_line['material_catalog_id']), str(self.catalog.pk))
        self.assertEqual(source_line['source_unit_text'], 'KG')
        self.assertEqual(Decimal(source_line['required_quantity']), Decimal(self.bom_line.raw_values['long_material_total_weight_kg']))
        group = self.client.post('/api/v1/purchase-groups/', {'production_task_id': str(self.task.pk),
            'bom_id': str(self.bom.pk), 'source_revision': source['source_revision']}, format='json')
        self.assertEqual(group.status_code, 201, group.data)
        self.group_id = group.data['data']['id']
        self.line_id = group.data['data']['progress']['lines'][0]['id']
        created = self.client.post(f'/api/v1/purchase-groups/{self.group_id}/batches/', self.batch_payload(weight),
            format='json', HTTP_IF_MATCH=self.detail()['ETag'])
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data['data']['id']
        confirmed = self.client.post(f'/api/v1/purchase-orders/{order_id}/confirm/', {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        options = self.client.get(f'/api/v1/purchase-orders/{order_id}/sheet-options/')
        self.assertEqual(options.status_code, 200, options.data)
        generated = self.client.post(f'/api/v1/purchase-orders/{order_id}/generate-sheets/', {'assignments': [{
            'supplier_id': str(self.supplier.pk), 'template_version_id': options.data['data']['templates'][0]['version_id'],
        }]}, format='json')
        self.assertEqual(generated.status_code, 201, generated.data)
        for sheet in generated.data['data']:
            detail = self.client.get(f"/api/v1/supplier-purchase-sheets/{sheet['id']}/")
            published = self.client.post(f"/api/v1/supplier-purchase-sheets/{sheet['id']}/publish/", {},
                format='json', HTTP_IF_MATCH=detail['ETag'])
            self.assertEqual(published.status_code, 200, published.data)
        if weighed_history:
            self.history = historical_weighed_return(PurchaseOrder.objects.get(pk=order_id).lines.get(), self.zone.pk)
        return confirmed.data['data']

    def receive(self, batch, *, weight='4.1', roots=3):
        eligible = self.client.get('/api/v1/material-inventory/eligible-lines/', {'purchase_order_id': batch['id']})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        row = eligible.data['data'][0]
        payload = {'purchase_order_line_id': batch['lines'][0]['id'], 'zone_id': str(self.zone.pk),
            'expected_remaining_quantity': row['remaining_quantity']}
        if weight is not None:
            payload['received_weight_kg'] = weight
        if roots is not None:
            payload['received_bar_count'] = roots
        return self.client.post('/api/v1/material-inventory/receipts/', {'items': [payload]}, format='json')

    def quality(self, receipt, *, weight='1', roots=1):
        batch = receipt.data['data']
        return self.client.post(f"/api/v1/material-inventory/quality-batches/{batch['id']}/confirm/", {'items': [{
            'line_id': row['id'], 'expected_received_quantity': row['received_weight_kg'] if weight is not None else row['received_bar_count'],
            **({'return_weight_kg': weight} if weight is not None else {}),
            **({'return_bar_count': roots} if roots is not None else {}),
        } for row in batch['lines']]}, format='json')

    def test_supplier_submission_keeps_pipe_remaining_weight_and_sheet_in_kg(self):
        source = self.get_source(self.task).data['data']
        group = self.client.post('/api/v1/purchase-groups/', {'production_task_id': str(self.task.pk),
            'bom_id': str(self.bom.pk), 'source_revision': source['source_revision']}, format='json')
        self.assertEqual(group.status_code, 201, group.data)
        self.group_id = group.data['data']['id']
        self.line_id = group.data['data']['progress']['lines'][0]['id']
        result = self.client.post(f'/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/',
            self.batch_payload('4.1001'), format='json', HTTP_IF_MATCH=group['ETag'])
        self.assertEqual(result.status_code, 201, result.data)
        data = result.data['data']
        self.assertEqual(data['group']['progress']['lines'][0]['remaining_purchase_quantity'], '5.8999')
        sheet = SupplierPurchaseSheet.objects.get(purchase_order_id=data['order_id'])
        self.assertEqual(sheet.status, 'DRAFT')
        line = sheet.content_snapshot['lines'][0]
        self.assertEqual((line['unit'], Decimal(line['quantity'])), ('kg', Decimal('4.1001')))

    def test_catalog_group_purchase_prices_kg_and_credits_counted_roots(self):
        batch = self.create_batch()
        purchase = PurchaseOrder.objects.get(pk=batch['id']).lines.get()
        self.assertEqual(purchase.material_catalog_id, self.catalog.pk)
        self.assertEqual(purchase.material_selection_snapshot, self.saved)
        self.assertEqual((purchase.actual_purchase_quantity, purchase.actual_bar_count, purchase.amount),
                         (Decimal('4.1001'), 2, Decimal('8.2002')))
        printed = SupplierPurchaseSheet.objects.get().content_snapshot['lines'][0]
        self.assertEqual((printed['unit'], Decimal(printed['quantity']), Decimal(printed['amount'])),
                         ('kg', Decimal('4.1001'), Decimal('8.2002')))
        self.catalog.name = '目录改名不覆盖冻结采购'
        self.catalog.save(update_fields=['name'])
        receipt = self.receive(batch, weight=None, roots=2)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        received = MaterialInboundLine.objects.get()
        self.assertIsNone(received.raw_material_information_id)
        self.assertEqual(received.material_catalog_id, self.catalog.pk)
        self.assertEqual(received.material_selection_snapshot, self.saved)
        self.assertEqual((received.received_bar_count, received.received_weight_kg, received.received_quantity),
                         (2, None, Decimal('6.1')))
        self.assertFalse(PublicStockBalance.objects.exists())
        confirmed = self.quality(receipt, weight=None, roots=1)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balance = PublicStockBalance.objects.get()
        self.assertEqual(balance.material_catalog_id, self.catalog.pk)
        self.assertIsNone(balance.raw_material_id)
        self.assertEqual((balance.quantity, balance.weight_quantity, balance.meter_quantity),
                         (Decimal('1'), None, Decimal('3.05')))
        movement = PublicStockMovement.objects.get()
        self.assertEqual((movement.quantity, movement.weight_quantity), (Decimal('1'), None))
        returned = PurchaseReturnLine.objects.get()
        self.assertEqual(returned.quantity, Decimal('1'))
        self.assertEqual(purchase_return_amount(returned.return_order), '4.1002')
        progress = self.detail().data['data']['progress']['lines'][0]
        self.assertEqual((Decimal(progress['accepted_quantity']), Decimal(progress['progress_percent'])),
                         (Decimal('2.0501'), Decimal('25')))
        trace = self.client.get(f'/api/v1/material-inventory/{self.catalog.pk}/order-purchases/',
            {'identity_key': balance.identity_key})
        self.assertEqual(trace.status_code, 200, trace.data)
        row = trace.data['data'][0]
        self.assertEqual((row['unit'], Decimal(row['actual_inbound_quantity']), Decimal(row['pending_inbound_quantity'])),
                         ('KG', Decimal('2.0501'), Decimal('2.05')))
        self.assertEqual(row['bar_counts'], {'ordered': 2, 'accepted': 1, 'pending': 1})

    def test_catalog_source_includes_root_allowance_in_weight(self):
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6,
                         order_quantity=10, purchase_allowance_mode='AUTO')
        self.bom_line.suggested_bar_count = plan['suggested_bar_count']
        self.bom_line.suggested_purchase_meters = plan['suggested_purchase_meters']
        self.bom_line.raw_values.update(pipe_plan_version=4, long_material_total_weight_kg='22.5000',
            **{key: plan[key] for key in ('purchase_allowance_mode', 'purchase_allowance_rule',
                                          'base_purchase_bar_count', 'purchase_allowance_bar_count')})
        self.bom_line.save()
        batch = self.create_batch(weight='22.5')
        line = batch['lines'][0]
        self.assertEqual((line['suggested_bar_count'], Decimal(line['suggested_purchase_weight_kg'])), (9, Decimal('22.5')))
        self.assertEqual((line['actual_bar_count'], Decimal(line['amount'])), (9, Decimal('45')))
        self.assertEqual(line['calculation_snapshot']['purchase_allowance_bar_count'], 5)

    def test_catalog_receipt_rejects_invalid_roots_or_excess_weight(self):
        batch = self.create_batch(weighed_history=True)
        for weight, roots in (('4.1', '1.5'), ('4.1', 0), ('4.1002', 3), ('2.4999', None)):
            with self.subTest(weight=weight, roots=roots):
                response = self.receive(batch, weight=weight, roots=roots)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(MaterialInboundLine.objects.count(), 1)
        receipt = self.receive(batch, roots=None)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        row = receipt.data['data']['lines'][0]
        self.assertEqual(row['received_bar_count'], 1)
        self.assertEqual(row['calculation_snapshot']['receipt_root_rounding'], 'FLOOR')

    def test_catalog_quality_requires_consistent_roots_and_weight_and_all_return_has_no_stock(self):
        batch = self.create_batch(weighed_history=True)
        receipt = self.receive(batch)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        invalid = self.quality(receipt, weight='1', roots=3)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PurchaseReturnLine.objects.exclude(inbound_line=self.history).exists())
        confirmed = self.quality(receipt, weight='4.1', roots=3)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertEqual(PurchaseReturnLine.objects.get(inbound_line__inbound_id=receipt.data['data']['id']).quantity, Decimal('4.1'))
        self.assertEqual(Decimal(self.detail().data['data']['progress']['lines'][0]['accepted_quantity']), Decimal('0'))

    def test_weight_only_partial_return_preserves_remaining_stock(self):
        batch = self.create_batch(weight='8.1', weighed_history=True)
        receipt = self.receive(batch, weight='8.1', roots=None)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        invalid = self.quality(receipt, weight='6', roots=None)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertFalse(PublicStockBalance.objects.exists())
        self.assertFalse(PurchaseReturnLine.objects.exclude(inbound_line=self.history).exists())
        confirmed = self.quality(receipt, weight='3', roots=None)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        received = MaterialInboundLine.objects.get(inbound_id=receipt.data['data']['id'])
        self.assertEqual((received.accepted_bar_count, received.return_bar_count), (2, 1))
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.weight_quantity), (Decimal('2'), Decimal('5.1')))
        returned = PurchaseReturnLine.objects.get(inbound_line=received)
        self.assertEqual(returned.quantity, Decimal('3'))
        self.assertEqual(purchase_return_amount(returned.return_order), '6.0000')

    def test_positive_return_weight_with_zero_reference_roots_is_recorded(self):
        batch = self.create_batch(weight='4', weighed_history=True)
        receipt = self.receive(batch, weight='4', roots=None)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        confirmed = self.quality(receipt, weight='0.1', roots=None)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        received = MaterialInboundLine.objects.get(inbound_id=receipt.data['data']['id'])
        self.assertEqual((received.accepted_bar_count, received.return_bar_count), (1, 0))
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.weight_quantity), (Decimal('1'), Decimal('3.9')))
        returned = PurchaseReturnLine.objects.get(inbound_line=received)
        self.assertEqual(returned.quantity, Decimal('0.1'))
        self.assertEqual(purchase_return_amount(returned.return_order), '0.2000')

