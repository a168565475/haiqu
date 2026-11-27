from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.boms.models import BomSectionType
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, Supplier
from apps.procurement.purchase_scope import PACKAGING_PERMISSION
from apps.procurement.tracking_rules import BEIJING, beijing_today

from . import test_purchase_groups as groups
from . import test_tracking_queries as tracking


@override_settings(PURCHASE_TRACKING_ENABLED=False)
class PurchaseWorkbenchTests(APITestCase):
    make_task = groups.PurchaseGroupApiTests.make_task
    make_product_line = groups.PurchaseGroupApiTests.make_product_line
    make_bom = groups.PurchaseGroupApiTests.make_bom
    get_source = groups.PurchaseGroupApiTests.get_source
    detail = groups.PurchaseGroupApiTests.detail
    batch = groups.PurchaseGroupApiTests.batch
    batch_payload = groups.PurchaseGroupApiTests.batch_payload
    schedule = tracking.TrackingQueryTests.schedule
    inbound = tracking.TrackingQueryTests.inbound
    extra_set_component = groups.PurchaseGroupApiTests.extra_set_component
    setUp = groups.PurchaseGroupApiTests.setUp
    base = '/api/v1/purchase-tracking/workbench'

    def get(self, suffix='', **query):
        response = self.client.get(f'{self.base}{suffix}/', query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_wholly_unpurchased_task_partial_materials_and_pagination(self):
        other = self.make_product_line(self.task, line_number=2)
        self.make_bom(other, section_type=BomSectionType.ACCESSORY, budget_quantity='30')
        self.batch('5', confirm=False)
        overview = self.get()['data']['counts']
        self.assertEqual((overview['unstarted'], overview['shortage']), (1, 2))
        unstarted = self.get('-items', category='unstarted')['data']
        self.assertEqual([(row['task_number'], row['material_count']) for row in unstarted], [(self.task.task_number, 2)])
        first = self.get('-items', category='shortage', page_size=1)
        second = self.get('-items', category='shortage', page_size=1, page=2)
        self.assertEqual(first['meta']['total'], 2)
        self.assertNotEqual(first['data'][0]['row_key'], second['data'][0]['row_key'])
        self.batch('40')
        counts = self.get()['data']['counts']
        self.assertEqual((counts['unstarted'], counts['shortage']), (0, 2))
        self.bom_line.budget_quantity = '150'
        self.bom_line.save(update_fields=['budget_quantity'])
        self.assertEqual(self.get()['data']['counts']['bom_changed'], 1)
        self.make_product_line(self.task, line_number=3)
        self.assertEqual(self.get()['data']['availability_reasons']['shortage'], '另有 1 项需求量待核对')

    def test_delivery_queues_partial_receipt_and_schedule_comparison(self):
        today = beijing_today()
        batches = [self.batch('20') for _ in range(4)]
        for batch, days in zip(batches, (-1, 0, 2, None)):
            PurchaseOrderLine.objects.filter(purchase_order_id=batch['id']).update(
                delivery_date=today + timedelta(days=days) if days is not None else None)
        self.inbound(batches[0], '7')
        overview = self.get()['data']
        for category in ('near_due', 'due_today', 'overdue', 'missing_due'):
            self.assertEqual(overview['counts'][category], 1, category)
        self.assertIsNone(overview['counts']['late_for_use'])
        self.assertEqual(overview['missing_use_date_count'], 3)
        rows = self.get('-items', category='overdue')['data']
        self.assertEqual([Decimal(row['unreceived_quantity']) for row in rows], [Decimal('13')])
        plan = self.schedule()
        plan.material_inbound_date = today
        plan.save(update_fields=['material_inbound_date'])
        self.assertEqual(self.get()['data']['counts']['late_for_use'], 1)
        late = self.get('-items', category='late_for_use')['data']
        self.assertEqual(late[0]['material_inbound_date'], today.isoformat())

    def test_confirmation_period_price_gaps_trend_and_historical_packaging(self):
        batches = [self.batch('10', confirm=False) for _ in range(5)]
        self.batch('10', confirm=False)
        # 模拟既有确认记录及无审计日期的历史导入，审计日志仅追加。
        for batch, month in zip(batches, (3, 4, 4, 4, 5)):
            PurchaseOrder.objects.filter(pk=batch['id']).update(status='SUBMITTED')
            if batch != batches[3]:
                AuditLog.objects.create(object_type='PURCHASE_ORDER', object_id=batch['id'], action='CONFIRMED',
                    occurred_at=datetime(2026, month, 1, tzinfo=BEIJING), actor_employee=self.employee)
        PurchaseOrderLine.objects.filter(purchase_order_id=batches[1]['id']).update(amount=None, unit_price=None)
        PurchaseOrderLine.objects.filter(purchase_order_id=batches[2]['id']).update(section_title_snapshot=' 包材类 ')
        data = self.get('-spend', period='quarter', date='2026-04-02')['data']
        self.assertEqual((data['start_date'], data['end_date'], data['unknown_date_count']), ('2026-04-01','2026-04-02',1))
        bucket, = data['currencies']
        self.assertEqual((bucket['currency'], Decimal(bucket['amount']), bucket['order_count'], bucket['line_count'],
            bucket['supplier_count'], bucket['unpriced_count']), ('CNY', 0, 1, 1, 1, 1))
        self.assertEqual(len(bucket['trend']), 12)
        self.assertEqual(Decimal(bucket['trend'][2]['amount']), 20)
        self.assertEqual((bucket['trend'][3]['line_count'], bucket['trend'][3]['unpriced_count']), (1, 1))
        self.assertEqual((bucket['trend'][0]['line_count'], bucket['trend'][0]['unpriced_count']), (0, 0))
        self.assertEqual(bucket['suppliers'][0]['supplier_name'], self.supplier.supplier_name)
        self.assertEqual(Decimal(self.get('-spend', period='year', date='2026-12-01')['data']['currencies'][0]['amount']), 40)

    def test_split_supplier_batch_set_pricing_and_separate_currencies(self):
        child = self.extra_set_component('套内配件', tape=True)
        separate = self.extra_set_component('另购五金')
        second_supplier = Supplier.objects.create(supplier_number='GYS90003', supplier_name='五金采购',
            supplier_type='MATERIAL', supplier_categories=['HARDWARE'], payment_cycle='MONTHLY', phone='13800000003')
        session = str(uuid4())
        url = f'/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/'
        payload = self.batch_payload('20', batch_session_id=session)
        anchor = payload['lines'][0]
        anchor.update(unit_price=None, set_pricing={'anchor_id': self.line_id, 'quantity': 2, 'unit_price': '5'})
        payload['lines'].append({**anchor, 'purchase_group_line_id': child})
        first = self.client.post(url, payload, format='json', HTTP_IF_MATCH=self.detail()['ETag'])
        self.assertEqual(first.status_code, 201, first.data)
        second = self.batch_payload('10', batch_session_id=session)
        second['lines'][0].update(purchase_group_line_id=separate, supplier_id=str(second_supplier.pk))
        response = self.client.post(url, second, format='json', HTTP_IF_MATCH=self.detail()['ETag'])
        self.assertEqual(response.status_code, 201, response.data)
        # 现行确认只收人民币；模拟历史外币单据以覆盖原币汇总边界。
        foreign = self.batch('1')
        PurchaseOrder.objects.filter(pk=foreign['id']).update(currency=self.sales_currency, currency_code_snapshot='USD')
        by_currency = {row['currency']: row for row in self.get('-spend')['data']['currencies']}
        cny = by_currency['CNY']
        self.assertEqual((Decimal(cny['amount']), cny['unpriced_count'], cny['line_count'], cny['order_count']), (30, 0, 3, 1))
        self.assertEqual([Decimal(row['amount']) for row in cny['suppliers']], [20, 10])
        self.assertEqual(Decimal(by_currency['USD']['amount']), 2)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_permission_scope_for_every_endpoint_and_invalid_filters(self):
        self.batch('10')
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        role = RoleProfile.objects.create(role_code='WB-PACK', display_name='跟单', auth_group=Group.objects.create(name='wb-pack'))
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        app, code = PACKAGING_PERMISSION.split('.')
        RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(content_type__app_label=app, codename=code), scope='FOLLOWED')
        for suffix in ('/', '-spend/', '-items/?category=shortage'):
            self.assertEqual(self.client.get(self.base + suffix).status_code, 403)
        RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(content_type__app_label='procurement',
            codename='view_purchaseorder'), scope='FOLLOWED')
        self.assertEqual(self.get()['data']['counts']['shortage'], 0)
        self.assertEqual(self.get('-items', category='shortage')['meta']['total'], 0)
        self.assertEqual(self.get('-spend')['data']['currencies'], [])
        self.task.followers.add(self.employee)
        self.assertEqual(self.get()['data']['counts']['shortage'], 1)
        self.assertEqual(len(self.get('-spend')['data']['currencies']), 1)
        for suffix in ('/?purchase_scope=PACKAGING', '-items/?category=bad', '-items/?category=shortage&page=0',
                       '-spend/?period=bad', '-spend/?date=2026-02-31'):
            self.assertEqual(self.client.get(self.base + suffix).status_code, 400)
