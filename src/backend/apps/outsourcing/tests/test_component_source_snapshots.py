from django.test import SimpleTestCase

from apps.outsourcing.component_source_snapshots import frozen_component_source_materials


class ComponentSourceSnapshotTests(SimpleTestCase):
    def identity(self, *sources):
        return {'identity_snapshot': {'composition': [{'piece': {'source': source}} for source in sources]}}

    def test_saved_grouped_sources_are_copied_without_reading_current_bom(self):
        rows = [{'source_bom_line_id': 'saved', 'name': '布料', 'material': '涤纶',
                 'color': '蓝', 'color_code': 'B1', 'fabric_spec': '600D', 'width': '150', 'unit': '米'}]
        snapshot = {'component_source_materials': rows}
        result = frozen_component_source_materials(snapshot)
        self.assertEqual(result, rows)
        result[0]['material'] = '后改'
        self.assertEqual(rows[0]['material'], '涤纶')

    def test_legacy_catalog_source_name_is_not_mislabeled_as_material(self):
        identity = self.identity({'identity_key': 'saved-raw-identity', 'material': '保存牛津布',
            'specification': '600D', 'color': '蓝色', 'unit': '米'})
        self.assertEqual(frozen_component_source_materials({'public_output_identity': identity}), [{
            'source_bom_line_id': '', 'name': '保存牛津布', 'material': '', 'color': '蓝色',
            'color_code': '', 'fabric_spec': '600D', 'width': '', 'unit': '米'}])

    def test_legacy_plain_sources_keep_material_and_pairing_and_deduplicate(self):
        fabric = {'identity_key': '', 'material': '涤纶', 'specification': '600D', 'color': '蓝', 'unit': '米'}
        cotton = {'identity_key': '', 'material': '无胶棉', 'specification': '200g', 'color': '白', 'unit': '米'}
        rows = frozen_component_source_materials({}, self.identity(fabric, cotton, fabric))
        self.assertEqual([(row['name'], row['material'], row['color'], row['fabric_spec']) for row in rows],
                         [('', '涤纶', '蓝', '600D'), ('', '无胶棉', '白', '200g')])
        self.assertTrue(all(row['width'] == row['color_code'] == '' for row in rows))

    def test_reference_attributes_are_never_used_as_source_and_empty_saved_list_stays_empty(self):
        self.assertEqual(frozen_component_source_materials({'component_material_selection_snapshot': {
            'attributes': {'material': '错误父材质', 'color': '错误父颜色'}}}), [])
        self.assertEqual(frozen_component_source_materials({'component_source_materials': []},
            self.identity({'material': '不应回填'})), [])
