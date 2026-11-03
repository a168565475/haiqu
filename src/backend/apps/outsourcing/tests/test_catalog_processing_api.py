"""新目录加工链的隔离数据库/API测试；不冒充真实员工Session验收。"""
from decimal import Decimal
from copy import deepcopy
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.models import PublicStockMovement, InternalSemiFinishedReceipt
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.catalog_stock_queries import available_catalog_balances
from apps.inventory.stock_services import InventoryStockValidationError
from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.public_semi_requirements import build_public_semi_specs
from apps.material_issues.catalog_requirements import catalog_requirement_specs
from apps.material_issues.models import MaterialIssue
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.tests import test_tube_d1_receipts as d1_fixture
from apps.boms.material_flow_calculations import pipe_plan_for_line
from apps.inventory.tests.test_sewing_processing_services import SewingProcessingFixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit
from django.utils import timezone
from rest_framework.test import APIClient
from ..models import OutsourcingFactoryCraft
from ..models import TubeOutsourcingOrder
from .test_plan_orders_api import PlanApiFixture
from . import test_plan_cutting_api as plan_cutting_tests


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class CatalogTubeProcessingApiTests(PlanApiFixture, APITestCase):
    def setUp(self):
        super().setUp()
        line = self.metal_bom_line
        self.catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='新目录加工管材')
        self.selected = {
            'schema_version': 1, 'catalog_id': str(self.catalog.pk), 'catalog_version': self.catalog.updated_at.isoformat(),
            'name': self.catalog.name, 'category_key': 'TUBE', 'template_key': 'TUBE', 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': line.material, 'shape': line.raw_values['tube_shape'],
                'section_size': line.raw_values['tube_diameter'], 'thickness': line.raw_values['tube_thickness'],
                'length': str(line.raw_bar_length_m)},
            'unit_id': str(self.root_unit.pk), 'unit_name': '根', 'display_name': '新目录加工管材 / 根',
        }
        line.material_catalog = self.catalog
        line.material_selection_snapshot = self.selected
        line.raw_values = {key: value for key, value in line.raw_values.items() if not key.startswith('source_')}
        line.raw_values['pipe_plan_version'] = 3
        line.unit = '根'
        plan = pipe_plan_for_line(line)
        line.raw_bar_length_m = Decimal(plan['raw_bar_length_m'])
        line.suggested_bar_count = plan['suggested_bar_count']
        line.suggested_purchase_meters = Decimal(plan['suggested_purchase_meters'])
        line.save(update_fields=['material_catalog', 'material_selection_snapshot', 'raw_values', 'unit',
            'raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters'])

    d1_preview = d1_fixture.D1Fixture.d1_preview
    d1_payload = d1_fixture.D1Fixture.d1_payload
    d1_post = d1_fixture.D1Fixture.d1_post

    def credit_catalog_roots(self, quantity=100, actual_length='5.05'):
        # 实际入库原长由本测试独立给定；不从目录属性或BOM计算结果补出。
        identity = build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.selected, raw_bar_length_m=actual_length)
        return credit_public_stock(identity=identity, zone=self.raw_zone, quantity=quantity,
            source_type='U5_CATALOG_ROOT_OPENING', source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee).balance

    def issue_catalog_roots(self, quantity='100'):
        # 旧夹具投入不能充当新材料实际投入，停用其状态后沿真实 API 重新领料。
        MaterialIssue.objects.filter(pk=self.issue_line.issue_id).update(status='RETURNED', issued_at=None)
        self.credit_catalog_roots()
        specs, blockers = catalog_requirement_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        payload = {'client_request_id': str(uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'METAL', 'production_task_id': str(self.task.pk), 'product_line_id': str(self.product_line.pk),
            'workshop_id': str(self.workshop.pk), 'recipient_workshop_employee_id': str(self.worker.pk),
            'issue_at': timezone.now().isoformat(), 'lines': [{'requirement_id': str(specs[0]['id']), 'requested_quantity': quantity}]}
        created = self.client.post('/api/v1/material-issues/', payload, format='json', HTTP_HOST='localhost')
        self.assertEqual(created.status_code, 201, created.data)
        identifier = created.data['data']['id']
        submitted = self.client.post(f'/api/v1/material-issues/{identifier}/submit/', {}, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        preview = self.client.post(f'/api/v1/material-issues/{identifier}/preview-issue/', {}, format='json', HTTP_HOST='localhost')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data['data']['can_confirm'], preview.data)
        confirmed = self.client.post(f'/api/v1/material-issues/{identifier}/confirm-issue/',
            {'request_id': str(uuid4())}, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        return MaterialIssue.objects.get(pk=identifier).lines.get()

    def test_catalog_root_dispatch_deducts_roots_and_receives_frozen_pieces(self):
        balance = self.credit_catalog_roots(30)
        order = self.plan('RAW_PIPE')
        self.assertEqual(order['lines'][0]['input_material_selection_snapshot']['unit_name'], '根')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(source='RAW_PIPE', quantity='250'))
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 5)
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_DISPATCH')
        self.assertEqual(movement.quantity, 25)
        self.assertEqual(movement.meter_quantity, Decimal('126.25'))
        self.assertEqual(Decimal(movement.snapshot['public_identity']['raw_bar_length_m']), Decimal('5.05'))
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '240'))
        returned = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(returned.quantity, 240)
        self.assertEqual(returned.snapshot['input_material_selection_snapshot']['unit_name'], '根')
        self.assertEqual(returned.snapshot['output_material_selection_snapshot']['unit_name'], '支')

    def test_catalog_raw_pipe_requires_exact_actual_length_pool(self):
        other = self.credit_catalog_roots(10, actual_length='6.00')
        order = self.plan('RAW_PIPE')
        before = (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count())
        self.write_plan(order, 'dispatch', self.dispatch_payload(source='RAW_PIPE', quantity='20'), expected=400)
        self.assertEqual((TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count()), before)
        exact = self.credit_catalog_roots(3, actual_length='5.05')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(source='RAW_PIPE', quantity='20'))
        exact.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((exact.quantity, exact.meter_quantity), (1, Decimal('5.05')))
        self.assertEqual((other.quantity, other.meter_quantity), (10, Decimal('60.00')))
        batch = TubeOutsourcingOrder.objects.get(pk=order['dispatch_records'][0]['id'])
        from apps.outsourcing.tube_receipt_selectors import dispatch_evidence_blockers
        self.assertEqual(dispatch_evidence_blockers(batch), [])
        saved = batch.lines.get()
        saved.input_identity['raw_bar_length_m'] = '6.00'
        saved.save(update_fields=['input_identity'])
        self.assertTrue(dispatch_evidence_blockers(batch))

    def test_catalog_first_metal_receipt_uses_actual_issue_and_saved_bom(self):
        issue_line = self.issue_catalog_roots()
        preview = self.d1_preview()
        self.assertEqual(preview['lines'][0]['can_receive'], '100')
        self.assertEqual(preview['lines'][0]['input_material_selection_snapshot'], self.selected)
        response = self.d1_post(self.d1_payload('40'), etag=preview['etag'])
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        confirmed = self.client.post(f'/api/v1/semi-finished-receipts/{receipt.pk}/confirm/', {}, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        saved_line = receipt.lines.get()
        self.assertEqual(saved_line.stock_movement.quantity, 40)
        self.assertEqual(saved_line.input_snapshot['catalog_inputs'][0]['issue_line_id'], str(issue_line.pk))
        self.assertEqual(saved_line.stock_movement.snapshot['input_material_selection_snapshot'], self.selected)
        self.assertEqual(saved_line.stock_movement.snapshot['output_material_selection_snapshot']['processing_stage'], 'METAL')
        from apps.inventory.notification_events import current_inventory_object
        self.assertIsNotNone(current_inventory_object('INTERNAL_SEMI_RECEIPT_CONFIRMED', receipt.pk))
        movement = saved_line.stock_movement
        PublicStockMovement.objects.filter(pk=movement.pk).update(source_type='U5_INVALID_SOURCE')
        self.assertIsNone(current_inventory_object('INTERNAL_SEMI_RECEIPT_CONFIRMED', receipt.pk))
        PublicStockMovement.objects.filter(pk=movement.pk).update(source_type=movement.source_type)
        self.assertEqual(self.d1_preview()['lines'][0]['can_receive'], '60')
        self.metal_bom_line.raw_values['tube_coating_color'] = '后来BOM改色'
        self.metal_bom_line.save(update_fields=['raw_values'])
        self.catalog.name = '后来目录改名'
        self.catalog.save(update_fields=['name'])
        self.assertEqual(self.d1_preview()['lines'][0]['output_material_selection_snapshot']['name'], self.selected['name'])
        direct = self.context('METAL')['rows'][0]
        self.assertFalse(direct['blockers'], direct)
        self.assertEqual(direct['output_material_selection_snapshot']['attributes']['color'], '黑色')
        self.assertEqual(direct['spray_color'], '黑色')

    def test_direct_plan_dispatch_receipts_freeze_two_stages_and_use_saved_output(self):
        order = self.plan('METAL')
        row = order['lines'][0]
        self.assertEqual(row['input_material_selection_snapshot']['processing_stage'], 'METAL')
        self.assertEqual(row['output_material_selection_snapshot']['processing_stage'], 'POWDER_COATING')
        self.assertEqual(row['output_material_selection_snapshot']['attributes']['length'], '500 mm')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='200'))
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '100'))
        saved = TubeOutsourcingOrder.objects.get(pk=order['id']).lines.get().output_material_selection_snapshot
        MaterialCatalog.objects.filter(pk=self.catalog.pk).update(name='目录后来改名')
        self.metal_bom_line.raw_values['tube_coating_color'] = '改色后不能覆盖旧回货'
        self.metal_bom_line.save(update_fields=['raw_values'])
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '100'))
        movements = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements.values('balance_id').distinct().count(), 1)
        self.assertEqual(movements.first().balance.quantity, Decimal(200))
        self.assertEqual(movements.first().balance.identity_snapshot['material_selection_snapshot'], saved)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())

    def test_public_semi_uses_new_identity_and_debits_actual_pool(self):
        context = self.plan_context('PUBLIC_SEMI')
        self.assertFalse(context['rows'][0]['blockers'], context['rows'][0]['blockers'])
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        balance = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=120,
            source_type='U5_TEST_CATALOG_OPENING', source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee).balance
        order = self.plan('PUBLIC_SEMI')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(source='PUBLIC_SEMI', quantity='100'))
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal(20))
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').get().balance_id, balance.pk)
        order = self.write_plan(order, 'receipt', self.receipt_payload(order, '100'))
        specs, blockers = build_public_semi_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        matching = [row for row in specs if row['completed_craft'].pk == self.spray.pk]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['identity']['stock_kind'], 'CATALOG_SEMI')

    def test_catalog_reservation_is_released_on_cancel_and_plan_does_not_reserve(self):
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        credit_public_stock(identity=identity, zone=self.semi_zone, quantity=120,
            source_type='U5_TEST_RESERVATION', source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
        saved = self.post_order(self.order_payload('PUBLIC_SEMI', '20')).data['data']
        query = dict(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=identity['identity_snapshot']['material_selection_snapshot'], zone_id=self.semi_zone.pk)
        balance = available_catalog_balances(**query)[0]
        self.assertEqual((balance['quantity'], balance['reserved_quantity'], balance['available_quantity']), (120, 20, 100))
        self.plan('PUBLIC_SEMI')
        self.assertEqual(available_catalog_balances(**query)[0]['reserved_quantity'], 20)
        response = self.client.post(f"/api/v1/tube-outsourcing-orders/{saved['id']}/cancel/",
            {'client_request_id': str(uuid4()), 'remark': '隔离取消预留'}, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=saved['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(available_catalog_balances(**query)[0]['available_quantity'], 120)

    def test_inconsistent_saved_material_fails_without_receipt_or_stock_write(self):
        order = self.plan('METAL')
        order = self.write_plan(order, 'dispatch', self.dispatch_payload(quantity='100'))
        line = TubeOutsourcingOrder.objects.get(pk=order['id']).lines.get()
        before = PublicStockMovement.objects.count()
        for field in ('input_material_selection_snapshot', 'output_material_selection_snapshot'):
            original = deepcopy(getattr(line, field))
            getattr(line, field)['attributes']['length'] = '999 mm'
            line.save(update_fields=[field])
            self.write_plan(order, 'receipt', self.receipt_payload(order, '10'), expected=400)
            self.assertEqual(PublicStockMovement.objects.count(), before)
            setattr(line, field, original)
            line.save(update_fields=[field])

    def use_kilogram_material(self):
        unit = ProductionUnit.objects.create(unit_name='公斤', unit_code='U5-KG')
        self.selected = {**self.selected, 'unit_id': str(unit.pk), 'unit_name': '公斤'}
        self.metal_bom_line.material_selection_snapshot = self.selected
        self.metal_bom_line.save(update_fields=['material_selection_snapshot'])

    def test_kilogram_new_plans_and_dispatch_fail_without_side_effects_but_saved_receipt_remains(self):
        prior = self.plan('METAL')
        prior = self.write_plan(prior, 'dispatch', self.dispatch_payload(quantity='100'))
        self.use_kilogram_material()
        before = (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count())
        for source in ('RAW_PIPE', 'PUBLIC_SEMI', 'METAL'):
            context = self.plan_context(source)
            self.assertIn('按公斤计量的管材暂不支持加工／外发。', context['rows'][0]['blockers'])
            response = self.post_order({'is_plan': True, 'client_request_id': str(uuid4()),
                'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
                'source_kind': source, 'zone_id': context['zone_id'], 'planned_dispatch_date': str(timezone.localdate()),
                'expected_return_date': str(timezone.localdate()), 'lines': [{'component_identity': self.component,
                    'quantity': '20', 'factory_id': str(self.factory.pk), 'unit_price': '1'}]}, expected=400)
            self.assertIn('按公斤计量', str(response.data))
        response = self.write_plan(prior, 'dispatch', self.dispatch_payload(quantity='20'), expected=400)
        self.assertIn('按公斤计量', str(response.data))
        self.assertEqual((TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count()), before)
        # 已保存原单回货仍按原来的支单位与加工身份，不用后来公斤BOM重算。
        self.write_plan(prior, 'receipt', self.receipt_payload(prior, '10'))
        self.assertEqual(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN').get().balance.unit.unit_name, '支')

    def test_kilogram_first_metal_receipt_rejected_without_partial_header(self):
        self.use_kilogram_material()
        query = {'schedule_product_id': str(self.schedule_product.pk), 'plan_category': 'METAL'}
        response = self.client.get('/api/v1/semi-finished-receipts/preview/', query, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        preview = response.data['data']
        self.assertIn('按公斤计量', str(preview))
        before = (InternalSemiFinishedReceipt.objects.count(), PublicStockMovement.objects.count())
        response = self.client.post('/api/v1/semi-finished-receipts/', {**query, 'request_id':str(uuid4()),
            'zone_id':str(self.semi_zone.pk), 'receipt_date':str(timezone.localdate()),
            'lines':[{'bom_line_id':str(self.metal_bom_line.pk),'quantity':'1'}]}, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('按公斤计量', str(response.data))
        self.assertEqual((InternalSemiFinishedReceipt.objects.count(), PublicStockMovement.objects.count()), before)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class CatalogCuttingProcessingApiTests(SewingProcessingFixture, APITestCase):
    context = plan_cutting_tests.PlanCuttingApiTests.context
    plan = plan_cutting_tests.PlanCuttingApiTests.plan
    dispatch = plan_cutting_tests.PlanCuttingApiTests.dispatch
    receive = plan_cutting_tests.PlanCuttingApiTests.receive

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.print_craft,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.print_craft.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.print_craft,
            defaults={'craft_name_snapshot': self.print_craft.name})
        fabric_catalog = MaterialCatalog.objects.create(category_key='FABRIC', template_key='FABRIC', name='新目录面料')
        self.catalog = MaterialCatalog.objects.create(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', name='新目录裁片')
        source = {'schema_version': 1, 'catalog_id': str(fabric_catalog.pk), 'catalog_version': fabric_catalog.updated_at.isoformat(),
            'category_key': 'FABRIC', 'template_key': 'FABRIC', 'name': fabric_catalog.name, 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '600D', 'fabric_spec': '150cm', 'width': '150cm', 'color': '蓝色'},
            'unit_id': str(self.meter.pk), 'unit_name': '米', 'display_name': '新目录面料 / 米'}
        self.fabric.material_catalog, self.fabric.material_selection_snapshot = fabric_catalog, source
        self.fabric.save(update_fields=['material_catalog', 'material_selection_snapshot'])
        for line in self.parts:
            line.material_catalog = self.catalog
            line.material_selection_snapshot = {**source, 'catalog_id': str(self.catalog.pk), 'name': self.catalog.name,
                'catalog_version': self.catalog.updated_at.isoformat(), 'category_key': 'FABRIC_SEMI', 'template_key': 'FABRIC_SEMI',
                'attributes': {'material': '600D', 'size': '50*40', 'color': '蓝色'},
                'processing_state': 'PROCESSED', 'processing_stage': 'SEWING', 'semi_kind': 'CUTTING',
                'completed_craft': {'id': str(self.external_sewing.pk), 'craft_type': 'EXTERNAL', 'code': 'SEWING'},
                'unit_id': str(self.set_unit.pk), 'unit_name': '套', 'display_name': '新目录裁片 / 套'}
            line.save(update_fields=['material_catalog', 'material_selection_snapshot'])

    def test_direct_cutting_preserves_input_sewing_and_output_printing(self):
        order = self.plan()
        row = order['lines'][0]
        self.assertEqual(row['input_material_selection_snapshot']['processing_stage'], 'SEWING')
        self.assertEqual(row['output_material_selection_snapshot']['processing_stage'], 'SCREEN_PRINTING')
        self.assertEqual(row['output_material_selection_snapshot']['fabric_material_selection_snapshot'], self.fabric.material_selection_snapshot)
        order = self.dispatch(order, 120)
        order = self.receive(order, 100)
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.balance.stock_kind, 'CATALOG_SEMI')
        self.assertEqual(movement.balance.identity_snapshot['pieces_per_set'], 2)
        self.assertEqual(movement.balance.quantity, Decimal(100))
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())

    def test_public_cutting_debits_saved_sewing_stock_and_credits_new_stage(self):
        order = self.plan('PUBLIC_CUTTING')
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        stock = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=80,
            source_type='U5_TEST_CATALOG_CUTTING_OPENING', source_id=uuid4(), source_line_id=uuid4(),
            actor_employee=self.employee).balance
        order = self.dispatch(order, 80, 'PUBLIC_CUTTING')
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 0)
        order = self.receive(order, 75)
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.balance.identity_snapshot['completed_craft']['id'], str(self.print_craft.pk))
        self.assertNotEqual(movement.balance.identity_key, stock.identity_key)

    def test_catalog_sewing_credit_cannot_bypass_direct_output_usage(self):
        # U3 v5公共门禁回归：已经直发的套数仍占首次产出，不因CATALOG_SEMI跳过。
        order = self.plan()
        self.dispatch(order, 500)
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        before = PublicStockMovement.objects.count()
        with self.assertRaises(InventoryStockValidationError) as caught:
            credit_public_stock(identity=identity, zone=self.semi_zone, quantity=1,
                source_type='INTERNAL_SEMI_RECEIPT', source_id=uuid4(), source_line_id=uuid4(),
                actor_employee=self.employee, production_task=self.task, product_line=self.product_line, bom_line=self.parts[0])
        self.assertEqual(caught.exception.api_error_code, 'INTERNAL_RECEIPT_DEMAND_EXCEEDED')
        self.assertEqual(PublicStockMovement.objects.count(), before)
