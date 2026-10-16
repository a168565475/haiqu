import json

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.files.models import BusinessFile

from ..models import ProductionTaskDetail, ProductionTaskProductImage
from . import test_task_management as management_fixtures


class SalesProductImmutableDetailsTests(APITestCase):
    setUp = management_fixtures.ProductionTaskSalesManagementTests.setUp
    direct_payload = management_fixtures.ProductionTaskSalesManagementTests.direct_payload
    create_direct = management_fixtures.ProductionTaskSalesManagementTests.create_direct
    make_source_task = management_fixtures.ProductionTaskSalesManagementTests.make_source_task
    product_payload = management_fixtures.ProductionTaskSalesManagementTests.product_payload

    def source(self):
        task, _ = self.make_source_task()
        line = task.products.get()
        image = BusinessFile.objects.create(original_name='source.png', storage_key='unit/source.png',
                                            content_type='image/png', size_bytes=1, scan_status='CLEAN')
        line.image_file = image
        line.special_requirements = '来源生产要求'
        line.packaging_method = '来源包装要求'
        line.save()
        ProductionTaskProductImage.objects.create(product_line=line, line_number=1, image_file=image)
        detail = ProductionTaskDetail.objects.create(product_line=line, line_number=1, detail_type='固定明细',
                                                     description='来源描述')
        item = self.product_payload(line)
        item.update(retained_image_ids=[str(image.pk)], special_requirements=line.special_requirements,
                    packaging_method=line.packaging_method, details=[{'client_key': str(detail.pk),
                    'detail_type': detail.detail_type, 'description': detail.description}])
        return task, line, detail, image, item, f'/api/v1/production-tasks/{task.pk}/'

    def test_sales_line_readonly_properties_cannot_be_changed(self):
        task, line, detail, image, item, url = self.source()
        for change in ({'special_requirements': '改要求'}, {'packaging_method': '改包装'},
                       {'retained_image_ids': []}, {'replace_primary_image': True}, {'details': []},
                       {'details': [{'client_key': str(detail.pk), 'detail_type': '改类型'}]}):
            with self.subTest(change=change):
                response = self.client.patch(url, {'products': [{**item, **change}]}, format='json',
                                            HTTP_IF_MATCH=self.client.get(url)['ETag'])
                self.assertEqual(response.status_code, 400, response.data)
        line.refresh_from_db()
        detail.refresh_from_db()
        self.assertEqual(line.special_requirements, '来源生产要求')
        self.assertEqual(line.packaging_method, '来源包装要求')
        self.assertEqual(detail.description, '来源描述')
        self.assertEqual(line.images.get().image_file_id, image.pk)

    def test_omitted_readonly_children_survive_quantity_edit_with_same_ids(self):
        task, line, detail, image, item, url = self.source()
        item.pop('details')
        item.pop('retained_image_ids')
        item['quantity'] = 5
        image_links = list(line.images.values())
        detail_rows = list(line.details.values())
        response = self.client.patch(url, {'products': [item]}, format='json',
                                    HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertEqual(line.quantity, 5)
        self.assertEqual(line.image_file_id, image.pk)
        self.assertEqual(list(line.images.values()), image_links)
        self.assertEqual(list(line.details.values()), detail_rows)

    def test_sales_product_file_upload_is_rejected_without_modifying_source(self):
        task, line, detail, image, item, url = self.source()
        response = self.client.patch(url, {'payload': json.dumps({'products': [item]}),
            f'product_image_{line.pk}': SimpleUploadedFile('new.png', b'new', content_type='image/png')},
            format='multipart', HTTP_IF_MATCH=self.client.get(url)['ETag'])
        self.assertEqual(response.status_code, 400, response.data)
        line.refresh_from_db()
        self.assertEqual(line.image_file_id, image.pk)
