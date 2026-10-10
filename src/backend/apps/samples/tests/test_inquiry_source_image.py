from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from apps.files.models import BusinessFile
from apps.inquiries.models import InquiryFileLink
from apps.samples.models import SampleRequest
from . import test_application_api as fixture


class InquirySourceImageTests(APITestCase):
    setUp = fixture.SampleApplicationApiTests.setUp
    create_customer = fixture.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = fixture.SampleApplicationApiTests.create_inquiry_with_item
    payload = fixture.SampleApplicationApiTests.payload
    submit = fixture.SampleApplicationApiTests.submit

    def source(self):
        inquiry, item = self.create_inquiry_with_item()
        image = BusinessFile.objects.create(original_name='产品.png', storage_key='test-sample/inquiry.png', content_type='image/png', size_bytes=100, scan_status='CLEAN')
        InquiryFileLink.objects.create(inquiry=inquiry, business_file=image, file_role='REFERENCE')
        payload = self.payload(source_type='inquiry', source_id=str(inquiry.pk), source_product_id=str(item.pk), source_reference_image_id=str(image.pk), product_name=item.product_description, specification=item.specification)
        return image, payload

    def test_source_inquiry_image_is_saved_as_sample_product_image(self):
        image, payload = self.source()
        response = self.submit(payload)
        self.assertEqual(response.status_code, 201, response.data)
        sample = SampleRequest.objects.get(pk=response.data['data']['id'])
        self.assertEqual(sample.reference_image_id, image.pk)
        self.assertEqual(str(response.data['data']['reference_image']), str(image.pk))

    def test_source_image_requires_permission_and_cannot_mix_with_remove(self):
        image, payload = self.source()
        self.assertEqual(self.submit({**payload, 'remove_reference_image': True}).status_code, 400)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inquiries', codename='view_inquiryfilelink'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.submit(payload).status_code, 400)
        self.assertEqual(SampleRequest.objects.count(), 0)
