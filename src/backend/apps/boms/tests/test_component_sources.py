from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.component_sources import component_source_materials


class ComponentSourceMaterialsTests(SimpleTestCase):
    def setUp(self):
        self.bom_id = uuid4()
        self.cut_section = SimpleNamespace(bom_id=self.bom_id, section_type='FABRIC', title='裁剪明细')
        self.cut_section_id = uuid4()
        self.pieces = []
        self.part = SimpleNamespace(component_kind='SEWN_PART', section=self.cut_section,
            section_id=self.cut_section_id, cut_pieces=SimpleNamespace(all=lambda: self.pieces),
            material='父部位伪造材质', specification='父部位成形尺寸', fabric_source_line=None,
            material_selection_snapshot={'attributes': {'material': '伪造', 'color': '错误颜色',
                                                       'fabric_spec': '错误规格', 'width': '错误门幅'}})

    def source(self, *, name='面布', material='涤纶', color='蓝色', spec='600D', width='150cm', cotton=False):
        return SimpleNamespace(pk=uuid4(), component_kind='', material_catalog_id=None,
            material_selection_snapshot={}, section=SimpleNamespace(bom_id=self.bom_id, section_type='FABRIC',
                title='辅料类' if cotton else '面料类'), part_name=name, material=material,
            specification=spec, unit='米', raw_values={
                ('accessory_color' if cotton else 'fabric_color_name'): color, 'fabric_width': width})

    def piece(self, source):
        line = SimpleNamespace(component_kind='CUT_PIECE', section=self.cut_section,
            section_id=self.cut_section_id, fabric_source_line=source, specification='裁片实际尺寸',
            material='裁片旧材质', material_selection_snapshot={'attributes': {'color': '裁片错误颜色'}})
        self.pieces.append(line)
        return line

    def test_piece_reads_saved_source_attributes_and_keeps_color_code(self):
        source = self.source(material='旧兼容材质', color='旧兼容颜色', spec='旧兼容规格')
        source.material_catalog_id = uuid4()
        source.material_selection_snapshot = {
            'name': '已保存原布品名', 'category_key': 'FABRIC', 'processing_state': 'RAW',
            'attributes': {'material': '涤纶', 'color': '藏蓝', 'fabric_spec': '420D', 'width': '160cm'},
            'color_name': '藏蓝', 'color_code': '19-4025', 'unit_name': '米',
        }
        piece = self.piece(source)
        self.assertEqual(component_source_materials(piece), [{
            'source_bom_line_id': str(source.pk), 'name': '已保存原布品名', 'material': '涤纶',
            'color': '藏蓝', 'color_code': '19-4025', 'fabric_spec': '420D', 'width': '160cm', 'unit': '米',
        }])
        self.assertEqual(piece.specification, '裁片实际尺寸')

    def test_parent_keeps_each_source_material_color_and_specification_paired(self):
        blue = self.source(name='蓝色面布', color='蓝色', spec='600D')
        red = self.source(name='红色里布', material='尼龙', color='红色', spec='210D', width='140cm')
        cotton = self.source(name='珍珠棉', material='EPE', color='白色', spec='5mm', width='120cm', cotton=True)
        for source in (blue, red, cotton):
            self.piece(source)
        rows = component_source_materials(self.part)
        self.assertEqual([(row['name'], row['material'], row['color'], row['fabric_spec'], row['width']) for row in rows], [
            ('蓝色面布', '涤纶', '蓝色', '600D', '150cm'),
            ('红色里布', '尼龙', '红色', '210D', '140cm'),
            ('珍珠棉', 'EPE', '白色', '5mm', '120cm'),
        ])
        self.assertTrue(all(isinstance(value, str) for row in rows for value in row.values()))

    def test_deduplicates_source_ids_without_merging_distinct_identical_source_lines(self):
        source = self.source()
        self.piece(source)
        self.piece(source)
        another = deepcopy(source)
        another.pk = uuid4()
        self.piece(another)
        self.assertEqual([row['source_bom_line_id'] for row in component_source_materials(self.part)],
                         [str(source.pk), str(another.pk)])

    def test_parent_reference_and_price_cannot_override_the_actual_source(self):
        source = self.source()
        self.piece(source)
        before = component_source_materials(self.part)
        self.part.material_selection_snapshot['attributes'].update(material='另一材质', color='另一颜色')
        self.part.material_selection_snapshot.update(catalog_version='refreshed', unit_price='99.00')
        self.assertEqual(component_source_materials(self.part), before)

    def test_explicit_part_source_takes_precedence_without_changing_child_sources(self):
        child_source = self.source(name='裁片棉料', cotton=True)
        piece = self.piece(child_source)
        selected = self.source(name='部位面布', material='尼龙', color='红色', spec='210D')
        self.part.fabric_source_line = selected
        rows = component_source_materials(self.part)
        self.assertEqual([(row['source_bom_line_id'], row['name'], row['material'], row['color'], row['fabric_spec']) for row in rows],
                         [(str(selected.pk), '部位面布', '尼龙', '红色', '210D')])
        self.assertEqual(component_source_materials(piece)[0]['source_bom_line_id'], str(child_source.pk))
        self.assertEqual(self.part.specification, '父部位成形尺寸')

    def test_explicit_part_source_still_requires_same_bom_raw_source(self):
        self.piece(self.source())
        source = self.source()
        self.part.fabric_source_line = source
        for invalid in ('foreign', 'typed', 'processed'):
            with self.subTest(invalid=invalid):
                source.section.bom_id, source.component_kind = self.bom_id, ''
                source.material_catalog_id, source.material_selection_snapshot = None, {}
                if invalid == 'foreign':
                    source.section.bom_id = uuid4()
                elif invalid == 'typed':
                    source.component_kind = 'CUT_PIECE'
                else:
                    source.material_catalog_id = uuid4()
                    source.material_selection_snapshot = {'category_key': 'FABRIC', 'processing_state': 'PROCESSED'}
                with self.assertRaises(ValidationError):
                    component_source_materials(self.part)

    def test_missing_source_does_not_guess_and_optional_source_fields_are_empty_strings(self):
        piece = self.piece(None)
        self.assertEqual(component_source_materials(piece), [])
        self.assertEqual(component_source_materials(self.part), [])
        source = self.source(material='', color='', spec='', width='')
        source.part_name, source.unit = '', ''
        self.piece(source)
        row = component_source_materials(self.part)[0]
        self.assertEqual({key: value for key, value in row.items() if key != 'source_bom_line_id'}, {
            'name': '', 'material': '', 'color': '', 'color_code': '', 'fabric_spec': '', 'width': '', 'unit': '',
        })

    def test_foreign_bom_or_invalid_source_section_is_rejected(self):
        source = self.source()
        piece = self.piece(source)
        for change in ('source_bom', 'source_section', 'piece_bom', 'piece_section', 'processed_source'):
            with self.subTest(change=change):
                source.section.bom_id, source.section.title = self.bom_id, '面料类'
                source.material_catalog_id, source.material_selection_snapshot = None, {}
                piece.section = self.cut_section
                piece.section_id = self.cut_section_id
                if change == 'source_bom':
                    source.section.bom_id = uuid4()
                elif change == 'source_section':
                    source.section.title = '裁剪明细'
                elif change == 'piece_bom':
                    piece.section = SimpleNamespace(bom_id=uuid4())
                elif change == 'piece_section':
                    piece.section_id = uuid4()
                else:
                    source.material_catalog_id = uuid4()
                    source.material_selection_snapshot = {'category_key': 'FABRIC', 'processing_state': 'PROCESSED'}
                with self.assertRaises(ValidationError):
                    component_source_materials(self.part)
