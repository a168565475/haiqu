from copy import deepcopy
from uuid import uuid4

from rest_framework.test import APITestCase

from apps.boms.models import Bom
from apps.product_catalog.models import ProductCatalog, ProductCatalogColor
from apps.production_tasks.models import ProductionTaskProduct
from . import test_catalog_business_flow as flow_fixtures


class CatalogBomCopyIsolationTests(APITestCase):
    # 复用持久化业务前提，不继承已有测试，避免重复执行先前通过的链路。
    payload = flow_fixtures.CatalogProductionBomBusinessTests.payload
    setUp = flow_fixtures.CatalogProductionBomBusinessTests.setUp
    selection = flow_fixtures.CatalogProductionBomBusinessTests.selection
    catalog_payload = flow_fixtures.CatalogProductionBomBusinessTests.catalog_payload
    create_catalog_task = flow_fixtures.CatalogProductionBomBusinessTests.create_catalog_task
    create_bom_with_material = flow_fixtures.CatalogProductionBomBusinessTests.create_bom_with_material

    def target_line(self, source, catalog, color_id):
        line = ProductionTaskProduct.objects.get(pk=source.pk)
        line.pk = uuid4()
        line.line_number = 2
        line.product_catalog = catalog
        line.product_selection_snapshot = {**deepcopy(source.product_selection_snapshot),
            "catalog_id": str(catalog.pk), "color_id": str(color_id),
            "color_name": "黑色" if color_id == self.black.pk else "蓝色"}
        line.color_name_snapshot = line.product_selection_snapshot["color_name"]
        line.customer_color_snapshot = line.color_name_snapshot
        line.save()
        return line

    def test_different_catalogs_cannot_copy_when_both_legacy_product_ids_are_null(self):
        _, source_line = self.create_catalog_task()
        source = self.create_bom_with_material(source_line)
        other = ProductCatalog.objects.create(name=self.catalog.name, product_code='COPY-OTHER',
            specification=self.catalog.specification, unit=self.catalog.unit)
        other_color = ProductCatalogColor.objects.create(product=other, value="蓝色")
        target = self.target_line(source_line, other, other_color.pk)
        before_count = Bom.objects.count()
        response = self.client.post('/api/v1/boms/', {
            'production_task_product_id': str(target.pk), 'creation_method': 'COPY',
            'source_bom_id': str(source.pk),
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Bom.objects.count(), before_count)

    def test_same_catalog_different_selected_color_keeps_existing_copy_rule(self):
        _, source_line = self.create_catalog_task()
        source = self.create_bom_with_material(source_line)
        target = self.target_line(source_line, self.catalog, self.black.pk)
        response = self.client.post('/api/v1/boms/', {
            'production_task_product_id': str(target.pk), 'creation_method': 'COPY',
            'source_bom_id': str(source.pk),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        copied = Bom.objects.get(pk=response.data['data']['id'])
        self.assertEqual(copied.copied_from_id, source.pk)
        self.assertEqual(copied.product_catalog_id, self.catalog.pk)
        self.assertEqual(copied.product_selection_snapshot['color_id'], str(self.black.pk))
