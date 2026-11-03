"""隔离数据库中的单元/API 回归；模型与扫描替身不作为真实验收。"""
from copy import deepcopy
from datetime import timedelta
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from openpyxl import Workbook
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APITestCase

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask
from apps.production_tasks.tests import test_production_task_api as fixtures
from ..models import ProductionTaskImport
from ..review import HEADER_FIELDS, PRODUCT_FIELDS
from ..storage import ImportFailure, source_path
from ..worker import preprocess_once, expire_once, finish_import


ROOT = '/api/v1/production-task-imports/'


@override_settings(ACCESS_MANAGEMENT_ENABLED=False, DEV_AUTO_LOGIN_ENABLED=False, FILE_VIRUS_SCAN_ENABLED=True)
class ImportApiTests(APITestCase):
    payload = fixtures.ProductionTaskApiTests.payload

    def setUp(self):
        fixtures.ProductionTaskApiTests.setUp(self)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label='production_task_imports', codename='import_production_task'))
        self.client.force_authenticate(None)
        self.client.force_login(self.user)
        self.temp = TemporaryDirectory(prefix='production-import-tests-')
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(PRODUCTION_IMPORT_ROOT=Path(self.temp.name) / 'sources',
                                                  MEDIA_ROOT=Path(self.temp.name) / 'media')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def upload(self, key=None, text='测试任务'):
        workbook = Workbook()
        workbook.active['A1'] = text
        output = io.BytesIO()
        workbook.save(output)
        return self.client.post(ROOT, {'client_request_id': str(key or uuid4()),
            'file': SimpleUploadedFile('task.xlsx', output.getvalue())}, format='multipart')

    def checked(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        with patch('apps.production_task_imports.worker.scan_source'):
            self.assertTrue(preprocess_once())
        record = ProductionTaskImport.objects.get(pk=response.data['data']['id'])
        self.assertEqual(record.state, 'QUEUED', record.error_code)
        return record

    def reviewable(self):
        record = self.checked()
        record.state, record.result_revision = 'REVIEW', 1
        record.extraction = {'fields': {}, 'products': [{'line_key': 'product-1', 'fields': {}}],
                             'issues': [], 'image_candidates': []}
        record.save()
        payload = self.payload()
        review = {'payload': {key: value for key, value in payload.items()
                              if key not in ('contract_number', 'contract_number_token')},
                  'confirmed_fields': list(HEADER_FIELDS) + ['products.product-1.' + field for field in PRODUCT_FIELDS],
                  'issues': {}, 'selected_images': {}}
        response = self.client.patch(f'{ROOT}{record.pk}/review/', {'review': review},
            format='json', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertEqual(response.status_code, 200, response.data)
        record.refresh_from_db()
        return record, {**payload, 'import_object_id': str(record.pk), 'result_revision': 1}

    def test_upload_idempotence_and_different_content_conflict(self):
        # 相同字节，避免 ZIP 时间戳影响测试。
        first = self.upload()
        self.assertEqual(first.status_code, 201, first.data)
        record = ProductionTaskImport.objects.get(pk=first.data['data']['id'])
        data = source_path(record).read_bytes()
        second = self.client.post(ROOT, {'client_request_id': str(record.client_request_id),
            'file': SimpleUploadedFile('renamed.xlsx', data)}, format='multipart')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(str(second.data['data']['id']), str(record.pk))
        self.assertEqual(self.upload(record.client_request_id, '另一个任务').status_code, 409)
        self.assertEqual(ProductionTaskImport.objects.count(), 1)

    def test_session_csrf_permissions_and_owner_only_sources(self):
        record = self.checked()
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(ROOT, {}, format='json').status_code, 403)
        other = get_user_model().objects.create_superuser('other_import_user', '', 'password')
        Employee.objects.create(user=other, employee_code='OTHER_IMPORT', display_name='其他员工')
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'{ROOT}{record.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'{ROOT}{record.pk}/source/?download=1').status_code, 404)
        self.client.force_login(self.user)
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label='production_task_imports', codename='import_production_task'))
        self.assertEqual(self.client.get(f'{ROOT}{record.pk}/').status_code, 403)

    def test_invalid_upload_and_missing_schema_are_explicit(self):
        invalid = self.client.post(ROOT, {'client_request_id': str(uuid4()),
            'file': SimpleUploadedFile('task.xls', b'anything')}, format='multipart')
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.get(ROOT + 'invalid-uuid/').status_code, 400)
        with patch('apps.production_task_imports.readiness.MigrationRecorder.Migration.objects.filter') as query:
            query.return_value.exists.return_value = False
            self.assertEqual(self.client.get(ROOT + str(uuid4()) + '/').status_code, 503)

    def test_import_openapi_validates_and_documents_etag(self):
        from django.urls import include, path
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        schema = SchemaGenerator(patterns=[path('api/v1/', include('apps.production_task_imports.urls'))]).get_schema(public=True)
        validate_schema(schema)
        paths = schema['paths']
        self.assertIn(ROOT, paths)
        review_path = next(value for key, value in paths.items() if key.endswith('/review/'))
        self.assertTrue(any(item['name'] == 'If-Match' and item['required'] for item in review_path['patch']['parameters']))

    def test_scan_failure_never_queues_or_exposes_source(self):
        uploaded = self.upload()
        with patch('apps.production_task_imports.worker.scan_source', side_effect=ImportFailure('SCAN_INFECTED')):
            preprocess_once()
        record = ProductionTaskImport.objects.get(pk=uploaded.data['data']['id'])
        self.assertEqual((record.state, record.scan_status), ('FAILED', 'INFECTED'))
        self.assertEqual(self.client.get(f'{ROOT}{record.pk}/source/').status_code, 404)

    def test_changed_source_is_rejected_before_zip_read(self):
        record = self.checked()
        path = source_path(record)
        path.write_bytes(b'PK\x03\x04modified')
        response = self.client.get(f'{ROOT}{record.pk}/source/?download=1')
        self.assertEqual(response.status_code, 422)

    def test_mutations_require_etag_and_do_not_accept_commands(self):
        record = self.checked()
        url = f'{ROOT}{record.pk}/cancel/'
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 428)
        self.assertEqual(self.client.post(url, {}, format='json', HTTP_IF_MATCH='"stale"').status_code, 412)
        self.assertEqual(self.client.post(url, {'command': 'anything'}, format='json',
            HTTP_IF_MATCH=etag_for_instance(record)).status_code, 400)
        self.assertEqual(self.client.post(url, {}, format='json', HTTP_IF_MATCH=etag_for_instance(record)).status_code, 200)

    def test_review_save_retry_is_same_task_and_saved_tombstone_blocks_recreation(self):
        record, payload = self.reviewable()
        before = ProductionTask.objects.count()
        saved = self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertEqual(saved.status_code, 201, saved.data)
        replay = self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH='"stale"')
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data['data']['id'], saved.data['data']['id'])
        self.assertEqual(ProductionTask.objects.count(), before + 1)
        task = ProductionTask.objects.get(pk=saved.data['data']['id'])
        task.archived_at = timezone.now()
        task.save(update_fields=['archived_at'])
        self.assertEqual(self.client.post('/api/v1/production-tasks/', payload, format='json').status_code, 409)

    def test_unreviewed_changed_and_old_revision_do_not_save(self):
        record, payload = self.reviewable()
        before = ProductionTask.objects.count()
        for change in ({'result_revision': 2}, {'task_number': 'HT999999'}):
            response = self.client.post('/api/v1/production-tasks/', {**payload, **change}, format='json',
                HTTP_IF_MATCH=etag_for_instance(record))
            self.assertEqual(response.status_code, 409, response.data)
        record.review['confirmed_fields'] = []
        record.save()
        response = self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(ProductionTask.objects.count(), before)

    def test_failed_save_rolls_back_task_and_import_link(self):
        record, payload = self.reviewable()
        before = ProductionTask.objects.count()
        with patch('apps.production_task_imports.saving.audit', side_effect=RuntimeError('failure after creation')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(record))
        record.refresh_from_db()
        self.assertEqual((record.state, record.saved_at, record.saved_task_id), ('REVIEW', None, None))
        self.assertEqual(ProductionTask.objects.count(), before)

    def test_unsaved_expiry_removes_exact_source_but_saved_source_is_retained(self):
        record = self.checked()
        path = source_path(record)
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save()
        self.assertTrue(expire_once())
        self.assertFalse(path.exists())
        record.refresh_from_db()
        self.assertEqual(record.state, 'EXPIRED')
        saved, payload = self.reviewable()
        response = self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(saved))
        self.assertEqual(response.status_code, 201, response.data)
        saved.refresh_from_db()
        saved.expires_at = timezone.now() - timedelta(days=8)
        saved.save()
        self.assertFalse(expire_once())
        self.assertTrue(source_path(saved).exists())

    def test_selected_object_reuses_existing_record(self):
        first = self.checked()
        candidate = {'object_id': 'a' * 64, 'candidate_key': 'one'}
        first.state, first.candidates = 'NEEDS_SELECTION', [candidate]
        first.save()
        selected = self.client.post(f'{ROOT}{first.pk}/select/', {'object_id': candidate['object_id']},
            format='json', HTTP_IF_MATCH=etag_for_instance(first))
        self.assertEqual(selected.status_code, 200, selected.data)
        duplicate = self.client.post(ROOT, {'client_request_id': str(uuid4()),
            'file': SimpleUploadedFile('copy.xlsx', source_path(first).read_bytes())}, format='multipart')
        second = ProductionTaskImport.objects.get(pk=duplicate.data['data']['id'])
        second.state, second.candidates = 'NEEDS_SELECTION', [candidate]
        second.save()
        selected = self.client.post(f'{ROOT}{second.pk}/select/', {'object_id': candidate['object_id']},
            format='json', HTTP_IF_MATCH=etag_for_instance(second))
        self.assertEqual(str(selected.data['data']['id']), str(first.pk))

    def test_cancel_queued_parse_releases_shared_connection(self):
        from apps.codex_connection.models import CodexConnection, CodexOperation
        from ..worker import enqueue_next
        record = self.checked()
        connection = CodexConnection.objects.create(singleton=1, status='READY', paused=False,
            selected_model='visible-model', account={'display_name': 'a***@example.test', 'plan_type': 'pro'})
        self.assertTrue(enqueue_next())
        record.refresh_from_db()
        response = self.client.post(f'{ROOT}{record.pk}/cancel/', {}, format='json', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertEqual(response.status_code, 200, response.data)
        connection.refresh_from_db()
        self.assertEqual((connection.status, connection.paused), ('READY', False))
        self.assertEqual(CodexOperation.objects.get(pk=record.operation_id).state, 'CANCELED')

    def test_late_result_cannot_overwrite_canceled_or_retried_record(self):
        from django.db import transaction
        from apps.codex_connection.models import CodexConnection, CodexOperation
        record = self.checked()
        connection = CodexConnection.objects.create(singleton=1)
        operation = CodexOperation.objects.create(connection=connection, actor=self.employee, action='discover')
        record.operation, record.state = operation, 'CANCELED'
        record.save()
        with transaction.atomic():
            self.assertEqual(finish_import(operation, {'untrusted': 'ignored'}, ''), '')
        record.refresh_from_db()
        self.assertEqual((record.state, record.discovery), ('CANCELED', {}))

    def test_blocking_conflict_cannot_be_saved_as_todo(self):
        record, payload = self.reviewable()
        record.extraction['issues'] = [{'type': 'CONFLICT', 'message': '尺寸冲突', 'field_path': None, 'source_ids': []}]
        record.review['issues'] = {'issue_0': {'status': 'TODO', 'note': '以后处理'}}
        record.save()
        response = self.client.post('/api/v1/production-tasks/', payload, format='json', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertEqual(response.status_code, 400, response.data)

    def test_rediscovery_reuses_first_object_even_when_model_version_description_changes(self):
        from django.db import transaction
        from apps.codex_connection.models import CodexConnection, CodexOperation
        first = self.checked()
        connection = CodexConnection.objects.create(singleton=1)
        candidate = {'candidate_key': 'task', 'task_number_original': 'HT123', 'product_summary': '床',
            'version_description': '原版本', 'task_source_ids': [first.manifest['sheets'][0]['source_id']],
            'auxiliary_source_ids': [], 'grouping_uncertain': False, 'uncertainty_reason': None}
        discovered = {'schema_version': '1', 'candidates': [candidate], 'auxiliary_sections': [], 'issues': []}
        first.operation = CodexOperation.objects.create(connection=connection, actor=self.employee, action='discover')
        first.save()
        with transaction.atomic():
            self.assertEqual(finish_import(first.operation, discovered, ''), '')
        first.refresh_from_db()
        CodexOperation.objects.filter(pk=first.operation_id).update(state='SUCCEEDED')
        second = ProductionTaskImport.objects.create(owner=first.owner, client_request_id=uuid4(),
            original_name=first.original_name, sha256=first.sha256, size_bytes=first.size_bytes,
            expires_at=first.expires_at, state='PARSING', manifest=first.manifest, scan_status='CLEAN',
            operation=CodexOperation.objects.create(connection=connection, actor=self.employee, action='discover'))
        changed = deepcopy(discovered)
        changed['candidates'][0]['version_description'] = '未注明修订号的版本'
        with transaction.atomic():
            self.assertEqual(finish_import(second.operation, changed, ''), '')
        second.refresh_from_db()
        self.assertEqual(second.candidates, first.candidates)
        self.assertEqual(second.state, 'NEEDS_SELECTION')
        response = self.client.post(f'{ROOT}{second.pk}/select/', {'object_id': second.candidates[0]['object_id']},
            format='json', HTTP_IF_MATCH=etag_for_instance(second))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(str(response.data['data']['id']), str(first.pk))

    def test_file_saved_then_database_failure_cleans_journal_and_media(self):
        import json
        from PIL import Image
        from apps.files.models import FileScanStatus
        record, payload = self.reviewable()
        output = io.BytesIO()
        Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
        with patch('apps.files.uploads.scan_upload', return_value=(FileScanStatus.CLEAN, '')):
            with patch('apps.production_task_imports.saving.audit', side_effect=RuntimeError('after file creation')):
                with self.assertRaises(RuntimeError):
                    self.client.post('/api/v1/production-tasks/', {'payload': json.dumps(payload),
                        'product_image_product-1': SimpleUploadedFile('image.png', output.getvalue(), 'image/png')},
                        format='multipart', HTTP_IF_MATCH=etag_for_instance(record))
        self.assertFalse(list((Path(self.temp.name) / 'media').rglob('*.png')))
        self.assertFalse(list((Path(self.temp.name) / 'sources').rglob('pending-media.json')))

    def test_recovery_checks_hash_and_preserves_unknown_file(self):
        from hashlib import sha256
        from ..saving import CreatedMedia
        from ..worker import recover_media_once
        record = self.checked()
        file_id = uuid4()
        path = Path(self.temp.name) / 'media/production_tasks/recovery.png'
        path.parent.mkdir(parents=True)
        journal = CreatedMedia(record)
        journal.prepare(file_id, 'production_tasks/recovery.png', sha256(b'owned bytes').hexdigest())
        path.write_bytes(b'unknown bytes')
        with self.assertRaises(ImportFailure):
            recover_media_once()
        self.assertTrue(path.exists())
        path.write_bytes(b'owned bytes')
        recover_media_once()
        self.assertFalse(path.exists())
