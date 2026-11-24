"""本地生成可审核发布工件，不联网、不运行 Docker、不部署。"""
import argparse
import base64
import json
from pathlib import Path

from runtime_release_bundle import build_bundle, canonical, require, sha


def main():
    root = Path(__file__).resolve().parents[2]
    owned = root / 'qa/bom_dxf_executor_20261105'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel-dir', type=Path, default=owned / 'offline_wheels')
    parser.add_argument('--output-dir', type=Path, default=owned / 'release')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(output.parent == owned.resolve() and not output.exists(), 'OUTPUT_BOUNDARY')
    raw, manifest = build_bundle(root, args.wheel_dir.resolve())
    scripts = {name: (root / 'deploy/codex' / name).read_bytes() for name in
               ('server_runtime_upgrade.py', 'runtime_release_bundle.py')}
    loader = (
        'import base64,sys,types\n'
        "module=types.ModuleType('runtime_release_bundle')\n"
        "sys.modules['runtime_release_bundle']=module\n"
        f"exec(compile(base64.b64decode({base64.b64encode(scripts['runtime_release_bundle.py']).decode()!r}),'runtime_release_bundle.py','exec'),module.__dict__)\n"
        f"exec(compile(base64.b64decode({base64.b64encode(scripts['server_runtime_upgrade.py']).decode()!r}),'server_runtime_upgrade.py','exec'),{{'__name__':'__main__'}})\n"
    ).encode()
    scripts['remote_upgrade.py'] = loader
    receipt = {'scope': 'runtime-local-erp', 'bundle_sha256': sha(raw), 'size_bytes': len(raw),
               'files': {'release.tar': {'size_bytes': len(raw), 'sha256': sha(raw)},
                         **{name: {'size_bytes': len(data), 'sha256': sha(data)} for name, data in scripts.items()}},
               'source_manifest_sha256': sha(canonical(manifest)), 'remote_execution': 'NOT_EXECUTED'}
    output.mkdir(mode=0o700)
    for name, data in {'release.tar': raw, 'release_manifest.json': canonical(manifest),
                       'release_receipt.json': canonical(receipt), **scripts}.items():
        with (output / name).open('xb') as stream:
            stream.write(data)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
