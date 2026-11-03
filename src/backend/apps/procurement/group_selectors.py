from decimal import Decimal, localcontext

from django.db.models import Prefetch
from rest_framework.exceptions import ValidationError

from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus
from apps.production_tasks.models import ProductionTaskProduct

from .catalog_materials import purchase_catalog_selection
from .models import (
    PurchaseGroup, PurchaseGroupLine, PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus,
    PurchaseReturnLine, PurchaseReturnStatus,
)


def purchase_groups_with_context(queryset=None):
    queryset = PurchaseGroup.objects.all() if queryset is None else queryset
    batch_lines = PurchaseOrderLine.objects.select_related("purchase_order").prefetch_related("material_inbound_lines__inbound")
    display_lines = PurchaseOrderLine.objects.prefetch_related(Prefetch(
        "material_inbound_lines",
        queryset=MaterialInboundLine.objects.select_related("inbound", "purchase_return_line__return_order"),
    ))
    products = ProductionTaskProduct.objects.select_related("unit").only(
        "id", "production_task_id", "product_name_snapshot", "specification_snapshot", "material_snapshot",
        "color_card_snapshot", "color_name_snapshot", "color_code_snapshot", "quantity", "unit_id", "unit__unit_name",
    )
    return queryset.select_related("production_task", "manual_completed_by_employee").prefetch_related(
        Prefetch("production_task__products", queryset=products, to_attr="purchase_group_products"),
        Prefetch("lines", queryset=PurchaseGroupLine.objects.prefetch_related(Prefetch("batch_lines", queryset=batch_lines))),
        Prefetch("batches", queryset=PurchaseOrder.objects.filter(archived_at__isnull=True)
                 .prefetch_related(Prefetch("lines", queryset=display_lines)).order_by("batch_number", "id")),
    )


def purchase_batch_display_status(order):
    # 自动显示不代替手动结单：保留持久状态、完成记录及其业务权限。
    if not order.purchase_group_id or order.status not in {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING}:
        return order.status
    lines = list(order.lines.all())
    if not lines:
        return order.status
    for line in lines:
        actual = line.actual_purchase_quantity
        if actual is None or not actual.is_finite() or actual <= 0:
            return order.status
        selected = None
        material_id = ""
        if line.material_catalog_id:
            try:
                selected = purchase_catalog_selection(line)
            except ValidationError:
                return order.status
        else:
            if not isinstance(line.calculation_snapshot, dict):
                return order.status
            material_id = str(line.calculation_snapshot.get("raw_material_id") or "")
            if not material_id:
                return order.status
        if not line.source_unit_text.strip():
            return order.status
        accepted = Decimal("0")
        for inbound_line in line.material_inbound_lines.all():
            if (inbound_line.inbound.status != MaterialInboundStatus.CONFIRMED
                    or inbound_line.inbound.purchase_order_id != order.pk
                    or inbound_line.source_unit_text_snapshot != line.source_unit_text):
                return order.status
            if selected is not None:
                if (inbound_line.material_catalog_id != line.material_catalog_id
                        or inbound_line.material_selection_snapshot != selected):
                    return order.status
            elif inbound_line.material_catalog_id or str(inbound_line.raw_material_information_id or "") != material_id:
                return order.status
            quantity, returned = inbound_line.accepted_quantity, inbound_line.return_quantity
            if (quantity is None or not quantity.is_finite() or quantity < 0
                    or returned is None or not returned.is_finite() or returned < 0):
                return order.status
            try:
                return_line = inbound_line.purchase_return_line
            except PurchaseReturnLine.DoesNotExist:
                return_line = None
            if returned > 0 or return_line is not None:
                if (return_line is None or return_line.quantity != returned
                        or return_line.return_order.purchase_order_id != order.pk
                        or return_line.return_order.inbound_id != inbound_line.inbound_id
                        or return_line.return_order.status != PurchaseReturnStatus.COMPLETED):
                    return order.status
            with localcontext() as context:
                context.prec = 64
                accepted += quantity
        if accepted < actual:
            return order.status
    return PurchaseOrderStatus.COMPLETED


def purchase_group_progress(group):
    lines = []
    valid_statuses = {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING, PurchaseOrderStatus.COMPLETED}
    for source in group.lines.all():
        issues = list(source.compatibility_issues)
        purchased, accepted = Decimal("0"), Decimal("0")
        is_pipe = source.source_snapshot.get("section_type_snapshot") == "PROFILE"
        # 根数仅用于展示；历史缺数保持未知，不影响已有米数进度。
        purchased_bars, accepted_bars = (0, 0) if is_pipe else (None, None)
        in_progress = Decimal("0")
        in_progress_bars = 0 if is_pipe else None
        material_id = str(source.source_snapshot.get("calculation_snapshot", {}).get("raw_material_id") or "")
        for line in source.batch_lines.all():
            order = line.purchase_order
            if order.archived_at or order.status not in valid_statuses:
                continue
            if not isinstance(line.calculation_snapshot, dict):
                issues.append("MATERIAL_SNAPSHOT_INVALID")
                continue
            batch_material_id = str(line.calculation_snapshot.get("raw_material_id") or "")
            if "raw_material_id" not in line.calculation_snapshot and not order.batch_request_id and line.raw_material_snapshot == source.source_snapshot.get("raw_material_snapshot"):
                batch_material_id = material_id
            if (order.purchase_group_id != group.pk or line.source_unit_text != source.source_unit_text
                    or line.required_quantity != source.required_quantity
                    or line.source_bom_line_id_snapshot != source.source_bom_line_id_snapshot
                    or batch_material_id != material_id):
                issues.append("BATCH_SOURCE_MISMATCH")
                continue
            if line.actual_purchase_quantity is None or line.actual_purchase_quantity <= 0:
                issues.append("PURCHASE_QUANTITY_INVALID")
                continue
            purchased += line.actual_purchase_quantity
            if is_pipe and purchased_bars is not None:
                purchased_bars = None if line.actual_bar_count is None else purchased_bars + line.actual_bar_count
            is_active = order.status in {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING}
            batch_remaining = line.actual_purchase_quantity
            batch_remaining_bars = line.actual_bar_count if is_pipe else None
            for inbound_line in line.material_inbound_lines.all():
                if inbound_line.inbound.status != MaterialInboundStatus.CONFIRMED:
                    continue
                if (inbound_line.source_unit_text_snapshot != source.source_unit_text
                        or (inbound_line.raw_material_information_id
                            and str(inbound_line.raw_material_information_id) != material_id)):
                    issues.append("INBOUND_IDENTITY_OR_UNIT_MISMATCH")
                    continue
                # accepted_quantity已经扣除质检退货；不再减采购退货单数量。
                accepted += inbound_line.accepted_quantity
                if is_pipe and accepted_bars is not None:
                    accepted_bars = None if inbound_line.accepted_bar_count is None else accepted_bars + inbound_line.accepted_bar_count
                if is_active:
                    with localcontext() as context:
                        context.prec = 64
                        batch_remaining -= inbound_line.accepted_quantity
                    if is_pipe and batch_remaining_bars is not None:
                        batch_remaining_bars = (None if inbound_line.accepted_bar_count is None
                                                else batch_remaining_bars - inbound_line.accepted_bar_count)
            if is_active:
                # 每批单独截零，避免某批超收入库抵消其他批尚未入库的数量。
                with localcontext() as context:
                    context.prec = 64
                    in_progress += max(batch_remaining, Decimal("0"))
                if is_pipe and in_progress_bars is not None:
                    in_progress_bars = (None if batch_remaining_bars is None
                                        else in_progress_bars + max(batch_remaining_bars, 0))
        if source.required_quantity is None or source.required_quantity <= 0:
            issues.append("SUGGESTED_QUANTITY_MISSING")
        with localcontext() as context:
            context.prec = 64
            percent = None if issues else (accepted / source.required_quantity * 100).quantize(Decimal("0.0001"))
        lines.append({
            "id": source.pk, "line_number": source.line_number,
            "source_bom_line_id_snapshot": source.source_bom_line_id_snapshot,
            "product_line_id_snapshot": source.product_line_id_snapshot,
            "required_quantity": source.required_quantity, "source_unit_text": source.source_unit_text,
            "source_snapshot": source.source_snapshot,
            "purchased_quantity": None if issues else purchased,
            "accepted_quantity": None if issues else accepted,
            "purchased_bar_count": None if issues else purchased_bars,
            "accepted_bar_count": None if issues else accepted_bars,
            "in_progress_quantity": None if issues else in_progress,
            "in_progress_bar_count": None if issues else in_progress_bars,
            "progress_percent": percent, "is_satisfied": not issues and accepted >= source.required_quantity,
            "compatibility_issues": sorted(set(issues)),
        })
    satisfied = sum(line["is_satisfied"] for line in lines)
    if not lines or group.compatibility_issues or any(line["compatibility_issues"] for line in lines):
        state = "UNKNOWN"
    elif satisfied == len(lines):
        state = "COMPLETED"
    elif any(line["purchased_quantity"] > 0 for line in lines):
        state = "PURCHASING"
    else:
        state = "PENDING"
    return {"status": state, "satisfied_line_count": satisfied, "line_count": len(lines), "lines": lines}


def purchase_group_completion_summary(group):
    if group.manual_completed_at:
        return {"can_complete": False, "blocked_reason": "采购总单已手动完成。"}
    progress = purchase_group_progress(group)
    if progress["status"] == "UNKNOWN":
        return {"can_complete": False, "blocked_reason": "采购总单来源或数量存在待核对项，请先核对。"}
    has_inbound = False
    for batch in group.batches.all():
        for line in batch.lines.all():
            for inbound_line in line.material_inbound_lines.all():
                if inbound_line.inbound.purchase_order_id != batch.pk:
                    return {"can_complete": False, "blocked_reason": "入库记录与采购批次归属不匹配，请先核对。"}
                has_inbound = True
                if inbound_line.inbound.status != MaterialInboundStatus.CONFIRMED:
                    return {"can_complete": False, "blocked_reason": "仍有到货批次待品质确认，请先完成相应流程。"}
                try:
                    return_line = inbound_line.purchase_return_line
                except PurchaseReturnLine.DoesNotExist:
                    return_line = None
                if inbound_line.return_quantity > 0 or return_line is not None:
                    if (return_line is None or return_line.quantity != inbound_line.return_quantity
                            or return_line.return_order.purchase_order_id != batch.pk
                            or return_line.return_order.inbound_id != inbound_line.inbound_id):
                        return {"can_complete": False, "blocked_reason": "存在未关联或不匹配的品质退货记录，请先核对退货明细。"}
                    if return_line.return_order.status != PurchaseReturnStatus.COMPLETED:
                        return {"can_complete": False, "blocked_reason": "请先在退货明细中完成全部退货。"}
    if not has_inbound:
        return {"can_complete": False, "blocked_reason": "至少需要完成一批到货流程后才能完成采购总单。"}
    return {"can_complete": True, "blocked_reason": ""}
