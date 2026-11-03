import asyncio
import json
import os
from pathlib import Path
import stat
import struct
import sys
import unittest

from codex_runtime.server import create_server, decode_request, encode_response, read_frame, MAX_FRAME
from codex_runtime.protocol import RuntimeErrorCode
from codex_runtime.service import Runtime
from test_service import Factory


class FrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_frame_decodes_and_extra_keys_rejected(self):
        body = b'{"method":"status","params":{}}'
        reader = asyncio.StreamReader()
        task = asyncio.create_task(read_frame(reader, 0.5))
        reader.feed_data(struct.pack('!I', len(body))[:2])
        await asyncio.sleep(0)
        reader.feed_data(struct.pack('!I', len(body))[2:] + body)
        self.assertEqual(decode_request(await task), ('status', {}))
        with self.assertRaises(RuntimeErrorCode):
            decode_request(b'{"method":"status","params":{},"token":"secret"}')

    async def test_large_short_invalid_duplicate_and_nan_frames_rejected(self):
        for raw in [struct.pack('!I', MAX_FRAME + 1), struct.pack('!I', 4) + b'{}']:
            reader = asyncio.StreamReader()
            reader.feed_data(raw)
            reader.feed_eof()
            with self.assertRaises(RuntimeErrorCode):
                await read_frame(reader, 0.1)
        for data in [b'\xff', b'{"method":"status","method":"start","params":{}}',
                     b'{"method":"status","params":{"a":NaN}}']:
            with self.assertRaises(RuntimeErrorCode):
                decode_request(data)

    async def test_response_is_one_bounded_frame(self):
        data = encode_response({'ok': False, 'error': {'code': 'INVALID_REQUEST'}})
        self.assertEqual(struct.unpack('!I', data[:4])[0], len(data) - 4)
        self.assertEqual(json.loads(data[4:])['error']['code'], 'INVALID_REQUEST')


@unittest.skipUnless(sys.platform.startswith('linux'), '真实Unix socket只在已登记Linux runner验证')
class UnixSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path('/tmp/haiqu-codex-runtime-unit02')
        self.assertFalse(self.root.exists() or self.root.is_symlink())
        self.root.mkdir(mode=0o700)
        self.path = self.root / 'runtime.sock'
        self.runtime = Runtime(session_factory=Factory())
        self.server = await create_server(self.runtime, self.path)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.runtime.close()
        if self.path.exists():
            self.assertTrue(stat.S_ISSOCK(self.path.lstat().st_mode))
            self.path.unlink()
        self.assertEqual(self.root.resolve(), Path('/tmp/haiqu-codex-runtime-unit02'))
        self.root.rmdir()
        self.assertFalse(self.root.exists())

    async def test_real_socket_round_trip_and_connection_closes_after_one_request(self):
        reader, writer = await asyncio.open_unix_connection(str(self.path))
        try:
            writer.write(encode_response({'method': 'status', 'params': {}}))
            await writer.drain()
            response = json.loads(await read_frame(reader))
            self.assertTrue(response['ok'])
            self.assertEqual(response['data']['boot_id'], self.runtime.boot_id)
            self.assertEqual(await asyncio.wait_for(reader.read(1), 0.5), b'')
            self.assertEqual(stat.S_IMODE(self.path.lstat().st_mode), 0o660)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_oversized_request_returns_fixed_error_without_body(self):
        reader, writer = await asyncio.open_unix_connection(str(self.path))
        try:
            writer.write(struct.pack('!I', MAX_FRAME + 1))
            await writer.drain()
            self.assertEqual(json.loads(await read_frame(reader)), {'ok': False, 'error': {'code': 'INVALID_REQUEST'}})
        finally:
            writer.close()
            await writer.wait_closed()
