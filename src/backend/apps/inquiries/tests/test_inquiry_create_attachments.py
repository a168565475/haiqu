import io
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.files.models import BusinessFile
from apps.imports.security import InfectedFile, ScannerUnavailable
from apps.inquiries.models import Inquiry, InquiryFileLink
from . import test_inquiry_api


@override_settings(FILE_VIRUS_SCAN_ENABLED=True)
class InquiryCreateAttachmentTests(APITestCase):
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def setUp(self):
        test_inquiry_api.InquiryApiTests.setUp(self)
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        result = self.create_inquiry(idempotency_key=str(uuid.uuid4()))
        self.inquiry_id = result.data['data']['id']
        self.etag = result['ETag']
        self.initial_file_count = BusinessFile.objects.count()
        self.url = f'/api/v1/inquiries/{self.inquiry_id}/attachments/'

    def upload(self, content=b'%PDF-1.4 test', name='需求.pdf', upload_id=None, etag=None):
        return self.client.post(self.url, {'file': SimpleUploadedFile(name, content), 'upload_id': upload_id or str(uuid.uuid4())}, format='multipart', HTTP_IF_MATCH=etag or self.etag)

    @patch('apps.inquiries.uploads._clamav_scan', return_value='stream: OK')
    def test_upload_links_file_versions_and_retry_does_not_duplicate(self, scanner):
        upload_id = str(uuid.uuid4())
        result = self.upload(upload_id=upload_id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertNotEqual(result['ETag'], self.etag)
        self.assertEqual(result.data['data']['scan_status'], 'CLEAN')
        self.assertEqual(result.data['data']['original_name'], '需求.pdf')
        stored = BusinessFile.objects.get(pk=upload_id)
        self.assertEqual((Path(self.media.name) / stored.storage_key).read_bytes(), b'%PDF-1.4 test')
        retry = self.upload(upload_id=upload_id)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.data['data']['id'], result.data['data']['id'])
        self.assertEqual(InquiryFileLink.objects.filter(inquiry_id=self.inquiry_id).count(), 1)
        scanner.assert_called_once()
        self.assertEqual(self.upload(content=b'%PDF-changed', upload_id=upload_id).status_code, 400)

    @patch('apps.inquiries.uploads._clamav_scan', return_value='stream: OK')
    def test_xlsx_and_rejected_format_signature_size(self, scanner):
        data = io.BytesIO()
        with ZipFile(data, 'w') as workbook:
            workbook.writestr('[Content_Types].xml', '<Types/>')
            workbook.writestr('xl/workbook.xml', '<workbook/>')
        result = self.upload(data.getvalue(), '规格.xlsx')
        self.assertEqual(result.status_code, 200, result.data)
        self.etag = result['ETag']
        self.initial_file_count = BusinessFile.objects.count()
        for content, name in [(b'plain', 'fake.pdf'), (b'PK\x03\x04bad', 'bad.xlsx'), (b'program', 'a.exe'), (b'x' * (10 * 1024 * 1024 + 1), 'large.pdf')]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(content, name).status_code, 400)
        self.assertEqual(scanner.call_count, 1)

    def test_scanner_unavailable_or_infected_does_not_link_or_leave_file(self):
        for error in [ScannerUnavailable(), InfectedFile()]:
            with self.subTest(error=type(error).__name__), patch('apps.inquiries.uploads._clamav_scan', side_effect=error):
                result = self.upload()
                self.assertIn(result.status_code, [400, 422, 503])
                self.assertFalse(InquiryFileLink.objects.filter(inquiry_id=self.inquiry_id).exists())
                self.assertEqual(BusinessFile.objects.count(), self.initial_file_count)
                self.assertEqual([path for path in Path(self.media.name).rglob('*') if path.is_file()], [])

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    @patch('apps.inquiries.uploads._clamav_scan', side_effect=ScannerUnavailable())
    def test_disabled_scan_saves_as_skipped_without_calling_scanner(self, scanner):
        result = self.upload()
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['data']['scan_status'], 'SKIPPED')
        scanner.assert_not_called()

    @override_settings(FILE_VIRUS_SCAN_ENABLED=False)
    @patch('apps.files.uploads._clamav_scan', side_effect=ScannerUnavailable())
    def test_product_image_saves_and_can_be_read_when_scanner_is_unavailable(self, scanner):
        item = Inquiry.objects.get(pk=self.inquiry_id).items.get()
        url = f'/api/v1/inquiry-items/{item.pk}/product-image/'
        content = b'\x89PNG\r\n\x1a\nproduct image'
        result = self.client.post(url, {'file': SimpleUploadedFile('product.png', content, content_type='image/png')}, format='multipart', HTTP_IF_MATCH=self.etag)
        self.assertEqual(result.status_code, 200, result.data)
        item.refresh_from_db()
        self.assertEqual(item.product_image.scan_status, 'SKIPPED')
        self.assertIsNone(item.product_image.scanned_at)
        scanner.assert_not_called()
        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b''.join(download.streaming_content), content)
        for state in ['PENDING', 'FAILED', 'INFECTED']:
            with self.subTest(state=state):
                BusinessFile.objects.filter(pk=item.product_image_id).update(scan_status=state)
                self.assertEqual(self.client.get(url).status_code, 400)

    @patch('apps.inquiries.uploads._clamav_scan')
    def test_permission_scope_version_and_submitted_guards_precede_scan(self, scanner):
        self.assertEqual(self.upload(etag='"stale"').status_code, 412)
        Inquiry.objects.filter(pk=self.inquiry_id).update(status='NEW')
        self.assertEqual(self.upload().status_code, 409)
        Inquiry.objects.filter(pk=self.inquiry_id).update(status='DRAFT')
        self.other_user.user_permissions.add(*self.user.user_permissions.all())
        self.client.force_authenticate(user=type(self.other_user).objects.get(pk=self.other_user.pk))
        self.assertEqual(self.upload().status_code, 404)
        self.client.force_authenticate(user=self.user)
        self.user.user_permissions.clear()
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.upload().status_code, 403)
        scanner.assert_not_called()

    @patch('apps.inquiries.uploads._clamav_scan', return_value='stream: OK')
    def test_link_failure_rolls_back_database_and_disk(self, scanner):
        with patch('apps.inquiries.services.link_inquiry_file', side_effect=RuntimeError('link failed')):
            self.client.raise_request_exception = False
            self.assertEqual(self.upload().status_code, 500)
        self.assertEqual(BusinessFile.objects.count(), self.initial_file_count)
        self.assertEqual([path for path in Path(self.media.name).rglob('*') if path.is_file()], [])

    def test_empty_draft_keeps_zero_budget_and_submit_requires_contact_and_product(self):
        result = self.create_inquiry(items=[], customer_contact_id=None, estimated_amount_min='0.00', estimated_amount_max='0.00', estimated_currency_code='USD')
        self.assertEqual(result.data['data']['estimated_amount_min'], '0.00')
        inquiry_id = result.data['data']['id']
        submit = self.client.post(f'/api/v1/inquiries/{inquiry_id}/submit/', {}, format='json', HTTP_IF_MATCH=result['ETag'])
        self.assertEqual(submit.status_code, 409)
        self.assertEqual(Inquiry.objects.get(pk=inquiry_id).status, 'DRAFT')

