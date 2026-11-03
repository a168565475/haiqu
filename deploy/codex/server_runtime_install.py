"""持久 Codex 运行桥安装器；inspect 只读，prepare/install 必须单独执行。"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import tarfile
import time


ROOT = Path('/opt/haiqu-erp/ai-verification')
WORK = ROOT / 'runtime-local-erp'
TASK = 'production_task_ai_local_erp_runtime_20261103'
SCOPE = 'runtime-local-erp'
NAME = 'haiqu-erp-codex-local-erp'
IMAGE = 'haiqu-erp-codex-runtime:0.165.0-local-erp'
CODEX = 'haiqu-erp-codex-verify:0.165.0-u1'
CODEX_ID = 'sha256:4685ec10826ce9a3c46056f85e6b1d5bc55da0e569efc2051f652d193f0556a8'
PYTHON = 'public.ecr.aws/docker/library/python:3.13-slim'
PYTHON_ID = 'sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1'
PROXY = 'haiqu-erp-codex-u1-proxy'
NETWORK = 'haiqu-erp-codex-u1-internal'
AUTH = ROOT / 'state/codex'
LOCK = ROOT / 'state/login.lock'
SOCKET = WORK / 'socket/runtime.sock'
FILES = {'src/codex_runtime/' + name for name in (
    '__init__.py', '__main__.py', 'config.toml', 'Dockerfile', 'protocol.py', 'README.md',
    'server.py', 'service.py', 'parsing.py', 'schemas/discovery.json', 'schemas/extraction.json',
    'tests/test_protocol.py', 'tests/test_server.py', 'tests/test_service.py', 'tests/test_parsing.py',
)} | {'src/backend/apps/production_task_imports/' + name for name in (
    'validation.py', 'schemas/discovery.json', 'schemas/extraction.json',
)}


class InstallError(Exception):
    pass


def require(value, code):
    if not value:
        raise InstallError(code)


def command(args, timeout=45, env=None):
    result = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    require(result.returncode == 0, 'COMMAND_FAILED')
    require(len(result.stdout) <= 4 * 1024 * 1024, 'OUTPUT_LIMIT')
    return result.stdout


def inspect(kind, name):
    return json.loads(command(['docker', kind, 'inspect', name]))[0]


def absent(kind, name):
    result = subprocess.run(['docker', kind, 'inspect', name], capture_output=True, timeout=30)
    return result.returncode == 1 and b'No such ' in result.stderr


def metadata(path, kind, uid, mode):
    value = path.lstat()
    require(path.resolve() == path and kind(value.st_mode) and value.st_uid == uid
            and stat.S_IMODE(value.st_mode) == mode, 'PATH_OWNER_MODE')
    require(kind is not stat.S_ISREG or value.st_nlink == 1, 'FILE_HARDLINK')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)


def baseline():
    require(os.geteuid() == 0 and ROOT.resolve() == ROOT, 'ROOT_REQUIRED')
    metadata(ROOT / 'owner.json', stat.S_ISREG, 0, 0o600)
    owner = json.loads((ROOT / 'owner.json').read_text())
    require(owner.get('task') == 'production_task_ai_unit01_20261102'
            and owner.get('scope') == 'offline-unit01', 'PARENT_OWNER')
    for name, expected in ((CODEX, CODEX_ID), (PYTHON, PYTHON_ID)):
        image = inspect('image', name)
        require(image['Id'] == expected and image['Os'] == 'linux' and image['Architecture'] == 'amd64', 'BASE_IMAGE_CHANGED')
    network, proxy = inspect('network', NETWORK), inspect('container', PROXY)
    require(network['Internal'] is True and not network['EnableIPv6']
            and network['Options'].get('com.docker.network.bridge.gateway_mode_ipv4') == 'isolated'
            and network['Labels'].get('haiqu.task') == 'production_task_ai_unit01_20261102', 'NETWORK_CHANGED')
    require(proxy['State']['Running'] and proxy['Config']['Labels'].get('haiqu.task') == 'production_task_ai_unit01_20261102'
            and proxy['NetworkSettings']['Networks'][NETWORK]['NetworkID'] == network['Id']
            and proxy['NetworkSettings']['Networks'][NETWORK]['IPAddress'] == '10.253.0.2', 'PROXY_CHANGED')
    require(set(network['Containers']) == {proxy['Id']}, 'NETWORK_HAS_ANOTHER_RUNTIME')
    require(set(command(['docker', 'ps', '--filter', 'name=haiqu-erp-codex', '--format', '{{.Names}}']).decode().splitlines()) == {PROXY},
            'ANOTHER_CODEX_RUNNING')
    require(absent('container', NAME), 'TARGET_CONTAINER_EXISTS')
    metadata(AUTH, stat.S_ISDIR, 10001, 0o700)
    auth_present = os.path.lexists(AUTH / 'auth.json')
    if auth_present:
        metadata(AUTH / 'auth.json', stat.S_ISREG, 10001, 0o600)
    lock = LOCK.lstat()
    require(lock.st_uid in (0, 10001) and lock.st_gid == lock.st_uid, 'LOGIN_LOCK_OWNER')
    metadata(LOCK, stat.S_ISREG, lock.st_uid, 0o600)
    return {'codex_version': '0.165.0', 'codex_image': CODEX, 'codex_image_id': CODEX_ID,
            'python_image_id': PYTHON_ID, 'runtime_image': IMAGE, 'runtime_container': NAME,
            'runtime_uid': 10001, 'auth_uid': 10001, 'auth_mode': '0700', 'auth_file_present': auth_present,
            'login_lock_uid': lock.st_uid, 'login_lock_mode': '0600',
            'proxy_container_id': proxy['Id'], 'network_id': network['Id'], 'network_internal': True,
            'proxy_restart_policy': proxy['HostConfig']['RestartPolicy']['Name'],
            'network_task_label': 'production_task_ai_unit01_20261102', 'socket': str(SOCKET),
            'published_ports': 0, 'persistent_resources': True}


def lock_open():
    current = LOCK.lstat()
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = os.fstat(fd)
        require((held.st_dev, held.st_ino) == (current.st_dev, current.st_ino), 'LOCK_INODE_CHANGED')
    except Exception:
        os.close(fd)
        raise
    return fd, current


def prepare(bundle_hash):
    snapshot = baseline()
    fd, _ = lock_open()
    try:
        require(not os.path.lexists(WORK) and absent('image', IMAGE), 'INSTALL_TARGET_EXISTS')
        WORK.mkdir(mode=0o700)
        save(WORK / 'owner.json', {'task': TASK, 'scope': SCOPE, 'bundle_sha256': bundle_hash,
                                 'retention': 'PERSISTENT_FUNCTIONAL_RUNTIME_NOT_ACCEPTANCE_TEMP'})
        (WORK / 'incoming').mkdir(mode=0o700)
    finally:
        os.close(fd)
    return {'task': TASK, 'scope': SCOPE, 'status': 'PREPARED', 'bundle_sha256': bundle_hash, **snapshot}


def extract(bundle_hash):
    metadata(WORK, stat.S_ISDIR, 0, 0o700)
    metadata(WORK / 'owner.json', stat.S_ISREG, 0, 0o600)
    require(json.loads((WORK / 'owner.json').read_text()) == {
        'task': TASK, 'scope': SCOPE, 'bundle_sha256': bundle_hash,
        'retention': 'PERSISTENT_FUNCTIONAL_RUNTIME_NOT_ACCEPTANCE_TEMP'}, 'INSTALL_OWNER')
    require({item.name for item in WORK.iterdir()} == {'owner.json', 'incoming'}, 'INSTALL_NOT_FRESH')
    metadata(WORK / 'incoming', stat.S_ISDIR, 0, 0o700)
    archive_path = WORK / 'incoming/runtime.tar'
    require({item.name for item in archive_path.parent.iterdir()} == {'runtime.tar'}, 'INCOMING_FILES')
    value = archive_path.lstat()
    require(archive_path.resolve() == archive_path and stat.S_ISREG(value.st_mode) and value.st_uid == 0
            and value.st_nlink == 1 and 0 < value.st_size <= 512 * 1024, 'BUNDLE_BOUNDARY')
    raw = archive_path.read_bytes()
    require(digest(raw) == bundle_hash, 'BUNDLE_HASH')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        require(len(members) == len(FILES) + 1 and {item.name for item in members} == FILES | {'source_manifest.json'}
                and all(item.isfile() and 0 < item.size < 200000 for item in members), 'ARCHIVE_BOUNDARY')
        content = {item.name: archive.extractfile(item).read() for item in members}
    manifest = json.loads(content['source_manifest.json'])
    require(manifest.get('task') == TASK and manifest.get('scope') == SCOPE
            and set(manifest.get('files', {})) == FILES, 'MANIFEST_BOUNDARY')
    for name in FILES:
        require(manifest['files'][name] == {'size': len(content[name]), 'sha256': digest(content[name])}, 'SOURCE_HASH')
    for schema in ('discovery.json', 'extraction.json'):
        require(content['src/codex_runtime/schemas/' + schema] == content['src/backend/apps/production_task_imports/schemas/' + schema], 'SCHEMA_DRIFT')
    source = WORK / 'source'
    source.mkdir(mode=0o700)
    for name, data in content.items():
        target = source / name
        require(target.resolve().is_relative_to(source), 'SOURCE_PATH')
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        for directory in target.parents:
            if directory == source:
                break
            directory.chmod(0o755)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644 if name in FILES else 0o600)
        os.fchmod(fd, 0o644 if name in FILES else 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    # tar 是已验证的传输副本，源码及清单是持久运行资料。
    require(digest(archive_path.read_bytes()) == bundle_hash, 'BUNDLE_CHANGED')
    archive_path.unlink()
    archive_path.parent.rmdir()
    return manifest


def verify_container(container, image_id, network_id, bundle_hash):
    host, config = container['HostConfig'], container['Config']
    require(container['Image'] == image_id and config['Image'] == IMAGE and config['User'] == '10001:10001'
            and config['Labels'].get('task') == TASK and config['Labels'].get('scope') == SCOPE
            and config['Labels'].get('bundle_sha256') == bundle_hash, 'CONTAINER_IDENTITY')
    require(host['ReadonlyRootfs'] and not host['Privileged'] and host['CapDrop'] == ['ALL']
            and 'no-new-privileges' in host['SecurityOpt'] and host['LogConfig']['Type'] == 'none'
            and host['PidsLimit'] == 64 and host['Memory'] == 768 * 1024**2 and host['NanoCpus'] == 10**9
            and not host['PortBindings'] and host['NetworkMode'] == NETWORK and host['Init'] is True
            and host['RestartPolicy']['Name'] == 'unless-stopped' and config['StopTimeout'] == 115, 'CONTAINER_ISOLATION')
    networks = container['NetworkSettings']['Networks']
    require(set(networks) == {NETWORK} and networks[NETWORK]['NetworkID'] == network_id, 'RUNTIME_NETWORK')
    mounts = {item['Destination']: item for item in container['Mounts'] if item['Type'] != 'tmpfs'}
    expected = {'/state/codex': AUTH, '/state/login.lock': LOCK, '/run/haiqu-codex': SOCKET.parent}
    require(set(mounts) == set(expected) and all(mounts[key]['Type'] == 'bind'
            and mounts[key]['Source'] == str(value) and mounts[key]['RW'] for key, value in expected.items()), 'MOUNT_BOUNDARY')
    env = dict(item.split('=', 1) for item in config['Env'])
    require(env['HTTP_PROXY'] == env['HTTPS_PROXY'] == 'http://10.253.0.2:18080'
            and env['NO_PROXY'] == 'localhost,127.0.0.1'
            and not any(re.search(r'POSTGRES|DATABASE|REDIS|DJANGO|SECRET|TOKEN|PASSWORD|API_KEY', key) for key in env), 'ENV_BOUNDARY')
    require(set(host['Tmpfs']) == {'/tmp', '/work/current'}, 'TMPFS_BOUNDARY')


def status():
    # 只读取运行桥缓存；不会刷新账号、登录、联网或调用模型。
    payload = b'{"method":"status","params":{}}'
    def receive(connection, length):
        result = bytearray()
        while len(result) < length:
            part = connection.recv(length - len(result))
            require(part, 'SOCKET_EOF')
            result.extend(part)
        return bytes(result)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(SOCKET))
        connection.sendall(struct.pack('!I', len(payload)) + payload)
        length = struct.unpack('!I', receive(connection, 4))[0]
        require(0 < length <= 16 * 1024 * 1024, 'SOCKET_FRAME')
        result = json.loads(receive(connection, length))
        require(result.get('ok') is True and connection.recv(1) == b'', 'RUNTIME_STATUS_FAILED')
        return result['data']


def install(bundle_hash):
    snapshot = baseline()
    require(snapshot['proxy_restart_policy'] in {'no', 'unless-stopped'}, 'PROXY_RESTART_POLICY_UNEXPECTED')
    require(absent('image', IMAGE), 'TARGET_IMAGE_EXISTS')
    # finally 只能把回执写入本任务已登记目录，不能给来源不明目录补归属文件。
    metadata(WORK, stat.S_ISDIR, 0, 0o700)
    metadata(WORK / 'owner.json', stat.S_ISREG, 0, 0o600)
    require(json.loads((WORK / 'owner.json').read_text()) == {
        'task': TASK, 'scope': SCOPE, 'bundle_sha256': bundle_hash,
        'retention': 'PERSISTENT_FUNCTIONAL_RUNTIME_NOT_ACCEPTANCE_TEMP'}, 'INSTALL_OWNER')
    receipt = {'task': TASK, 'scope': SCOPE, 'status': 'FAIL', 'bundle_sha256': bundle_hash,
               'retention': 'PERSISTENT_FUNCTIONAL_RUNTIME_NOT_ACCEPTANCE_TEMP', 'cleanup_errors': [],
               'proxy_restart_policy_before': snapshot['proxy_restart_policy'],
               'proxy_restart_policy_after': snapshot['proxy_restart_policy'], **snapshot}
    fd = original_lock = container_id = None
    lock_changed = installed = False
    try:
        receipt['stage'] = 'extract'
        manifest = extract(bundle_hash)
        receipt['source_files'] = manifest['files']
        receipt['stage'] = 'offline_build'
        command(['docker', 'build', '--pull=false', '--network=none', '--label', 'task=' + TASK,
                 '--label', 'scope=' + SCOPE, '--label', 'bundle_sha256=' + bundle_hash,
                 '--build-arg', 'CODEX_IMAGE=' + CODEX, '-f', str(WORK / 'source/src/codex_runtime/Dockerfile'),
                 '-t', IMAGE, str(WORK / 'source')], timeout=480, env={**os.environ, 'DOCKER_BUILDKIT': '0'})
        image = inspect('image', IMAGE)
        require(image['Config']['Labels'].get('bundle_sha256') == bundle_hash
                and image['Config']['User'] == '10001:10001', 'BUILT_IMAGE_BINDING')
        receipt['runtime_image_id'] = image['Id']
        receipt['stage'] = 'exclusive_lock_and_create'
        current = baseline()
        require(current['network_id'] == snapshot['network_id'] and current['proxy_container_id'] == snapshot['proxy_container_id'], 'BASELINE_DRIFT')
        fd, original_lock = lock_open()
        os.fchown(fd, 10001, 10001)
        lock_changed = True
        SOCKET.parent.mkdir(mode=0o770)
        os.chown(SOCKET.parent, 10001, 10001)
        os.chmod(SOCKET.parent, 0o770)
        args = ['docker', 'create', '--name', NAME, '--label', 'task=' + TASK, '--label', 'scope=' + SCOPE,
                '--label', 'bundle_sha256=' + bundle_hash, '--restart', 'unless-stopped', '--stop-timeout', '115', '--init', '--user', '10001:10001',
                '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
                '--memory', '768m', '--cpus', '1', '--log-driver', 'none', '--network', NETWORK,
                '--env', 'HTTP_PROXY=http://10.253.0.2:18080', '--env', 'HTTPS_PROXY=http://10.253.0.2:18080',
                '--env', 'NO_PROXY=localhost,127.0.0.1',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=134217728,uid=10001,gid=10001,mode=700',
                '--tmpfs', '/work/current:rw,noexec,nosuid,nodev,size=16777216,uid=10001,gid=10001,mode=700']
        for source, target in ((AUTH, '/state/codex'), (LOCK, '/state/login.lock'), (SOCKET.parent, '/run/haiqu-codex')):
            args += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + target]
        receipt['container_creation_state'] = 'UNKNOWN_UNTIL_ID_CONFIRMED'
        container_id = command(args + [IMAGE]).decode().strip()
        require(re.fullmatch('[a-f0-9]{64}', container_id), 'CONTAINER_ID_INVALID')
        receipt['container_creation_state'] = 'ID_CONFIRMED'
        receipt['container_id'] = container_id
        fcntl.flock(fd, fcntl.LOCK_UN)
        receipt['stage'] = 'start_local_socket'
        command(['docker', 'start', container_id])
        for _ in range(60):
            running = inspect('container', container_id)
            require(running['State']['Running'] and running['RestartCount'] == 0, 'RUNTIME_START_FAILED')
            if SOCKET.exists():
                break
            time.sleep(0.5)
        metadata(SOCKET, stat.S_ISSOCK, 10001, 0o660)
        verify_container(inspect('container', container_id), image['Id'], snapshot['network_id'], bundle_hash)
        require(set(inspect('network', NETWORK)['Containers']) == {snapshot['proxy_container_id'], container_id}, 'NETWORK_MEMBER_DRIFT')
        cache = status()
        require(cache.get('cli_version') == '0.165.0' and cache.get('operation') is None, 'CACHE_STATUS_INVALID')
        held_path = metadata(LOCK, stat.S_ISREG, 10001, 0o600)
        require((held_path.st_dev, held_path.st_ino) == (original_lock.st_dev, original_lock.st_ino), 'LOCK_PATH_INODE_CHANGED')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            receipt['runtime_holds_same_login_lock'] = True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            raise InstallError('RUNTIME_LOCK_NOT_HELD')
        receipt['stage'] = 'persistent_proxy_restart_policy'
        proxy_before = inspect('container', PROXY)
        require(proxy_before['Id'] == snapshot['proxy_container_id'] and proxy_before['State']['Running']
                and proxy_before['Config']['Labels'].get('haiqu.task') == 'production_task_ai_unit01_20261102'
                and proxy_before['HostConfig']['RestartPolicy']['Name'] == snapshot['proxy_restart_policy'], 'PROXY_BEFORE_UPDATE_CHANGED')
        # 只调整已绑定专属代理的重启策略；不重启、不更改代理配置或网络。
        if snapshot['proxy_restart_policy'] == 'no':
            command(['docker', 'update', '--restart', 'unless-stopped', proxy_before['Id']])
        proxy_after = inspect('container', PROXY)
        receipt['proxy_restart_policy_after'] = proxy_after['HostConfig']['RestartPolicy']['Name']
        before_host = {key: value for key, value in proxy_before['HostConfig'].items() if key != 'RestartPolicy'}
        after_host = {key: value for key, value in proxy_after['HostConfig'].items() if key != 'RestartPolicy'}
        require(proxy_after['Id'] == proxy_before['Id'] and proxy_after['Config'] == proxy_before['Config']
                and proxy_after['State']['Running'] and proxy_after['State']['StartedAt'] == proxy_before['State']['StartedAt']
                and proxy_after['NetworkSettings'] == proxy_before['NetworkSettings'] and before_host == after_host
                and proxy_after['HostConfig']['RestartPolicy'] == {'Name': 'unless-stopped', 'MaximumRetryCount': 0}, 'PROXY_UPDATE_SCOPE_CHANGED')
        receipt['proxy_not_restarted_and_config_network_unchanged'] = True
        receipt.update({'status': 'INSTALLED', 'stage': 'persistent_running', 'boot_id': cache['boot_id'],
                        'login_lock_uid': 10001, 'no_model_or_login_called': True,
                        'restart_policy': 'unless-stopped', 'deadline': None,
                        'retained_new_resources': [str(WORK), str(WORK / 'source'), str(SOCKET.parent), NAME, IMAGE],
                        'retained_existing_resources': [str(AUTH), str(LOCK), PROXY, NETWORK]})
        installed = True
    except Exception as error:
        receipt['error_code'] = str(error) if isinstance(error, InstallError) else type(error).__name__
    finally:
        if not installed and container_id:
            try:
                container = inspect('container', NAME)
                require(container['Id'] == container_id and container['Config']['Labels'].get('bundle_sha256') == bundle_hash
                        and container['Config']['Labels'].get('task') == TASK, 'FAILED_CONTAINER_OWNER')
                command(['docker', 'stop', '--time', '115', container_id], timeout=125)
                command(['docker', 'rm', container_id])
                require(absent('container', NAME), 'FAILED_CONTAINER_REMAINS')
            except Exception as error:
                receipt['cleanup_errors'].append({'stage': 'failed_container', 'type': type(error).__name__})
        if fd is not None:
            try:
                if not installed and lock_changed:
                    require(absent('container', NAME), 'CANNOT_RESTORE_OCCUPIED_LOCK')
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    require((os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (original_lock.st_dev, original_lock.st_ino), 'LOCK_INODE_CHANGED')
                    current_lock = metadata(LOCK, stat.S_ISREG, 10001, 0o600)
                    require((current_lock.st_dev, current_lock.st_ino) == (original_lock.st_dev, original_lock.st_ino), 'LOCK_PATH_INODE_CHANGED')
                    os.fchown(fd, original_lock.st_uid, original_lock.st_gid)
                    receipt['failed_install_lock_restored'] = True
            except Exception as error:
                receipt['cleanup_errors'].append({'stage': 'login_lock_restore', 'type': type(error).__name__})
            finally:
                os.close(fd)
        # 安装失败保留已核实源码/镜像/归属回执，禁止猜测式递归清理或自动重装。
        if WORK.is_dir() and not (WORK / 'install_receipt.json').exists():
            save(WORK / 'install_receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=('inspect', 'prepare', 'install'), required=True)
    parser.add_argument('--bundle-sha256')
    args = parser.parse_args()
    if args.action == 'inspect':
        require(args.bundle_sha256 is None, 'INSPECT_ARGUMENTS')
        result = baseline()
        fd, _ = lock_open()
        os.close(fd)
        result.update({'task': TASK, 'scope': SCOPE, 'status': 'PASS', 'login_lock_available': True,
                       'work_exists': os.path.lexists(WORK), 'target_image_absent': absent('image', IMAGE)})
    else:
        require(args.bundle_sha256 and re.fullmatch('[a-f0-9]{64}', args.bundle_sha256), 'BUNDLE_HASH_REQUIRED')
        result = prepare(args.bundle_sha256) if args.action == 'prepare' else install(args.bundle_sha256)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] in {'PASS', 'PREPARED', 'INSTALLED'} else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'task': TASK, 'status': 'FAIL', 'error_code': str(error) if isinstance(error, InstallError) else type(error).__name__}), flush=True)
        raise SystemExit(1)
