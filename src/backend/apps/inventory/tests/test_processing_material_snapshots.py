from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.processing_material_snapshots import copy_material_selection, freeze_processing_materials, tube_processing_not_enabled


class ProcessingMaterialSnapshotsTests(SimpleTestCase):
    def test_temporary_kilogram_limit_does_not_expand_to_other_materials_or_units(self):
        for category, unit, blocked in [('TUBE','公斤',True),('TUBE','千克',True),('TUBE','KG',True),
                ('TUBE','根',False),('TUBE','米',False),('PLASTIC','公斤',False),('FABRIC','公斤',False)]:
            with self.subTest(category=category, unit=unit):
                line = SimpleNamespace(material_catalog_id=uuid4(),
                    material_selection_snapshot={'category_key':category,'unit_name':unit})
                self.assertEqual(bool(tube_processing_not_enabled(line)),blocked)

    def setUp(self):
        self.catalog_id = uuid4()
        self.metal = SimpleNamespace(pk=uuid4(), craft_type='INTERNAL', plan_category='METAL', outsourcing_code='')
        self.spray = SimpleNamespace(pk=uuid4(), craft_type='EXTERNAL', plan_category='', outsourcing_code='POWDER_COATING')
        self.sewing = SimpleNamespace(pk=uuid4(), craft_type='EXTERNAL', plan_category='', outsourcing_code='SEWING')
        self.raw = {
            'schema_version': 1, 'catalog_id': str(self.catalog_id), 'catalog_version': '2026-10-29T10:00:00+08:00',
            'category_key': 'TUBE', 'template_key': 'TUBE', 'name': '铁管', 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '6'},
            'unit_id': str(uuid4()), 'unit_name': '公斤', 'display_name': '铁管 / 公斤',
        }

    def result(self, craft=None):
        craft = craft or self.metal
        snapshot = deepcopy(self.raw)
        snapshot.update(processing_state='PROCESSED', processing_stage=craft.plan_category or craft.outsourcing_code,
            completed_craft={'id': str(craft.pk), 'craft_type': craft.craft_type, 'code': craft.plan_category or craft.outsourcing_code},
            semi_kind='PIPE', unit_id=str(uuid4()), unit_name='支')
        return snapshot

    def freeze(self, output=None, **kwargs):
        return freeze_processing_materials(input_snapshot=self.raw, output_snapshot=output or self.result(),
            output_catalog_id=self.catalog_id, completed_craft=kwargs.pop('completed_craft', self.metal),
            semi_kind=kwargs.pop('semi_kind', 'PIPE'), **kwargs)

    def test_saved_content_is_deep_copied_without_database_access(self):
        output = self.result()
        frozen = self.freeze(output)
        self.raw['attributes']['section_size'] = '32'
        output['completed_craft']['code'] = 'POWDER_COATING'
        self.assertEqual(frozen['input_material_selection_snapshot']['attributes']['section_size'], '25')
        self.assertEqual(frozen['output_material_selection_snapshot']['completed_craft']['code'], 'METAL')

    def test_input_and_output_units_are_independent(self):
        pair = self.freeze()
        self.assertEqual(pair['input_material_selection_snapshot']['unit_name'], '公斤')
        self.assertEqual(pair['output_material_selection_snapshot']['unit_name'], '支')
        self.assertNotIn('quantity', pair['output_material_selection_snapshot'])

    def test_base_scope_can_be_processed_metal(self):
        self.assertEqual(self.freeze()['output_material_selection_snapshot']['scope'], 'BASE')

    def test_actual_output_stage_cannot_be_replaced_by_input_stage(self):
        with self.assertRaisesMessage(ValidationError, '实际完成工艺'):
            self.freeze(self.result(self.spray))

    def test_source_and_result_catalog_can_differ_for_fabric_to_cutting(self):
        output = self.result(self.sewing)
        output.update(category_key='FABRIC_SEMI', template_key='FABRIC_SEMI', semi_kind='CUTTING')
        output['attributes'] = {'material': '布', 'size': '500x600', 'color': '白色'}
        self.raw.update(catalog_id=str(uuid4()), category_key='FABRIC', template_key='FABRIC')
        self.raw['attributes'] = {'material': '布', 'width': '1.5', 'fabric_spec': '600D', 'color': '白色'}
        result = self.freeze(output, completed_craft=self.sewing, semi_kind='CUTTING', input_catalog_id=self.raw['catalog_id'])
        self.assertNotEqual(result['input_material_selection_snapshot']['catalog_id'], result['output_material_selection_snapshot']['catalog_id'])

    def test_internal_sewing_uses_explicit_shared_stock_craft(self):
        output = self.result(self.sewing)
        output['semi_kind'] = 'CUTTING'
        result = self.freeze(output, completed_craft=self.sewing, semi_kind='CUTTING')
        self.assertEqual(result['output_material_selection_snapshot']['completed_craft']['craft_type'], 'EXTERNAL')

    def test_wrong_catalog_is_rejected(self):
        output = self.result()
        output['catalog_id'] = str(uuid4())
        with self.assertRaisesMessage(ValidationError, '关联'):
            self.freeze(output)

    def test_malformed_snapshots_fail_instead_of_becoming_empty_success(self):
        for change in ({'schema_version': True}, {'attributes': {}}, {'unit_id': 'bad'},
                       {'processing_stage': 'PROCESSED'}, {'unit_name': ''}, {'scope': 'OTHER'},
                       {'completed_craft': {'code': 'METAL'}}, {'semi_kind': None}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.freeze({**self.result(), **change})

    def test_raw_cannot_claim_completed_craft(self):
        with self.assertRaisesMessage(ValidationError, '原料快照'):
            copy_material_selection({**self.raw, 'completed_craft': self.result()['completed_craft']}, field='source')
