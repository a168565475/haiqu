"""订金与货款共用；调用方须已开启事务并锁定所属账单及所选订金。"""
from django.db import transaction
from django.utils import timezone

from apps.core.api.concurrency import etag_for_instance
from apps.core.audit import write_audit_log
from apps.reference_data.models import Currency
from .exceptions import FinanceConflict
from .models import FinanceAccount
from .receipt_exceptions import ReceiptValidationError
from .receipt_models import FinanceReceiptUpload, Receipt, ReceiptAccountLine, ReceiptAttachment
from .services import require_receipt_account
from .settlement_totals import SettlementAmountError, sum_money


def statement_has_active_receipts(statement_id):
    """U03 在持有账单锁后调用；同时检查订金和货款。"""
    return Receipt.objects.filter(statement_id=statement_id, status=Receipt.Status.ACTIVE).exists()


def lock_receipt_accounts(account_lines):
    """返回 {UUID: FinanceAccount}；按币种 UUID → 账户 UUID 稳定加锁。"""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("账户锁定必须在收款事务中执行。")
    account_ids = sorted({line["account_id"] for line in account_lines}, key=str)
    currency_ids = set(FinanceAccount.objects.filter(pk__in=account_ids).values_list("currency_id", flat=True))
    currencies = {item.pk: item for item in Currency.objects.select_for_update().filter(pk__in=currency_ids).order_by("pk")}
    accounts = {item.pk: item for item in FinanceAccount.objects.select_for_update().filter(pk__in=account_ids).order_by("pk")}
    for line in account_lines:
        account = accounts.get(line["account_id"])
        if account is None:
            raise FinanceConflict("ACCOUNT_UNAVAILABLE", "账户已不可用，请重新选择。")
        # 不在账户锁之后补锁新币种；币种被同时更换时让用户重读，避免反向锁序。
        if account.currency_id not in currencies or etag_for_instance(account) != line["account_etag"]:
            raise FinanceConflict("ACCOUNT_CHANGED", "账户资料已变化，请刷新并重新确认。")
        account.currency = currencies[account.currency_id]
        require_receipt_account(account)
    return accounts


def receipt_account_snapshot(account):
    return {"account_type": account.account_type, "code": account.code, "category": account.category,
        "name": account.name, "account_number": account.account_number, "status": account.status,
        "currency_id": str(account.currency_id), "currency_code": account.currency.code}


def account_line_totals(account_lines):
    try:
        return (sum_money(line["cash_amount"] for line in account_lines),
            sum_money(line["fee_amount"] for line in account_lines))
    except SettlementAmountError as exc:
        raise ReceiptValidationError(exc.code, {"account_lines": str(exc)}, meta=exc.meta) from exc


def create_receipt_account_lines(receipt, account_lines, locked_accounts):
    return ReceiptAccountLine.objects.bulk_create([
        ReceiptAccountLine(receipt=receipt, account=locked_accounts[line["account_id"]],
            line_number=index, account_snapshot=receipt_account_snapshot(locked_accounts[line["account_id"]]),
            cash_amount=line["cash_amount"], fee_amount=line["fee_amount"], received_on=line["received_on"])
        for index, line in enumerate(account_lines, 1)
    ])


def lock_receipt_uploads(*, upload_ids, actor, statement, cash_amount):
    """账户锁之后、编号锁之前调用；返回经归属/扫描/实体校验的上传凭证列表。"""
    from .receipt_uploads import require_usable_file
    from rest_framework.exceptions import NotFound

    if cash_amount > 0 and not upload_ids:
        raise ReceiptValidationError("ATTACHMENT_REQUIRED", {"upload_ids": "有新到账必须上传水单。"})
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("水单锁定必须在收款事务中执行。")
    uploads = list(FinanceReceiptUpload.objects.select_for_update(of=("self",)).select_related("file")
        .filter(pk__in=upload_ids, owner_employee=actor, statement=statement).order_by("pk"))
    if len(uploads) != len(upload_ids):
        raise NotFound("水单不存在或不属于当前草稿。")
    for upload in uploads:
        if upload.status != FinanceReceiptUpload.Status.UNBOUND:
            raise FinanceConflict("FILE_NOT_USABLE", "水单已绑定或正在清理，请重新核对。")
        require_usable_file(upload.file)
    return uploads


def bind_receipt_uploads(*, receipt, uploads):
    """仅接收 lock_receipt_uploads 返回的已锁凭证，与收款处于同一事务。"""
    now = timezone.now()
    for upload in uploads:
        ReceiptAttachment.objects.create(receipt=receipt, file=upload.file)
        upload.status = FinanceReceiptUpload.Status.BOUND
        upload.bound_at = now
        upload.save(update_fields=["status", "bound_at"])


def receipt_statement_snapshot(statement, *, outstanding_before, outstanding_after):
    return {"number": statement.number, "production_task_id": str(statement.production_task_id),
        "task_number": statement.task_number_snapshot, "salesperson_id": str(statement.salesperson_id),
        "salesperson_code": statement.salesperson_code_snapshot, "salesperson_name": statement.salesperson_name_snapshot,
        "source_order_date": statement.source_order_date.isoformat(), "amount": str(statement.amount),
        "outstanding_before": str(outstanding_before), "outstanding_after": str(outstanding_after)}


def touch_receipt_statement(statement, actor):
    statement.updated_by_employee = actor
    statement.save(update_fields=["updated_at", "updated_by_employee"])


def audit_receipt(receipt, actor, action, *, request=None):
    write_audit_log(object_type="FINANCE_RECEIPT", object_id=receipt.pk, action=action,
        actor_employee=actor, context_type="RECEIVABLE_STATEMENT", context_id=receipt.statement_id,
        after_data={"number": receipt.number, "status": receipt.status, "receipt_type": receipt.receipt_type,
            "cash_amount": str(receipt.cash_amount), "fee_amount": str(receipt.fee_amount),
            "deposit_amount": str(receipt.deposit_amount), "allocated_deposit_amount": str(receipt.allocated_deposit_amount),
            "discount_amount": str(receipt.discount_amount), "settled_amount": str(receipt.settled_amount),
            "void_reason": receipt.void_reason}, request=request)
