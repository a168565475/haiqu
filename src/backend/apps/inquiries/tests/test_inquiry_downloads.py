from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth.models import Permission
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.files.models import BusinessFile
from ..models import Inquiry, InquiryFileLink
from . import test_inquiry_api


class InquiryDownloadTests(APITestCase):
    setUp = test_inquiry_api.InquiryApiTests.setUp
    create_customer = test_inquiry_api.InquiryApiTests.create_customer
    inquiry_payload = test_inquiry_api.InquiryApiTests.inquiry_payload
    create_inquiry = test_inquiry_api.InquiryApiTests.create_inquiry

    def consume(self, response):
        # 测试客户端迭代文件会触发请求结束；不让它关闭 APITestCase 正在使用的事务连接。
        request_finished.disconnect(close_old_connections)
        try:
            return b''.join(response.streaming_content)
        finally:
            request_finished.connect(close_old_connections)

    def attach(self, inquiry_id, folder, key, name='规格.pdf', scan='CLEAN'):
        (Path(folder) / key).write_bytes(b'attachment-content')
        business_file = BusinessFile.objects.create(original_name=name, storage_key=key, content_type='application/pdf', size_bytes=18, scan_status=scan)
        InquiryFileLink.objects.create(inquiry_id=inquiry_id, business_file=business_file, file_role='REQUIREMENT')
        return business_file

    def test_single_and_zip_preserve_content_and_unique_safe_names(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            first = self.attach(inquiry_id, folder, 'first.pdf')
            self.attach(inquiry_id, folder, 'second.pdf')
            self.attach(inquiry_id, folder, 'third.pdf', name='../危险/名称.pdf')
            response = self.client.get(f'/api/v1/inquiries/{inquiry_id}/files/{first.pk}/download/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response['Content-Disposition'])
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(self.consume(response), b'attachment-content')
            response = self.client.get(f'/api/v1/inquiries/{inquiry_id}/files-download/')
            self.assertEqual(response.status_code, 200)
            with ZipFile(BytesIO(self.consume(response))) as bundle:
                self.assertEqual(len(bundle.namelist()), 3)
                self.assertEqual(len(set(bundle.namelist())), 3)
                for name in bundle.namelist():
                    self.assertNotIn('/', name)
                    self.assertNotIn('\\', name)
                    self.assertEqual(bundle.read(name), b'attachment-content')

    def test_scan_and_missing_file_never_return_partial_archive(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            file = self.attach(inquiry_id, folder, 'unsafe.pdf', scan='PENDING')
            single = f'/api/v1/inquiries/{inquiry_id}/files/{file.pk}/download/'
            bulk = f'/api/v1/inquiries/{inquiry_id}/files-download/'
            for state in ['PENDING', 'INFECTED', 'FAILED', 'SKIPPED']:
                BusinessFile.objects.filter(pk=file.pk).update(scan_status=state)
                self.assertEqual(self.client.get(single).status_code, 400)
                self.assertEqual(self.client.get(bulk).status_code, 400)
            BusinessFile.objects.filter(pk=file.pk).update(scan_status='CLEAN', storage_key='missing.pdf')
            self.assertEqual(self.client.get(single).status_code, 404)
            self.assertEqual(self.client.get(bulk).status_code, 404)

    def test_permissions_foreign_link_archive_and_path_escape(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        other_id = self.create_inquiry().data['data']['id']
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            file = self.attach(other_id, folder, 'file.pdf')
            single = f'/api/v1/inquiries/{inquiry_id}/files/{file.pk}/download/'
            self.assertEqual(self.client.get(single).status_code, 404)
            single = f'/api/v1/inquiries/{other_id}/files/{file.pk}/download/'
            BusinessFile.objects.filter(pk=file.pk).update(storage_key='../outside.pdf')
            self.assertEqual(self.client.get(single).status_code, 404)
            BusinessFile.objects.filter(pk=file.pk).update(storage_key='file.pdf', archived_at=timezone.now())
            self.assertEqual(self.client.get(single).status_code, 404)
            BusinessFile.objects.filter(pk=file.pk).update(archived_at=None)
            Inquiry.objects.filter(pk=other_id).update(customer_account=self.other_customer, transaction_entity=None, customer_contact=None)
            self.assertEqual(self.client.get(single).status_code, 404)
            self.assertEqual(self.client.get(f'/api/v1/inquiries/{other_id}/files-download/').status_code, 404)
            Inquiry.objects.filter(pk=other_id).update(customer_account=self.customer)
            self.user.user_permissions.remove(Permission.objects.get(codename='view_inquiryfilelink'))
            self.client.force_authenticate(user=self.user.__class__.objects.get(pk=self.user.pk))
            self.assertEqual(self.client.get(single).status_code, 403)
            self.assertEqual(self.client.get(f'/api/v1/inquiries/{other_id}/files-download/').status_code, 403)

    def test_empty_and_count_limit(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        url = f'/api/v1/inquiries/{inquiry_id}/files-download/'
        self.assertEqual(self.client.get(url).status_code, 400)
        files = BusinessFile.objects.bulk_create([BusinessFile(original_name=f'{index}.pdf', storage_key=f'{index}.pdf', content_type='application/pdf', size_bytes=1, scan_status='CLEAN') for index in range(101)])
        InquiryFileLink.objects.bulk_create([InquiryFileLink(inquiry_id=inquiry_id, business_file=file, file_role='REQUIREMENT') for file in files])
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_task_created_from_detail_links_to_inquiry(self):
        inquiry_id = self.create_inquiry().data['data']['id']
        response = self.client.post('/api/v1/tasks/', {
            'title': '确认包装要求', 'assignee_employee_id': str(self.employee.pk),
            'source_type': 'INQUIRY', 'source_id': inquiry_id,
            'task_type': 'OTHER', 'priority': 'NORMAL',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        inquiry = Inquiry.objects.get(pk=inquiry_id)
        self.assertTrue(inquiry.task_links.filter(business_task_id=response.data['data']['id'], is_primary_source=True).exists())
        tasks = self.client.get(f'/api/v1/inquiries/{inquiry_id}/tasks/')
        self.assertEqual(tasks.status_code, 200)
        self.assertIn(response.data['data']['id'], [row['id'] for row in tasks.data['data']])
