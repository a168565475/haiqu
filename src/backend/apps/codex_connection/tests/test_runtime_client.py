import json
import struct
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings


@override_settings(CODEX_RUNTIME_SOCKET='/run/codex/connection.sock')
class RuntimeClientTests(SimpleTestCase):
    def test_old_runtime_has_no_implicit_nesting_capability(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_snapshot
        raw = {'boot_id': str(uuid4()), 'cli_version': '0.165.0', 'account': None,
               'models': [], 'rate_limits': None, 'limits_updated_at': None, 'operation': None}
        self.assertEqual(clean_snapshot(raw)['capabilities'], [])
        self.assertEqual(clean_snapshot({**raw, 'capabilities': ['nest']})['capabilities'], [])
        self.assertEqual(clean_snapshot({**raw, 'capabilities': ['nest_tools_v1']})['capabilities'], ['nest_tools_v1'])

    def test_capabilities_are_bounded_and_do_not_pass_unknown_text(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_snapshot, RuntimeFailure
        raw = {'boot_id': str(uuid4()), 'cli_version': '0.165.0', 'account': None,
               'models': [], 'rate_limits': None, 'limits_updated_at': None, 'operation': None}
        self.assertEqual(clean_snapshot({**raw, 'capabilities': ['nest_tools_v1', 'private-extra']})['capabilities'], ['nest_tools_v1'])
        for invalid in ('nest', [None], ['nest'] * 33):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeFailure):
                clean_snapshot({**raw, 'capabilities': invalid})

    def test_nest_operation_is_a_valid_public_action(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_operation
        value = clean_operation({'id': str(uuid4()), 'generation': 1, 'action': 'nest',
                                 'state': 'FAILED', 'error_code': 'UNSUPPORTED_CAPABILITY',
                                 'completed_at': '2026-11-05T01:00:00Z'})
        self.assertEqual(value['action'], 'nest')

    def test_response_schema_includes_nesting_and_fixed_failure_code(self):
        from uuid import uuid4
        from apps.codex_connection.runtime_client import clean_operation
        from apps.codex_connection.serializers import OperationSerializer
        self.assertTrue({'discover', 'extract', 'nest'} <= set(OperationSerializer().fields['action'].choices))
        value = clean_operation({'id': str(uuid4()), 'generation': 1, 'action': 'nest',
                                 'state': 'FAILED', 'error_code': 'CODEX_INVALID_PROPOSAL',
                                 'completed_at': '2026-11-05T01:00:00Z'})
        self.assertEqual(value['error_code'], 'CODEX_INVALID_PROPOSAL')

    def exchange(self, response):
        sock = MagicMock()
        raw = json.dumps(response).encode()
        sock.recv.side_effect = [struct.pack('!I', len(raw)), raw]
        sock.__enter__.return_value = sock
        return sock

    def test_artifact_transfer_verifies_identity_bytes_and_manifest(self):
        import base64
        import hashlib
        from uuid import uuid4
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        content = b'x' * 300000
        params = {'operation_id': str(uuid4()), 'generation': 1, 'boot_id': str(uuid4()), 'name': 'layout.svg'}
        raw = {**params, 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
               'data_base64': base64.b64encode(content).decode()}
        manifest = {'name': 'layout.svg', 'size_bytes': len(content), 'sha256': raw['sha256'], 'content_type': 'image/svg+xml'}
        with patch('socket.socket', return_value=self.exchange({'ok': True, 'data': raw})):
            self.assertEqual(RuntimeClient().fetch_artifact(params, manifest), content)
        for change in ({'sha256': 'a' * 64}, {'size_bytes': True}, {'size_bytes': 8 * 1024 * 1024 + 1},
                       {'data_base64': '!'}, {'boot_id': str(uuid4())}, {'generation': 2}, {'name': '../source.dxf'}):
            with self.subTest(change=change), patch('socket.socket', return_value=self.exchange({'ok': True, 'data': {**raw, **change}})):
                with self.assertRaises(RuntimeFailure):
                    RuntimeClient().fetch_artifact(params, manifest)
        with patch('socket.socket', return_value=self.exchange({'ok': True, 'data': raw})):
            with self.assertRaises(RuntimeFailure):
                RuntimeClient().fetch_artifact(params, {**manifest, 'sha256': 'b' * 64})
        for change in ({'name': []}, {'size_bytes': True}, {'size_bytes': 0}):
            with self.subTest(manifest=change), patch('socket.socket') as socket_mock:
                with self.assertRaises(RuntimeFailure):
                    RuntimeClient().fetch_artifact(params, {**manifest, **change})
                socket_mock.assert_not_called()

    def test_only_nest_upload_and_artifact_have_long_transfer_deadline(self):
        from apps.codex_connection.runtime_client import RuntimeClient, RuntimeFailure
        for method, params, budget in (
            ('artifact', {}, 30), ('start', {'action': 'nest'}, 30),
            ('start', {'action': 'extract'}, 5), ('start', {}, 5), ('result', {}, 5), ('status', {}, 5),
        ):
            sock = self.exchange({'ok': False, 'error': {'code': 'NOT_READY'}})
            with self.subTest(method=method, params=params), patch('socket.socket', return_value=sock), \
                    patch('apps.codex_connection.runtime_client.time.monotonic', return_value=100):
                with self.assertRaises(RuntimeFailure):
                    RuntimeClient().call(method, params)
            self.assertEqual([call.args[0] for call in sock.settimeout.call_args_list], [budget] * 4)

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
