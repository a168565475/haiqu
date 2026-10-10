from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number

from .models import SampleInventoryLine, SampleInventoryLoan, SampleInventoryLoanLine


@transaction.atomic
def create_sample_inventory_loan(*, items, actor_employee):
    if actor_employee is None:
        raise PermissionDenied("执行样品借出需要绑定有效员工档案。")

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
        if submitted_item["loan_quantity"] > available_quantity:
            raise Conflict(
                f"{inventory_line.receipt.receipt_number} 当前最多可借出 {available_quantity}。"
            )
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt and linked_receipt.remaining_quantity != available_quantity:
            raise Conflict("样品库与成品库存数量不一致，请联系管理员核对后再操作。")
        validated_lines.append((inventory_line, submitted_item))

    now = timezone.now()
    loan = SampleInventoryLoan.objects.create(
        loan_number=next_business_number("SAMPLE_INVENTORY_LOAN"),
        operated_by_employee=actor_employee,
        operated_at=now,
    )
    SampleInventoryLoanLine.objects.bulk_create(
        [
            SampleInventoryLoanLine(
                loan=loan,
                inventory_line=inventory_line,
                loan_quantity=submitted_item["loan_quantity"],
                borrower_name=submitted_item["borrower_name"],
                purpose_note=submitted_item["purpose_note"],
            )
            for inventory_line, submitted_item in validated_lines
        ]
    )
    for inventory_line, submitted_item in validated_lines:
        inventory_line.loaned_quantity += submitted_item["loan_quantity"]
        inventory_line.updated_at = now
    SampleInventoryLine.objects.bulk_update(
        [inventory_line for inventory_line, _ in validated_lines],
        ["loaned_quantity", "updated_at"],
    )
    for inventory_line, submitted_item in validated_lines:
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt:
            linked_receipt.remaining_quantity -= submitted_item["loan_quantity"]
            linked_receipt.remaining_box_slots = None
            linked_receipt.updated_at = now
    FinishedGoodsReceipt.objects.bulk_update(
        list(linked_receipts.values()),
        ["remaining_quantity", "remaining_box_slots", "updated_at"],
    )
    loan.created_line_count = len(validated_lines)
    return loan


@transaction.atomic
def delete_sample_inventory_loan(*, loan_id, actor_employee):
    if actor_employee is None:
        raise PermissionDenied("删除样品借出单需要绑定有效员工档案。")

    try:
        loan = SampleInventoryLoan.objects.select_for_update().get(pk=loan_id)
    except SampleInventoryLoan.DoesNotExist as exc:
        raise NotFound("样品借出单不存在。") from exc

    loan_lines = list(SampleInventoryLoanLine.objects.select_for_update().filter(loan=loan))
    inventory_line_ids = [line.inventory_line_id for line in loan_lines]
    locked_inventory_lines = {
        line.pk: line
        for line in SampleInventoryLine.objects.select_for_update().filter(
            pk__in=inventory_line_ids
        )
    }
    if len(locked_inventory_lines) != len(inventory_line_ids):
        raise Conflict("关联的库存明细不存在，无法安全删除该借出单。")

    from apps.inventory.models import FinishedGoodsReceipt

    linked_receipts = {
        receipt.source_sample_inventory_line_id: receipt
        for receipt in FinishedGoodsReceipt.objects.select_for_update().filter(
            source_sample_inventory_line_id__in=inventory_line_ids
        )
    }

    now = timezone.now()
    for loan_line in loan_lines:
        inventory_line = locked_inventory_lines[loan_line.inventory_line_id]
        if inventory_line.loaned_quantity < loan_line.loan_quantity:
            raise Conflict("库存借出数量异常，无法安全删除该借出单。")
        inventory_line.loaned_quantity -= loan_line.loan_quantity
        inventory_line.updated_at = now
        linked_receipt = linked_receipts.get(inventory_line.pk)
        if linked_receipt:
            if linked_receipt.remaining_quantity + loan_line.loan_quantity > linked_receipt.received_quantity:
                raise Conflict("成品库存数量异常，无法安全删除该样品借出单。")
            linked_receipt.remaining_quantity += loan_line.loan_quantity
            linked_receipt.remaining_box_slots = None
            linked_receipt.updated_at = now

    SampleInventoryLine.objects.bulk_update(
        list(locked_inventory_lines.values()),
        ["loaned_quantity", "updated_at"],
    )
    FinishedGoodsReceipt.objects.bulk_update(
        list(linked_receipts.values()),
        ["remaining_quantity", "remaining_box_slots", "updated_at"],
    )
    loan_object_id = loan.pk
    before_data = {
        "loan_number": loan.loan_number,
        "line_count": len(loan_lines),
        "loan_quantity": sum(line.loan_quantity for line in loan_lines),
    }
    SampleInventoryLoanLine.objects.filter(loan=loan).delete()
    loan.delete()
    write_audit_log(
        object_type="SampleInventoryLoan",
        object_id=loan_object_id,
        action="SAMPLE_INVENTORY_LOAN_DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
    )
