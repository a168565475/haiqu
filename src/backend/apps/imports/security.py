import hashlib
import os
import shutil
import socket
import struct
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.files.models import BusinessFile, FileScanStatus


class InfectedFile(APIException):
    status_code = 422
    default_detail = "文件未通过病毒扫描。"
    default_code = "infected_file"


class ScannerUnavailable(APIException):
    status_code = 503
    default_detail = "病毒扫描服务暂时不可用，请稍后重试。"
    default_code = "scanner_unavailable"


def scan_upload(path, *, scanner=None):
    """按全局开关扫描临时文件，并返回状态与说明。"""
    if not settings.FILE_VIRUS_SCAN_ENABLED:
        return FileScanStatus.SKIPPED, "病毒扫描已关闭，文件未执行病毒扫描。"
    scan = scanner or _clamav_scan
    return FileScanStatus.CLEAN, scan(path)


def _clamav_scan(path):
    host = settings.CLAMAV_HOST
    port = settings.CLAMAV_PORT
    timeout = settings.CLAMAV_TIMEOUT
    reply = bytearray()
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(b"zINSTREAM\0")
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    connection.sendall(struct.pack(">I", len(chunk)))
                    connection.sendall(chunk)
            connection.sendall(struct.pack(">I", 0))
            while True:
                data = connection.recv(4096)
                if not data:
                    break
                reply.extend(data)
                if b"\0" in data:
                    break
    except (OSError, TimeoutError) as exc:
        raise ScannerUnavailable() from exc
    message = bytes(reply).replace(b"\0", b"").decode("utf-8", "replace").strip()
    if message.endswith(" FOUND"):
        raise InfectedFile(message)
    if not message.endswith(" OK"):
        raise ScannerUnavailable(f"病毒扫描服务返回异常：{message or '无响应'}")
    return message


def save_and_scan_upload(uploaded_file, actor_employee):
    original_name = Path(uploaded_file.name or "upload").name[:255]
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValidationError("只支持 CSV 或 XLSX 文件。")
    max_bytes = settings.CONTACT_IMPORT_MAX_BYTES
    if uploaded_file.size <= 0 or uploaded_file.size > max_bytes:
        raise ValidationError(f"文件必须大于 0 字节且不超过 {max_bytes // 1024 // 1024}MB。")

    quarantine_dir = Path(settings.MEDIA_ROOT) / "quarantine" / str(uuid.uuid4())
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    temporary_path = quarantine_dir / original_name
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(f"文件不能超过 {max_bytes // 1024 // 1024}MB。")
                digest.update(chunk)
                target.write(chunk)

        with temporary_path.open("rb") as source:
            signature = source.read(4)
        if suffix == ".xlsx" and signature[:2] != b"PK":
            raise ValidationError("XLSX 文件签名不正确。")
        if suffix == ".csv" and b"\x00" in signature:
            raise ValidationError("CSV 文件内容不正确。")

        virtual_key = f"quarantine/{quarantine_dir.name}/{original_name}"
        try:
            scan_status, scan_message = scan_upload(temporary_path)
        except InfectedFile as exc:
            BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=original_name,
                storage_key=virtual_key,
                content_type=uploaded_file.content_type or "application/octet-stream",
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=FileScanStatus.INFECTED,
                scanned_at=timezone.now(),
                scan_message=str(exc.detail)[:500],
            )
            raise
        except ScannerUnavailable as exc:
            BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=original_name,
                storage_key=virtual_key,
                content_type=uploaded_file.content_type or "application/octet-stream",
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=FileScanStatus.FAILED,
                scanned_at=timezone.now(),
                scan_message=str(exc.detail)[:500],
            )
            raise

        relative_key = Path("imports") / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}{suffix}"
        final_path = Path(settings.MEDIA_ROOT) / relative_key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_path), str(final_path))
        try:
            business_file = BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=original_name,
                storage_key=relative_key.as_posix(),
                content_type=uploaded_file.content_type or "application/octet-stream",
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=scan_status,
                scanned_at=timezone.now() if scan_status == FileScanStatus.CLEAN else None,
                scan_message=scan_message[:500],
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        return business_file, final_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            os.rmdir(quarantine_dir)
        except OSError:
            pass
