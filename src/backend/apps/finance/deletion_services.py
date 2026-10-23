"""已作废财务单据的物理删除；保留审计及幂等键，不改变有效余额。"""
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.files.models import BusinessFile
from .exceptions import FinanceConflict
from .models import FinanceMutationKey
from .receipt_exceptions import ReceiptFileError
from .receipt_models import FinanceReceiptUpload, Receipt, ReceiptAccountLine, ReceiptAttachment
from .receipt_uploads import has_recovery_record, receipt_file_path, recovery_path, require_no_outer_transaction
from .statement_locks import lock_statement
from .statement_models import ReceivableStatement, ReceivableStatementLine


def statement_delete_block_reason(statement):
    if statement.status != "VOID":
        return "请先作废对账单。"
    has_receipts = getattr(statement, "_has_receipts", None)
    if has_receipts is None:
        has_receipts = statement.receipts.exists()
    if has_receipts:
        return "请先删除该对账单下的收款单。"
    has_occupied = getattr(statement, "_has_occupied_lines", None)
    if has_occupied is None:
        has_occupied = statement.lines.filter(is_occupied=True).exists()
    return "对账单仍有产品行占用，请先核对作废结果。" if has_occupied else None


def receipt_delete_block_reason(receipt):
    if receipt.status != "VOID":
        return "请先作废收款单。"
    has_references = getattr(receipt, "_has_deposit_references", None)
    if has_references is None:
        has_references = receipt.deposit_allocations.exists()
    if has_references:
        return "请先删除引用该订金的货款单。"
    has_active = getattr(receipt, "_has_active_allocations", None)
    if has_active is None:
        has_active = receipt.allocations.filter(is_active=True).exists()
    return "收款单仍有有效抵扣，请先核对作废结果。" if has_active else None


def lock_target(request, pk, *, receipt):
    if receipt:
        target = get_object_or_404(Receipt.objects.only("statement_id"), pk=pk)
        statement = lock_statement(target.statement_id)
        target = get_object_or_404(Receipt.objects.select_for_update(), pk=pk)
        reason = receipt_delete_block_reason(target)
    else:
        from .statement_services import lock_tasks
        current = get_object_or_404(ReceivableStatement.objects.only("production_task_id"), pk=pk)
        lock_tasks([current.production_task_id])
        target = lock_statement(pk)
        statement = target
        reason = statement_delete_block_reason(target)
    require_matching_etag(request, target)
    if reason:
        raise FinanceConflict("DELETE_BLOCKED", reason)
    from .allocation_models import DepositAllocation
    owned_models = {ReceiptAccountLine, ReceiptAttachment, DepositAllocation} if receipt else {
        ReceivableStatementLine, FinanceReceiptUpload, Receipt}
    for relation in target._meta.related_objects:
        if relation.related_model not in owned_models and relation.related_model.objects.filter(
                **{relation.field.name: target}).exists():
            raise FinanceConflict("REFERENCED_RECORD", "单据被其他业务引用，不能删除。")
    return target, statement


def locked_files(target, statement, *, receipt):
    file_ids = list(target.attachments.values_list("file_id", flat=True)) if receipt else list(
        statement.receipt_uploads.values_list("file_id", flat=True))
    uploads = list(FinanceReceiptUpload.objects.select_for_update().filter(file_id__in=file_ids).order_by("pk"))
    if any(upload.statement_id != statement.pk for upload in uploads):
        raise FinanceConflict("REFERENCED_RECORD", "水单关联不一致，删除已停止。")
    files = list(BusinessFile.objects.select_for_update().filter(pk__in=file_ids).order_by("pk"))
    for file in files:
        receipt_file_path(file)
        if recovery_path(file.pk).exists() and not has_recovery_record(file):
            raise FinanceConflict("REFERENCED_RECORD", "水单恢复登记不匹配，删除已停止。")
        for relation in file._meta.related_objects:
            rows = relation.related_model.objects.filter(**{relation.field.name: file})
            if relation.related_model is FinanceReceiptUpload:
                rows = rows.exclude(pk__in=[upload.pk for upload in uploads])
            if receipt and relation.related_model is ReceiptAttachment:
                rows = rows.exclude(receipt=target)
            if rows.exists():
                raise FinanceConflict("REFERENCED_RECORD", "水单被其他业务引用，不能删除。")
    return files, uploads


def deletion_snapshot(target, files, *, receipt):
    data = {"number": target.number, "status": target.status, "void_reason": target.void_reason,
            "file_ids": [str(file.pk) for file in files]}
    if receipt:
        data.update(statement_id=str(target.statement_id), receipt_type=target.receipt_type,
                    cash_amount=str(target.cash_amount), settled_amount=str(target.settled_amount),
                    discount_amount=str(target.discount_amount))
    else:
        data.update(production_task_id=str(target.production_task_id), amount=str(target.amount))
    return data


def delete_void_document(request, pk, *, receipt):
    require_no_outer_transaction()
    object_type = "FINANCE_RECEIPT" if receipt else "RECEIVABLE_STATEMENT"
    # 先持久化删除意图。磁盘不参与数据库回滚；失败时保留 VOID 单据及关联，原请求可重试。
    with transaction.atomic():
        target, statement = lock_target(request, pk, receipt=receipt)
        files, _ = locked_files(target, statement, receipt=receipt)
        snapshot = deletion_snapshot(target, files, receipt=receipt)
        write_audit_log(object_type=object_type, object_id=pk, action="DELETE_REQUESTED",
                        actor_employee=request.employee, before_data=snapshot, request=request)
    try:
        with transaction.atomic():
            target, statement = lock_target(request, pk, receipt=receipt)
            files, uploads = locked_files(target, statement, receipt=receipt)
            for file in files:
                receipt_file_path(file).unlink(missing_ok=True)
                recovery_path(file.pk).unlink(missing_ok=True)
            if receipt:
                target.allocations.all().delete()
                target.account_lines.all().delete()
                target.attachments.all().delete()
            else:
                target.lines.all().delete()
            # 留下上传标识墓碑，迟到重试不能重新生成已删除单据的水单。
            file_hashes = {file.pk: file.content_hash for file in files}
            for upload in uploads:
                FinanceMutationKey.objects.get_or_create(actor_employee_id=upload.owner_employee_id,
                    action="DELETE_RECEIPT_UPLOAD", key=upload.upload_key,
                    defaults={"request_hash": file_hashes[upload.file_id], "resource_id": upload.pk})
            FinanceReceiptUpload.objects.filter(pk__in=[upload.pk for upload in uploads]).delete()
            BusinessFile.objects.filter(pk__in=[file.pk for file in files]).delete()
            target.delete()
            write_audit_log(object_type=object_type, object_id=pk, action="DELETE",
                            actor_employee=request.employee, before_data=snapshot, after_data={}, request=request)
    except OSError as exc:
        write_audit_log(object_type=object_type, object_id=pk, action="DELETE_CLEANUP_FAILED",
                        actor_employee=request.employee, before_data=snapshot, request=request)
        raise ReceiptFileError("FILE_CLEANUP_FAILED", "水单清理未完成，单据仍保留；部分水单可能已清理，请重试删除。", status=500) from exc
    except (ProtectedError, RestrictedError) as exc:
        raise FinanceConflict("REFERENCED_RECORD", "单据仍被其他数据引用，删除未完成，请核对关联记录。") from exc


def delete_statement(request, pk):
    return delete_void_document(request, pk, receipt=False)


def delete_receipt(request, pk):
    return delete_void_document(request, pk, receipt=True)
