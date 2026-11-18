"""真实隔离 Session/UI 的最小外发链；合成资料不代表正式业务验收。"""
import json
import os
import time
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boms.models import BomLine
from apps.boms.tests import test_part_flow_browser as browser_fixture
from apps.inventory.models import PublicStockMovement
from apps.inventory.part_flow_quantities import first_output_available
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.procurement.tracking_models import PurchaseTrackingPolicy
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from ..models import OutsourcingFactoryCraft, TubeOutsourcingOrder, TubeOutsourcingInput, TubePlanReceiptLine


@skipUnless(os.environ.get('BOM_PARTS_OUTSOURCING_BROWSER_QA') == '20261113', '仅显式启动本任务隔离页面检查')
@override_settings(ALLOWED_HOSTS=['*'], CSRF_TRUSTED_ORIGINS=['http://127.0.0.1:18517'],
    DEV_AUTO_LOGIN_ENABLED=False, MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True,
    SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PartFlowOutsourcingBrowserTests(D1Fixture, LiveServerTestCase):
    host, port = '0.0.0.0', 18516
    client_class = APIClient
    ordinary_role = browser_fixture.PartFlowBrowserTests.ordinary_role

    def setUp(self):
        self.assertEqual(connection.settings_dict['NAME'], 'test_bom_parts_20261113_a1d32c')
        PurchaseTrackingPolicy.objects.get_or_create(key='default')
        super().setUp()

    def test_create_partial_dispatch_and_unlimited_part_receipt(self):
        control = Path('/qa/outsourcing-browser-control')
        control.mkdir(parents=True, exist_ok=True)
        self.assertFalse(any(control.iterdir()), '控制目录存在文件，拒绝覆盖未知资料')
        ready, done = control / 'ready.json', control / 'done.json'
        try:
            ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
            SewingFixture.prepare_sewing(self)
            ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'OUT_UI_PIECE'})
            ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'OUT_UI_PART'})
            part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
                component_kind='SEWN_PART', part_name='隔离床面', unit='个', parts_per_product=1)
            for line in self.parts:
                line.component_kind, line.parent_part, line.pieces_per_part, line.unit = 'CUT_PIECE', part, 2, '片'
                line.cutting_pieces_per_set = line.cutting_sets_per_product = None
                line.fabric_meters_per_piece = line.fabric_meters_per_set = None
                line.save()
            workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
            cutting, _ = Craft.objects.get_or_create(plan_category='CUTTING', defaults={
                'name': '隔离页面裁剪', 'craft_type': 'INTERNAL', 'workshop': workshop, 'status': 'ACTIVE'})
            self.assertEqual((cutting.craft_type, cutting.workshop_id, cutting.status), ('INTERNAL', workshop.pk, 'ACTIVE'))
            ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
                craft=cutting, craft_type_snapshot='INTERNAL', craft_name_snapshot=cutting.name, plan_category='CUTTING')
            ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
                craft=self.external_sewing, craft_type_snapshot='EXTERNAL', craft_name_snapshot=self.external_sewing.name)
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.external_sewing,
                defaults={'craft_name_snapshot': self.external_sewing.name})
            auth = self.ordinary_role('OUTSOURCING', [f'outsourcing.{code}_outsourcingorder' for code in
                ('view', 'add', 'confirm_dispatch', 'confirm_return')])
            actor = get_user_model().objects.get(username=auth['username'])
            self.assertFalse(actor.is_superuser)
            self.assertFalse(actor.has_perm('production_tasks.view_productiontask'))
            self.client.force_authenticate(actor)
            options = self.client.get('/api/v1/tube-outsourcing-orders/options/', {'category': 'cutting'})
            self.assertEqual(options.status_code, 200, options.data)
            self.assertTrue(any(str(self.schedule_product.pk) == item['schedule_product_id']
                for task in options.data['data']['tasks'] for item in task['products']))
            source = self.client.get('/api/v1/tube-outsourcing-orders/source-context/', {
                'schedule_product_id': str(self.schedule_product.pk), 'source_kind': 'CUTTING',
                'craft_id': str(self.external_sewing.pk), 'is_plan': 'true'})
            self.assertEqual(source.status_code, 200, source.data)
            self.assertTrue(source.data['data']['ready'], source.data)
            before_available = first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity)
            payload = {'database': connection.settings_dict['NAME'], 'user': auth,
                'scheduleProductId': str(self.schedule_product.pk), 'craftId': str(self.external_sewing.pk),
                'partName': part.part_name, 'pieceName': self.parts[0].part_name,
                'otherPieceName': self.parts[1].part_name, 'factoryName': self.factory.name,
                'warehouseName': self.semi_zone.warehouse.warehouse_name, 'zoneName': self.semi_zone.zone_name,
                'date': str(timezone.localdate())}
            temporary = control / 'ready.tmp'
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            temporary.replace(ready)
            print('外发部位隔离页面资料已就绪，凭据不输出。', flush=True)
            deadline = time.monotonic() + 600
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.25)
            self.assertTrue(done.exists(), '等待后台页面检查超时')
            self.assertTrue(json.loads(done.read_text(encoding='utf-8')).get('passed'), '后台页面检查失败，见脱敏报告')
            order = TubeOutsourcingOrder.objects.get(is_plan=True, schedule_product=self.schedule_product)
            target = order.lines.get()
            self.assertEqual((target.bom_line_id, target.quantity, target.unit_price), (part.pk, 100, None))
            sent = TubeOutsourcingInput.objects.get(order__plan=order)
            self.assertEqual((sent.bom_line_id, sent.quantity, sent.source_kind), (self.parts[0].pk, 20, 'CUTTING'))
            self.assertEqual(first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity), before_available - 20)
            received = TubePlanReceiptLine.objects.get(receipt__order=order)
            self.assertEqual(received.received_quantity, 10001)
            movement = received.stock_movement
            self.assertEqual((movement.quantity, movement.balance.quantity, movement.balance.unit.unit_name), (10001, 10001, '个'))
            self.assertEqual(movement.balance.identity_snapshot['semi_kind'], 'SEWN_PART')
            self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
        finally:
            for path in (ready, done, control / 'ready.tmp', control / 'done.tmp'):
                path.unlink(missing_ok=True)
