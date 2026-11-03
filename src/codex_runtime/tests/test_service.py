"""仅模拟官方协议边界；不代表真实账号或模型验收。"""
import asyncio
import copy
import contextlib
import io
import json
import unittest
import uuid
from datetime import datetime, timezone

from codex_runtime.service import Runtime, RuntimeErrorCode, account_summary, normalize_limits


class FakeSession:
    def __init__(self, factory):
        self.factory = factory
        self.events = asyncio.Queue()
        self.login_id = str(uuid.uuid4())
        self.closed = False
        self.calls = []

    async def start(self):
        if self.factory.start_gate:
            await self.factory.start_gate.wait()

    async def request(self, method, params, timeout=20):
        self.calls.append((method, copy.deepcopy(params)))
        if self.factory.fail == method:
            raise RuntimeError('secret-upstream-error-token')
        if method == 'account/read':
            return {'account': copy.deepcopy(self.factory.account), 'requiresOpenaiAuth': True}
        if method == 'account/login/start':
            return {'type': 'chatgptDeviceCode', 'loginId': self.login_id,
                    'verificationUrl': self.factory.url, 'userCode': 'ABCD-EFGH'}
        if method == 'account/login/cancel':
            return {'status': self.factory.cancel_status}
        if method == 'account/logout':
            self.factory.account = None
            return {}
        if method == 'model/list':
            return {'data': [{'model': 'visible-model', 'displayName': 'Visible', 'hidden': False}], 'nextCursor': None}
        if method == 'account/rateLimits/read':
            return {'rateLimits': {'primary': {'usedPercent': 12, 'windowDurationMins': 300, 'resetsAt': 1900000000},
                                  'credits': {'unlimited': False, 'hasCredits': True, 'balance': '2.5'}}}
        if method == 'thread/start':
            return {'thread': {'id': 'thread-1', 'ephemeral': True, 'environments': []},
                    'approvalPolicy': 'never', 'model': params['model']}
        if method == 'mcpServerStatus/list':
            return {'data': [], 'nextCursor': None}
        if method == 'turn/start':
            if self.factory.turn_events is not None:
                for event in self.factory.turn_events:
                    self.events.put_nowait(copy.deepcopy(event))
                return {'turn': {'id': 'turn-1'}}
            self.events.put_nowait({'method': 'item/completed', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
                                    'item': {'type': 'agentMessage', 'text': '{"ok":true}'}}})
            self.events.put_nowait({'method': 'turn/completed', 'params': {'threadId': 'thread-1',
                                    'turn': {'id': 'turn-1', 'status': 'completed'}}})
            return {'turn': {'id': 'turn-1'}}
        if method == 'turn/interrupt':
            return {}
        raise AssertionError('unexpected method')

    async def notification(self, timeout=20):
        return await asyncio.wait_for(self.events.get(), timeout)

    def take_queued_notifications(self):
        return [self.events.get_nowait() for _ in range(self.events.qsize())]

    async def close(self):
        if self.factory.close_error:
            self.factory.close_error = False
            raise RuntimeErrorCode('INTERRUPTED')
        self.closed = True
        if self.factory.close_gate:
            await self.factory.close_gate.wait()
        if self.factory.complete_on_close:
            self.factory.account = dict(type='chatgpt', email='private-person@example.test', planType='pro')
            self.factory.complete_on_close = False


class Factory:
    def __init__(self):
        self.sessions = []
        self.account = None
        self.start_gate = self.close_gate = None
        self.fail = None
        self.url = 'https://auth.openai.com/codex/device'
        self.cancel_status = 'canceled'
        self.complete_on_close = False
        self.turn_events = None
        self.close_error = False

    def __call__(self):
        session = FakeSession(self)
        self.sessions.append(session)
        return session


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def model_events(self, text, commentary=False):
        events = []
        if commentary:
            events.append({'method': 'item/completed', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
                'item': {'type': 'agentMessage', 'phase': 'commentary', 'text': 'Preparing the requested result.'}}})
        events.extend([
            {'method': 'item/completed', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
                'item': {'type': 'agentMessage', 'phase': 'final_answer', 'text': text}}},
            {'method': 'turn/completed', 'params': {'threadId': 'thread-1',
                'turn': {'id': 'turn-1', 'status': 'completed'}}},
        ])
        return events

    async def test_model_commentary_is_not_parsed_as_final_json(self):
        self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
        self.factory.turn_events = self.model_events('{"ok":true}', commentary=True)
        await self.runtime.dispatch('start', self.params('test'))
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')

    async def test_invalid_final_json_never_interrupts_already_completed_turn(self):
        self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
        self.factory.turn_events = self.model_events('not-json')
        await self.runtime.dispatch('start', self.params('test'))
        self.assertEqual((await self.terminal())['state'], 'FAILED')
        self.assertFalse(any(method == 'turn/interrupt' for session in self.factory.sessions for method, _ in session.calls))

    async def test_primary_failure_diagnostic_survives_cleanup_failure(self):
        self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
        self.factory.turn_events = self.model_events('not-json')
        self.factory.close_error = True
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            await self.runtime.dispatch('start', self.params('test'))
            operation = await self.terminal()
        self.assertEqual((operation['state'], operation['error_code']), ('FAILED', 'INTERRUPTED'))
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn({'event': 'operation_failure', 'action': 'test', 'stage': 'final_json',
                       'error_code': 'INVALID_REQUEST'}, events)
        self.assertNotIn('not-json', output.getvalue())

    async def capture_turn_result(self, status, error=None, notices=()):
        self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
        self.factory.turn_events = list(notices) + self.model_events('{"ok":true}')
        self.factory.turn_events[-1]['params']['turn'].update(status=status, error=error)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            await self.runtime.dispatch('start', self.params('test'))
            operation = await self.terminal()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        diagnostics = [record for record in records if record.get('event') == 'model_turn_result']
        self.assertEqual(len(diagnostics), 1)
        self.assertFalse(any(method == 'turn/interrupt' for session in self.factory.sessions for method, _ in session.calls))
        return operation, diagnostics[0], output.getvalue()

    async def test_turn_diagnostic_classifies_known_errors_with_explicit_usage_code(self):
        for category in ('usageLimitExceeded', 'rateLimitExceeded', 'sessionBudgetExceeded', 'modelNotFound', 'unauthorized'):
            with self.subTest(category=category):
                operation, diagnostic, output = await self.capture_turn_result('failed', {
                    'message': 'private-token-message', 'additionalDetails': 'private-detail', 'codexErrorInfo': category})
                expected = 'USAGE_LIMIT_EXCEEDED' if category == 'usageLimitExceeded' else 'UPSTREAM_UNAVAILABLE'
                self.assertEqual((operation['state'], operation['error_code']), ('FAILED', expected))
                self.assertEqual(diagnostic, {'event': 'model_turn_result', 'turn_status': 'failed',
                    'error_present': True, 'codex_error_info': category, 'http_status': None,
                    'cancel_requested': False, 'last_error': None})
                self.assertNotIn('private-', output)

    async def test_usage_limit_requires_explicit_failed_terminal_error(self):
        notice = {'method': 'error', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'willRetry': False,
            'error': {'message': 'private-message', 'codexErrorInfo': 'usageLimitExceeded'}}}
        for status, error, notices, state, code in (
            ('failed', {'codexErrorInfo': 'usageLimitExceeded'}, [], 'FAILED', 'USAGE_LIMIT_EXCEEDED'),
            ('failed', None, [notice], 'FAILED', 'UPSTREAM_UNAVAILABLE'),
            ('failed', {'codexErrorInfo': 'unauthorized'}, [notice], 'FAILED', 'UPSTREAM_UNAVAILABLE'),
            ('interrupted', {'codexErrorInfo': 'usageLimitExceeded'}, [notice], 'FAILED', 'UPSTREAM_UNAVAILABLE'),
            ('inProgress', {'codexErrorInfo': 'usageLimitExceeded'}, [], 'FAILED', 'UPSTREAM_UNAVAILABLE'),
            ('completed', None, [notice], 'SUCCEEDED', ''),
            ('completed', {'codexErrorInfo': 'usageLimitExceeded'}, [], 'SUCCEEDED', ''),
        ):
            with self.subTest(status=status, error=error, notices=bool(notices)):
                operation, _, output = await self.capture_turn_result(status, error, notices)
                self.assertEqual((operation['state'], operation['error_code']), (state, code))
                self.assertNotIn('private-', output)

    async def test_turn_diagnostic_keeps_success_and_interruption_distinct(self):
        for status in ('completed', 'interrupted', 'inProgress', 'private-secret-status', None, []):
            with self.subTest(status=status):
                operation, diagnostic, output = await self.capture_turn_result(status)
                self.assertEqual(operation['state'], 'SUCCEEDED' if status == 'completed' else 'FAILED')
                self.assertEqual(diagnostic['turn_status'], status if type(status) is str and status in {
                    'completed', 'interrupted', 'inProgress'} else 'UNKNOWN')
                self.assertFalse(diagnostic['error_present'])
                self.assertNotIn('private-secret-status', output)

    async def test_turn_diagnostic_http_status_rejects_bool_string_float_and_out_of_range(self):
        for status in (403, 429, 503, True, '429', 429.0, 99, 600):
            with self.subTest(status=status):
                _, diagnostic, output = await self.capture_turn_result('failed', {'message': 'private-message',
                    'codexErrorInfo': {'httpConnectionFailed': {'httpStatusCode': status, 'extra': 'private-secret'}}})
                self.assertEqual(diagnostic['codex_error_info'], 'httpConnectionFailed')
                self.assertEqual(diagnostic['http_status'], status if type(status) is int and 100 <= status <= 599 else None)
                self.assertNotIn('private-', output)

    async def test_turn_diagnostic_never_echoes_unknown_error_payload(self):
        for info in ('private-secret', {'private-secret': {'message': 'private-token'}}, [],
                     {'httpConnectionFailed': 'private-token'}):
            with self.subTest(info=info):
                _, diagnostic, output = await self.capture_turn_result('failed', {'message': 'private-message',
                    'codexErrorInfo': info, 'misalignment': {'errorType': 'private-secret'}})
                self.assertEqual(diagnostic['codex_error_info'], 'UNKNOWN')
                self.assertNotIn('private-', output)

    async def test_turn_diagnostic_rejects_malformed_error_and_non_http_status(self):
        _, diagnostic, _ = await self.capture_turn_result('failed', 'usageLimitExceeded')
        self.assertEqual(diagnostic['codex_error_info'], 'UNKNOWN')
        _, diagnostic, _ = await self.capture_turn_result('failed', {'message': 'private-message',
            'codexErrorInfo': {'activeTurnNotSteerable': {'turnKind': 'review', 'httpStatusCode': 403}}})
        self.assertEqual(diagnostic['codex_error_info'], 'activeTurnNotSteerable')
        self.assertIsNone(diagnostic['http_status'])

    async def test_turn_diagnostic_only_keeps_last_error_for_matching_thread_and_turn(self):
        def notice(thread, turn, category, retry):
            return {'method': 'error', 'params': {'threadId': thread, 'turnId': turn, 'willRetry': retry,
                'error': {'message': 'private-message', 'codexErrorInfo': category}}}
        notices = [notice('other-thread', 'turn-1', 'modelNotFound', False),
                   notice('thread-1', 'other-turn', 'unauthorized', False),
                   notice('thread-1', 'turn-1', 'rateLimitExceeded', True)]
        operation, diagnostic, output = await self.capture_turn_result('failed', notices=notices)
        self.assertEqual((operation['state'], operation['error_code']), ('FAILED', 'UPSTREAM_UNAVAILABLE'))
        self.assertEqual(diagnostic['last_error'], {'codex_error_info': 'rateLimitExceeded',
            'http_status': None, 'will_retry': True})
        self.assertIsNone(diagnostic['codex_error_info'])
        notifications = [json.loads(line) for line in output.splitlines()
                         if json.loads(line).get('event') == 'model_turn_error']
        self.assertEqual(notifications, [{'event': 'model_turn_error', 'codex_error_info': 'rateLimitExceeded',
            'http_status': None, 'will_retry': True}])
        self.assertNotIn('private-', output)

    async def asyncSetUp(self):
        self.factory = Factory()
        self.runtime = Runtime(session_factory=self.factory, login_timeout=0.2, operation_timeout=2)
        self.runtime.login_completion_grace = 0

    async def asyncTearDown(self):
        if self.factory.close_gate:
            self.factory.close_gate.set()
        if self.factory.start_gate:
            self.factory.start_gate.set()
        await self.runtime.close()

    def params(self, action='login', generation=1):
        return dict(operation_id=str(uuid.uuid4()), generation=generation, action=action,
                    model='visible-model' if action == 'test' else '')

    async def eventually(self, condition):
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(0.005)
        self.fail('condition did not become true')

    async def terminal(self):
        await self.eventually(lambda: self.runtime.snapshot()['operation']['state'] != 'RUNNING')
        return self.runtime.snapshot()['operation']

    async def challenge(self, params):
        for _ in range(50):
            try:
                return await self.runtime.dispatch('challenge', {k: params[k] for k in ('operation_id', 'generation')})
            except RuntimeErrorCode as error:
                self.assertEqual(error.code, 'NOT_READY')
                await asyncio.sleep(0.005)
        self.fail('challenge not available')

    async def test_status_is_cache_only_and_boot_changes(self):
        first = await self.runtime.dispatch('status', {})
        second = Runtime(session_factory=self.factory)
        self.assertNotEqual(first['boot_id'], second.snapshot()['boot_id'])
        self.assertEqual(self.factory.sessions, [])
        self.assertIsNone(first['account'])
        await second.close()

    async def test_start_is_nonblocking_and_same_payload_is_idempotent(self):
        self.factory.start_gate = asyncio.Event()
        p = self.params()
        first = await asyncio.wait_for(self.runtime.dispatch('start', p), 0.1)
        again = await self.runtime.dispatch('start', p)
        self.assertEqual(first['operation']['id'], again['operation']['id'])
        with self.assertRaisesRegex(RuntimeErrorCode, 'INVALID_REQUEST'):
            await self.runtime.dispatch('start', dict(p, action='switch'))
        with self.assertRaisesRegex(RuntimeErrorCode, 'BUSY'):
            await self.runtime.dispatch('start', self.params())

    async def test_cancel_is_quick_idempotent_and_keeps_barrier_until_exit(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        self.factory.close_gate = asyncio.Event()
        lookup = {k: p[k] for k in ('operation_id', 'generation')}
        await asyncio.wait_for(self.runtime.dispatch('cancel', lookup), 0.1)
        await self.runtime.dispatch('cancel', lookup)
        self.assertEqual(self.runtime.snapshot()['operation']['state'], 'RUNNING')
        with self.assertRaisesRegex(RuntimeErrorCode, 'BUSY'):
            await self.runtime.dispatch('start', self.params())
        self.factory.close_gate.set()
        op = await self.terminal()
        self.assertEqual(op['state'], 'CANCELED')
        self.assertTrue(all(s.closed for s in self.factory.sessions))
        self.assertEqual(sum(m == 'account/login/cancel' for s in self.factory.sessions for m, _ in s.calls), 1)
        await self.runtime.dispatch('cancel', lookup)
        self.assertEqual((await self.runtime.dispatch('operation', lookup))['operation'], op)

    async def test_cancel_before_worker_starts_still_finishes(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.runtime.dispatch('cancel', {k: p[k] for k in ('operation_id', 'generation')})
        self.assertEqual((await self.terminal())['state'], 'CANCELED')

    async def test_cancel_completion_race_reconciles_actual_account(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        self.factory.cancel_status = 'notFound'
        self.factory.complete_on_close = True
        await self.runtime.dispatch('cancel', {k: p[k] for k in ('operation_id', 'generation')})
        self.assertEqual((await self.terminal())['state'], 'CANCELED')
        snapshot = self.runtime.snapshot()
        self.assertIsNotNone(snapshot['account'])
        self.assertNotIn('private-person', json.dumps(snapshot))
        self.assertNotIn('example.test', json.dumps(snapshot))

    async def test_wrong_login_notification_is_ignored_and_timeout_cancels(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        self.factory.sessions[0].events.put_nowait({'method': 'account/login/completed',
             'params': {'loginId': str(uuid.uuid4()), 'success': True}})
        op = await self.terminal()
        self.assertEqual((op['state'], op['error_code']), ('FAILED', 'TIMEOUT'))
        self.assertTrue(all(s.closed for s in self.factory.sessions))

    async def test_login_success_refreshes_and_hides_challenge(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        challenge = await self.challenge(p)
        self.assertEqual(set(challenge), {'operation_id', 'verification_url', 'user_code', 'expires_at'})
        session = self.factory.sessions[0]
        self.factory.account = dict(type='chatgpt', email='secret@example.test', planType='pro')
        session.events.put_nowait({'method': 'account/login/completed',
            'params': {'loginId': session.login_id, 'success': True}})
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        self.assertEqual(self.runtime.snapshot()['models'][0]['id'], 'visible-model')
        self.assertNotIn('ABCD', json.dumps(self.runtime.snapshot()))
        with self.assertRaisesRegex(RuntimeErrorCode, 'NOT_FOUND'):
            await self.runtime.dispatch('challenge', {k: p[k] for k in ('operation_id', 'generation')})

    async def test_default_device_code_display_is_fifteen_minutes(self):
        self.runtime = Runtime(session_factory=self.factory)
        self.assertEqual(self.runtime.login_timeout, 900)
        self.assertEqual(self.runtime.login_completion_grace, 120)
        before = datetime.now(timezone.utc)
        p = self.params()
        await self.runtime.dispatch('start', p)
        challenge = await self.challenge(p)
        seconds = (datetime.fromisoformat(challenge['expires_at']) - before).total_seconds()
        self.assertGreaterEqual(seconds, 900)
        self.assertLess(seconds, 901)

    async def test_login_and_switch_keep_nonwaiting_budget(self):
        for action in ('login', 'switch'):
            with self.subTest(action=action):
                await self.runtime.close()
                self.factory = Factory()
                self.runtime = Runtime(session_factory=self.factory, login_timeout=0.2, operation_timeout=0.02)
                self.runtime.login_completion_grace = 0.1
                p = self.params(action)
                await self.runtime.dispatch('start', p)
                await self.challenge(p)
                await asyncio.sleep(0.05)
                self.assertEqual(self.runtime.snapshot()['operation']['state'], 'RUNNING')
                session = self.factory.sessions[-1]
                self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
                session.events.put_nowait({'method': 'account/login/completed',
                    'params': {'loginId': session.login_id, 'success': True}})
                self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')

    async def test_nonlogin_operations_keep_the_original_timeout(self):
        self.runtime.operation_timeout = 0.02
        self.factory.start_gate = asyncio.Event()
        await self.runtime.dispatch('start', self.params('refresh'))
        op = await self.terminal()
        self.assertEqual((op['state'], op['error_code']), ('FAILED', 'TIMEOUT'))

    async def test_no_completion_after_grace_times_out_and_cancels(self):
        self.runtime.login_timeout, self.runtime.login_completion_grace = 0.02, 0.02
        await self.runtime.dispatch('start', self.params())
        op = await self.terminal()
        self.assertEqual((op['state'], op['error_code']), ('FAILED', 'TIMEOUT'))
        self.assertEqual(sum(m == 'account/login/cancel' for s in self.factory.sessions for m, _ in s.calls), 1)

    async def test_expired_display_still_accepts_completion_during_bounded_grace(self):
        self.runtime.login_timeout, self.runtime.login_completion_grace = 0.02, 0.2
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        await asyncio.sleep(0.04)
        with self.assertRaisesRegex(RuntimeErrorCode, 'NOT_FOUND'):
            await self.runtime.dispatch('challenge', {k: p[k] for k in ('operation_id', 'generation')})
        self.assertEqual(self.runtime.snapshot()['operation']['state'], 'RUNNING')
        session = self.factory.sessions[0]
        self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
        session.events.put_nowait({'method': 'account/login/completed',
            'params': {'loginId': session.login_id, 'success': True}})
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')

    async def test_deadline_consumes_queued_match_after_wrong_login_id(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        session = self.factory.sessions[0]
        # 等待协程到期时，读泵已把通知入队；该边缘不能被当成没有完成通知。
        async def deadline(_):
            self.factory.account = dict(type='chatgpt', email='test@example.test', planType='pro')
            for identifier in (str(uuid.uuid4()), session.login_id):
                session.events.put_nowait({'method': 'account/login/completed',
                    'params': {'loginId': identifier, 'success': True}})
            raise RuntimeErrorCode('TIMEOUT')
        session.notification = deadline
        session.events.put_nowait({'method': 'account/login/completed',
            'params': {'loginId': str(uuid.uuid4()), 'success': True}})
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        self.assertFalse(any(method == 'account/login/cancel' for method, _ in session.calls))

    async def test_deadline_wrong_id_does_not_wait_again(self):
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        session = self.factory.sessions[0]
        calls = 0
        async def deadline(_):
            nonlocal calls
            calls += 1
            session.events.put_nowait({'method': 'account/login/completed',
                'params': {'loginId': str(uuid.uuid4()), 'success': True}})
            raise RuntimeErrorCode('TIMEOUT')
        session.notification = deadline
        session.events.put_nowait({'method': 'account/login/completed',
            'params': {'loginId': str(uuid.uuid4()), 'success': True}})
        op = await self.terminal()
        self.assertEqual((op['state'], op['error_code'], calls), ('FAILED', 'TIMEOUT', 1))

    async def test_cancel_during_completion_grace_keeps_reconciliation(self):
        self.runtime.login_timeout, self.runtime.login_completion_grace = 0.02, 0.2
        p = self.params()
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        await asyncio.sleep(0.04)
        self.factory.complete_on_close = True
        await self.runtime.dispatch('cancel', {k: p[k] for k in ('operation_id', 'generation')})
        self.assertEqual((await self.terminal())['state'], 'CANCELED')
        self.assertIsNotNone(self.runtime.snapshot()['account'])

    async def test_unofficial_challenge_rejected_and_upstream_error_redacted(self):
        self.factory.url = 'https://auth.openai.com.evil.test/login'
        await self.runtime.dispatch('start', self.params())
        op = await self.terminal()
        self.assertEqual(op['state'], 'FAILED')
        self.assertNotIn('evil', json.dumps(self.runtime.snapshot()))
        self.factory.url = 'https://auth.openai.com/codex/device'
        self.factory.fail = 'account/read'
        await self.runtime.dispatch('start', self.params('refresh', 2))
        self.assertEqual((await self.terminal())['error_code'], 'UPSTREAM_UNAVAILABLE')
        self.assertNotIn('secret-upstream', json.dumps(self.runtime.snapshot()))

    async def test_switch_stops_old_session_before_new_login(self):
        self.factory.account = dict(type='chatgpt', email='old@example.test', planType='pro')
        p = self.params('switch')
        await self.runtime.dispatch('start', p)
        await self.challenge(p)
        self.assertGreaterEqual(len(self.factory.sessions), 2)
        self.assertTrue(self.factory.sessions[0].closed)
        self.assertIn(('account/logout', {}), self.factory.sessions[0].calls)

    async def test_test_uses_visible_model_and_empty_execution_environments(self):
        self.factory.account = dict(type='chatgpt', email='private@example.test', planType='pro')
        await self.runtime.dispatch('start', self.params('test'))
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        calls = [call for session in self.factory.sessions for call in session.calls]
        for method in ('thread/start', 'turn/start'):
            params = next(params for name, params in calls if name == method)
            self.assertEqual(params['environments'], [])
        self.assertTrue(next(p for n, p in calls if n == 'thread/start')['ephemeral'])
        self.assertEqual(next(p for n, p in calls if n == 'turn/start')['input'][0]['text'],
                         'Return exactly the JSON object {"ok":true}. Do not call tools.')

    async def test_unknown_generation_and_extra_fields_rejected(self):
        with self.assertRaisesRegex(RuntimeErrorCode, 'INVALID_REQUEST'):
            await self.runtime.dispatch('start', dict(self.params(), prompt='arbitrary'))
        with self.assertRaisesRegex(RuntimeErrorCode, 'INVALID_REQUEST'):
            await self.runtime.dispatch('start', dict(self.params(), generation=True))
        p = self.params()
        await self.runtime.dispatch('start', p)
        with self.assertRaisesRegex(RuntimeErrorCode, 'NOT_FOUND'):
            await self.runtime.dispatch('operation', dict(operation_id=p['operation_id'], generation=2))

    async def test_unknown_operation_returns_null_without_replaying(self):
        result = await self.runtime.dispatch('operation', {'operation_id': str(uuid.uuid4()), 'generation': 1})
        self.assertIsNone(result['operation'])
        self.assertEqual(self.factory.sessions, [])

    async def test_unhashable_action_is_invalid_request(self):
        with self.assertRaisesRegex(RuntimeErrorCode, 'INVALID_REQUEST'):
            await self.runtime.dispatch('start', dict(self.params(), action=[]))

    async def test_replay_terminal_operation_returns_that_operation_not_latest(self):
        self.factory.account = dict(type='chatgpt', email='private@example.test', planType='pro')
        first, second = self.params('refresh'), self.params('refresh')
        await self.runtime.dispatch('start', first)
        await self.terminal()
        await self.runtime.dispatch('start', second)
        await self.terminal()
        count = len(self.factory.sessions)
        result = await self.runtime.dispatch('start', first)
        self.assertEqual(result['operation']['id'], first['operation_id'])
        self.assertEqual(len(self.factory.sessions), count)

    async def test_failed_limit_refresh_does_not_keep_previous_limit_snapshot(self):
        self.factory.account = dict(type='chatgpt', email='private@example.test', planType='pro')
        await self.runtime.dispatch('start', self.params('refresh'))
        await self.terminal()
        self.assertIsNotNone(self.runtime.snapshot()['rate_limits'])
        self.factory.fail = 'account/rateLimits/read'
        await self.runtime.dispatch('start', self.params('refresh'))
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        self.assertIsNone(self.runtime.snapshot()['rate_limits'])
        self.assertIsNone(self.runtime.snapshot()['limits_updated_at'])
        self.assertEqual(self.runtime.snapshot()['models'][0]['id'], 'visible-model')

    async def test_missing_limits_does_not_prevent_real_model_test(self):
        self.factory.account = dict(type='chatgpt', email='private@example.test', planType='pro')
        self.factory.fail = 'account/rateLimits/read'
        await self.runtime.dispatch('start', self.params('test'))
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        self.assertTrue(any(method == 'turn/start' for s in self.factory.sessions for method, _ in s.calls))


class LimitTests(unittest.TestCase):
    def test_masked_accounts_are_distinguishable_without_full_email_or_domain(self):
        first = account_summary(dict(type='chatgpt', email='alice@example.test', planType='pro'))
        second = account_summary(dict(type='chatgpt', email='bob@example.test', planType='pro'))
        self.assertNotEqual(first['display_name'], second['display_name'])
        self.assertEqual(first['display_name'], 'a***@e***.test')
        self.assertNotIn('example.test', json.dumps(first))

    def test_null_is_unknown_and_zero_is_preserved(self):
        value = normalize_limits({'rateLimits': {'primary': {'usedPercent': 0}, 'secondary': None}})
        self.assertEqual(value['windows'][0]['used_percent'], 0)
        self.assertIsNone(value['windows'][0]['window_minutes'])
        self.assertIsNone(value['windows'][0]['resets_at'])
        self.assertIsNone(value['credits'])

    def test_secret_like_balance_is_not_returned(self):
        with self.assertRaises(RuntimeErrorCode):
            normalize_limits({'rateLimits': {'credits': {'unlimited': False, 'hasCredits': True, 'balance': 'secret-token'}}})

    def test_more_than_twenty_windows_is_rejected_without_truncating(self):
        bucket = {'primary': {'usedPercent': 1}, 'secondary': {'usedPercent': 2}}
        with self.assertRaises(RuntimeErrorCode):
            normalize_limits({'rateLimits': bucket, 'rateLimitsByLimitId': {f'bucket{i}': bucket for i in range(11)}})
