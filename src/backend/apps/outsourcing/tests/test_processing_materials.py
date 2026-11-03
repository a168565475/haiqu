"""材料快照持久化/详情契约测试；fixture准备不代替新材料全链验收。"""
from copy import deepcopy

from django.db.models.deletion import ProtectedError
from django.test import override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog
from ..models import TubeOutsourcingOrder
from ..processing_materials import processing_line_fields, require_saved_processing_materials
from .test_plan_orders_api import PlanApiFixture
from .test_tube_orders_api import BASE


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class ProcessingMaterialPersistenceTests(PlanApiFixture, APITestCase):
    def setUp(self):
        super().setUp()
        # 使用既有真实隔离数据库fixture建立单据，定向验证新增保存字段和详情。
        self.detail = self.plan()
        self.line = TubeOutsourcingOrder.objects.get(pk=self.detail['id']).lines.get()
        self.catalog = MaterialCatalog.objects.create(category_key='TUBE', template_key='TUBE', name='U5快照管材')
        self.material = {
            'schema_version': 1, 'catalog_id': str(self.catalog.pk), 'catalog_version': self.catalog.updated_at.isoformat(),
            'name': self.catalog.name, 'category_key': 'TUBE', 'template_key': 'TUBE', 'scope': 'BASE',
            'processing_state': 'RAW', 'processing_stage': 'RAW', 'completed_craft': None, 'semi_kind': None,
            'attributes': {'material': '铁', 'shape': '圆管', 'section_size': '25', 'thickness': '1.2', 'length': '6'},
            'unit_id': str(self.root_unit.pk), 'unit_name': '根', 'display_name': 'U5快照管材 / 根',
        }
        self.output = {**deepcopy(self.material), 'scope': 'SPRAY', 'processing_state': 'PROCESSED',
            'processing_stage': 'POWDER_COATING', 'semi_kind': 'PIPE',
            'completed_craft': {'id': str(self.spray.pk), 'craft_type': 'EXTERNAL', 'code': 'POWDER_COATING'},
            'unit_id': str(self.piece_unit.pk), 'unit_name': '支'}
        self.line.bom_line.material_catalog_id = self.catalog.pk
        self.pair = {'input_material_selection_snapshot': self.material,
                     'output_material_selection_snapshot': self.output}

    def save_pair(self):
        fields = processing_line_fields(bom_line=self.line.bom_line, row={'snapshot': self.pair}, craft=self.spray)
        for key, value in fields.items():
            setattr(self.line, key, value)
        self.line.save(update_fields=list(fields))
        self.line.refresh_from_db()

    def test_persist_and_reopen_does_not_read_current_catalog_name(self):
        self.save_pair()
        MaterialCatalog.objects.filter(pk=self.catalog.pk).update(name='目录后来改名')
        self.material['attributes']['section_size'] = '32'
        response = self.client.get(BASE + self.detail['id'] + '/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        saved = response.data['data']['lines'][0]
        self.assertEqual(saved['input_material_catalog_id'], str(self.catalog.pk))
        self.assertEqual(saved['output_material_catalog_id'], str(self.catalog.pk))
        self.assertEqual(saved['input_material_selection_snapshot']['name'], 'U5快照管材')
        self.assertEqual(saved['input_material_selection_snapshot']['attributes']['section_size'], '25')
        self.assertEqual(saved['output_material_selection_snapshot']['unit_name'], '支')

    def test_catalog_referenced_by_processing_line_is_protected(self):
        self.save_pair()
        with self.assertRaises(ProtectedError):
            self.catalog.delete()

    def test_new_line_cannot_fall_back_to_empty_or_mismatched_material_pair(self):
        for value in ({}, {'snapshot': {'input_material_selection_snapshot': self.material}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                processing_line_fields(bom_line=self.line.bom_line, row=value, craft=self.spray)
        self.save_pair()
        self.line.output_material_selection_snapshot['processing_stage'] = 'METAL'
        with self.assertRaises(ValidationError):
            require_saved_processing_materials(self.line)
