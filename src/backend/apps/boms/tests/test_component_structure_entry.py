from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError

from ..api.serializers import BomUpdateInputSerializer
from ..component_structure import component_structure_data, imported_component_structure, require_component_structure
from ..models import BomLine, BomSection
from ..services import create_bom
from . import test_material_flow_bom as fixtures


class ComponentStructureEntryTests(SimpleTestCase):
    def test_only_marked_new_boms_require_legacy_cutting_rows_to_be_completed(self):
        line = SimpleNamespace(component_kind='', section=SimpleNamespace(title='裁剪明细'))
        historical = SimpleNamespace(source_metadata={})
        current = SimpleNamespace(source_metadata={'component_structure_version': 1})
        self.assertFalse(component_structure_data(historical, [line])['pending'])
        require_component_structure(historical, [line])
        self.assertTrue(component_structure_data(current, [line])['pending'])
        with self.assertRaisesMessage(ValidationError, '部位与裁片组成待完善'):
            require_component_structure(current, [line])

    def test_no_cutting_or_typed_rows_are_not_reported_as_legacy_pending(self):
        bom = SimpleNamespace(source_metadata={'component_structure_version': 1})
        for lines in ([], [SimpleNamespace(component_kind='', section=SimpleNamespace(title='管材类'))],
                      [SimpleNamespace(component_kind='CUT_PIECE', section=SimpleNamespace(title='裁剪明细'))]):
            self.assertEqual(component_structure_data(bom, lines), {'required': True, 'pending': False, 'message': ''})
        self.assertTrue(imported_component_structure({'sections': [{'title': '裁剪明细', 'lines': [{}]}]})['pending'])
        self.assertFalse(imported_component_structure({'sections': [{'title': '管材类', 'lines': [{}]}]})['pending'])

    def test_explicit_imported_cutting_header_and_actual_value_require_manual_grouping(self):
        bom = SimpleNamespace(source_metadata={'component_structure_version': 1})
        for headers, raw_values, quantity in [({'D': '裁片名称'}, {'D': '椅面内衬'}, ''),
                                              ({'G': '裁片量'}, {}, '2')]:
            section = SimpleNamespace(title='面辅料清单', headers=headers)
            line = SimpleNamespace(component_kind='', section=section, raw_values=raw_values, cut_piece_quantity=quantity)
            self.assertTrue(component_structure_data(bom, [line])['pending'])
            self.assertTrue(imported_component_structure({'sections': [{'title': section.title, 'headers': headers,
                'lines': [{'raw_values': raw_values, 'cut_piece_quantity': quantity}]}]})['pending'])
            with self.assertRaisesMessage(ValidationError, '请先整理源表裁片'):
                require_component_structure(bom, [line])

    def test_generic_material_header_or_empty_cutting_columns_do_not_block_raw_material_rows(self):
        bom = SimpleNamespace(source_metadata={'component_structure_version': 1})
        for headers, raw_values, quantity in [({'D': '材料名称'}, {'D': '原布'}, '2'),
                                              ({'D': '裁片名称', 'G': '裁片量'}, {'D': ''}, '')]:
            section = SimpleNamespace(title='面辅料清单', headers=headers)
            line = SimpleNamespace(component_kind='', section=section, raw_values=raw_values, cut_piece_quantity=quantity)
            self.assertFalse(component_structure_data(bom, [line])['pending'])
            self.assertFalse(imported_component_structure({'sections': [{'title': section.title, 'headers': headers,
                'lines': [{'raw_values': raw_values, 'cut_piece_quantity': quantity}]}]})['pending'])

    def test_unmarked_historical_bom_cannot_confirm_mixed_typed_and_unassigned_cutting_rows(self):
        bom = SimpleNamespace(source_metadata={})
        section = SimpleNamespace(title='裁剪明细')
        lines = [SimpleNamespace(component_kind='SEWN_PART', section=section),
                 SimpleNamespace(component_kind='', section=section)]
        state = component_structure_data(bom, lines)
        self.assertTrue(state['required'])
        self.assertTrue(state['pending'])
        with self.assertRaisesMessage(ValidationError, '部位与裁片组成待完善'):
            require_component_structure(bom, lines)
        self.assertEqual(bom.source_metadata, {})

    def test_unmarked_legacy_only_and_fully_typed_boms_keep_their_respective_paths(self):
        bom = SimpleNamespace(source_metadata={})
        section = SimpleNamespace(title='裁剪明细')
        legacy = [SimpleNamespace(component_kind='', section=section)]
        typed = [SimpleNamespace(component_kind='SEWN_PART', section=section),
                 SimpleNamespace(component_kind='CUT_PIECE', section=section),
                 SimpleNamespace(component_kind='', section=SimpleNamespace(title='面料类'))]
        self.assertEqual(component_structure_data(bom, legacy), {'required': False, 'pending': False, 'message': ''})
        self.assertEqual(component_structure_data(bom, typed), {'required': True, 'pending': False, 'message': ''})
        require_component_structure(bom, legacy)
        require_component_structure(bom, typed)
        self.assertEqual(bom.source_metadata, {})


class ComponentStructureEntryApiTests(TestCase):
    setUpFixture = fixtures.MaterialFlowBomTests.setUpFixture
    tearDown = fixtures.MaterialFlowBomTests.tearDown
    material = fixtures.MaterialFlowBomTests.material
    get = fixtures.MaterialFlowBomTests.get
    verify = fixtures.MaterialFlowBomTests.verify

    def setUp(self):
        fixtures.MaterialFlowBomTests.setUp(self)

    def legacy_line(self):
        section = BomSection.objects.create(bom=self.bom, line_number=2, section_type='FABRIC', title='裁剪明细')
        line = BomLine.objects.create(section=section, line_number=1, part_name='源表裁片', unit='套', specification='50*40cm')
        self.bom.line_count = 1
        self.bom.save(update_fields=['line_count'])
        return line

    def test_blank_entry_is_marked_and_client_cannot_remove_or_add_marker(self):
        self.assertEqual(self.bom.source_metadata['component_structure_version'], 1)
        self.assertEqual(self.get().data['data']['component_structure'], {'required': True, 'pending': False, 'message': ''})
        self.assertNotIn('source_metadata', BomUpdateInputSerializer().fields)
        self.bom.source_metadata = {}
        self.bom.save(update_fields=['source_metadata'])
        self.assertNotIn('source_metadata', BomUpdateInputSerializer().fields)
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.source_metadata, {})

    def test_copying_historical_rows_requires_completion_without_mutating_source(self):
        original = self.legacy_line()
        self.bom.source_metadata = {'source_note': '原始表格'}
        self.bom.save(update_fields=['source_metadata'])
        copied = create_bom(product_line=self.product_line, creation_method='COPY', source_bom=self.bom,
            actor_employee=self.employee)
        self.assertEqual(copied.source_metadata, {'source_note': '原始表格', 'component_structure_version': 1})
        copied_line = BomLine.objects.get(section__bom=copied)
        self.assertEqual((copied_line.component_kind, copied_line.parent_part_id, copied_line.unit), ('', None, '套'))
        self.assertTrue(component_structure_data(copied, [copied_line])['pending'])
        self.bom.refresh_from_db()
        self.assertFalse(component_structure_data(self.bom, [original])['required'])

    def test_new_legacy_rows_remain_editable_draft_but_confirmation_is_blocked(self):
        line = self.legacy_line()
        self.assertTrue(self.get().data['data']['component_structure']['pending'])
        response = self.verify()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('部位与裁片组成待完善', str(response.data))
        line.refresh_from_db()
        self.assertEqual((line.component_kind, line.parent_part_id), ('', None))

    def test_excel_import_keeps_unmapped_rows_but_marks_new_bom(self):
        plan = {'metadata': {'source_note': '导入来源'}, 'original_name': 'source.xlsx', 'sheet_name': 'BOM',
            'source_quantity': self.product_line.quantity, 'section_count': 1, 'line_count': 1, 'calculation_summary': {},
            'sections': [{'section_type': 'FABRIC', 'title': '裁剪明细', 'source_title_row': 1,
                'source_header_row': 2, 'headers': {}, 'calculation_rows': [],
                'lines': [{'part_name': '源表裁片', 'unit': '片', 'specification': '50*40cm'}]}]}
        prepared = SimpleNamespace(temporary_path='unused-test.xlsx', original_name='source.xlsx', cleanup=lambda: None)
        with patch('apps.boms.services.prepare_bom_upload', return_value=prepared), \
                patch('apps.boms.services.parse_bom_workbook', return_value=plan), \
                patch('apps.boms.services.persist_prepared_bom_upload', return_value=(None, None)), \
                patch('apps.boms.services.validate_workbook_identity', return_value=[]), \
                patch('apps.boms.services.match_maintenance_configuration', return_value={
                    'matched_count': 0, 'unmatched_count': 0, 'unmatched_values': []}):
            imported = create_bom(product_line=self.product_line, creation_method='IMPORT', uploaded_file=object(),
                actor_employee=self.employee)
        line = BomLine.objects.get(section__bom=imported)
        self.assertEqual(imported.source_metadata, {'source_note': '导入来源', 'component_structure_version': 1})
        self.assertTrue(component_structure_data(imported, [line])['pending'])
        self.assertEqual((line.component_kind, line.parent_part_id), ('', None))
