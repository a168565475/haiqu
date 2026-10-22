from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from apps.inventory.models import FinishedGoodsReceipt, FinishedGoodsReceiptStatus
from apps.products.models import ProductInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit
from apps.workshop_reporting.models import WorkReport, WorkReportLine
from .test_assembly_receipts import AssemblyFixture


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

    def race(self):
        barrier = Barrier(2)
        preview_etag = self.preview()['etag']
        report_url = f'/api/v1/workshop-reporting/work-reports/{self.report.pk}/'
        report_etag = self.client.get(report_url)['ETag']
        edit = dict(schedule_product_id=str(self.plan.pk), scheme_id=str(self.assembly_scheme.pk),
            scheme_revision=self.assembly_scheme.revision, production_date=str(timezone.localdate()),
            lines=[dict(scheme_line_id=str(self.report_line.scheme_line_id),
                workshop_employee_id=str(self.report_line.workshop_employee_id), quantity='600', production_line=1)])
        new_payload = self.payload(received_quantity=700)
        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                client = APIClient(); client.force_authenticate(self.user)
                barrier.wait(timeout=10)
                if action == 'edit':
                    response = client.patch(report_url, edit, format='json', HTTP_IF_MATCH=report_etag)
                else:
                    response = client.post('/api/v1/assembly-finished-receipts/', new_payload, format='json', HTTP_IF_MATCH=preview_etag)
                return response.status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipt_future = pool.submit(run, 'receipt'); edit_future = pool.submit(run, 'edit')
            receipt_status, edit_status = receipt_future.result(timeout=25), edit_future.result(timeout=25)
        received = sum(FinishedGoodsReceipt.objects.filter(status=FinishedGoodsReceiptStatus.CONFIRMED)
                       .values_list('received_quantity', flat=True))
        reported = WorkReportLine.objects.get(report=self.report).quantity
        self.assertLessEqual(received, reported)
        self.assertIn((receipt_status, edit_status), [(201,200),(201,400),(400,200),(412,200)])

    def test_assembly_receipt_and_report_reduction_share_product_lock(self):
        self.race()
