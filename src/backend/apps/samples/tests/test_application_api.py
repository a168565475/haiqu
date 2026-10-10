import uuid
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.middleware.csrf import _get_new_csrf_string
from rest_framework.test import APIClient, APITestCase
from apps.audit.models import AuditLog
from ..models import SampleRequest, SampleRequestStatus
from . import test_sample_api as legacy_tests


class SampleApplicationApiTests(APITestCase):
    setUp = legacy_tests.SampleApiTests.setUp
    create_customer = legacy_tests.SampleApiTests.create_customer
    create_inquiry_with_item = legacy_tests.SampleApiTests.create_inquiry_with_item
    create_quotation_version_with_line = legacy_tests.SampleApiTests.create_quotation_version_with_line

    def payload(self, **updates):
        data = {
            'customer_account_id': str(self.customer.pk), 'customer_contact_id': str(self.contact.pk), 'owner_employee_id': str(self.employee.pk),
            'source_type': None, 'source_id': None, 'source_product_id': None,
            'sample_type': 'PRE_SALES', 'shipping_method': 'MAIL', 'delivery_batch': 'SINGLE', 'is_repeat_order': False,
            'order_date': '2026-09-10', 'sample_due_date': '2026-09-18', 'product_name': '测试折叠椅', 'specification': '铝合金 黑色',
            'purpose': '测试要求', 'quantity': 3, 'length_cm': '50.00', 'armrest_width_cm': None, 'seat_width_cm': None,
            'back_height_cm': None, 'seat_height_cm': None, 'idempotency_key': str(uuid.uuid4()),
        }
        return {**data, **updates}

    def submit(self, payload=None, client=None):
        return (client or self.client).post('/api/v1/sample-requests/applications/', {'payload': payload or self.payload()}, format='json')

    def review(self, created, decision='approve', note='', etag=None, client=None):
        return (client or self.client).post(f"/api/v1/sample-requests/{created.data['data']['id']}/director-review/", {'decision': decision, 'note': note}, format='json', HTTP_IF_MATCH=etag or created['ETag'])

    def test_create_and_approve_preserve_all_fields_and_audit(self):
        created = self.submit()
        self.assertEqual(created.status_code, 201, created.data)
        data = created.data['data']
        self.assertTrue(data['request_number'].startswith('SRQ-'))
        self.assertEqual(data['status'], 'DIRECTOR_REVIEW')
        self.assertEqual(data['products'][0]['total_sample_quantity'], 3)
        self.assertEqual(data['products'][0]['length_cm'], '50.00')
        self.assertIsNone(data['products'][0]['task_sheet_file_id'])
        self.assertTrue(data['application_actions']['can_director_review'])
        approved = self.review(created, note='可以制作')
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data['data']['status'], 'MATERIALS_PENDING')
        self.assertEqual(approved.data['data']['director_note'], '可以制作')
        self.assertFalse(approved.data['data']['application_actions']['can_director_review'])
        self.assertTrue(AuditLog.objects.filter(object_id=data['id'], action='DIRECTOR_APPROVED').exists())
        self.assertEqual(self.review(created).status_code, 412)
        self.assertEqual(self.review(approved).status_code, 409)

    def test_return_edit_resubmit_approve_repeated_rounds(self):
        payload = self.payload()
        created = self.submit(payload)
        returned = self.review(created, 'return', '请补充颜色')
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertTrue(returned.data['data']['application_actions']['can_resubmit'])
        url = f"/api/v1/sample-requests/{created.data['data']['id']}/application-resubmit/"
        payload['specification'] = '铝合金 白色'
        resubmitted = self.client.post(url, {'payload': payload}, format='json', HTTP_IF_MATCH=returned['ETag'])
        self.assertEqual(resubmitted.status_code, 200, resubmitted.data)
        self.assertEqual(resubmitted.data['data']['status'], 'DIRECTOR_REVIEW')
        self.assertEqual(resubmitted.data['data']['products'][0]['specification'], '铝合金 白色')
        again = self.review(resubmitted, 'return', '请确认数量')
        payload['quantity'] = 4
        final = self.client.post(url, {'payload': payload}, format='json', HTTP_IF_MATCH=again['ETag'])
        self.assertEqual(self.review(final).status_code, 200)
        self.assertEqual(SampleRequest.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='DIRECTOR_RETURNED').count(), 2)

    def test_idempotency_replay_and_payload_conflict(self):
        payload = self.payload()
        created = self.submit(payload)
        replay = self.submit(payload)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(created.data['data']['id'], replay.data['data']['id'])
        payload['quantity'] = 9
        self.assertEqual(self.submit(payload).status_code, 409)
        self.assertEqual(SampleRequest.objects.count(), 1)

    def test_validation_and_source_contact_boundaries(self):
        for changes in [{'quantity': 0}, {'quantity': 1.2}, {'length_cm': '-1'}, {'sample_due_date': '2026-09-09'}, {'source_type': 'inquiry'}, {'customer_account_id': str(self.other_customer.pk)}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.submit(self.payload(**changes)).status_code, 400)
        self.assertEqual(SampleRequest.objects.count(), 0)

    def test_review_requires_dedicated_permission_and_active_actor(self):
        created = self.submit()
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='review_sample_application'))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.review(created).status_code, 403)
        self.employee.status = 'INACTIVE'
        self.employee.save()
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.submit().status_code, 403)

    def test_director_can_read_new_queue_without_customer_ownership(self):
        created = self.submit()
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'review_sample_application']))
        director = APIClient()
        director.force_authenticate(user=self.other_user)
        url = f"/api/v1/sample-requests/{created.data['data']['id']}/"
        self.assertEqual(director.get(url).status_code, 200)
        self.assertEqual(self.review(created, client=director).status_code, 200)

    def test_salesperson_cannot_read_unassigned_application_or_resubmit_others(self):
        created = self.submit()
        self.other_user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['view_samplerequest', 'add_samplerequest']))
        outsider = APIClient()
        outsider.force_authenticate(user=self.other_user)
        url = f"/api/v1/sample-requests/{created.data['data']['id']}/"
        self.assertEqual(outsider.get(url).status_code, 404)
        returned = self.review(created, 'return', '补充规格')
        self.assertEqual(outsider.post(url + 'application-resubmit/', {'payload': self.payload()}, format='json', HTTP_IF_MATCH=returned['ETag']).status_code, 404)

    def test_note_required_and_missing_stale_etag(self):
        created = self.submit()
        self.assertEqual(self.review(created, 'return', '  ').status_code, 400)
        self.assertEqual(self.review(created, note='字' * 501).status_code, 400)
        url = f"/api/v1/sample-requests/{created.data['data']['id']}/director-review/"
        self.assertEqual(self.client.post(url, {'decision': 'approve', 'note': ''}, format='json').status_code, 428)
        self.assertEqual(self.review(created, etag='"stale"').status_code, 412)

    def test_old_draft_does_not_enter_new_review(self):
        legacy = self.client.post('/api/v1/sample-requests/', legacy_tests.SampleApiTests.payload(self), format='json')
        self.assertEqual(legacy.status_code, 201, legacy.data)
        self.assertEqual(self.review(legacy).status_code, 409)

    def test_reference_image_scanned_and_readable_only_on_own_application(self):
        import json
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder), patch('apps.files.uploads._clamav_scan', return_value='OK'):
            file = SimpleUploadedFile('reference.png', b'\x89PNG\r\n\x1a\n' + b'x' * 40, content_type='image/png')
            created = self.client.post('/api/v1/sample-requests/applications/', {'payload': json.dumps(self.payload()), 'reference_image': file}, format='multipart')
            self.assertEqual(created.status_code, 201, created.data)
            data = created.data['data']
            image_id = data['reference_image']
            self.assertTrue(image_id)
            response = self.client.get(f"/api/v1/sample-requests/{data['id']}/business-files/{image_id}/")
            self.assertEqual(response.status_code, 200)
            for close_file in response._resource_closers:
                close_file()
            other = self.submit().data['data']['id']
            self.assertEqual(self.client.get(f"/api/v1/sample-requests/{other}/business-files/{image_id}/").status_code, 404)

    def test_session_csrf_required(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.submit(client=client).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies['csrftoken'] = csrf
        client.credentials(HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(self.submit(client=client).status_code, 201)

    def test_source_permissions_and_snapshot_resubmission(self):
        from apps.quotations.models import QuotationVersion
        inquiry, item = self.create_inquiry_with_item()
        quotation, version, line = self.create_quotation_version_with_line(inquiry, item)
        payload = self.payload(source_type='quotation', source_id=str(version.pk), source_product_id=str(line.pk), product_name=line.product_description_snapshot, specification=line.specification_snapshot)
        for source_type, app_label, codename, source_id, product_id in [
            ('inquiry', 'inquiries', 'view_inquiry', inquiry.pk, item.pk),
            ('quotation', 'quotations', 'view_quotationversion', version.pk, line.pk),
        ]:
            permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
            self.user.user_permissions.remove(permission)
            self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
            denied = self.submit({**payload, 'source_type': source_type, 'source_id': str(source_id), 'source_product_id': str(product_id)})
            self.assertEqual(denied.status_code, 403, denied.data)
            self.user.user_permissions.add(permission)
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        created = self.submit(payload)
        self.assertEqual(created.status_code, 201, created.data)
        returned = self.review(created, 'return', '补充数量')
        for changes in [
            {'source_type': 'inquiry', 'source_id': str(inquiry.pk), 'source_product_id': str(item.pk)},
            {'source_type': None, 'source_id': None, 'source_product_id': None},
        ]:
            tampered = self.client.post(f"/api/v1/sample-requests/{created.data['data']['id']}/application-resubmit/", {'payload': {**payload, **changes}}, format='json', HTTP_IF_MATCH=returned['ETag'])
            self.assertEqual(tampered.status_code, 400, tampered.data)
        QuotationVersion.objects.create(quotation=quotation, version_number=version.version_number + 1, status='DRAFT', currency_code=version.currency_code)
        payload['quantity'] = 5
        result = self.client.post(f"/api/v1/sample-requests/{created.data['data']['id']}/application-resubmit/", {'payload': payload}, format='json', HTTP_IF_MATCH=returned['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(str(result.data['data']['source_quotation_version']), str(version.pk))

    def test_returned_capability_closes_when_customer_scope_is_lost(self):
        from apps.customers.models import CustomerAssignment
        from django.utils import timezone
        created = self.submit()
        self.review(created, 'return', '补充规格')
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label='samples', codename__in=['add_samplerequest', 'view_samplerequest']))
        CustomerAssignment.objects.filter(customer_account=self.customer).update(effective_to=timezone.now())
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        response = self.client.get(f"/api/v1/sample-requests/{created.data['data']['id']}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['data']['application_actions']['can_resubmit'])
