"""仅升级已存在的 runtime-local-erp；不操作 ERP 服务或账号文件。"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import time

from runtime_release_bundle import ReleaseError, TASK, SCOPE, MAX_BUNDLE, canonical, require, sha, validate_bundle

ROOT = Path('/opt/haiqu-erp/ai-verification')
WORK = ROOT / 'runtime-local-erp'
RELEASES = WORK / 'dxf-releases'
NAME = 'haiqu-erp-codex-local-erp'
OWNER_TASK = 'production_task_ai_local_erp_runtime_20261103'
NETWORK = 'haiqu-erp-codex-u1-internal'
PROXY = 'haiqu-erp-codex-u1-proxy'
AUTH = ROOT / 'state/codex'
LOCK = ROOT / 'state/login.lock'
SOCKET = WORK / 'socket/runtime.sock'
CODEX_IMAGE = 'haiqu-erp-codex-verify:0.165.0-u1'
CODEX_ID = 'sha256:4685ec10826ce9a3c46056f85e6b1d5bc55da0e569efc2051f652d193f0556a8'
PYTHON_IMAGE = 'public.ecr.aws/docker/library/python:3.13-slim'
PYTHON_ID = 'sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1'


def command(args, timeout=45):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(result.returncode == 0, 'COMMAND_FAILED')
    return result.stdout


def inspect(kind, name):
    return json.loads(command(['docker', kind, 'inspect', name]))[0]


def container(name):
    return inspect('container', name)


def absent(kind, name):
    result = subprocess.run(['docker', kind, 'inspect', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    return result.returncode == 1 and b'No such ' in result.stderr


def metadata(path, kind, uid, mode):
    info = path.lstat()
    require(path.resolve() == path and kind(info.st_mode) and info.st_uid == uid
            and stat.S_IMODE(info.st_mode) == mode, 'PATH_BOUNDARY')
    require(kind is not stat.S_ISREG or info.st_nlink == 1, 'FILE_HARDLINK')
    return info


def read_record(path):
    info = metadata(path, stat.S_ISREG, 0, 0o600)
    require(info.st_size <= 2 * 1024 * 1024, 'RECORD_SIZE')
    return json.loads(path.read_bytes())


def save_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def require_target_identity(value, name):
    labels = value.get('Config', {}).get('Labels') or {}
    require(name == NAME or re.fullmatch(re.escape(NAME) + r'-before-[a-f0-9]{12}', name), 'TARGET_NAME')
    require(value.get('Name') == '/' + name and re.fullmatch('[a-f0-9]{64}', value.get('Id', ''))
            and labels.get('task') == OWNER_TASK and labels.get('scope') == SCOPE
            and re.fullmatch('[a-f0-9]{64}', labels.get('bundle_sha256', '')), 'CONTAINER_IDENTITY')


def require_idle(snapshot):
    require(snapshot.get('cli_version') == '0.165.0', 'CLI_VERSION')
    operation = snapshot.get('operation')
    require(operation is None or (type(operation) is dict
            and operation.get('state') in {'SUCCEEDED', 'FAILED', 'CANCELED'}), 'OPERATION_ACTIVE')


def status():
    def receive(stream, size, deadline):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'STATUS_TIMEOUT')
            stream.settimeout(remaining)
            data = stream.recv(size - len(result))
            require(data, 'STATUS_EOF')
            result.extend(data)
        return bytes(result)
    request = b'{"method":"status","params":{}}'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        deadline = time.monotonic() + 5
        stream.settimeout(5)
        stream.connect(str(SOCKET))
        stream.sendall(struct.pack('!I', len(request)) + request)
        length = struct.unpack('!I', receive(stream, 4, deadline))[0]
        require(0 < length <= 256 * 1024, 'STATUS_FRAME')
        response = json.loads(receive(stream, length, deadline))
    require(response.get('ok') is True and type(response.get('data')) is dict, 'STATUS_RESPONSE')
    return response['data']


def baseline():
    require(os.geteuid() == 0, 'ROOT_REQUIRED')
    metadata(ROOT, stat.S_ISDIR, 0, 0o700)
    owner = read_record(ROOT / 'owner.json')
    require(owner.get('task') == 'production_task_ai_unit01_20261102' and owner.get('scope') == 'offline-unit01', 'PARENT_OWNER')
    metadata(WORK, stat.S_ISDIR, 0, 0o700)
    owner = read_record(WORK / 'owner.json')
    require(owner.get('task') == OWNER_TASK and owner.get('scope') == SCOPE, 'WORK_OWNER')
    metadata(AUTH, stat.S_ISDIR, 10001, 0o700)
    lock = metadata(LOCK, stat.S_ISREG, 10001, 0o600)
    metadata(SOCKET.parent, stat.S_ISDIR, 10001, 0o770)
    metadata(SOCKET, stat.S_ISSOCK, 10001, 0o660)
    value = container(NAME)
    require_target_identity(value, NAME)
    host, config = value['HostConfig'], value['Config']
    require(value['State']['Running'] and config['User'] == '10001:10001' and host['ReadonlyRootfs']
            and not host['Privileged'] and host['CapDrop'] == ['ALL'] and 'no-new-privileges' in host['SecurityOpt']
            and host['Memory'] == 768 * 1024**2 and host['PidsLimit'] == 64 and host['NanoCpus'] == 10**9
            and not host['PortBindings'] and host['NetworkMode'] == NETWORK and host['Init'] is True
            and host['RestartPolicy']['Name'] == 'unless-stopped' and host['LogConfig']['Type'] == 'none', 'CONTAINER_ISOLATION')
    mounts = {item['Destination']: item for item in value['Mounts'] if item['Type'] != 'tmpfs'}
    expected = {'/state/codex': AUTH, '/state/login.lock': LOCK, '/run/haiqu-codex': SOCKET.parent}
    require(set(mounts) == set(expected) and all(mounts[key]['Type'] == 'bind' and mounts[key]['RW']
            and mounts[key]['Source'] == str(path) for key, path in expected.items()), 'MOUNT_BOUNDARY')
    require(set(host['Tmpfs']) == {'/tmp', '/work/current'}, 'TMPFS_BOUNDARY')
    env = dict(item.split('=', 1) for item in config['Env'])
    require(env.get('HTTP_PROXY') == env.get('HTTPS_PROXY') == 'http://10.253.0.2:18080'
            and env.get('NO_PROXY') == 'localhost,127.0.0.1'
            and not any(re.search('POSTGRES|DATABASE|REDIS|DJANGO|SECRET|TOKEN|PASSWORD|API_KEY', key) for key in env), 'ENV_BOUNDARY')
    network, proxy = inspect('network', NETWORK), container(PROXY)
    require(network['Internal'] and not network['EnableIPv6']
            and network['Options'].get('com.docker.network.bridge.gateway_mode_ipv4') == 'isolated'
            and network['Labels'].get('haiqu.task') == 'production_task_ai_unit01_20261102'
            and set(network['Containers']) == {value['Id'], proxy['Id']} and proxy['State']['Running']
            and proxy['Config']['Labels'].get('haiqu.task') == 'production_task_ai_unit01_20261102', 'NETWORK_BOUNDARY')
    for name, expected_id in ((CODEX_IMAGE, CODEX_ID), (PYTHON_IMAGE, PYTHON_ID)):
        image = inspect('image', name)
        require(image['Id'] == expected_id and image['Os'] == 'linux' and image['Architecture'] == 'amd64', 'BASE_IMAGE_CHANGED')
    cache = status()
    require_idle(cache)
    return {'container_id': value['Id'], 'image_id': value['Image'], 'network_id': network['Id'],
            'proxy_id': proxy['Id'], 'lock_inode': [lock.st_dev, lock.st_ino],
            'bundle_sha256': config['Labels']['bundle_sha256'], 'boot_id': cache['boot_id']}


def release_path(bundle_hash):
    require(re.fullmatch('[a-f0-9]{64}', bundle_hash or ''), 'BUNDLE_HASH_REQUIRED')
    path = RELEASES / bundle_hash
    require(path.resolve().parent == RELEASES, 'RELEASE_PATH')
    return path


def validate_release(path, bundle_hash):
    metadata(RELEASES, stat.S_ISDIR, 0, 0o700)
    require(read_record(RELEASES / 'owner.json') == {'task': TASK, 'scope': SCOPE}, 'RELEASE_ROOT_OWNER')
    metadata(path, stat.S_ISDIR, 0, 0o700)
    require(read_record(path / 'owner.json') == {'task': TASK, 'scope': SCOPE, 'bundle_sha256': bundle_hash}, 'RELEASE_OWNER')


@contextlib.contextmanager
def release_lock():
    import fcntl
    path = RELEASES / 'upgrade.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        current = metadata(path, stat.S_ISREG, 0, 0o600)
        held = os.fstat(descriptor)
        require((held.st_dev, held.st_ino) == (current.st_dev, current.st_ino), 'UPGRADE_LOCK_CHANGED')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def prepare(bundle_hash):
    previous = baseline()
    if not os.path.lexists(RELEASES):
        RELEASES.mkdir(mode=0o700)
        save_new(RELEASES / 'owner.json', {'task': TASK, 'scope': SCOPE})
    metadata(RELEASES, stat.S_ISDIR, 0, 0o700)
    require(read_record(RELEASES / 'owner.json') == {'task': TASK, 'scope': SCOPE}, 'RELEASE_ROOT_OWNER')
    path = release_path(bundle_hash)
    with release_lock():
        require(not os.path.lexists(path), 'RELEASE_EXISTS')
        path.mkdir(mode=0o700)
        save_new(path / 'owner.json', {'task': TASK, 'scope': SCOPE, 'bundle_sha256': bundle_hash})
        save_new(path / 'previous.json', previous)
        (path / 'incoming').mkdir(mode=0o700)
    return {'status': 'PREPARED', 'incoming': str(path / 'incoming/release.tar'), 'previous': previous}


def stage(path, bundle_hash):
    previous = read_record(path / 'previous.json')
    require(baseline() == previous, 'BASELINE_DRIFT')
    incoming = path / 'incoming/release.tar'
    metadata(path / 'incoming', stat.S_ISDIR, 0, 0o700)
    info = metadata(incoming, stat.S_ISREG, 0, 0o600)
    require(0 < info.st_size <= MAX_BUNDLE, 'BUNDLE_SIZE')
    content, manifest = validate_bundle(incoming.read_bytes(), bundle_hash)
    source = path / 'source'
    require(not os.path.lexists(source), 'SOURCE_EXISTS')
    source.mkdir(mode=0o700)
    for name, data in content.items():
        target = source / name
        require(target.resolve().is_relative_to(source), 'SOURCE_PATH')
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    image_name = 'haiqu-erp-codex-runtime:0.165.0-dxf-' + bundle_hash[:12]
    require(absent('image', image_name), 'TARGET_IMAGE_EXISTS')
    command(['docker', 'build', '--pull=false', '--network=none', '--label', 'task=' + OWNER_TASK,
             '--label', 'scope=' + SCOPE, '--label', 'bundle_sha256=' + bundle_hash,
             '--build-arg', 'CODEX_IMAGE=' + CODEX_IMAGE, '-f', str(source / 'src/codex_runtime/Dockerfile.offline'),
             '-t', image_name, str(source)], timeout=600)
    image = inspect('image', image_name)
    require(image['Config']['Labels'].get('bundle_sha256') == bundle_hash
            and image['Config']['User'] == '10001:10001', 'BUILT_IMAGE_IDENTITY')
    # 不挂账号、不联网；实际导入Linux几何依赖及核查固定CLI，避免ABI只靠文件名推断。
    probe_name = NAME + '-deps-' + bundle_hash[:12]
    require(absent('container', probe_name), 'DEPENDENCY_PROBE_EXISTS')
    command(['docker', 'run', '--rm', '--name', probe_name, '--label', 'task=' + OWNER_TASK,
             '--label', 'scope=' + SCOPE, '--label', 'bundle_sha256=' + bundle_hash,
             '--label', 'purpose=dependency-preflight', '--network=none', '--read-only', '--cap-drop=ALL',
             '--security-opt=no-new-privileges', '--pids-limit=16', '--memory=256m',
             '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777', '--env', 'HOME=/tmp',
             '--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'OMP_NUM_THREADS=1',
             '--entrypoint', 'python', image['Id'], '-I', '-B', '-c',
             "import ezdxf,shapely,subprocess; assert ezdxf.__version__=='1.4.5' and shapely.__version__=='2.2.0'; assert subprocess.check_output(['/usr/local/bin/codex','--version']).strip()==b'codex-cli 0.165.0'"], timeout=30)
    require(absent('container', probe_name), 'DEPENDENCY_PROBE_REMAINS')
    record = {'status': 'STAGED', 'bundle_sha256': bundle_hash, 'image_name': image_name, 'image_id': image['Id'],
              'previous': previous, 'source_manifest_sha256': sha(canonical(manifest))}
    save_new(path / 'staged.json', record)
    return record


def wait_ready(identifier, *, capability):
    for _ in range(60):
        value = container(identifier)
        require(value['State']['Running'] and value['RestartCount'] == 0, 'RUNTIME_START_FAILED')
        try:
            metadata(SOCKET, stat.S_ISSOCK, 10001, 0o660)
            cache = status()
        except (OSError, ReleaseError):
            time.sleep(0.5)
            continue
        require_idle(cache)
        require(not capability or 'nest_tools_v1' in cache.get('capabilities', []), 'CAPABILITY_MISSING')
        return cache
    raise ReleaseError('RUNTIME_START_TIMEOUT')


def restore_previous(receipt):
    previous = receipt['previous']
    old = container(previous['container_id'])
    require(old['Id'] == previous['container_id'] and old['Image'] == previous['image_id']
            and old['Name'] in ('/' + NAME, '/' + receipt['previous_name']), 'ROLLBACK_OLD_IDENTITY')
    if old['Name'] != '/' + NAME:
        if not absent('container', NAME):
            current = container(NAME)
            require_target_identity(current, NAME)
            require(current['Image'] == receipt['image_id']
                    and current['Config']['Labels'].get('bundle_sha256') == receipt['bundle_sha256']
                    and (not receipt.get('new_container_id') or current['Id'] == receipt['new_container_id']),
                    'ROLLBACK_NEW_IDENTITY')
            command(['docker', 'stop', '--time', '115', current['Id']], timeout=125)
            command(['docker', 'rm', current['Id']])
        command(['docker', 'rename', previous['container_id'], NAME])
    command(['docker', 'start', previous['container_id']])
    wait_ready(previous['container_id'], capability=False)


def activate(path, bundle_hash):
    staged = read_record(path / 'staged.json')
    require(staged['bundle_sha256'] == bundle_hash and baseline() == staged['previous'], 'BASELINE_DRIFT')
    image = inspect('image', staged['image_name'])
    require(image['Id'] == staged['image_id'] and image['Config']['Labels'].get('bundle_sha256') == bundle_hash, 'IMAGE_CHANGED')
    old_name = NAME + '-before-' + bundle_hash[:12]
    require(absent('container', old_name) and not (path / 'activation-started.json').exists(), 'ACTIVATION_EXISTS')
    receipt = {**staged, 'status': 'FAILED', 'previous_name': old_name, 'new_container_id': None}
    # 停服务前持久记录已核实的旧ID，断电/命令回执丢失后仍可按同一入口精确恢复。
    save_new(path / 'activation-started.json', receipt)
    try:
        command(['docker', 'stop', '--time', '115', staged['previous']['container_id']], timeout=125)
        require(not container(staged['previous']['container_id'])['State']['Running'], 'OLD_NOT_STOPPED')
        command(['docker', 'rename', staged['previous']['container_id'], old_name])
        args = ['docker', 'create', '--name', NAME, '--label', 'task=' + OWNER_TASK, '--label', 'scope=' + SCOPE,
                '--label', 'bundle_sha256=' + bundle_hash, '--restart', 'unless-stopped', '--stop-timeout', '115',
                '--init', '--user', '10001:10001', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--pids-limit', '64', '--memory', '768m', '--cpus', '1', '--log-driver', 'none', '--network', NETWORK,
                '--env', 'HTTP_PROXY=http://10.253.0.2:18080', '--env', 'HTTPS_PROXY=http://10.253.0.2:18080',
                '--env', 'NO_PROXY=localhost,127.0.0.1',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=134217728,uid=10001,gid=10001,mode=700',
                '--tmpfs', '/work/current:rw,noexec,nosuid,nodev,size=16777216,uid=10001,gid=10001,mode=700']
        for source, target in ((AUTH, '/state/codex'), (LOCK, '/state/login.lock'), (SOCKET.parent, '/run/haiqu-codex')):
            args += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + target]
        new_id = command(args + [staged['image_name']]).decode().strip()
        require(re.fullmatch('[a-f0-9]{64}', new_id), 'NEW_CONTAINER_ID')
        receipt['new_container_id'] = new_id
        save_new(path / 'created.json', {'new_container_id': new_id, 'bundle_sha256': bundle_hash})
        command(['docker', 'start', new_id])
        wait_ready(new_id, capability=True)
        current = baseline()
        require(current['container_id'] == new_id and current['image_id'] == staged['image_id']
                and current['lock_inode'] == staged['previous']['lock_inode']
                and current['network_id'] == staged['previous']['network_id']
                and current['proxy_id'] == staged['previous']['proxy_id'], 'POST_SWITCH_IDENTITY')
        receipt.update(status='ACTIVATED', boot_id=current['boot_id'])
    except Exception as error:
        receipt['error_code'] = str(error) if isinstance(error, ReleaseError) else type(error).__name__
        try:
            restore_previous(receipt)
            receipt['restored_previous'] = True
        except Exception as recovery_error:
            receipt['rollback_error'] = str(recovery_error) if isinstance(recovery_error, ReleaseError) else type(recovery_error).__name__
            receipt['restored_previous'] = False
    save_new(path / 'activation.json', receipt)
    return receipt


def rollback(path, bundle_hash):
    completed = (path / 'activation.json').exists()
    receipt = read_record(path / ('activation.json' if completed else 'activation-started.json'))
    require(receipt['bundle_sha256'] == bundle_hash
            and not (path / 'rollback.json').exists(), 'ROLLBACK_STATE')
    resuming = (path / 'rollback-started.json').exists()
    if resuming:
        started = read_record(path / 'rollback-started.json')
        require(started['bundle_sha256'] == bundle_hash and started['previous'] == receipt['previous']
                and started['image_id'] == receipt['image_id'] and started['previous_name'] == receipt['previous_name'],
                'ROLLBACK_RECEIPT')
        receipt = started
    elif completed and receipt['status'] == 'ACTIVATED':
        current = container(NAME)
        require_target_identity(current, NAME)
        require(current['Id'] == receipt['new_container_id'] and current['Image'] == receipt['image_id']
                and current['Config']['Labels'].get('bundle_sha256') == bundle_hash, 'ROLLBACK_DRIFT')
        # 已停止/OOM 的新容器不可能再响应 status，不能因此阻止恢复原服务。
        if current['State']['Running']:
            require_idle(status())
    elif (path / 'created.json').exists():
        created = read_record(path / 'created.json')
        require(created['bundle_sha256'] == bundle_hash, 'CREATED_RECEIPT')
        receipt['new_container_id'] = created['new_container_id']
    if not resuming:
        save_new(path / 'rollback-started.json', receipt)
    restore_previous(receipt)
    result = {'status': 'ROLLED_BACK', 'bundle_sha256': bundle_hash, 'container_id': receipt['previous']['container_id']}
    save_new(path / 'rollback.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=('inspect', 'prepare', 'stage', 'activate', 'rollback'), required=True)
    parser.add_argument('--bundle-sha256')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'ROOT_REQUIRED')
    if args.action == 'inspect':
        require(args.bundle_sha256 is None, 'INSPECT_ARGUMENTS')
        result = {'status': 'INSPECTED', **baseline()}
    elif args.action == 'prepare':
        result = prepare(args.bundle_sha256)
    else:
        path = release_path(args.bundle_sha256)
        validate_release(path, args.bundle_sha256)
        with release_lock():
            result = {'stage': stage, 'activate': activate, 'rollback': rollback}[args.action](path, args.bundle_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] != 'FAILED' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ReleaseError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'FAILED', 'error_code': str(error) if isinstance(error, ReleaseError) else type(error).__name__}))
        raise SystemExit(1)
