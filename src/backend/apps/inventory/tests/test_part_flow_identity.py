from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.inventory.part_flow_identity import build_part_flow_identity
from apps.inventory.public_stock_identity import _make_identity, validate_public_identity
from apps.inventory.stock_services import InventoryStockValidationError


class PartFlowIdentityTests(SimpleTestCase):
    def setUp(self):
        self.unit = SimpleNamespace(pk=uuid4(), unit_name='片')
        self.part_unit = SimpleNamespace(pk=uuid4(), unit_name='个')
        self.cutting = SimpleNamespace(pk=uuid4(), craft_type='INTERNAL', plan_category='CUTTING')
        self.sewing = SimpleNamespace(pk=uuid4(), craft_type='EXTERNAL', outsourcing_code='SEWING')
        section = SimpleNamespace(bom_id=uuid4())
        self.source = SimpleNamespace(section=section, material_catalog_id=None, material='涤纶',
            specification='300D', unit='米', raw_values={'fabric_color_name': '黑色'})
        self.part = SimpleNamespace(pk=uuid4(), component_kind='SEWN_PART', section=section,
            part_name='外袋', specification='', unit='个', parts_per_product=1, parent_part_id=None)
        self.piece = SimpleNamespace(component_kind='CUT_PIECE', section=section, part_name='大片', unit='片',
            specification='98*21CM', parent_part=self.part, parent_part_id=self.part.pk,
            pieces_per_part=2, fabric_source_line=self.source)
        self.part.cut_pieces = SimpleNamespace(all=lambda: [self.piece])

    def test_cut_piece_and_sewn_part_are_distinct_frozen_objects(self):
        piece = build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)
        part = build_part_flow_identity(bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit)
        self.assertNotEqual(piece['identity_key'], part['identity_key'])
        self.assertEqual(piece['identity_snapshot']['semi_kind'], 'CUT_PIECE')
        self.assertEqual(part['identity_snapshot']['semi_kind'], 'SEWN_PART')
        self.assertEqual(validate_public_identity(piece), piece)
        self.assertEqual(validate_public_identity(part), part)

    def test_order_usage_does_not_change_piece_identity_but_composition_changes_part(self):
        before_piece = build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)
        before_part = build_part_flow_identity(bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit)
        self.part.parts_per_product = 3
        self.assertEqual(before_part, build_part_flow_identity(bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit))
        self.piece.pieces_per_part = 3
        self.assertEqual(before_piece, build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit))
        self.assertNotEqual(before_part['identity_key'], build_part_flow_identity(
            bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit)['identity_key'])

    def test_cotton_is_a_piece_and_wrong_stage_or_missing_source_is_rejected(self):
        self.source.material = '棉'
        self.source.specification = '200g'
        self.source.raw_values = {}
        identity = build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)
        self.assertEqual(identity['identity_snapshot']['material'], '棉')
        with self.assertRaises(InventoryStockValidationError):
            build_part_flow_identity(bom_line=self.piece, completed_craft=self.sewing, unit=self.unit)
        self.piece.fabric_source_line = None
        with self.assertRaises(InventoryStockValidationError):
            build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)

    def test_frozen_identity_rejects_tampered_composition(self):
        identity = build_part_flow_identity(bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit)
        identity['identity_snapshot']['composition'][0]['quantity'] = 99
        with self.assertRaises(InventoryStockValidationError):
            validate_public_identity(identity)

    def test_printed_piece_stays_a_piece_and_belongs_to_its_order_and_component(self):
        self.piece.section.bom = SimpleNamespace(product_line_id=uuid4())
        self.piece.component_identity = uuid4()
        silk = SimpleNamespace(pk=uuid4(), craft_type='EXTERNAL', outsourcing_code='SCREEN_PRINTING')
        normal = build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)
        printed = build_part_flow_identity(bom_line=self.piece, completed_craft=silk, unit=self.unit)
        self.assertEqual(validate_public_identity(printed), printed)
        self.assertEqual(printed['identity_snapshot']['semi_kind'], 'CUT_PIECE')
        self.assertEqual(printed['identity_snapshot']['composition'], normal['identity_snapshot']['composition'])
        self.assertNotEqual(printed['identity_key'], normal['identity_key'])
        self.piece.section.bom.product_line_id = uuid4()
        other_order = build_part_flow_identity(bom_line=self.piece, completed_craft=silk, unit=self.unit)
        self.assertNotEqual(printed['identity_key'], other_order['identity_key'])
        self.piece.component_identity = uuid4()
        other_piece = build_part_flow_identity(bom_line=self.piece, completed_craft=silk, unit=self.unit)
        self.assertNotEqual(other_order['identity_key'], other_piece['identity_key'])

    def reference(self, line, attributes, *, marked=True):
        line.material_selection_snapshot = {
            'selection_kind': 'BOM_COMPONENT_REFERENCE', 'attributes': attributes,
            'catalog_id': str(uuid4()), 'catalog_version': 'initial',
        }
        if marked:
            line.material_selection_snapshot['identity_attributes_version'] = 1

    def part_identity(self):
        return build_part_flow_identity(bom_line=self.part, completed_craft=self.sewing, unit=self.part_unit)

    def piece_identity(self):
        return build_part_flow_identity(bom_line=self.piece, completed_craft=self.cutting, unit=self.unit)

    def test_unmarked_references_keep_the_exact_legacy_snapshot_and_hash(self):
        legacy = self.part_identity()
        self.reference(self.part, {'model': '旧图号'}, marked=False)
        self.reference(self.piece, {'process': '旧做法'}, marked=False)
        self.assertEqual(self.part_identity(), legacy)
        self.assertEqual(validate_public_identity(legacy), legacy)
        self.assertNotIn('component_attributes', legacy['identity_snapshot'])
        self.assertNotIn('component_attributes', legacy['identity_snapshot']['composition'][0]['piece'])
        self.reference(self.part, {})
        self.reference(self.piece, {})
        self.assertEqual(self.part_identity(), legacy)

    def test_distinct_parent_attributes_do_not_share_inventory(self):
        legacy = self.part_identity()
        piece_before = self.piece_identity()
        self.reference(self.part, {'model': '椅面 A', 'process': '单线'})
        first = self.part_identity()
        self.assertEqual(first['identity_snapshot']['schema_version'], 3)
        self.assertEqual(first['identity_snapshot']['component_attributes'], {'model': '椅面 A', 'process': '单线'})
        self.assertEqual(first['identity_snapshot']['composition'][0]['piece']['component_attributes'], {})
        self.assertNotEqual(first['identity_key'], legacy['identity_key'])
        self.part.material_selection_snapshot['attributes']['process'] = '双线'
        self.assertNotEqual(self.part_identity()['identity_key'], first['identity_key'])
        self.assertEqual(self.piece_identity(), piece_before)
        self.assertEqual(validate_public_identity(first), first)

    def test_piece_attributes_also_separate_the_composed_parent(self):
        parent_before = self.part_identity()
        piece_before = self.piece_identity()
        self.reference(self.piece, {'model': '大片 A'})
        parent, piece = self.part_identity(), self.piece_identity()
        self.assertNotEqual(parent['identity_key'], parent_before['identity_key'])
        self.assertNotEqual(piece['identity_key'], piece_before['identity_key'])
        self.assertEqual(parent['identity_snapshot']['component_attributes'], {})
        self.assertEqual(parent['identity_snapshot']['composition'][0]['piece']['component_attributes'], {'model': '大片 A'})
        self.assertEqual(piece['identity_snapshot']['component_attributes'], {'model': '大片 A'})
        self.assertEqual(validate_public_identity(parent), parent)
        self.assertEqual(validate_public_identity(piece), piece)
        self.piece.material_selection_snapshot['attributes']['model'] = '大片 B'
        self.assertNotEqual(self.part_identity()['identity_key'], parent['identity_key'])
        self.assertNotEqual(self.piece_identity()['identity_key'], piece['identity_key'])

    def test_attribute_order_catalog_revision_prices_and_target_do_not_change_identity(self):
        self.reference(self.part, {'model': '椅面 A', 'process': '单线'})
        before = self.part_identity()
        self.part.material_selection_snapshot.update(
            attributes={'process': '单线', 'model': '椅面 A'}, catalog_version='refreshed',
            catalog_id=str(uuid4()), unit_price='9.25',
        )
        self.part.parts_per_product = 8
        self.assertEqual(self.part_identity(), before)
        self.piece.pieces_per_part = 3
        self.assertNotEqual(self.part_identity()['identity_key'], before['identity_key'])

    def test_extended_snapshot_rejects_invalid_attributes_even_with_matching_hash(self):
        self.reference(self.part, {'model': '椅面 A'})
        valid = self.part_identity()['identity_snapshot']
        for attributes in ({'unknown': 'A'}, {'model': ''}, {'model': '/'}, {'model': None},
                           {'model': True}, {'model': ['A']}, {'model': ' A '}, []):
            with self.subTest(attributes=attributes):
                snapshot = deepcopy(valid)
                snapshot['component_attributes'] = attributes
                with self.assertRaises(InventoryStockValidationError):
                    validate_public_identity(_make_identity(snapshot))
        for change in ('empty', 'missing_piece_field', 'extra_piece_field', 'extra_root_field'):
            with self.subTest(change=change):
                snapshot = deepcopy(valid)
                if change == 'empty':
                    snapshot['component_attributes'] = {}
                elif change == 'missing_piece_field':
                    del snapshot['composition'][0]['piece']['component_attributes']
                elif change == 'extra_piece_field':
                    snapshot['composition'][0]['piece']['price'] = '5'
                else:
                    snapshot['catalog_version'] = 'new'
                with self.assertRaises(InventoryStockValidationError):
                    validate_public_identity(_make_identity(snapshot))

    def test_piece_attributes_cannot_disagree_with_composition_or_use_invalid_marker(self):
        self.reference(self.piece, {'model': '大片 A'})
        snapshot = self.piece_identity()['identity_snapshot']
        snapshot['composition'][0]['piece']['component_attributes'] = {'model': '大片 B'}
        with self.assertRaises(InventoryStockValidationError):
            validate_public_identity(_make_identity(snapshot))
        for version in (True, 0, 2, '1'):
            with self.subTest(version=version):
                self.piece.material_selection_snapshot['identity_attributes_version'] = version
                with self.assertRaises(InventoryStockValidationError):
                    self.piece_identity()
