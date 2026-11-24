import asyncio
import base64
import hashlib
import json
import unittest
from unittest.mock import patch
import uuid

import test_service as fixtures
from codex_runtime.nesting import validate_payload
from codex_runtime.protocol import RuntimeErrorCode
from codex_runtime.service import Runtime


def payload(phase='extract'):
    source = b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n'
    value = {'schema_version': 2, 'phase': phase, 'source': {
        'data_base64': base64.b64encode(source).decode(), 'size_bytes': len(source),
        'sha256': hashlib.sha256(source).hexdigest(), 'unit': 'mm'}}
    if phase == 'nest':
        value.update(parameters={'width_mm': 1680, 'gap_mm': 0, 'set_count': 1, 'products_per_set': 1,
            'pieces': [{'piece_id': 'P001', 'quantity': 1, 'rotation_mode': 'free'}]}, analysis_digest='a' * 64)
    return value


class FakeTools:
    instances = []

    def __init__(self, value):
        self.value, self.calls, self.closed = value, [], False
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def tool_definitions(self):
        return [{'type': 'function', 'name': name, 'description': 'fixed',
                 'inputSchema': {'type': 'object', 'additionalProperties': False}}
                for name in ('inspect_source', 'search_layout', 'finalize_layout')]

    async def call(self, tool, arguments, call_id):
        self.calls.append((tool, arguments, call_id))
        return {'step': tool}

    def completed_result(self):
        if not self.calls or self.calls[-1][0] != 'finalize_layout':
            raise RuntimeErrorCode('TOOL_SEQUENCE')
        artifacts = {'layout.svg': b'<svg/>', 'layout.dxf': b'0\nEOF\n'} if self.value['phase'] == 'nest' else {}
        manifest = [{'name': name, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                     'content_type': 'image/svg+xml' if name.endswith('.svg') else 'application/dxf'}
                    for name, data in artifacts.items()]
        return {'schema_version': 2, 'phase': self.value['phase'], 'source_sha256': self.value['source']['sha256'],
                'analysis_digest': 'a' * 64, 'parameters_digest': '', 'analysis': {'pieces': []},
                'result': None, 'artifacts': manifest, 'execution': {'engine': 'CODEX_TOOLS',
                'toolkit_version': '1', 'tool_calls': [], 'guided_attempts': 0}}, artifacts


class ToolFakeSession(fixtures.FakeSession):
    def enable_dynamic_tools(self):
        self.calls.append(('dynamic/enable', {}))

    async def respond_tool_call(self, request_id, response):
        self.calls.append(('dynamic/reply', {'id': request_id, 'result': response}))


class ToolFactory(fixtures.Factory):
    def __call__(self):
        session = ToolFakeSession(self)
        self.sessions.append(session)
        return session


def tool_event(name, index=1, **overrides):
    return {'id': f'rpc-{index}', 'method': 'item/tool/call', 'params': {
        'threadId': 'thread-1', 'turnId': 'turn-1', 'callId': f'call-{index}',
        'tool': name, 'arguments': {}, **overrides}}


class NestingBoundaryTests(unittest.TestCase):
    def test_source_payload_and_version_are_strict(self):
        validate_payload(payload())
        validate_payload(payload('nest'))
        changes = [lambda p: p.update(schema_version=1), lambda p: p.update(prompt='read secrets'),
            lambda p: p['source'].update(path='/private'), lambda p: p['source'].update(data_base64='!'),
            lambda p: p['source'].update(size_bytes=6 * 1024 * 1024), lambda p: p['source'].update(size_bytes=True),
            lambda p: p['source'].update(sha256='b' * 64), lambda p: p['source'].update(unit='unknown')]
        for change in changes:
            value = payload()
            change(value)
            with self.subTest(change=change), self.assertRaises(RuntimeErrorCode):
                validate_payload(value)


class NestingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.factory = ToolFactory()
        self.factory.account = {'type': 'chatgpt', 'email': 'test@example.test', 'planType': 'pro'}
        self.runtime = Runtime(self.factory)
        self.tool_patch = patch('codex_runtime.nesting.tool_session_factory', FakeTools)
        self.tool_patch.start()

    async def asyncTearDown(self):
        await self.runtime.close()
        self.tool_patch.stop()

    def params(self, phase='extract'):
        return {'operation_id': str(uuid.uuid4()), 'generation': 1, 'action': 'nest',
                'model': 'visible-model', 'payload': payload(phase)}

    async def terminal(self):
        for _ in range(200):
            await asyncio.sleep(.01)
            state = self.runtime.snapshot()['operation']
            if state and state['state'] != 'RUNNING':
                return state
        self.fail('operation did not finish')

    def events(self):
        return [tool_event('inspect_source'), tool_event('finalize_layout', 2),
                *fixtures.RuntimeTests.model_events(self, 'plain final text is not a result')]

    async def test_tools_drive_result_and_file_never_enters_model_input(self):
        params = self.params('nest')
        self.factory.turn_events = self.events()
        self.assertEqual(self.runtime.snapshot()['capabilities'], ['nest_tools_v1'])
        await self.runtime.dispatch('start', params)
        self.assertEqual((await self.terminal())['state'], 'SUCCEEDED')
        operation = self.runtime.operations[params['operation_id']]
        self.assertEqual(operation.result['execution']['model'], 'visible-model')
        self.assertEqual(operation.artifacts['layout.svg'], b'<svg/>')
        self.assertTrue(FakeTools.instances[-1].closed)
        calls = [call for session in self.factory.sessions for call in session.calls]
        thread = next(value for method, value in calls if method == 'thread/start')
        turn = next(value for method, value in calls if method == 'turn/start')
        self.assertEqual(thread['model'], 'visible-model')
        self.assertEqual(len(thread['dynamicTools']), 3)
        self.assertNotIn(params['payload']['source']['data_base64'], json.dumps(turn))
        self.assertEqual([value['id'] for method, value in calls if method == 'dynamic/reply'], ['rpc-1', 'rpc-2'])
        self.assertNotIn('payload', operation.params)
        self.assertNotIn('source_sha256', json.dumps(self.runtime.snapshot()))

    async def test_model_claim_without_tools_cannot_succeed(self):
        self.factory.turn_events = fixtures.RuntimeTests.model_events(self, '{"done":true,"validation":true}')
        await self.runtime.dispatch('start', self.params())
        self.assertEqual((await self.terminal())['state'], 'FAILED')
        self.assertTrue(FakeTools.instances[-1].closed)

    async def test_wrong_turn_forbidden_tool_duplicate_call_and_rpc_are_rejected(self):
        for events in ([tool_event('inspect_source', turnId='other')], [tool_event('shell')],
                [tool_event('inspect_source'), tool_event('finalize_layout', 2, callId='call-1')],
                [tool_event('inspect_source'), tool_event('finalize_layout')]):
            self.factory.turn_events = [*events, *fixtures.RuntimeTests.model_events(self, '{"done":true}')]
            await self.runtime.dispatch('start', self.params())
            self.assertEqual((await self.terminal())['state'], 'FAILED')

    async def test_artifact_identity_and_previous_result_cleanup(self):
        params = self.params('nest')
        self.factory.turn_events = self.events()
        await self.runtime.dispatch('start', params)
        await self.terminal()
        request = {'operation_id': params['operation_id'], 'generation': 1,
                   'boot_id': self.runtime.boot_id, 'name': 'layout.svg'}
        response = await self.runtime.dispatch('artifact', request)
        self.assertEqual(base64.b64decode(response['data_base64']), b'<svg/>')
        for changed in ({**request, 'boot_id': str(uuid.uuid4())}, {**request, 'name': '../source.dxf'},
                        {**request, 'generation': 2}):
            with self.assertRaises(RuntimeErrorCode):
                await self.runtime.dispatch('artifact', changed)
        await self.runtime.dispatch('start', self.params())
        with self.assertRaises(RuntimeErrorCode):
            await self.runtime.dispatch('artifact', request)
        await self.terminal()

    async def test_cancel_and_timeout_close_tools_without_artifacts(self):
        for cancel in (True, False):
            self.factory.turn_events = []
            self.runtime.operation_timeout = 2 if cancel else .02
            params = self.params()
            await self.runtime.dispatch('start', params)
            for _ in range(50):
                if self.runtime.operations[params['operation_id']].turn:
                    break
                await asyncio.sleep(.005)
            if cancel:
                await self.runtime.dispatch('cancel', {'operation_id': params['operation_id'], 'generation': 1})
            self.assertEqual((await self.terminal())['state'], 'CANCELED' if cancel else 'FAILED')
            self.assertTrue(FakeTools.instances[-1].closed)
            self.assertEqual(self.runtime.operations[params['operation_id']].artifacts, {})
