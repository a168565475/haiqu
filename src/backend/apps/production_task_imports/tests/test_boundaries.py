import io
import stat
import zipfile

from django.test import SimpleTestCase, override_settings
from ..preprocessing import ManifestError, parse_xml, resolve_part, validate_package
from ..storage import ImportFailure, scan_source
from ..validation import discovery_result, extraction_result, references, schema_for, source_scope, validate_schema, validate_value


class SourceBoundaryTests(SimpleTestCase):
    def package(self, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return zipfile.ZipFile(io.BytesIO(output.getvalue()))

    def test_zip_traversal_and_case_duplicates_rejected(self):
        for entries in ([('../outside.txt', b'x')], [('A.xml', b'x'), ('a.xml', b'y')]):
            with self.subTest(entries=entries), self.package(entries) as archive:
                with self.assertRaises(ManifestError):
                    validate_package(archive)

    def test_symlink_rejected(self):
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.package([(info, b'/etc/passwd')]) as archive:
            with self.assertRaises(ManifestError):
                validate_package(archive)

    def test_encoded_xml_dtd_rejected(self):
        data = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE a [<!ENTITY e "secret">]><a>&e;</a>'.encode('utf-16')
        with self.assertRaises(ManifestError):
            parse_xml(data)

    def test_external_and_escaping_relationship_rejected(self):
        for target in ['https://example.com/file', '../../../../../outside', '..\\secret', '%00x']:
            with self.subTest(target=target), self.assertRaises(ManifestError):
                resolve_part('xl/worksheets/sheet1.xml', target)
        self.assertEqual(resolve_part('xl/worksheets/sheet1.xml', '../drawings/drawing1.xml'), 'xl/drawings/drawing1.xml')

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    def test_disabled_scanner_never_allows_parsing(self):
        with self.assertRaises(ImportFailure) as caught:
            scan_source(None)
        self.assertEqual(caught.exception.code, 'SCAN_UNAVAILABLE')

    def test_strict_schema_rejects_model_database_id(self):
        value = {'schema_version': '1', 'candidates': [], 'auxiliary_sections': [], 'issues': []}
        validate_schema(value, schema_for('discovery'))
        with self.assertRaises(ImportFailure):
            validate_schema({**value, 'product_id': 'invented'}, schema_for('discovery'))

    def test_boolean_number_date_decimal_boundaries(self):
        for name, value in [('quantity', '0'), ('quantity', '1.5'), ('includes_tax', 'false'),
                            ('unit_price_cny', 'NaN'), ('order_date', '2026-02-30'), ('delivery_method', '猜测')]:
            with self.subTest(name=name, value=value), self.assertRaises(ImportFailure):
                validate_value(name, value)
        validate_value('includes_tax', False)
        validate_value('quantity', '500')
        validate_value('order_date', '2026-08-14')

    def test_source_scope_does_not_include_other_sheet(self):
        manifest = {'source_index': {'s1': {'kind': 'sheet_title', 'sheet_part': 'one'},
                                    'c1': {'kind': 'cell', 'sheet_part': 'one'},
                                    'c2': {'kind': 'cell', 'sheet_part': 'two'}},
                    'sheets': [], 'images': []}
        sources, images = source_scope(manifest, {'task_source_ids': ['s1'], 'auxiliary_source_ids': []})
        self.assertEqual(sources, {'s1', 'c1'})
        self.assertEqual(images, set())

    def image_source_manifest(self):
        selected_picture = {'source_id': 'metadata_one', 'embed_image_id': 'image_one',
                            'link': {'source_id': 'relation_one', 'external': True,
                                     'target': 'https://example.invalid/not-fetched'}}
        other_picture = {'source_id': 'metadata_two', 'embed_image_id': 'image_two',
                         'link': {'source_id': 'relation_two', 'external': True,
                                  'target': 'https://example.invalid/other-not-fetched'}}
        index = {
            'sheet_one': {'kind': 'sheet_title', 'sheet_part': 'one'},
            'sheet_two': {'kind': 'sheet_title', 'sheet_part': 'two'},
            'cell_one': {'kind': 'cell', 'sheet_part': 'one'},
            'cell_same_sheet': {'kind': 'cell', 'sheet_part': 'one'},
            'cell_other_sheet': {'kind': 'cell', 'sheet_part': 'two'},
            'dispimg_one': {'kind': 'dispimg_reference', 'sheet_part': 'one'},
            'drawing_one': {'kind': 'drawing_picture', 'sheet_part': 'one'},
            'metadata_one': {'kind': 'cell_image'}, 'metadata_two': {'kind': 'cell_image'},
            'relation_one': {'kind': 'external_relationship'},
            'relation_two': {'kind': 'external_relationship'},
            'drawing_relation': {'kind': 'external_relationship'},
            'asset_one': {'kind': 'image_asset'}, 'asset_two': {'kind': 'image_asset'},
        }
        return {'source_index': index, 'sheets': [
            {'cells': [{'source_id': 'cell_one', 'dispimg': {'source_id': 'dispimg_one', 'picture': selected_picture}},
                       {'source_id': 'cell_same_sheet', 'dispimg': {'picture': other_picture}}],
             'pictures': [{'source_id': 'drawing_one', 'embed_image_id': 'image_one',
                           'link': {'source_id': 'drawing_relation', 'external': True}}]},
            {'cells': [{'source_id': 'cell_other_sheet', 'dispimg': {'picture': other_picture}}], 'pictures': []}],
            'images': [{'id': 'image_one', 'source_id': 'asset_one'}, {'id': 'image_two', 'source_id': 'asset_two'}],
            'cell_images': {'one': selected_picture, 'two': other_picture}}

    def test_selected_dispimg_metadata_validates_without_other_sources(self):
        manifest = self.image_source_manifest()
        candidate = {'candidate_key': 'one', 'task_source_ids': ['cell_one'], 'auxiliary_source_ids': []}
        sources, images = source_scope(manifest, candidate)
        self.assertEqual(sources, {'cell_one', 'dispimg_one', 'metadata_one', 'relation_one', 'asset_one'})
        self.assertEqual(images, {'image_one'})
        for outside in ('sheet_one', 'sheet_two', 'cell_same_sheet', 'cell_other_sheet',
                        'drawing_one', 'drawing_relation', 'metadata_two', 'relation_two', 'asset_two'):
            with self.subTest(source=outside), self.assertRaises(ImportFailure):
                references([outside], sources)
        schema = schema_for('extraction')
        def missing_fields(fields):
            return {name: {'value': None, 'raw_text': None, 'source_ids': [], 'status': 'MISSING'} for name in fields}
        output = {'schema_version': '1', 'candidate_key': 'one',
                  'fields': missing_fields(schema['properties']['fields']['properties']),
                  'products': [{'line_key': 'one', 'fields': missing_fields(schema['properties']['products']['items']['properties']['fields']['properties'])}],
                  'issues': [{'issue_key': 'external_image', 'product_line_key': 'one', 'field_path': None,
                              'type': 'EXTERNAL_REFERENCE', 'message': '只记录外链，不访问。',
                              'source_ids': ['metadata_one', 'relation_one', 'dispimg_one']}],
                  'unmapped_content': [], 'image_candidates': [{'image_id': 'image_one', 'proposed_use': 'PRODUCT',
                      'source_ids': ['asset_one'], 'note': None, 'proposed_product_line_key': 'one'}]}
        self.assertIs(extraction_result(output, manifest, candidate), output)
        output['issues'][0]['source_ids'] = ['relation_two']
        with self.assertRaises(ImportFailure):
            extraction_result(output, manifest, candidate)

    def test_selected_image_adds_only_its_global_metadata(self):
        manifest = self.image_source_manifest()
        sources, images = source_scope(manifest, {'task_source_ids': ['asset_one'], 'auxiliary_source_ids': []})
        self.assertEqual(sources, {'asset_one', 'metadata_one', 'relation_one'})
        self.assertEqual(images, {'image_one'})

    def test_selected_drawing_adds_its_relation_without_other_sheet(self):
        sources, images = source_scope(self.image_source_manifest(),
                                      {'task_source_ids': ['drawing_one'], 'auxiliary_source_ids': []})
        self.assertEqual(sources, {'drawing_one', 'drawing_relation', 'asset_one', 'metadata_one', 'relation_one'})
        self.assertEqual(images, {'image_one'})

    def test_image_metadata_never_introduces_unregistered_sources_or_images(self):
        manifest = self.image_source_manifest()
        manifest['cell_images']['one']['link']['source_id'] = 'unregistered_relation'
        manifest['cell_images']['one']['link_image_id'] = 'image_two'
        sources, images = source_scope(manifest, {'task_source_ids': ['asset_one'], 'auxiliary_source_ids': []})
        self.assertEqual(sources, {'asset_one', 'metadata_one'})
        self.assertEqual(images, {'image_one'})
        with self.assertRaises(ImportFailure):
            references(['unregistered_relation'], sources)

    def test_discovery_rejects_bom_as_only_task_and_unknown_source(self):
        manifest = {'source_sha256': 'a' * 64, 'source_index': {'s1': {'kind': 'cell', 'sheet_part': 'one'}},
                    'sheets': [], 'images': []}
        candidate = {'candidate_key': 'one', 'task_number_original': None, 'product_summary': '床',
                     'version_description': None, 'task_source_ids': ['s1'], 'auxiliary_source_ids': [],
                     'grouping_uncertain': False, 'uncertainty_reason': None}
        value = {'schema_version': '1', 'candidates': [candidate], 'auxiliary_sections': [], 'issues': []}
        self.assertEqual(len(discovery_result(value, manifest)), 1)
        value['auxiliary_sections'] = [{'section_key': 'bom', 'kind': 'BOM', 'source_ids': ['s1'], 'candidate_keys': ['one'], 'note': None}]
        with self.assertRaises(ImportFailure):
            discovery_result(value, manifest)
        value['auxiliary_sections'] = []
        candidate['task_source_ids'] = ['unknown']
        with self.assertRaises(ImportFailure):
            discovery_result(value, manifest)
