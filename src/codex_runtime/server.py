"""私有 Unix socket：4字节大端长度 + JSON，一连接一个请求。"""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import stat
import struct

from .protocol import RuntimeErrorCode, child_environment, report_error, require, strict_json
from .service import Runtime


MAX_FRAME = 16 * 1024 * 1024


def decode_request(data):
    value = strict_json(data)
    require(type(value) is dict and set(value) == {'method', 'params'}
            and type(value['method']) is str and type(value['params']) is dict, 'INVALID_REQUEST')
    return value['method'], value['params']


def encode_response(value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    require(0 < len(data) <= MAX_FRAME, 'UPSTREAM_UNAVAILABLE')
    return struct.pack('!I', len(data)) + data


async def read_frame(reader, timeout=5):
    try:
        async with asyncio.timeout(timeout):
            header = await reader.readexactly(4)
            size = struct.unpack('!I', header)[0]
            require(0 < size <= MAX_FRAME, 'INVALID_REQUEST')
            return await reader.readexactly(size)
    except (TimeoutError, asyncio.IncompleteReadError, OSError):
        raise RuntimeErrorCode('INVALID_REQUEST') from None


async def create_server(runtime, path):
    capacity = asyncio.Semaphore(16)

    async def handle(reader, writer):
        acquired = False
        try:
            try:
                require(not capacity.locked(), 'BUSY')
                await capacity.acquire()
                acquired = True
                method, params = decode_request(await read_frame(reader))
                data = await runtime.dispatch(method, params)
                response = {'ok': True, 'data': data}
            except RuntimeErrorCode as error:
                response = {'ok': False, 'error': {'code': error.code}}
            except Exception as error:
                report_error('bridge_request', error)
                response = {'ok': False, 'error': {'code': 'UPSTREAM_UNAVAILABLE'}}
            writer.write(encode_response(response))
            await asyncio.wait_for(writer.drain(), 5)
        except (RuntimeErrorCode, OSError, TimeoutError):
            # 对端关闭后不再次发送错误；连接结束不等于取消已受理操作。
            return
        finally:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 1)
            if acquired:
                capacity.release()

    require(not path.exists() and not path.is_symlink(), 'NOT_READY')
    server = await asyncio.start_unix_server(handle, path=str(path), limit=MAX_FRAME + 4)
    path.chmod(0o660)
    return server


async def verify_version():
    process = await asyncio.create_subprocess_exec('/usr/local/bin/codex', '--version',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=child_environment())
    try:
        output = await asyncio.wait_for(process.stdout.read(256), 10)
        await asyncio.wait_for(process.wait(), 5)
        require(process.returncode == 0 and output.strip() == b'codex-cli 0.165.0', 'NOT_READY')
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)


async def run_server():
    import fcntl  # 仅生产Linux启动入口使用；可移植单测不加载它。

    require(os.geteuid() == 10001, 'NOT_READY')
    socket_path = Path(os.getenv('CODEX_RUNTIME_SOCKET', '/run/haiqu-codex/runtime.sock'))
    lock_path = Path('/state/login.lock')
    auth = Path('/state/codex')
    require(socket_path.is_absolute() and socket_path.parent.resolve() == socket_path.parent, 'NOT_READY')
    info = socket_path.parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 10001 and not info.st_mode & 0o007, 'NOT_READY')
    info = auth.lstat()
    require(stat.S_ISDIR(info.st_mode) and auth.resolve() == auth and info.st_uid == 10001
            and stat.S_IMODE(info.st_mode) == 0o700, 'NOT_READY')
    info = lock_path.lstat()
    require(stat.S_ISREG(info.st_mode) and lock_path.resolve() == lock_path and info.st_uid == 10001
            and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, 'NOT_READY')
    lock = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    runtime, server, socket_identity = Runtime(), None, None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = os.fstat(lock)
        require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'NOT_READY')
        # 持锁后只处理本目录同UID旧socket；普通文件/链接/其他UID一律拒绝。
        if socket_path.exists() or socket_path.is_symlink():
            previous = socket_path.lstat()
            require(stat.S_ISSOCK(previous.st_mode) and previous.st_uid == 10001, 'NOT_READY')
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(socket_path)), 1)
            except (ConnectionRefusedError, FileNotFoundError):
                current = socket_path.lstat()
                require((current.st_dev, current.st_ino) == (previous.st_dev, previous.st_ino), 'NOT_READY')
                socket_path.unlink()
            else:
                writer.close()
                await writer.wait_closed()
                raise RuntimeErrorCode('BUSY')
        await verify_version()
        server = await create_server(runtime, socket_path)
        metadata = socket_path.lstat()
        socket_identity = metadata.st_dev, metadata.st_ino
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(name, stop.set)
        await stop.wait()
    finally:
        cleanup_failed = False
        try:
            if server:
                server.close()
                await server.wait_closed()
        except Exception as error:
            cleanup_failed = True
            report_error('socket_shutdown', error)
        try:
            await runtime.close()
        except Exception as error:
            cleanup_failed = True
            report_error('runtime_shutdown', error)
        try:
            if socket_identity and (socket_path.exists() or socket_path.is_symlink()):
                metadata = socket_path.lstat()
                require(stat.S_ISSOCK(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == socket_identity,
                        'INTERRUPTED')
                socket_path.unlink()
        except Exception as error:
            cleanup_failed = True
            report_error('socket_cleanup', error)
        finally:
            os.close(lock)
        require(not cleanup_failed, 'INTERRUPTED')


def main():
    try:
        asyncio.run(run_server())
    except Exception as error:
        # 启动/停止错误不输出环境变量、路径内容、原始RPC或堆栈。
        report_error('runtime_start_or_stop', error)
        print(json.dumps({'event': 'runtime_stopped', 'error_code': error.code
                          if isinstance(error, RuntimeErrorCode) else 'NOT_READY'}), flush=True)
        return 1
    return 0
