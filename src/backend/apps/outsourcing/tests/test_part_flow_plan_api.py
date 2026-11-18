"""真实隔离数据库：裁片投入、部位回货、分次补发与原费用隔离。"""
import uuid
from types import SimpleNamespace
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.boms.models import BomLine, BomSection
from apps.inventory.models import PublicStockMovement, WarehouseZone
from apps.inventory.part_flow_quantities import first_output_available
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.outsourcing.models import OutsourcingFactoryCraft, TubeOutsourcingInput, TubeOutsourcingOrder

BASE = '/api/v1/tube-outsourcing-orders/'


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PartFlowPlanApiTests(ScopedActorMixin, D1Fixture, APITestCase):
    def setUp(self):
        super().setUp()
        ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
        SewingFixture.prepare_sewing(self)
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'PFTPIECE'})
        self.part_unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'PFTPART'})
        self.cut_craft = Craft.objects.create(name='部位厂内裁剪', craft_type='INTERNAL',
            plan_category='CUTTING', workshop=self.workshop, status='ACTIVE')
        self.part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
            component_kind='SEWN_PART', part_name='床面', unit='个', parts_per_product=1)
        for line in self.parts:
            line.component_kind = 'CUT_PIECE'
            line.parent_part = self.part
            line.pieces_per_part = 2
            line.unit = '片'
            line.cutting_pieces_per_set = line.cutting_sets_per_product = None
            line.fabric_meters_per_piece = line.fabric_meters_per_set = None
            line.save()
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        cotton = BomLine.objects.create(section=section, line_number=1, part_name='无胶棉', material='无胶棉',
            specification='200g', unit='米', raw_values={'accessory_color': '白色'})
        self.cotton = BomLine.objects.create(section=self.part.section, line_number=4, component_kind='CUT_PIECE',
            parent_part=self.part, pieces_per_part=1, unit='片', part_name='床面棉片', specification='50*40', fabric_source_line=cotton)
        self.print_craft = Craft.objects.create(name='部位丝印', craft_type='EXTERNAL', outsourcing_code='SCREEN_PRINTING')
        for craft in (self.external_sewing, self.print_craft):
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=craft,
                defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': craft.name})
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=craft, defaults={'craft_name_snapshot': craft.name})

    def part_context(self, source='CUTTING', craft=None, order=None):
        query = {'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'craft_id': str((craft or self.external_sewing).pk),
            'plan_id' if order else 'is_plan': order['id'] if order else 'true'}
        if source.startswith('PUBLIC_'):
            query['zone_id'] = str(self.semi_zone.pk)
        response = self.client.get(BASE + 'source-context/', query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_demand_category_loads_sewing_and_printing_targets_without_sources(self):
        for craft, source, sewing in ((self.external_sewing, 'CUTTING', True), (self.print_craft, 'SEWING', False)):
            with self.subTest(craft=craft.outsourcing_code):
                response = self.client.get(BASE + 'source-context/', {
                    'schedule_product_id': str(self.schedule_product.pk), 'category': 'cutting',
                    'craft_id': str(craft.pk), 'is_plan': 'true'})
                self.assertEqual(response.status_code, 200, response.data)
                context = response.data['data']
                self.assertTrue(context['ready'], context['blockers'])
                self.assertEqual(context['source_kind'], source)
                self.assertIsNone(context['zone_id'])
                self.assertEqual(context['sewing_inputs'], sewing)
                self.assertEqual(context['rows'][0]['bom_line_id'], str(self.part.pk))
                self.assertEqual(context['rows'][0]['order_required'], '100')

    def create_part_plan(self, source='CUTTING', craft=None, price='1.20', expected=201):
        context = self.part_context(source, craft)
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'craft_id': str((craft or self.external_sewing).pk), 'zone_id': context['zone_id'],
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': str(self.part.component_identity), 'quantity': '100',
                'factory_id': str(self.factory.pk), 'unit_price': price}]}
        response = self.client.post(BASE, payload, format='json')
        self.assertEqual(response.status_code, expected, response.data)
        return response.data.get('data')

    def dispatch_part(self, order, quantity, source='CUTTING', piece=None):
        row = {'component_identity': str((piece or self.parts[0]).component_identity), 'quantity': str(quantity)}
        payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': source, 'zone_id': str(self.semi_zone.pk) if source.startswith('PUBLIC_') else None,
            'inputs': [row]}
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data'], payload

    def receive_part(self, order, quantity):
        payload = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{'order_line_id': order['lines'][0]['id'],
            'received_quantity': str(quantity), 'zone_id': str(self.semi_zone.pk)}]}
        response = self.client.post(BASE + order['id'] + '/plan-receipt/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    @override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
        SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_sewing_workshop_scope_can_create_and_dispatch_cutting_without_stock_grant(self):
        workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
        self.cut_craft.workshop = workshop
        self.cut_craft.save(update_fields=['workshop'])
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
            craft=self.cut_craft, craft_type_snapshot='INTERNAL',
            craft_name_snapshot=self.cut_craft.name, plan_category='CUTTING')
        self.scoped_actor()
        for permission in ('view_outsourcingorder', 'add_outsourcingorder', 'confirm_dispatch_outsourcingorder'):
            self.grant('outsourcing.' + permission, 'WORKSHOP', [workshop])
        self.assertFalse(self.scope_user.is_superuser)
        self.assertFalse(self.scope_user.has_perm('production_tasks.view_productiontask'))
        response = self.client.get(BASE + 'options/', {'category': 'cutting'})
        self.assertEqual(response.status_code, 200, response.data)
        sources = {row['value'] for row in response.data['data']['source_kinds']}
        self.assertIn('CUTTING', sources)
        self.assertNotIn('PUBLIC_PIECE', sources)
        order = self.create_part_plan()
        order, _ = self.dispatch_part(order, 20)
        self.assertEqual(order['dispatch_records'][0]['lines'][0]['quantity'], '20')
        self.assertTrue(all('stock_zones' not in row for row in self.part_context(order=order)['inputs']))
        response = self.client.get(BASE + 'source-context/', {
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': 'PUBLIC_PIECE',
            'craft_id': str(self.external_sewing.pk), 'zone_id': str(self.semi_zone.pk), 'is_plan': 'true'})
        self.assertEqual(response.status_code, 403, response.data)

    def test_direct_shortage_shows_current_stock_zones_without_changing_dispatch_revision(self):
        order, _ = self.dispatch_part(self.create_part_plan(), 20)
        before = self.part_context(order=order)
        piece = self.parts[0]
        identity = build_semi_finished_identity(bom_line=piece, completed_craft=component_stock_craft('CUTTING'), unit=self.piece_unit)
        other_zone = WarehouseZone.objects.create(warehouse=self.semi_zone.warehouse, zone_name='备用裁片区')
        for zone, quantity in [(self.semi_zone, 30), (other_zone, 5)]:
            credit_public_stock(identity=identity, zone=zone, quantity=quantity,
                source_type='TEST_PART_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
        context = self.part_context(order=order)
        self.assertEqual(context['source_revision'], before['source_revision'])
        row = next(row for row in context['inputs'] if row['bom_line_id'] == str(piece.pk))
        self.assertEqual({stock['zone_id']: Decimal(stock['available_quantity']) for stock in row['stock_zones']},
            {str(self.semi_zone.pk): 30, str(other_zone.pk): 5})
        stock_row = next(row for row in self.part_context('PUBLIC_PIECE', order=order)['inputs']
            if row['bom_line_id'] == str(piece.pk))
        self.assertEqual(Decimal(stock_row['max_quantity']), 30)
        self.assertTrue(all('stock_zones' not in row for row in context['inputs'] if row['bom_line_id'] != str(piece.pk)))

    def test_partial_direct_pieces_and_cotton_return_only_parts_without_receipt_cap(self):
        context = self.part_context()
        self.assertNotIn(str(self.cotton.fabric_source_line_id), {row['bom_line_id'] for row in context['material_rows']})
        initial = first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity)
        order = self.create_part_plan()
        self.assertEqual(order['lines'][0]['unit'], '个')
        self.assertEqual(order['planned_amount'], '120.00')
        self.assertEqual(len(order['inputs']), 3)
        self.assertFalse(TubeOutsourcingInput.objects.exists())
        order, payload = self.dispatch_part(order, 20)
        self.assertEqual(first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity), initial-20)
        replay = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(TubeOutsourcingInput.objects.count(), 1)
        order, _ = self.dispatch_part(order, 1, piece=self.cotton)
        order = self.receive_part(order, 10001)
        order = self.receive_part(order, 1)
        self.assertEqual(order['lines'][0]['received_quantity'], '10002')
        self.assertEqual(order['lines'][0]['dispatched_quantity'], '0')
        returns = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(returns.count(), 2)
        self.assertEqual({row.balance.identity_snapshot['semi_kind'] for row in returns}, {'SEWN_PART'})
        self.assertEqual({row.balance.unit_id for row in returns}, {self.part_unit.pk})
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())

    def test_stock_pieces_debit_without_first_output_recount_and_dispatch_can_be_reduced(self):
        order = self.create_part_plan('PUBLIC_PIECE')
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=component_stock_craft('CUTTING'), unit=self.piece_unit)
        balance = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=30,
            source_type='TEST_PART_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        available = first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity)
        order, _ = self.dispatch_part(order, 20, 'PUBLIC_PIECE')
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 10)
        self.assertEqual(first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity), available)
        order = self.receive_part(order, 10001)
        record = order['dispatch_records'][0]
        correction = {'client_request_id': str(uuid.uuid4()), 'record_kind': 'DISPATCH', 'record_id': record['id'],
            'operation': 'UPDATE', 'business_date': str(timezone.localdate()),
            'lines': [{'component_identity': str(self.parts[0].component_identity), 'quantity': '10'}]}
        response = self.client.post(BASE + order['id'] + '/plan-record-correction/', correction,
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 20)
        self.assertEqual(response.data['data']['lines'][0]['received_quantity'], '10001')

    def test_new_part_price_requires_explicit_value_instead_of_unknown(self):
        self.create_part_plan(price=None, expected=400)
        self.assertFalse(TubeOutsourcingOrder.objects.filter(is_plan=True).exists())

    def test_dispatch_limits_remain_and_parent_cannot_be_sent_as_piece(self):
        order = self.create_part_plan()
        for component, quantity, expected in [(self.part.component_identity, 1, 400),
                (self.parts[0].component_identity, 201, 400)]:
            response = self.client.post(BASE + order['id'] + '/plan-dispatch/', {
                'client_request_id': str(uuid.uuid4()), 'source_kind': 'CUTTING',
                'actual_dispatch_date': str(timezone.localdate()), 'inputs': [
                    {'component_identity': str(component), 'quantity': str(quantity)}]},
                format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(response.status_code, expected, response.data)
        self.assertFalse(TubeOutsourcingInput.objects.exists())
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid.uuid4()), 'source_kind': 'PUBLIC_PIECE', 'zone_id': str(self.semi_zone.pk),
            'actual_dispatch_date': str(timezone.localdate()), 'inputs': [
                {'component_identity': str(self.parts[0].component_identity), 'quantity': '1'}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(TubeOutsourcingInput.objects.exists())

    def test_direct_dispatch_correction_does_not_depend_on_received_parts(self):
        available = first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity)
        order, _ = self.dispatch_part(self.create_part_plan(), 20)
        order = self.receive_part(order, 10001)
        record = order['dispatch_records'][0]
        payload = {'client_request_id': str(uuid.uuid4()), 'record_kind': 'DISPATCH', 'record_id': record['id'],
            'operation': 'DELETE'}
        response = self.client.post(BASE + order['id'] + '/plan-record-correction/', payload,
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(first_output_available(self.product_line.pk, self.parts[0], self.bom.order_quantity), available)
        self.assertEqual(response.data['data']['lines'][0]['received_quantity'], '10001')

    def test_printing_consumes_and_returns_parent_in_its_own_unit(self):
        order = self.create_part_plan('PUBLIC_PART', self.print_craft)
        identity = build_semi_finished_identity(bom_line=self.part, completed_craft=self.external_sewing, unit=self.part_unit)
        balance = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=10,
            source_type='TEST_PART_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid.uuid4()), 'source_kind': 'PUBLIC_PART', 'zone_id': str(self.semi_zone.pk),
            'actual_dispatch_date': str(timezone.localdate()), 'lines': [{'component_identity': str(self.part.component_identity),
                'quantity': '10', 'factory_id': str(self.factory.pk)}]}, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = self.receive_part(response.data['data'], 10001)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 0)
        self.assertEqual(order['lines'][0]['unit'], '个')
        returned = PublicStockMovement.objects.get(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(returned.balance.identity_snapshot['completed_craft']['code'], 'SCREEN_PRINTING')
        self.assertEqual(order['receipt_records'][0]['received_amount'], '12001.20')

    def test_catalog_reference_attributes_freeze_without_fake_processing_materials(self):
        from apps.boms.component_catalog import apply_component_catalog_selection
        from apps.material_catalog.models import MaterialCatalog, MaterialAttributeValue
        for line in (self.part, self.parts[0]):
            catalog = MaterialCatalog.objects.create(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', name=line.part_name)
            MaterialAttributeValue.objects.create(catalog=catalog, scope='BASE', field_key='model', value='规格A')
            apply_component_catalog_selection(line, {'material_catalog_id': catalog.pk, 'material_selection': {
                'catalog_version': catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'PROCESSED',
                'unit_name': line.unit, 'attributes': {'model': '规格A'}}}, old=None,
                request=SimpleNamespace(user=self.user), persist=True, versions={},
                selection_permission='material_catalog.view_materialcatalog')
            line.save()
        order = self.create_part_plan()
        target = order['lines'][0]
        self.assertEqual(target['specification'], '规格A')
        self.assertEqual(target['component_material_selection_snapshot']['attributes'], {'model': '规格A'})
        self.assertIsNone(target['component_material_selection_snapshot']['completed_craft'])
        self.assertEqual(target['output_material_selection_snapshot'], {})
        order, _ = self.dispatch_part(order, 1)
        batch = self.client.get(BASE + order['dispatch_records'][0]['id'] + '/').data['data']
        self.assertEqual(batch['lines'][0]['component_material_selection_snapshot']['attributes'], {'model': '规格A'})
        MaterialCatalog.objects.filter(pk=self.part.material_catalog_id).update(name='档案后改名')
        order = self.receive_part(order, 2)
        returned = order['receipt_records'][0]['lines'][0]
        self.assertEqual(returned['component_material_selection_snapshot']['name'], self.part.part_name)
        self.assertEqual(returned['received_amount'], '2.40')

    def test_part_receipts_freeze_price_and_corrections_use_original_price(self):
        order, _ = self.dispatch_part(self.create_part_plan(price='3.25'), 20)
        order = self.receive_part(order, 10001)
        first = order['receipt_records'][0]
        self.assertEqual(first['received_amount'], '32503.25')
        response = self.client.patch(BASE + order['id'] + '/plan-quantity/', {'lines': [{
            'order_line_id': order['lines'][0]['id'], 'quantity': '100', 'unit_price': '4.50'}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = self.receive_part(response.data['data'], 2)
        rows = {row['id']: row for row in order['receipt_records']}
        self.assertEqual(rows[first['id']]['lines'][0]['unit_price'], '3.25')
        self.assertEqual(order['plan_summary']['received_amount'], '32512.25')
        second = next(row for row in rows.values() if row['id'] != first['id'])
        for record, operation in ((first, 'UPDATE'), (second, 'DELETE')):
            payload = {'client_request_id': str(uuid.uuid4()), 'record_kind': 'RECEIPT',
                'record_id': record['id'], 'operation': operation}
            if operation == 'UPDATE':
                payload.update(business_date=str(timezone.localdate()), lines=[{
                    'component_identity': str(self.part.component_identity), 'quantity': '10000'}])
            response = self.client.post(BASE + order['id'] + '/plan-record-correction/', payload,
                format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(response.status_code, 200, response.data)
            order = response.data['data']
        self.assertEqual(order['plan_summary']['received_amount'], '32500.00')
        self.assertFalse(order['plan_summary']['has_unknown_receipt_amount'])

    def test_historical_unknown_receipts_stay_unknown_after_parent_price_is_filled(self):
        from apps.outsourcing.models import TubePlanReceiptLine
        order = self.create_part_plan()
        master = TubeOutsourcingOrder.objects.get(pk=order['id'])
        master.source_snapshot.pop('billing_basis')
        master.source_snapshot['fees_deferred'] = True
        master.save(update_fields=['source_snapshot'])
        master.lines.update(unit_price=None)
        order = self.receive_part(order, 3)
        historical = TubePlanReceiptLine.objects.get(receipt__order=master)
        historical.snapshot.pop('billing_basis')
        historical.snapshot.pop('unit_price')
        historical.save(update_fields=['snapshot'])
        response = self.client.patch(BASE + order['id'] + '/plan-quantity/', {'lines': [{
            'order_line_id': order['lines'][0]['id'], 'quantity': '100', 'unit_price': '2.00'}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = self.receive_part(response.data['data'], 4)
        self.assertEqual(order['billing_basis'], 'PART_RECEIPT')
        self.assertEqual(order['plan_summary']['received_amount'], '8.00')
        self.assertTrue(order['plan_summary']['has_unknown_receipt_amount'])
        historical.refresh_from_db()
        self.assertNotIn('unit_price', historical.snapshot)

    def test_price_edit_validates_amount_and_existing_etag_permission_contract(self):
        order = self.create_part_plan(price='0')
        self.assertEqual(order['planned_amount'], '0.00')
        payload = {'lines': [{'order_line_id': order['lines'][0]['id'], 'quantity': '100', 'unit_price': '1.23'}]}
        no_etag = self.client.patch(BASE + order['id'] + '/plan-quantity/', payload, format='json')
        self.assertEqual(no_etag.status_code, 428, no_etag.data)
        for value in (None, '', '-1', '1.234', '100000000000000'):
            payload['lines'][0]['unit_price'] = value
            response = self.client.patch(BASE + order['id'] + '/plan-quantity/', payload,
                format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(response.status_code, 400, response.data)
        target = TubeOutsourcingOrder.objects.get(pk=order['id']).lines.get()
        self.assertEqual(target.unit_price, Decimal('0'))

    def test_distinct_parent_units_and_prices_bill_only_each_returned_part(self):
        ProductionUnit.objects.get_or_create(unit_name='件', defaults={'unit_code': 'PFTITEM'})
        other = BomLine.objects.create(section=self.part.section, line_number=5,
            component_kind='SEWN_PART', part_name='外袋', unit='件', parts_per_product=1)
        self.parts[1].parent_part = other
        self.parts[1].save(update_fields=['parent_part'])
        context = self.part_context()
        response = self.client.post(BASE, {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'CUTTING', 'craft_id': str(self.external_sewing.pk), 'zone_id': None,
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': str(line.component_identity), 'quantity': '100',
                       'factory_id': str(self.factory.pk), 'unit_price': price}
                      for line, price in ((self.part, '1.20'), (other, '2.50'))]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order = response.data['data']
        response = self.client.post(BASE + order['id'] + '/plan-receipt/', {
            'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(self.semi_zone.warehouse_id), 'lines': [{
                'order_line_id': line['id'], 'received_quantity': '1' if line['unit'] == '个' else '2',
                'zone_id': str(self.semi_zone.pk)} for line in order['lines']]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data['data']
        self.assertEqual(result['plan_summary']['received_amount'], '6.20')
        returned = {line['unit']: line for line in result['receipt_records'][0]['lines']}
        self.assertEqual((returned['个']['unit_price'], returned['件']['unit_price']), ('1.20', '2.50'))
        self.assertFalse(TubeOutsourcingInput.objects.exists())

    def test_source_fabrics_are_grouped_and_frozen_for_plan_dispatch_and_receipt(self):
        self.fabric.raw_values = {**self.fabric.raw_values, 'fabric_width': '150'}
        self.fabric.save(update_fields=['raw_values'])
        self.part.material = '不得当作来源布料'
        self.part.save(update_fields=['material'])
        context = self.part_context()
        sources = context['rows'][0]['component_source_materials']
        self.assertEqual(len(sources), 2)
        fabric = next(row for row in sources if row['source_bom_line_id'] == str(self.fabric.pk))
        self.assertEqual((fabric['name'], fabric['material'], fabric['color'], fabric['fabric_spec']),
                         ('面布', '600D', '蓝色', '150cm'))
        self.assertEqual((fabric['color_code'], fabric['width']), ('5865C', '150'))
        order = self.create_part_plan(price='2.50')
        self.assertEqual(order['lines'][0]['component_source_materials'], sources)
        self.fabric.raw_values['fabric_width'] = '180'
        self.fabric.save(update_fields=['raw_values'])
        order, _ = self.dispatch_part(order, 1)
        dispatch = order['dispatch_records'][0]['lines'][0]['component_source_materials']
        self.assertEqual(dispatch, [fabric])
        batch = self.client.get(BASE + order['dispatch_records'][0]['id'] + '/').data['data']
        self.assertEqual(batch['lines'][0]['component_source_materials'], [fabric])
        order = self.receive_part(order, 3)
        self.assertEqual(order['receipt_records'][0]['lines'][0]['component_source_materials'], sources)
        self.assertEqual(order['plan_summary']['received_amount'], '7.50')

    def test_old_plan_sources_are_recovered_from_saved_identity_not_current_bom(self):
        order = self.create_part_plan()
        master = TubeOutsourcingOrder.objects.get(pk=order['id'])
        target = master.lines.get()
        target.snapshot.pop('component_source_materials')
        for piece in target.snapshot['pieces']:
            piece.pop('component_source_materials')
        target.save(update_fields=['snapshot'])
        self.fabric.material = '最新错误材质'
        self.fabric.specification = '最新错误规格'
        self.fabric.save(update_fields=['material', 'specification'])
        response = self.client.get(BASE + order['id'] + '/')
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data['data']
        sources = result['lines'][0]['component_source_materials']
        self.assertIn(('', '600D', '蓝色', '150cm'),
            [(row['name'], row['material'], row['color'], row['fabric_spec']) for row in sources])
        self.assertTrue(all(row['color_code'] == row['width'] == '' for row in sources))
        self.assertEqual(result['inputs'][0]['component_source_materials'][0]['material'], '600D')
        received = self.receive_part(result, 1)
        self.assertEqual(received['receipt_records'][0]['lines'][0]['component_source_materials'], sources)


    def test_mixed_piece_units_freeze_dispatch_totals_and_keep_part_receipt_price(self):
        item_unit, _ = ProductionUnit.objects.get_or_create(unit_name='件', defaults={'unit_code': 'PFTITEM'})
        self.parts[1].unit = item_unit.unit_name
        self.parts[1].save(update_fields=['unit'])
        self.cotton.unit = self.part_unit.unit_name
        self.cotton.save(update_fields=['unit'])
        context = self.part_context()
        self.assertTrue(context['ready'], context['rows'])
        expected = {str(self.parts[0].component_identity): '片', str(self.parts[1].component_identity): '件',
                    str(self.cotton.component_identity): '个'}
        self.assertEqual({row['component_identity']: row['unit'] for row in context['inputs']}, expected)
        order = self.create_part_plan(price='7.50')
        frozen = TubeOutsourcingOrder.objects.get(pk=order['id']).lines.get().snapshot['pieces']
        for row in frozen:
            identity = row['input_identity']['identity_snapshot']
            self.assertEqual(identity['unit_name'], row['unit'])
            piece = identity['composition'][0]['piece']
            if row['unit'] == '片':
                self.assertNotIn('unit_name', piece)
            else:
                self.assertEqual(piece['unit_name'], row['unit'])
        quantities = {str(self.parts[0].component_identity): '20', str(self.parts[1].component_identity): '3',
                      str(self.cotton.component_identity): '2'}
        payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': 'CUTTING', 'zone_id': None,
            'inputs': [{'component_identity': key, 'quantity': quantity} for key, quantity in quantities.items()]}
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        order = response.data['data']
        self.assertEqual(order['status'], 'PROCESSING')
        self.assertIsNone(order['plan_summary']['dispatched_quantity'])
        self.assertIsNone(order['plan_summary']['dispatch_progress'])
        self.assertEqual({row['unit']: row['dispatched_quantity'] for row in order['plan_summary']['input_totals']},
                         {'片': '20', '件': '3', '个': '2'})
        self.assertEqual({row['component_identity']: row['unit'] for row in order['dispatch_records'][0]['lines']}, expected)
        for line in TubeOutsourcingInput.objects.all():
            self.assertEqual(line.snapshot['unit'], expected[str(line.component_identity)])
            self.assertEqual(line.input_identity['identity_snapshot']['unit_name'], line.snapshot['unit'])
        batch = self.client.get(BASE + order['dispatch_records'][0]['id'] + '/')
        self.assertEqual(batch.status_code, 200, batch.data)
        self.assertEqual({row['component_identity']: row['unit'] for row in batch.data['data']['lines']}, expected)
        listed = self.client.get('/api/v1/unified-outsourcing-orders/', HTTP_HOST='localhost')
        self.assertEqual(listed.status_code, 200, listed.data)
        entry = next(row for row in listed.data['data'] if row['id'] == order['id'])
        self.assertEqual({row['unit']: row['quantity'] for row in entry['dispatched_quantities']},
                         {'片': '20', '件': '3', '个': '2'})
        order = self.receive_part(order, 2)
        self.assertEqual(order['plan_summary']['received_amount'], '15.00')
        self.assertEqual(order['receipt_records'][0]['lines'][0]['unit'], '个')
        from apps.production_scheduling.detail_related import _tube_records
        related = _tube_records(TubeOutsourcingOrder.objects.filter(pk=order['id']), [self.product_line.pk])
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0][1]['quantity_unit'], '个')
        self.assertEqual(related[0][1]['received_unit'], '个')

    def test_non_piece_stock_unit_debits_and_correction_retains_frozen_unit(self):
        item_unit, _ = ProductionUnit.objects.get_or_create(unit_name='件', defaults={'unit_code': 'PFTITEM'})
        piece = self.parts[0]
        piece.unit = item_unit.unit_name
        piece.save(update_fields=['unit'])
        identity = build_semi_finished_identity(bom_line=piece, completed_craft=component_stock_craft('CUTTING'), unit=item_unit)
        balance = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=30,
            source_type='TEST_PART_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        order = self.create_part_plan('PUBLIC_PIECE')
        order, _ = self.dispatch_part(order, 20, 'PUBLIC_PIECE')
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 10)
        record = order['dispatch_records'][0]
        correction = {'client_request_id': str(uuid.uuid4()), 'record_kind': 'DISPATCH', 'record_id': record['id'],
            'operation': 'UPDATE', 'business_date': str(timezone.localdate()),
            'lines': [{'component_identity': str(piece.component_identity), 'quantity': '10'}]}
        response = self.client.post(BASE + order['id'] + '/plan-record-correction/', correction,
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 20)
        result = response.data['data']
        self.assertEqual(result['dispatch_records'][0]['lines'][0]['unit'], '件')
        self.assertEqual({row['unit']: row['dispatched_quantity'] for row in result['plan_summary']['input_totals']},
                         {'片': '0', '件': '10'})

    def test_default_piece_summary_keeps_legacy_single_unit_contract(self):
        order = self.create_part_plan()
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '0')
        self.assertEqual(order['plan_summary']['input_totals'], [{'unit': '片', 'dispatched_quantity': '0'}])
        order, _ = self.dispatch_part(order, 20)
        self.assertEqual(order['plan_summary']['dispatched_quantity'], '20')
        self.assertEqual(order['plan_summary']['input_totals'], [{'unit': '片', 'dispatched_quantity': '20'}])
