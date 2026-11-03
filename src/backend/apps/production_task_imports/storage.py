"""私有来源目录不挂在 MEDIA_URL 下；所有路径来自记录 UUID 或固定文件名。"""
import hashlib
import os
from pathlib import Path
import socket
import struct
import time
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from .preprocessing import LIMITS


class ImportFailure(APIException):
    status_code = 422
    def __init__(self, code):
        self.code = code
        self.api_error_code = code
        super().__init__('导入资料检查未通过，请根据错误类别处理后重试。', code=code)


def directory(record_id, *, create=False):
    root = Path(settings.PRODUCTION_IMPORT_ROOT).absolute()
    # 即使父目录被误配为符号链接，也不得沿链接访问其他媒体或账号。
    if root.resolve() != root:
        raise ImportFailure('STORAGE_UNSAFE')
    target = root / str(UUID(str(record_id)))
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.mkdir(mode=0o700)
    if target.resolve() != target or (target.exists() and not target.is_dir()):
        raise ImportFailure('STORAGE_UNSAFE')
    return target


def source_path(record):
    path = directory(record.pk) / 'original.xlsx'
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ImportFailure('SOURCE_MISSING')
    if path.stat().st_size != record.size_bytes or path.stat().st_size > LIMITS['file_bytes']:
        raise ImportFailure('SOURCE_CHANGED')
    with path.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != record.sha256:
            raise ImportFailure('SOURCE_CHANGED')
    return path


def upload_bytes(upload):
    if upload is None:
        raise ValidationError({'file': '请选择 XLSX 文件。'})
    name = Path(upload.name or '').name
    if Path(name).suffix.lower() != '.xlsx' or name.startswith('~$') or len(name) > 255:
        raise ValidationError({'file': '仅支持非临时的 XLSX 文件。'})
    if not 0 < upload.size <= LIMITS['file_bytes']:
        raise ValidationError({'file': '文件必须大于 0 字节且不超过 25 MiB。'})
    data = bytearray()
    for chunk in upload.chunks():
        if len(data) + len(chunk) > LIMITS['file_bytes']:
            raise ValidationError({'file': '文件不能超过 25 MiB。'})
        data.extend(chunk)
    if not data.startswith(b'PK\x03\x04'):
        raise ValidationError({'file': '文件内容不是 XLSX 压缩包。'})
    return name, bytes(data), hashlib.sha256(data).hexdigest()


def write_source(record, data):
    target = directory(record.pk, create=True)
    try:
        with (target / 'original.xlsx').open('xb') as output:
            output.write(data)
        os.chmod(target / 'original.xlsx', 0o600)
    except BaseException:
        (target / 'original.xlsx').unlink(missing_ok=True)
        target.rmdir()
        raise


def remove_files(record):
    target = directory(record.pk)
    if not target.exists():
        return
    allowed = {'original.xlsx'}
    files = list(target.iterdir())
    if any(path.name not in allowed or path.is_symlink() or not path.is_file()
           or path.stat().st_nlink != 1 for path in files):
        raise ImportFailure('CLEANUP_UNKNOWN_RESOURCE')
    for path in files:
        path.unlink()
    target.rmdir()


def scan_source(path):
    # 本模块不能把全局扫描关闭所返回的 SKIPPED 当作可解析。
    if not settings.FILE_VIRUS_SCAN_ENABLED:
        raise ImportFailure('SCAN_UNAVAILABLE')
    deadline = time.monotonic() + 60
    try:
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=10) as connection:
            def send(data):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                connection.settimeout(remaining)
                connection.sendall(data)
            send(b'zINSTREAM\0')
            with path.open('rb') as source:
                while chunk := source.read(65536):
                    send(struct.pack('>I', len(chunk)) + chunk)
            send(struct.pack('>I', 0))
            reply = bytearray()
            while len(reply) < 4096:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                connection.settimeout(remaining)
                chunk = connection.recv(min(512, 4096 - len(reply)))
                if not chunk:
                    break
                reply.extend(chunk)
                if b'\0' in chunk:
                    break
    except (OSError, TimeoutError):
        raise ImportFailure('SCAN_UNAVAILABLE') from None
    message = bytes(reply).rstrip(b'\0\r\n')
    if message.endswith(b' FOUND'):
        raise ImportFailure('SCAN_INFECTED')
    if message != b'stream: OK':
        raise ImportFailure('SCAN_UNAVAILABLE')
