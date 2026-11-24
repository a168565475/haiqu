from decimal import Decimal


def purchase_inbound_workflow_status(
    *,
    order_status: str,
    has_lines: bool,
    has_remaining_lines: bool,
    pending_quality_count: int,
    received_quantity: Decimal,
    return_status: str,
    can_receive_submitted: bool = False,
) -> tuple[str, str]:
    """采购单在仓库入库链路中的当前状态，供采购列表与入库列表共用。"""
    if order_status not in {"PURCHASING", "COMPLETED"} and not (order_status == "SUBMITTED" and can_receive_submitted):
        return "NOT_STARTED", "—"
    if return_status == "MISSING":
        return "RETURN_RECORD_MISSING", "退货记录待核对"
    if return_status == "QUALITY_GENERATED":
        return "PENDING_PROCUREMENT_CONFIRMATION", "等待确认退货"
    if pending_quality_count:
        return "PENDING_QUALITY", "待品质确认"
    if return_status == "PROCUREMENT_CONFIRMED":
        return "PENDING_RETURN", "等待退货完成"
    if received_quantity > Decimal("0") and has_remaining_lines:
        return "PARTIAL_RECEIVED", "部分入库"
    if has_lines and not has_remaining_lines:
        return "COMPLETED", "已完成"
    return "PENDING_RECEIPT", "等待入库"


def purchase_receiving_status(*, line_count, remaining_line_count, has_received, has_pending_quality, has_open_return):
    if remaining_line_count:
        return "PARTIAL_RECEIVED" if has_received else "PENDING_RECEIPT"
    if not line_count:
        return "PENDING_RECEIPT"
    if has_pending_quality or has_open_return:
        return "RECEIPT_COMPLETE"
    return "COMPLETED"
