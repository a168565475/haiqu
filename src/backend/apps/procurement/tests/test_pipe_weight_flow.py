"""重量采购用 PostgreSQL 测试库/API 验证；不代表正式账号业务验收。"""
from decimal import Decimal
from django.db import IntegrityError, transaction

from rest_framework.test import APITestCase
from apps.core.api.exceptions import Conflict

from apps.inventory.models import MaterialStockBalance
from apps.inventory.selectors import material_inbound_order_totals, material_received_totals
from apps.procurement.models import PurchaseReturnLine
from apps.procurement.pipe_purchase import pipe_source_snapshot, purchase_pipe_values
from apps.procurement.tracking_selectors import arrival_rows
from . import test_pipe_purchase_flow as pipe_fixture


class PipeWeightReceivingTests(APITestCase):
    def setUp(self):
        pipe_fixture.PipePurchaseFlowTests.setUp(self)
        self.bom_line.raw_values.update(long_material_unit_weight_kg='2.5000', long_material_total_weight_kg='10.0000')
        self.bom_line.save(update_fields=['raw_values'])
        snapshot = pipe_source_snapshot(self.bom_line)
        for name, value in purchase_pipe_values(snapshot, {'actual_purchase_quantity': '10'}).items():
            setattr(self.purchase_line, name, value)
        self.purchase_line.source_unit_text = 'KG'
        self.purchase_line.required_quantity = Decimal('10')
        self.purchase_line.actual_purchase_quantity = Decimal('10')
        self.purchase_line.amount = Decimal('20')
        self.purchase_line.save()

    def receive(self, weight='4.1', roots=2, remaining='10'):
        return self.client.post('/api/v1/material-inventory/receipts/', {'items': [{
            'purchase_order_line_id': str(self.purchase_line.pk), 'zone_id': self.zone_id,
            'expected_remaining_quantity': remaining, 'received_weight_kg': weight,
            'received_bar_count': roots,
        }]}, format='json')

    def quality(self, response, weight='0', roots=0):
        batch = response.data['data']
        return self.client.post(f"/api/v1/material-inventory/quality-batches/{batch['id']}/confirm/", {'items': [{
            'line_id': row['id'], 'expected_received_quantity': row['received_weight_kg'],
            'return_weight_kg': weight, 'return_bar_count': roots,
        } for row in batch['lines']]}, format='json')

    def test_receipt_uses_verified_roots_but_remaining_and_tracking_use_kg(self):
        response = self.receive(roots=3)
        self.assertEqual(response.status_code, 201, response.data)
        row = response.data['data']['lines'][0]
        self.assertEqual(row['received_bar_count'], 3)
        self.assertEqual(Decimal(row['received_weight_kg']), Decimal('4.1'))
        self.assertEqual(Decimal(row['received_quantity']), Decimal('9.15'))
        self.assertEqual(material_received_totals([self.purchase_line.pk])[self.purchase_line.pk], Decimal('4.1'))
        progress = material_inbound_order_totals([self.order.pk])[self.order.pk]
        self.assertEqual(progress['received_weight_quantity'], Decimal('4.1'))
        eligible = self.client.get('/api/v1/material-inventory/eligible-lines/', {'purchase_order_id': str(self.order.pk)})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(Decimal(eligible.data['data'][0]['remaining_weight_kg']), Decimal('5.9'))
        tracking = arrival_rows(task_ids=[self.task.pk])[0]
        self.assertEqual(Decimal(tracking['received_quantity']), Decimal('4.1'))
        self.assertEqual(Decimal(tracking['unreceived_quantity']), Decimal('5.9'))
        self.assertNotIn('ARRIVED', {risk['code'] for risk in tracking['risks']})
        self.assertEqual(self.receive(weight='6', remaining='5.9').status_code, 400)
        self.assertEqual(self.receive(weight='1', remaining='10').status_code, 409)

    def test_quality_keeps_remaining_weight_and_read_detail_uses_weight_fields(self):
        received = self.receive()
        self.assertEqual(received.status_code, 201, received.data)
        invalid = self.quality(received, weight='3', roots=2)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        confirmed = self.quality(received, weight='3', roots=1)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        balance = MaterialStockBalance.objects.get(measurement_kind='PIPE')
        self.assertEqual((balance.quantity, balance.weight_quantity), (Decimal('1'), Decimal('1.1')))
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal('3'))
        self.assertEqual(material_received_totals([self.purchase_line.pk])[self.purchase_line.pk], Decimal('1.1'))
        progress = material_inbound_order_totals([self.order.pk])[self.order.pk]
        self.assertEqual((progress['received_weight_quantity'], progress['return_weight_quantity']), (Decimal('4.1'), Decimal('3')))
        response = self.client.get(f'/api/v1/purchase-orders/{self.order.pk}/details/')
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data']['lines'][0]
        self.assertEqual(tuple(Decimal(row[key]) for key in ('received_weight_kg', 'accepted_weight_kg', 'return_weight_kg')),
                         (Decimal('4.1'), Decimal('1.1'), Decimal('3')))

    def test_all_returned_and_invalid_root_input_do_not_create_stock(self):
        self.assertEqual(self.receive(roots=0).status_code, 400)
        self.assertEqual(self.receive(roots='1.5').status_code, 400)
        received = self.receive()
        self.assertEqual(received.status_code, 201, received.data)
        self.assertEqual(self.quality(received, weight='4.1', roots=1).status_code, 400)
        result = self.quality(received, weight='4.1', roots=2)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(MaterialStockBalance.objects.filter(measurement_kind='PIPE').exists())
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal('4.1'))

    def test_list_totals_keep_non_pipe_kg_and_unknown_pipe_weight_distinct(self):
        received = self.receive()
        self.assertEqual(received.status_code, 201, received.data)
        line = self.purchase_line.material_inbound_lines.get()
        line.received_weight_kg = None
        line.save(update_fields=['received_weight_kg'])
        self.assertIsNone(material_inbound_order_totals([self.order.pk])[self.order.pk]['received_weight_quantity'])
        with self.assertRaises(Conflict):
            material_received_totals([self.purchase_line.pk])
        line.measurement_kind = 'OTHER'
        line.received_quantity = Decimal('7.2')
        line.accepted_quantity = Decimal('7.2')
        line.raw_bar_length_m = line.received_bar_count = line.accepted_bar_count = line.return_bar_count = None
        line.bar_weight_kg = line.accepted_weight_kg = line.return_weight_kg = None
        line.save(update_fields=['measurement_kind', 'received_quantity', 'accepted_quantity', 'raw_bar_length_m',
                                'received_bar_count', 'accepted_bar_count', 'return_bar_count', 'bar_weight_kg',
                                'accepted_weight_kg', 'return_weight_kg'])
        self.assertEqual(material_inbound_order_totals([self.order.pk])[self.order.pk]['received_weight_quantity'], Decimal('7.2'))


class PipeWeightOrderTests(APITestCase):
    make_task = pipe_fixture.PipePurchaseOrderApiTests.make_task
    make_product_line = pipe_fixture.PipePurchaseOrderApiTests.make_product_line
    make_bom = pipe_fixture.PipePurchaseOrderApiTests.make_bom
    get_source = pipe_fixture.PipePurchaseOrderApiTests.get_source
    create_payload = staticmethod(pipe_fixture.PipePurchaseOrderApiTests.create_payload)
    create = pipe_fixture.PipePurchaseOrderApiTests.create

    def setUp(self):
        pipe_fixture.PipePurchaseOrderApiTests.setUp(self)
        self.line.raw_values.update(long_material_unit_weight_kg='2.5', long_material_total_weight_kg='835')
        self.line.save(update_fields=['raw_values'])

    def test_purchase_weight_is_pricing_basis_and_roots_round_up(self):
        created = self.create(actual_bar_count=None, actual_purchase_quantity='4.1001')
        self.assertEqual(created.status_code, 201, created.data)
        row = created.data['data']['lines'][0]
        self.assertEqual(row['source_unit_text'], 'KG')
        self.assertEqual(row['actual_bar_count'], 2)
        self.assertEqual(Decimal(row['actual_purchase_quantity']), Decimal('4.1001'))
        self.assertEqual(Decimal(row['amount']), Decimal('8.2002'))
        self.assertEqual(Decimal(row['suggested_purchase_weight_kg']), Decimal('835'))
        confirmed = self.client.post(f"/api/v1/purchase-orders/{created.data['data']['id']}/confirm/", {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def test_catalog_pipe_cannot_bypass_weight_quantity_constraint(self):
        from apps.material_catalog.models import MaterialCatalog
        from apps.procurement.models import PurchaseOrderLine
        created = self.create(actual_purchase_quantity='4.1001')
        self.assertEqual(created.status_code, 201, created.data)
        catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='重量约束管材')
        line = PurchaseOrderLine.objects.get(pk=created.data['data']['lines'][0]['id'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseOrderLine.objects.filter(pk=line.pk).update(material_catalog=catalog, actual_purchase_weight_kg=Decimal('4.2'))
