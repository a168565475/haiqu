from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.reference_data.models import ProductionUnit
from ..models import BomLine
from . import test_component_parts as fixtures


class ComponentSelectableUnitApiTests(TestCase):
    setUpFixture = fixtures.ComponentPartsApiTests.setUpFixture
    tearDown = fixtures.ComponentPartsApiTests.tearDown
    material = fixtures.ComponentPartsApiTests.material
    get = fixtures.ComponentPartsApiTests.get
    save = fixtures.ComponentPartsApiTests.save
    verify = fixtures.ComponentPartsApiTests.verify
    payload = fixtures.ComponentPartsApiTests.payload

    def setUp(self):
        fixtures.ComponentPartsApiTests.setUp(self)
        self.set_unit, _ = ProductionUnit.objects.get_or_create(unit_name='套', defaults={'unit_code': 'CUNITSET'})

    def test_parent_and_piece_keep_their_selected_valid_units_and_integer_counts(self):
        for unit in ('片', '个', '米', '套'):
            with self.subTest(unit=unit):
                payload = self.payload()
                piece, parent = payload[0]['lines']
                piece['unit'], parent['unit'] = unit, '套'
                result = self.save(payload)
                self.assertEqual(result.status_code, 200, result.data)
                saved_piece = BomLine.objects.get(section__bom=self.bom, component_kind='CUT_PIECE')
                self.assertEqual((saved_piece.unit, saved_piece.total_consumption), (unit, '6000'))
                self.assertEqual((saved_piece.parent_part.unit, saved_piece.parent_part.total_consumption), ('套', '2000'))
        verified = self.verify()
        self.assertEqual(verified.status_code, 200, verified.data)

    def test_unknown_inactive_and_archived_piece_units_are_rejected(self):
        ProductionUnit.objects.create(unit_name='停用裁片单位', unit_code='CUNITOFF', status='INACTIVE')
        ProductionUnit.objects.create(unit_name='归档裁片单位', unit_code='CUNITOLD', archived_at=timezone.now())
        for unit in ('不存在裁片单位', '停用裁片单位', '归档裁片单位'):
            payload = self.payload()
            payload[0]['lines'][0]['unit'] = unit
            result = self.save(payload)
            self.assertEqual(result.status_code, 400, result.data)
            self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_empty_piece_unit_can_save_draft_but_is_not_silently_changed_or_confirmed(self):
        payload = self.payload()
        payload[0]['lines'][0]['unit'] = ''
        saved = self.save(payload)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(BomLine.objects.get(section__bom=self.bom, component_kind='CUT_PIECE').unit, '')
        result = self.verify()
        self.assertEqual(result.status_code, 400, result.data)

    def test_selected_meter_unit_does_not_enable_fractional_component_counts(self):
        payload = self.payload()
        payload[0]['lines'][0].update(unit='米', pieces_per_part='1.5')
        result = self.save(payload)
        self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(BomLine.objects.filter(section__bom=self.bom).exists())

    def test_catalog_reference_uses_selected_piece_unit_without_changing_catalog_units(self):
        from django.contrib.auth.models import Permission
        from apps.material_catalog.models import MaterialAllowedUnit, MaterialCatalog
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label='material_catalog', codename='view_materialcatalog'))
        catalog = MaterialCatalog.objects.create(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', name='选单位裁片')
        before = MaterialAllowedUnit.objects.count()
        payload = self.payload()
        payload[0]['lines'][0].update(unit='米', material_catalog_id=str(catalog.pk), material_selection={
            'catalog_version': catalog.updated_at.isoformat(), 'scope': 'BASE', 'processing_state': 'PROCESSED',
            'attributes': {}, 'unit_name': '米'})
        response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.data)
        piece = BomLine.objects.get(section__bom=self.bom, component_kind='CUT_PIECE')
        self.assertEqual((piece.unit, piece.material_selection_snapshot['unit_name']), ('米', '米'))
        self.assertEqual(MaterialAllowedUnit.objects.count(), before)

    def test_used_piece_or_parent_freezes_child_unit_but_unused_unit_can_change(self):
        result = self.save(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        sections = result.data['data']['sections']
        piece = BomLine.objects.get(section__bom=self.bom, component_kind='CUT_PIECE')
        payload = deepcopy(sections)
        next(line for section in payload for line in section['lines']
             if line['component_kind'] == 'CUT_PIECE')['unit'] = '个'
        for used in (piece.component_identity, piece.parent_part.component_identity):
            with patch('apps.boms.component_parts._used_component_identities', return_value={used}):
                blocked = self.save(payload)
                self.assertEqual(blocked.status_code, 400, blocked.data)
                piece.refresh_from_db()
                self.assertEqual(piece.unit, '片')
        changed = self.save(payload)
        self.assertEqual(changed.status_code, 200, changed.data)
        piece.refresh_from_db()
        self.assertEqual(piece.unit, '个')
