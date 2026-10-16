import json
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase
from apps.files.models import BusinessFile
from apps.inquiries.models import InquiryFileLink
from apps.samples.models import SampleRequest
from . import test_application_api as application_tests


@override_settings(FILE_VIRUS_SCAN_ENABLED=True)
class SampleApplicationImageTests(APITestCase):
    setUp = application_tests.SampleApplicationApiTests.setUp
    create_customer = application_tests.SampleApplicationApiTests.create_customer
    create_inquiry_with_item = application_tests.SampleApplicationApiTests.create_inquiry_with_item
    create_quotation_version_with_line = application_tests.SampleApplicationApiTests.create_quotation_version_with_line
    payload = application_tests.SampleApplicationApiTests.payload
    submit = application_tests.SampleApplicationApiTests.submit
    review = application_tests.SampleApplicationApiTests.review

    def image(self, inquiry, **changes):
        image = BusinessFile.objects.create(**{'original_name': '产品.png', 'storage_key': f'qa/{uuid.uuid4()}.png', 'content_type': 'image/png', 'size_bytes': 10, 'scan_status': 'CLEAN', **changes})
        InquiryFileLink.objects.create(inquiry=inquiry, business_file=image, file_role='CUSTOMER_ATTACHMENT')
        return image

    def source_payload(self, inquiry, item, **changes):
        return self.payload(source_type='inquiry', source_id=str(inquiry.pk), source_product_id=str(item.pk), product_name=item.product_description, specification=item.specification, **changes)

    def context(self, inquiry):
        return self.client.get('/api/v1/sample-requests/form-context/', {'sourceType': 'inquiry', 'sourceId': str(inquiry.pk)})

    def test_inherits_selected_source_image_and_sample_can_read_it(self):
        inquiry, item = self.create_inquiry_with_item()
        image = self.image(inquiry, scan_status='SKIPPED')
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            path = Path(folder) / image.storage_key
            path.parent.mkdir(parents=True)
            path.write_bytes(b'PNG sample')
            source = self.context(inquiry)
            self.assertEqual(source.status_code, 200, source.data)
            self.assertEqual(source.data['data']['reference_images'][0]['id'], str(image.pk))
            payload = self.source_payload(inquiry, item, source_reference_image_id=str(image.pk))
            result = self.submit(payload)
            self.assertEqual(result.status_code, 201, result.data)
            self.assertEqual(str(result.data['data']['reference_image']), str(image.pk))
            replay = self.submit(payload)
            self.assertEqual(replay.data['data']['id'], result.data['data']['id'])
            response = self.client.get(f"/api/v1/sample-requests/{result.data['data']['id']}/business-files/{image.pk}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'PNG sample')

    def test_foreign_unsafe_archived_and_unauthorized_images_are_rejected(self):
        from django.utils import timezone
        inquiry, item = self.create_inquiry_with_item()
        other, _ = self.create_inquiry_with_item(number='INQ-OTHER')
        for image in [self.image(other), self.image(inquiry, scan_status='PENDING'), self.image(inquiry, archived_at=timezone.now())]:
            result = self.submit(self.source_payload(inquiry, item, source_reference_image_id=str(image.pk)))
            self.assertEqual(result.status_code, 400, result.data)
        valid = self.image(inquiry)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='inquiries', codename='view_inquiryfilelink'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.context(inquiry).data['data']['reference_images'], [])
        self.assertEqual(self.submit(self.source_payload(inquiry, item, source_reference_image_id=str(valid.pk))).status_code, 400)

    def test_upload_replaces_inherited_image_without_changing_inquiry_attachment(self):
        inquiry, item = self.create_inquiry_with_item()
        original = self.image(inquiry)
        created = self.submit(self.source_payload(inquiry, item, source_reference_image_id=str(original.pk)))
        returned = self.review(created, 'return', '替换图片')
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder), patch('apps.files.uploads._clamav_scan', return_value='OK'):
            payload = self.source_payload(inquiry, item)
            file = SimpleUploadedFile('replacement.png', b'\x89PNG\r\n\x1a\n' + b'x' * 40, content_type='image/png')
            result = self.client.post(f"/api/v1/sample-requests/{created.data['data']['id']}/application-resubmit/", {'payload': json.dumps(payload), 'reference_image': file}, format='multipart', HTTP_IF_MATCH=returned['ETag'])
            self.assertEqual(result.status_code, 200, result.data)
            self.assertNotEqual(str(result.data['data']['reference_image']), str(original.pk))
            self.assertTrue(inquiry.file_links.filter(business_file=original).exists())

    def test_sample_creation_grant_does_not_grant_inquiry_image_access(self):
        from django.utils import timezone
        from apps.customers.models import CustomerAssignment, CustomerDataAccessGrant
        inquiry, item = self.create_inquiry_with_item()
        image = self.image(inquiry)
        CustomerAssignment.objects.filter(customer_account=self.customer).update(employee=self.other_employee)
        CustomerDataAccessGrant.objects.create(
            employee=self.employee, customer_account=self.customer,
            permission=Permission.objects.get(content_type__app_label='samples', codename='add_samplerequest'),
            effective_from=timezone.now(), reason='仅授权创建打样',
        )
        context = self.context(inquiry)
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual(context.data['data']['reference_images'], [])
        self.assertEqual(self.client.get(f'/api/v1/inquiries/{inquiry.pk}/images/{image.pk}/').status_code, 404)
        result = self.submit(self.source_payload(inquiry, item, source_reference_image_id=str(image.pk)))
        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn('source_reference_image_id', str(result.data))

    def test_quotation_product_image_is_listed_per_product_and_can_be_inherited(self):
        inquiry, inquiry_item = self.create_inquiry_with_item()
        image = BusinessFile.objects.create(
            original_name='报价产品图.png',
            storage_key=f'qa/{uuid.uuid4()}.png',
            content_type='image/png',
            size_bytes=10,
            scan_status='CLEAN',
        )
        _quotation, version, line = self.create_quotation_version_with_line(
            inquiry, inquiry_item, product_image=image,
        )

        source = self.client.get(
            '/api/v1/sample-requests/form-context/',
            {'sourceType': 'quotation', 'sourceId': str(version.pk)},
        )

        self.assertEqual(source.status_code, 200, source.data)
        self.assertEqual(source.data['data']['reference_images'], [])
        self.assertEqual(
            source.data['data']['products'][0]['reference_images'],
            [{
                'id': str(image.pk),
                'name': '报价产品图.png',
                'url': f'/api/v1/quotation-lines/{line.pk}/product-image/',
            }],
        )
        payload = self.payload(
            source_type='quotation',
            source_id=str(version.pk),
            source_product_id=str(line.pk),
            source_reference_image_id=str(image.pk),
            product_name=line.product_description_snapshot,
            specification=line.specification_snapshot,
        )
        result = self.submit(payload)
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(str(result.data['data']['reference_image']), str(image.pk))

    def test_quotation_image_from_another_product_is_rejected(self):
        inquiry, inquiry_item = self.create_inquiry_with_item()
        other_image = BusinessFile.objects.create(
            original_name='其他产品图.png',
            storage_key=f'qa/{uuid.uuid4()}.png',
            content_type='image/png',
            size_bytes=10,
            scan_status='CLEAN',
        )
        _quotation, version, line = self.create_quotation_version_with_line(
            inquiry, inquiry_item, other_product_image=other_image,
        )
        payload = self.payload(
            source_type='quotation',
            source_id=str(version.pk),
            source_product_id=str(line.pk),
            source_reference_image_id=str(other_image.pk),
            product_name=line.product_description_snapshot,
            specification=line.specification_snapshot,
        )

        result = self.submit(payload)

        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn('source_reference_image_id', str(result.data))
        self.assertFalse(SampleRequest.objects.filter(reference_image=other_image).exists())
