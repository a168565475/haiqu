"""新目录随单辅料：公共库存实扣、预留、原单快照和整单回滚。"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.boms.models import BomLine, BomSection
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.models import PublicStockMovement, MaterialStockMovement
from apps.inventory.public_stock_services import credit_public_stock, debit_public_stock
from apps.inventory.tests import test_sewing_processing_services as sewing_tests
from apps.inventory.tests import test_catalog_sewing_inputs as catalog_sewing_tests
from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.catalog_requirements import catalog_requirement_rows
from apps.material_issues.models import OrderMaterialRequirement
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft
from ..models import OutsourcingFactoryCraft, TubeOutsourcingOrder
from ..tube_materials import MOVEMENT_SOURCE, material_dispatch_blockers
from . import test_plan_cutting_api as plan_tests


BASE = '/api/v1/tube-outsourcing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class CatalogAuxiliaryInputTests(sewing_tests.SewingProcessingFixture, TestCase):
    context = plan_tests.PlanCuttingApiTests.context
    plan = plan_tests.PlanCuttingApiTests.plan
    dispatch = plan_tests.PlanCuttingApiTests.dispatch
    receive = plan_tests.PlanCuttingApiTests.receive

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        catalog_sewing_tests.prepare_catalog_sewing(self)
        self.crafts = [self.print_craft, self.external_sewing]
        embroidery, _ = Craft.objects.get_or_create(outsourcing_code='EMBROIDERY',
            defaults={'name': '目录裁片刺绣', 'craft_type': 'EXTERNAL'})
        self.crafts.append(embroidery)
        for craft in self.crafts:
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=craft,
                defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': craft.name})
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=craft,
                defaults={'craft_name_snapshot': craft.name})
        self.auxiliary_catalog = MaterialCatalog.objects.create(category_key='AUXILIARY', template_key='TAPE', name='目录包边带')
        self.selected = {'schema_version': 1, 'catalog_id': str(self.auxiliary_catalog.pk),
            'catalog_version': self.auxiliary_catalog.updated_at.isoformat(), 'category_key': 'AUXILIARY',
            'template_key': 'TAPE', 'name': self.auxiliary_catalog.name, 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '涤纶', 'width': '25mm', 'color': '黑色'},
            'unit_id': str(self.meter.pk), 'unit_name': '米', 'display_name': '目录包边带 / 米'}
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        self.auxiliary = BomLine.objects.create(section=section, line_number=1, part_name='包边带',
            category='辅料', material='涤纶', specification='25mm', unit='米', unit_consumption='2',
            total_consumption='1000', material_catalog=self.auxiliary_catalog, material_selection_snapshot=self.selected)

    def entered(self, quantity):
        return {'bom_line_id': str(self.auxiliary.pk), 'factory_id': str(self.factory.pk),
                'quantity': str(quantity), 'zone_id': str(self.zone.pk)}

    def opening(self, quantity):
        identity = build_catalog_stock_identity(material_catalog_id=self.auxiliary_catalog.pk,
            material_selection_snapshot=self.selected)
        return credit_public_stock(identity=identity, zone=self.zone, quantity=Decimal(str(quantity)),
            source_type='U5_TEST_CATALOG_AUXILIARY', source_id=uuid4(), source_line_id=uuid4(),
            actor_employee=self.employee).balance

    def pending_context(self):
        response = self.client.get(BASE + 'source-context/', {'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'SEWING', 'craft_id': str(self.print_craft.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def pending_order(self, quantity):
        context = self.pending_context()
        response = self.client.post(BASE, {'client_request_id': str(uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'SEWING', 'craft_id': str(self.print_craft.pk), 'zone_id': None,
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': '10', 'factory_id': str(self.factory.pk)}],
            'material_source_revision': context['material_source_revision'], 'materials': [self.entered(quantity)]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data']

    def action(self, order, kind, expected=200):
        payload = {'client_request_id': str(uuid4())}
        if kind == 'dispatch':
            payload['actual_dispatch_date'] = str(timezone.localdate())
        response = self.client.post(BASE + order['id'] + '/' + kind + '/', payload,
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def test_plan_does_not_reserve_and_batches_debit_saved_decimal_units(self):
        order = self.plan(materials=[self.entered('1200.25')])
        stock = self.opening('1300.5')
        order = self.dispatch(order, 100, materials=[self.entered('1200.25')])
        order = self.dispatch(order, 10, materials=[self.entered('50.125')])
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('50.125'))
        requirement = OrderMaterialRequirement.objects.get(material_catalog=self.auxiliary_catalog)
        self.assertEqual(requirement.outsourcing_issued_quantity, Decimal('1250.375'))
        self.assertEqual(requirement.required_quantity, 1000)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type=MOVEMENT_SOURCE).exists())
        movements = PublicStockMovement.objects.filter(source_type=MOVEMENT_SOURCE)
        self.assertEqual(movements.count(), 2)
        self.assertTrue(all(row.snapshot['material_selection_snapshot'] == self.selected for row in movements))
        actual = [row for batch in order['dispatch_records'] for row in batch['materials']]
        self.assertTrue(all(row['material_selection_snapshot'] == self.selected and row['unit'] == '米' for row in actual))
        order = self.receive(order, 100)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('50.125'))

    def test_pending_catalog_material_reserves_public_stock_and_order_quota_then_cancel_releases(self):
        self.report((200, 300))
        stock = self.opening(100)
        order = self.pending_order('20.5')
        row = next(row for row in self.pending_context()['material_rows'] if row['bom_line_id'] == str(self.auxiliary.pk))
        self.assertEqual((Decimal(row['available_stock']), Decimal(row['order_remaining'])), (Decimal('79.5'), Decimal('979.5')))
        issue_rows, blockers = catalog_requirement_rows(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        issue_row = next(row for row in issue_rows if row['material_catalog_id'] == str(self.auxiliary_catalog.pk))
        self.assertEqual(Decimal(issue_row['public_pending_quantity']), Decimal('20.5'))
        with self.assertRaises(ValidationError):
            debit_public_stock(balance_id=stock.pk, quantity=80, source_type='U5_TEST_OTHER_CONSUMER',
                source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
        self.action(order, 'cancel')
        row = next(row for row in self.pending_context()['material_rows'] if row['bom_line_id'] == str(self.auxiliary.pk))
        self.assertEqual((Decimal(row['available_stock']), Decimal(row['order_remaining'])), (100, 1000))

    def test_dispatch_freezes_catalog_and_real_movement_and_receipt_does_not_redebit(self):
        self.report((200, 300))
        stock = self.opening(100)
        order = self.pending_order('20.25')
        self.auxiliary_catalog.name = '目录后来改名'
        self.auxiliary_catalog.archived_at = timezone.now()
        self.auxiliary_catalog.save(update_fields=['name', 'archived_at'])
        order = self.action(order, 'dispatch').data['data']
        model = TubeOutsourcingOrder.objects.get(pk=order['id'])
        material = model.materials.get()
        self.assertIsNone(material.raw_material_id)
        self.assertEqual(material.material_selection_snapshot, self.selected)
        self.assertEqual(material_dispatch_blockers(model, model.actions.get(kind='DISPATCH')), [])
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('79.75'))
        response = self.client.post(BASE + order['id'] + '/confirm-receipt/', {
            'client_request_id': str(uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': order['lines'][0]['id'],
                'received_quantity': '10', 'zone_id': str(self.semi_zone.pk)}]}, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 201, response.data)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('79.75'))

    def test_failed_catalog_debit_rolls_back_order_and_frozen_material_movement(self):
        self.report((200, 300))
        stock = self.opening(100)
        order = self.pending_order(20)
        with patch('apps.outsourcing.tube_materials.debit_public_stock', side_effect=RuntimeError('隔离测试扣库失败')):
            with self.assertRaises(RuntimeError):
                self.action(order, 'dispatch')
        model = TubeOutsourcingOrder.objects.get(pk=order['id'])
        self.assertEqual(model.status, 'PENDING_DISPATCH')
        self.assertFalse(model.actions.exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type=MOVEMENT_SOURCE).exists())
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 100)
        self.action(order, 'dispatch')

    def test_changed_saved_auxiliary_snapshot_is_not_silently_replaced(self):
        self.report((200, 300))
        stock = self.opening(100)
        order = self.pending_order(20)
        self.auxiliary.material_selection_snapshot = deepcopy(self.selected)
        self.auxiliary.material_selection_snapshot['attributes']['color'] = '白色'
        self.auxiliary.save(update_fields=['material_selection_snapshot'])
        self.action(order, 'dispatch', expected=409)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 100)
        self.assertFalse(PublicStockMovement.objects.filter(source_type=MOVEMENT_SOURCE).exists())

    def test_kilogram_auxiliary_is_not_blocked_as_kilogram_tube(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='公斤', defaults={'unit_code': 'U5-AUX-KG'})
        self.selected = {**self.selected, 'unit_id': str(unit.pk), 'unit_name': '公斤', 'display_name': '目录包边带 / 公斤'}
        self.auxiliary.unit = '公斤'
        self.auxiliary.material_selection_snapshot = self.selected
        self.auxiliary.save(update_fields=['unit', 'material_selection_snapshot'])
        stock = self.opening('10.5')
        order = self.plan(materials=[self.entered('2.25')])
        self.dispatch(order, 10, materials=[self.entered('2.25')])
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('8.25'))

    def test_existing_cutting_crafts_keep_catalog_input_and_actual_output_stage(self):
        original = self.print_craft
        for craft in self.crafts:
            with self.subTest(craft=craft.outsourcing_code):
                self.print_craft = craft
                order = self.plan()
                order = self.dispatch(order, 10)
                self.receive(order, 10)
                movement = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN',
                    balance__identity_snapshot__completed_craft__id=str(craft.pk)).get()
                self.assertEqual(movement.balance.stock_kind, 'CATALOG_SEMI')
                self.assertEqual(movement.snapshot['input_material_selection_snapshot']['processing_stage'], 'SEWING')
                self.assertEqual(movement.snapshot['output_material_selection_snapshot']['processing_stage'], craft.outsourcing_code)
        self.print_craft = original
