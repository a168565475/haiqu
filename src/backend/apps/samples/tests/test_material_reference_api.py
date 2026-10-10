from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.reference_data import models as ref
from apps.products.models import RawMaterialInformation
from . import test_application_api as application_tests


class SampleMaterialReferenceApiTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item
    create_quotation_version_with_line = application_tests.SampleApplicationApiTests.create_quotation_version_with_line

    def test_material_editor_reads_active_bom_sources_without_bom_permission(self):
        self.assertFalse(self.user.has_perm('boms.change_bom'))
        ref.TubeProductName.objects.create(product_name='QA 圆管')
        ref.TubeProductName.objects.create(product_name='QA 停用管', status='INACTIVE')
        ref.FabricMaterial.objects.create(material_name='QA PU涂层')
        ref.TubeDiameter.objects.create(diameter_value='QA25')
        ref.TubeThickness.objects.create(thickness_value='QA1.2')
        ref.ProductColor.objects.create(color_name='QA黑', color_card='QA色卡', color_code='QA9005')
        product = ref.AccessoryProductName.objects.create(product_name='QA 织带', unit_name='米')
        ref.AccessorySpecification.objects.create(product_name=product, specification_value='25mm')
        ref.AccessorySpecification.objects.create(product_name=product, specification_value='停用规格', status='INACTIVE')
        ref.AccessoryColor.objects.create(product_name=product, color_name='黑色')
        response = self.client.get('/api/v1/sample-requests/material-reference-options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('QA 圆管', [row['label'] for row in response.data['data']['tube']['name']])
        self.assertNotIn('QA 停用管', [row['label'] for row in response.data['data']['tube']['name']])
        self.assertIn('QA PU涂层', [row['label'] for row in response.data['data']['fabric']['material']])
        self.assertNotIn('name', response.data['data']['fabric'])
        self.assertIn({'label': 'QA25', 'pinyin_search': ''}, response.data['data']['tubeDiameters'])
        self.assertIn({'label': 'QA1.2', 'pinyin_search': ''}, response.data['data']['tubeThicknesses'])
        self.assertIn({'label': 'QA黑 - QA色卡 - QA9005'}, response.data['data']['colors'])
        accessory = next(row for row in response.data['data']['accessories'] if row['label'] == 'QA 织带')
        self.assertEqual(accessory['specifications'], [{'label': '25mm'}])
        self.assertEqual(accessory['colors'], [{'label': '黑色'}])
        self.assertEqual(accessory['unitLabel'], '米')

    def test_catalog_search_category_and_active_unit_filters(self):
        category, _ = ref.ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type': 'MATERIAL'})
        plastic, _ = ref.ProductCategory.objects.get_or_create(category_name='塑料件', defaults={'item_type': 'MATERIAL'})
        unit = ref.ProductionUnit.objects.create(unit_code='QA_SELECT', unit_name='验收单位')
        def create(number, **updates):
            return RawMaterialInformation.objects.create(**{'material_number': number, 'material_name': 'QA 螺钉', 'specification': 'QA-M4', 'material': '不锈钢', 'color_snapshot': 'QA黑色', 'category': category, 'unit': unit, 'item_type': 'MATERIAL', **updates})
        expected = create('QA-1')
        create('QA-2', archived_at=timezone.now())
        create('QA-3', category=plastic)
        groups = self.client.get('/api/v1/sample-requests/material-reference-options/').data['data']['catalogNames']
        self.assertEqual(groups['hardware'].count('QA 螺钉'), 1)
        url = '/api/v1/sample-requests/material-candidates/'
        for keyword in ['QA-1', 'QA-M4', 'QA黑色', '不锈钢']:
            response = self.client.get(url, {'category': 'hardware', 'q': keyword})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual([row['id'] for row in response.data['data']], [str(expected.pk)])
            self.assertEqual(response.data['data'][0]['unitId'], str(unit.pk))
            self.assertNotIn('price', response.data['data'][0])
        unit.status = 'INACTIVE'
        unit.save()
        self.assertEqual(self.client.get(url, {'category': 'hardware', 'q': 'QA-M4'}).data['data'], [])

    def test_catalog_product_name_filter_is_exact_and_applied_before_pagination(self):
        category, _ = ref.ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type': 'MATERIAL'})
        unit = ref.ProductionUnit.objects.create(unit_code='QA_GROUP', unit_name='分组个')
        for index, name in enumerate(['螺钉', '螺钉', '自攻螺钉']):
            RawMaterialInformation.objects.create(material_number=f'GROUP-{index}', material_name=name, specification=f'M{index}', category=category, unit=unit, item_type='MATERIAL')
        result = self.client.get('/api/v1/sample-requests/material-candidates/', {'category': 'hardware', 'name': '螺钉', 'page_size': 1})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['meta']['total'], 2)
        self.assertEqual(result.data['data'][0]['name'], '螺钉')

    def test_query_validation_and_dedicated_permission(self):
        url = '/api/v1/sample-requests/material-candidates/'
        for query in [{}, {'category': 'tube'}, {'category': 'hardware', 'q': 'x' * 101}]:
            self.assertEqual(self.client.get(url, query).status_code, 400)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='edit_sample_materials'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(url, {'category': 'hardware'}).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/sample-requests/material-reference-options/').status_code, 403)
