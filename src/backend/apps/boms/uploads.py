import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.files.models import BusinessFile, FileScanStatus


@dataclass
class PreparedBomUpload:
    original_name: str
    suffix: str
    content_type: str
    size_bytes: int
    content_hash: str
    temporary_path: Path
    quarantine_dir: Path

    def cleanup(self):
        if self.temporary_path.exists():
            self.temporary_path.unlink()
        try:
            os.rmdir(self.quarantine_dir)
        except OSError:
            pass


def prepare_bom_upload(uploaded_file):
    original_name = Path(uploaded_file.name or "bom").name[:255]
    if original_name.startswith("~$"):
        raise ValidationError({"workbook": "“~$”开头的是 Excel 临时锁定文件，不能作为 BOM 数据源。"})
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise ValidationError({"workbook": "BOM 文件仅支持 XLS 或 XLSX 格式。"})

    max_bytes = getattr(settings, "BOM_IMPORT_MAX_BYTES", 100 * 1024 * 1024)
    size_hint = int(getattr(uploaded_file, "size", 0) or 0)
    if size_hint <= 0 or size_hint > max_bytes:
        raise ValidationError({"workbook": f"文件必须大于 0 字节且不超过 {max_bytes // 1024 // 1024}MB。"})

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
                    raise ValidationError({"workbook": f"文件不能超过 {max_bytes // 1024 // 1024}MB。"})
                digest.update(chunk)
                target.write(chunk)

        signature = temporary_path.read_bytes()[:8]
        if suffix == ".xlsx" and not signature.startswith(b"PK"):
            raise ValidationError({"workbook": "XLSX 文件签名不正确。"})
        if suffix == ".xls" and signature != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValidationError({"workbook": "XLS 文件签名不正确。"})

        return PreparedBomUpload(
            original_name=original_name,
            suffix=suffix,
            content_type=uploaded_file.content_type or "application/octet-stream",
            size_bytes=size,
            content_hash=digest.hexdigest(),
            temporary_path=temporary_path,
            quarantine_dir=quarantine_dir,
        )
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            os.rmdir(quarantine_dir)
        except OSError:
            pass
        raise


def persist_prepared_bom_upload(prepared, actor_employee):
    relative_key = Path("boms") / timezone.now().strftime("%Y/%m") / f"{uuid.uuid4()}{prepared.suffix}"
    final_path = Path(settings.MEDIA_ROOT) / relative_key
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(prepared.temporary_path), str(final_path))
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=actor_employee,
            original_name=prepared.original_name,
            storage_key=relative_key.as_posix(),
            content_type=prepared.content_type,
            size_bytes=prepared.size_bytes,
            content_hash=prepared.content_hash,
            scan_status=FileScanStatus.SKIPPED,
            scanned_at=None,
            scan_message="BOM 上传已关闭病毒扫描。",
        )
        return business_file, final_path
    except Exception:
        if final_path.exists():
            final_path.unlink()
        raise
    finally:
        try:
            os.rmdir(prepared.quarantine_dir)
        except OSError:
            pass
