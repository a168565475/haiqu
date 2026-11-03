"""SSH stdin 与 ERP 私有 Unix socket 之间的有界帧转发；不开放 TCP 端口。"""
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import stat
import struct
import sys
import time

MAX_FRAME = 16 * 1024 * 1024
LOCAL_SOCKET = Path('/run/haiqu-codex/runtime.sock')
REMOTE_ROOT = Path('/opt/haiqu-erp/ai-verification/runtime-local-erp')
REMOTE_SOCKET = REMOTE_ROOT / 'socket/runtime.sock'
TASK = 'production_task_ai_local_erp_runtime_20261103'
CONFIGURATION_ERRORS = frozenset({
    'REMOTE_ROOT', 'REMOTE_OWNER', 'SOCKET_BOUNDARY', 'SOCKET_CHANGED',
    'LOCAL_ROOT', 'LOCAL_LOCK_BOUNDARY',
})


def require(value, code):
    if not value:
        raise RuntimeError(code)


def exact(stream, count, deadline):
    data = bytearray()
    while len(data) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise TimeoutError('FRAME_TIMEOUT')
        chunk = os.read(stream.fileno(), count - len(data))
        if not chunk:
            raise EOFError('FRAME_EOF')
        data.extend(chunk)
    return bytes(data)


def frame(stream, *, idle=False):
    # 空闲 stdin 可长期等待；收到第一个字节后整帧限时，避免半帧拖住连接。
    first = os.read(stream.fileno(), 1) if idle else exact(stream, 1, time.monotonic() + 5)
    if not first:
        raise EOFError('FRAME_EOF')
    deadline = time.monotonic() + 5
    header = first + exact(stream, 3, deadline)
    count = struct.unpack('!I', header)[0]
    require(0 < count <= MAX_FRAME, 'FRAME_LIMIT')
    return header + exact(stream, count, deadline)


def send(stream, data):
    deadline = time.monotonic() + 5
    view = memoryview(data)
    while view:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [stream], [], remaining)[1]:
            raise TimeoutError('WRITE_TIMEOUT')
        # 管道每次最多写4KiB，不能在一次大写入里绕过总截止时间。
        count = os.write(stream.fileno(), view[:4096])
        require(count > 0, 'WRITE_CLOSED')
        view = view[count:]


def check_socket(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise  # runtime 尚未创建 socket 时允许宿主退避重连。
    except OSError:
        raise RuntimeError('SOCKET_BOUNDARY') from None
    require(path.resolve() == path and stat.S_ISSOCK(info.st_mode)
            and info.st_uid == 10001 and stat.S_IMODE(info.st_mode) == 0o660,
            'SOCKET_BOUNDARY')
    return info.st_dev, info.st_ino


def remote():
    try:
        info = REMOTE_ROOT.lstat()
    except OSError:
        raise RuntimeError('REMOTE_ROOT') from None
    require(REMOTE_ROOT.resolve() == REMOTE_ROOT and stat.S_ISDIR(info.st_mode)
            and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700, 'REMOTE_ROOT')
    owner = REMOTE_ROOT / 'owner.json'
    try:
        info = owner.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and owner.resolve() == owner
                and info.st_size <= 4096, 'REMOTE_OWNER')
        value = json.loads(owner.read_bytes())
    except (OSError, ValueError):
        raise RuntimeError('REMOTE_OWNER') from None
    require(isinstance(value, dict) and value.get('task') == TASK
            and value.get('scope') == 'runtime-local-erp', 'REMOTE_OWNER')
    check_socket(REMOTE_SOCKET)
    while True:
        try:
            request = frame(sys.stdin.buffer, idle=True)
        except EOFError:
            return
        check_socket(REMOTE_SOCKET)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(REMOTE_SOCKET))
            send(client, request)
            response = frame(client)
        send(sys.stdout.buffer, response)


def local():
    parent = LOCAL_SOCKET.parent
    info = parent.lstat()
    require(os.geteuid() == 10001 and parent.resolve() == parent
            and stat.S_ISDIR(info.st_mode) and info.st_uid == 10001
            and stat.S_IMODE(info.st_mode) == 0o750, 'LOCAL_ROOT')
    lock_path = parent / 'bridge.lock'
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise RuntimeError('LOCAL_LOCK_BOUNDARY') from None
    # 锁文件保留同一个 inode；退出仅释放 flock，不删除后重建另一把锁。
    with os.fdopen(descriptor, 'rb', buffering=0) as lock:
        info = os.fstat(lock.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (10001, 10001, 0o600),
                'LOCAL_LOCK_BOUNDARY')
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('LOCAL_LOCK_BUSY') from None
        current = lock_path.lstat()
        require(lock_path.resolve() == lock_path
                and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'LOCAL_LOCK_BOUNDARY')
        local_locked()


def local_locked():
    if os.path.lexists(LOCAL_SOCKET):
        identity = check_socket(LOCAL_SOCKET)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as previous:
            previous.settimeout(1)
            try:
                previous.connect(str(LOCAL_SOCKET))
            except ConnectionRefusedError:
                require(check_socket(LOCAL_SOCKET) == identity, 'SOCKET_CHANGED')
                LOCAL_SOCKET.unlink()
            else:
                raise RuntimeError('SOCKET_IN_USE')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        server.bind(str(LOCAL_SOCKET))
        LOCAL_SOCKET.chmod(0o660)
        identity = check_socket(LOCAL_SOCKET)
        server.listen(16)
        # EOF 必须能唤醒空闲监听；宿主/SSH退出后不留下占用旧socket的exec。
        while True:
            readable = select.select([server, sys.stdin.buffer], [], [])[0]
            if sys.stdin.buffer in readable:
                require(not os.read(sys.stdin.fileno(), 1), 'UNEXPECTED_RESPONSE')
                return
            client, _ = server.accept()
            with client:
                try:
                    request = frame(client)
                except (EOFError, ConnectionError, TimeoutError):
                    continue  # 尚未发送请求，下一客户端不会串帧。
                send(sys.stdout.buffer, request)
                # 已发请求的管道失败必须退出整个连接，禁止把旧响应送给下一请求。
                response = frame(sys.stdin.buffer)
                try:
                    send(client, response)
                except (ConnectionError, TimeoutError):
                    continue  # 旧响应已完整消费，可安全接收下一请求。
    finally:
        server.close()
        if identity is not None:
            require(check_socket(LOCAL_SOCKET) == identity, 'SOCKET_CHANGED')
            LOCAL_SOCKET.unlink()


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in {'local', 'remote'}, 'INVALID_MODE')
        (local if sys.argv[1] == 'local' else remote)()
    except Exception as error:
        # 仅固定边界码可触发宿主停止重试；不输出文件路径、原始异常或业务内容。
        code = str(error) if isinstance(error, RuntimeError) and str(error) in CONFIGURATION_ERRORS else 'TRANSPORT_ERROR'
        print(json.dumps({'event': 'codex_bridge_exit', 'type': type(error).__name__, 'code': code}), file=sys.stderr)
        raise SystemExit(1)
