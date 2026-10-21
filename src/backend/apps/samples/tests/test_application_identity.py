from decimal import Decimal

from rest_framework.test import APITestCase

from apps.files.models import BusinessFile
from apps.products.models import ProductInformation
from apps.reference_data.models import ProductItem, ProductionUnit
from ..models import SampleRequest
from . import test_application_api as application_tests


class SampleApplicationIdentityTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review

    def product(self, suffix):
        unit, _ = ProductionUnit.objects.get_or_create(unit_code='SAMPLE_ID_PCS', defaults={'unit_name': '件'})
        item = ProductItem.objects.create(item_number=f'SAMPLE-ID-ITEM-{suffix}', category=self.product_category)
        return ProductInformation.objects.create(
            product_number=f'SAMPLE-ID-{suffix}', product_code=f'SAMPLE-ID-CODE-{suffix}',
            category=self.product_category, product_name=f'正式产品{suffix}', specification=f'{suffix}规格',
            unit=unit, product_item=item, scale='CUSTOM',
        )

    def returned_product(self):
        original = self.product('A')
        payload = self.payload(product_id=str(original.pk), product_name=original.product_name, specification=original.specification)
        created = self.submit(payload)
        self.assertEqual(created.status_code, 201, created.data)
        sample = SampleRequest.objects.get(pk=created.data['data']['id'])
        product = sample.products.get()
        self.assertEqual(product.product_id, original.pk)
        # 预置已有产品派生快照；只建文件元数据，不写物理测试文件。
        image = BusinessFile.objects.create(
            original_name='原产品A.png', storage_key='qa-fixtures/sample-identity-a.png',
            content_type='image/png', size_bytes=1, scan_status='CLEAN',
        )
        product.material_snapshot = '原产品A材质'
        product.product_image = image
        product.save()
        returned = self.review(created, 'return', '调整申请产品')
        self.assertEqual(returned.status_code, 200, returned.data)
        return sample, product, payload, returned['ETag']

    def resubmit(self, sample, payload, etag):
        response = self.client.post(
            f'/api/v1/sample-requests/{sample.pk}/application-resubmit/',
            {'payload': payload}, format='json', HTTP_IF_MATCH=etag,
        )
        self.assertEqual(response.status_code, 200, response.data)

    def assert_custom_identity(self, product):
        product.refresh_from_db()
        self.assertIsNone(product.product_id)
        self.assertIsNone(product.product_image_id)
        for field in ('product_number_snapshot', 'product_code_snapshot', 'item_number_snapshot', 'material_snapshot'):
            self.assertEqual(getattr(product, field), '', field)
        self.assertEqual(product.product_name, '自定义产品B')
        self.assertEqual(product.specification, 'B手工规格')

    def test_resubmit_custom_product_clears_old_identity_and_preserves_input(self):
        sample, product, payload, etag = self.returned_product()
        self.resubmit(sample, {
            **payload, 'product_id': None, 'product_name': '自定义产品B', 'specification': 'B手工规格',
            'length_cm': '72.50', 'seat_width_cm': '43.20', 'quantity': 2, 'purpose': 'B制作要求',
        }, etag)
        self.assert_custom_identity(product)
        self.assertEqual(product.length_cm, Decimal('72.50'))
        self.assertEqual(product.seat_width_cm, Decimal('43.20'))
        item = sample.items.get()
        self.assertEqual(item.product_description_snapshot, '自定义产品B')
        self.assertEqual(item.specification_snapshot, 'B手工规格')
        self.assertEqual(item.requested_quantity, 2)
        sample.refresh_from_db()
        self.assertEqual(sample.purpose, 'B制作要求')

    def test_resubmit_changed_identity_does_not_keep_stale_selected_product_id(self):
        sample, product, payload, etag = self.returned_product()
        self.resubmit(sample, {**payload, 'product_name': '自定义产品B', 'specification': 'B手工规格'}, etag)
        self.assert_custom_identity(product)

    def test_resubmit_another_formal_product_uses_its_identity(self):
        sample, product, payload, etag = self.returned_product()
        replacement = self.product('C')
        self.resubmit(sample, {
            **payload, 'product_id': str(replacement.pk), 'product_name': replacement.product_name,
            'specification': replacement.specification, 'length_cm': '88.50',
        }, etag)
        product.refresh_from_db()
        self.assertEqual(product.product_id, replacement.pk)
        self.assertEqual(product.product_number_snapshot, replacement.product_number)
        self.assertEqual(product.product_code_snapshot, replacement.product_code)
        self.assertEqual(product.item_number_snapshot, replacement.product_item.item_number)
        self.assertEqual(product.product_name, replacement.product_name)
        self.assertEqual(product.specification, replacement.specification)
        self.assertEqual(product.length_cm, Decimal('88.50'))
        self.assertEqual(product.material_snapshot, '')
        self.assertIsNone(product.product_image_id)
