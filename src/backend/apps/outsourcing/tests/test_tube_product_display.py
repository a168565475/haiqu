"""管材外发创建页只读产品展示与图片权限边界。"""
import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.audit.models import AuditLog
from apps.files.models import BusinessFile, FileScanStatus
from apps.inventory.models import PublicStockMovement
from apps.production_tasks.models import ProductionTaskProductImage
from apps.workshop_config.models import Craft

from ..api.tube_views import TubeOutsourcingOrderViewSet
from ..models import TubeOutsourcingOrder
from .test_tube_orders_api import BASE, TubeApiFixture


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True)
class TubeProductDisplayTests(ScopedActorMixin, TubeApiFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.media_root = Path('/tmp/haiqu_tube_product_summary_20261019_agent') / self._testMethodName
        self.assertFalse(self.media_root.exists(), '本项临时图片目录已存在，不能覆盖未知资源。')
        self.media_root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.media_root)
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))

    def image(self, name='product.png'):
        image_bytes = b'\x89PNG\r\n\x1a\nproduct-display-test'
        (self.media_root / name).write_bytes(image_bytes)
        return BusinessFile.objects.create(uploaded_by_employee=self.employee, original_name=name,
            storage_key=name, content_type='image/png', size_bytes=len(image_bytes), scan_status=FileScanStatus.CLEAN)

    def attach_image(self, image):
        self.product_line.image_file = image
        self.product_line.save(update_fields=['image_file'])

    def image_url(self, image):
        return BASE + f'product-images/{self.schedule_product.pk}/{image.pk}/'

    def options_product(self):
        response = self.client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']['tasks'][0]['products'][0]

    def test_options_and_context_expose_separate_snapshots_without_business_writes(self):
        raw = '47*55*79；颜色：酒红色；材质：PE'
        self.product_line.specification_snapshot = raw
        self.product_line.customer_specification_snapshot = ''
        self.product_line.customer_color_snapshot = ''
        self.product_line.color_name_snapshot = '酒红色'
        self.product_line.material_snapshot = 'PE'
        self.product_line.save(update_fields=['specification_snapshot', 'customer_specification_snapshot',
            'customer_color_snapshot', 'color_name_snapshot', 'material_snapshot'])
        before = (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count(), AuditLog.objects.count())
        for row in [self.options_product(), self.context()]:
            self.assertEqual(row['specification'], raw)
            self.assertEqual(row['specification_display'], '47*55*79')
            self.assertEqual(row['material'], 'PE')
            self.assertEqual(row['color'], '酒红色')
            self.assertIsNone(row['image_file_id'])
            self.assertEqual(row['image_url'], '')
        self.product_line.refresh_from_db()
        self.assertEqual(self.product_line.specification_snapshot, raw)
        self.assertEqual(before, (TubeOutsourcingOrder.objects.count(), PublicStockMovement.objects.count(), AuditLog.objects.count()))

    def test_unverified_specification_suffix_is_preserved(self):
        self.product_line.specification_snapshot = '47*55*79；颜色：其他颜色'
        self.product_line.customer_specification_snapshot = ''
        self.product_line.save(update_fields=['specification_snapshot', 'customer_specification_snapshot'])
        self.assertEqual(self.options_product()['specification_display'], self.product_line.specification_snapshot)

    def test_task_primary_then_ordered_gallery_is_used(self):
        primary, first, second = self.image(), self.image('first.png'), self.image('second.png')
        self.attach_image(primary)
        ProductionTaskProductImage.objects.create(product_line=self.product_line, image_file=second, line_number=2)
        ProductionTaskProductImage.objects.create(product_line=self.product_line, image_file=first, line_number=1)
        self.assertEqual(self.options_product()['image_file_id'], str(primary.pk))
        self.attach_image(None)
        row = self.options_product()
        self.assertEqual(row['image_file_id'], str(first.pk))
        self.assertEqual(row['image_url'], self.image_url(first))
        self.assertEqual(self.client.get(self.image_url(primary), HTTP_HOST='localhost').status_code, 404)

    def test_craft_scope_reads_image_without_production_task_permission(self):
        image = self.image()
        self.attach_image(image)
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        self.assertFalse(get_user_model().objects.get(pk=self.scope_user.pk).has_perm('production_tasks.view_productiontask'))
        row = self.options_product()
        self.assertEqual(self.context()['image_file_id'], str(image.pk))
        response = self.client.get(row['image_url'], HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(response.streaming_content), (self.media_root / image.storage_key).read_bytes())
        response.file_to_stream.close()

    def test_missing_permission_wrong_scope_and_unrelated_file_are_rejected(self):
        image, unrelated = self.image(), self.image('unrelated.png')
        self.attach_image(image)
        self.assertEqual(self.client.get(self.image_url(unrelated), HTTP_HOST='localhost').status_code, 404)
        self.scoped_actor()
        self.assertEqual(self.client.get(self.image_url(image), HTTP_HOST='localhost').status_code, 403)
        unrelated_craft = Craft.objects.create(craft_type='EXTERNAL', name='只授权其他工艺', outsourcing_code='SEWING')
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [unrelated_craft])
        self.assertEqual(self.client.get(self.image_url(image), HTTP_HOST='localhost').status_code, 404)
        options = self.client.get(BASE + 'options/', HTTP_HOST='localhost')
        self.assertEqual(options.data['data']['tasks'], [])

    def test_image_keeps_scan_archive_content_type_and_storage_guards(self):
        image = self.image()
        self.attach_image(image)
        for update in [
            {'scan_status': FileScanStatus.INFECTED},
            {'scan_status': FileScanStatus.CLEAN, 'archived_at': timezone.now()},
            {'archived_at': None, 'content_type': 'application/pdf'},
            {'content_type': 'image/png', 'storage_key': '../outside.png'},
            {'storage_key': 'missing.png'},
        ]:
            with self.subTest(update=update):
                for name, value in update.items():
                    setattr(image, name, value)
                image.save(update_fields=list(update))
                self.assertEqual(self.client.get(self.image_url(image), HTTP_HOST='localhost').status_code, 404)
                if image.scan_status != FileScanStatus.CLEAN or image.archived_at or image.content_type == 'application/pdf':
                    self.assertIsNone(self.options_product()['image_file_id'])

    def test_invalid_image_identifiers_return_400(self):
        self.assertEqual(self.client.get(BASE + f'product-images/{self.schedule_product.pk}/invalid/',
            HTTP_HOST='localhost').status_code, 400)
        self.assertEqual(self.client.get(BASE + 'product-images/invalid/invalid/', HTTP_HOST='localhost').status_code, 400)

    def test_product_image_openapi_contract_validates(self):
        patterns = [path('api/v1/tube-outsourcing-orders/product-images/<uuid:schedule_product_id>/<uuid:file_id>/',
            TubeOutsourcingOrderViewSet.as_view({'get': 'product_image'}))]
        schema = SchemaGenerator(patterns=patterns).get_schema(public=True)
        validate_schema(schema)
        operation = next(iter(schema['paths'].values()))['get']
        self.assertEqual(operation['responses']['200']['content']['application/octet-stream']['schema'],
            {'type': 'string', 'format': 'binary'})
        self.assertEqual({item['name'] for item in operation['parameters']}, {'schedule_product_id', 'file_id'})
