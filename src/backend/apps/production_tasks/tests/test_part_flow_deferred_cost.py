"""真实隔离 API/数据库：先回货的部位总单不能把暂缓费用显示为完整。"""
import uuid

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.outsourcing.models import OutsourcingFactoryCraft, TubeOutsourcingOrder
from apps.outsourcing.tests import test_part_flow_plan_api as part_fixture
from apps.outsourcing.tests.test_plan_record_corrections import CorrectionApiMixin
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_tasks.cost_selectors import task_cost_summary
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop


class PartFlowCostFixture(CorrectionApiMixin, D1Fixture):
    part_context = part_fixture.PartFlowPlanApiTests.part_context
    create_part_plan = part_fixture.PartFlowPlanApiTests.create_part_plan
    dispatch_part = part_fixture.PartFlowPlanApiTests.dispatch_part
    receive_part = part_fixture.PartFlowPlanApiTests.receive_part

    def setUp(self):
        super().setUp()
        ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
        SewingFixture.prepare_sewing(self)
        ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'COST-PIECE'})
        ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'COST-PART'})
        self.part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
            component_kind='SEWN_PART', part_name='费用待定床面', unit='个', parts_per_product=1)
        for line in self.parts:
            line.component_kind, line.parent_part, line.pieces_per_part, line.unit = 'CUT_PIECE', self.part, 2, '片'
            line.cutting_pieces_per_set = line.cutting_sets_per_product = None
            line.fabric_meters_per_piece = line.fabric_meters_per_set = None
            line.save()
        workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
        cutting, _ = Craft.objects.get_or_create(plan_category='CUTTING', defaults={
            'name': '费用隔离裁剪', 'craft_type': 'INTERNAL', 'workshop': workshop, 'status': 'ACTIVE'})
        self.assertEqual((cutting.craft_type, cutting.workshop_id, cutting.status), ('INTERNAL', workshop.pk, 'ACTIVE'))
        self.finishing = [Craft.objects.get_or_create(craft_type='EXTERNAL', outsourcing_code=code,
            defaults={'name': name})[0] for code, name in (
                ('SCREEN_PRINTING', '费用隔离丝印'), ('EMBROIDERY', '费用隔离刺绣'))]
        for craft in [self.external_sewing, *self.finishing]:
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=craft,
                defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': craft.name})
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=craft,
                defaults={'craft_name_snapshot': craft.name})

    def as_legacy_plan(self, order):
        # 仅隔离夹具还原升级前总单；业务路径不允许改写历史回货价格。
        saved = TubeOutsourcingOrder.objects.get(pk=order['id'])
        snapshot = dict(saved.source_snapshot)
        snapshot.pop('billing_basis', None)
        snapshot['fees_deferred'] = True
        saved.source_snapshot = snapshot
        saved.save(update_fields=['source_snapshot'])
        saved.lines.update(unit_price=None)
        response = self.client.get(f"/api/v1/tube-outsourcing-orders/{saved.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class DeferredPartFlowCostTests(PartFlowCostFixture, APITestCase):
    def create_part_plan(self, source='CUTTING', craft=None):
        return self.as_legacy_plan(super().create_part_plan(source, craft, price='1.20'))

    def assert_cost_gap(self, expected, *, prefix=None):
        result = task_cost_summary(task=self.task)
        category = result['categories'][2]
        self.assertEqual((category['count'], category['missing_count']), (expected, expected), category)
        self.assertEqual(category['amount'], '0.00')
        if expected:
            self.assertFalse(result['complete'])
            self.assertIsNone(result['current_difference'])
            self.assertIsNone(result['cost_ratio'])
            self.assertTrue(all(row['amount'] is None and row['amount_cny'] is None for row in category['items']))
        if prefix:
            self.assertTrue(all(row['id'].startswith(prefix) for row in category['items']), category)

    def test_receipt_only_plan_has_one_gap_across_receipts_and_voids(self):
        order = self.create_part_plan()
        self.assert_cost_gap(0)
        order = self.receive_part(order, 10001)
        order = self.receive_part(order, 1)
        self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
        order = self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE'))
        self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
        self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE'))
        self.assert_cost_gap(0)

    def test_later_dispatch_replaces_receipt_gap_and_void_restores_it(self):
        order = self.receive_part(self.create_part_plan(), 10001)
        self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
        order, _ = self.dispatch_part(order, 20)
        self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:DEFERRED:')
        order = self.correct(order, self.correction_payload(order, operation='DELETE'))
        self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
        self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE'))
        self.assert_cost_gap(0)

    def test_printing_and_embroidery_receipt_only_gap_uses_existing_batch_fee_after_dispatch(self):
        for craft in self.finishing:
            with self.subTest(craft=craft.outsourcing_code):
                order = self.create_part_plan('SEWING', craft)
                self.assertFalse(order['sewing_inputs'])
                self.assert_cost_gap(0)
                order = self.receive_part(order, 10001)
                self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
                response = self.client.post(f"/api/v1/tube-outsourcing-orders/{order['id']}/plan-dispatch/", {
                    'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
                    'source_kind': 'SEWING', 'zone_id': None,
                    'lines': [{'component_identity': str(self.part.component_identity), 'quantity': '20',
                        'factory_id': str(self.factory.pk)}]}, format='json', HTTP_IF_MATCH=order['etag'])
                self.assertEqual(response.status_code, 200, response.data)
                order = response.data['data']
                self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:LINE:')
                order = self.correct(order, self.correction_payload(order, operation='DELETE'))
                self.assert_cost_gap(1, prefix='TUBE_OUTSOURCING:RECEIPT_ONLY:')
                self.correct(order, self.correction_payload(order, 'RECEIPT', operation='DELETE'))
                self.assert_cost_gap(0)
