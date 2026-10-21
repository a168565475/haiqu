"""裁片复用外发单的真实数据库链路；仅在隔离测试库运行。"""
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.boms.models import BomLine, BomSection
from apps.inventory.models import PublicStockMovement, PublicStockBalance, MaterialStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.stock_services import credit_material_stock
from apps.inventory.tests import test_sewing_processing_services as sewing_fixture
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.workshop_config.models import Craft
from apps.workshop_reporting.models import WorkReportLine
from ..models import (OutsourcingFactoryCraft, OutsourcingOrder, OutsourcingOrderProduct,
    OutsourcingProcessingItem, TubeOutsourcingOrder, TubeOutsourcingReceipt)


BASE = '/api/v1/tube-outsourcing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class CuttingTubeOrdersTests(sewing_fixture.SewingProcessingFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.embroidery, _ = Craft.objects.get_or_create(outsourcing_code='EMBROIDERY',
            defaults={'craft_type': 'EXTERNAL', 'name': '测试刺绣'})
        self.cut_craft, _ = Craft.objects.get_or_create(outsourcing_code='CUTTING',
            defaults={'craft_type': 'EXTERNAL', 'name': '测试裁剪'})
        for craft in (self.print_craft, self.embroidery, self.cut_craft, self.external_sewing):
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=craft,
                defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': craft.name})
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=craft,
                defaults={'craft_name_snapshot': craft.name})

    def context(self, source='SEWING', craft=None):
        query = {'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
                 'craft_id': str((craft or self.print_craft).pk)}
        if source == 'PUBLIC_CUTTING':
            query['zone_id'] = str(self.semi_zone.pk)
        response = self.client.get(BASE + 'source-context/', query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def payload(self, source='SEWING', quantity='50', craft=None):
        context = self.context(source, craft)
        return {'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'craft_id': context['craft_id'], 'zone_id': context['zone_id'],
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': self.component, 'quantity': quantity,
                       'factory_id': str(self.factory.pk), 'unit_price': '1.25'}]}

    def create(self, payload, status=201):
        response = self.client.post(BASE, payload, format='json')
        self.assertEqual(response.status_code, status, response.data)
        return response

    def act(self, detail, action, *, payload=None, status=200):
        data = payload or {'client_request_id': str(uuid.uuid4())}
        if action == 'dispatch':
            data.setdefault('actual_dispatch_date', str(timezone.localdate()))
        response = self.client.post(BASE + detail['id'] + '/' + action + '/', data,
            format='json', HTTP_IF_MATCH=detail['etag'])
        self.assertEqual(response.status_code, status, response.data)
        return response

    def stock(self, quantity=100):
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.external_sewing, unit=self.set_unit)
        return credit_public_stock(identity=identity, zone=self.semi_zone, quantity=quantity,
            source_type='OUTSOURCING_RETURN', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee, production_task=self.task, product_line=self.product_line,
            bom_line=self.parts[0]).balance

    def test_options_filter_crafts_and_require_explicit_cutting_craft(self):
        response = self.client.get(BASE + 'options/', {'category': 'cutting'})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual({row['value'] for row in data['source_kinds']}, {'SEWING', 'PUBLIC_CUTTING'})
        self.assertEqual({row['outsourcing_code'] for row in data['crafts']},
                         {'SCREEN_PRINTING', 'EMBROIDERY', 'CUTTING', 'SEWING'})
        self.assertEqual(self.client.get(BASE + 'source-context/', {'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'SEWING'}).status_code, 400)
        payload = self.payload()
        spray, _ = Craft.objects.get_or_create(outsourcing_code='POWDER_COATING',
            defaults={'craft_type': 'EXTERNAL', 'name': '测试喷塑'})
        payload['craft_id'] = str(spray.pk)
        self.create(payload, 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_no_report_or_missing_required_operation_cannot_dispatch(self):
        context = self.context()
        row = next(row for row in context['rows'] if row['component_identity'] == self.component)
        self.assertEqual(Decimal(row['max_quantity']), 0)
        self.create(self.payload(quantity='1'), 400)
        self.report((200, 0))
        self.create(self.payload(quantity='1'), 400)
        self.assertFalse(TubeOutsourcingOrder.objects.exists())

    def test_shared_save_reserves_sets_replay_and_cancel_release(self):
        self.report((200, 300))
        payload = self.payload(quantity='80')
        response = self.create(payload)
        self.assertEqual(response.data['data']['output_unit'], '套')
        self.assertEqual(response.data['data']['lines'][0]['current_reported_minimum'], '150')
        self.assertEqual({row['quantity'] for row in response.data['data']['lines'][0]['operations']}, {'200', '150'})
        self.create(payload, 200)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 1)
        row = next(row for row in self.context()['rows'] if row['component_identity'] == self.component)
        self.assertEqual(Decimal(row['max_quantity']), 70)
        self.create(self.payload(quantity='71'), 400)
        self.act(response.data['data'], 'cancel')
        self.create(self.payload(quantity='150'))

    def test_direct_dispatch_has_no_fake_stock_and_receipt_uses_selected_craft(self):
        self.report((200, 300))
        response = self.create(self.payload(quantity='50', craft=self.embroidery))
        dispatched = self.act(response.data['data'], 'dispatch').data['data']
        order = TubeOutsourcingOrder.objects.get(pk=dispatched['id'])
        self.assertFalse(PublicStockMovement.objects.filter(source_id=order.pk, direction='OUT').exists())
        entry = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': dispatched['lines'][0]['id'],
            'received_quantity': '48', 'shortage_reason': '少回2套', 'zone_id': str(self.semi_zone.pk)}]}
        received = self.act(dispatched, 'confirm-receipt', payload=entry, status=201).data['data']
        self.assertEqual((received['output_unit'], received['total_received_quantity']), ('套', '48'))
        self.assertEqual(PublicStockBalance.objects.get(identity_snapshot__completed_craft__code='EMBROIDERY').quantity, 48)
        self.act(dispatched, 'confirm-receipt', payload=entry)
        self.assertEqual(TubeOutsourcingReceipt.objects.count(), 1)
        self.assertEqual(self.component_limit()['allowance']['dispatched'], 50)

    def test_stock_source_reservation_debit_and_receipt_do_not_restore_first_output(self):
        self.report((200, 300))
        balance = self.stock(100)
        detail = self.create(self.payload('PUBLIC_CUTTING', quantity='70')).data['data']
        self.assertEqual(self.component_limit()['allowance']['remaining'], 50)
        row = next(row for row in self.context('PUBLIC_CUTTING')['rows'] if row['component_identity'] == self.component)
        self.assertEqual(Decimal(row['max_quantity']), 30)
        dispatched = self.act(detail, 'dispatch').data['data']
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 30)
        self.assertEqual(self.component_limit()['allowance']['remaining'], 50)
        movement = PublicStockMovement.objects.get(source_id=detail['id'], direction='OUT')
        self.assertEqual(movement.quantity, 70)
        entry = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': dispatched['lines'][0]['id'],
            'received_quantity': '68', 'shortage_reason': '少回2套', 'zone_id': str(self.semi_zone.pk)}]}
        received = self.act(dispatched, 'confirm-receipt', payload=entry, status=201).data['data']
        self.assertEqual(received['total_received_quantity'], '68')
        output = PublicStockBalance.objects.get(identity_snapshot__completed_craft__code='SCREEN_PRINTING')
        self.assertEqual(output.quantity, 68)
        self.assertEqual({key: value for key, value in output.identity_snapshot.items() if key != 'completed_craft'},
                         {key: value for key, value in balance.identity_snapshot.items() if key != 'completed_craft'})
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 30)
        self.assertEqual(self.component_limit()['allowance']['remaining'], 50)

    def assert_cutting_and_sewing_round_trips(self, source):
        self.report((500, 1000))
        if source == 'PUBLIC_CUTTING':
            self.stock(100)
        input_identity = build_semi_finished_identity(bom_line=self.parts[0],
            completed_craft=self.external_sewing, unit=self.set_unit)['identity_snapshot']
        for craft in (self.cut_craft, self.external_sewing):
            with self.subTest(source=source, craft=craft.outsourcing_code):
                detail = self.create(self.payload(source, quantity='50', craft=craft)).data['data']
                self.assertEqual((detail['source_kind'], detail['craft_id'], detail['output_unit']),
                                 (source, str(craft.pk), '套'))
                order = TubeOutsourcingOrder.objects.get(pk=detail['id'])
                if source == 'PUBLIC_CUTTING':
                    self.assertEqual(order.lines.get().input_identity['identity_snapshot']['completed_craft']['code'], 'SEWING')
                dispatched = self.act(detail, 'dispatch').data['data']
                self.assertEqual(PublicStockMovement.objects.filter(source_id=order.pk, direction='OUT').count(),
                                 1 if source == 'PUBLIC_CUTTING' else 0)
                before = self.component_limit()['allowance'].copy()
                entry = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
                    'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': dispatched['lines'][0]['id'],
                    'received_quantity': '50', 'shortage_reason': '', 'zone_id': str(self.semi_zone.pk)}]}
                received = self.act(dispatched, 'confirm-receipt', payload=entry, status=201).data['data']
                self.assertEqual((received['output_unit'], received['total_received_quantity']), ('套', '50'))
                movement = PublicStockMovement.objects.get(source_id=received['id'], source_type='TUBE_OUTSOURCING_RETURN')
                output_identity = movement.balance.identity_snapshot
                self.assertEqual((output_identity['completed_craft']['code'], output_identity['unit_name']),
                                 (craft.outsourcing_code, '套'))
                self.assertEqual({key: value for key, value in output_identity.items() if key != 'completed_craft'},
                                 {key: value for key, value in input_identity.items() if key != 'completed_craft'})
                after = self.component_limit()['allowance']
                self.assertEqual({key: after[key] for key in ('received', 'dispatched', 'reserved', 'used', 'remaining')},
                                 {key: before[key] for key in ('received', 'dispatched', 'reserved', 'used', 'remaining')})

    def test_cutting_and_sewing_direct_dispatch_and_return_keep_first_output_usage(self):
        self.assert_cutting_and_sewing_round_trips('SEWING')

    def test_cutting_and_sewing_stock_dispatch_and_return_keep_first_output_usage(self):
        self.assert_cutting_and_sewing_round_trips('PUBLIC_CUTTING')

    def test_legacy_first_output_is_excluded_but_new_four_crafts_share_processing_quota(self):
        self.report((500, 1000))
        for craft, quantity in ((self.cut_craft, 500), (self.external_sewing, 500),
                                (self.print_craft, 100), (self.embroidery, 100)):
            legacy = OutsourcingOrder.objects.create(order_number=f'CUT-LEGACY-{craft.outsourcing_code}',
                schedule=self.schedule_product.schedule, craft=craft, craft_name_snapshot=craft.name,
                craft_code_snapshot=craft.outsourcing_code, delivery_date=timezone.localdate(),
                source_revision_hash='a'*64, client_request_id=uuid.uuid4(), request_payload_hash='b'*64,
                created_by_employee=self.employee, updated_by_employee=self.employee)
            product = OutsourcingOrderProduct.objects.create(order=legacy, schedule_product=self.schedule_product,
                bom=self.bom, line_number=1, order_quantity_snapshot=500, planned_quantity_snapshot=500,
                bom_number_snapshot=self.bom.bom_number, bom_version_snapshot=self.bom.version_number,
                source_revision_hash='c'*64)
            OutsourcingProcessingItem.objects.create(order_product=product, bom_line=self.parts[0],
                component_key=self.component, line_number=1, quantity=quantity, unit=self.set_unit, unit_snapshot='套')
        row = next(row for row in self.context()['rows'] if row['component_identity'] == self.component)
        self.assertFalse(row['blockers'], row)
        self.assertEqual(Decimal(row['max_quantity']), 300)
        for craft, quantity, remaining in ((self.cut_craft, '100', 200), (self.external_sewing, '100', 100),
                                           (self.print_craft, '50', 50), (self.embroidery, '50', 0)):
            self.create(self.payload(quantity=quantity, craft=craft))
            row = next(row for row in self.context()['rows'] if row['component_identity'] == self.component)
            self.assertEqual(Decimal(row['max_quantity']), remaining)
        self.assertEqual(OutsourcingOrder.objects.count(), 4)
        self.assertEqual(TubeOutsourcingOrder.objects.count(), 4)

    def test_stale_report_rechecked_at_dispatch_rolls_back_entire_action(self):
        self.report((200, 300))
        detail = self.create(self.payload(quantity='100')).data['data']
        WorkReportLine.objects.filter(work_item=self.items[1]).update(quantity=100)
        self.act(detail, 'dispatch', status=400)
        order = TubeOutsourcingOrder.objects.get(pk=detail['id'])
        self.assertEqual(order.status, 'PENDING_DISPATCH')
        self.assertFalse(order.actions.exists())

    def test_stock_history_conflict_includes_current_order_reservation(self):
        balance = self.stock(100)
        detail = self.create(self.payload('PUBLIC_CUTTING', quantity='70')).data['data']
        stale_payload = self.payload('PUBLIC_CUTTING', quantity='1')
        # 模拟历史库存被其他入口改少，当前待发预留仍为70套。
        PublicStockBalance.objects.filter(pk=balance.pk).update(quantity=30)
        row = next(row for row in self.context('PUBLIC_CUTTING')['rows'] if row['component_identity'] == self.component)
        self.assertEqual(row['max_quantity'], '0')
        self.assertTrue(any('历史待发预留70套超过来源库区现存30' in value for value in row['blockers']))
        stale = self.create(stale_payload, 412)
        self.assertIn('历史待发预留70套', str(stale.data))
        saved = self.create(self.payload('PUBLIC_CUTTING', quantity='1'), 400)
        self.assertIn('历史待发预留70套', str(saved.data))
        dispatched = self.act(detail, 'dispatch', status=400)
        self.assertIn('历史待发预留70套', str(dispatched.data))
        order = TubeOutsourcingOrder.objects.get(pk=detail['id'])
        self.assertEqual(order.status, 'PENDING_DISPATCH')
        self.assertFalse(order.actions.exists())
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 30)

    def test_order_history_conflict_includes_current_order_allocation(self):
        self.stock(100)
        detail = self.create(self.payload('PUBLIC_CUTTING', quantity='70')).data['data']
        # 模拟历史订单及确认BOM已减量，保留原外发占用，不自动回写历史单。
        self.schedule_product.planned_quantity = 50
        self.schedule_product.save(update_fields=['planned_quantity'])
        self.product_line.quantity = 50
        self.product_line.save(update_fields=['quantity'])
        self.schedule_product.source_quantity_snapshot = 50
        self.schedule_product.save(update_fields=['source_quantity_snapshot'])
        self.bom.order_quantity = 50
        self.bom.save(update_fields=['order_quantity'])
        row = next(row for row in self.context('PUBLIC_CUTTING')['rows'] if row['component_identity'] == self.component)
        self.assertEqual(row['max_quantity'], '0')
        self.assertTrue(any('历史裁片加工占用70套超过订单需求50套' in value for value in row['blockers']))
        saved = self.create(self.payload('PUBLIC_CUTTING', quantity='1'), 400)
        self.assertIn('历史裁片加工占用70套', str(saved.data))
        dispatched = self.act(detail, 'dispatch', status=400)
        self.assertIn('历史裁片加工占用70套', str(dispatched.data))
        order = TubeOutsourcingOrder.objects.get(pk=detail['id'])
        self.assertEqual(order.status, 'PENDING_DISPATCH')
        self.assertEqual(order.lines.get().quantity, 70)
        self.assertFalse(order.actions.exists())

    def test_invalid_quantity_frozen_attribute_and_other_stage_never_pass(self):
        self.report((200, 300))
        for quantity in ['1.5', '-1', True]:
            with self.subTest(quantity=quantity):
                self.create(self.payload(quantity=quantity), 400)
        payload = self.payload()
        self.parts[0].specification = '60*40'
        self.parts[0].save(update_fields=['specification'])
        self.create(payload, 412)
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=self.print_craft, unit=self.set_unit)
        credit_public_stock(identity=identity, zone=self.semi_zone, quantity=100,
            source_type='TEST_CUTTING_OTHER_STAGE', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        row = next(row for row in self.context('PUBLIC_CUTTING')['rows'] if row['component_identity'] == self.component)
        self.assertEqual(Decimal(row['max_quantity']), 0)

    def test_receipt_candidates_keep_cutting_separate_from_default_tube(self):
        self.report((200, 300))
        detail = self.create(self.payload()).data['data']
        self.act(detail, 'dispatch')
        response = self.client.get(BASE + 'receipt-candidates/', {'category': 'cutting'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['total'], 1)
        response = self.client.get(BASE + 'receipt-candidates/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['total'], 0)

    def test_auxiliary_uses_own_units_and_dispatch_failure_rolls_back_stock_and_status(self):
        self.report((200, 300))
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'CUTTING-AUX-COUNT'})
        category, _ = ProductCategory.objects.get_or_create(category_name='辅料', item_type='MATERIAL')
        raw = RawMaterialInformation.objects.create(material_number='CUTTING-AUX-001', item_type='MATERIAL',
            category=category, unit=unit, material_name='裁片随单扣件', material='塑料', specification='M6', color_snapshot='黑色')
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        line = BomLine.objects.create(section=section, line_number=1, part_name='裁片随单扣件', category='辅料',
            material='塑料', specification='M6', unit='个', unit_consumption='2', total_consumption='1000',
            raw_values={'source_inventory_material_id': str(raw.pk), 'accessory_color': '黑色'})
        stock = credit_material_stock(raw_material=raw, unit=unit, zone=self.zone, quantity=100,
            source_type='TEST_CUTTING_AUXILIARY', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        context = self.context()
        material = next(row for row in context['material_rows'] if row['bom_line_id'] == str(line.pk))
        self.assertEqual((material['unit'], material['color']), ('个', '黑色'))
        payload = self.payload()
        payload.update(material_source_revision=context['material_source_revision'], materials=[{
            'bom_line_id': str(line.pk), 'factory_id': str(self.factory.pk), 'quantity': '20', 'zone_id': str(self.zone.pk)}])
        detail = self.create(payload).data['data']
        with patch('apps.outsourcing.tube_materials.debit_material_stock', side_effect=RuntimeError('验证整单回滚')):
            with self.assertRaises(RuntimeError):
                self.act(detail, 'dispatch')
        order = TubeOutsourcingOrder.objects.get(pk=detail['id'])
        self.assertEqual(order.status, 'PENDING_DISPATCH')
        self.assertFalse(order.actions.exists())
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 100)
        dispatched = self.act(detail, 'dispatch').data['data']
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 80)
        entry = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': dispatched['lines'][0]['id'],
            'received_quantity': '50', 'shortage_reason': '', 'zone_id': str(self.semi_zone.pk)}]}
        received = self.act(dispatched, 'confirm-receipt', payload=entry, status=201).data['data']
        self.assertEqual(len(received['lines']), 1)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 80)
        self.assertFalse(MaterialStockMovement.objects.filter(source_id=order.pk, direction='IN').exists())
