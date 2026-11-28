"""真实隔离数据库：裁片投入、部位回货、分次补发与原费用隔离。"""
import uuid
from types import SimpleNamespace
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.boms.models import BomLine, BomSection
from apps.inventory.models import PublicStockMovement, WarehouseZone
from apps.inventory.part_flow_quantities import first_output_available
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_inventory_queries import public_semi_inventory_page
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.outsourcing.models import OutsourcingFactoryCraft, TubeOutsourcingInput, TubeOutsourcingOrder

BASE = '/api/v1/tube-outsourcing-orders/'
MOVEMENTS = '/api/v1/outsourcing-movements/'


class PartFlowPlanFixture(ScopedActorMixin, D1Fixture):
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
            specification='200g', unit='米', raw_values={'accessory_color': '白色', 'purchase_required': False})
        self.cotton = BomLine.objects.create(section=self.part.section, line_number=4, component_kind='CUT_PIECE',
            parent_part=self.part, pieces_per_part=1, unit='片', part_name='床面棉片', specification='50*40', fabric_source_line=cotton)
        self.print_craft = Craft.objects.create(name='部位丝印', craft_type='EXTERNAL', outsourcing_code='SCREEN_PRINTING')
        for craft in (self.external_sewing, self.print_craft):
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=craft,
                defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': craft.name})
            OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=craft, defaults={'craft_name_snapshot': craft.name})


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PartFlowPlanApiTests(PartFlowPlanFixture, APITestCase):
    def movements(self, direction='dispatch', process=''):
        response = self.client.get(MOVEMENTS, {'task_number': self.task.task_number.lower(),
                                               'direction': direction, 'process': process})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

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

    def create_part_plan(self, source='CUTTING', craft=None, price='1.20', expected=201, *, additional_lines=()):
        context = self.part_context(source, craft)
        payload = {'is_plan': True, 'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
            'schedule_product_id': str(self.schedule_product.pk), 'source_kind': source,
            'craft_id': str((craft or self.external_sewing).pk), 'zone_id': context['zone_id'],
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': [{'component_identity': str(self.part.component_identity), 'quantity': '100',
                'factory_id': str(self.factory.pk), 'unit_price': price}, *additional_lines]}
        response = self.client.post(BASE, payload, format='json')
        self.assertEqual(response.status_code, expected, response.data)
        return response.data.get('data')

    def test_sewing_accessories_are_entered_only_on_actual_dispatch(self):
        from apps.inventory.stock_services import credit_material_stock
        from apps.products.models import RawMaterialInformation

        category, _ = ProductCategory.objects.get_or_create(category_name='辅料', item_type='MATERIAL')
        raw = RawMaterialInformation.objects.create(material_number='SEW-AUX', item_type='MATERIAL',
            category=category, unit=self.part_unit, material_name='随单扣件')
        accessory = BomLine.objects.create(section=self.cotton.fabric_source_line.section, line_number=2,
            part_name='随单扣件', unit='个', unit_consumption='1', total_consumption='100',
            raw_values={'source_inventory_material_id': str(raw.pk), 'purchase_required': True})
        material = {'bom_line_id': str(accessory.pk), 'factory_id': str(self.factory.pk), 'quantity': '2',
                    'zone_id': str(self.raw_zone.pk)}
        context = self.part_context()
        self.assertEqual(context['material_rows'], [])
        today = str(timezone.localdate())
        plan = {'is_plan': True, 'client_request_id': str(uuid.uuid4()), 'source_revision': context['source_revision'],
                'schedule_product_id': str(self.schedule_product.pk), 'source_kind': 'CUTTING',
                'craft_id': str(self.external_sewing.pk), 'planned_dispatch_date': today, 'expected_return_date': today,
                'lines': [{'component_identity': str(self.part.component_identity), 'quantity': '100',
                           'factory_id': str(self.factory.pk), 'unit_price': '1'}]}
        rejected = self.client.post(BASE, {**plan, 'materials': [material], 'material_source_revision': '0' * 64}, format='json')
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn('车缝辅料请在实际外发时填写', str(rejected.data))
        saved = self.client.post(BASE, plan, format='json')
        self.assertEqual(saved.status_code, 201, saved.data)
        order = saved.data['data']
        balance = credit_material_stock(raw_material=raw, unit=self.part_unit, zone=self.raw_zone, quantity=5,
            source_type='TEST_SEWING_AUX', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee).balance
        context = self.part_context(order=order)
        self.assertIn(str(accessory.pk), [row['bom_line_id'] for row in context['material_rows']])
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', {'client_request_id': str(uuid.uuid4()),
            'actual_dispatch_date': today, 'source_kind': 'CUTTING', 'inputs': [{'component_identity': str(self.parts[0].component_identity), 'quantity': '1'}],
            'materials': [material], 'material_source_revision': context['material_source_revision']},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 3)
        self.assertCountEqual([(row['item_name'], Decimal(row['quantity']), row['unit']) for row in self.movements()],
            [(self.parts[0].part_name, 1, '片'), (accessory.part_name, 2, self.part_unit.unit_name)])

    def dispatch_part(self, order, quantity, source='CUTTING', piece=None):
        row = {'component_identity': str((piece or self.parts[0]).component_identity), 'quantity': str(quantity)}
        payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': source, 'zone_id': str(self.semi_zone.pk) if source.startswith('PUBLIC_') else None,
            'inputs': [row]}
        response = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data'], payload

    def receive_part(self, order, quantity, *, zone=None):
        zone = zone or self.semi_zone
        payload = {'client_request_id': str(uuid.uuid4()), 'receipt_date': str(timezone.localdate()),
            'warehouse_id': str(zone.warehouse_id), 'lines': [{'order_line_id': order['lines'][0]['id'],
                'received_quantity': str(quantity), 'zone_id': str(zone.pk)}]}
        response = self.client.post(BASE + order['id'] + '/plan-receipt/', payload, format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def sewing_assignment(self, *, external=False, schedule_internal=True):
        if schedule_internal:
            craft, _ = Craft.objects.get_or_create(plan_category='SEWING', defaults={
                'craft_type': 'INTERNAL', 'name': '本厂车缝工艺', 'workshop': self.workshop})
            ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product,
                craft=craft, defaults={'craft_type_snapshot': 'INTERNAL', 'craft_name_snapshot': craft.name,
                                       'plan_category': 'SEWING'})
        own = type(self.factory).objects.get(pk=self.factory.pk)
        own.pk, own.factory_number, own.name = uuid.uuid4(), 'PFT-OWN', '本厂'
        own.save(force_insert=True)
        OutsourcingFactoryCraft.objects.create(factory=own, craft=self.external_sewing,
                                               craft_name_snapshot=self.external_sewing.name)
        quantity = int(self.product_line.quantity)
        rows = [{'component_identity': str(self.part.component_identity), 'quantity': quantity,
                 'factory_id': str(own.pk), 'unit_price': '2.25'}]
        if external:
            other = BomLine.objects.create(section=self.part.section, line_number=5, component_kind='SEWN_PART',
                                           part_name='外袋', unit=self.part.unit, parts_per_product=1)
            self.parts[1].parent_part = other
            self.parts[1].save(update_fields=['parent_part'])
            rows.append({'component_identity': str(other.component_identity), 'quantity': quantity,
                         'factory_id': str(self.factory.pk), 'unit_price': '1.50'})
        context = self.part_context()
        return self.client.post(BASE, {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            'source_revision': context['source_revision'], 'schedule_product_id': str(self.schedule_product.pk),
            'source_kind': 'CUTTING', 'craft_id': str(self.external_sewing.pk),
            'planned_dispatch_date': str(timezone.localdate()), 'expected_return_date': str(timezone.localdate()),
            'lines': rows}, format='json')

    def test_sewing_assignment_keeps_internal_price_out_of_dispatch_receipts_and_external_totals(self):
        from apps.outsourcing.sewing_assignments import internal_sewing_products, sewing_part_scope
        self.part.specification = '120×65'
        self.part.save(update_fields=['specification'])
        response = self.sewing_assignment(external=True)
        self.assertEqual(response.status_code, 201, response.data)
        order = response.data['data']
        self.assertEqual([row['part_name'] for row in order['lines']], ['外袋'])
        self.assertEqual({row['component_identity'] for row in order['inputs']}, {str(self.parts[1].component_identity)})
        own = order['internal_sewing_parts'][0]
        self.assertEqual((own['part_name'], Decimal(own['unit_price'])), ('床面', Decimal('2.25')))
        self.assertEqual((own['bom_quantity'], own['specification']), (str(own['quantity']), '120×65'))
        cotton_id = str(self.cotton.fabric_source_line_id)
        self.assertIn(cotton_id, [row['source_bom_line_id'] for row in own['component_source_materials']])
        self.assertEqual(order['plan_summary']['planned_quantity'], str(int(self.product_line.quantity)))
        self.assertTrue(internal_sewing_products().filter(pk=self.schedule_product.pk).exists())
        self.assertEqual(sewing_part_scope(product_line_id=self.product_line.pk),
                         {str(self.part.component_identity): int(self.product_line.quantity)})
        warehouse = self.client.get(BASE + order['id'] + '/', {'warehouse_stage': 'all'})
        self.assertEqual(warehouse.status_code, 200, warehouse.data)
        self.assertNotIn('internal_sewing_parts', warehouse.data['data'])
        for params, visible in (({}, True), ({'warehouse_stage': 'all'}, False)):
            preview = self.client.get(BASE + order['id'] + '/receipt-preview/', params)
            self.assertEqual(preview.status_code, 200, preview.data)
            self.assertEqual('internal_sewing_parts' in preview.data['data']['order'], visible)
        available = self.part_context(order=order)
        self.assertEqual({row['component_identity'] for row in available['inputs']}, {str(self.parts[1].component_identity)})
        rejected = self.client.post(BASE + order['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
            'source_kind': 'CUTTING', 'inputs': [{'component_identity': str(self.parts[0].component_identity), 'quantity': 1}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(rejected.status_code, 400, rejected.data)
        returned = self.receive_part(order, 2)
        self.assertEqual(Decimal(returned['plan_summary']['received_amount']), Decimal('3'))
        BomLine.objects.filter(pk=self.part.pk).update(specification='改版后规格')
        BomLine.objects.filter(pk=cotton_id).update(specification='改版后棉料')
        reopened = self.client.get(BASE + order['id'] + '/')
        self.assertEqual(reopened.data['data']['internal_sewing_parts'], [own])

    def test_all_internal_assignment_has_no_warehouse_order(self):
        response = self.sewing_assignment()
        self.assertEqual(response.status_code, 201, response.data)
        order = response.data['data']
        self.assertEqual((order['lines'], order['inputs']), ([], []))
        self.assertFalse(order['permissions']['can_dispatch'])
        self.assertFalse(order['permissions']['can_receive'])
        self.assertEqual(len(order['internal_sewing_parts']), 1)
        self.assertEqual(self.client.get(BASE + order['id'] + '/', {'warehouse_stage': 'all'}).status_code, 404)
        cancelled = self.client.post(BASE + order['id'] + '/cancel/', {'client_request_id': str(uuid.uuid4())},
                                     format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data['data']['status'], 'CANCELLED')

    def test_used_internal_sewing_assignment_cannot_cancel(self):
        from apps.material_issues.models import MaterialIssueAuditEvent
        order = self.sewing_assignment(external=True).data['data']
        MaterialIssueAuditEvent.objects.create(issue=self.fabric_issue, action='CREATED', issue_version=2,
            actor_employee=self.employee, snapshot={'plan_source': {'plan_category': 'SEWING'}})
        detail = self.client.get(BASE + order['id'] + '/').data['data']
        self.assertFalse(detail['permissions']['can_cancel'])
        result = self.client.post(BASE + order['id'] + '/cancel/', {'client_request_id': str(uuid.uuid4())},
                                  format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(result.status_code, 409, result.data)

    def test_internal_assignment_requires_scheduled_internal_sewing(self):
        response = self.sewing_assignment(schedule_internal=False)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('补选厂内车缝', str(response.data))

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
        self.assertCountEqual([(row['voucher_number'], row['item_name'], row['quantity'], row['unit'])
                               for row in self.movements('receipt', 'SEWING')],
                              [(row['receipt_number'], self.part.part_name, row['total_received_quantity'], '个')
                               for row in order['receipt_records']])
        returns = PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN')
        self.assertEqual(returns.count(), 2)
        self.assertEqual({row.balance.identity_snapshot['semi_kind'] for row in returns}, {'SEWN_PART'})
        self.assertEqual({row.balance.unit_id for row in returns}, {self.part_unit.pk})
        self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
        cutting = public_semi_inventory_page(page=1, page_size=20, bom_section='FABRIC_SEMI')
        parts = public_semi_inventory_page(page=1, page_size=20, bom_section='SEWN_PART')
        self.assertEqual(cutting['count'], 0)
        row, = parts['results']
        self.assertEqual(row['inventory_quantity'], 10002)

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
        for direction, quantity in (('dispatch', '10'), ('receipt', '10001')):
            row, = self.movements(direction, 'SCREEN_PRINTING')
            self.assertEqual((row['item_name'], row['quantity'], row['unit'], row['direct_transfer']),
                             (self.part.part_name, quantity, '个', False))
        with self.settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            self.scoped_actor()
            self.grant('outsourcing.confirm_dispatch_outsourcingorder', 'CRAFT', [self.print_craft])
            self.assertEqual([row['quantity'] for row in self.movements()], ['10'])
            self.assertEqual(self.client.get(MOVEMENTS, {'direction': 'receipt'}).status_code, 403)
            self.grant('outsourcing.confirm_return_outsourcingorder', 'CRAFT', [self.print_craft])
            self.assertEqual([row['quantity'] for row in self.movements('receipt')], ['10001'])

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
        row, = self.movements('receipt')
        self.assertEqual((row['voucher_number'], row['quantity']), (first['receipt_number'], '10000'))

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

    def create_print_plan(self, factory, *, product_ref=None):
        piece = self.parts[0]
        component = str(piece.component_identity)
        today = str(timezone.localdate())
        printing_api = '/api/v1/cut-piece-printing-orders/'
        product_ref = product_ref or {'schedule_product_id': str(self.schedule_product.pk)}
        options = self.client.get(printing_api + 'source-context/', {**product_ref, 'craft_id': str(self.print_craft.pk)})
        self.assertEqual(options.status_code, 200, options.content[:240])
        context = options.data['data']
        row = next(item for item in context['rows'] if item['component_identity'] == component)
        self.assertEqual(Decimal(row['order_required']), 200)  # 每个成品需要两片该裁片。
        printing = self.client.post(printing_api, {'is_plan': True, 'client_request_id': str(uuid.uuid4()),
            **product_ref, 'source_kind': 'CUTTING',
            'craft_id': str(self.print_craft.pk), 'source_revision': context['source_revision'],
            'planned_dispatch_date': today, 'expected_return_date': today,
            'lines': [{'component_identity': component, 'factory_id': str(factory.pk),
                       'quantity': 200, 'unit_price': '0.50'}]}, format='json')
        self.assertEqual(printing.status_code, 201, printing.data)
        unprinted = build_semi_finished_identity(bom_line=piece, completed_craft=self.cut_craft, unit=self.piece_unit)
        credit_public_stock(identity=unprinted, zone=self.semi_zone, quantity=100, actor_employee=self.employee,
            source_type='TEST_CUT_STOCK', source_id=uuid.uuid4(), source_line_id=uuid.uuid4())
        return printing.data['data']

    def test_unscheduled_print_plan_uses_cut_stock_and_receives_against_original_task(self):
        schedule = self.schedule_product.schedule
        schedule.record_status, schedule.voided_at, schedule.voided_by_employee = 'VOID', timezone.now(), self.employee
        schedule.void_reason = '尚无有效排产的产品'
        schedule.save()
        product_ref = {'product_line_id': str(self.product_line.pk)}
        order = self.create_print_plan(self.factory, product_ref=product_ref)
        query = {**product_ref, 'plan_id': order['id'], 'craft_id': str(self.print_craft.pk)}
        direct = self.client.get(BASE + 'source-context/', {**query, 'source_kind': 'CUTTING'})
        self.assertEqual(direct.status_code, 200, direct.data)
        direct_rows = direct.data['data']['rows']
        self.assertTrue(all(Decimal(row['max_quantity']) == 0 for row in direct_rows))
        component = str(self.parts[0].component_identity)
        direct_piece = next(row for row in direct_rows if row['component_identity'] == component)
        self.assertEqual({item['zone_id']: Decimal(item['available_quantity']) for item in direct_piece['stock_zones']},
                         {str(self.semi_zone.pk): 100})
        self.assertTrue(all('stock_zones' not in row for row in direct_rows if row['component_identity'] != component))
        invalid = self.client.post(BASE + order['id'] + '/plan-dispatch/', {'client_request_id': str(uuid.uuid4()),
            'source_kind': 'CUTTING', 'actual_dispatch_date': str(timezone.localdate()), 'lines': [{
                'component_identity': str(self.parts[0].component_identity), 'factory_id': str(self.factory.pk), 'quantity': 1}]},
            format='json', HTTP_IF_MATCH=order['etag'])
        self.assertEqual(invalid.status_code, 409, invalid.data)
        stock = self.client.get(BASE + 'source-context/', {**query, 'source_kind': 'PUBLIC_PIECE', 'zone_id': str(self.semi_zone.pk)})
        self.assertEqual(stock.status_code, 200, stock.data)
        stock_piece = next(row for row in stock.data['data']['rows'] if row['component_identity'] == component)
        self.assertEqual(Decimal(stock_piece['max_quantity']), 100)
        order = self.send_to_printer(order, self.factory, 7)
        order = self.receive_part(order, 5)
        self.assertEqual(order['plan_summary']['received_quantity'], '5')
        self.assertTrue(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_RETURN',
            production_task=self.task, product_line=self.product_line, quantity=5).exists())

    def send_to_printer(self, printing, factory, quantity):
        response = self.client.post(BASE + printing['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid.uuid4()), 'source_kind': 'PUBLIC_PIECE', 'zone_id': str(self.semi_zone.pk),
            'actual_dispatch_date': str(timezone.localdate()), 'lines': [{'component_identity': str(self.parts[0].component_identity),
                'factory_id': str(factory.pk), 'quantity': quantity}]}, format='json', HTTP_IF_MATCH=printing['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_processor_rejects_unprinted_piece_wrong_origin_and_excess_without_touching_stock(self):
        sewing = self.create_part_plan()
        printing = self.create_print_plan(self.factory)
        component = str(self.parts[0].component_identity)
        source = self.part_context('CUTTING', craft=self.print_craft, order=printing)
        piece = next(row for row in source['rows'] if row['component_identity'] == component)
        self.assertEqual(Decimal(piece['max_quantity']), 0)
        self.assertEqual(Decimal(piece['order_required']), 200)
        printing = self.send_to_printer(printing, self.factory, 12)
        line_id = printing['lines'][0]['id']
        rows = self.part_context('PROCESSOR', order=sewing)['inputs']
        self.assertEqual(next(row['max_quantity'] for row in rows if row['component_identity'] == component), '12')
        movement_count = PublicStockMovement.objects.count()
        for identity, origin, quantity, status in [
                (component, str(uuid.uuid4()), 1, 400),
                (str(self.parts[1].component_identity), line_id, 1, 400),
                (component, line_id, 13, 409)]:
            response = self.client.post(BASE + sewing['id'] + '/plan-dispatch/', {
                'client_request_id': str(uuid.uuid4()), 'source_kind': 'PROCESSOR',
                'actual_dispatch_date': str(timezone.localdate()),
                'inputs': [{'component_identity': identity, 'print_order_line_id': origin, 'quantity': quantity}],
            }, format='json', HTTP_IF_MATCH=sewing['etag'])
            self.assertEqual(response.status_code, status, response.data)
        self.assertFalse(TubeOutsourcingInput.objects.filter(print_order_line_id=line_id).exists())
        self.assertEqual(PublicStockMovement.objects.count(), movement_count)

    def test_sewing_plan_precedes_returns_but_actual_issue_only_uses_its_printed_piece_returns(self):
        self.schedule_product.crafts.filter(craft=self.print_craft).update(removed_at=timezone.now(), removed_by_employee=self.employee)
        piece = self.parts[0]
        component = str(piece.component_identity)
        today = str(timezone.localdate())
        printing = self.create_print_plan(self.factory)
        sewing = self.create_part_plan()
        self.assertTrue(self.part_context('PUBLIC_PIECE', craft=self.print_craft, order=printing)['screen_print_pieces'])

        def check_issue_ceiling(order, available):
            inputs = self.part_context('PUBLIC_PIECE', order=order)['inputs']
            selected = next(item for item in inputs if item['component_identity'] == component)
            self.assertEqual(Decimal(selected['max_quantity']), available)
            payload = {'client_request_id': str(uuid.uuid4()), 'source_kind': 'PUBLIC_PIECE',
                'zone_id': str(self.semi_zone.pk), 'actual_dispatch_date': today,
                'inputs': [{'component_identity': component, 'quantity': available + 1}]}
            rejected = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload,
                                        format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(rejected.status_code, 409, rejected.data)

        check_issue_ceiling(sewing, 0)
        sewing, _ = self.dispatch_part(sewing, 3, piece=self.parts[1])
        printing = self.receive_part(self.send_to_printer(printing, self.factory, 50), 30)
        check_issue_ceiling(sewing, 30)
        sewing, _ = self.dispatch_part(sewing, 18, source='PUBLIC_PIECE', piece=piece)
        check_issue_ceiling(sewing, 12)
        receipt_id = printing['receipt_records'][0]['id']

        def reject_correction(order, kind, record_id, new_quantity):
            result = self.client.post(BASE + order['id'] + '/plan-record-correction/', {
                'client_request_id': str(uuid.uuid4()), 'record_kind': kind, 'record_id': record_id,
                'operation': 'UPDATE', 'business_date': today,
                'lines': [{'component_identity': component, 'quantity': new_quantity}]},
                format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(result.status_code, 409, result.data)

        reject_correction(printing, 'RECEIPT', receipt_id, 17)
        reject_correction(printing, 'RECEIPT', receipt_id, 51)
        printing = self.receive_part(printing, 20)
        check_issue_ceiling(sewing, 32)
        reject_correction(printing, 'DISPATCH', printing['dispatch_records'][0]['id'], 49)

    def test_sewing_dispatches_warehouse_and_processor_pieces_in_one_confirmation(self):
        sewing = self.create_part_plan()
        printing = self.receive_part(self.send_to_printer(self.create_print_plan(self.factory), self.factory, 100), 30)
        second_zone = WarehouseZone.objects.create(warehouse=self.semi_zone.warehouse, zone_name='丝印回仓二区')
        printing = self.receive_part(printing, 12, zone=second_zone)
        component = str(self.parts[0].component_identity)
        line_id = printing['lines'][0]['id']
        context = self.part_context(order=sewing)
        row = next(row for row in context['inputs'] if row['component_identity'] == component)
        self.assertTrue(context['sewing_print_sources'])
        zones = {zone['zone_id']: Decimal(zone['available_quantity']) for zone in row['stock_zones']}
        self.assertEqual(zones, {str(self.semi_zone.pk): Decimal(30), str(second_zone.pk): Decimal(12)})
        self.assertEqual(row['processor_source']['available_quantity'], '58')
        self.assertTrue(all('processor_source' not in item for item in context['inputs'] if item is not row))

        payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()), 'batches': [
            {'source_kind': 'CUTTING', 'inputs': [{'component_identity': str(self.parts[1].component_identity), 'quantity': 3}]},
            {'source_kind': 'PUBLIC_PIECE', 'zone_id': str(self.semi_zone.pk),
             'inputs': [{'component_identity': component, 'quantity': 18}]},
            {'source_kind': 'PUBLIC_PIECE', 'zone_id': str(second_zone.pk),
             'inputs': [{'component_identity': component, 'quantity': 7}]},
            {'source_kind': 'PROCESSOR', 'inputs': [{'component_identity': component, 'quantity': 59,
                                                    'print_order_line_id': line_id}]},
        ]}
        url = f"{BASE}{sewing['id']}/plan-dispatch/"
        movement_count = PublicStockMovement.objects.count()
        rejected = self.client.post(url, payload, format='json', HTTP_IF_MATCH=sewing['etag'])
        self.assertEqual(rejected.status_code, 409, rejected.data)
        self.assertFalse(TubeOutsourcingInput.objects.filter(order__plan_id=sewing['id']).exists())
        self.assertEqual(PublicStockMovement.objects.count(), movement_count)

        payload['batches'][3]['inputs'][0]['quantity'] = 50
        for _ in range(2):
            saved = self.client.post(url, payload, format='json', HTTP_IF_MATCH=sewing['etag'])
            self.assertEqual(saved.status_code, 200, saved.data)
        result = saved.data['data']
        self.assertCountEqual([(record['source_kind'], record['zone_name'], record['total_quantity'])
                               for record in result['dispatch_records']],
            [('CUTTING', '', '3'), ('PUBLIC_PIECE', self.semi_zone.zone_name, '18'),
             ('PUBLIC_PIECE', second_zone.zone_name, '7'), ('PROCESSOR', '', '50')])
        row = next(row for row in result['inputs'] if row['component_identity'] == component)
        self.assertEqual(row['dispatched_quantity'], '75')
        self.assertEqual(PublicStockMovement.objects.count(), movement_count + 2)
        printing = self.client.get(f"{BASE}{printing['id']}/").data['data']
        self.assertEqual(printing['lines'][0]['receivable_quantity'], '8')

    def test_movement_rows_show_direct_transfer_on_dispatch_only(self):
        from apps.outsourcing.models import OutsourcingFactory

        printer = OutsourcingFactory.objects.create(name='直送丝印厂', factory_number='MOVEMENT-PRINT',
            created_by_employee=self.employee, updated_by_employee=self.employee)
        OutsourcingFactoryCraft.objects.create(factory=printer, craft=self.print_craft, craft_name_snapshot=self.print_craft.name)
        sewing = self.create_part_plan()
        printing = self.create_print_plan(printer)
        self.assertEqual(self.movements(), [])
        printing = self.send_to_printer(printing, printer, 100)
        printing = self.receive_part(printing, 60)
        today = str(timezone.localdate())
        response = self.client.post(BASE + sewing['id'] + '/plan-dispatch/', {
            'client_request_id': str(uuid.uuid4()), 'source_kind': 'PROCESSOR', 'actual_dispatch_date': today,
            'inputs': [{'component_identity': str(self.parts[0].component_identity), 'quantity': 40,
                        'print_order_line_id': printing['lines'][0]['id']}],
        }, format='json', HTTP_IF_MATCH=sewing['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        sewing = response.data['data']
        sent = self.movements()
        self.assertCountEqual([(row['process'], row['factory_name'], row['quantity'], row['unit'], row['direct_transfer'])
                               for row in sent],
                              [('SCREEN_PRINTING', printer.name, '100', '片', False),
                               ('SEWING', self.factory.name, '40', '片', True)])
        self.assertTrue(all(row['item_name'] == self.parts[0].part_name and row['business_date'] == today for row in sent))
        row, = self.movements('receipt')
        self.assertEqual((row['process'], row['factory_name'], row['quantity'], row['unit'], row['voucher_number']),
                         ('SCREEN_PRINTING', printer.name, '60', '片', printing['receipt_records'][0]['receipt_number']))
        self.assertEqual(self.movements('receipt', 'SEWING'), [])
        sewing = self.receive_part(sewing, 8)
        sewing = self.receive_part(sewing, 4)
        self.assertCountEqual([(row['item_name'], row['quantity'], row['unit']) for row in self.movements('receipt', 'SEWING')],
                              [(self.part.part_name, '8', '个'), (self.part.part_name, '4', '个')])
        self.assertEqual(self.client.get(MOVEMENTS, {'process': 'CUTTING'}).status_code, 400)
        self.assertEqual(self.client.post(MOVEMENTS, {}, format='json').status_code, 405)
        with self.settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True):
            self.scoped_actor()
            self.task.followers.add(self.scope_employee)
            self.grant('outsourcing.view_outsourcingorder', 'FOLLOWED')
            self.assertEqual(self.client.get(MOVEMENTS).status_code, 403)
            self.grant(CUT_PIECE_PRINTING, 'FOLLOWED')
            self.assertEqual([row['quantity'] for row in self.movements()], ['100'])
            self.assertEqual([row['quantity'] for row in self.movements('receipt')], ['60'])
            self.task.followers.remove(self.scope_employee)
            self.assertEqual(self.movements(), [])
            self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.external_sewing])
            self.assertEqual([row['quantity'] for row in self.movements()], ['40'])

    def test_printer_transfers_and_warehouse_receipts_share_one_remaining_quantity(self):
        from apps.outsourcing.models import OutsourcingFactory
        from apps.production_tasks.cost_selectors import task_cost_summary

        printer = OutsourcingFactory.objects.create(name='直送丝印厂', factory_number='PRINT-DIRECT',
            created_by_employee=self.employee, updated_by_employee=self.employee)
        OutsourcingFactoryCraft.objects.create(factory=printer, craft=self.print_craft, craft_name_snapshot=self.print_craft.name)
        sewing = self.create_part_plan()  # 丝印安排前吴杰即可建单。
        printing = self.send_to_printer(self.create_print_plan(printer), printer, 100)
        component = str(self.parts[0].component_identity)
        today = str(timezone.localdate())
        line_id = printing['lines'][0]['id']
        payload = {'client_request_id': str(uuid.uuid4()), 'source_kind': 'PROCESSOR', 'actual_dispatch_date': today,
            'inputs': [{'component_identity': component, 'quantity': 50, 'print_order_line_id': line_id}]}
        through = BASE + sewing['id'] + '/plan-dispatch/'
        count = PublicStockMovement.objects.count()
        saved = self.client.post(through, payload, format='json', HTTP_IF_MATCH=sewing['etag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        replay = self.client.post(through, payload, format='json', HTTP_IF_MATCH=sewing['etag'])
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(PublicStockMovement.objects.count(), count)
        transfer = TubeOutsourcingInput.objects.get(print_order_line_id=line_id)
        self.assertEqual((transfer.quantity, transfer.factory_id, transfer.print_order_line.factory_id),
                         (50, self.factory.pk, printer.pk))
        sewing = saved.data['data']
        print_url = BASE + printing['id'] + '/'
        printing = self.receive_part(self.client.get(print_url).data['data'], 30)
        self.assertEqual([printing['lines'][0][key] for key in
            ('dispatched_quantity', 'received_quantity', 'transferred_quantity', 'receivable_quantity')], ['100','30','50','20'])
        self.assertEqual(PublicStockMovement.objects.count(), count + 1)

        def tracked_printing():
            result = self.client.get('/api/v1/sewing-tracking/', {'task_number': self.task.task_number})
            self.assertEqual(result.status_code, 200, result.data)
            self.assertEqual({row['process'] for row in result.data['data']}, {'SEWING', 'SCREEN_PRINTING'})
            row, = [row for row in result.data['data'] if row['process'] == 'SCREEN_PRINTING']
            self.assertEqual(row['last_receipt_date'], today)
            by_owner = self.client.get('/api/v1/sewing-tracking/', {'task_number': self.task.task_number, 'owner': printer.name})
            self.assertEqual(by_owner.status_code, 200, by_owner.data)
            reminder, = [item['reminder'] for item in by_owner.data['data']]
            self.assertEqual(reminder['action'], '催回厂')
            self.assertEqual(reminder['quantity'], row['factory_remaining'][0]['quantity'])
            return row

        tracked = tracked_printing()
        for field, amount in (('sent', '100'), ('received', '30'), ('transferred', '50'),
                              ('factory_remaining', '20'), ('not_sent', '100')):
            self.assertEqual(tracked[field], [{'quantity': amount, 'unit': '片'}])
        items = [row for group in task_cost_summary(task=self.task)['categories'] for row in group['items']
                 if row['id'] == f'TUBE_OUTSOURCING:PRINT_TRANSFER:{transfer.pk}']
        self.assertEqual([row['amount_cny'] for row in items], ['25.00'])

        def correct(quantity):
            change = {'client_request_id': str(uuid.uuid4()), 'record_kind': 'DISPATCH', 'record_id': str(transfer.order_id),
                'operation': 'UPDATE', 'business_date': today, 'lines': [{'component_identity': component, 'quantity': quantity}]}
            return self.client.post(BASE + sewing['id'] + '/plan-record-correction/', change, format='json', HTTP_IF_MATCH=sewing['etag'])

        rejected = correct(71)
        self.assertEqual(rejected.status_code, 409, rejected.data)
        updated = correct(60)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(self.client.get(print_url).data['data']['lines'][0]['receivable_quantity'], '10')
        self.assertEqual(tracked_printing()['factory_remaining'], [{'quantity': '10', 'unit': '片'}])
        row, = self.movements('dispatch', 'SEWING')
        self.assertEqual((row['quantity'], row['direct_transfer']), ('60', True))
        deleted = self.client.post(BASE + sewing['id'] + '/plan-record-correction/', {'client_request_id': str(uuid.uuid4()),
            'record_kind': 'DISPATCH', 'record_id': str(transfer.order_id), 'operation': 'DELETE'},
            format='json', HTTP_IF_MATCH=updated.data['data']['etag'])
        self.assertEqual(deleted.status_code, 200, deleted.data)
        self.assertEqual(self.client.get(print_url).data['data']['lines'][0]['receivable_quantity'], '70')
        tracked = tracked_printing()
        self.assertEqual(tracked['transferred'], [])
        self.assertEqual(tracked['factory_remaining'], [{'quantity': '70', 'unit': '片'}])
        self.assertEqual(PublicStockMovement.objects.count(), count + 1)
        self.assertEqual(self.movements('dispatch', 'SEWING'), [])
