from datetime import date
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, Supplier
from apps.procurement.selectors import purchase_orders_with_context
from apps.procurement.api.serializers import PurchaseOrderDetailSerializer


class PurchaseOrderLoadingReadTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='purchase_loading')
        self.employee = Employee.objects.create(user=self.user, employee_code='PUR_LOAD', display_name='采购加载测试')
        self.other = Employee.objects.create(employee_code='PUR_OTHER', display_name='其他员工')
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='procurement', codename__in=['add_purchaseorder', 'view_purchaseorder']))
        self.customer = CustomerAccount.objects.create(account_code='PUR_LOAD', account_name='采购加载客户', primary_country_code='CN')
        self.currency, _ = Currency.objects.get_or_create(code='CNY', defaults={'numeric_code': '156', 'chinese_name': '人民币', 'english_name': 'Yuan'})
        self.order = self.make_order(1, self.employee)
        self.hidden = self.make_order(2, self.other)
        self.archived = self.make_order(3, self.employee)
        self.archived.archived_at = timezone.now(); self.archived.save()
        self.supplier = Supplier.objects.create(supplier_number='GYS99991', supplier_name='启用供应商', supplier_type='MATERIAL', supplier_categories=['TUBE'])
        Supplier.objects.create(supplier_number='GYS99992', supplier_name='停用供应商', supplier_type='MATERIAL', is_disabled=True)
        Supplier.objects.create(supplier_number='GYS99993', supplier_name='归档供应商', supplier_type='MATERIAL', archived_at=timezone.now())
        PurchaseOrderLine.objects.create(purchase_order=self.order, line_number=1, quantity_parse_status='READY', supplier=self.supplier,
                                         supplier_number_snapshot=self.supplier.supplier_number, supplier_name_snapshot=self.supplier.supplier_name,
                                         product_name_snapshot='采购产品', section_type_snapshot='PROFILE', part_name_snapshot='管材')
        self.client.force_authenticate(self.user)

    def make_order(self, index, employee):
        task = ProductionTask.objects.create(task_number=f'PUR-LOAD-{index}', contract_number=f'PUR-CONTRACT-{index}', order_number=f'ORDER-{index}',
            order_source='NEW', customer_account=self.customer, salesperson=employee, currency=self.currency,
            order_date=date(2026, 9, 16), delivery_date=date(2026, 10, 1), includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method='SINGLE')
        return PurchaseOrder.objects.create(order_number=f'CGDD20260916{index:02d}', production_task=task,
            production_task_number_snapshot=task.task_number, sales_order_number_snapshot=task.order_number,
            customer_name_snapshot=self.customer.account_name, source_revision='read-test', currency=self.currency, created_by_employee=employee)

    def test_supplier_scope_matches_full_options_without_evaluating_purchase_sources(self):
        full = self.client.get('/api/v1/purchase-orders/options/', HTTP_HOST='localhost')
        self.assertEqual(full.status_code, 200, full.data)
        with patch('apps.procurement.api.views.evaluate_purchase_source', side_effect=AssertionError('不应计算采购来源')):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get('/api/v1/purchase-orders/options/', {'scope': 'suppliers'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], {'suppliers': full.data['data']['suppliers']})
        self.assertEqual([row['id'] for row in response.data['data']['suppliers']], [str(self.supplier.pk)])
        sql = '\n'.join(q['sql'] for q in queries)
        for table in ['production_task', 'bom', 'sample_material_procurement_request', 'reference_currency']:
            self.assertNotIn(f'FROM "{table}"', sql)
        self.assertIn('production_tasks', full.data['data'])
        self.assertIn('sample_requests', full.data['data'])

    def test_supplier_scope_validation_and_existing_permission_are_preserved(self):
        invalid = self.client.get('/api/v1/purchase-orders/options/', {'scope': 'invalid'}, HTTP_HOST='localhost')
        self.assertEqual(invalid.status_code, 400)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='procurement', codename='add_purchaseorder'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        denied = self.client.get('/api/v1/purchase-orders/options/', {'scope': 'suppliers'}, HTTP_HOST='localhost')
        self.assertEqual(denied.status_code, 403)

    def test_read_relations_keep_payload_and_do_not_add_per_line_queries(self):
        expected = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=self.order.pk)).get()).data
        with CaptureQueriesContext(connection) as queries:
            actual = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=self.order.pk), read_optimized=True).get()).data
        self.assertEqual(actual, expected)
        for sql in [queries[0]['sql'], queries[1]['sql']]:
            for table in ['sales_order', 'reference_currency', 'customer_account', 'procurement_supplier', 'bom', 'bom_line']:
                self.assertNotIn(f'JOIN "{table}"', sql)
        original_count = len(queries)
        PurchaseOrderLine.objects.bulk_create([PurchaseOrderLine(purchase_order=self.order, line_number=i, quantity_parse_status='MISSING') for i in range(2, 12)])
        with CaptureQueriesContext(connection) as queries:
            result = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=self.order.pk), read_optimized=True).get()).data
        self.assertEqual(len(queries), original_count)
        self.assertEqual(result['line_count'], 11)

    def test_list_detail_and_filter_options_keep_data_scope_and_etag(self):
        response = self.client.get('/api/v1/purchase-orders/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['data']], [str(self.order.pk)])
        detail = self.client.get(f'/api/v1/purchase-orders/{self.order.pk}/', HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200); self.assertTrue(detail.get('ETag'))
        for order in [self.hidden, self.archived]:
            self.assertEqual(self.client.get(f'/api/v1/purchase-orders/{order.pk}/', HTTP_HOST='localhost').status_code, 404)
        options = self.client.get('/api/v1/purchase-orders/filter-options/', HTTP_HOST='localhost')
        self.assertEqual(len(options.data['data']['production_tasks']), 1)
        stats = self.client.get('/api/v1/purchase-orders/stats/', HTTP_HOST='localhost')
        self.assertEqual(stats.data['data']['total'], 1)

    def test_sample_source_and_dates_keep_complete_payload(self):
        from apps.samples.models import SampleRequest, SampleMaterialRequest, SampleMaterialProcurementRequest, SampleMaterialPurchaseSource
        sample = SampleRequest.objects.create(customer_account=self.customer, owner_employee=self.employee,
            request_number='PUR-LOAD-SAMPLE', status='PROCUREMENT_PENDING', application_payload_hash='test',
            order_date=date(2026, 9, 16), sample_due_date=date(2026, 10, 1), requested_at=timezone.now())
        material = SampleMaterialRequest.objects.create(sample_request=sample)
        procurement = SampleMaterialProcurementRequest.objects.create(material_request=material, lines=[])
        order = PurchaseOrder.objects.create(order_number='CGDD2026091604', source_type='SAMPLE', sample_procurement_request=procurement,
            sample_number_snapshot=sample.request_number, created_by_employee=self.employee)
        line = PurchaseOrderLine.objects.create(purchase_order=order, line_number=1, quantity_parse_status='READY')
        key = uuid4()
        SampleMaterialPurchaseSource.objects.create(procurement_request=procurement, line_key=key, purchase_order_line=line)
        expected = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=order.pk)).get()).data
        actual = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=order.pk), read_optimized=True).get()).data
        self.assertEqual(actual, expected)
        self.assertEqual(actual['source_number'], sample.request_number)
        self.assertEqual(actual['order_date'], '2026-09-16')
        self.assertEqual(actual['delivery_date'], '2026-10-01')
        self.assertEqual(actual['lines'][0]['sample_line_key'], str(key))

    def test_return_states_keep_complete_payload_and_completion_gate(self):
        from apps.inventory.models import Warehouse, WarehouseZone, MaterialInbound, MaterialInboundLine
        from apps.procurement.models import PurchaseReturn, PurchaseReturnLine
        warehouse = Warehouse.objects.create(warehouse_number='PUR-TEST', warehouse_name='采购测试仓', warehouse_type='MATERIAL')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='测试区')
        inbound = MaterialInbound.objects.create(inbound_number='PUR-TEST-RECEIPT', purchase_order=self.order, status='CONFIRMED', received_by_employee=self.employee)
        line = self.order.lines.get()
        line.actual_purchase_quantity = 10; line.save()
        self.order.status = 'PURCHASING'; self.order.save()
        received = MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=line, zone=zone,
            received_quantity=10, return_quantity=2, accepted_quantity=8, purchased_quantity_snapshot=10)
        def compare(expected_status, can_complete):
            expected = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=self.order.pk)).get()).data
            actual = PurchaseOrderDetailSerializer(purchase_orders_with_context(PurchaseOrder.objects.filter(pk=self.order.pk), read_optimized=True).get()).data
            self.assertEqual(actual, expected)
            self.assertEqual(actual['completion']['return_status'], expected_status)
            self.assertEqual(actual['completion']['can_complete'], can_complete)
        compare('MISSING', False)
        record = PurchaseReturn.objects.create(return_number='PUR-TEST-RETURN', purchase_order=self.order, inbound=inbound,
            supplier=self.supplier, generated_by_employee=self.employee)
        PurchaseReturnLine.objects.create(return_order=record, inbound_line=received, quantity=2)
        for state in ['QUALITY_GENERATED', 'PROCUREMENT_CONFIRMED', 'COMPLETED']:
            record.status = state; record.save()
            compare(state, state == 'COMPLETED')
