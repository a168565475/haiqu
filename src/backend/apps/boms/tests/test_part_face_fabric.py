from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.component_sources import component_source_materials
from apps.boms.material_flow_bom import validate_fabric_links
from apps.boms.models import BomLine
from apps.boms.services import create_bom
from apps.inventory.part_flow_identity import build_part_flow_identity
from . import test_component_parts as fixtures


class PartFaceFabricApiTests(TestCase):
    setUpFixture = fixtures.ComponentPartsApiTests.setUpFixture
    tearDown = fixtures.ComponentPartsApiTests.tearDown
    material = fixtures.ComponentPartsApiTests.material
    get = fixtures.ComponentPartsApiTests.get
    save = fixtures.ComponentPartsApiTests.save
    verify = fixtures.ComponentPartsApiTests.verify

    def setUp(self):
        fixtures.ComponentPartsApiTests.setUp(self)
        self.face = self.material('PART_FACE_FABRIC', '辅料', self.meter_unit)
        self.face.material, self.face.specification = '尼龙面布', '210D/150cm'
        self.face.save()

    def payload(self, *, selected=True):
        sections = fixtures.ComponentPartsApiTests.payload(self)
        key = str(uuid4())
        sections[1]['lines'].append({
            'client_key': key, 'part_name': '部位归属面布', 'unit': '米', 'unit_consumption': '0.2',
            'source_inventory_material_id': str(self.face.pk),
            'material': self.face.material, 'specification': self.face.specification,
        })
        parent = sections[0]['lines'][1]
        parent['specification'] = '成形尺寸60*40cm'
        if selected:
            parent['fabric_source_client_key'] = key
        return sections

    def saved(self, *, selected=True):
        response = self.save(self.payload(selected=selected))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']['sections']

    def parent_row(self, sections):
        return next(line for section in sections for line in section['lines']
                    if line['component_kind'] == 'SEWN_PART')

    def parent(self):
        return BomLine.objects.get(section__bom=self.bom, component_kind='SEWN_PART')

    def test_unsaved_parent_source_resolves_without_changing_piece_or_part_specification(self):
        saved = self.saved()
        part = self.parent()
        piece = part.cut_pieces.get()
        self.assertNotEqual(part.fabric_source_line_id, piece.fabric_source_line_id)
        self.assertEqual((part.specification, piece.specification), ('成形尺寸60*40cm', '55*111cm'))
        self.assertEqual(piece.material, '珍珠棉')
        self.assertEqual(part.material, '')
        self.assertEqual(part.total_purchase_quantity, '')
        self.assertEqual(self.parent_row(saved)['fabric_source_line_id'], str(part.fabric_source_line_id))
        self.assertEqual(component_source_materials(part)[0]['source_bom_line_id'], str(part.fabric_source_line_id))
        verified = self.verify()
        self.assertEqual(verified.status_code, 200, verified.data)

    def test_copy_rebinds_parent_and_child_sources_and_preserves_source_identities(self):
        self.saved()
        original = self.parent()
        copied = create_bom(product_line=self.product_line, creation_method='COPY', source_bom=self.bom,
                            actor_employee=self.employee)
        part = BomLine.objects.get(section__bom=copied, component_kind='SEWN_PART')
        piece = part.cut_pieces.get()
        self.assertEqual(part.fabric_source_line.section.bom_id, copied.pk)
        self.assertNotEqual(part.fabric_source_line_id, original.fabric_source_line_id)
        self.assertEqual(part.fabric_source_line.component_identity, original.fabric_source_line.component_identity)
        self.assertEqual(piece.fabric_source_line.section.bom_id, copied.pk)
        self.assertNotEqual(part.fabric_source_line_id, piece.fabric_source_line_id)
        self.assertEqual(part.specification, original.specification)

    def test_unused_selection_changes_no_inventory_identity_or_child_quantity(self):
        saved = self.saved(selected=False)
        part = self.parent()
        piece = part.cut_pieces.get()
        sewing = SimpleNamespace(pk=uuid4(), craft_type='EXTERNAL', outsourcing_code='SEWING')
        cutting = SimpleNamespace(pk=uuid4(), craft_type='INTERNAL', plan_category='CUTTING')
        before_part = build_part_flow_identity(bom_line=part, completed_craft=sewing, unit=self.part_unit)
        before_piece = build_part_flow_identity(bom_line=piece, completed_craft=cutting, unit=self.piece_unit)
        before_child = (piece.fabric_source_line_id, piece.specification, piece.total_consumption, piece.pieces_per_part)
        source = BomLine.objects.get(section__bom=self.bom, raw_values__source_inventory_material_id=str(self.face.pk))
        self.parent_row(saved)['fabric_source_line_id'] = str(source.pk)
        result = self.save(saved)
        self.assertEqual(result.status_code, 200, result.data)
        part.refresh_from_db()
        piece.refresh_from_db()
        self.assertEqual(build_part_flow_identity(bom_line=part, completed_craft=sewing, unit=self.part_unit), before_part)
        self.assertEqual(build_part_flow_identity(bom_line=piece, completed_craft=cutting, unit=self.piece_unit), before_piece)
        self.assertEqual((piece.fabric_source_line_id, piece.specification, piece.total_consumption, piece.pieces_per_part), before_child)

    def test_foreign_and_unknown_source_ids_are_rejected_without_writes(self):
        saved = self.saved()
        copied = create_bom(product_line=self.product_line, creation_method='COPY', source_bom=self.bom,
                            actor_employee=self.employee)
        foreign = BomLine.objects.get(section__bom=copied, component_kind='SEWN_PART').fabric_source_line_id
        before = list(BomLine.objects.filter(section__bom=self.bom).order_by('pk').values())
        for source_id in (foreign, uuid4()):
            payload = deepcopy(saved)
            self.parent_row(payload)['fabric_source_line_id'] = str(source_id)
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)
            self.assertEqual(list(BomLine.objects.filter(section__bom=self.bom).order_by('pk').values()), before)

    def test_deleting_parent_only_source_requires_clearing_the_unused_parent_link(self):
        saved = self.saved()
        part = self.parent()
        removed_id = str(part.fabric_source_line_id)
        for section in saved:
            section['lines'] = [line for line in section['lines'] if line['id'] != removed_id]
        result = self.save(saved)
        self.assertEqual(result.status_code, 400, result.data)
        self.assertTrue(BomLine.objects.filter(pk=removed_id).exists())
        self.parent_row(saved)['fabric_source_line_id'] = None
        result = self.save(saved)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(BomLine.objects.filter(pk=removed_id).exists())
        self.assertIsNone(self.parent().fabric_source_line_id)

    def test_typed_component_cannot_be_parent_raw_source(self):
        saved = self.saved()
        for invalid_id in (self.parent().pk, self.parent().cut_pieces.get().pk):
            payload = deepcopy(saved)
            self.parent_row(payload)['fabric_source_line_id'] = str(invalid_id)
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)

    def test_confirmation_validates_selected_parent_raw_material_and_keeps_empty_legacy_optional(self):
        self.saved()
        lines = list(BomLine.objects.filter(section__bom=self.bom).select_related('section', 'fabric_source_line'))
        validate_fabric_links(lines, require_complete=True)
        self.face.archived_at = timezone.now()
        self.face.save()
        with self.assertRaisesMessage(ValidationError, '部位'):
            validate_fabric_links(lines, require_complete=True)
        part = next(line for line in lines if line.component_kind == 'SEWN_PART')
        part.fabric_source_line = None
        validate_fabric_links(lines, require_complete=True)

    def test_used_parent_rejects_changing_or_clearing_selected_source(self):
        saved = self.saved()
        part = self.parent()
        before = part.fabric_source_line_id
        with patch('apps.boms.component_parts._used_component_identities', return_value={part.component_identity}):
            for source_id in (None, str(part.cut_pieces.get().fabric_source_line_id)):
                payload = deepcopy(saved)
                self.parent_row(payload)['fabric_source_line_id'] = source_id
                result = self.save(payload)
                self.assertEqual(result.status_code, 400, result.data)
                part.refresh_from_db()
                self.assertEqual(part.fabric_source_line_id, before)

    def test_real_used_child_also_blocks_adding_source_to_legacy_parent(self):
        from apps.material_issues.models import OrderSemiFinishedRequirement
        from apps.workshop_config.models import Craft
        saved = self.saved(selected=False)
        part = self.parent()
        piece = part.cut_pieces.get()
        craft, _ = Craft.objects.get_or_create(craft_type='EXTERNAL', outsourcing_code='SEWING',
                                               defaults={'name': '归属面布冻结测试车缝'})
        OrderSemiFinishedRequirement.objects.create(production_task=self.bom.production_task,
            product_line=self.product_line, component_identity=piece.component_identity, bom_line=piece,
            completed_craft=craft, unit=self.piece_unit, identity_key='c' * 64,
            identity_snapshot={'test': '裁片已领保护部位关联'}, source_revision_hash='d' * 64,
            required_quantity=6000, internal_issued_quantity=1)
        source = BomLine.objects.get(section__bom=self.bom, raw_values__source_inventory_material_id=str(self.face.pk))
        self.parent_row(saved)['fabric_source_line_id'] = str(source.pk)
        result = self.save(saved)
        self.assertEqual(result.status_code, 400, result.data)
        part.refresh_from_db()
        self.assertIsNone(part.fabric_source_line_id)
