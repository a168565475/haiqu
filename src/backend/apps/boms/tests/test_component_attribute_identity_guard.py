from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.component_parts import validate_used_component_structure


class ComponentAttributeIdentityGuardTests(SimpleTestCase):
    def setUp(self):
        section = SimpleNamespace(bom_id=uuid4(), title='裁剪明细')
        source = SimpleNamespace(component_identity=uuid4(), section=section, material_catalog_id=None,
            material='涤纶', specification='300D', unit='米', raw_values={'fabric_color_name': '黑色'})
        self.part = SimpleNamespace(pk=uuid4(), component_identity=uuid4(), component_kind='SEWN_PART',
            section=section, part_name='椅面', specification='50*40', unit='个', parts_per_product=1,
            parent_part_id=None, material_catalog_id=uuid4(),
            material_selection_snapshot={'selection_kind': 'BOM_COMPONENT_REFERENCE', 'attributes': {'model': '椅面 A'}})
        self.piece = SimpleNamespace(pk=uuid4(), component_identity=uuid4(), component_kind='CUT_PIECE',
            section=section, part_name='大片', specification='50*40', unit='片', pieces_per_part=2,
            parent_part=self.part, parent_part_id=self.part.pk, fabric_source_line=source,
            material_catalog_id=uuid4(), material_selection_snapshot={
                'selection_kind': 'BOM_COMPONENT_REFERENCE', 'attributes': {'process': '单线'}})
        self.lines = [self.part, self.piece]

    def test_used_parent_rejects_marker_only_change_on_parent_or_child(self):
        with patch('apps.boms.component_parts._used_component_identities', return_value={self.part.component_identity}):
            for index in (0, 1):
                with self.subTest(index=index):
                    planned = deepcopy(self.lines)
                    planned[index].material_selection_snapshot['identity_attributes_version'] = 1
                    with self.assertRaises(ValidationError):
                        validate_used_component_structure(SimpleNamespace(), self.lines, planned)

    def test_used_child_freezes_the_whole_parent_including_markers_and_composition(self):
        with patch('apps.boms.component_parts._used_component_identities', return_value={self.piece.component_identity}):
            for change in ('parent_marker', 'child_marker', 'attributes', 'pieces_per_part'):
                with self.subTest(change=change):
                    planned = deepcopy(self.lines)
                    if change == 'parent_marker':
                        planned[0].material_selection_snapshot['identity_attributes_version'] = 1
                    elif change == 'child_marker':
                        planned[1].material_selection_snapshot['identity_attributes_version'] = 1
                    elif change == 'attributes':
                        planned[1].material_selection_snapshot['attributes']['process'] = '双线'
                    else:
                        planned[1].pieces_per_part = 3
                    with self.assertRaises(ValidationError):
                        validate_used_component_structure(SimpleNamespace(), self.lines, planned)

    def test_unused_upgrade_and_used_target_quantity_changes_remain_allowed(self):
        planned = deepcopy(self.lines)
        planned[0].material_selection_snapshot['identity_attributes_version'] = 1
        with patch('apps.boms.component_parts._used_component_identities', return_value=set()):
            validate_used_component_structure(SimpleNamespace(), self.lines, planned)
        planned = deepcopy(self.lines)
        planned[0].parts_per_product = 3
        planned[0].material_selection_snapshot['catalog_version'] = 'refreshed'
        with patch('apps.boms.component_parts._used_component_identities', return_value={self.piece.component_identity}):
            validate_used_component_structure(SimpleNamespace(), self.lines, planned)
