"""专用 DXF runtime 发布包；不接受业务文件、账号资料或任意归档路径。"""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import zipfile
from email.parser import BytesParser

TASK = 'bom_dxf_executor_20261105'
SCOPE = 'runtime-local-erp'
MAX_BUNDLE = 64 * 1024 * 1024
SOURCE_FILES = {'src/codex_runtime/' + name for name in (
    '__init__.py', '__main__.py', 'config.toml', 'Dockerfile', 'Dockerfile.offline', 'protocol.py', 'README.md',
    'server.py', 'service.py', 'nesting.py',
    'tests/test_protocol.py', 'tests/test_server.py', 'tests/test_service.py', 'tests/test_nesting.py',
    'tests/test_dxf_tools.py', 'tests/test_dxf_geometry.py', 'tests/test_dxf_nesting.py',
    'tests/test_dxf_codex_optimization.py', 'tests/test_dxf_outputs.py',
    'dxf_tools/__init__.py', 'dxf_tools/session.py', 'dxf_tools/runner.py', 'dxf_tools/README.md',
    'dxf_tools/dxf_geometry.py', 'dxf_tools/dxf_nesting.py', 'dxf_tools/dxf_rendering.py',
    'dxf_tools/dxf_codex_optimization.py', 'dxf_tools/requirements.txt',
)}


class ReleaseError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise ReleaseError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def describe(data):
    return {'size_bytes': len(data), 'sha256': sha(data)}


def wheel_identity(name, data):
    require(re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', name) is not None and 0 < len(data) <= 24 * 1024 * 1024,
            'WHEEL_BOUNDARY')
    require(name.endswith('-py3-none-any.whl') or (('cp313' in name or 'abi3' in name)
            and 'manylinux' in name and name.endswith('_x86_64.whl')), 'WHEEL_PLATFORM')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [item for item in archive.infolist() if item.filename.endswith('.dist-info/METADATA')]
        require(len(members) == 1 and members[0].file_size <= 512 * 1024, 'WHEEL_METADATA')
        metadata = BytesParser().parsebytes(archive.read(members[0]))
    package, version = metadata.get('Name', ''), metadata.get('Version', '')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', package) and re.fullmatch(r'[A-Za-z0-9_.+-]+', version), 'WHEEL_METADATA')
    return re.sub(r'[-_.]+', '-', package).lower(), version


def locked_requirements(wheels):
    require(2 <= len(wheels) <= 24, 'WHEEL_COUNT')
    packages = {}
    for name, data in sorted(wheels.items()):
        package, version = wheel_identity(name, data)
        require(package not in packages, 'WHEEL_DUPLICATE')
        packages[package] = version, sha(data)
    require(packages.get('ezdxf', (None,))[0] == '1.4.5' and packages.get('shapely', (None,))[0] == '2.2.0', 'GEOMETRY_VERSION')
    return ''.join(f'{name}=={version} --hash=sha256:{digest}\n'
                   for name, (version, digest) in sorted(packages.items())).encode()


def build_bundle(root, wheel_dir):
    manifest = json.loads((wheel_dir / 'manifest.json').read_bytes())
    require(type(manifest) is dict and set(manifest) == {'python', 'platform', 'requirements', 'files'}
            and manifest['python'] == '3.13' and manifest['platform'] == 'manylinux_x86_64'
            and manifest['requirements'] == ['ezdxf==1.4.5', 'Shapely==2.2.0']
            and type(manifest['files']) is dict, 'WHEEL_MANIFEST')
    require({p.name for p in wheel_dir.iterdir()} == set(manifest['files']) | {'manifest.json'}, 'WHEEL_DIRECTORY')
    wheels = {}
    for name, expected in manifest['files'].items():
        require(re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', name) is not None, 'WHEEL_NAME')
        path = wheel_dir / name
        require(path.is_file() and not path.is_symlink(), 'WHEEL_PATH')
        wheels[name] = path.read_bytes()
        require(describe(wheels[name]) == expected, 'WHEEL_HASH')
    lock = locked_requirements(wheels)
    content = {}
    for name in SOURCE_FILES:
        path = root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'SOURCE_PATH')
        content[name] = path.read_bytes()
        require(0 < len(content[name]) < 200000, 'SOURCE_SIZE')
    content.update({'vendor/wheels/' + name: data for name, data in wheels.items()})
    content['vendor/requirements.lock'] = lock
    release = {'schema_version': 1, 'task': TASK, 'scope': SCOPE,
               'files': {name: describe(data) for name, data in sorted(content.items())}}
    content['release_manifest.json'] = canonical(release)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(content.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
    raw = output.getvalue()
    require(len(raw) <= MAX_BUNDLE, 'BUNDLE_SIZE')
    validate_bundle(raw, sha(raw))
    return raw, release


def validate_bundle(raw, expected_sha):
    require(re.fullmatch('[a-f0-9]{64}', expected_sha) and 0 < len(raw) <= MAX_BUNDLE and sha(raw) == expected_sha, 'BUNDLE_HASH')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        names = [item.name for item in members]
        require(len(names) == len(set(names)) and len(names) <= len(SOURCE_FILES) + 26, 'ARCHIVE_MEMBERS')
        require(all(item.isfile() and 0 < item.size <= 24 * 1024 * 1024 for item in members), 'ARCHIVE_TYPE')
        require('release_manifest.json' in names, 'MANIFEST_MISSING')
        content = {item.name: archive.extractfile(item).read() for item in members}
    manifest = json.loads(content.pop('release_manifest.json'))
    require(type(manifest) is dict and set(manifest) == {'schema_version', 'task', 'scope', 'files'}
            and type(manifest['schema_version']) is int and manifest['schema_version'] == 1
            and manifest['task'] == TASK and manifest['scope'] == SCOPE
            and type(manifest['files']) is dict and set(manifest['files']) == set(content), 'MANIFEST_BOUNDARY')
    wheels = {name.removeprefix('vendor/wheels/'): data for name, data in content.items() if name.startswith('vendor/wheels/')}
    require(set(content) == SOURCE_FILES | {'vendor/requirements.lock'} | {'vendor/wheels/' + name for name in wheels}, 'ARCHIVE_PATH')
    for name, data in content.items():
        require(describe(data) == manifest['files'][name], 'SOURCE_HASH')
        if name in SOURCE_FILES:
            require(len(data) < 200000, 'SOURCE_SIZE')
    require(content['vendor/requirements.lock'] == locked_requirements(wheels), 'WHEEL_LOCK')
    return content, manifest
