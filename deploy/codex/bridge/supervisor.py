"""本机ERP专用SSH桥的Windows守护进程；凭据仅由既有DPAPI askpass读取。"""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

STATE = Path('E:/CodexData/.codex/private/haiqu-erp-local-codex')
HELPER = Path('E:/CodexData/.codex/skills/bushu/scripts/ssh.py')
TASK = 'haiqu-erp-local-codex'
CONTAINER = 'haiqu-codex-worker'
STOP = threading.Event()
CONFIGURATION_ERRORS = frozenset({
    'REMOTE_ROOT', 'REMOTE_OWNER', 'SOCKET_BOUNDARY', 'SOCKET_CHANGED',
    'LOCAL_ROOT', 'LOCAL_LOCK_BOUNDARY',
})


def save_status(state, **fields):
    value = {'task': TASK, 'pid': os.getpid(), 'state': state,
             'updated_at': datetime.now(timezone.utc).isoformat(), **fields}
    temporary = STATE / 'status.tmp'
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(STATE / 'status.json')


def stopping():
    return STOP.is_set() or (STATE / 'stop.request').exists()


class Bridge:
    def __init__(self, commands, environment):
        self.processes = {}
        self.threads = []
        self.closed = threading.Event()
        self.failure = threading.Event()
        self.auth_failure = threading.Event()
        options = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.processes['remote'] = subprocess.Popen(commands['remote'], env=environment, **options)
            self.processes['local'] = subprocess.Popen(commands['local'], **options)
            for source, target in (('remote', 'local'), ('local', 'remote')):
                self.start_thread(self.pump, self.processes[source].stdout, self.processes[target].stdin)
            for name, process in self.processes.items():
                self.start_thread(self.drain, name, process.stderr)
        except Exception:
            self.close()
            raise

    def start_thread(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def pump(self, source, destination):
        try:
            while not self.closed.is_set():
                data = source.read(65536)
                if not data:
                    break
                remaining = memoryview(data)
                while remaining and not self.closed.is_set():
                    written = destination.write(remaining)
                    if not written:
                        raise BrokenPipeError()
                    remaining = remaining[written:]
        except (OSError, ValueError):
            self.failure.set()
        finally:
            self.failure.set()
            try:
                destination.close()
            except (OSError, ValueError):
                self.failure.set()

    def drain(self, name, stream):
        tail = b''
        try:
            while True:
                data = stream.read(4096)
                if not data:
                    return
                tail = (tail + data)[-8192:]
                if name == 'remote' and any(marker in tail.lower() for marker in (
                    b'permission denied', b'host key verification failed',
                    b'remote host identification has changed', b'askpass',
                )):
                    self.auth_failure.set()
                for line in tail.splitlines():
                    try:
                        event = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue  # SSH 自身消息不是桥接的结构化诊断。
                    if (isinstance(event, dict) and event.get('event') == 'codex_bridge_exit'
                            and isinstance(event.get('code'), str) and event['code'] in CONFIGURATION_ERRORS):
                        self.auth_failure.set()
                # 原始SSH/运行消息只在有界内存中分类；不写日志或状态文件。
        except (OSError, ValueError):
            self.failure.set()

    def running(self):
        return not self.failure.is_set() and all(p.poll() is None for p in self.processes.values())

    def close(self):
        self.closed.set()
        # 关闭本对象拥有的CLI/SSH子进程会关闭stdin；Linux桥据EOF退出并清理socket。
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=2)
        for process in self.processes.values():
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    self.failure.set()


def commands():
    try:
        return configured_commands()
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        # profile、helper、构建清单或可信主机文件缺失也是固定配置错误。
        raise RuntimeError('BRIDGE_CONFIGURATION_INVALID') from None


def configured_commands():
    spec = importlib.util.spec_from_file_location('_haiqu_bushu_ssh', HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    profile = helper.load_profile(helper.DEFAULT_PROFILE)
    helper.validate_helper(profile)
    if profile['host'] != '139.9.195.119' or profile['username'] != 'root' or profile['port'] != 22:
        raise ValueError('SSH_PROFILE_TARGET_CHANGED')
    environment = dict(os.environ, SSH_ASKPASS=profile['askpass_exe'], SSH_ASKPASS_REQUIRE='force',
                       DISPLAY='haiqu-erp-local-codex', HAIQU_SSH_CREDENTIAL_FILE=profile['credential_file'])
    source = base64.b64encode(Path(__file__).with_name('transport.py').read_bytes()).decode('ascii')
    loader = "import base64,sys;source=base64.b64decode(sys.argv.pop(1),validate=True);exec(compile(source,'codex_transport.py','exec'))"
    remote_command = ' '.join(shlex.quote(value) for value in ('python3', '-I', '-B', '-u', '-c', loader, source, 'remote'))
    remote = [helper.openssh_executable('ssh'), '-F', 'NUL', '-T',
              '-o', 'StrictHostKeyChecking=yes', '-o', 'NumberOfPasswordPrompts=1',
              '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password',
              '-o', 'BatchMode=no', '-o', 'ConnectTimeout=15',
              '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
              '-o', 'UserKnownHostsFile=' + profile['known_hosts_file'], '-p', '22',
              '--', 'root@139.9.195.119', remote_command]
    local = ['docker', 'exec', '--user', '10001:10001', '-i', CONTAINER,
             'python', '-I', '-B', '-u', '/opt/haiqu-codex-bridge/transport.py', 'local']
    return {'remote': remote, 'local': local}, environment


def verify_container():
    result = subprocess.run(['docker', 'inspect', '--format',
        '{{.State.Running}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}',
        CONTAINER], capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0 and result.stdout.strip() == b'true|haiqu-erp|codex-worker'


def run():
    if not STATE.is_dir() or STATE.is_symlink():
        raise RuntimeError('STATE_DIRECTORY_REQUIRED')
    lock = (STATE / 'supervisor.lock').open('a+b')
    try:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return  # 已运行，不启动第二个SSH或本机socket。
        stop_file = STATE / 'stop.request'
        if stop_file.exists():
            stop_file.unlink()
        retry = 0
        while not stopping():
            bridge = None
            fatal_auth = False
            try:
                if not verify_container():
                    save_status('WAITING_FOR_WORKER')
                else:
                    cmd, environment = commands()
                    bridge = Bridge(cmd, environment)
                    started = time.monotonic()
                    while bridge.running() and not stopping():
                        save_status('BRIDGE_RUNNING', uptime_seconds=int(time.monotonic() - started))
                        STOP.wait(2)
                    fatal_auth = bridge.auth_failure.is_set()
                    if time.monotonic() - started >= 60:
                        retry = 0
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                save_status('ERROR', error_type=type(error).__name__)
                # 配置/凭据校验错误不自动反复尝试认证。
                fatal_auth = isinstance(error, (ValueError, RuntimeError))
            finally:
                if bridge is not None:
                    bridge.close()
                    fatal_auth = fatal_auth or bridge.auth_failure.is_set()
            if fatal_auth:
                save_status('AUTH_OR_CONFIGURATION_ERROR')
                return
            if not stopping():
                retry += 1
                delay = min(60, 2 ** min(retry, 6))
                save_status('RECONNECTING', retry_delay_seconds=delay)
                for _ in range(delay):
                    if stopping():
                        break
                    STOP.wait(1)
        save_status('STOPPED')
    finally:
        lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'status', 'stop'])
    action = parser.parse_args().action
    if action == 'status':
        path = STATE / 'status.json'
        value = json.loads(path.read_text()) if path.exists() else {'task': TASK, 'state': 'NOT_STARTED'}
        if value.get('state') in {'BRIDGE_RUNNING', 'RECONNECTING', 'WAITING_FOR_WORKER'}:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(value['updated_at'])).total_seconds()
            if age > 75:
                value['state'] = 'STALE'
        print(json.dumps(value))
    elif action == 'stop':
        if STATE.is_dir():
            (STATE / 'stop.request').write_text(TASK, encoding='ascii')
        print(json.dumps({'task': TASK, 'state': 'STOP_REQUESTED'}))
    else:
        try:
            run()
        except Exception as error:
            save_status('ERROR', error_type=type(error).__name__)
            raise SystemExit(1)
