import uuid

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine, BomSection
from apps.material_issues.public_semi_requirements import public_semi_requirement_rows
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.inventory.models import InternalSemiFinishedReceipt, PublicStockBalance, PublicStockMovement
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from .test_internal_receipt_sewing import SewingFixture
from .test_tube_d1_receipts import D1Fixture


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class PartFlowReceiptTests(D1Fixture, APITestCase):
    url = '/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
        SewingFixture.prepare_sewing(self)
        self.cut_unit, _ = ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'PFPIECE'})
        self.part_unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'PFPART'})
        self.part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
            component_kind='SEWN_PART', part_name='床面', unit='个', parts_per_product=1)
        for line in self.parts:
            line.component_kind = 'CUT_PIECE'
            line.parent_part = self.part
            line.pieces_per_part = 2
            line.unit = '片'
            line.cutting_pieces_per_set = None
            line.cutting_sets_per_product = None
            line.fabric_meters_per_piece = None
            line.fabric_meters_per_set = None
            line.save()
        auxiliary = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        cotton = BomLine.objects.create(section=auxiliary, line_number=1, category='辅料', part_name='无胶棉',
            material='无胶棉', specification='200g', unit='米', raw_values={'accessory_color': '白色'})
        self.parts.append(BomLine.objects.create(section=self.part.section, line_number=4,
            component_kind='CUT_PIECE', parent_part=self.part, pieces_per_part=1, unit='片',
            part_name='床面棉片', specification='50*40', fabric_source_line=cotton))
        workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
        for category in ('CUTTING', 'SEWING'):
            craft = Craft.objects.create(name=f'部位流程测试{category}', craft_type='INTERNAL',
                plan_category=category, workshop=workshop, status='ACTIVE')
            ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
                craft=craft, craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name, plan_category=category)

    def preview(self, category):
        response = self.client.get(self.url + 'preview/',
            {'schedule_product_id': str(self.schedule_product.pk), 'plan_category': category})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def submit(self, category, line, quantity, etag=None):
        data = {'request_id': str(uuid.uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': category, 'zone_id': str(self.semi_zone.pk), 'receipt_date': str(timezone.localdate()),
            'lines': [{'bom_line_id': str(line.pk), 'quantity': str(quantity)}]}
        response = self.client.post(self.url, data, format='json',
            HTTP_IF_MATCH=etag or self.preview(category)['etag'])
        return response, data

    def confirm(self, response):
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        return self.client.post(f'{self.url}{receipt.pk}/confirm/', HTTP_IF_MATCH=f'"{receipt.source_revision_hash}"')

    def test_cutting_and_sewing_offer_different_objects_and_units(self):
        cutting = self.preview('CUTTING')['lines']
        sewing = self.preview('SEWING')['lines']
        self.assertEqual({row['bom_line_id'] for row in cutting}, {str(line.pk) for line in self.parts})
        self.assertEqual({row['unit'] for row in cutting}, {'片'})
        self.assertEqual([(row['bom_line_id'], row['unit']) for row in sewing], [(str(self.part.pk), '个')])
        invalid, _ = self.submit('SEWING', self.parts[0], 1)
        self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_pending_confirm_and_replay_credit_cut_pieces_once(self):
        created, payload = self.submit('CUTTING', self.parts[0], 20)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())
        first = self.confirm(created)
        self.assertEqual(first.status_code, 200, first.data)
        second = self.confirm(created)
        self.assertEqual(second.status_code, 200, second.data)
        movement = PublicStockMovement.objects.get(source_type='INTERNAL_SEMI_RECEIPT')
        self.assertEqual(movement.quantity, 20)
        self.assertEqual(movement.balance.identity_snapshot['semi_kind'], 'CUT_PIECE')
        line = InternalSemiFinishedReceipt.objects.get(pk=created.data['data']['receipt_id']).lines.get()
        self.assertIsNone(line.input_requirement_id)
        self.assertEqual(line.unit_id, self.cut_unit.pk)

    def test_stale_preview_rejected_and_parent_composition_is_frozen(self):
        etag = self.preview('SEWING')['etag']
        first, _ = self.submit('SEWING', self.part, 10, etag)
        self.assertEqual(first.status_code, 201, first.data)
        stale, _ = self.submit('SEWING', self.part, 10, etag)
        self.assertEqual(stale.status_code, 412, stale.data)
        self.parts[0].specification = '99*99'
        self.parts[0].save(update_fields=['specification'])
        changed = self.confirm(first)
        self.assertEqual(changed.status_code, 409, changed.data)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())

    def test_external_receipt_has_no_order_cap_and_assembly_gets_parts_only(self):
        for line, stage, unit in [(self.parts[0], 'CUTTING', self.cut_unit), (self.part, 'SEWING', self.part_unit)]:
            identity = build_semi_finished_identity(bom_line=line, completed_craft=component_stock_craft(stage), unit=unit)
            credit_public_stock(identity=identity, zone=self.semi_zone, quantity=9000,
                actor_employee=self.employee, source_type='TUBE_OUTSOURCING_RETURN',
                source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), production_task=self.task,
                product_line=self.product_line, bom_line=line)
        assembly, blockers = public_semi_requirement_rows(self.task.pk, self.product_line.pk, plan_category='ASSEMBLY')
        self.assertFalse(blockers, blockers)
        typed_assembly = [row for row in assembly if row['conversion_snapshot']['public_identity']['identity_snapshot'].get('schema_version') == 3]
        self.assertEqual({row['material_name'] for row in typed_assembly}, {'床面'})
        sewing, blockers = public_semi_requirement_rows(self.task.pk, self.product_line.pk, plan_category='SEWING')
        self.assertFalse(blockers, blockers)
        typed_sewing = [row for row in sewing if row['conversion_snapshot']['public_identity']['identity_snapshot'].get('schema_version') == 3]
        self.assertEqual({row['material_name'] for row in typed_sewing}, {line.part_name for line in self.parts})
        self.assertEqual(PublicStockBalance.objects.filter(identity_snapshot__semi_kind='SEWN_PART').get().quantity, 9000)

    def test_attribute_identity_extension_passes_receipt_constraints_and_freezes_each_stage(self):
        from apps.material_catalog.models import MaterialCatalog
        for line, unit, attributes in (
            (self.part, self.part_unit, {'model': '床面 A', 'process': '双线'}),
            (self.parts[0], self.cut_unit, {'model': '布片 A'}),
        ):
            catalog = MaterialCatalog.objects.create(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', name=line.part_name)
            line.material_catalog = catalog
            line.material_selection_snapshot = {
                'schema_version': 1, 'selection_kind': 'BOM_COMPONENT_REFERENCE',
                'catalog_id': str(catalog.pk), 'catalog_version': catalog.updated_at.isoformat(),
                'category_key': 'FABRIC_SEMI', 'template_key': 'FABRIC_SEMI', 'name': line.part_name,
                'scope': 'BASE', 'processing_state': 'PROCESSED', 'processing_stage': '',
                'completed_craft': None, 'semi_kind': None, 'attributes': attributes,
                'unit_id': str(unit.pk), 'unit_name': unit.unit_name,
                'display_name': line.part_name, 'identity_attributes_version': 1,
            }
            line.save(update_fields=['material_catalog', 'material_selection_snapshot'])
        for category, line in (('CUTTING', self.parts[0]), ('SEWING', self.part)):
            with self.subTest(category=category):
                created, _ = self.submit(category, line, 1)
                self.assertEqual(created.status_code, 201, created.data)
                receipt = InternalSemiFinishedReceipt.objects.get(pk=created.data['data']['receipt_id'])
                saved = receipt.lines.get()
                self.assertIsNone(saved.input_requirement_id)
                self.assertEqual(saved.attribute_snapshot['schema_version'], 3)
                self.assertEqual(saved.attribute_snapshot['component_attributes'], line.material_selection_snapshot['attributes'])
                confirmed = self.confirm(created)
                self.assertEqual(confirmed.status_code, 200, confirmed.data)
                movement = PublicStockMovement.objects.get(source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk)
                self.assertEqual(movement.balance.identity_snapshot, saved.attribute_snapshot)
                self.assertEqual(self.confirm(created).status_code, 200)
                self.assertEqual(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk).count(), 1)
