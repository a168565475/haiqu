import json
import struct
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings


@override_settings(CODEX_RUNTIME_SOCKET='/run/codex/connection.sock')
class RuntimeClientTests(SimpleTestCase):
    def exchange(self, response):
        sock = MagicMock()
        raw = json.dumps(response).encode()
        sock.recv.side_effect = [struct.pack('!I', len(raw)), raw]
        sock.__enter__.return_value = sock
        return sock

    def test_unknown_upstream_error_is_fixed_and_does_not_echo_payload(self):
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        sock = self.exchange({'ok': False, 'error': {'code': 'SECRET_TOKEN_123', 'detail': 'secret'}})
        with patch('socket.socket', return_value=sock):
            with self.assertRaises(RuntimeFailure) as result:
                RuntimeClient().call('status', {})
        self.assertEqual(result.exception.code, 'INVALID_RESPONSE')
        self.assertNotIn('SECRET', str(result.exception))

    def test_usage_limit_error_is_preserved_without_upstream_details(self):
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        sock = self.exchange({'ok': False, 'error': {'code': 'USAGE_LIMIT_EXCEEDED', 'detail': 'SECRET_TOKEN_123'}})
        with patch('socket.socket', return_value=sock):
            with self.assertRaises(RuntimeFailure) as result:
                RuntimeClient().call('status', {})
        self.assertEqual(result.exception.code, 'USAGE_LIMIT_EXCEEDED')
        self.assertNotIn('SECRET', str(result.exception))

    def test_usage_limit_operation_keeps_failed_state(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_operation
        result = clean_operation({'id': str(uuid4()), 'generation': 1, 'action': 'test', 'state': 'FAILED',
                                  'error_code': 'USAGE_LIMIT_EXCEEDED', 'completed_at': '2026-11-03T01:00:00Z'})
        self.assertEqual((result['state'], result['error_code']), ('FAILED', 'USAGE_LIMIT_EXCEEDED'))

    def test_unknown_operation_error_remains_rejected(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_operation, RuntimeFailure
        with self.assertRaises(RuntimeFailure) as result:
            clean_operation({'id': str(uuid4()), 'generation': 1, 'action': 'test', 'state': 'FAILED',
                             'error_code': 'SECRET_TOKEN_123', 'completed_at': '2026-11-03T01:00:00Z'})
        self.assertEqual(result.exception.code, 'INVALID_RESPONSE')
        self.assertNotIn('SECRET', str(result.exception))

    def test_oversized_response_is_rejected_before_body_read(self):
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        sock = self.exchange({})
        sock.recv.side_effect = [struct.pack('!I', 256 * 1024 + 1)]
        with patch('socket.socket', return_value=sock):
            with self.assertRaises(RuntimeFailure) as result:
                RuntimeClient().call('status', {})
        self.assertEqual(result.exception.code, 'INVALID_RESPONSE')

    def test_invalid_snapshot_does_not_pass_through_extra_credentials(self):
        from apps.codex_connection.runtime_client import clean_snapshot, RuntimeFailure
        with self.assertRaises(RuntimeFailure):
            clean_snapshot({'boot_id': 'invalid', 'auth': 'SECRET_TOKEN_123'})

    def test_socket_error_never_includes_raw_exception(self):
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        with patch('socket.socket', side_effect=OSError('SECRET_TOKEN_123')):
            with self.assertRaises(RuntimeFailure) as result:
                RuntimeClient().call('status', {})
        self.assertEqual(result.exception.code, 'UPSTREAM_UNAVAILABLE')
        self.assertNotIn('SECRET', str(result.exception))

    def test_authorization_url_rejects_explicit_default_port(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_challenge, RuntimeFailure
        with self.assertRaises(RuntimeFailure):
            clean_challenge({'operation_id': str(uuid4()), 'verification_url': 'https://auth.openai.com:443/codex/device',
                             'user_code': 'ABCD-EFGH', 'expires_at': '2099-01-01T00:00:00Z'})
