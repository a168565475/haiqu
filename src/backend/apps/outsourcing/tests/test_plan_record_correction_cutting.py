"""裁片、旧/新目录辅料和共享池的总单更正回归。"""
import copy
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boms.models import BomLine, BomSection
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.models import MaterialStockMovement, PublicStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.sewing_processing_services import sewing_output_usage
from apps.inventory.stock_services import credit_material_stock
from apps.inventory.tests.test_sewing_processing_services import SewingProcessingFixture
from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.models import OrderMaterialRequirement
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit, ProductCategory
from ..models import OutsourcingFactoryCraft, TubeOutsourcingOrder
from ..plan_correction_stock import MATERIAL_SOURCE
from .test_plan_cutting_api import PlanCuttingApiTests
from .test_plan_record_corrections import CorrectionApiMixin
from .test_tube_orders_api import BASE


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PlanCuttingCorrectionTests(CorrectionApiMixin, SewingProcessingFixture, TestCase):
    context = PlanCuttingApiTests.context
    plan = PlanCuttingApiTests.plan
    dispatch = PlanCuttingApiTests.dispatch
    receive = PlanCuttingApiTests.receive

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.print_craft,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.print_craft.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.print_craft,
            defaults={'craft_name_snapshot': self.print_craft.name})

    def opening_cutting(self, quantity):
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        return credit_public_stock(identity=identity, zone=self.semi_zone, quantity=quantity,
            source_type='CORRECTION_CUTTING_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee, production_task=self.task, product_line=self.product_line, bom_line=self.parts[0]).balance

    def auxiliary(self, catalog):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'CORRECTION-AUX'})
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        selected = {}
        if catalog:
            item = MaterialCatalog.objects.create(category_key='AUXILIARY', template_key='TAPE', name='更正包边带')
            selected = {'schema_version': 1, 'catalog_id': str(item.pk), 'catalog_version': item.updated_at.isoformat(),
                'category_key': 'AUXILIARY', 'template_key': 'TAPE', 'name': item.name, 'scope': 'BASE',
                'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
                'attributes': {'material': '涤纶', 'width': '25mm', 'color': '黑色'},
                'unit_id': str(self.meter.pk), 'unit_name': '米', 'display_name': '更正包边带 / 米'}
            line = BomLine.objects.create(section=section, line_number=1, part_name='包边带', category='辅料',
                material='涤纶', specification='25mm', unit='米', unit_consumption='2', total_consumption='1000',
                material_catalog=item, material_selection_snapshot=selected)
            identity = build_catalog_stock_identity(material_catalog_id=item.pk, material_selection_snapshot=selected)
            stock = credit_public_stock(identity=identity, zone=self.zone, quantity=Decimal('100.5'),
                source_type='CORRECTION_AUX_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        else:
            category, _ = ProductCategory.objects.get_or_create(category_name='辅料', item_type='MATERIAL')
            raw = RawMaterialInformation.objects.create(material_number='CORRECTION-AUX', item_type='MATERIAL',
                category=category, unit=unit, material_name='更正扣件', material='塑料', specification='M6', color_snapshot='黑色')
            line = BomLine.objects.create(section=section, line_number=1, part_name='更正扣件', category='辅料',
                material='塑料', specification='M6', unit='个', unit_consumption='2', total_consumption='1000',
                raw_values={'source_inventory_material_id': str(raw.pk), 'accessory_color': '黑色'})
            stock = credit_material_stock(raw_material=raw, unit=unit, zone=self.zone, quantity=100,
                source_type='CORRECTION_AUX_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        entered = {'bom_line_id': str(line.pk), 'factory_id': str(self.factory.pk),
            'quantity': '20.25' if catalog else '20', 'zone_id': str(self.zone.pk)}
        return entered, stock

    def test_sewing_direct_changes_usage_without_stock_and_receipt_prevents_excess_reduction(self):
        order = self.dispatch(self.plan(), 100)
        changed = self.correct(order, self.correction_payload(order, quantity=150))
        self.assertEqual(sewing_output_usage(self.product_line.pk)[self.component]['dispatched'], 150)
        self.assertFalse(PublicStockMovement.objects.filter(source_type__startswith='TUBE_PLAN').exists())
        changed = self.receive(changed, 120)
        self.correct(changed, self.correction_payload(changed, quantity=119), expected=400)
        self.correct(changed, self.correction_payload(changed, operation='DELETE'), expected=400)

    def test_public_cutting_increase_decrease_delete_returns_saved_pool(self):
        stock = self.opening_cutting(100)
        order = self.dispatch(self.plan('PUBLIC_CUTTING'), 80, 'PUBLIC_CUTTING')
        self.correct(order, self.correction_payload(order, quantity=101), expected=409)
        changed = self.correct(order, self.correction_payload(order, quantity=90))
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 10)
        changed = self.correct(changed, self.correction_payload(changed, quantity=50))
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 50)
        self.correct(changed, self.correction_payload(changed, operation='DELETE'))
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 100)

    def test_public_cutting_increase_protects_other_pending_dispatch(self):
        stock = self.opening_cutting(100)
        order = self.dispatch(self.plan('PUBLIC_CUTTING'), 80, 'PUBLIC_CUTTING')
        response = self.client.get(BASE + 'source-context/', {'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'PUBLIC_CUTTING', 'craft_id': str(self.print_craft.pk), 'zone_id': str(self.semi_zone.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        context = response.data['data']
        response = self.client.post(BASE, {'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': 'PUBLIC_CUTTING',
            'craft_id': str(self.print_craft.pk), 'zone_id': str(self.semi_zone.pk),
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': '10', 'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.correct(order, self.correction_payload(order, quantity=95), expected=409)
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 20)
        self.correct(order, self.correction_payload(order, quantity=90))
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 10)

    def _check_auxiliary_delete(self, catalog):
        material, stock = self.auxiliary(catalog)
        opening = stock.quantity
        order = self.dispatch(self.plan(materials=[material]), 100, materials=[material])
        batch = TubeOutsourcingOrder.objects.get(pk=order['dispatch_records'][0]['id'])
        auxiliary = batch.materials.get()
        changed = self.correct(order, self.correction_payload(order, quantity=80))
        auxiliary.refresh_from_db(); stock.refresh_from_db()
        self.assertEqual(auxiliary.quantity, Decimal(material['quantity']))
        self.assertEqual(stock.quantity, opening - auxiliary.quantity)
        self.correct(changed, self.correction_payload(changed, operation='DELETE'))
        stock.refresh_from_db(); auxiliary.requirement.refresh_from_db()
        self.assertEqual(stock.quantity, opening)
        self.assertEqual(auxiliary.requirement.outsourcing_issued_quantity, 0)
        model = PublicStockMovement if catalog else MaterialStockMovement
        self.assertEqual(model.objects.filter(source_type=MATERIAL_SOURCE).count(), 1)
        self.assertTrue(batch.materials.filter(pk=auxiliary.pk).exists())

    def test_legacy_auxiliary_unchanged_on_update_and_restored_on_whole_delete(self):
        self._check_auxiliary_delete(False)

    def test_catalog_auxiliary_unchanged_on_update_and_restored_on_whole_delete(self):
        self._check_auxiliary_delete(True)

    def test_catalog_auxiliary_corrupt_snapshot_blocks_whole_delete_atomically(self):
        material, stock = self.auxiliary(True)
        order = self.dispatch(self.plan(materials=[material]), 100, materials=[material])
        batch = TubeOutsourcingOrder.objects.get(pk=order['dispatch_records'][0]['id'])
        auxiliary = batch.materials.get()
        auxiliary.material_selection_snapshot = copy.deepcopy(auxiliary.material_selection_snapshot)
        auxiliary.material_selection_snapshot['attributes']['color'] = '白色'
        auxiliary.save(update_fields=['material_selection_snapshot'])
        self.correct(order, self.correction_payload(order, operation='DELETE'), expected=409)
        batch.refresh_from_db(); stock.refresh_from_db()
        self.assertEqual(batch.status, 'PROCESSING')
        self.assertEqual(stock.quantity, Decimal('80.25'))
        self.assertFalse(PublicStockMovement.objects.filter(source_type=MATERIAL_SOURCE).exists())

    def test_multiple_components_sharing_stock_pool_use_combined_difference(self):
        first = self.parts[0]
        duplicate = BomLine.objects.get(pk=first.pk)
        duplicate.pk = None
        duplicate.line_number = 99
        duplicate.component_identity = uuid.uuid4()
        duplicate.save(force_insert=True)
        stock = self.opening_cutting(100)
        context = self.context('PUBLIC_CUTTING')
        wanted = [str(first.component_identity), str(duplicate.component_identity)]
        lines = [{'component_identity': key, 'quantity': '40', 'factory_id': str(self.factory.pk), 'unit_price': '1.25'} for key in wanted]
        response = self.client.post(BASE, {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'craft_id': str(self.print_craft.pk), 'source_kind': 'PUBLIC_CUTTING', 'zone_id': str(self.semi_zone.pk),
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()), 'lines': lines}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order = response.data['data']
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', {'client_request_id': str(uuid.uuid4()),
            'actual_dispatch_date': str(timezone.localdate()), 'source_kind': 'PUBLIC_CUTTING',
            'zone_id': str(self.semi_zone.pk), 'lines': lines}, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = response.data['data']
        self.correct(order, self.correction_payload(order, quantity=60), expected=409)
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 20)
        self.correct(order, self.correction_payload(order, quantity=50))
        stock.refresh_from_db(); self.assertEqual(stock.quantity, 0)
