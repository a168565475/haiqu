import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.middleware.csrf import _get_new_csrf_string
from rest_framework.test import APITestCase, APIClient

from apps.files.models import BusinessFile
from apps.imports.security import InfectedFile, ScannerUnavailable
from ..models import SampleRequest
from .test_application_products import SampleApplicationProductsTests as ProductTests


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
MEDIA = Path('/tmp/sample-editor-unit01-annotations-a15dac-media')


@override_settings(FILE_VIRUS_SCAN_ENABLED=True)
class SampleApplicationProductImageTests(APITestCase):
    create_customer = ProductTests.create_customer
    payload = ProductTests.payload
    submit = ProductTests.submit
    review = ProductTests.review
    product = ProductTests.product
    prepared = ProductTests.prepared

    def setUp(self):
        ProductTests.setUp(self)
        MEDIA.mkdir(exist_ok=True)
        folder = TemporaryDirectory(prefix='case-', dir=MEDIA)
        self.addCleanup(folder.cleanup)
        override = self.settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)

    def file(self, name='reference.png', content=PNG, content_type='image/png'):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def upload(self, approved, data, file=None, etag=None, client=None, **extra):
        return (client or self.client).patch(f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/",
                                 {'payload': json.dumps(data), 'reference_image': file or self.file(), **extra},
                                 format='multipart', HTTP_IF_MATCH=etag or approved['ETag'])

    def old_image(self, approved):
        image_path = Path(settings.MEDIA_ROOT) / 'source/old.png'
        image_path.parent.mkdir()
        image_path.write_bytes(PNG)
        image = BusinessFile.objects.create(original_name='old.png', storage_key='source/old.png', content_type='image/png', size_bytes=len(PNG), scan_status='CLEAN')
        SampleRequest.objects.filter(pk=approved.data['data']['id']).update(reference_image=image)
        return image, image_path

    def test_real_png_scan_and_atomic_replacement_preserve_old_shared_image(self):
        approved, _, data = self.prepared()
        old, old_path = self.old_image(approved)
        response = self.upload(approved, data)
        self.assertEqual(response.status_code, 200, response.data)
        new = BusinessFile.objects.get(pk=response.data['data']['reference_image'])
        self.assertNotEqual(new.pk, old.pk)
        self.assertEqual(new.scan_status, 'CLEAN')
        self.assertEqual((Path(settings.MEDIA_ROOT) / new.storage_key).read_bytes(), PNG)
        self.assertTrue(old_path.exists())
        self.assertTrue(BusinessFile.objects.filter(pk=old.pk).exists())
        self.assertNotEqual(response['ETag'], approved['ETag'])
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/business-files/{new.pk}/"
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200)
        for close_file in result._resource_closers:
            close_file()

    def test_json_without_image_preserves_old_reference(self):
        approved, _, data = self.prepared()
        old, old_path = self.old_image(approved)
        response = ProductTests.save(self, approved, data)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(str(response.data['data']['reference_image']), str(old.pk))
        self.assertTrue(old_path.exists())

    def test_invalid_format_signature_size_and_multipart_shape(self):
        approved, _, data = self.prepared()
        for file in [self.file('bad.gif', b'GIF89a', 'image/gif'), self.file(content=b'not png'), self.file(content=b'x' * (5 * 1024 * 1024 + 1)), self.file(content=b'')]:
            with self.subTest(name=file.name, size=file.size):
                self.assertEqual(self.upload(approved, data, file=file).status_code, 400)
        self.assertEqual(self.upload(approved, data, unknown=self.file()).status_code, 400)
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/"
        self.assertEqual(self.client.patch(url, {'payload': json.dumps(data), 'reference_image': [self.file(), self.file()]}, format='multipart', HTTP_IF_MATCH=approved['ETag']).status_code, 400)
        self.assertEqual(self.client.patch(url, {'payload': '{bad', 'reference_image': self.file()}, format='multipart', HTTP_IF_MATCH=approved['ETag']).status_code, 400)
        self.assertFalse(BusinessFile.objects.filter(storage_key__startswith='samples/application-references').exists())

    def test_stale_etag_permission_and_foreign_products_reject_before_file_storage(self):
        approved, _, data = self.prepared()
        with patch('apps.samples.application_product_services.save_scanned_image') as save:
            self.assertEqual(self.upload(approved, data, etag='"stale"').status_code, 412)
            self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='complete_sample_requirements'))
            self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
            self.assertEqual(self.upload(approved, data).status_code, 403)
            save.assert_not_called()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='samples', codename='complete_sample_requirements'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        created = self.submit()
        with patch('apps.samples.application_product_services.save_scanned_image') as save:
            self.assertEqual(self.upload(created, data).status_code, 400)
            save.assert_not_called()

    def test_multipart_session_requires_csrf_and_version(self):
        approved, _, data = self.prepared()
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.upload(approved, data, client=client).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies['csrftoken'] = csrf
        client.credentials(HTTP_X_CSRFTOKEN=csrf)
        url = f"/api/v1/sample-requests/{approved.data['data']['id']}/application-products/"
        self.assertEqual(client.patch(url, {'payload': json.dumps(data), 'reference_image': self.file()}, format='multipart').status_code, 428)
        self.assertEqual(self.upload(approved, data, client=client).status_code, 200)

    def test_scan_errors_rollback_product_and_keep_old_image(self):
        approved, _, data = self.prepared()
        old, old_path = self.old_image(approved)
        for error, status in [(InfectedFile('infected'), 422), (ScannerUnavailable('offline'), 503)]:
            with self.subTest(status=status), patch('apps.files.uploads._clamav_scan', side_effect=error):
                self.assertEqual(self.upload(approved, data).status_code, status)
                sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
                self.assertEqual(sample.status, 'PENDING_COMPLETION')
                self.assertEqual(sample.reference_image_id, old.pk)
                self.assertIsNone(sample.products.get().category_id)
                self.assertTrue(old_path.exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob('*.png')), [old_path])

    def test_audit_failure_rolls_back_db_and_removes_only_new_physical_file(self):
        approved, _, data = self.prepared()
        old, old_path = self.old_image(approved)
        with patch('apps.samples.application_product_services._write_sample_records', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                self.upload(approved, data)
        sample = SampleRequest.objects.get(pk=approved.data['data']['id'])
        self.assertEqual(sample.status, 'PENDING_COMPLETION')
        self.assertEqual(sample.reference_image_id, old.pk)
        self.assertIsNone(sample.products.get().category_id)
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob('*.png')), [old_path])
        self.assertFalse(BusinessFile.objects.filter(storage_key__startswith='samples/application-references').exists())
