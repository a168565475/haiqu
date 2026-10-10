from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number

from .models import SampleInventoryLine, SampleInventoryOutbound, SampleInventoryOutboundLine


@transaction.atomic
def create_sample_inventory_outbound(*, items, actor_employee):
    if actor_employee is None:
        raise PermissionDenied("执行样品出库需要绑定有效员工档案。")

    inventory_line_ids = [item["inventory_line_id"] for item in items]
    locked_lines = {
        line.pk: line
        for line in SampleInventoryLine.objects.select_for_update(of=("self",))
        .select_related("receipt", "sample_item", "sample_item__sample_request")
        .filter(pk__in=inventory_line_ids)
    }
    if len(locked_lines) != len(inventory_line_ids):
        raise ValidationError({"items": "部分入库批次明细不存在，请刷新后重新选择。"})

    from apps.inventory.models import FinishedGoodsReceipt

    linked_receipts = {
        receipt.source_sample_inventory_line_id: receipt
        for receipt in FinishedGoodsReceipt.objects.select_for_update().filter(
            source_sample_inventory_line_id__in=inventory_line_ids
        )
    }

    validated_lines = []
    for submitted_item in items:
        inventory_line = locked_lines[submitted_item["inventory_line_id"]]
        available_quantity = (
            inventory_line.received_quantity
            - inventory_line.outbound_quantity
            - inventory_line.loaned_quantity
        )
        if available_quantity != submitted_item["expected_available_quantity"]:
            raise Conflict("样品可用库存已变化，请刷新可选列表后重试。")
        if available_quantity <= 0:
            raise Conflict("所选入库批次已无可用库存，请刷新后重新选择。")
        if submitted_item["outbound_quantity"] > available_quantity:
            raise Conflict(
                f"{inventory_line.receipt.receipt_number} 当前最多可出库 {available_quantity}。"
            )
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt and linked_receipt.remaining_quantity != available_quantity:
            raise Conflict("样品库与成品库存数量不一致，请联系管理员核对后再操作。")
        validated_lines.append((inventory_line, submitted_item))

    now = timezone.now()
    outbound = SampleInventoryOutbound.objects.create(
        outbound_number=next_business_number("SAMPLE_INVENTORY_OUTBOUND"),
        operated_by_employee=actor_employee,
        operated_at=now,
    )
    SampleInventoryOutboundLine.objects.bulk_create(
        [
            SampleInventoryOutboundLine(
                outbound=outbound,
                inventory_line=inventory_line,
                outbound_quantity=submitted_item["outbound_quantity"],
                outbound_method=submitted_item["outbound_method"],
                courier_company=submitted_item["courier_company"],
                tracking_number=submitted_item["tracking_number"],
                remark=submitted_item["remark"],
            )
            for inventory_line, submitted_item in validated_lines
        ]
    )
    for inventory_line, submitted_item in validated_lines:
        inventory_line.outbound_quantity += submitted_item["outbound_quantity"]
        inventory_line.updated_at = now
    SampleInventoryLine.objects.bulk_update(
        [inventory_line for inventory_line, _ in validated_lines],
        ["outbound_quantity", "updated_at"],
    )
    for inventory_line, submitted_item in validated_lines:
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt:
            linked_receipt.remaining_quantity -= submitted_item["outbound_quantity"]
            linked_receipt.remaining_box_slots = None
            linked_receipt.updated_at = now
    FinishedGoodsReceipt.objects.bulk_update(
        list(linked_receipts.values()),
        ["remaining_quantity", "remaining_box_slots", "updated_at"],
    )
    outbound.created_line_count = len(validated_lines)
    return outbound


@transaction.atomic
def delete_sample_inventory_outbound(*, outbound_id, actor_employee):
    if actor_employee is None:
        raise PermissionDenied("删除样品出库单需要绑定有效员工档案。")

    try:
        outbound = SampleInventoryOutbound.objects.select_for_update().get(pk=outbound_id)
    except SampleInventoryOutbound.DoesNotExist as exc:
        raise NotFound("样品出库单不存在。") from exc

    outbound_lines = list(
        SampleInventoryOutboundLine.objects.select_for_update().filter(outbound=outbound)
    )
    inventory_line_ids = [line.inventory_line_id for line in outbound_lines]
    locked_inventory_lines = {
        line.pk: line
        for line in SampleInventoryLine.objects.select_for_update().filter(
            pk__in=inventory_line_ids
        )
    }
    if len(locked_inventory_lines) != len(inventory_line_ids):
        raise Conflict("关联的库存明细不存在，无法安全删除该出库单。")

    from apps.inventory.models import FinishedGoodsReceipt

    linked_receipts = {
        receipt.source_sample_inventory_line_id: receipt
        for receipt in FinishedGoodsReceipt.objects.select_for_update().filter(
            source_sample_inventory_line_id__in=inventory_line_ids
        )
    }

    now = timezone.now()
    for outbound_line in outbound_lines:
        inventory_line = locked_inventory_lines[outbound_line.inventory_line_id]
        if inventory_line.outbound_quantity < outbound_line.outbound_quantity:
            raise Conflict("库存出库数量异常，无法安全删除该出库单。")
        inventory_line.outbound_quantity -= outbound_line.outbound_quantity
        inventory_line.updated_at = now
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt:
            if linked_receipt.remaining_quantity + outbound_line.outbound_quantity > linked_receipt.received_quantity:
                raise Conflict("成品库存数量异常，无法安全删除该样品出库单。")
            linked_receipt.remaining_quantity += outbound_line.outbound_quantity
            linked_receipt.remaining_box_slots = None
            linked_receipt.updated_at = now

    SampleInventoryLine.objects.bulk_update(
        list(locked_inventory_lines.values()),
        ["outbound_quantity", "updated_at"],
    )
    FinishedGoodsReceipt.objects.bulk_update(
        list(linked_receipts.values()),
        ["remaining_quantity", "remaining_box_slots", "updated_at"],
    )
    outbound_object_id = outbound.pk
    before_data = {
        "outbound_number": outbound.outbound_number,
        "line_count": len(outbound_lines),
        "outbound_quantity": sum(line.outbound_quantity for line in outbound_lines),
    }
    SampleInventoryOutboundLine.objects.filter(outbound=outbound).delete()
    outbound.delete()
    write_audit_log(
        object_type="SampleInventoryOutbound",
        object_id=outbound_object_id,
        action="SAMPLE_INVENTORY_OUTBOUND_DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
    )
