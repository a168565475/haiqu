"""按完整 OCI 归档的原始 blob 去重；仅使用 Python 3.11+ 标准库，不调用 Docker。"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile


ROOT_FILES = {'index.json', 'manifest.json', 'oci-layout'}
DIRECTORIES = {'blobs', 'blobs/sha256'}
SHA256 = re.compile(r'[0-9a-f]{64}')
BLOB = re.compile(r'blobs/sha256/[0-9a-f]{64}')
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def read_json(stream):
    data = stream.read(16 * 1024 * 1024 + 1)
    require(len(data) <= 16 * 1024 * 1024, 'JSON exceeds 16 MiB')
    return json.loads(data)


def validate_inventory(record):
    require(isinstance(record, dict) and record.get('format') == 'OCI', 'Expected OCI inventory')
    require(isinstance(record.get('files'), list), 'Missing files inventory')
    files = {}
    for item in record['files']:
        require(isinstance(item, dict), 'Invalid inventory member')
        name, size, digest = item.get('name'), item.get('bytes'), item.get('sha256')
        require(isinstance(name, str) and (name in ROOT_FILES or BLOB.fullmatch(name)), f'Forbidden path: {name}')
        require(name not in files, f'Duplicate inventory member: {name}')
        require(type(size) is int and size >= 0, f'Invalid size: {name}')
        require(isinstance(digest, str) and SHA256.fullmatch(digest), f'Invalid digest: {name}')
        require(not BLOB.fullmatch(name) or digest == name.rsplit('/', 1)[1], f'Blob digest mismatch: {name}')
        files[name] = item
    directories = record.get('directories', [])
    require(isinstance(directories, list) and len(set(directories)) == len(directories)
            and all(name in DIRECTORIES for name in directories), 'Invalid directories')
    return files


def scan(archive):
    files, directories, seen = [], [], set()
    for member in archive.getmembers():
        name = member.name
        require(name not in seen, f'Duplicate archive member: {name}')
        seen.add(name)
        if member.isdir():
            require(name in DIRECTORIES and member.size == 0, f'Forbidden directory: {name}')
            directories.append(name)
            continue
        require(member.isfile() and not member.issparse(), f'Forbidden member type: {name}')
        require(name in ROOT_FILES or BLOB.fullmatch(name), f'Forbidden path: {name}')
        require(member.size >= 0, f'Invalid member size: {name}')
        with archive.extractfile(member) as stream:
            files.append({'name': name, 'bytes': member.size, 'sha256': sha256(stream)})
    record = {'format': 'OCI', 'archive_bytes': Path(archive.name).stat().st_size,
              'files': sorted(files, key=lambda item: item['name']), 'directories': sorted(directories)}
    validate_inventory(record)
    return record


def verify_graph(archive, record):
    files = validate_inventory(record)
    require(ROOT_FILES <= files.keys(), 'Missing OCI or Docker compatibility metadata')
    def document(name):
        with archive.extractfile(name) as stream:
            return read_json(stream)
    layout = document('oci-layout')
    require(isinstance(layout, dict) and layout.get('imageLayoutVersion') == '1.0.0', 'Unsupported OCI layout')
    index = document('index.json')
    require(isinstance(index, dict) and index.get('schemaVersion') == 2 and index.get('mediaType') in INDEX_TYPES, 'Invalid OCI index')
    pending = index.get('manifests')
    require(isinstance(pending, list) and pending, 'Empty or missing image index')
    require(all(isinstance(child, dict) and child.get('mediaType') in INDEX_TYPES | MANIFEST_TYPES for child in pending), 'Unsupported image index descriptor')
    pending, visited = list(pending), set()
    while pending:
        desc = pending.pop()
        require(isinstance(desc, dict), 'Invalid OCI descriptor')
        digest, size, media = desc.get('digest'), desc.get('size'), desc.get('mediaType')
        require(isinstance(digest, str) and digest.startswith('sha256:') and SHA256.fullmatch(digest[7:]), 'Missing or invalid descriptor digest')
        require(type(size) is int and size >= 0 and isinstance(media, str), 'Missing or invalid descriptor size/mediaType')
        name = 'blobs/sha256/' + digest[7:]
        require(name in files and files[name]['bytes'] == size, f'Missing blob or wrong size: {digest}')
        if name in visited:
            continue
        visited.add(name)
        if media in INDEX_TYPES | MANIFEST_TYPES:
            node = document(name)
            require(isinstance(node, dict) and node.get('schemaVersion') == 2 and node.get('mediaType') == media, f'Invalid graph node: {digest}')
            children = node.get('manifests') if media in INDEX_TYPES else node.get('layers')
            require(isinstance(children, list), f'Missing graph children: {digest}')
            if media in INDEX_TYPES:
                require(all(isinstance(child, dict) and child.get('mediaType') in INDEX_TYPES | MANIFEST_TYPES for child in children), 'Unsupported nested index descriptor')
            pending.extend(children)
            if media in MANIFEST_TYPES:
                require(isinstance(node.get('config'), dict), 'Missing image configuration')
                pending.append(node['config'])
            if 'subject' in node:
                pending.append(node['subject'])
    manifests = document('manifest.json')
    require(isinstance(manifests, list) and manifests, 'Invalid Docker compatibility manifest')
    for item in manifests:
        require(isinstance(item, dict) and isinstance(item.get('Layers'), list), 'Invalid Docker layer list')
        names = [item.get('Config')] + item['Layers']
        require(all(isinstance(name, str) and BLOB.fullmatch(name) and name in files for name in names), 'Missing Docker compatibility blob')
    return index['manifests']


def write_json(path, value, created):
    with Path(path).open('x', encoding='utf-8') as stream:
        created.append(Path(path))
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def write_archive(path, directories, files, sources, created):
    with Path(path).open('xb') as stream:
        created.append(Path(path))
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT) as output:
            for name in directories:
                member = tarfile.TarInfo(name)
                member.type, member.mode = tarfile.DIRTYPE, 0o755
                output.addfile(member)
            for name in files:
                source = sources[name]
                member = source.getmember(name)
                with source.extractfile(member) as data:
                    output.addfile(member, data)


def run(args, created):
    with ExitStack() as stack:
        def archive(path):
            return stack.enter_context(tarfile.open(path, 'r:'))
        def json_file(path):
            with Path(path).open('rb') as stream:
                return read_json(stream)
        source = archive(args.archive)
        current = scan(source)
        if args.command in ('inventory', 'verify', 'delta'):
            current['targets'] = verify_graph(source, current)
        if args.command == 'delta':
            require(args.baseline and args.output and args.recipe, 'delta requires --baseline, --output and --recipe')
            baseline = validate_inventory(json_file(args.baseline))
            files = validate_inventory(current)
            included = [name for name, item in files.items() if name in ROOT_FILES or baseline.get(name) != item]
            reused = [item for name, item in files.items() if name not in included]
            write_archive(args.output, current['directories'], included, {name: source for name in included}, created)
            with Path(args.output).open('rb') as stream:
                delta_digest = sha256(stream)
            current.update(source_archive_bytes=current['archive_bytes'], included=included,
                           reused_blob_count=len(reused), reused_bytes=sum(item['bytes'] for item in reused),
                           delta_bytes=Path(args.output).stat().st_size, delta_sha256=delta_digest)
            write_json(args.recipe, current, created)
        elif args.command == 'reassemble':
            require(args.delta and args.recipe and args.output, 'reassemble requires --delta, --recipe and --output')
            recipe = json_file(args.recipe)
            expected, baseline = validate_inventory(recipe), validate_inventory(current)
            included = recipe.get('included')
            require(isinstance(included, list) and all(isinstance(name, str) for name in included)
                    and len(set(included)) == len(included) and set(included) <= expected.keys()
                    and ROOT_FILES <= set(included), 'Invalid delta member list')
            with Path(args.delta).open('rb') as stream:
                require(sha256(stream) == recipe.get('delta_sha256'), 'Delta archive digest mismatch')
            require(Path(args.delta).stat().st_size == recipe.get('delta_bytes'), 'Delta archive size mismatch')
            delta = archive(args.delta)
            added = validate_inventory(scan(delta))
            require(set(added) == set(included), 'Unexpected or missing delta members')
            sources = {}
            for name, item in expected.items():
                candidate, candidate_files = (delta, added) if name in added else (source, baseline)
                require(candidate_files.get(name) == item, f'Missing or changed member: {name}')
                sources[name] = candidate
            write_archive(args.output, recipe.get('directories', []), expected, sources, created)
            rebuilt = archive(args.output)
            current = scan(rebuilt)
            require(current['files'] == recipe['files'] and current['directories'] == recipe.get('directories', []), 'Reassembled member mismatch')
            current['targets'] = verify_graph(rebuilt, current)
        elif args.command == 'verify' and args.recipe:
            recipe = json_file(args.recipe)
            validate_inventory(recipe)
            require(current['files'] == recipe['files'] and current['directories'] == recipe.get('directories', []), 'Archive differs from source recipe')
        elif args.command == 'inventory' and args.output:
            write_json(args.output, current, created)
        return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'delta', 'reassemble', 'verify'))
    parser.add_argument('archive', help='Uncompressed docker save OCI tar')
    for name in ('baseline', 'delta', 'recipe', 'output'):
        parser.add_argument('--' + name)
    args = parser.parse_args()
    created = []
    try:
        outputs = [args.output] if args.output else []
        if args.command == 'delta' and args.recipe:
            outputs.append(args.recipe)
        require(len({Path(path).resolve() for path in outputs}) == len(outputs), 'Output paths must be distinct')
        require(all(not Path(path).exists() and not Path(path).is_symlink() for path in outputs), 'Output already exists')
        result = run(args, created)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError) as error:
        for path in reversed(created):
            path.unlink()
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
