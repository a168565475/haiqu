from django.utils import timezone

from apps.core.api.concurrency import require_matching_etag
from apps.core.daily_numbering import next_daily_business_number
from .exceptions import FinanceConflict
from .receipt_common import account_line_totals, audit_receipt, bind_receipt_uploads, create_receipt_account_lines, lock_receipt_accounts, lock_receipt_uploads, receipt_statement_snapshot, touch_receipt_statement
from .receipt_exceptions import ReceiptValidationError
from .receipt_models import Receipt
from .receipt_selectors import used_deposit_allocations
from .settlement_selectors import settlement_totals_for
from .settlement_totals import SettlementAmountError, sum_money, validate_new_deposit


def create_deposit_receipt_locked(*, request, statement, data, resource_id):
    """公共入口已持账单锁、核验状态/ETag；订金不改变核销口径未付。"""
    totals = settlement_totals_for(statement)
    cash, fee = account_line_totals(data["account_lines"])
    try:
        validate_new_deposit(totals, deposit_amount=cash)
    except SettlementAmountError as exc:
        raise ReceiptValidationError(exc.code, {"account_lines": str(exc)}, meta=exc.meta) from exc
    try:
        sum_money((totals.fee_amount, fee))
    except SettlementAmountError as exc:
        raise ReceiptValidationError(exc.code, {"account_lines": "累计手续费超出允许范围。"}, meta=exc.meta) from exc
    accounts = lock_receipt_accounts(data["account_lines"])
    uploads = lock_receipt_uploads(upload_ids=data["upload_ids"], actor=request.employee, statement=statement, cash_amount=cash)
    receipt = Receipt.objects.create(id=resource_id, number=next_daily_business_number("FINANCE_RECEIPT"),
        statement=statement, receipt_type="DEPOSIT", cash_amount=cash, fee_amount=fee, deposit_amount=cash,
        statement_snapshot=receipt_statement_snapshot(statement, outstanding_before=totals.outstanding_amount,
            outstanding_after=totals.outstanding_amount), created_by_employee=request.employee, updated_by_employee=request.employee)
    create_receipt_account_lines(receipt, data["account_lines"], accounts)
    bind_receipt_uploads(receipt=receipt, uploads=uploads)
    touch_receipt_statement(statement, request.employee)
    audit_receipt(receipt, request.employee, "CREATE", request=request)
    return receipt


def void_deposit_receipt_locked(*, request, statement, receipt_id, reason):
    receipt = Receipt.objects.select_for_update().get(pk=receipt_id, statement=statement)
    require_matching_etag(request, receipt)
    if receipt.status == "VOID":
        return receipt, False
    allocations = used_deposit_allocations(receipt.pk)
    if allocations.exists():
        raise FinanceConflict("DEPOSIT_UNAVAILABLE", "订金已用于货款，请先作废关联货款。",
            meta={"goods_receipts": [{"id": str(value.goods_receipt_id), "number": value.goods_receipt.number}
                for value in allocations.select_related("goods_receipt")]})
    receipt.status = "VOID"
    receipt.void_reason = reason
    receipt.voided_by = request.employee
    receipt.voided_at = timezone.now()
    receipt.updated_by_employee = request.employee
    receipt.save(update_fields=["status", "void_reason", "voided_by", "voided_at", "updated_by_employee", "updated_at"])
    # 以剩余有效记录重算，异常不能以旧快照或零余额代替。
    settlement_totals_for(statement)
    touch_receipt_statement(statement, request.employee)
    audit_receipt(receipt, request.employee, "VOID", request=request)
    return receipt, True
