"""隔离测试库中的生产创建、PMC、BOM 核对/确认链；不以 Mock 替代持久化。"""
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomLine, BomSection
from apps.organizations.models import Employee
from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit

from ..models import ProductionTask
from . import test_production_task_api as fixtures


class CatalogProductionBomBusinessTests(APITestCase):
    payload = fixtures.ProductionTaskApiTests.payload

    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='boms'))
        approver_user = get_user_model().objects.create_user(username='catalog_flow_pmc')
        self.approver = Employee.objects.create(user=approver_user, employee_code='CATALOG_FLOW_PMC',
            display_name='独立 PMC 审批员')
        approver_user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='production_tasks',
            codename__in=['view_productiontask', 'view_all_productiontask', 'confirm_productiontask']))
        self.approver_client = APIClient()
        self.approver_client.force_authenticate(approver_user)
        category = ProductCatalogCategory.objects.create(name='生产贯通产品类')
        name = ProductCatalogName.objects.create(category=category, name='贯通折叠椅')
        self.catalog = ProductCatalog.objects.create(name=name, product_code='CAT-FLOW', item_number='FLOW-01',
            specification='60*80', unit=self.unit.unit_name, materials=['铁', '铝'], thicknesses=['0.8', '1.0'])
        self.blue = ProductCatalogColor.objects.create(product=self.catalog, value='蓝色')
        self.black = ProductCatalogColor.objects.create(product=self.catalog, value='黑色')
        self.original_product_ids = set(ProductInformation.objects.values_list('pk', flat=True))

    def selection(self, **overrides):
        return {'catalog_version': self.catalog.updated_at.isoformat(), 'color_id': str(self.blue.pk),
                'material': '铁', 'thickness': '0.8', **overrides}

    def catalog_payload(self):
        data = self.payload()
        data.update(planned_start_date=timezone.localdate().isoformat(), planned_end_date=timezone.localdate().isoformat())
        data['products'][0].update(product_id=None, product_color_id=None, color_code='',
                                   product_catalog_id=str(self.catalog.pk), product_selection=self.selection())
        return data

    def create_catalog_task(self):
        response = self.client.post('/api/v1/production-tasks/', self.catalog_payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        task = ProductionTask.objects.get(pk=response.data['data']['id'])
        line = task.products.get()
        self.assertIsNone(line.product_id)
        self.assertIsNone(line.product_color_id)
        self.assertEqual(line.product_catalog_id, self.catalog.pk)
        self.assertEqual(line.product_selection_snapshot['unit_id'], str(self.unit.pk))
        self.assertEqual(response.data['data']['products'][0]['product_catalog_id'], str(self.catalog.pk))
        submitted = self.client.post(f'/api/v1/production-tasks/{task.pk}/submit/', {}, format='json', HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        confirmed = self.approver_client.post(f'/api/v1/production-tasks/{task.pk}/pmc-decision/',
            {'decision': 'CONFIRM', 'follower_ids': [str(self.follower.pk)]}, format='json', HTTP_IF_MATCH=submitted['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertNotEqual(self.approver.pk, self.employee.pk)
        self.assertTrue(AuditLog.objects.filter(object_type='PRODUCTION_TASK', object_id=task.pk,
            action='CONFIRMED', actor_employee=self.approver).exists())
        task.refresh_from_db()
        self.assertEqual(task.status, 'READY')
        return task, line

    def create_bom_with_material(self, line):
        created = self.client.post('/api/v1/boms/', {'production_task_product_id': str(line.pk), 'creation_method': 'BLANK'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        bom = Bom.objects.get(pk=created.data['data']['id'])
        self.assertIsNone(bom.product_id)
        self.assertEqual(bom.product_catalog_id, line.product_catalog_id)
        self.assertEqual(bom.product_selection_snapshot, line.product_selection_snapshot)
        # 当前验证只改成品身份；用现有五金原料规则准备最小用料前提，不涉及导入文件。
        material = RawMaterialInformation.objects.create(material_number='CAT-FLOW-ACCESSORY', material_name='贯通测试配件',
            item_type='MATERIAL', category=ProductCategory.objects.get(category_name='五金', item_type='MATERIAL'),
            unit=ProductionUnit.objects.get(unit_name='PCS'))
        section = BomSection.objects.create(bom=bom, line_number=2, section_type='ACCESSORY', title='五金件')
        BomLine.objects.create(section=section, line_number=1, part_name=material.material_name, unit=material.unit.unit_name,
            unit_consumption='1', total_consumption='10', raw_values={'source_inventory_material_id': str(material.pk)})
        Bom.objects.filter(pk=bom.pk).update(line_count=1, section_count=2)
        return bom

    def confirm_bom(self, bom, selection=None):
        current = self.client.get(f'/api/v1/boms/{bom.pk}/')
        self.assertEqual(current.status_code, 200, current.data)
        payload = {'product_catalog_id': str(self.catalog.pk)}
        if selection is not None:
            payload['product_selection'] = selection
        reviewed = self.client.post(f'/api/v1/boms/{bom.pk}/confirm-product/', payload,
            format='json', HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        self.assertTrue(reviewed.data['data']['product_information_confirmed'])
        return reviewed

    def verify_bom(self, bom, reviewed):
        verified = self.client.post(f'/api/v1/boms/{bom.pk}/verify/', {'quantity_confirmation_reason': ''},
            format='json', HTTP_IF_MATCH=reviewed['ETag'])
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data['data']['status'], 'VERIFIED')
        self.assertIsNone(verified.data['data']['product_master_id'])
        self.assertEqual(set(ProductInformation.objects.values_list('pk', flat=True)), self.original_product_ids)
        self.assertTrue(AuditLog.objects.filter(object_type='BOM', object_id=bom.pk, action='VERIFY').exists())

    def test_manual_production_to_bom_confirms_without_old_product_and_preserves_snapshot(self):
        task, line = self.create_catalog_task()
        original = deepcopy(line.product_selection_snapshot)
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(specification='以后修改的规格', materials=['木'], archived_at=timezone.now())
        bom = self.create_bom_with_material(line)
        reviewed = self.confirm_bom(bom)
        self.verify_bom(bom, reviewed)
        bom.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(bom.product_selection_snapshot, original)
        self.assertEqual(line.product_selection_snapshot, original)
        self.assertEqual(bom.specification_snapshot, '60*80')
        self.assertIsNone(line.product_id)
        self.assertEqual(line.production_task_id, task.pk)

    def test_bom_attribute_reselection_only_writes_production_snapshot_after_verify(self):
        _, line = self.create_catalog_task()
        before = deepcopy(line.product_selection_snapshot)
        bom = self.create_bom_with_material(line)
        reviewed = self.confirm_bom(bom, self.selection(color_id=str(self.black.pk), material='铝', thickness='1.0'))
        line.refresh_from_db()
        self.assertEqual(line.product_selection_snapshot, before)
        self.verify_bom(bom, reviewed)
        line.refresh_from_db()
        bom.refresh_from_db()
        self.assertEqual(line.product_selection_snapshot, bom.product_selection_snapshot)
        self.assertEqual(line.product_selection_snapshot['color_id'], str(self.black.pk))
        self.assertEqual(line.product_selection_snapshot['material'], '铝')
        self.assertEqual(line.product_selection_snapshot['thickness'], '1.0')
        self.assertIsNone(line.product_id)

    def test_stale_catalog_version_rejects_entire_production_creation(self):
        data = self.catalog_payload()
        data['products'][0]['product_selection']['catalog_version'] = '2020-01-01T00:00:00+00:00'
        before_tasks = ProductionTask.objects.count()
        response = self.client.post('/api/v1/production-tasks/', data, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('product_selection', response.data['error']['field_errors'])
        self.assertEqual(ProductionTask.objects.count(), before_tasks)
        self.assertEqual(set(ProductInformation.objects.values_list('pk', flat=True)), self.original_product_ids)
        self.assertFalse(Bom.objects.exists())
