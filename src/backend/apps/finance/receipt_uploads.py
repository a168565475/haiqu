"""水单预上传与确切文件清理；扫描不在收款/账单事务持锁期间执行。"""
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.models import AuditLog
from apps.core.audit import write_audit_log
from apps.files.models import BusinessFile, FileScanStatus, is_file_scan_usable
from apps.files.uploads import save_scanned_image
from apps.imports.security import InfectedFile, ScannerUnavailable
from .exceptions import FinanceConflict
from .models import FinanceMutationKey
from .receipt_exceptions import ReceiptFileError
from .receipt_models import FinanceReceiptUpload, ReceiptAttachment
from .statement_locks import lock_statement
from .statement_models import ReceivableStatement

MAX_RECEIPT_BYTES = 20 * 1024 * 1024
STORAGE_FOLDER = "finance/receipt_uploads"
logger = logging.getLogger(__name__)


def require_no_outer_transaction():
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError("财务预上传和两阶段清理不能包在外层事务中。")


def recovery_path(file_id):
    file_id = UUID(str(file_id))
    root = Path(settings.MEDIA_ROOT).resolve()
    folder = root / "finance" / "receipt_cleanup"
    path = folder / f"{file_id}.json"
    if folder.resolve() != folder or path.resolve() != path:
        raise ReceiptFileError("FILE_NOT_USABLE", "上传恢复登记路径无效。")
    return path


def read_recovery_record(file_id):
    path = recovery_path(file_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotFound("未找到指定文件的上传恢复登记。") from exc
    except (ValueError, OSError) as exc:
        raise ReceiptFileError("FILE_CLEANUP_FAILED", "上传恢复登记不可读，须核对后处理。", status=500) from exc
    valid = isinstance(data, dict) and set(data) == {"file_id", "owner_id", "storage_key"}
    try:
        valid = valid and data["file_id"] == str(UUID(str(file_id))) and str(UUID(data["owner_id"])) == data["owner_id"]
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid or not isinstance(data["storage_key"], str) or not data["storage_key"].startswith(STORAGE_FOLDER + "/"):
        raise ReceiptFileError("FILE_NOT_USABLE", "上传恢复登记内容不匹配，拒绝清理未知文件。")
    receipt_file_path(SimpleNamespace(storage_key=data["storage_key"]))
    return data


def record_new_file(file):
    path = recovery_path(file.pk)
    path.parent.mkdir(parents=True, exist_ok=True)
    # UUID 是本次刚创建的文件；独占创建，不能覆盖另一请求的清理凭证。
    with path.open("x", encoding="utf-8") as target:
        json.dump({"file_id": str(file.pk), "owner_id": str(file.uploaded_by_employee_id),
            "storage_key": file.storage_key}, target)


def has_recovery_record(file):
    path = recovery_path(file.pk)
    if not path.is_file():
        return False
    data = read_recovery_record(file.pk)
    return data == {"file_id": str(file.pk), "owner_id": str(file.uploaded_by_employee_id), "storage_key": file.storage_key}


def file_has_other_references(file, *, own_upload_id=None):
    for relation in file._meta.related_objects:
        rows = relation.related_model.objects.filter(**{relation.field.name: file})
        if relation.related_model is FinanceReceiptUpload and own_upload_id is not None:
            rows = rows.exclude(pk=own_upload_id)
        if rows.exists():
            return True
    return False


def receipt_file_path(file):
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / file.storage_key).resolve()
    finance_root = (root / STORAGE_FOLDER).resolve()
    if not path.is_relative_to(finance_root) or path == finance_root or not finance_root.is_relative_to(root):
        raise ReceiptFileError("FILE_NOT_USABLE", "水单存储路径无效。")
    return path


def require_usable_file(file):
    if file.archived_at or not is_file_scan_usable(file.scan_status) or (
        file.scan_status == FileScanStatus.SKIPPED and settings.FILE_VIRUS_SCAN_ENABLED
    ):
        raise ReceiptFileError("FILE_NOT_USABLE", "水单扫描状态不可用，请重新上传。")
    if file.content_type not in ("image/jpeg", "image/png") or not 0 < file.size_bytes <= MAX_RECEIPT_BYTES:
        raise ReceiptFileError("FILE_NOT_USABLE", "水单格式或大小不符合要求。")
    path = receipt_file_path(file)
    if not path.is_file():
        raise ReceiptFileError("FILE_MISSING", "水单文件实体不存在。", status=404)
    return path


def upload_digest(uploaded_file):
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png") or not 0 < uploaded_file.size <= MAX_RECEIPT_BYTES:
        raise ReceiptFileError("FILE_INVALID", "水单仅支持 JPG/PNG，大小须在 0 至 20 MB 之间。", status=400)
    digest = hashlib.sha256()
    size = 0
    signature = b""
    for chunk in uploaded_file.chunks():
        size += len(chunk)
        if size > MAX_RECEIPT_BYTES:
            raise ReceiptFileError("FILE_INVALID", "水单超过 20 MB。", status=400)
        if len(signature) < 8:
            signature += chunk[:8 - len(signature)]
        digest.update(chunk)
    uploaded_file.seek(0)
    expected = b"\x89PNG\r\n\x1a\n" if suffix == ".png" else b"\xff\xd8\xff"
    if not size or not signature.startswith(expected):
        raise ReceiptFileError("FILE_INVALID", "水单签名与文件扩展名不一致。", status=400)
    return digest.hexdigest()


def replay_upload(upload, *, actor, statement_id, digest):
    if upload.owner_employee_id != actor.pk:
        raise NotFound("水单不存在。")
    if upload.statement_id != statement_id or upload.file.content_hash != digest:
        raise FinanceConflict("IDEMPOTENCY_KEY_REUSED", "上传标识已用于其他账单或文件。")
    # 返回现态，已清理或绑定的上传不伪装成可再次使用。
    return upload, True


def audit_upload_file(file, actor, action, *, request=None):
    write_audit_log(object_type="FINANCE_UPLOAD_FILE", object_id=file.pk, action=action,
        actor_employee=actor, after_data={"file_id": str(file.pk), "storage_key": file.storage_key,
            "scan_status": file.scan_status}, request=request)


def compensate_upload_file(file_id, *, actor, request=None, _new_file=None):
    """只清理本次登记的未建立凭证文件；失败保留 BusinessFile + REGISTERED 审计供精确重试。"""
    require_no_outer_transaction()
    try:
        with transaction.atomic():
            file = BusinessFile.objects.select_for_update().filter(pk=file_id).first()
            if file is None:
                # 文件与元数据已删、仅登记删除失败时，重试只能删除经核实的确切登记。
                record = read_recovery_record(file_id)
                if record["owner_id"] != str(actor.pk):
                    raise ReceiptFileError("FILE_NOT_USABLE", "上传恢复登记所属人不匹配。")
                if receipt_file_path(SimpleNamespace(storage_key=record["storage_key"])).exists() or BusinessFile.objects.filter(storage_key=record["storage_key"]).exists():
                    raise ReceiptFileError("FILE_NOT_USABLE", "恢复登记仍有文件或元数据，须核对后处理。")
                recovery_path(file_id).unlink()
                return
            registered = AuditLog.objects.filter(
                object_type="FINANCE_UPLOAD_FILE", object_id=file.pk, action="REGISTERED"
            ).exists()
            known_new = _new_file is not None and _new_file.pk == file.pk and _new_file.storage_key == file.storage_key
            if file.uploaded_by_employee_id != actor.pk or not (registered or known_new or has_recovery_record(file)):
                raise ReceiptFileError("FILE_NOT_USABLE", "未找到本次上传登记，拒绝清理未知文件。")
            if file_has_other_references(file):
                raise FinanceConflict("REFERENCED_RECORD", "文件已有引用，拒绝补偿删除。")
            receipt_file_path(file).unlink(missing_ok=True)
            file.delete()
        recovery_path(file_id).unlink(missing_ok=True)
    except OSError as exc:
        # 不吞掉清理错误，保留确切待处理 UUID，管理命令可再次核验后处理。
        file = BusinessFile.objects.filter(pk=file_id).first()
        recovery_action = "RETRY_EXACT_CLEANUP"
        if file is not None and not recovery_path(file_id).exists():
            try:
                record_new_file(file)
            except OSError:
                logger.exception("财务水单恢复登记写入失败 file_id=%s", file_id)
                recovery_action = "MANUAL_REVIEW"
        raise ReceiptFileError("FILE_CLEANUP_FAILED", "上传失败后的文件清理未完成。", status=500,
            meta={"orphan_file_id": str(file_id), "recovery_action": recovery_action}) from exc


def reject_deleted_upload(upload_key, actor):
    deleted = FinanceMutationKey.objects.filter(action="DELETE_RECEIPT_UPLOAD", key=upload_key).first()
    if deleted is not None:
        if deleted.actor_employee_id != actor.pk:
            raise NotFound("水单不存在。")
        raise ReceiptFileError("ORIGINAL_RESULT_DELETED", "该上传记录已随作废单据删除，请勿重试原上传。", status=410)


def create_receipt_upload(*, actor, statement_id, upload_key, uploaded_file, request=None):
    require_no_outer_transaction()
    reject_deleted_upload(upload_key, actor)
    digest = upload_digest(uploaded_file)
    existing = FinanceReceiptUpload.objects.select_related("file").filter(upload_key=upload_key).first()
    if existing:
        if existing.owner_employee_id == actor.pk:
            recovery_path(existing.file_id).unlink(missing_ok=True)
        return replay_upload(existing, actor=actor, statement_id=statement_id, digest=digest)
    statement = ReceivableStatement.objects.filter(pk=statement_id).first()
    if statement is None:
        raise NotFound("对账单不存在。")
    if statement.status != "ACTIVE":
        raise FinanceConflict("STATEMENT_VOID", "已作废对账单不能上传新水单。")
    try:
        file = save_scanned_image(uploaded_file, actor, storage_folder=STORAGE_FOLDER,
            field_label="水单", max_bytes=MAX_RECEIPT_BYTES)
    except ScannerUnavailable as exc:
        raise ReceiptFileError("SCANNER_UNAVAILABLE", "扫描服务不可用，文件实体已清理，失败元数据保留。", status=503) from exc
    except InfectedFile as exc:
        raise ReceiptFileError("FILE_NOT_USABLE", "文件未通过扫描，实体已清理，失败元数据保留。") from exc
    except ValidationError as exc:
        raise ReceiptFileError("FILE_INVALID", exc.detail, status=400) from exc
    # 独立提交清理登记；凭证创建回滚不能抹掉本次文件身份。
    try:
        record_new_file(file)
        audit_upload_file(file, actor, "REGISTERED", request=request)
        with transaction.atomic():
            current = lock_statement(statement_id)
            reject_deleted_upload(upload_key, actor)
            if current.status != "ACTIVE":
                raise FinanceConflict("STATEMENT_VOID", "对账单已作废，不能绑定新上传。")
            upload = FinanceReceiptUpload.objects.create(file=file, owner_employee=actor,
                statement=current, upload_key=upload_key)
            # 跨账单同键插入可能等待旧行删除提交；插入后重查，拒绝复活已删除上传。
            reject_deleted_upload(upload_key, actor)
            write_audit_log(object_type="FINANCE_RECEIPT_UPLOAD", object_id=upload.pk, action="CREATE",
                actor_employee=actor, after_data={"file_id": str(file.pk), "statement_id": str(statement_id)}, request=request)
    except Exception as exc:
        # 这是文件系统补偿边界；清理后保留并重新抛出原内部错误。
        compensate_upload_file(file.pk, actor=actor, request=request, _new_file=file)
        if isinstance(exc, IntegrityError):
            winner = FinanceReceiptUpload.objects.select_related("file").filter(upload_key=upload_key).first()
            if winner:
                return replay_upload(winner, actor=actor, statement_id=statement_id, digest=digest)
        raise
    # 凭证已提交后不能因中间登记清理失败而误删它引用的文件。
    try:
        recovery_path(file.pk).unlink(missing_ok=True)
    except OSError as exc:
        raise ReceiptFileError("FILE_CLEANUP_FAILED", "上传已保存，但中间登记清理失败；重试原上传即可核对。", status=500,
            meta={"upload_id": str(upload.pk), "recovery_action": "RETRY_ORIGINAL_UPLOAD"}) from exc
    return upload, False


def discard_receipt_upload(upload_id, *, actor, request=None):
    require_no_outer_transaction()
    # 阶段一先持久化拒绝绑定的状态，再执行文件系统删除。
    with transaction.atomic():
        upload = FinanceReceiptUpload.objects.select_for_update().select_related("file").filter(
            pk=upload_id, owner_employee=actor).first()
        if upload is None:
            raise NotFound("水单不存在。")
        if upload.status == FinanceReceiptUpload.Status.DISCARDED:
            return upload
        if upload.status == FinanceReceiptUpload.Status.BOUND or file_has_other_references(upload.file, own_upload_id=upload.pk):
            raise FinanceConflict("REFERENCED_RECORD", "水单已有业务引用，不能删除。")
        upload.status = FinanceReceiptUpload.Status.DISCARD_PENDING
        upload.save(update_fields=["status"])
        write_audit_log(object_type="FINANCE_RECEIPT_UPLOAD", object_id=upload.pk, action="DISCARD_PENDING",
            actor_employee=actor, after_data={"status": upload.status}, request=request)
    try:
        with transaction.atomic():
            upload = FinanceReceiptUpload.objects.select_for_update().select_related("file").get(pk=upload.pk)
            if file_has_other_references(upload.file, own_upload_id=upload.pk):
                raise FinanceConflict("REFERENCED_RECORD", "水单已有业务引用，清理已停止。")
            receipt_file_path(upload.file).unlink(missing_ok=True)
    except OSError as exc:
        audit_upload_file(upload.file, actor, "CLEANUP_FAILED", request=request)
        raise ReceiptFileError("FILE_CLEANUP_FAILED", "水单清理失败，已禁止绑定，请重试移除。", status=500,
            meta={"upload_id": str(upload.pk), "status": "DISCARD_PENDING"}) from exc
    with transaction.atomic():
        upload = FinanceReceiptUpload.objects.select_for_update().select_related("file").get(pk=upload.pk)
        if upload.status != FinanceReceiptUpload.Status.DISCARDED:
            upload.status = FinanceReceiptUpload.Status.DISCARDED
            upload.discarded_at = timezone.now()
            upload.save(update_fields=["status", "discarded_at"])
            write_audit_log(object_type="FINANCE_RECEIPT_UPLOAD", object_id=upload.pk, action="DISCARDED",
                actor_employee=actor, after_data={"status": upload.status}, request=request)
        return upload
