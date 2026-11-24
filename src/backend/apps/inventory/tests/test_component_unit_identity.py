from copy import deepcopy
from uuid import UUID

from django.test import SimpleTestCase

from apps.inventory.part_flow_identity import build_part_flow_identity
from apps.inventory.public_stock_identity import _make_identity, validate_public_identity
from apps.inventory.stock_services import InventoryStockValidationError
from . import test_part_flow_identity as fixtures


class ComponentUnitIdentityTests(SimpleTestCase):
    def setUp(self):
        fixtures.PartFlowIdentityTests.setUp(self)
        self.unit.pk = UUID(int=1)
        self.part_unit.pk = UUID(int=2)
        self.cutting.pk = UUID(int=3)
        self.sewing.pk = UUID(int=4)

    def identity(self, *, parent=False):
        return build_part_flow_identity(bom_line=self.part if parent else self.piece,
            completed_craft=self.sewing if parent else self.cutting,
            unit=self.part_unit if parent else self.unit)

    def test_existing_piece_and_parent_keep_exact_old_snapshot_and_hash(self):
        piece = {'name': '大片', 'specification': '98*21CM', 'source': {
            'identity_key': '', 'material': '涤纶', 'specification': '300D', 'color': '黑色', 'unit': '米'}}
        for parent in (False, True):
            unit = self.part_unit if parent else self.unit
            craft = self.sewing if parent else self.cutting
            expected = {
                'schema_version': 3, 'stock_kind': 'SEMI', 'semi_kind': 'SEWN_PART' if parent else 'CUT_PIECE',
                'unit_id': str(unit.pk), 'unit_name': unit.unit_name,
                'category': '车缝部位' if parent else '裁片', 'part_name': '外袋' if parent else '大片',
                'specification': '' if parent else '98*21CM', 'material': '涤纶', 'color': '黑色',
                'completed_craft': {'id': str(craft.pk), 'craft_type': 'EXTERNAL' if parent else 'INTERNAL',
                                    'code': 'SEWING' if parent else 'CUTTING'},
                'composition': [{'piece': piece, 'quantity': 2 if parent else 1}],
            }
            identity = self.identity(parent=parent)
            self.assertEqual(identity, _make_identity(expected))
            self.assertEqual(validate_public_identity(identity), identity)

    def test_non_piece_unit_changes_both_child_and_parent_identity_without_conversion(self):
        before_piece, before_part = self.identity(), self.identity(parent=True)
        self.piece.unit = self.unit.unit_name = '套'
        piece, part = self.identity(), self.identity(parent=True)
        self.assertNotEqual(piece['identity_key'], before_piece['identity_key'])
        self.assertNotEqual(part['identity_key'], before_part['identity_key'])
        self.assertEqual(piece['identity_snapshot']['composition'][0]['piece']['unit_name'], '套')
        self.assertEqual(part['identity_snapshot']['composition'][0]['quantity'], 2)
        self.assertEqual(validate_public_identity(piece), piece)
        self.assertEqual(validate_public_identity(part), part)
        self.piece.unit = self.unit.unit_name = '片'
        self.assertEqual(self.identity(), before_piece)
        self.assertEqual(self.identity(parent=True), before_part)

    def test_non_piece_unit_and_attribute_extension_are_compatible(self):
        self.piece.unit = self.unit.unit_name = '米'
        self.piece.material_selection_snapshot = {'selection_kind': 'BOM_COMPONENT_REFERENCE',
            'identity_attributes_version': 1, 'attributes': {'model': '大片A'}}
        for parent in (False, True):
            identity = self.identity(parent=parent)
            piece = identity['identity_snapshot']['composition'][0]['piece']
            self.assertEqual(piece['unit_name'], '米')
            self.assertEqual(piece['component_attributes'], {'model': '大片A'})
            self.assertEqual(validate_public_identity(identity), identity)

    def test_builder_requires_real_bom_unit_and_matching_stock_unit(self):
        for unit in ('', None, '个'):
            self.piece.unit = unit
            with self.assertRaises(InventoryStockValidationError):
                self.identity()

    def test_validator_rejects_noncanonical_or_mismatching_composition_units(self):
        baseline = self.identity()['identity_snapshot']
        for unit in ('', ' ', '-', '片', '套 ', True, 1, None):
            with self.subTest(unit=unit):
                snapshot = deepcopy(baseline)
                snapshot['composition'][0]['piece']['unit_name'] = unit
                with self.assertRaises(InventoryStockValidationError):
                    validate_public_identity(_make_identity(snapshot))
        for top, child in (('个', None), ('套', '个'), ('片', '套')):
            snapshot = deepcopy(baseline)
            snapshot['unit_name'] = top
            if child is not None:
                snapshot['composition'][0]['piece']['unit_name'] = child
            with self.assertRaises(InventoryStockValidationError):
                validate_public_identity(_make_identity(snapshot))
