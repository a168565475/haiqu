"""裁片总单、真实库存及辅料补发的隔离数据库测试。"""
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boms.models import BomLine, BomSection
from apps.inventory.models import PublicStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.sewing_processing_services import sewing_output_usage, assert_sewing_reports_cover_usage
from apps.inventory.stock_services import credit_material_stock
from apps.inventory.tests.test_sewing_processing_services import SewingProcessingFixture
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit, ProductCategory
from ..models import OutsourcingFactoryCraft

BASE = '/api/v1/tube-outsourcing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PlanCuttingApiTests(SewingProcessingFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.print_craft,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.print_craft.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.print_craft,
            defaults={'craft_name_snapshot': self.print_craft.name})

    def context(self, source='SEWING', order=None):
        query = {'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'craft_id': str(self.print_craft.pk), 'zone_id': str(self.semi_zone.pk) if source == 'PUBLIC_CUTTING' else None}
        query['plan_id' if order else 'is_plan'] = order['id'] if order else 'true'
        if query['zone_id'] is None:
            query.pop('zone_id')
        response = self.client.get(BASE + 'source-context/', query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def plan(self, source='SEWING', materials=None, expected=201):
        context = self.context(source)
        self.assertEqual(context['rows'][0]['order_required'], '500')
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'craft_id': str(self.print_craft.pk),
            'source_kind': source, 'zone_id': context['zone_id'], 'planned_dispatch_date': str(timezone.localdate()),
            'expected_return_date': str(timezone.localdate()), 'lines': [
                {'component_identity': self.component, 'quantity': '600', 'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}
        if materials is not None:
            payload.update(materials=materials, material_source_revision=context['material_source_revision'])
        response = self.client.post(BASE, payload, format='json')
        self.assertEqual(response.status_code, expected, response.data)
        return response.data['data'] if expected == 201 else response

    def dispatch(self, order, quantity, source='SEWING', materials=None, expected=200):
        context = self.context(source, order)
        payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': source, 'zone_id': context['zone_id'], 'lines': [{'component_identity': self.component,
                'quantity': str(quantity), 'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}
        if materials:
            payload.update(materials=materials, material_source_revision=context['material_source_revision'])
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response.data['data'] if expected == 200 else response

    def receive(self, order, quantity):
        response = self.client.post(BASE + order['id'] + '/plan-receipt/', {
            'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': order['lines'][0]['id'],
                'received_quantity': str(quantity), 'zone_id': str(self.semi_zone.pk)}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_direct_cutting_without_reports_replenishes_and_receives_in_sets(self):
        order = self.plan()
        self.assertEqual(order['plan_summary']['bom_quantity'], '500')
        self.assertEqual(order['plan_summary']['planned_quantity'], '600')
        self.assertEqual(sewing_output_usage(self.product_line.pk)[self.component]['reserved'], 0)
        for quantity in (300, 300):
            order = self.dispatch(order, quantity)
        response = self.dispatch(order, 1, expected=400)
        self.assertIn('本次最多可发0套', str(response.data))
        order = self.receive(order, 550)
        self.assertEqual(order['output_unit'], '套')
        self.assertEqual(order['plan_summary']['receipt_progress'], 100)
        self.assertEqual(order['lines'][0]['receivable_quantity'], '50')
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
        movement = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(movement.balance.unit_id, self.set_unit.pk)
        self.assertEqual(movement.balance.identity_snapshot['completed_craft']['id'], str(self.print_craft.pk))
        self.assertEqual(sewing_output_usage(self.product_line.pk)[self.component]['dispatched'], 600)
        assert_sewing_reports_cover_usage(self.product_line.pk)

    def test_cutting_receipt_can_exceed_dispatch_and_continue_after_target(self):
        order = self.dispatch(self.plan(), 100)
        order = self.receive(order, 10001)
        self.assertEqual(order['plan_summary']['received_quantity'], '10001')
        self.assertEqual(order['plan_summary']['receipt_progress'], 100)
        self.assertEqual(order['status'], 'COMPLETED')
        order = self.receive(order, 1)
        self.assertEqual(order['plan_summary']['received_quantity'], '10002')
        self.assertEqual(sewing_output_usage(self.product_line.pk)[self.component]['dispatched'], 100)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())

    def test_stock_cutting_plan_can_precede_stock_and_only_actual_dispatch_debits(self):
        order = self.plan('PUBLIC_CUTTING')
        self.dispatch(order, 1, 'PUBLIC_CUTTING', expected=400)
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        stock = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=100,
            source_type='OUTSOURCING_RETURN', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee, production_task=self.task, product_line=self.product_line, bom_line=self.parts[0]).balance
        order = self.dispatch(order, 80, 'PUBLIC_CUTTING')
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 20)
        order = self.receive(order, 70)
        self.assertEqual(order['plan_summary']['received_quantity'], '70')
        self.assertEqual(sewing_output_usage(self.product_line.pk)[self.component]['received'], 100)

    def test_auxiliary_plan_does_not_reserve_and_replenishment_uses_actual_stock(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'PLAN-AUX-COUNT'})
        category, _ = ProductCategory.objects.get_or_create(category_name='辅料', item_type='MATERIAL')
        raw = RawMaterialInformation.objects.create(material_number='PLAN-AUX-001', item_type='MATERIAL',
            category=category, unit=unit, material_name='随单扣件', material='塑料', specification='M6', color_snapshot='黑色')
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        line = BomLine.objects.create(section=section, line_number=1, part_name='随单扣件', category='辅料',
            material='塑料', specification='M6', unit='个', unit_consumption='2', total_consumption='1000',
            raw_values={'source_inventory_material_id': str(raw.pk), 'accessory_color': '黑色'})
        material = {'bom_line_id': str(line.pk), 'factory_id': str(self.factory.pk), 'quantity': '1200'}
        order = self.plan(materials=[material])
        self.assertEqual(len(order['planned_materials']), 1)
        self.assertNotIn('zone_id', order['planned_materials'][0])
        self.assertEqual({key: order['planned_materials'][0][key] for key in ('specification', 'material', 'color')},
                         {'specification': 'M6', 'material': '塑料', 'color': '黑色'})
        self.dispatch(order, 100, materials=[material], expected=400)
        material['zone_id'] = str(self.zone.pk)
        stock = credit_material_stock(raw_material=raw, unit=unit, zone=self.zone, quantity=1300,
            source_type='TEST_PLAN_AUXILIARY', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        order = self.dispatch(order, 100, materials=[material])
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 100)
        material['quantity'] = '50'
        order = self.dispatch(order, 10, materials=[material])
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 50)
        self.assertEqual(Decimal(order['planned_materials'][0]['quantity']), 1200)
        actual_materials = [row for record in order['dispatch_records'] for row in record['materials']]
        self.assertEqual(sorted(Decimal(row['quantity']) for row in actual_materials), [50, 1200])
        self.assertTrue(all(row['unit'] == '个' and row['factory_name'] == self.factory.name
            and row['zone_name'] == self.zone.zone_name for row in actual_materials))
        from apps.material_issues.requirements import sync_order_requirements
        from apps.material_issues.models import OrderMaterialRequirement
        from ..tube_materials import tube_material_context
        sync_order_requirements(self.task.pk)
        requirement = OrderMaterialRequirement.objects.get(production_task=self.task, raw_material=raw)
        self.assertEqual(requirement.required_quantity, 1000)
        self.assertEqual(requirement.outsourcing_issued_quantity, 1250)
        line.specification = 'M8'
        line.material = '新材质'
        line.raw_values['accessory_color'] = '新颜色'
        line.save(update_fields=['specification', 'material', 'raw_values'])
        reloaded = self.client.get(BASE + order['id'] + '/')
        self.assertEqual(reloaded.status_code, 200, reloaded.data)
        self.assertEqual({key: reloaded.data['data']['planned_materials'][0][key]
                          for key in ('specification', 'material', 'color')},
                         {'specification': 'M6', 'material': '塑料', 'color': '黑色'})
        old_context = tube_material_context(self.schedule_product, source_kind='SEWING')
        old_row = next(row for row in old_context['material_rows'] if row['bom_line_id'] == str(line.pk))
        self.assertEqual(Decimal(old_row['max_quantity']), 0)
        material['quantity'] = '51'
        response = self.dispatch(order, 1, materials=[material], expected=409)
        self.assertIn('可用库存', str(response.data))
        stock.refresh_from_db()
        requirement.refresh_from_db()
        self.assertEqual(stock.quantity, 50)
        self.assertEqual(requirement.outsourcing_issued_quantity, 1250)
