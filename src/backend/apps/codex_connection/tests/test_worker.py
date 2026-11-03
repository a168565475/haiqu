from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.organizations.models import Employee


ROOT = '/api/v1/codex-connection/'


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class CodexWorkerTests(TransactionTestCase):
    def setUp(self):
        from apps.codex_connection.models import CodexConnection
        user = get_user_model().objects.create_superuser('codex_worker', '', 'TestPassword123!')
        self.employee = Employee.objects.create(user=user, employee_code='CODEX_WORKER', display_name='测试管理员')
        self.client = APIClient()
        self.client.force_login(user)
        self.connection = CodexConnection.objects.create(singleton=1)

    def queue(self, action):
        response = self.client.get(ROOT)
        return self.client.post(ROOT + action + '/', {}, format='json', HTTP_IF_MATCH=response['ETag'])

    def runtime_snapshot(self, operation=None, boot_id=None):
        return {'boot_id': boot_id or str(uuid4()), 'cli_version': '0.165.0',
                'account': {'display_name': 'c***@example.test', 'plan_type': 'pro'},
                'models': [{'id': 'actual-model', 'display_name': 'Actual model'}],
                'rate_limits': None, 'limits_updated_at': None, 'operation': operation}

    def running(self, action='test'):
        from apps.codex_connection.models import CodexOperation
        return CodexOperation.objects.create(connection=self.connection, actor=self.employee,
            action=action, state='RUNNING', generation=self.connection.config_generation,
            attempt_no=1, lease_id=uuid4(), lease_expires_at=timezone.now() + timedelta(seconds=30),
            runtime_boot_id=uuid4())

    def test_disconnect_drains_running_test_and_blocks_new_test(self):
        self.running()
        self.assertEqual(self.queue('disconnect').status_code, 202)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'DRAINING')
        self.assertTrue(self.connection.paused)
        self.assertEqual(self.queue('test').status_code, 409)

    def test_stale_attempt_or_generation_cannot_apply_runtime_result(self):
        from apps.codex_connection.worker import apply_result
        operation = self.running()
        result = self.runtime_snapshot({'id': str(operation.id), 'generation': operation.generation,
            'action': 'test', 'state': 'SUCCEEDED', 'error_code': '', 'completed_at': timezone.now().isoformat()},
            str(operation.runtime_boot_id))
        self.assertFalse(apply_result(operation.id, operation.attempt_no + 1, operation.lease_id, result))
        self.connection.config_generation += 1
        self.connection.save()
        self.assertFalse(apply_result(operation.id, operation.attempt_no, operation.lease_id, result))
        operation.refresh_from_db()
        self.assertEqual(operation.state, 'RUNNING')

    def test_runtime_restart_marks_interrupted_without_replay(self):
        from unittest.mock import Mock
        from apps.codex_connection.worker import process_tick
        operation = self.running('login')
        operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
        operation.save()
        runtime = Mock()
        snapshot = self.runtime_snapshot()
        runtime.call.return_value = {'boot_id': snapshot['boot_id'], 'operation': None, 'snapshot': snapshot}
        process_tick(runtime, owner_id=uuid4())
        operation.refresh_from_db()
        self.connection.refresh_from_db()
        self.assertEqual(operation.state, 'INTERRUPTED')
        self.assertEqual(self.connection.status, 'UNKNOWN')
        self.assertTrue(self.connection.paused)
        self.assertEqual([call.args[0] for call in runtime.call.call_args_list], ['operation'])

    def test_terminal_result_clears_public_operation_and_sets_ready_only_for_test(self):
        from apps.codex_connection.worker import apply_result
        operation = self.running()
        snapshot = self.runtime_snapshot({'id': str(operation.id), 'generation': operation.generation,
            'action': 'test', 'state': 'SUCCEEDED', 'error_code': '', 'completed_at': timezone.now().isoformat()},
            str(operation.runtime_boot_id))
        self.assertTrue(apply_result(operation.id, operation.attempt_no, operation.lease_id, snapshot))
        payload = self.client.get(ROOT).data['data']
        self.assertEqual(payload['status'], 'READY')
        self.assertIsNone(payload['operation'])

    def test_lease_prevents_other_worker_polling_current_operation(self):
        from unittest.mock import Mock
        from apps.codex_connection.worker import process_tick
        self.running()
        runtime = Mock()
        self.assertFalse(process_tick(runtime, owner_id=uuid4()))
        runtime.call.assert_not_called()

    def test_cancellation_is_polled_and_does_not_claim_disconnected(self):
        from apps.codex_connection.worker import apply_result
        operation = self.running('login')
        operation.state = 'CANCELING'
        operation.save()
        snapshot = self.runtime_snapshot({'id': str(operation.id), 'generation': operation.generation,
            'action': 'login', 'state': 'CANCELED', 'error_code': '', 'completed_at': timezone.now().isoformat()},
            str(operation.runtime_boot_id))
        self.assertTrue(apply_result(operation.id, operation.attempt_no, operation.lease_id, snapshot))
        payload = self.client.get(ROOT).data['data']
        self.assertEqual(payload['status'], 'CONNECTED')
        self.assertIsNone(payload['operation'])

    def test_recovered_login_restores_challenge_visible_status(self):
        from apps.codex_connection.worker import apply_result
        operation = self.running('login')
        self.connection.status = 'UNKNOWN'
        self.connection.error_code = 'UPSTREAM_UNAVAILABLE'
        self.connection.save()
        snapshot = self.runtime_snapshot({'id': str(operation.id), 'generation': operation.generation,
            'action': 'login', 'state': 'RUNNING', 'error_code': '', 'completed_at': None},
            str(operation.runtime_boot_id))
        self.assertTrue(apply_result(operation.id, operation.attempt_no, operation.lease_id, snapshot))
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'LOGIN_PENDING')
        self.assertEqual(self.connection.error_code, '')
        first_etag = self.client.get(ROOT)['ETag']
        apply_result(operation.id, operation.attempt_no, operation.lease_id, snapshot)
        self.assertEqual(self.client.get(ROOT)['ETag'], first_etag)

    def test_cancel_queued_switch_does_not_interrupt_running_test(self):
        operation = self.running()
        response = self.queue('switch')
        self.assertEqual(response.status_code, 202)
        queued = self.connection.operations.get(state='QUEUED')
        response = self.client.post(ROOT + 'login-cancel/', {'operation_id': str(queued.id)}, format='json',
                                    HTTP_IF_MATCH=self.client.get(ROOT)['ETag'])
        self.assertEqual(response.status_code, 202)
        operation.refresh_from_db()
        queued.refresh_from_db()
        self.assertEqual(operation.state, 'RUNNING')
        self.assertEqual(queued.state, 'CANCELED')
