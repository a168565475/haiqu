import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from unittest import skipUnless
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from apps.inventory import services
from apps.inventory.models import FinishedGoodsReceipt, Warehouse, WarehouseLocation, WarehouseZone
from apps.products.models import ProductInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit
from apps.workshop_reporting.models import WorkReport, WorkReportLine
from .test_assembly_receipts import AssemblyFixture
from .assembly_reporting_fixture import seed_reported_assembly


class ReceiptReportingConcurrencyTests(AssemblyFixture, TransactionTestCase):
    def setUp(self):
        with transaction.atomic():
            # 自建所用权限，不与其他 available_apps 测试混用全库序列化恢复。
            for app_label in ('inventory', 'production_tasks', 'production_scheduling'):
                create_permissions(apps.get_app_config(app_label), verbosity=0)
            # 并发测试会清空数据库，必须自行准备资料，不能依赖主库副本或其他测试留下的产品。
            unit, _ = ProductionUnit.objects.get_or_create(unit_name='张', defaults={'unit_code': 'RACEUNIT'})
            category, _ = ProductCategory.objects.get_or_create(category_name='并发验收成品', defaults={'item_type': 'FINISHED'})
            item, _ = ProductItem.objects.get_or_create(item_number='RACEITEM', defaults={'category': category})
            ProductInformation.objects.get_or_create(product_number='RACEPRODUCT', defaults={
                'product_name': '并发验收椅', 'specification': '测试规格', 'unit': unit,
                'category': category, 'product_item': item, 'scale': 'REGULAR',
            })
            Currency.objects.get_or_create(code='CNY', defaults={'numeric_code': '156', 'chinese_name': '人民币'})
            self.prepare(quantity=1000, tolerance='2')
        self.user.is_superuser = True; self.user.save(update_fields=['is_superuser'])
        self.client.force_authenticate(self.user)
        self.report = WorkReport.objects.get(scheme=self.assembly_scheme)
        self.report_line = self.report.lines.get()
        WorkReportLine.objects.filter(pk=self.report_line.pk).update(quantity=800)

    def race(self, legacy=False):
        barrier = Barrier(2)
        preview_etag = self.preview()['etag']
        report_url = f'/api/v1/workshop-reporting/work-reports/{self.report.pk}/'
        report_etag = self.client.get(report_url)['ETag']
        edit = dict(schedule_product_id=str(self.plan.pk), scheme_id=str(self.assembly_scheme.pk),
            scheme_revision=self.assembly_scheme.revision, production_date=str(timezone.localdate()),
            lines=[dict(scheme_line_id=str(self.report_line.scheme_line_id),
                workshop_employee_id=str(self.report_line.workshop_employee_id), quantity='600', production_line=1)])
        new_payload = self.payload(received_quantity=700)
        old_payload = dict(production_task_product_id=str(self.line.pk), expected_received_total=0,
            received_quantity=700, quantity_per_box=None, location_id=self.location_id,
            unit_id=str(self.line.unit_id), actual_color='黑色')
        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                client = APIClient(); client.force_authenticate(self.user)
                barrier.wait(timeout=10)
                if action == 'edit':
                    response = client.patch(report_url, edit, format='json', HTTP_IF_MATCH=report_etag)
                elif legacy:
                    response = client.post('/api/v1/finished-goods-inventory/receipts/', old_payload, format='json')
                else:
                    response = client.post('/api/v1/assembly-finished-receipts/', new_payload, format='json', HTTP_IF_MATCH=preview_etag)
                return response.status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipt_future = pool.submit(run, 'receipt'); edit_future = pool.submit(run, 'edit')
            receipt_status, edit_status = receipt_future.result(timeout=25), edit_future.result(timeout=25)
        received = sum(FinishedGoodsReceipt.objects.values_list('received_quantity', flat=True))
        reported = WorkReportLine.objects.get(report=self.report).quantity
        self.assertLessEqual(received, reported)
        self.assertIn((receipt_status, edit_status), [(201,400),(400,200),(412,200)])

    def test_assembly_receipt_and_report_reduction_share_product_lock(self):
        self.race()

    def test_legacy_receipt_and_report_reduction_share_product_lock(self):
        self.race(legacy=True)

    @skipUnless(connection.vendor == 'postgresql', '成品入库锁序需要 PostgreSQL 双连接验证')
    def test_batch_and_single_receipts_lock_all_warehouses_before_daily_number(self):
        batch_line = copy.copy(self.line)
        batch_line.pk = uuid.uuid4()
        batch_line._state.adding = True
        batch_line.line_number = 2
        batch_line.save(force_insert=True)
        single_task = copy.copy(self.task)
        single_task.pk = uuid.uuid4()
        single_task._state.adding = True
        single_task.task_number = 'HT-INV-RACE-SINGLE'
        single_task.contract_number = 'HTC-INV-RACE-SINGLE'
        single_task.order_number = 'ORDER-INV-RACE-SINGLE'
        single_task.save(force_insert=True)
        single_line = copy.copy(self.line)
        single_line.pk = uuid.uuid4()
        single_line._state.adding = True
        single_line.production_task = single_task
        single_line.save(force_insert=True)
        with transaction.atomic():
            seed_reported_assembly(batch_line, self.employee)
            seed_reported_assembly(single_line, self.employee)

        warehouse = Warehouse.objects.create(
            warehouse_number='CKT-RACE-02', warehouse_name='并发第二成品仓', warehouse_type='FINISHED')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='并发库区')
        batch_location = WarehouseLocation.objects.create(zone=zone, location_number='BATCH-W2')
        single_location = WarehouseLocation.objects.create(zone=zone, location_number='SINGLE-W2')

        def payload(line, location_id):
            return dict(production_task_product_id=str(line.pk), expected_received_total=0,
                received_quantity=1, quantity_per_box=None, location_id=str(location_id),
                unit_id=str(line.unit_id), actual_color='黑色')

        batch_payload = {'items': [payload(self.line, self.location_id), payload(batch_line, batch_location.pk)]}
        single_payload = payload(single_line, single_location.pk)
        single_holds_warehouse, batch_started, batch_numbered = Event(), Event(), Event()
        worker = local()
        original_number = services.next_business_number
        number_order = []

        def synchronized_number(number_type, business_date=None):
            if number_type == 'FINISHED_GOODS_RECEIPT' and worker.kind == 'single':
                single_holds_warehouse.set()
                if not batch_started.wait(timeout=10):
                    raise AssertionError('批量收货线程未启动。')
                # 旧锁序下批量先取得流水再等 W2；修复后应在取号前等待 W2。
                batch_numbered.wait(timeout=2)
            number = original_number(number_type, business_date)
            if number_type == 'FINISHED_GOODS_RECEIPT':
                number_order.append(worker.kind)
                if worker.kind == 'batch':
                    batch_numbered.set()
            return number

        def run(kind):
            close_old_connections()
            worker.kind = kind
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                client = APIClient()
                client.force_authenticate(self.user)
                if kind == 'batch':
                    batch_started.set()
                    response = client.post('/api/v1/finished-goods-inventory/batch-receipts/', batch_payload, format='json')
                else:
                    response = client.post('/api/v1/finished-goods-inventory/receipts/', single_payload, format='json')
                return response.status_code, response.data
            finally:
                connections.close_all()

        with patch('apps.inventory.services.next_business_number', side_effect=synchronized_number):
            with ThreadPoolExecutor(max_workers=2) as pool:
                single_future = pool.submit(run, 'single')
                self.assertTrue(single_holds_warehouse.wait(timeout=10), '单笔收货未取得第二仓库锁。')
                batch_future = pool.submit(run, 'batch')
                single_status, single_data = single_future.result(timeout=25)
                batch_status, batch_data = batch_future.result(timeout=25)
        self.assertEqual(single_status, 201, single_data)
        self.assertEqual(batch_status, 201, batch_data)
        self.assertEqual(number_order, ['single', 'batch', 'batch'])
        self.assertEqual(FinishedGoodsReceipt.objects.count(), 3)
        self.assertEqual(FinishedGoodsReceipt.objects.values('receipt_number').distinct().count(), 3)
