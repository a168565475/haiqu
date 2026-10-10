import hashlib
import os
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.files.uploads import save_scanned_image
from apps.files.models import BusinessFile, FileScanStatus
from apps.imports.security import InfectedFile, ScannerUnavailable, _clamav_scan


MAX_PAYMENT_EVIDENCE_BYTES = 10 * 1024 * 1024
PAYMENT_EVIDENCE_RULES = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}
PARAMETER_FILE_RULES = {
    **PAYMENT_EVIDENCE_RULES,
    ".xls": ("application/vnd.ms-excel", b"\xd0\xcf\x11\xe0"),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        b"PK\x03\x04",
    ),
}


def _save_scanned_sample_document(
    uploaded_file,
    actor_employee,
    *,
    rules,
    storage_folder,
    field_label,
):
    name = Path(uploaded_file.name or "sample-document").name[:255]
    suffix = Path(name).suffix.lower()
    if suffix not in rules:
        supported = "、".join(sorted(item.lstrip(".").upper() for item in rules))
        raise ValidationError(f"{field_label}仅支持 {supported} 格式。")
    if uploaded_file.size <= 0 or uploaded_file.size > MAX_PAYMENT_EVIDENCE_BYTES:
        raise ValidationError(f"{field_label}必须大于 0 字节且不超过 10MB。")

    expected_content_type, expected_signature = rules[suffix]
    quarantine_dir = Path(settings.MEDIA_ROOT) / "quarantine" / str(uuid.uuid4())
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    temporary_path = quarantine_dir / name
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > MAX_PAYMENT_EVIDENCE_BYTES:
                    raise ValidationError(f"{field_label}不能超过 10MB。")
                digest.update(chunk)
                target.write(chunk)
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


def save_payment_evidence(uploaded_file, actor_employee):
    return _save_scanned_sample_document(
        uploaded_file,
        actor_employee,
        rules=PAYMENT_EVIDENCE_RULES,
        storage_folder="samples/payment-evidence",
        field_label="财务审核凭证",
    )


def save_sample_parameter_file(uploaded_file, actor_employee, *, parameter_type):
    if parameter_type not in {"metalwork", "cutting"}:
        raise ValidationError("参数文件类型不正确。")
    label = "金工参数文件" if parameter_type == "metalwork" else "裁剪参数文件"
    return _save_scanned_sample_document(
        uploaded_file,
        actor_employee,
        rules=PARAMETER_FILE_RULES,
        storage_folder=f"samples/{parameter_type}-parameters",
        field_label=label,
    )


def save_sample_parameter_image(uploaded_file, actor_employee, *, parameter_type):
    """新版金工/裁剪参数只接收图片，沿用统一图片安全校验。"""
    if parameter_type not in {"metalwork", "cutting"}:
        raise ValidationError("参数图片类型不正确。")
    label = "金工参数图片" if parameter_type == "metalwork" else "裁剪参数图片"
    return save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder=f"samples/{parameter_type}-parameter-images",
        field_label=label,
    )


def save_sample_task_sheet(uploaded_file, actor_employee):
    return save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="samples/task-sheets",
        field_label="任务单图片",
    )


def save_sampling_detail_image(uploaded_file, actor_employee):
    return save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="samples/sampling-details",
        field_label="打样信息明细图片",
    )


def cleanup_sample_task_files(business_files):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    for business_file in business_files:
        storage_path = (media_root / business_file.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError:
            continue
        if storage_path.is_file():
            storage_path.unlink()
        business_file.delete()


cleanup_sample_files = cleanup_sample_task_files
