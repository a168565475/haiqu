from django.db.models import Exists, Min, OuterRef, Subquery

from .settlement_totals import ZERO


def deposit_options(statement, *, include_unavailable=False):
    """返回可分页的真实QuerySet；include_unavailable用于审阅禁选原因。"""
    from .allocation_models import DepositAllocation
    from .receipt_models import Receipt

    occupied = DepositAllocation.objects.filter(deposit_receipt_id=OuterRef("pk"), is_active=True)
    rows = Receipt.objects.filter(statement=statement, receipt_type="DEPOSIT").annotate(
        is_allocated=Exists(occupied),
        allocated_goods_id=Subquery(occupied.values("goods_receipt_id")[:1]),
        allocated_goods_number=Subquery(occupied.values("goods_receipt__number")[:1]),
        received_on=Min("account_lines__received_on"),
    ).prefetch_related("attachments__file").order_by("created_at", "pk")
    if not include_unavailable:
        rows = rows.filter(status="ACTIVE", is_allocated=False)
    return rows


def deposit_option_data(receipt, totals):
    reason = None
    if receipt.status != "ACTIVE":
        reason = "该订金已作废"
    elif receipt.is_allocated:
        reason = f"已被货款 {receipt.allocated_goods_number} 整笔使用"
    elif receipt.deposit_amount > totals.outstanding_amount:
        reason = "整笔订金超过当前未付，不能拆分使用"
    available = receipt.deposit_amount if receipt.status == "ACTIVE" and not receipt.is_allocated else ZERO
    return {"id": str(receipt.pk), "number": receipt.number, "status": receipt.status,
        "received_on": receipt.received_on.isoformat() if receipt.received_on else None,
        "created_at": receipt.created_at.isoformat(), "deposit_amount": str(receipt.deposit_amount),
        "available_amount": str(available), "can_select": reason is None, "blocked_reason": reason,
        "allocated_goods_id": str(receipt.allocated_goods_id) if receipt.allocated_goods_id else None,
        "allocated_goods_number": receipt.allocated_goods_number,
        "attachments": [{"file_id": str(item.file_id), "original_name": item.file.original_name,
            "size_bytes": item.file.size_bytes, "scan_status": item.file.scan_status,
            "scan_label": "未扫描（当前配置跳过）" if item.file.scan_status == "SKIPPED" else item.file.get_scan_status_display()}
            for item in receipt.attachments.all()]}
