from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number

from .models import (
    SampleInventoryLine,
    SampleInventoryReceipt,
    SampleItem,
    SampleRequestStatus,
    SampleWorkflowRecord,
    SampleWorkflowStage,
)


def _snapshot_for_inventory(sample_item):
    sample_product = sample_item.sample_product
    return {
        "category_name_snapshot": sample_product.category_name_snapshot if sample_product else "",
        "product_name_snapshot": (
            sample_product.product_name if sample_product else sample_item.product_description_snapshot
        ),
        "specification_snapshot": (
            sample_item.specification_snapshot
            or (sample_product.specification if sample_product else "")
        ),
        "color_name_snapshot": sample_item.color_name_snapshot,
    }


@transaction.atomic
def create_sample_inventory_receipt(*, items, finished_goods_destination, actor_employee, request=None):
    if actor_employee is None:
        raise PermissionDenied("执行样品入库需要绑定有效员工档案。")

    item_ids = [item["sample_item_id"] for item in items]
    locked_items = {
        item.pk: item
        for item in SampleItem.objects.select_for_update(of=("self",))
        .select_related("sample_request", "sample_product")
        .filter(pk__in=item_ids)
    }
    if len(locked_items) != len(item_ids):
        raise ValidationError({"items": "部分样品明细不存在，请刷新后重新选择。"})

    from apps.inventory.models import (
        FinishedGoodsReceipt,
        FinishedGoodsReceiptSource,
        RecordStatus,
        WarehouseType,
    )
    from apps.inventory.services import lock_finished_goods_locations
    from apps.reference_data.models import ProductionUnit, ReferenceStatus
    from apps.reference_data.pinyin_search import build_pinyin_search

    location = lock_finished_goods_locations([finished_goods_destination["location_id"]]).get(
        str(finished_goods_destination["location_id"]))
    if location is None:
        raise ValidationError({"finished_goods_destination": "成品入库库位不存在。"})
    if (
        location.status != RecordStatus.ACTIVE
        or location.zone.status != RecordStatus.ACTIVE
        or location.zone.warehouse.status != RecordStatus.ACTIVE
        or location.zone.warehouse.warehouse_type != WarehouseType.FINISHED
        or location.zone_id != finished_goods_destination["zone_id"]
        or location.zone.warehouse_id != finished_goods_destination["warehouse_id"]
    ):
        raise Conflict("成品入库位置必须属于所选的正常成品仓、库区和库位。")

    units = {}
    for sample_item in locked_items.values():
        unit_text = sample_item.unit_code.strip()
        unit = ProductionUnit.objects.filter(status=ReferenceStatus.ACTIVE).filter(
            Q(unit_code__iexact=unit_text) | Q(unit_name__iexact=unit_text)
        ).order_by("sort_order", "id").first()
        if unit is None:
            raise ValidationError({"items": f"样品单位“{unit_text}”未在生产维护单位中启用，不能同步到成品库存。"})
        units[sample_item.pk] = unit

    inventory_lines = list(
        SampleInventoryLine.objects.select_for_update().filter(sample_item_id__in=item_ids)
    )
    received_by_item = defaultdict(int)
    for line in inventory_lines:
        received_by_item[line.sample_item_id] += line.received_quantity

    from .inventory_selectors import eligible_sample_items_for_inventory
    eligible_quantities = dict(eligible_sample_items_for_inventory().filter(pk__in=item_ids).values_list('pk', 'remaining_quantity'))

    validated_lines = []
    for submitted_item in items:
        sample_item = locked_items[submitted_item["sample_item_id"]]
        eligible = sample_item.pk in eligible_quantities
        if not eligible:
            raise Conflict("所选样品已不符合入库条件，请刷新后重新选择。")

        cumulative_received = received_by_item[sample_item.pk]
        if cumulative_received != submitted_item["expected_cumulative_received"]:
            raise Conflict("样品入库数量已变化，请刷新可选列表后重试。")
        remaining_quantity = eligible_quantities[sample_item.pk]
        if remaining_quantity <= 0:
            raise Conflict("所选样品已经全部入库，请刷新后重新选择。")
        if submitted_item["received_quantity"] > remaining_quantity:
            raise Conflict(
                f"{sample_item.sample_request.request_number} 当前最多可入库 {remaining_quantity}。"
            )
        validated_lines.append((sample_item, submitted_item))

    now = timezone.now()
    receipt = SampleInventoryReceipt.objects.create(
        receipt_number=next_business_number("SAMPLE_INVENTORY_RECEIPT"),
        submitted_by_employee=actor_employee,
        submitted_at=now,
    )
    created_lines = []
    for sample_item, submitted_item in validated_lines:
        snapshots = _snapshot_for_inventory(sample_item)
        inventory_line = SampleInventoryLine.objects.create(
            receipt=receipt,
            sample_item=sample_item,
            sampling_quantity=sample_item.sample_quantity,
            received_quantity=submitted_item["received_quantity"],
            location=submitted_item["location"],
            **snapshots,
        )
        created_lines.append(inventory_line)
        finished_receipt = FinishedGoodsReceipt.objects.create(
            receipt_number=next_business_number("FINISHED_GOODS_RECEIPT"),
            production_task_product=None,
            source_type=FinishedGoodsReceiptSource.SAMPLE_INVENTORY,
            source_document_number=sample_item.sample_request.request_number,
            source_sample_inventory_line=inventory_line,
            location=location,
            supplier=None,
            task_number_snapshot="",
            order_number_snapshot="",
            category_snapshot=snapshots["category_name_snapshot"][:150],
            product_number_snapshot="",
            product_code_snapshot="",
            product_name_snapshot=snapshots["product_name_snapshot"][:200],
            product_name_pinyin_search=build_pinyin_search(snapshots["product_name_snapshot"]),
            item_number_snapshot="",
            specification_snapshot=snapshots["specification_snapshot"][:300],
            actual_color=snapshots["color_name_snapshot"][:200],
            unit=units[sample_item.pk],
            received_quantity=submitted_item["received_quantity"],
            remaining_quantity=submitted_item["received_quantity"],
            quantity_per_box=None,
            box_count=None,
            tail_quantity=None,
            occupied_box_slots=None,
            remaining_box_slots=None,
            remark=f"来源：样品入库单 {receipt.receipt_number}",
            received_by_employee=actor_employee,
            received_at=now,
        )
        write_audit_log(
            object_type="FINISHED_GOODS_RECEIPT",
            object_id=finished_receipt.pk,
            action="CREATED_FROM_SAMPLE_INVENTORY",
            context_type="SAMPLE_REQUEST",
            context_id=sample_item.sample_request_id,
            actor_employee=actor_employee,
            after_data={
                "receipt_number": finished_receipt.receipt_number,
                "source_sample_receipt_number": receipt.receipt_number,
                "quantity": submitted_item["received_quantity"],
                "location_id": str(location.pk),
            },
            request=request,
        )
    receipt.created_line_count = len(validated_lines)
    return receipt


@transaction.atomic
def delete_sample_inventory_receipt(*, receipt_id, actor_employee):
    if actor_employee is None:
        raise PermissionDenied("删除样品入库单需要绑定有效员工档案。")

    try:
        receipt = SampleInventoryReceipt.objects.select_for_update().get(pk=receipt_id)
    except SampleInventoryReceipt.DoesNotExist as exc:
        raise NotFound("样品入库单不存在。") from exc

    inventory_lines = list(
        SampleInventoryLine.objects.select_for_update().filter(receipt=receipt)
    )
    if any(line.outbound_quantity > 0 or line.loaned_quantity > 0 for line in inventory_lines):
        raise Conflict("该入库单已有出库或借出记录，不能删除。请先删除关联单据。")

    from apps.inventory.models import FinishedGoodsReceipt

    linked_finished_receipts = list(
        FinishedGoodsReceipt.objects.select_for_update().filter(
            source_sample_inventory_line_id__in=[line.pk for line in inventory_lines]
        )
    )
    if any(receipt.remaining_quantity != receipt.received_quantity for receipt in linked_finished_receipts):
        raise Conflict("该样品入库已在成品库存发生出库，不能删除。")

    receipt_object_id = receipt.pk
    before_data = {
        "receipt_number": receipt.receipt_number,
        "line_count": len(inventory_lines),
        "received_quantity": sum(line.received_quantity for line in inventory_lines),
    }
    FinishedGoodsReceipt.objects.filter(pk__in=[item.pk for item in linked_finished_receipts]).delete()
    SampleInventoryLine.objects.filter(receipt=receipt).delete()
    receipt.delete()
    write_audit_log(
        object_type="SampleInventoryReceipt",
        object_id=receipt_object_id,
        action="SAMPLE_INVENTORY_RECEIPT_DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
    )
