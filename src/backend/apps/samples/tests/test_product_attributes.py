from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.inquiries.models import format_inquiry_item_specification
from ..models import SampleRequest
from ..product_attributes import split_product_specification
from . import test_application_api as application_tests


class ProductAttributeTextTests(SimpleTestCase):
    def test_only_explicit_trailing_labels_are_split(self):
        self.assertEqual(split_product_specification('60×80；颜色：黑色；材质：铝'),
                         {'specification': '60×80', 'color': '黑色', 'material': '铝'})
        self.assertEqual(split_product_specification('60;80 铝合金 黑色'),
                         {'specification': '60;80 铝合金 黑色', 'color': '', 'material': ''})


class SampleProductAttributeApiTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review

    def assert_attributes(self, response):
        self.assertIn(response.status_code, (200, 201), response.data)
        sample = SampleRequest.objects.get(pk=response.data['data']['id'])
        product, detail = sample.products.get(), sample.items.get()
        self.assertEqual(product.specification, '60×80')
        self.assertEqual(product.material_snapshot, '铝')
        self.assertEqual(detail.specification_snapshot, '60×80')
        self.assertEqual(detail.color_name_snapshot, '黑色')
        result = response.data['data']['products'][0]
        self.assertEqual(result['specification'], '60×80')
        self.assertEqual(result['specification_display'], '60×80；颜色：黑色；材质：铝')
        return sample

    def test_manual_save_and_read_keep_separate_attributes(self):
        created = self.submit(self.payload(specification='60×80；颜色：黑色；材质：铝'))
        sample = self.assert_attributes(created)
        self.assert_attributes(self.client.get(f'/api/v1/sample-requests/{sample.pk}/'))

    def test_inquiry_and_return_use_original_attribute_snapshot(self):
        inquiry, item = self.create_inquiry_with_item()
        item.specification, item.color, item.material = '60×80', '黑色', '铝'
        item.save()
        payload = self.payload(source_type='inquiry', source_id=str(inquiry.pk), source_product_id=str(item.pk),
                               product_name=item.product_description,
                               specification=format_inquiry_item_specification(item.specification, item.color, item.material))
        sample = self.assert_attributes(self.submit(payload))
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        returned = self.review(current, 'return', '补充数量')
        item.color, item.material = '蓝色', '钢'
        item.save()
        self.assert_attributes(self.client.post(f'/api/v1/sample-requests/{sample.pk}/application-resubmit/',
            {'payload': payload}, format='json', HTTP_IF_MATCH=returned['ETag']))

    def test_quotation_preserves_structured_snapshot(self):
        from django.utils import timezone
        from apps.quotations.models import Quotation, QuotationVersion, QuotationLine
        inquiry, item = self.create_inquiry_with_item()
        quotation = Quotation.objects.create(customer_account=self.customer, transaction_entity=self.entity,
            source_inquiry=inquiry, owner_employee=self.employee, quotation_number='QUO-ATTRIBUTES', subject='产品属性')
        version = QuotationVersion.objects.create(quotation=quotation, version_number=1, currency_code='USD',
            transaction_entity_snapshot={'legal_name': self.entity.legal_name},
            address_snapshot={'address_line1': self.address.address_line1},
            contact_snapshot={'id': str(self.contact.pk), 'display_name': self.contact.display_name})
        line = QuotationLine.objects.create(quotation_version=version, source_inquiry_item=item, line_number=1,
            product_description_snapshot='打样椅', specification_snapshot='60×80', color_snapshot='黑色',
            material_snapshot='铝', quantity='3', unit_code='PCS', unit_price='18.5', line_total='55.5')
        # 先建立完整快照，再发送锁定；不修改已发送报价。
        version.status, version.locked_at, version.issued_at = 'SENT', timezone.now(), timezone.now()
        version.save(update_fields=['status', 'locked_at', 'issued_at', 'updated_at'])
        self.assert_attributes(self.submit(self.payload(source_type='quotation', source_id=str(version.pk),
            source_product_id=str(line.pk), product_name=line.product_description_snapshot, specification='60×80')))

    def test_legacy_read_does_not_rewrite_business_record(self):
        created = self.submit(self.payload(specification='60×80'))
        sample = SampleRequest.objects.get(pk=created.data['data']['id'])
        product = sample.products.get()
        product.specification = '60×80；颜色：黑色；材质：铝'
        product.save()
        result = self.client.get(f'/api/v1/sample-requests/{sample.pk}/').data['data']['products'][0]
        self.assertEqual((result['specification'], result['material_snapshot'], result['color']), ('60×80', '铝', '黑色'))
        product.refresh_from_db()
        self.assertEqual(product.specification, '60×80；颜色：黑色；材质：铝')
        current = self.client.get(f'/api/v1/sample-requests/{sample.pk}/')
        approved = self.review(current)
        payload = application_tests.SampleApplicationApiTests.completion_payload(self, approved)
        saved = self.client.patch(f'/api/v1/sample-requests/{sample.pk}/form/', {'payload': payload},
                                 format='json', HTTP_IF_MATCH=approved['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        product.refresh_from_db()
        self.assertEqual((product.specification, product.material_snapshot), ('60×80', '铝'))
