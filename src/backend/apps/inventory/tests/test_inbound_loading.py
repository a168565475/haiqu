from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.procurement.tests import test_loading_read_api as purchase_tests
from apps.procurement.models import PurchaseOrderLine, PurchaseReturn, PurchaseReturnLine
from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound, MaterialInboundLine
from apps.inventory.selectors import material_received_totals
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit


class InboundLoadingTests(APITestCase):
    make_order = purchase_tests.PurchaseOrderLoadingReadTests.make_order

    def setUp(self):
        purchase_tests.PurchaseOrderLoadingReadTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='inventory', codename__in=['receive_material', 'quality_confirm_material', 'view_materialinbound']))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.order.status = 'PURCHASING'; self.order.save()
        self.hidden.status = 'PURCHASING'; self.hidden.save()
        self.line = self.order.lines.get(); self.line.actual_purchase_quantity = 10; self.line.save()
        self.warehouse = Warehouse.objects.create(warehouse_number='INBOUND-LOAD', warehouse_name='材料仓', warehouse_type='MATERIAL')
        self.zone = WarehouseZone.objects.create(warehouse=self.warehouse, zone_name='库区')
        material_category, _ = ProductCategory.objects.get_or_create(
            category_name='入库加载测试材料', defaults={'item_type': 'MATERIAL'}
        )
        stock_unit, _ = ProductionUnit.objects.get_or_create(
            unit_code='INBOUND_LOAD_PCS', defaults={'unit_name': '入库加载测试件'}
        )
        self.raw_material = RawMaterialInformation.objects.create(
            material_number='MAT-INBOUND-LOAD-001', item_type='MATERIAL', category=material_category,
            material_name='入库加载测试材料', specification='测试规格', unit=stock_unit,
            warehouse_number=self.warehouse.warehouse_number, warehouse_name=self.warehouse.warehouse_name,
        )
        self.root = '/api/v1/material-inventory/'

    def batch(self, number, status, quantities):
        inbound = MaterialInbound.objects.create(inbound_number=f'INBOUND-{number}', purchase_order=self.order, status=status, received_by_employee=self.employee)
        for received, returned in quantities:
            MaterialInboundLine.objects.create(
                inbound=inbound, purchase_order_line=self.line, raw_material_information=self.raw_material,
                zone=self.zone, received_quantity=received, return_quantity=returned,
                accepted_quantity=received-returned, source_unit_text_snapshot=self.raw_material.unit.unit_code,
                purchased_quantity_snapshot=10,
            )
        return inbound

    def get(self, action, params=None):
        response = self.client.get(self.root + action + '/', params or {}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_receiving_options_only_active_material_warehouses_and_zones(self):
        disabled = Warehouse.objects.create(warehouse_number='INBOUND-OFF', warehouse_name='停用仓', warehouse_type='MATERIAL', status='DISABLED')
        finished = Warehouse.objects.create(warehouse_number='INBOUND-FIN', warehouse_name='成品仓', warehouse_type='FINISHED')
        WarehouseZone.objects.create(warehouse=disabled, zone_name='停用仓库区')
        WarehouseZone.objects.create(warehouse=finished, zone_name='成品库区')
        WarehouseZone.objects.create(warehouse=self.warehouse, zone_name='停用库区', status='DISABLED')
        full = self.get('options').json()['data']
        with CaptureQueriesContext(connection) as queries:
            scoped = self.get('options', {'scope': 'receiving'}).json()['data']
        expected = {
            'warehouses': [{k:r[k] for k in ['id', 'warehouse_number', 'warehouse_name']} for r in full['warehouses']],
            'zones': [{k:r[k] for k in ['id', 'warehouse', 'zone_name']} for r in full['zones']],
        }
        self.assertEqual(scoped, expected)
        sql='\n'.join(q['sql'] for q in queries)
        for table in ['procurement_purchase_order', 'inventory_material_inbound_line', 'inventory_warehouse_location', 'inventory_finished_goods_receipt']:
            self.assertNotIn(f'FROM "{table}"', sql)
            self.assertNotIn(f'JOIN "{table}"', sql)
        self.assertEqual(len(scoped['warehouses']), 1); self.assertEqual(len(scoped['zones']), 1)

    def test_receiving_options_validate_scope_and_keep_permission(self):
        self.assertEqual(self.client.get(self.root+'options/', {'scope':'invalid'}, HTTP_HOST='localhost').status_code, 400)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.root+'options/', {'scope':'receiving'}, HTTP_HOST='localhost').status_code, 403)

    def test_list_aggregates_batches_without_counting_one_batch_per_line(self):
        self.batch(1, 'PENDING_QUALITY', [(2,0),(1,0)])
        self.batch(2, 'CONFIRMED', [(4,1)])
        with CaptureQueriesContext(connection) as queries:
            rows=self.get('procurement-inbound-orders').json()['data']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],str(self.order.pk))
        self.assertEqual(rows[0]['pending_quality_count'],1)
        self.assertEqual(rows[0]['confirmed_batch_count'],1)
        self.assertEqual(rows[0]['received_quantity'],'7.0000')
        self.assertEqual(rows[0]['return_quantity'],'1.0000')
        self.assertEqual(rows[0]['remaining_line_count'],1)
        self.assertEqual(rows[0]['workflow_status'],'PENDING_QUALITY')
        sql='\n'.join(q['sql'] for q in queries)
        for table in ['inventory_warehouse_zone','inventory_warehouse','procurement_supplier']:
            self.assertNotIn(f'FROM "{table}"', sql)
        self.assertEqual(self.get('procurement-inbound-orders', {'q':'NO-MATCH'}).data['data'], [])

    def test_selected_order_totals_are_scoped_and_pending_quality_reserves_quantity(self):
        self.batch(1,'PENDING_QUALITY',[(2,0),(1,0)])
        self.batch(2,'CONFIRMED',[(4,1)])
        with patch('apps.inventory.api.views.material_received_totals', wraps=material_received_totals) as totals:
            orders=self.get('eligible-purchase-orders', {'purchase_order_id':str(self.order.pk)}).data['data']
        self.assertEqual(set(totals.call_args.args[0]),{self.line.pk})
        self.assertEqual(len(orders),1)
        lines=self.get('eligible-lines',{'purchase_order_id':str(self.order.pk)}).data['data']
        self.assertEqual(lines[0]['remaining_quantity'],'4.0000')
        hidden=self.get('eligible-purchase-orders',{'purchase_order_id':str(self.hidden.pk)})
        self.assertEqual(hidden.data['data'],[])
        self.assertEqual(self.client.get(self.root+'eligible-lines/',{'purchase_order_id':str(self.hidden.pk)},HTTP_HOST='localhost').status_code,404)

    def test_return_gates_and_completed_order_replenishment_are_preserved(self):
        inbound=self.batch(1,'CONFIRMED',[(10,2)])
        record=PurchaseReturn.objects.create(return_number='RETURN-LOAD',purchase_order=self.order,inbound=inbound,supplier=self.supplier,generated_by_employee=self.employee)
        PurchaseReturnLine.objects.create(return_order=record,inbound_line=inbound.lines.get(),quantity=2)
        for status, workflow in [('QUALITY_GENERATED','PENDING_PROCUREMENT_CONFIRMATION'),('PROCUREMENT_CONFIRMED','PENDING_RETURN')]:
            record.status=status; record.save()
            rows=self.get('procurement-inbound-orders').data['data']
            self.assertEqual(rows[0]['workflow_status'],workflow)
            self.assertEqual(self.get('eligible-lines',{'purchase_order_id':str(self.order.pk)}).data['data'],[])
        record.status='COMPLETED'; record.save()
        self.order.status='COMPLETED'; self.order.save()
        completed = self.get('procurement-inbound-orders').data['data']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['workflow_status'], 'PARTIAL_RECEIVED')
        self.assertEqual(completed[0]['workflow_status_display'], '部分入库')
        self.assertEqual(len(self.get('eligible-purchase-orders',{'purchase_order_id':str(self.order.pk)}).data['data']),1)
        self.assertEqual(self.get('eligible-lines',{'purchase_order_id':str(self.order.pk)}).data['data'][0]['remaining_quantity'],'2.0000')

    def test_inbound_list_uses_sample_number_as_sample_order_source(self):
        from apps.samples.models import SampleMaterialProcurementRequest, SampleMaterialRequest, SampleRequest

        sample = SampleRequest.objects.create(
            customer_account=self.customer, owner_employee=self.employee,
            requested_by_employee=self.employee,
            request_number='DY202609160001', status='PROCUREMENT_PENDING',
            application_payload_hash='inbound-list-test', requested_at=timezone.now(),
        )
        material = SampleMaterialRequest.objects.create(sample_request=sample)
        procurement = SampleMaterialProcurementRequest.objects.create(material_request=material, lines=[])
        sample_order = self.order.__class__.objects.create(
            order_number='CGDD2026091699', source_type='SAMPLE',
            sample_procurement_request=procurement, sample_number_snapshot=sample.request_number,
            status='PURCHASING', created_by_employee=self.employee,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=sample_order, line_number=1, quantity_parse_status='READY',
            actual_purchase_quantity=1, supplier_name_snapshot='打样供应商',
        )

        rows = self.get('procurement-inbound-orders').data['data']
        sample_row = next(row for row in rows if str(row['id']) == str(sample_order.pk))
        self.assertEqual(sample_row['source_type'], 'SAMPLE')
        self.assertEqual(sample_row['source_number'], sample.request_number)
        searched = self.get('procurement-inbound-orders', {'q': sample.request_number}).data['data']
        self.assertEqual([str(row['id']) for row in searched], [str(sample_order.pk)])
