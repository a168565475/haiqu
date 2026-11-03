from copy import deepcopy

from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from apps.product_catalog.selection import resolve_product_selection
from apps.products.models import ProductInformation
from apps.files.models import BusinessFile
from apps.quotations.models import QuotationLine
from apps.reference_data.models import ProductionUnit

from ..models import SampleRequest
from ..services import sample_product_values_from_source
from ..catalog_products import apply_catalog_selection
from . import test_application_api as application_tests


class SampleCatalogProductTests(APITestCase):
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review

    def setUp(self):
        application_tests.SampleApplicationApiTests.setUp(self)
        category = ProductCatalogCategory.objects.create(name='样品新产品类')
        name = ProductCatalogName.objects.create(category=category, name='新产品椅')
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_name='套', defaults={'unit_code': 'SAMPLE-CAT-SET'})
        self.catalog = ProductCatalog.objects.create(name=name, item_number='NEW-01', specification='60*80', unit='套', materials=['铝'], thicknesses=['0.8'])
        self.color = ProductCatalogColor.objects.create(product=self.catalog, value='蓝色')

    def selected_payload(self, **updates):
        return self.payload(product_catalog_id=str(self.catalog.pk),
                            product_selection={'catalog_version': self.catalog.updated_at.isoformat()}, **updates)

    def test_application_saves_catalog_snapshot_without_fake_legacy_product(self):
        before = ProductInformation.objects.count()
        response = self.submit(self.selected_payload(product_name='客户端旧名', specification='客户端旧规格'))
        self.assertEqual(response.status_code, 201, response.data)
        product = SampleRequest.objects.get(pk=response.data['data']['id']).products.get()
        self.assertIsNone(product.product_id)
        self.assertEqual(product.product_catalog_id, self.catalog.pk)
        self.assertEqual(product.product_name, '新产品椅')
        self.assertEqual(product.specification, '60*80')
        self.assertEqual(product.material_snapshot, '铝')
        self.assertEqual(product.details.get().unit_code, self.unit.unit_code)
        self.assertEqual(product.details.get().color_name_snapshot, '蓝色')
        self.assertEqual(response.data['data']['products'][0]['product_selection_snapshot'], product.product_selection_snapshot)
        self.assertEqual(ProductInformation.objects.count(), before)
        with self.assertRaises(ProtectedError):
            self.catalog.delete()

    def test_invalid_catalog_version_rolls_back_application(self):
        before = SampleRequest.objects.count()
        payload = self.selected_payload()
        payload['product_selection']['catalog_version'] = '2020-01-01T00:00:00+00:00'
        response = self.submit(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(SampleRequest.objects.count(), before)

    def test_completion_keeps_saved_selection_without_old_category_or_color(self):
        created = self.submit(self.selected_payload())
        self.assertEqual(created.status_code, 201, created.data)
        approved = self.review(created)
        product = approved.data['data']['products'][0]
        snapshot = deepcopy(product['product_selection_snapshot'])
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(specification='主档新规格', materials=['铁'], archived_at=timezone.now())
        payload = {'purpose': '完善数量', 'products': [{
            'id': product['id'], 'product_catalog_id': str(self.catalog.pk), 'product_name': product['product_name'],
            'specification': product['specification'], 'category_id': None,
            'details': [{'id': product['details'][0]['id'], 'product_color_id': None, 'sample_quantity': 5, 'tolerance': 'NONE'}],
        }]}
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/"
        response = self.client.patch(url, payload, format='json', HTTP_IF_MATCH=approved['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        saved = response.data['data']['products'][0]
        self.assertEqual(saved['product_selection_snapshot'], snapshot)
        self.assertEqual(saved['specification'], '60*80')
        self.assertEqual(saved['total_sample_quantity'], 5)
        self.assertEqual(saved['details'][0]['color_name'], '蓝色')

    def test_source_transfer_uses_frozen_catalog_snapshot_when_master_changed(self):
        inquiry, item = self.create_inquiry_with_item()
        _, snapshot = resolve_product_selection(self.catalog.pk, {'catalog_version': self.catalog.updated_at.isoformat()})
        item.product_catalog = self.catalog
        item.product = None
        item.product_selection_snapshot = snapshot
        item.save()
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(specification='不应带入', archived_at=timezone.now())
        values = sample_product_values_from_source(item)
        self.assertEqual(values['product_catalog'].pk, self.catalog.pk)
        self.assertEqual(values['product_selection_snapshot'], snapshot)
        self.assertEqual(values['specification'], '60*80')
        self.assertIsNot(values['product_selection_snapshot'], snapshot)

    def test_source_image_and_unchanged_product_image_preserved_replacement_clears_image(self):
        image = BusinessFile.objects.create(original_name='产品图片.png', storage_key='qa-fixtures/catalog-product-image.png',
                                            content_type='image/png', size_bytes=1, scan_status='CLEAN')
        _, snapshot = resolve_product_selection(self.catalog.pk, {'catalog_version': self.catalog.updated_at.isoformat()})
        source = QuotationLine(product_catalog=self.catalog, product_selection_snapshot=snapshot, product_image=image)
        self.assertEqual(sample_product_values_from_source(source)['product_image'], image)
        inherited = {}
        apply_catalog_selection(inherited, source=source)
        self.assertEqual(inherited['product_image'], image)
        created = self.submit(self.selected_payload())
        product = SampleRequest.objects.get(pk=created.data['data']['id']).products.get()
        product.product_image = image
        product.save(update_fields=['product_image'])
        preserved = {'product_catalog_id': self.catalog.pk}
        apply_catalog_selection(preserved, existing=product)
        self.assertEqual(preserved['product_image'], image)
        replacement = ProductCatalog.objects.create(name=self.catalog.name, specification='另一规格', unit='套')
        changed = {'product_catalog_id': replacement.pk, 'product_selection': {'catalog_version': replacement.updated_at.isoformat()}}
        apply_catalog_selection(changed, existing=product)
        self.assertIsNone(changed['product_image'])
