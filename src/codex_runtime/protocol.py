"""固定 0.165.0 App Server 的私有 stdio 会话。"""
import asyncio
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
from urllib.parse import urlsplit


ERROR_CODES = {'INVALID_REQUEST', 'BUSY', 'NOT_FOUND', 'NOT_READY', 'UPSTREAM_UNAVAILABLE',
               'AUTH_REQUIRED', 'MODEL_UNAVAILABLE', 'USAGE_LIMIT_EXCEEDED', 'TIMEOUT', 'INTERRUPTED'}
FEATURES = {'shell_tool': False, 'view_image': False, 'apps': False, 'multi_agent_v2': False,
            'plugins': False, 'skip_host_skill_discovery': True, 'browser_use': False,
            'computer_use': False, 'image_generation': False}
TOOL_TYPES = {'functionCallOutput', 'commandExecution', 'fileChange', 'mcpToolCall', 'dynamicToolCall',
              'collabAgentToolCall', 'subAgentActivity', 'webSearch', 'imageView', 'imageGeneration', 'sleep'}
MAX_RPC_LINE = 4 * 1024 * 1024


class RuntimeErrorCode(Exception):
    def __init__(self, code):
        self.code = code if code in ERROR_CODES else 'UPSTREAM_UNAVAILABLE'
        super().__init__(self.code)


def require(condition, code='UPSTREAM_UNAVAILABLE'):
    if not condition:
        raise RuntimeErrorCode(code)


def report_error(stage, error):
    """仅固定调用位置和异常类型；不打印异常消息、局部变量、RPC正文或堆栈。"""
    print(json.dumps({'event': 'runtime_error', 'stage': stage,
                      'exception_type': type(error).__name__}), file=sys.stderr, flush=True)


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'INVALID_REQUEST')
            result[key] = value
        return result

    def invalid(_):
        raise RuntimeErrorCode('INVALID_REQUEST')

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RuntimeErrorCode('INVALID_REQUEST') from None


def validate_config(config, sqlite_home=None, log_dir=None):
    require(isinstance(config, dict))
    require(config.get('approval_policy') == 'never' and config.get('web_search') == 'disabled'
            and config.get('sandbox_mode') == 'read-only' and config.get('cli_auth_credentials_store') == 'file')
    require(all((config.get('features') or {}).get(key) is value for key, value in FEATURES.items()))
    require((config.get('agents') or {}).get('enabled') is False and config.get('mcp_servers') == {})
    for section in ('apps', 'plugins'):
        values = config.get(section) or {}
        require(set(values) == {'_default'} and (values['_default'] or {}).get('enabled') is False)
    skills = config.get('skills') or {}
    require(skills.get('include_instructions') is False and (skills.get('bundled') or {}).get('enabled') is False)
    if sqlite_home is not None:
        require(config.get('sqlite_home') == sqlite_home and config.get('log_dir') == log_dir)


class RpcPeer:
    """一个读泵匹配全部响应；请求协程绝不直接抢读 stdout。"""
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.pending = {}
        self.events = asyncio.Queue(maxsize=256)
        self.write_lock = asyncio.Lock()
        self.identifier = 0
        self.bytes_read = 0
        self.failure = None
        self.reader_task = asyncio.create_task(self._read())

    def fail(self, code):
        if self.failure is None:
            self.failure = RuntimeErrorCode(code)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeErrorCode(self.failure.code))
        if not self.events.full():
            self.events.put_nowait(None)

    async def send(self, message):
        payload = (json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n').encode()
        require(len(payload) <= MAX_RPC_LINE)
        async with self.write_lock:
            require(self.failure is None)
            self.writer.write(payload)
            try:
                await asyncio.wait_for(self.writer.drain(), 10)
            except (OSError, TimeoutError):
                raise RuntimeErrorCode('UPSTREAM_UNAVAILABLE') from None

    async def _read(self):
        try:
            while True:
                line = await self.reader.readline()
                require(line and len(line) <= MAX_RPC_LINE)
                self.bytes_read += len(line)
                require(self.bytes_read <= 8 * 1024 * 1024)
                message = strict_json(line)
                require(type(message) is dict)
                if 'method' in message and 'id' in message:
                    await self.send({'id': message['id'], 'error': {'code': -32601, 'message': 'Requests disabled'}})
                    raise RuntimeErrorCode('UPSTREAM_UNAVAILABLE')
                if 'id' in message:
                    identifier = message['id']
                    require(type(identifier) is int and 0 < identifier <= self.identifier)
                    future = self.pending.get(identifier)
                    if future is None or future.done():
                        continue
                    if 'error' in message:
                        future.set_exception(RuntimeErrorCode('UPSTREAM_UNAVAILABLE'))
                    else:
                        require(type(message.get('result')) is dict)
                        future.set_result(message['result'])
                elif message.get('method') in {'account/login/completed', 'turn/completed',
                                               'item/started', 'item/completed', 'error'}:
                    require(not self.events.full())
                    self.events.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # 第三方 JSON/错误体只能留在当前调用内存，不能成为日志或异常消息。
            self.fail('UPSTREAM_UNAVAILABLE')
            report_error('app_server_reader', error)

    async def request(self, method, params, timeout=20):
        if self.failure:
            raise RuntimeErrorCode(self.failure.code)
        self.identifier += 1
        identifier = self.identifier
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self.send({'id': identifier, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            raise RuntimeErrorCode('TIMEOUT') from None
        finally:
            self.pending.pop(identifier, None)
            if not future.done():
                future.cancel()

    async def notification(self, timeout=20):
        if self.failure:
            raise RuntimeErrorCode(self.failure.code)
        try:
            event = await asyncio.wait_for(self.events.get(), timeout)
        except TimeoutError:
            raise RuntimeErrorCode('TIMEOUT') from None
        if event is None or self.failure:
            raise RuntimeErrorCode(self.failure.code if self.failure else 'UPSTREAM_UNAVAILABLE')
        return event

    def take_queued_notifications(self):
        if self.failure:
            raise RuntimeErrorCode(self.failure.code)
        # 同一事件循环内不await，只取截止时已有的有限队列，不等待晚到事件。
        return [self.events.get_nowait() for _ in range(self.events.qsize())]

    async def close(self):
        self.reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader_task
        self.fail('INTERRUPTED')


def child_environment():
    proxy = os.getenv('HTTP_PROXY', '')
    parsed = urlsplit(proxy)
    try:
        valid_ip = ipaddress.IPv4Address(parsed.hostname or '').is_private
        port = parsed.port
    except ValueError:
        raise RuntimeErrorCode('NOT_READY') from None
    require(parsed.scheme == 'http' and valid_ip and port == 18080 and not parsed.username
            and not parsed.password and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
            and os.getenv('HTTPS_PROXY') == proxy, 'NOT_READY')
    return {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': '/state/codex', 'CODEX_HOME': '/state/codex',
            'SSL_CERT_FILE': '/etc/ssl/certs/ca-certificates.crt',
            'HTTP_PROXY': proxy, 'HTTPS_PROXY': proxy, 'NO_PROXY': 'localhost,127.0.0.1'}


class AppServerSession:
    def __init__(self):
        self.process = self.peer = self.stderr_task = self.temporary = self.identity = None

    async def start(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='codex-runtime-', dir='/tmp')
        root = Path(self.temporary.name)
        info = root.lstat()
        self.identity = info.st_dev, info.st_ino
        sqlite_home, log_dir = str(root / 'state'), str(root / 'log')
        self.process = await asyncio.create_subprocess_exec(
            '/usr/local/bin/codex', '-c', f'sqlite_home={json.dumps(sqlite_home)}',
            '-c', f'log_dir={json.dumps(log_dir)}', 'app-server', '--strict-config', '--listen', 'stdio://',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=MAX_RPC_LINE + 1, env=child_environment(), cwd='/work/current', start_new_session=True)
        self.peer = RpcPeer(self.process.stdout, self.process.stdin)
        self.stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request('initialize', {'clientInfo': {'name': 'haiqu_codex_runtime', 'version': '0.1.0'},
                                         'capabilities': {'experimentalApi': True}})
        await self.peer.send({'method': 'initialized'})
        config = await self.request('config/read', {'includeLayers': False, 'cwd': '/work/current'})
        validate_config(config.get('config'), sqlite_home, log_dir)

    async def _drain_stderr(self):
        total = 0
        while data := await self.process.stderr.read(4096):
            total += len(data)
            if total > 65536:
                self.peer.fail('UPSTREAM_UNAVAILABLE')
                return

    async def request(self, method, params, timeout=20):
        require(self.peer is not None)
        return await self.peer.request(method, params, timeout)

    async def notification(self, timeout=20):
        return await self.peer.notification(timeout)

    def take_queued_notifications(self):
        return self.peer.take_queued_notifications()

    async def close(self):
        failure = None
        # 主动结束会话先停止读泵，再关闭stdin；子进程随后产生的EOF不是上游故障。
        if self.peer:
            await self.peer.close()
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                await asyncio.wait_for(self.process.wait(), 8)
            except (TimeoutError, OSError):
                for sig, timeout in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
                    if self.process.returncode is not None:
                        break
                    try:
                        os.killpg(self.process.pid, sig)
                        await asyncio.wait_for(self.process.wait(), timeout)
                    except (OSError, TimeoutError):
                        continue
                if self.process.returncode is None:
                    failure = RuntimeErrorCode('INTERRUPTED')
        if self.stderr_task:
            self.stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.stderr_task
        if self.temporary and failure is None:
            root = Path(self.temporary.name)
            info = root.lstat()
            require(root.parent == Path('/tmp') and root.resolve() == root and stat.S_ISDIR(info.st_mode)
                    and (info.st_dev, info.st_ino) == self.identity, 'INTERRUPTED')
            self.temporary.cleanup()
            self.temporary = None
        if failure:
            raise failure
