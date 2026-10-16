from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry, InquiryFileLink
from apps.inquiries.tests import test_inquiry_api as fixture
from apps.quotations.models import Quotation, QuotationVersion, QuotationLine


class InquiryProductImageTests(APITestCase):
    create_customer = fixture.InquiryApiTests.create_customer
    inquiry_payload = fixture.InquiryApiTests.inquiry_payload
    create_inquiry = fixture.InquiryApiTests.create_inquiry

    def setUp(self):
        fixture.InquiryApiTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='quotations'))
        self.inquiry = Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        self.quote = Quotation.objects.create(quotation_number='IMAGE-TEST', customer_account=self.customer, transaction_entity=self.entity, owner_employee=self.employee, source_inquiry=self.inquiry)
        self.version = QuotationVersion.objects.create(quotation=self.quote, version_number=1, currency_code='USD')
        self.line = QuotationLine.objects.create(quotation_version=self.version, line_number=1, product_description_snapshot='测试产品', quantity=10, unit_code='PCS')
        self.url = f'/api/v1/quotation-lines/{self.line.pk}/product-image/'
        self.list_url = f'/api/v1/quotations/{self.quote.pk}/inquiry-images/'
        self.image = self.add_image('product.png')

    def add_image(self, name, inquiry=None, scan='CLEAN', role='REFERENCE'):
        image = BusinessFile.objects.create(original_name=name, storage_key='test-inquiry-images/' + name, content_type='image/png', size_bytes=100, scan_status=scan)
        InquiryFileLink.objects.create(inquiry=inquiry or self.inquiry, business_file=image, file_role=role)
        return image

    def select(self, image_id, etag=None):
        return self.client.post(self.url, {'source_image_id': str(image_id)}, format='json', HTTP_IF_MATCH=etag or etag_for_instance(self.version))

    def test_select_source_image_persists_and_keeps_version_lock(self):
        listing = self.client.get(self.list_url)
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual([item['id'] for item in listing.data['data']], [str(self.image.pk)])
        old_etag = etag_for_instance(self.version)
        response = self.select(self.image.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.line.refresh_from_db()
        self.assertEqual(self.line.product_image_id, self.image.pk)
        self.assertNotEqual(response.headers['ETag'], old_etag)
        self.assertEqual(self.select(self.image.pk, old_etag).status_code, 412)
        self.version.refresh_from_db()
        self.version.status = 'ISSUED'
        self.version.locked_at = timezone.now()
        self.version.transaction_entity_snapshot = {'legal_name': '测试主体'}
        self.version.address_snapshot = {'address': '测试地址'}
        self.version.contact_snapshot = {'name': '测试联系人'}
        self.version.save()
        self.assertEqual(self.select(self.image.pk).status_code, 409)

    def test_foreign_unscanned_communication_and_malformed_images_are_rejected(self):
        foreign = Inquiry.objects.get(pk=self.create_inquiry().data['data']['id'])
        images = [self.add_image('foreign.png', inquiry=foreign), self.add_image('pending.png', scan='PENDING'), self.add_image('chat.png', role='COMMUNICATION_IMAGE')]
        listing = self.client.get(self.list_url)
        self.assertEqual([item['id'] for item in listing.data['data']], [str(self.image.pk)])
        for image_id in [*(image.pk for image in images), 'not-uuid']:
            self.assertEqual(self.select(image_id).status_code, 400)
        self.line.refresh_from_db()
        self.assertIsNone(self.line.product_image_id)

    def test_source_image_requires_inquiry_file_permission(self):
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inquiries', codename='view_inquiryfilelink'))
        for name in ['_perm_cache', '_user_perm_cache', '_group_perm_cache']:
            self.user.__dict__.pop(name, None)
        self.assertEqual(self.client.get(self.list_url).data['data'], [])
        self.assertEqual(self.select(self.image.pk).status_code, 400)

    def test_skipped_source_image_can_be_selected_but_failed_and_infected_cannot(self):
        skipped = self.add_image('skipped.png', scan='SKIPPED')
        for state in ['FAILED', 'INFECTED']:
            image = self.add_image(f'{state}.png', scan=state)
            self.assertEqual(self.select(image.pk).status_code, 400)
        listing = self.client.get(self.list_url)
        self.assertIn(str(skipped.pk), [item['id'] for item in listing.data['data']])
        response = self.select(skipped.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.line.refresh_from_db()
        self.assertEqual(self.line.product_image_id, skipped.pk)
