"""固定子进程入口；参数只有源码目录内的模块与原件路径。"""
import json
from pathlib import Path
import runpy
import sys
import xml.etree.ElementTree as ET
import zipfile


def main():
    module = runpy.run_path(str(Path(__file__).with_name('preprocessing.py')))
    try:
        _, encoded, _ = module['build_manifest'](sys.argv[1])
    except module['ManifestError'] as exc:
        code = str(exc)
        if not code or len(code) > 64 or not all(char.isupper() or char == '_' or char.isdigit() for char in code):
            raise
        print(json.dumps({'error_code': code}))
        return 2
    except (ET.ParseError, zipfile.BadZipFile, UnicodeError):
        print(json.dumps({'error_code': 'FILE_STRUCTURE_REJECTED'}))
        return 2
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
