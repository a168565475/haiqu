"""队列/连接边界的隔离数据库测试，不冒充真实模型验收。"""
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.codex_connection.models import CodexConnection, CodexOperation
from apps.codex_connection.runtime_client import RuntimeFailure
from apps.codex_connection.worker import apply_result, process_tick, reserve_artifact_transfer, claim_tick
from apps.organizations.models import Employee


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class NestingWorkerTests(TransactionTestCase):
    def setUp(self):
        user = get_user_model().objects.create_user('nest_worker', password='TestPassword123!')
        self.employee = Employee.objects.create(user=user, employee_code='NEST_WORKER', display_name='排料测试员工')
        self.connection = CodexConnection.objects.create(singleton=1, status='READY', paused=False,
            account={'display_name': 'masked', 'plan_type': 'pro'}, selected_model='actual-model', cli_version='0.165.0')

    def operation(self, state='QUEUED'):
        return CodexOperation.objects.create(connection=self.connection, actor=self.employee, action='nest',
            model='actual-model', state=state, generation=self.connection.config_generation,
            attempt_no=1 if state == 'RUNNING' else 0, lease_id=uuid4() if state == 'RUNNING' else None,
            lease_expires_at=timezone.now() - timedelta(seconds=1) if state == 'RUNNING' else None,
            runtime_boot_id=uuid4() if state == 'RUNNING' else None)

    def snapshot(self, operation=None, *, capabilities=('nest_tools_v1',), boot_id=None):
        return {'boot_id': boot_id or str(uuid4()), 'cli_version': '0.165.0',
            'account': {'display_name': 'masked', 'plan_type': 'pro'},
            'models': [{'id': 'actual-model', 'display_name': 'Actual model'}],
            'rate_limits': None, 'limits_updated_at': None, 'operation': operation,
            'capabilities': list(capabilities)}

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    @patch('apps.boms.nesting_codex.runtime_payload', return_value={'bounded': 'data'})
    @patch('apps.boms.nesting_codex.operation_allowed', return_value=True)
    def test_old_runtime_is_not_called_with_start_and_does_not_break_ready(self, allowed, payload, finish):
        operation = self.operation()
        runtime = Mock()
        runtime.call.return_value = self.snapshot(capabilities=())
        self.assertTrue(process_tick(runtime, owner_id=uuid4()))
        operation.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual([call.args[0] for call in runtime.call.call_args_list], ['status'])
        self.assertEqual((operation.state, operation.error_code), ('FAILED', 'UNSUPPORTED_CAPABILITY'))
        self.assertEqual((self.connection.status, self.connection.paused), ('READY', False))
        self.assertEqual(finish.call_args.args[2], 'UNSUPPORTED_CAPABILITY')

    @patch('apps.boms.nesting_codex.runtime_payload', return_value={'bounded': 'data'})
    @patch('apps.boms.nesting_codex.operation_allowed', return_value=True)
    def test_nesting_uses_existing_selected_model_and_operation(self, allowed, payload):
        operation = self.operation()
        boot_id = str(uuid4())
        running = {'id': str(operation.id), 'generation': operation.generation, 'action': 'nest',
                   'state': 'RUNNING', 'error_code': '', 'completed_at': None}
        runtime = Mock()
        runtime.call.side_effect = [self.snapshot(boot_id=boot_id), self.snapshot(running, boot_id=boot_id)]
        self.assertTrue(process_tick(runtime, owner_id=uuid4()))
        start = runtime.call.call_args_list[-1]
        self.assertEqual(start.args[0], 'start')
        self.assertEqual(start.args[1]['action'], 'nest')
        self.assertEqual(start.args[1]['model'], 'actual-model')
        self.assertEqual(start.args[1]['payload'], {'bounded': 'data'})
        operation.refresh_from_db()
        self.assertEqual(str(operation.runtime_boot_id), boot_id)

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    def test_terminal_and_stale_results_use_business_callback(self, finish):
        operation = self.operation('RUNNING')
        result = {'id': str(operation.id), 'generation': operation.generation, 'action': 'nest',
                  'state': 'SUCCEEDED', 'error_code': '', 'completed_at': timezone.now().isoformat()}
        snapshot = self.snapshot(result, boot_id=str(operation.runtime_boot_id))
        self.assertFalse(apply_result(operation.id, 2, operation.lease_id, snapshot, {'suggestions': []}))
        finish.assert_not_called()
        self.assertTrue(apply_result(operation.id, 1, operation.lease_id, snapshot, {'suggestions': []}))
        self.assertEqual(finish.call_args.args[1:], ({'suggestions': []}, ''))
        self.connection.refresh_from_db()
        self.assertEqual((self.connection.status, self.connection.paused), ('READY', False))

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    @patch('apps.boms.nesting_codex.operation_allowed', return_value=False)
    def test_revoked_before_dispatch_finishes_without_external_request(self, allowed, finish):
        operation = self.operation()
        runtime = Mock()
        self.assertFalse(process_tick(runtime, owner_id=uuid4()))
        runtime.call.assert_not_called()
        operation.refresh_from_db()
        self.assertEqual((operation.state, operation.error_code), ('FAILED', 'PERMISSION_REVOKED'))
        self.assertEqual(finish.call_args.args[2], 'PERMISSION_REVOKED')
        self.connection.refresh_from_db()
        self.assertEqual((self.connection.status, self.connection.paused), ('READY', False))

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    def test_runtime_restart_finishes_nesting_as_interrupted_without_replay(self, finish):
        operation = self.operation('RUNNING')
        runtime = Mock()
        snapshot = self.snapshot()
        runtime.call.return_value = {'boot_id': snapshot['boot_id'], 'operation': None, 'snapshot': snapshot}
        self.assertTrue(process_tick(runtime, owner_id=uuid4()))
        self.assertEqual([call.args[0] for call in runtime.call.call_args_list], ['operation'])
        self.assertEqual(finish.call_args.args[2], 'INTERRUPTED')
        operation.refresh_from_db()
        self.assertEqual(operation.state, 'INTERRUPTED')

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    @patch('apps.boms.nesting_codex.runtime_payload', return_value={'bounded': 'data'})
    @patch('apps.boms.nesting_codex.operation_allowed', return_value=True)
    def test_uncertain_start_is_never_replayed_and_eventually_finishes_business_job(self, allowed, payload, finish):
        operation = self.operation()
        owner = uuid4()
        snapshot = self.snapshot()
        runtime = Mock()
        runtime.call.side_effect = [snapshot, RuntimeFailure('UPSTREAM_UNAVAILABLE')]
        self.assertTrue(process_tick(runtime, owner_id=owner))
        finish.assert_not_called()
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'UNKNOWN')
        runtime.call.side_effect = None
        runtime.call.return_value = {'boot_id': snapshot['boot_id'], 'operation': None, 'snapshot': snapshot}
        self.assertTrue(process_tick(runtime, owner_id=owner))
        self.assertEqual([call.args[0] for call in runtime.call.call_args_list], ['status', 'start', 'operation'])
        self.assertEqual(finish.call_args.args[2], 'INTERRUPTED')

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    def test_canceling_before_start_releases_operation_without_request(self, finish):
        operation = self.operation('RUNNING')
        operation.state, operation.runtime_boot_id = 'CANCELING', None
        operation.save(update_fields=['state', 'runtime_boot_id', 'updated_at'])
        runtime = Mock()
        self.assertTrue(process_tick(runtime, owner_id=operation.lease_id))
        runtime.call.assert_not_called()
        finish.assert_called_once()
        operation.refresh_from_db()
        self.assertEqual(operation.state, 'CANCELED')

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    def test_failed_model_result_finishes_job_without_returning_payload(self, finish):
        operation = self.operation('RUNNING')
        result = {'id': str(operation.id), 'generation': operation.generation, 'action': 'nest',
                  'state': 'FAILED', 'error_code': 'CODEX_INVALID_PROPOSAL', 'completed_at': timezone.now().isoformat()}
        snapshot = self.snapshot(result, boot_id=str(operation.runtime_boot_id))
        self.assertTrue(apply_result(operation.id, 1, operation.lease_id, snapshot, {'untrusted': 'ignored'}))
        self.assertEqual(finish.call_args.args[1:], (None, 'CODEX_INVALID_PROPOSAL'))
        operation.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual((operation.state, operation.error_code), ('FAILED', 'CODEX_INVALID_PROPOSAL'))
        self.assertEqual((self.connection.status, self.connection.paused, self.connection.error_code), ('READY', False, ''))

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    @patch('apps.boms.nesting_codex.operation_allowed', return_value=True)
    def test_source_changed_before_upload_fails_only_nesting_job(self, allowed, finish):
        from apps.boms.nesting_storage import NestingFailure
        operation = self.operation()
        runtime = Mock()
        with patch('apps.boms.nesting_codex.runtime_payload', side_effect=NestingFailure('SOURCE_CHANGED')):
            self.assertTrue(process_tick(runtime, owner_id=uuid4()))
        runtime.call.assert_not_called()
        operation.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual((operation.state, operation.error_code), ('FAILED', 'SOURCE_CHANGED'))
        self.assertEqual((self.connection.status, self.connection.paused), ('READY', False))

    def test_artifact_transfer_reserves_enough_lease_and_blocks_other_worker(self):
        operation = self.operation('RUNNING')
        self.assertTrue(reserve_artifact_transfer(operation))
        operation.refresh_from_db()
        self.assertGreater((operation.lease_expires_at-timezone.now()).total_seconds(), 80)
        self.assertIsNone(claim_tick(uuid4()))
        previous_expiry = operation.lease_expires_at
        operation.attempt_no += 1
        self.assertFalse(reserve_artifact_transfer(operation))
        operation.refresh_from_db()
        self.assertEqual(operation.lease_expires_at, previous_expiry)

    @patch('apps.boms.nesting_codex.finish_codex_operation', return_value='')
    def test_auth_failure_still_marks_shared_connection_unavailable(self, finish):
        operation = self.operation('RUNNING')
        result = {'id': str(operation.id), 'generation': operation.generation, 'action': 'nest',
                  'state': 'FAILED', 'error_code': 'AUTH_REQUIRED', 'completed_at': timezone.now().isoformat()}
        snapshot = self.snapshot(result, boot_id=str(operation.runtime_boot_id))
        self.assertTrue(apply_result(operation.id, 1, operation.lease_id, snapshot))
        self.assertEqual(finish.call_args.args[1:], (None, 'AUTH_REQUIRED'))
        operation.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual((operation.state, operation.error_code), ('FAILED', 'AUTH_REQUIRED'))
        self.assertEqual((self.connection.status, self.connection.paused, self.connection.error_code), ('ERROR', True, 'AUTH_REQUIRED'))
