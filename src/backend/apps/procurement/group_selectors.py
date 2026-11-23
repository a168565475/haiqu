from decimal import Decimal, localcontext

from django.db.models import Exists, Max, OuterRef, Prefetch, Q
from rest_framework.exceptions import ValidationError

from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus
from apps.inventory.pipe_receipt_basis import allocated_order_kg, is_root_receipt, root_receipt_line_ids
from apps.production_tasks.models import ProductionTaskProduct

from .catalog_materials import is_weight_purchase, purchase_catalog_selection
from .multi_bom_sources import matches_combined_source
from .tracking_rules import decimal_value, root_count_value
from .models import (
    PurchaseGroup, PurchaseGroupBomSource, PurchaseGroupLine, PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus,
    PurchaseReturnLine, PurchaseReturnStatus,
)


def purchase_groups_with_context(queryset=None):
    queryset = PurchaseGroup.objects.all() if queryset is None else queryset
    # 删除资格必须包括已归档批次，不能由页面进度或可见批次数推断。
    all_batches = PurchaseOrder.objects.filter(purchase_group_id=OuterRef("pk"))
    queryset = queryset.annotate(
        delete_has_purchase=Exists(all_batches.filter(
            ~Q(status=PurchaseOrderStatus.DRAFT) | Q(completed_at__isnull=False),
        )),
        delete_has_documents=Exists(all_batches.filter(
            Q(supplier_purchase_sheets__isnull=False) | Q(material_inbounds__isnull=False)
            | Q(returns__isnull=False) | Q(lines__material_inbound_lines__isnull=False)
            | Q(lines__purchase_payable_lines__isnull=False) | Q(lines__sample_material_source__isnull=False),
        )),
        delete_has_foreign_lines=Exists(PurchaseOrderLine.objects.filter(
            purchase_group_line__purchase_group_id=OuterRef("pk"),
        ).exclude(purchase_order__purchase_group_id=OuterRef("pk"))),
    )
    batch_lines = PurchaseOrderLine.objects.select_related("purchase_order").prefetch_related(Prefetch(
        "material_inbound_lines", queryset=MaterialInboundLine.objects.select_related("inbound", "purchase_return_line__return_order"),
    ))
    display_lines = PurchaseOrderLine.objects.prefetch_related(Prefetch(
        "material_inbound_lines",
        queryset=MaterialInboundLine.objects.select_related("inbound", "purchase_return_line__return_order"),
    ))
    products = ProductionTaskProduct.objects.select_related("unit").only(
        "id", "production_task_id", "product_name_snapshot", "specification_snapshot", "material_snapshot",
        "color_card_snapshot", "color_name_snapshot", "color_code_snapshot", "quantity", "unit_id", "unit__unit_name",
    )
    source_lines = PurchaseGroupLine.objects.prefetch_related(Prefetch("batch_lines", queryset=batch_lines))
    return queryset.select_related("production_task", "manual_completed_by_employee").prefetch_related(
        Prefetch("bom_sources", queryset=PurchaseGroupBomSource.objects.select_related("previous_group").prefetch_related(
            Prefetch("previous_group__lines", queryset=source_lines))),
        "combined_into_sources",
        Prefetch("production_task__products", queryset=products, to_attr="purchase_group_products"),
        Prefetch("lines", queryset=source_lines),
        Prefetch("batches", queryset=PurchaseOrder.objects.filter(archived_at__isnull=True)
                 .prefetch_related(Prefetch("lines", queryset=display_lines)).order_by("batch_number", "id")),
    )


def purchase_group_batch_numbers(group_id, batch_session_id=None):
    # 已归档的采购单也占用发出的批次号。
    aggregates = {"latest": Max("batch_number")}
    if batch_session_id:
        aggregates["current"] = Max("batch_number", filter=Q(batch_session_id=batch_session_id))
    numbers = PurchaseOrder.objects.filter(purchase_group_id=group_id).aggregate(**aggregates)
    return numbers.get("current"), (numbers["latest"] or 0) + 1


def purchase_group_deletion_summary(group):
    if group.combined_into_sources.all():
        reason = "本需求已并入合并采购，需保留原单据供追溯。"
    elif group.manual_completed_at:
        reason = "采购需求已完成，不能删除。"
    elif group.delete_has_purchase:
        reason = "已有确认采购或已完成的批次，不能删除采购需求。"
    elif group.delete_has_documents:
        reason = "已有关联供应商采购表、入库、退货或其他后续记录，不能删除采购需求。"
    elif group.delete_has_foreign_lines:
        reason = "采购需求材料被其他采购批次引用，请先核对关联记录。"
    else:
        reason = ""
    return {"can_delete": not reason, "blocked_reason": reason}


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
            if is_root_receipt(inbound_line):
                actual = line.actual_bar_count
                quantity, returned = Decimal(inbound_line.accepted_bar_count), Decimal(inbound_line.return_bar_count)
            elif is_weight_purchase(line):
                quantity, returned = inbound_line.accepted_weight_kg, inbound_line.return_weight_kg
            else:
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


def previous_group_lines(group):
    if not any(isinstance(line.source_snapshot, dict) and "source_contributions" in line.source_snapshot
               for line in group.lines.all()):
        return {}
    return {str(line.pk): line for membership in group.bom_sources.all() if membership.previous_group_id
            for line in membership.previous_group.lines.all()}


def purchase_group_progress(group):
    lines = []
    external_supply_line_ids = []
    valid_statuses = {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING, PurchaseOrderStatus.COMPLETED}
    previous_lines = previous_group_lines(group)
    root_ids = root_receipt_line_ids(line for source in [*group.lines.all(), *previous_lines.values()]
        if source.source_unit_text == 'KG' for line in source.batch_lines.all()
        if line.section_type_snapshot == 'PROFILE' and not line.material_inbound_lines.all())
    for source in group.lines.all():
        issues = list(source.compatibility_issues)
        snapshot = source.source_snapshot
        if not isinstance(snapshot, dict):
            issues.append("MATERIAL_SNAPSHOT_INVALID")
            snapshot = {}
        if snapshot.get("purchase_required") is False:
            external_supply_line_ids.append(str(source.pk))
            continue
        calculation = snapshot.get("calculation_snapshot", {})
        if not isinstance(calculation, dict):
            issues.append("MATERIAL_SNAPSHOT_INVALID")
            calculation = {}
        purchased, accepted, planned = Decimal("0"), Decimal("0"), Decimal("0")
        is_pipe = snapshot.get("section_type_snapshot") == "PROFILE"
        is_weight = source.source_unit_text == "KG" and (is_pipe or
            calculation.get("measurement_kind") == "HARDWARE_WEIGHT")
        required_bars = root_count_value(snapshot.get('suggested_bar_count'))
        roots_only = is_pipe and is_weight and required_bars is not None
        purchased_bars, accepted_bars = (0, 0) if is_pipe else (None, None)
        in_progress = Decimal("0")
        in_progress_bars = 0 if is_pipe else None
        material_id = str(calculation.get("raw_material_id") or "")
        related_sources = [source]
        inherited_ids = {item["previous_group_line_id"] for item in snapshot.get("source_contributions", [])
                         if item.get("previous_group_line_id")}
        inherited_ids.update(snapshot.get("previous_group_line_ids", []))
        if inherited_ids - previous_lines.keys():
            issues.append("BATCH_SOURCE_MISMATCH")
        related_sources.extend(previous_lines[key] for key in inherited_ids if key in previous_lines)
        for origin, line in ((origin, line) for origin in related_sources for line in origin.batch_lines.all()):
            order = line.purchase_order
            if order.archived_at:
                continue
            if order.status == PurchaseOrderStatus.DRAFT:
                if line.source_unit_text == source.source_unit_text:
                    planned += line.actual_purchase_quantity or Decimal("0")
                continue
            if order.status not in valid_statuses:
                continue
            if not isinstance(line.calculation_snapshot, dict):
                issues.append("MATERIAL_SNAPSHOT_INVALID")
                continue
            batch_material_id = str(line.calculation_snapshot.get("raw_material_id") or "")
            if "raw_material_id" not in line.calculation_snapshot and not order.batch_request_id and line.raw_material_snapshot == snapshot.get("raw_material_snapshot"):
                batch_material_id = material_id
            frozen_match = (line.required_quantity == origin.required_quantity
                            and line.source_bom_line_id_snapshot == origin.source_bom_line_id_snapshot)
            if (order.purchase_group_id != (group.pk if origin is source else origin.purchase_group_id)
                    or line.source_unit_text != source.source_unit_text
                    or not (frozen_match or matches_combined_source(line, origin))
                    or batch_material_id != material_id):
                issues.append("BATCH_SOURCE_MISMATCH")
                continue
            if line.actual_purchase_quantity is None or line.actual_purchase_quantity <= 0:
                issues.append("PURCHASE_QUANTITY_INVALID")
                continue
            purchased += line.actual_purchase_quantity
            planned += line.actual_purchase_quantity
            receipts = line.material_inbound_lines.all()
            root_receipt = is_weight and is_pipe and (is_root_receipt(receipts[0]) if receipts else line.pk in root_ids)
            roots_only = roots_only and root_receipt
            if is_pipe and purchased_bars is not None:
                purchased_bars = None if line.actual_bar_count is None else purchased_bars + line.actual_bar_count
            is_active = order.status in {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING}
            batch_remaining = line.actual_purchase_quantity
            batch_remaining_bars = line.actual_bar_count if is_pipe else None
            for inbound_line in receipts:
                if inbound_line.inbound.status != MaterialInboundStatus.CONFIRMED:
                    if root_receipt and is_active:
                        batch_remaining_bars -= inbound_line.received_bar_count
                    continue
                if (inbound_line.source_unit_text_snapshot != source.source_unit_text
                        or (inbound_line.raw_material_information_id
                            and str(inbound_line.raw_material_information_id) != material_id)):
                    issues.append("INBOUND_IDENTITY_OR_UNIT_MISMATCH")
                    continue
                if root_receipt:
                    quantity = decimal_value(inbound_line.calculation_snapshot.get('settlement_weight_kg'))
                else:
                    quantity = inbound_line.accepted_weight_kg if is_weight else inbound_line.accepted_quantity
                if is_weight and (quantity is None or not quantity.is_finite() or quantity < 0):
                    issues.append("INBOUND_WEIGHT_MISSING_OR_INVALID")
                    continue
                # 合格数量已经扣除质检退货；不再减采购退货单数量。
                accepted += quantity
                if is_pipe and accepted_bars is not None:
                    accepted_bars = None if inbound_line.accepted_bar_count is None else accepted_bars + inbound_line.accepted_bar_count
                if is_active:
                    with localcontext() as context:
                        context.prec = 64
                        batch_remaining -= quantity
                    if is_pipe and batch_remaining_bars is not None:
                        batch_remaining_bars = (None if inbound_line.accepted_bar_count is None
                                                else batch_remaining_bars - inbound_line.accepted_bar_count)
            if is_active:
                # 每批单独截零，避免某批超收入库抵消其他批尚未入库的数量。
                if root_receipt:
                    occupied_bars = line.actual_bar_count - max(batch_remaining_bars, 0)
                    batch_remaining = line.actual_purchase_quantity - allocated_order_kg(line, occupied_bars)
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
            target = Decimal(required_bars) if roots_only else source.required_quantity
            done = accepted_bars if roots_only else accepted
            percent = None if issues else (done / target * 100).quantize(Decimal("0.0001"))
        lines.append({
            "id": source.pk, "line_number": source.line_number,
            "source_bom_line_id_snapshot": source.source_bom_line_id_snapshot,
            "product_line_id_snapshot": source.product_line_id_snapshot,
            "required_quantity": source.required_quantity, "source_unit_text": source.source_unit_text,
            "source_snapshot": snapshot,
            "purchased_quantity": None if issues else purchased,
            "planned_purchase_quantity": None if issues else planned,
            "remaining_purchase_quantity": None if issues else max(source.required_quantity - planned, Decimal("0")),
            "accepted_quantity": None if issues else accepted,
            "purchased_bar_count": None if issues else purchased_bars,
            "accepted_bar_count": None if issues else accepted_bars,
            "in_progress_quantity": None if issues else in_progress,
            "in_progress_bar_count": None if issues else in_progress_bars,
            "receipt_quantity_mode": 'ROOTS' if roots_only else None,
            "progress_percent": percent, "is_satisfied": not issues and done >= target,
            "compatibility_issues": sorted(set(issues)),
        })
    satisfied = sum(line["is_satisfied"] for line in lines)
    if (not lines and not external_supply_line_ids) or group.compatibility_issues or any(line["compatibility_issues"] for line in lines):
        state = "UNKNOWN"
    elif satisfied == len(lines):
        state = "COMPLETED"
    elif any(line["purchased_quantity"] > 0 for line in lines):
        state = "PURCHASING"
    else:
        state = "PENDING"
    return {"status": state, "satisfied_line_count": satisfied, "line_count": len(lines),
            "lines": lines, "external_supply_line_ids": external_supply_line_ids}


def purchase_group_completion_summary(group, *, progress=None):
    if group.manual_completed_at:
        return {"can_complete": False, "blocked_reason": "采购需求已手动完成。"}
    if progress is None:
        progress = purchase_group_progress(group)
    if progress["status"] == "UNKNOWN":
        return {"can_complete": False, "blocked_reason": "采购需求来源或数量存在待核对项，请先核对。"}
    has_inbound = False
    batch_items = [(batch, list(batch.lines.all())) for batch in group.batches.all()]
    for source in previous_group_lines(group).values():
        batch_items.extend((line.purchase_order, [line]) for line in source.batch_lines.all()
                           if not line.purchase_order.archived_at)
    for batch, items in batch_items:
        for line in items:
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
                if is_root_receipt(inbound_line):
                    returned = Decimal(inbound_line.return_bar_count)
                else:
                    returned = inbound_line.return_weight_kg if is_weight_purchase(line) else inbound_line.return_quantity
                if returned is None or not returned.is_finite() or returned < 0:
                    return {"can_complete": False, "blocked_reason": "到货退货数量缺失或无效，请先核对。"}
                if returned > 0 or return_line is not None:
                    if (return_line is None or return_line.quantity != returned
                            or return_line.return_order.purchase_order_id != batch.pk
                            or return_line.return_order.inbound_id != inbound_line.inbound_id):
                        return {"can_complete": False, "blocked_reason": "存在未关联或不匹配的品质退货记录，请先核对退货明细。"}
                    if return_line.return_order.status != PurchaseReturnStatus.COMPLETED:
                        return {"can_complete": False, "blocked_reason": "请先在退货明细中完成全部退货。"}
    if not has_inbound:
        return {"can_complete": False, "blocked_reason": "至少需要完成一批到货流程后才能完成采购需求。"}
    return {"can_complete": True, "blocked_reason": ""}
