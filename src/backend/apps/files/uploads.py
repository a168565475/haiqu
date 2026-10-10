"""通用图片隔离、文件签名校验与 ClamAV 安全扫描。"""

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.imports.security import InfectedFile, ScannerUnavailable, _clamav_scan

from .models import BusinessFile, FileScanStatus


IMAGE_RULES = {
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".webp": ("image/webp", b"RIFF"),
}
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024
DOCUMENT_RULES = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}
DEFAULT_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def save_scanned_image(
    uploaded_file,
    actor_employee,
    *,
    storage_folder,
    field_label="图片",
    max_bytes=DEFAULT_MAX_IMAGE_BYTES,
):
    name = Path(uploaded_file.name or "image").name[:255]
    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_RULES:
        raise ValidationError(f"{field_label}仅支持 JPG、PNG、GIF 或 WebP 格式。")
    if uploaded_file.size <= 0 or uploaded_file.size > max_bytes:
        raise ValidationError(f"{field_label}必须大于 0 字节且不超过 {max_bytes // 1024 // 1024}MB。")

    quarantine_dir = Path(settings.MEDIA_ROOT) / "quarantine" / str(uuid.uuid4())
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    temporary_path = quarantine_dir / name
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(f"{field_label}不能超过 {max_bytes // 1024 // 1024}MB。")
                digest.update(chunk)
                target.write(chunk)
        signature = temporary_path.read_bytes()[:12]
        expected_content_type, expected_signature = IMAGE_RULES[suffix]
        if not signature.startswith(expected_signature):
            raise ValidationError(f"{field_label}文件签名与扩展名不一致。")
        if suffix == ".webp" and signature[8:12] != b"WEBP":
            raise ValidationError("WebP 图片签名不正确。")
        try:
            scan_message = _clamav_scan(temporary_path)
        except (InfectedFile, ScannerUnavailable) as exc:
            scan_status = FileScanStatus.INFECTED if isinstance(exc, InfectedFile) else FileScanStatus.FAILED
            BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=name,
                storage_key=f"quarantine/{quarantine_dir.name}/{name}",
                content_type=uploaded_file.content_type or expected_content_type,
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=scan_status,
                scanned_at=timezone.now(),
                scan_message=str(exc.detail)[:500],
            )
            raise

        relative_key = Path(storage_folder) / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}{suffix}"
        final_path = Path(settings.MEDIA_ROOT) / relative_key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_path), str(final_path))
        try:
            return BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=name,
                storage_key=relative_key.as_posix(),
                content_type=expected_content_type,
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=FileScanStatus.CLEAN,
                scanned_at=timezone.now(),
                scan_message=scan_message[:500],
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            os.rmdir(quarantine_dir)
        except OSError:
            pass


def save_scanned_document(
    uploaded_file,
    actor_employee,
    *,
    storage_folder,
    field_label="文件",
    max_bytes=DEFAULT_MAX_DOCUMENT_BYTES,
):
    """保存 PDF 或常见图片凭证；先校验签名，再经过 ClamAV 扫描。"""

    name = Path(uploaded_file.name or "document").name[:255]
    suffix = Path(name).suffix.lower()
    if suffix not in DOCUMENT_RULES:
        raise ValidationError(f"{field_label}仅支持 PDF、JPG 或 PNG 格式。")
    if uploaded_file.size <= 0 or uploaded_file.size > max_bytes:
        raise ValidationError(f"{field_label}必须大于 0 字节且不超过 {max_bytes // 1024 // 1024}MB。")

    quarantine_dir = Path(settings.MEDIA_ROOT) / "quarantine" / str(uuid.uuid4())
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    temporary_path = quarantine_dir / name
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(f"{field_label}不能超过 {max_bytes // 1024 // 1024}MB。")
                digest.update(chunk)
                target.write(chunk)
        expected_content_type, expected_signature = DOCUMENT_RULES[suffix]
        if not temporary_path.read_bytes()[:12].startswith(expected_signature):
            raise ValidationError(f"{field_label}文件签名与扩展名不一致。")
        try:
            scan_message = _clamav_scan(temporary_path)
        except (InfectedFile, ScannerUnavailable) as exc:
            scan_status = FileScanStatus.INFECTED if isinstance(exc, InfectedFile) else FileScanStatus.FAILED
            BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=name,
                storage_key=f"quarantine/{quarantine_dir.name}/{name}",
                content_type=uploaded_file.content_type or expected_content_type,
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=scan_status,
                scanned_at=timezone.now(),
                scan_message=str(exc.detail)[:500],
            )
            raise

        relative_key = Path(storage_folder) / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}{suffix}"
        final_path = Path(settings.MEDIA_ROOT) / relative_key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_path), str(final_path))
        try:
            return BusinessFile.objects.create(
                uploaded_by_employee=actor_employee,
                original_name=name,
                storage_key=relative_key.as_posix(),
                content_type=expected_content_type,
                size_bytes=size,
                content_hash=digest.hexdigest(),
                scan_status=FileScanStatus.CLEAN,
                scanned_at=timezone.now(),
                scan_message=scan_message[:500],
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            os.rmdir(quarantine_dir)
        except OSError:
            pass
