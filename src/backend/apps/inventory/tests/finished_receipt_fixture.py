"""明确构造历史已入库批次，仅用于查询和后续出库回归。"""
import uuid

from apps.inventory.models import FinishedGoodsReceipt, FinishedGoodsReceiptStatus
from apps.inventory.services import packaging_values
from apps.reference_data.pinyin_search import build_pinyin_search


def historical_finished_receipt(*, product_line, actor, location_id, quantity=6,
                                quantity_per_box=5, actual_color='实际黑色'):
    boxes, tail, slots = packaging_values(quantity, quantity_per_box)
    task = product_line.production_task
    return FinishedGoodsReceipt.objects.create(
        receipt_number='HISTORY-' + uuid.uuid4().hex.upper(),
        production_task_product=product_line, source_document_number=task.task_number,
        status=FinishedGoodsReceiptStatus.CONFIRMED, location_id=location_id,
        task_number_snapshot=task.task_number, order_number_snapshot=task.order_number,
        category_snapshot=getattr(product_line.product.category, 'category_name', ''),
        product_number_snapshot=product_line.product_number_snapshot,
        product_code_snapshot=product_line.product_code_snapshot,
        product_name_snapshot=product_line.product_name_snapshot,
        product_name_pinyin_search=build_pinyin_search(product_line.product_name_snapshot),
        item_number_snapshot=product_line.item_number_snapshot,
        specification_snapshot=product_line.specification_snapshot,
        actual_color=actual_color, material_snapshot=product_line.material_snapshot,
        unit=product_line.unit, received_quantity=quantity, remaining_quantity=quantity,
        quantity_per_box=quantity_per_box, box_count=boxes, tail_quantity=tail,
        occupied_box_slots=slots, remaining_box_slots=slots, received_by_employee=actor,
    )
