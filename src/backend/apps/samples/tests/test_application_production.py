import uuid
from copy import deepcopy
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase
from . import test_material_api as material_tests
from ..models import SampleParameterImage, SampleRequest, SampleWorkflowStage, SampleMaterialRequest
from ..inventory_selectors import eligible_sample_items_for_inventory


class ApplicationProductionTests(APITestCase):
    setUp = material_tests.SampleMaterialApiTests.setUp
    create_customer = material_tests.SampleMaterialApiTests.create_customer
    create_inquiry_with_item = material_tests.SampleMaterialApiTests.create_inquiry_with_item
    create_quotation_version_with_line = material_tests.SampleMaterialApiTests.create_quotation_version_with_line
    payload = material_tests.SampleMaterialApiTests.payload
    submit = material_tests.SampleMaterialApiTests.submit
    review = material_tests.SampleMaterialApiTests.review
    prepare = material_tests.SampleMaterialApiTests.prepare
    draft = material_tests.SampleMaterialApiTests.draft
    put = material_tests.SampleMaterialApiTests.put
    to_warehouse = material_tests.SampleMaterialApiTests.to_warehouse
    supplies = material_tests.SampleMaterialApiTests.supplies

    def no_materials(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        response = self.client.post(self.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def upload(self, kind, etag):
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder), patch('apps.samples.uploads._clamav_scan', return_value='CLEAN'):
            return self.client.post(self.root + kind + '-parameters/',
                                    {'file': SimpleUploadedFile('parameters.png', b'\x89PNG\r\n\x1a\n', content_type='image/png')},
                                    format='multipart', HTTP_IF_MATCH=etag)

    def report(self, etag, complete=True):
        sample = SampleRequest.objects.get(pk=self.root.split('/')[-2])
        rows = [{'id': str(item.pk), 'metalwork_reported_quantity': 3 if complete else 1,
                 'cutting_reported_quantity': 3 if complete else 0,
                 'metalwork_completed': complete, 'cutting_completed': complete} for item in sample.items.all()]
        return self.client.post(self.root + 'production-report/', {'items': rows}, format='json', HTTP_IF_MATCH=etag)

    def test_no_materials_preserves_draft_and_does_not_forge_approvals(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        saved = self.put('materials', self.draft(), False, state['ETag'])
        done = self.client.post(self.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=saved['ETag'])
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['data']['status'], 'METALWORK_PENDING')
        record = SampleMaterialRequest.objects.get()
        self.assertTrue(record.no_materials)
        warehouse = self.client.get(self.root + 'warehouse-review/')
        self.assertEqual(warehouse.status_code, 200)
        self.assertFalse(warehouse.data['data']['available'])
        self.assertEqual(len(record.draft['lines']), 3)
        self.assertEqual(done.data['data']['progress']['label'], '无需用料')
        self.assertFalse(record.sample_request.workflow_records.filter(stage__in=['PMC_APPROVED', 'FINANCE_CONFIRMED']).exists())
        self.assertEqual(self.client.post(self.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=saved['ETag']).status_code, 412)
        self.assertEqual(self.client.post(self.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=done['ETag']).status_code, 409)

    def test_parameters_first_waits_for_reports_then_becomes_eligible(self):
        ready = self.no_materials()
        metal = self.upload('metalwork', ready['ETag'])
        self.assertEqual(metal.status_code, 200, metal.data)
        cut = self.upload('cutting', metal['ETag'])
        self.assertEqual(cut.status_code, 200, cut.data)
        self.assertEqual(cut.data['data']['status'], 'PRODUCTION_PENDING')
        self.assertFalse(eligible_sample_items_for_inventory().exists())
        incomplete = self.report(cut['ETag'], False)
        self.assertEqual(incomplete.data['data']['status'], 'PRODUCTION_PENDING')
        done = self.report(incomplete['ETag'])
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['data']['status'], 'FINISHED')
        self.assertEqual(eligible_sample_items_for_inventory().count(), 1)
        self.assertFalse(done.data['data']['workflow_actions']['can_report_production'])
        sample = SampleRequest.objects.get(pk=done.data['data']['id'])
        SampleParameterImage.objects.filter(sample_request=sample, parameter_type='METALWORK').update(archived_at=sample.updated_at)
        self.assertFalse(eligible_sample_items_for_inventory().exists())

    def test_reports_first_allows_either_parameter_order(self):
        ready = self.no_materials()
        cutting = self.upload('cutting', ready['ETag'])
        self.assertEqual(cutting.status_code, 200, cutting.data)
        self.assertEqual(cutting.data['data']['status'], 'METALWORK_PENDING')
        reported = self.report(cutting['ETag'])
        self.assertEqual(reported.status_code, 200, reported.data)
        self.assertEqual(reported.data['data']['status'], 'METALWORK_PENDING')
        self.assertFalse(eligible_sample_items_for_inventory().exists())
        metal = self.upload('metalwork', reported['ETag'])
        self.assertEqual(metal.status_code, 200, metal.data)
        self.assertEqual(metal.data['data']['status'], 'FINISHED')
        self.assertEqual(eligible_sample_items_for_inventory().count(), 1)

    def test_deleting_last_parameter_image_returns_to_missing_stage(self):
        ready = self.no_materials()
        uploaded = self.upload('cutting', ready['ETag'])
        self.assertEqual(uploaded.status_code, 200, uploaded.data)
        image_id = uploaded.data['data']['parameter_images'][0]['id']
        deleted = self.client.delete(
            self.root + f'parameter-images/{image_id}/',
            HTTP_IF_MATCH=uploaded['ETag'],
        )
        self.assertEqual(deleted.status_code, 200, deleted.data)
        self.assertEqual(deleted.data['data']['status'], 'METALWORK_PENDING')
        self.assertEqual(deleted.data['data']['parameter_images'], [])

    def test_report_validation_permissions_and_material_gate(self):
        self.prepare()
        state = self.client.get(self.root + 'materials/')
        self.assertEqual(self.report(state['ETag']).status_code, 409)
        ready = self.client.post(self.root + 'no-materials/', {}, format='json', HTTP_IF_MATCH=state['ETag'])
        item_id = str(SampleRequest.objects.get(pk=self.root.split('/')[-2]).items.get().pk)
        base = {'id': item_id, 'metalwork_reported_quantity': 0, 'cutting_reported_quantity': 0,
                'metalwork_completed': False, 'cutting_completed': False}
        for change in [{'id': str(uuid.uuid4())}, {'metalwork_reported_quantity': 4}, {'cutting_reported_quantity': -1}]:
            bad = self.client.post(self.root + 'production-report/', {'items': [{**base, **change}]}, format='json', HTTP_IF_MATCH=ready['ETag'])
            self.assertEqual(bad.status_code, 400, bad.data)
        completed_without_quantity = self.client.post(
            self.root + 'production-report/',
            {'items': [{**base, 'metalwork_completed': True}]},
            format='json', HTTP_IF_MATCH=ready['ETag'],
        )
        self.assertEqual(completed_without_quantity.status_code, 400, completed_without_quantity.data)
        self.assertEqual(self.report('').status_code, 428)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='change_samplerequest'))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.report(ready['ETag']).status_code, 403)

    def test_backfill_is_dry_run_by_default_and_only_advances_verified_ready(self):
        state = self.to_warehouse()
        done = self.put('warehouse-review', self.supplies(state, ('12', '6', '4')), True, state['ETag'])
        sample_id = self.root.split('/')[-2]
        SampleRequest.objects.filter(pk=sample_id).update(status='MATERIALS_READY')
        SampleRequest.objects.get(pk=sample_id).workflow_records.filter(stage='MATERIALS_READY').delete()
        call_command('advance_ready_sample_applications', stdout=StringIO())
        self.assertEqual(SampleRequest.objects.get(pk=sample_id).status, 'MATERIALS_READY')
        call_command('advance_ready_sample_applications', '--apply', '--sample-id', sample_id, stdout=StringIO())
        self.assertEqual(SampleRequest.objects.get(pk=sample_id).status, 'METALWORK_PENDING')
