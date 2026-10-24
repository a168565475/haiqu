"""货款业务分支；公共 Receipt 入口负责权限、幂等及账单锁。"""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.daily_numbering import next_daily_business_number
from .allocation_models import DepositAllocation
from .exceptions import FinanceConflict
from .receipt_common import (
    account_line_totals, audit_receipt, bind_receipt_uploads, create_receipt_account_lines,
    lock_receipt_accounts, lock_receipt_uploads, receipt_statement_snapshot, touch_receipt_statement,
)
from .receipt_exceptions import ReceiptValidationError
from .receipt_models import Receipt
from .settlement_selectors import settlement_totals_for
from .settlement_totals import ZERO, SettlementAmountError, sum_money, validate_goods_settlement


def _require_transaction():
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("货款分支必须在公共收款事务及账单锁内调用。")


def _lock_selected_deposits(statement, data):
    requested = data.get("deposit_allocations")
    deposit_ids = [item["deposit_id"] for item in requested] if requested is not None else data.get("deposit_ids", [])
    if len(set(deposit_ids)) != len(deposit_ids):
        raise ReceiptValidationError("VALIDATION_ERROR", {"deposit_ids": "不能重复选择同一订金。"})
    # 先按归属过滤，绝不在持本账单锁时锁另一账单的订金。
    deposits = list(Receipt.objects.select_for_update().filter(pk__in=deposit_ids,
        statement=statement, receipt_type="DEPOSIT").order_by("pk"))
    if len(deposits) != len(deposit_ids) or any(item.status != "ACTIVE" for item in deposits):
        raise FinanceConflict("DEPOSIT_UNAVAILABLE", "所选订金不属于本对账单、已作废或不可用，请刷新确认。")
    used = dict(DepositAllocation.objects.filter(deposit_receipt__in=deposits, is_active=True)
        .values("deposit_receipt_id").annotate(total=Sum("amount")).values_list("deposit_receipt_id", "total"))
    amounts = {item["deposit_id"]: item["amount"] for item in requested} if requested is not None else {}
    allocations = []
    for deposit in deposits:
        available = deposit.deposit_amount - used.get(deposit.pk, ZERO)
        if available < ZERO:
            raise RuntimeError("订金有效核销金额超过原金额，登记已停止。")
        # 旧客户端仅传编号时，使用锁内剩余全额；新客户端逐笔指定本次核销金额。
        amount = amounts.get(deposit.pk, available)
        if amount <= ZERO or amount > available:
            raise FinanceConflict("DEPOSIT_UNAVAILABLE", "订金核销金额超过当前可用余额，请刷新后核对。",
                meta={"deposit_id": str(deposit.pk), "available_amount": str(available),
                    "recovery_action": "REVIEW_AMOUNTS"})
        allocations.append((deposit, amount))
    return allocations


def create_goods_receipt(*, request, statement, data, resource_id):
    """U04 在幂等占位、锁账单、ACTIVE/If-Match及Serializer成功后调用。"""
    _require_transaction()
    if statement.status != "ACTIVE":
        raise FinanceConflict("STATEMENT_VOID", "对账单已作废，不能登记货款。")
    if data["receipt_type"] != "GOODS":
        raise ReceiptValidationError("RECEIPT_TYPE_FIELDS_INVALID", {"receipt_type": "此分支仅处理货款。"})
    allocations = _lock_selected_deposits(statement, data)
    totals = settlement_totals_for(statement)
    cash, fees = account_line_totals(data["account_lines"])
    try:
        sum_money((totals.fee_amount, fees))
    except SettlementAmountError as exc:
        raise ReceiptValidationError(exc.code, {"account_lines": "累计手续费超出允许金额范围，请核对本次手续费。"},
            meta={"field": "fee_amount", "recovery_action": "REVIEW_AMOUNTS"}) from exc
    try:
        amount = validate_goods_settlement(totals, cash_amount=cash,
            allocated_deposit_amount=sum_money(value for _, value in allocations),
            discount_amount=data.get("discount_amount", ZERO))
    except SettlementAmountError as exc:
        raise ReceiptValidationError(exc.code, {"amounts": str(exc)}, meta=exc.meta) from exc
    accounts = lock_receipt_accounts(data["account_lines"])
    uploads = lock_receipt_uploads(upload_ids=data["upload_ids"], actor=request.employee,
        statement=statement, cash_amount=cash)
    receipt = Receipt.objects.create(id=resource_id, number=next_daily_business_number("FINANCE_RECEIPT"),
        statement=statement, receipt_type="GOODS", cash_amount=cash, fee_amount=fees,
        allocated_deposit_amount=amount.allocated_deposit_amount, discount_amount=amount.discount_amount,
        settled_amount=amount.settled_amount,
        statement_snapshot=receipt_statement_snapshot(statement, outstanding_before=amount.outstanding_before,
            outstanding_after=amount.outstanding_after),
        created_by_employee=request.employee, updated_by_employee=request.employee)
    DepositAllocation.objects.bulk_create([DepositAllocation(goods_receipt=receipt,
        deposit_receipt=deposit, amount=value) for deposit, value in allocations])
    create_receipt_account_lines(receipt, data["account_lines"], accounts)
    bind_receipt_uploads(receipt=receipt, uploads=uploads)
    for deposit, _ in allocations:
        deposit.updated_by_employee = request.employee
        deposit.save(update_fields=["updated_at", "updated_by_employee"])
    touch_receipt_statement(statement, request.employee)
    audit_receipt(receipt, request.employee, "CREATE", request=request)
    return receipt


def void_goods_receipt(*, request, statement, receipt_id, reason):
    """U04先锁所属账单再委派；返回(receipt, changed)，旧ETag即使作废过也拒绝。"""
    _require_transaction()
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ReceiptValidationError("VALIDATION_ERROR", {"reason": "请填写不超过500字的作废原因。"})
    deposit_ids = list(DepositAllocation.objects.filter(goods_receipt_id=receipt_id)
        .values_list("deposit_receipt_id", flat=True))
    locked = {item.pk: item for item in Receipt.objects.select_for_update().filter(
        statement=statement, pk__in=[receipt_id, *deposit_ids]).order_by("pk")}
    receipt = get_object_or_404(Receipt.objects.filter(pk__in=locked, receipt_type="GOODS"), pk=receipt_id)
    receipt = locked[receipt.pk]
    require_matching_etag(request, receipt)
    if receipt.status == "VOID":
        return receipt, False
    allocations = list(DepositAllocation.objects.select_for_update().filter(goods_receipt=receipt, is_active=True).order_by("pk"))
    if sum_money(item.amount for item in allocations) != receipt.allocated_deposit_amount:
        raise RuntimeError("有效货款的订金抵扣记录与合计不一致，作废已停止。")
    now = timezone.now()
    for allocation in allocations:
        deposit = locked.get(allocation.deposit_receipt_id)
        if deposit is None or deposit.receipt_type != "DEPOSIT" or deposit.status != "ACTIVE" or not ZERO < allocation.amount <= deposit.deposit_amount:
            raise RuntimeError("货款抵扣归属或核销金额不一致，作废已停止。")
        allocation.is_active = False
        allocation.voided_at = now
        allocation.save(update_fields=["is_active", "voided_at"])
        deposit.updated_by_employee = request.employee
        deposit.save(update_fields=["updated_at", "updated_by_employee"])
    receipt.status = "VOID"
    receipt.void_reason = reason.strip()
    receipt.voided_at = now
    receipt.voided_by = request.employee
    receipt.updated_by_employee = request.employee
    receipt.save(update_fields=["status", "void_reason", "voided_at", "voided_by", "updated_at", "updated_by_employee"])
    # 不恢复outstanding_before历史快照；保留全部后续有效收款再算余额。
    settlement_totals_for(statement)
    touch_receipt_statement(statement, request.employee)
    audit_receipt(receipt, request.employee, "VOID", request=request)
    return receipt, True
