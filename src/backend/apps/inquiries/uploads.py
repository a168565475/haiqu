"""询盘附件：校验格式、隔离扫描，通过后再保存及关联。"""

import hashlib
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.files.models import BusinessFile, FileScanStatus
from apps.files.uploads import save_scanned_image
from apps.imports.security import _clamav_scan, scan_upload


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ATTACHMENT_TYPES = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
}
PRODUCT_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_PRODUCT_IMAGE_BYTES = 10 * 1024 * 1024


def save_inquiry_product_image(uploaded_file, actor_employee, inquiry_id):
    """保存询盘产品图；产品图只允许 JPG/JPEG/PNG，且单张不超过 10MB。"""
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in PRODUCT_IMAGE_SUFFIXES:
        raise ValidationError("产品图片仅支持 JPG、JPEG 或 PNG 格式。")
    return save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder=f"inquiries/{inquiry_id}/product-images",
        field_label="产品图片",
        max_bytes=MAX_PRODUCT_IMAGE_BYTES,
    )


def attachment_hash(uploaded_file):
    digest = hashlib.sha256()
    size = 0
    for chunk in uploaded_file.chunks():
        size += len(chunk)
        if size > MAX_ATTACHMENT_BYTES:
            raise ValidationError("附件不能超过 10 MB。")
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def save_inquiry_attachment(uploaded_file, actor, inquiry_id, upload_id):
    name = Path((uploaded_file.name or "").replace("\\", "/")).name[:255]
    suffix = Path(name).suffix.lower()
    if suffix not in ATTACHMENT_TYPES:
        raise ValidationError("附件仅支持 PDF、XLSX、JPG、JPEG、PNG。")
    if not uploaded_file.size or uploaded_file.size > MAX_ATTACHMENT_BYTES:
        raise ValidationError("附件必须大于 0 字节且不超过 10 MB。")
    quarantine = Path(settings.MEDIA_ROOT) / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=quarantine) as directory:
        temporary = Path(directory) / "attachment"
        digest = hashlib.sha256()
        size = 0
        with temporary.open("wb") as target:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise ValidationError("附件不能超过 10 MB。")
                digest.update(chunk)
                target.write(chunk)
        content_type, signature = ATTACHMENT_TYPES[suffix]
        with temporary.open("rb") as source:
            if not source.read(12).startswith(signature):
                raise ValidationError("附件内容与扩展名不一致。")
        if suffix == ".xlsx":
            try:
                with ZipFile(temporary) as workbook:
                    entries = workbook.infolist()
                    names = {entry.filename for entry in entries}
                    if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
                        raise ValidationError("附件不是有效的 XLSX 工作簿。")
                    if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 100 * 1024 * 1024:
                        raise ValidationError("工作簿解压后内容过大。")
                    if any(entry.flag_bits & 1 for entry in entries) or "xl/vbaProject.bin" in names:
                        raise ValidationError("不支持加密或含宏的工作簿。")
            except BadZipFile as exc:
                raise ValidationError("XLSX 文件已损坏。") from exc
        scan_status, scan_message = scan_upload(temporary, scanner=_clamav_scan)
        key = Path("inquiries") / str(inquiry_id) / "attachments" / f"{uuid.uuid4()}{suffix}"
        final_path = Path(settings.MEDIA_ROOT) / key
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(final_path)
        try:
            return BusinessFile.objects.create(
                id=upload_id, uploaded_by_employee=actor, original_name=name,
                storage_key=key.as_posix(), content_type=content_type, size_bytes=size,
                content_hash=digest.hexdigest(), scan_status=scan_status,
                scanned_at=timezone.now() if scan_status == FileScanStatus.CLEAN else None,
                scan_message=str(scan_message)[:500],
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
