import asyncio
import contextlib
import io
import json
import sys
import unittest

from codex_runtime.protocol import AppServerSession, RpcPeer, RuntimeErrorCode, validate_config


class Writer:
    def __init__(self):
        self.data = []
    def write(self, data):
        self.data.append(json.loads(data))
    async def drain(self):
        pass


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_result_limit_is_not_reported_as_upstream_outage(self):
        reader = asyncio.StreamReader()
        peer = RpcPeer(reader, Writer())
        peer.bytes_read = peer.max_total_bytes
        try:
            reader.feed_data(b'{}\n')
            with self.assertRaisesRegex(RuntimeErrorCode, '^RESULT_LIMIT$'):
                await peer.notification(.2)
        finally:
            await peer.close()

    async def test_usage_limit_error_code_is_preserved_and_unknown_code_is_sanitized(self):
        self.assertEqual(RuntimeErrorCode('USAGE_LIMIT_EXCEEDED').code, 'USAGE_LIMIT_EXCEEDED')
        self.assertEqual(RuntimeErrorCode('private-upstream-reason').code, 'UPSTREAM_UNAVAILABLE')

    async def test_deadline_queue_snapshot_is_nonblocking_and_preserves_failure(self):
        peer = RpcPeer(asyncio.StreamReader(), Writer())
        session = AppServerSession()
        session.peer = peer
        try:
            first = {'method': 'account/login/completed', 'params': {'loginId': 'first'}}
            second = {'method': 'account/login/completed', 'params': {'loginId': 'second'}}
            peer.events.put_nowait(first)
            peer.events.put_nowait(second)
            self.assertEqual(session.take_queued_notifications(), [first, second])
            self.assertEqual(session.take_queued_notifications(), [])
            peer.fail('UPSTREAM_UNAVAILABLE')
            with self.assertRaisesRegex(RuntimeErrorCode, '^UPSTREAM_UNAVAILABLE$'):
                session.take_queued_notifications()
        finally:
            await session.close()

    async def test_intentional_session_close_does_not_report_upstream_failure(self):
        session = AppServerSession()
        session.process = await asyncio.create_subprocess_exec(
            sys.executable, '-B', '-c', 'import sys; sys.stdin.buffer.read()',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        session.peer = RpcPeer(session.process.stdout, session.process.stdin)
        output = io.StringIO()
        try:
            with contextlib.redirect_stderr(output):
                await session.close()
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(session.process.returncode, 0)
            self.assertTrue(session.peer.reader_task.done())
        finally:
            await session.close()

    async def test_unexpected_eof_fails_pending_request_and_reports_fixed_error(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        pending = asyncio.create_task(peer.request('account/read', {}))
        await asyncio.sleep(0)
        output = io.StringIO()
        try:
            with contextlib.redirect_stderr(output):
                reader.feed_eof()
                with self.assertRaisesRegex(RuntimeErrorCode, '^UPSTREAM_UNAVAILABLE$'):
                    await pending
                await peer.close()
            self.assertEqual(json.loads(output.getvalue()), {
                'event': 'runtime_error', 'stage': 'app_server_reader', 'exception_type': 'RuntimeErrorCode'})
        finally:
            await peer.close()

    async def test_single_reader_routes_out_of_order_responses_and_notifications(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        first = asyncio.create_task(peer.request('account/read', {}))
        second = asyncio.create_task(peer.request('model/list', {}))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        ids = [item['id'] for item in writer.data]
        reader.feed_data((json.dumps({'id': ids[1], 'result': {'data': []}}) + '\n' +
                          json.dumps({'method': 'account/login/completed', 'params': {'loginId': 'a'}}) + '\n' +
                          json.dumps({'id': ids[0], 'result': {'account': None}}) + '\n').encode())
        self.assertEqual(await second, {'data': []})
        self.assertEqual(await first, {'account': None})
        self.assertEqual((await peer.notification(0.1))['method'], 'account/login/completed')
        await peer.close()

    async def test_error_body_never_escapes(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        pending = asyncio.create_task(peer.request('account/read', {}))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        reader.feed_data((json.dumps({'id': writer.data[0]['id'], 'error': {'message': 'secret-token'}}) + '\n').encode())
        with self.assertRaisesRegex(RuntimeErrorCode, '^UPSTREAM_UNAVAILABLE$'):
            await pending
        await peer.close()

    async def test_server_requests_rejected(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        reader.feed_data(b'{"method":"item/commandExecution/requestApproval","id":9,"params":{}}\n')
        with self.assertRaises(RuntimeErrorCode):
            await peer.notification(0.2)
        self.assertEqual(writer.data[-1]['error']['code'], -32601)
        await peer.close()

    async def test_dynamic_request_opt_in_preserves_server_id_and_rejects_replay(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        try:
            peer.enable_dynamic_tools()
            request = {'method': 'item/tool/call', 'id': 'server-9', 'params': {'tool': 'inspect_source'}}
            reader.feed_data((json.dumps(request) + '\n').encode())
            self.assertEqual(await peer.notification(.2), request)
            await peer.respond_tool_call('server-9', {'success': True, 'contentItems': []})
            self.assertEqual(writer.data[-1], {'id': 'server-9', 'result': {'success': True, 'contentItems': []}})
            with self.assertRaises(RuntimeErrorCode):
                await peer.respond_tool_call('server-9', {'success': True, 'contentItems': []})
            reader.feed_data((json.dumps(request) + '\n').encode())
            with self.assertRaises(RuntimeErrorCode):
                await peer.notification(.2)
        finally:
            await peer.close()

    async def test_dynamic_opt_in_does_not_allow_shell_requests(self):
        reader, writer = asyncio.StreamReader(), Writer()
        peer = RpcPeer(reader, writer)
        try:
            peer.enable_dynamic_tools()
            reader.feed_data(b'{"method":"item/commandExecution/requestApproval","id":3,"params":{}}\n')
            with self.assertRaises(RuntimeErrorCode):
                await peer.notification(.2)
        finally:
            await peer.close()
