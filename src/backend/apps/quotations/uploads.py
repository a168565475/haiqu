"""报价产品图片与正式报价文件上传。"""

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.files.uploads import DEFAULT_MAX_IMAGE_BYTES, save_scanned_image
from apps.files.models import BusinessFile, FileScanStatus
from apps.imports.security import InfectedFile, ScannerUnavailable, _clamav_scan


MAX_IMAGE_BYTES = DEFAULT_MAX_IMAGE_BYTES
PRODUCT_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FORMAL_DOCUMENT_BYTES = 10 * 1024 * 1024
FORMAL_DOCUMENT_RULES = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
}


def save_quotation_product_image(uploaded_file, actor_employee):
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in PRODUCT_IMAGE_SUFFIXES:
        raise ValidationError("产品主图仅支持 JPG、PNG 或 WebP 格式。")
    return save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="quotation-images",
        field_label="产品图片",
        max_bytes=MAX_IMAGE_BYTES,
    )


def save_quotation_formal_document(uploaded_file, actor_employee):
    name = Path(uploaded_file.name or "quotation").name[:255]
    suffix = Path(name).suffix.lower()
    if suffix not in FORMAL_DOCUMENT_RULES:
        raise ValidationError("正式报价文件仅支持 PDF 或 XLSX 格式。")
    if uploaded_file.size <= 0 or uploaded_file.size > MAX_FORMAL_DOCUMENT_BYTES:
        raise ValidationError("正式报价文件必须大于 0 字节且不超过 10MB。")

    quarantine_dir = Path(settings.MEDIA_ROOT) / "quarantine" / str(uuid.uuid4())
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    temporary_path = quarantine_dir / name
    digest = hashlib.sha256()
    size = 0
    expected_content_type, expected_signature = FORMAL_DOCUMENT_RULES[suffix]
    try:
        with temporary_path.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > MAX_FORMAL_DOCUMENT_BYTES:
                    raise ValidationError("正式报价文件不能超过 10MB。")
                digest.update(chunk)
                target.write(chunk)
        if not temporary_path.read_bytes()[:8].startswith(expected_signature):
            raise ValidationError("正式报价文件签名与扩展名不一致。")
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

        relative_key = Path("quotation-documents") / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}{suffix}"
        final_path = Path(settings.MEDIA_ROOT) / relative_key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_path), str(final_path))
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
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            os.rmdir(quarantine_dir)
        except OSError:
            pass
