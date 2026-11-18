"""独占数据库的 ERP 网关测试；模拟执行端回复不代表真实模型验收。"""
import base64
from copy import deepcopy
import hashlib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.nesting_codex import enqueue_next, finish_codex_operation, runtime_payload
from apps.boms.nesting_models import BomNestingJob
from apps.boms.nesting_storage import source_path
from apps.boms.nesting_executor_contract import canonical_digest
from apps.codex_connection.models import CodexConnection, CodexOperation
from apps.core.api.concurrency import etag_for_instance
from . import test_nesting_api as api_tests
from . import test_nesting_executor_inputs as contract_tests


@override_settings(FILE_VIRUS_SCAN_ENABLED=False, SALES_ACCESS_ENABLED=False,
                   MODULE_ACCESS_ENABLED=False, CONFIRMED_ROLE_POLICY_ENABLED=False)
class ExecutorGatewayTests(APITestCase):
    setUp = api_tests.NestingApiTests.setUp
    upload = api_tests.NestingApiTests.upload

    def ready(self):
        return CodexConnection.objects.create(singleton=1, status='READY', paused=False,
            selected_model='configured-model', account={'display_name': 'test', 'plan_type': 'pro'})

    def queued_source(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        return BomNestingJob.objects.get(pk=response.data['data']['id'])

    def response_data(self, job, *, extract=False):
        fixture = contract_tests.ExecutorEnvelopeTests()
        fixture.setUp()
        data = deepcopy(fixture.data)
        data['source_sha256'] = job.sha256
        data['execution']['model'] = job.operation.model
        if extract:
            data.update(phase='extract', parameters_digest='', result=None, artifacts=[])
            data['execution']['tool_calls'] = [data['execution']['tool_calls'][0], data['execution']['tool_calls'][-1]]
            data['execution']['guided_attempts'] = 0
            contents = {}
        else:
            data['analysis_digest'] = job.analysis_digest
            data['parameters_digest'] = canonical_digest(job.parameters)
            contents = {'layout.svg': b'<svg xmlns="http://www.w3.org/2000/svg"/>', 'layout.dxf': b'0\nEOF\n'}
            for entry in data['artifacts']:
                entry['size_bytes'] = len(contents[entry['name']])
                entry['sha256'] = hashlib.sha256(contents[entry['name']]).hexdigest()
        return {**data, '_artifact_bytes': contents}

    def extracted(self):
        connection = self.ready()
        job = self.queued_source()
        self.assertTrue(enqueue_next())
        job.refresh_from_db()
        finish_codex_operation(job.operation, self.response_data(job, extract=True), '')
        job.refresh_from_db()
        self.assertEqual(job.status, 'NEEDS_PARAMETERS')
        # 模拟队列公共层已记录终态；此类只覆盖 BOM 领域回调。
        CodexOperation.objects.filter(pk=job.operation_id).update(state='SUCCEEDED')
        connection.paused = False
        connection.save(update_fields=['paused'])
        return job

    def running_layout(self):
        job = self.extracted()
        fixture = contract_tests.ExecutorEnvelopeTests()
        fixture.setUp()
        response = self.client.post(f'{self.url}{job.pk}/calculate/', fixture.parameters,
                                    format='json', HTTP_IF_MATCH=etag_for_instance(job))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(enqueue_next())
        job.refresh_from_db()
        return job

    def test_upload_queues_actual_file_to_executor_without_erp_geometry(self):
        self.ready()
        job = self.queued_source()
        self.assertTrue(enqueue_next())
        job.refresh_from_db()
        payload = runtime_payload(job.operation)
        self.assertEqual((payload['schema_version'], payload['phase']), (2, 'extract'))
        self.assertEqual(base64.b64decode(payload['source']['data_base64']), source_path(job).read_bytes())
        self.assertNotIn('analysis', payload)
        self.assertNotIn('target_snapshot', payload)
        self.assertEqual(job.analysis, {})

    def test_unavailable_executor_fails_without_local_fallback(self):
        job = self.queued_source()
        self.assertTrue(enqueue_next())
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'NOT_READY'))
        self.assertEqual((job.analysis, job.result, job.artifacts), ({}, {}, []))
        self.assertEqual(CodexOperation.objects.count(), 0)

    def test_nest_submits_original_source_parameters_and_analysis_digest(self):
        job = self.running_layout()
        payload = runtime_payload(job.operation)
        self.assertEqual(payload['phase'], 'nest')
        self.assertEqual(payload['parameters'], job.parameters)
        self.assertEqual(payload['analysis_digest'], job.analysis_digest)
        self.assertNotIn('analysis', payload)
        self.assertNotIn('baseline', payload)
        self.assertEqual(job.execution, {})

    def test_completed_artifacts_are_served_unchanged_and_bom_is_not_written(self):
        job = self.running_layout()
        data = self.response_data(job)
        self.assertEqual(finish_codex_operation(job.operation, data, ''), '')
        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCEEDED')
        self.assertEqual(job.result['consumption_rounded_m'], data['result']['consumption_rounded_m'])
        for endpoint, name in [('preview', 'layout.svg'), ('dxf', 'layout.dxf')]:
            response = self.client.get(f'{self.url}{job.pk}/{endpoint}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), data['_artifact_bytes'][name])
            self.assertTrue(response.closed)  # Django 测试客户端耗尽迭代器后自动关闭。
        self.line.refresh_from_db()
        self.assertEqual(Decimal(self.line.unit_consumption), Decimal('2'))

    def test_corrupted_artifact_or_source_never_becomes_adoptable(self):
        job = self.running_layout()
        data = self.response_data(job)
        data['_artifact_bytes']['layout.svg'] += b'corrupted'
        finish_codex_operation(job.operation, data, '')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'ARTIFACT_INVALID'))
        self.assertEqual(job.result, {})
        self.assertFalse((source_path(job).parent / 'layout.svg').exists())

    def test_download_stream_remains_bound_to_verified_file_when_replaced(self):
        job = self.running_layout()
        data = self.response_data(job)
        finish_codex_operation(job.operation, data, '')
        job.refresh_from_db()
        response = self.client.get(f'{self.url}{job.pk}/preview/')
        self.assertEqual(response.status_code, 200)
        replacement = source_path(job).parent / 'test-replacement.svg'
        replacement.write_bytes(b'unverified replacement')
        replacement.replace(replacement.parent / 'layout.svg')
        self.assertEqual(b''.join(response.streaming_content), data['_artifact_bytes']['layout.svg'])
        self.assertTrue(response.closed)
        self.assertEqual(self.client.get(f'{self.url}{job.pk}/preview/').status_code, 422)

    def test_changed_source_rejects_even_successful_executor_result(self):
        job = self.running_layout()
        data = self.response_data(job)
        source_path(job).write_bytes(b'changed')
        finish_codex_operation(job.operation, data, '')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'SOURCE_CHANGED'))
        self.assertEqual(job.result, {})

    def test_storage_failure_is_reported_without_stopping_shared_worker(self):
        job = self.running_layout()
        data = self.response_data(job)
        with patch('apps.boms.nesting_storage.os.replace', side_effect=PermissionError('read-only')):
            with self.assertLogs('apps.boms.nesting_storage', level='ERROR'):
                code = finish_codex_operation(job.operation, data, '')
        self.assertEqual(code, 'STORAGE_UNAVAILABLE')
        job.refresh_from_db()
        self.assertEqual((job.status, job.result), ('FAILED', {}))
        self.assertEqual(list(source_path(job).parent.glob('.artifact-*.tmp')), [])

    def test_cancel_does_not_accept_late_files(self):
        job = self.running_layout()
        data = self.response_data(job)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'{self.url}{job.pk}/cancel/', {}, HTTP_IF_MATCH=etag_for_instance(job))
        self.assertEqual(response.status_code, 200)
        finish_codex_operation(job.operation, data, '')
        job.refresh_from_db()
        self.assertEqual((job.status, job.result), ('CANCELED', {}))
        self.assertFalse((source_path(job).parent / 'layout.svg').exists())

    def test_permission_revocation_rejects_result(self):
        job = self.running_layout()
        data = self.response_data(job)
        self.user.user_permissions.clear()
        finish_codex_operation(job.operation, data, '')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'PERMISSION_REVOKED'))
        self.assertEqual(job.result, {})

    def test_executor_timeout_has_no_successful_local_plan(self):
        job = self.running_layout()
        BomNestingJob.objects.filter(pk=job.pk).update(started_at=timezone.now()-timedelta(seconds=1201))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(enqueue_next())
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('FAILED', 'TIMEOUT'))
        self.assertEqual(job.result, {})

    def test_old_local_result_is_read_only(self):
        job = self.queued_source()
        job.status, job.phase, job.result = 'SUCCEEDED', 'REFINE', {'consumption_m': '.1'}
        job.save()
        self.assertEqual(self.client.get(f'{self.url}{job.pk}/preview/').status_code, 409)
