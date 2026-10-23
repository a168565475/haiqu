from apps.inventory.public_stock_cutover import stock_write_transaction
from .pipe_receipts import receipt_pipe_values, quality_pipe_quantities
from apps.organizations.selectors import active_department_employees
from apps.procurement.pipe_purchase import pipe_meters
from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.boms.models import BomLine
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseReturn,
    PurchaseReturnLine,
    PurchaseReturnStatus,
    SupplierType,
)
from apps.products.material_identity import lock_bom_line_material_identities, resolve_bom_line_raw_material
from apps.products.models import RawMaterialInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.reference_data.pinyin_search import build_pinyin_search

from .models import (
    FinishedGoodsOutbound,
    FinishedGoodsOutboundLine,
    FinishedGoodsOutboundAttachment,
    FinishedGoodsReceipt,
    FinishedGoodsReceiptSource,
    FinishedGoodsReceiptStatus,
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    PublicStockBalance,
    SemiFinishedStockBalance,
    RecordStatus,
    Warehouse,
    WarehouseLocation,
    WarehouseType,
    WarehouseZone,
)
from .selectors import material_inbounds, material_received_totals
from .stock_services import credit_confirmed_inbound_line, validate_inbound_stock_identity
from .public_stock_mode import new_stock_mode, require_document_stock_mode
from .public_stock_services import lock_public_stock_locations


def packaging_values(quantity, quantity_per_box):
    quantity = int(quantity)
    if quantity_per_box in {None, ""}:
        if quantity <= 0:
            raise ValidationError({"quantity": "数量必须为正整数。"})
        return None, None, None
    quantity_per_box = int(quantity_per_box)
    if quantity <= 0:
        raise ValidationError({"quantity": "数量必须为正整数。"})
    if quantity_per_box <= 0:
        raise ValidationError({"quantity_per_box": "每箱数量必须为正整数。"})
    box_count, tail_quantity = divmod(quantity, quantity_per_box)
    occupied_box_slots = box_count + (1 if tail_quantity else 0)
    return box_count, tail_quantity, occupied_box_slots


def _warehouse_snapshot(instance):
    return {
        "warehouse_number": instance.warehouse_number,
        "warehouse_name": instance.warehouse_name,
        "warehouse_type": instance.warehouse_type,
        "address": instance.address,
        "status": instance.status,
        "responsible_person_name": instance.responsible_person_name,
        "contact_phone": instance.contact_phone,
    }


def _zone_snapshot(instance):
    return {"warehouse_id": str(instance.warehouse_id), "zone_name": instance.zone_name, "status": instance.status}


def _location_snapshot(instance):
    return {
        "zone_id": str(instance.zone_id),
        "location_number": instance.location_number,
        "capacity_box_slots": instance.capacity_box_slots,
        "status": instance.status,
    }


def _active_stock_for_warehouse(warehouse):
    return FinishedGoodsReceipt.objects.filter(
        location__zone__warehouse=warehouse, status=FinishedGoodsReceiptStatus.CONFIRMED, remaining_quantity__gt=0
    ).exists() or MaterialInboundLine.objects.filter(zone__warehouse=warehouse).exists() or PublicStockBalance.objects.filter(
        zone__warehouse=warehouse, quantity__gt=0,
    ).exists() or SemiFinishedStockBalance.objects.filter(zone__warehouse=warehouse, quantity__gt=0).exists()


def _active_stock_for_zone(zone):
    return FinishedGoodsReceipt.objects.filter(
        location__zone=zone, status=FinishedGoodsReceiptStatus.CONFIRMED, remaining_quantity__gt=0
    ).exists() or MaterialInboundLine.objects.filter(zone=zone).exists() or PublicStockBalance.objects.filter(
        zone=zone, quantity__gt=0,
    ).exists() or SemiFinishedStockBalance.objects.filter(zone=zone, quantity__gt=0).exists()


def _active_stock_for_location(location):
    return FinishedGoodsReceipt.objects.filter(
        location=location, status=FinishedGoodsReceiptStatus.CONFIRMED, remaining_quantity__gt=0
    ).exists() or MaterialInboundLine.objects.filter(location=location).exists()


@stock_write_transaction
def save_warehouse(*, instance, validated_data, actor_employee, request):
    current = Warehouse.objects.select_for_update().filter(pk=getattr(instance, "pk", None)).first()
    target = current or Warehouse()
    before = _warehouse_snapshot(target) if current else None
    if validated_data.get("status") == RecordStatus.DISABLED and current and _active_stock_for_warehouse(current):
        raise Conflict("仓库仍有库存或入库记录，不能停用。")
    for field, value in validated_data.items():
        setattr(target, field, value)
    if current:
        target.updated_by_employee = actor_employee
    else:
        target.created_by_employee = actor_employee
        target.updated_by_employee = actor_employee
    target.full_clean()
    target.save()
    write_audit_log(
        object_type="WAREHOUSE", object_id=target.pk, action="UPDATED" if current else "CREATED",
        actor_employee=actor_employee, before_data=before, after_data=_warehouse_snapshot(target), request=request,
    )
    return target


@stock_write_transaction
def save_zone(*, instance, validated_data, actor_employee, request):
    zone_id = getattr(instance, "pk", None)
    hint = WarehouseZone.objects.filter(pk=zone_id).values("warehouse_id").first() if zone_id else None
    if zone_id and hint is None:
        raise Conflict("库区已不存在，请刷新后重试。")
    target_warehouse = validated_data.get("warehouse")
    warehouse_ids = {hint["warehouse_id"]} if hint else set()
    if target_warehouse is not None:
        warehouse_ids.add(target_warehouse.pk)
    warehouses = list(Warehouse.objects.select_for_update(of=("self",), no_key=True).filter(
        pk__in=warehouse_ids).order_by("id"))
    if len(warehouses) != len(warehouse_ids):
        raise Conflict("原仓库或目标仓库已不存在，请刷新后重试。")
    current = WarehouseZone.objects.select_for_update(of=("self",), no_key=True).filter(pk=zone_id).first()
    if hint and (current is None or current.warehouse_id != hint["warehouse_id"]):
        raise Conflict("库区所属仓库已变化，请刷新后重试。")
    target = current or WarehouseZone()
    before = _zone_snapshot(target) if current else None
    if validated_data.get("status") == RecordStatus.DISABLED and current and _active_stock_for_zone(current):
        raise Conflict("库区仍有库存或入库记录，不能停用。")
    for field, value in validated_data.items():
        setattr(target, field, value)
    if current:
        target.updated_by_employee = actor_employee
    else:
        target.created_by_employee = actor_employee
        target.updated_by_employee = actor_employee
    target.full_clean()
    target.save()
    write_audit_log(
        object_type="WAREHOUSE_ZONE", object_id=target.pk, action="UPDATED" if current else "CREATED",
        actor_employee=actor_employee, before_data=before, after_data=_zone_snapshot(target), request=request,
    )
    return target


@stock_write_transaction
def save_location(*, instance, validated_data, actor_employee, request):
    current = WarehouseLocation.objects.select_for_update().filter(pk=getattr(instance, "pk", None)).first()
    target = current or WarehouseLocation()
    before = _location_snapshot(target) if current else None
    occupied = 0
    if current:
        occupied = FinishedGoodsReceipt.objects.filter(location=current, status=FinishedGoodsReceiptStatus.CONFIRMED,
            remaining_quantity__gt=0).aggregate(
            total=Sum("remaining_box_slots")
        )["total"] or 0
    capacity = validated_data.get("capacity_box_slots", target.capacity_box_slots)
    if capacity is not None and capacity < occupied:
        raise Conflict(f"库位当前占用 {occupied} 个箱位，容量不能调低到 {capacity}。")
    if validated_data.get("status") == RecordStatus.DISABLED and current and occupied:
        raise Conflict("库位仍有成品库存，不能停用。")
    for field, value in validated_data.items():
        setattr(target, field, value)
    if current:
        target.updated_by_employee = actor_employee
    else:
        target.created_by_employee = actor_employee
        target.updated_by_employee = actor_employee
    target.full_clean()
    target.save()
    write_audit_log(
        object_type="WAREHOUSE_LOCATION", object_id=target.pk, action="UPDATED" if current else "CREATED",
        actor_employee=actor_employee, before_data=before, after_data=_location_snapshot(target), request=request,
    )
    return target


def lock_finished_goods_locations(location_ids):
    """取成品入库流水前，按仓库、库区、库位顺序锁齐本次全部位置。"""
    hints = dict(WarehouseLocation.objects.filter(pk__in=location_ids).values_list("id", "zone_id"))
    zones = lock_public_stock_locations(set(hints.values()))
    locations = list(WarehouseLocation.objects.select_for_update(of=("self",)).filter(
        pk__in=location_ids).order_by("id"))
    if len(locations) != len(hints) or any(location.zone_id != hints.get(location.pk) for location in locations):
        raise Conflict("入库库位或所属库区已变化，请刷新后重试。")
    for location in locations:
        location.zone = zones[location.zone_id]
    return {str(location.pk): location for location in locations}


def _validate_finished_goods_location(location):
    if (
        location.status != RecordStatus.ACTIVE
        or location.zone.status != RecordStatus.ACTIVE
        or location.zone.warehouse.status != RecordStatus.ACTIVE
        or location.zone.warehouse.warehouse_type != WarehouseType.FINISHED
    ):
        raise Conflict("入库库位必须属于正常的成品仓、正常库区和正常库位。")


@transaction.atomic
def create_finished_goods_receipt(*, validated_data, actor_employee, request):
    """装配提交仅登记待入库，库存余额由仓管确认时写入。"""
    task_id = ProductionTaskProduct.objects.filter(pk=validated_data['production_task_product_id']).values_list('production_task_id', flat=True).first()
    if task_id is None:
        raise ValidationError({'production_task_product_id': '生产订单产品不存在。'})
    ProductionTask.objects.select_for_update().get(pk=task_id)
    line = (
        ProductionTaskProduct.objects.select_for_update(of=('self',))
        .select_related(
            "production_task", "product", "product__category", "product__product_item", "unit"
        )
        .filter(pk=validated_data["production_task_product_id"])
        .first()
    )
    if line is None:
        raise ValidationError({"production_task_product_id": "生产订单产品不存在。"})
    if line.production_task.status != ProductionTaskStatus.IN_PRODUCTION:
        raise Conflict("只有生产中的订单产品可以入库。")

    received_total = FinishedGoodsReceipt.objects.filter(production_task_product=line).aggregate(
        total=Sum("received_quantity")
    )["total"] or 0
    expected_received_total = validated_data["expected_received_total"]
    if int(received_total) != int(expected_received_total):
        raise Conflict("订单产品累计入库数量已变化，请刷新后重试。")
    tolerance = Decimal(line.production_task.order_tolerance_percent) / Decimal("100")
    maximum = (Decimal(line.quantity) * (Decimal("1") + tolerance)).to_integral_value(rounding=ROUND_FLOOR)
    from .assembly_reporting_limits import assembly_reporting_limit
    reporting = assembly_reporting_limit(line)
    maximum = min(maximum, reporting['reported_minimum'])
    quantity = validated_data["received_quantity"]
    if Decimal(received_total) + Decimal(quantity) > maximum:
        raise ValidationError({"received_quantity": f"累计入库不能超过 {int(maximum)}；装配各工序最低累计报工 {reporting['reported_minimum']}，已入库 {received_total}。"})

    location = lock_finished_goods_locations([validated_data["location_id"]]).get(str(validated_data["location_id"]))
    if location is None:
        raise ValidationError({"location_id": "入库库位不存在。"})

    supplier = validated_data.get("supplier")
    if supplier and (supplier.is_disabled or supplier.supplier_type != SupplierType.FINISHED):
        raise ValidationError({"supplier_id": "供应商必须是正常的成品供应商。"})
    if validated_data["unit_id"] != line.unit_id:
        raise ValidationError({"unit_id": "入库单位必须与生产订单产品单位一致。"})

    box_count, tail_quantity, occupied_box_slots = packaging_values(
        quantity, validated_data["quantity_per_box"]
    )
    _validate_finished_goods_location(location)
    product = line.product
    category_name = getattr(product.category, "category_name", "")
    receipt = FinishedGoodsReceipt.objects.create(
        receipt_number=next_business_number("FINISHED_GOODS_RECEIPT"),
        production_task_product=line,
        source_document_number=line.production_task.task_number,
        status=FinishedGoodsReceiptStatus.PENDING,
        location=location,
        supplier=supplier,
        task_number_snapshot=line.production_task.task_number,
        order_number_snapshot=line.production_task.order_number,
        category_snapshot=category_name,
        product_number_snapshot=line.product_number_snapshot,
        product_code_snapshot=line.product_code_snapshot,
        product_name_snapshot=line.product_name_snapshot,
        product_name_pinyin_search=build_pinyin_search(line.product_name_snapshot),
        item_number_snapshot=line.item_number_snapshot,
        specification_snapshot=line.specification_snapshot,
        actual_color=validated_data["actual_color"].strip(),
        material_snapshot=line.material_snapshot,
        unit_id=validated_data["unit_id"],
        received_quantity=quantity,
        remaining_quantity=0,
        quantity_per_box=validated_data["quantity_per_box"],
        box_count=box_count,
        tail_quantity=tail_quantity,
        occupied_box_slots=occupied_box_slots,
        remaining_box_slots=0,
        remark=validated_data.get("remark", ""),
        received_by_employee=actor_employee,
        submitted_by_employee=actor_employee,
        submitted_at=timezone.now(),
    )
    write_audit_log(
        object_type="FINISHED_GOODS_RECEIPT", object_id=receipt.pk, action="CREATED",
        context_type="PRODUCTION_TASK", context_id=line.production_task_id, actor_employee=actor_employee,
        after_data={"receipt_number": receipt.receipt_number, "quantity": quantity, "location_id": str(location.pk),
                    "status": receipt.status},
        request=request,
    )
    return receipt


@transaction.atomic
def confirm_finished_goods_receipt(*, receipt_id, actor_employee, request):
    receipt = FinishedGoodsReceipt.objects.select_for_update().select_related(
        "location", "location__zone", "location__zone__warehouse",
    ).filter(pk=receipt_id).first()
    if receipt is None:
        raise FinishedGoodsReceipt.DoesNotExist
    if receipt.status == FinishedGoodsReceiptStatus.CONFIRMED:
        return receipt, True
    if receipt.status != FinishedGoodsReceiptStatus.PENDING:
        raise Conflict("当前成品入库单状态不能确认。")
    location = lock_finished_goods_locations([receipt.location_id]).get(str(receipt.location_id))
    if location is None:
        raise ValidationError({"location_id": "入库库位不存在。"})
    _validate_finished_goods_location(location)
    occupied_now = FinishedGoodsReceipt.objects.filter(
        location=location, status=FinishedGoodsReceiptStatus.CONFIRMED, remaining_quantity__gt=0,
    ).exclude(pk=receipt.pk).aggregate(total=Sum("remaining_box_slots"))["total"] or 0
    if (
        receipt.occupied_box_slots is not None
        and location.capacity_box_slots is not None
        and occupied_now + receipt.occupied_box_slots > location.capacity_box_slots
    ):
        raise ValidationError({"receipt": f"库位剩余 {location.capacity_box_slots - occupied_now} 个箱位，无法确认本次入库。"})
    receipt.status = FinishedGoodsReceiptStatus.CONFIRMED
    receipt.remaining_quantity = receipt.received_quantity
    receipt.remaining_box_slots = receipt.occupied_box_slots
    receipt.confirmed_by_employee = actor_employee
    receipt.confirmed_at = timezone.now()
    receipt.save(update_fields=["status", "remaining_quantity", "remaining_box_slots", "confirmed_by_employee", "confirmed_at", "updated_at"])
    write_audit_log(
        object_type="FINISHED_GOODS_RECEIPT", object_id=receipt.pk, action="CONFIRMED",
        context_type="PRODUCTION_TASK", context_id=receipt.production_task_product.production_task_id,
        actor_employee=actor_employee,
        after_data={"receipt_number": receipt.receipt_number, "quantity": receipt.received_quantity,
                    "location_id": str(receipt.location_id), "status": receipt.status},
        request=request,
    )
    return receipt, False


@transaction.atomic
def create_finished_goods_outbound(*, items, receiver_name, used_for_order_number, remark, actor_employee, request,
                                   responsible_employee_id=None, shipment_date=None, loading_fee=0, other_fee=0, attachment_ids=None):
    receipt_ids = [item["receipt_id"] for item in items]
    locked_receipts = list(
        FinishedGoodsReceipt.objects.select_for_update(of=("self",))
        .select_related("location", "production_task_product")
        .filter(pk__in=receipt_ids, status=FinishedGoodsReceiptStatus.CONFIRMED)
        .order_by("id")
    )
    if len(locked_receipts) != len(receipt_ids):
        raise ValidationError({"items": "部分入库批次不存在。"})
    if any(
        receipt.source_type == FinishedGoodsReceiptSource.SAMPLE_INVENTORY
        or receipt.source_sample_inventory_line_id
        for receipt in locked_receipts
    ):
        raise Conflict("样品入库来源的成品库存请在样品库办理出库或借出，避免重复扣减。")
    task_ids = {receipt.production_task_product.production_task_id for receipt in locked_receipts if receipt.production_task_product_id}
    if len(task_ids) != 1 or any(not receipt.production_task_product_id for receipt in locked_receipts):
        raise ValidationError({"items": "一张出货单只能包含同一生产任务单的库存。"})
    receipt_map = {receipt.pk: receipt for receipt in locked_receipts}
    location_ids = sorted({receipt.location_id for receipt in locked_receipts}, key=str)
    list(WarehouseLocation.objects.select_for_update().filter(pk__in=location_ids).order_by("id"))

    from apps.organizations.models import Employee
    responsible = active_department_employees("DEPT_WAREHOUSE").filter(pk=responsible_employee_id).first() if responsible_employee_id else None
    if responsible_employee_id and responsible is None:
        raise ValidationError({"responsible_employee_id": "负责人不存在或已停用。"})
    outbound = FinishedGoodsOutbound.objects.create(
        outbound_number=next_business_number("FINISHED_GOODS_OUTBOUND"),
        receiver_name=receiver_name,
        used_for_order_number=used_for_order_number,
        remark=remark,
        outbound_by_employee=actor_employee,
        responsible_employee=responsible,
        responsible_name_snapshot=responsible.display_name if responsible else "",
        shipment_date=shipment_date,
        loading_fee=loading_fee,
        other_fee=other_fee,
    )
    for item in items:
        receipt = receipt_map[item["receipt_id"]]
        if receipt.remaining_quantity != item["expected_remaining_quantity"]:
            raise Conflict(f"批次 {receipt.receipt_number} 库存已变化，请刷新后重试。")
        quantity = item["outbound_quantity"]
        if quantity > receipt.remaining_quantity:
            raise ValidationError({"items": f"批次 {receipt.receipt_number} 出库数量不能超过可用库存。"})
        box_count, tail_quantity, _ = packaging_values(quantity, item["quantity_per_box"])
        before_quantity = receipt.remaining_quantity
        after_quantity = before_quantity - quantity
        if after_quantity == 0:
            remaining_slots = 0 if receipt.quantity_per_box is not None else None
        else:
            remaining_slots = packaging_values(after_quantity, receipt.quantity_per_box)[2]
        FinishedGoodsOutboundLine.objects.create(
            outbound=outbound,
            receipt=receipt,
            outbound_quantity=quantity,
            quantity_per_box=item["quantity_per_box"],
            box_count=box_count,
            tail_quantity=tail_quantity,
            before_quantity=before_quantity,
            after_quantity=after_quantity,
        )
        receipt.remaining_quantity = after_quantity
        receipt.remaining_box_slots = remaining_slots
        if not receipt.material_snapshot:
            receipt.material_snapshot = receipt.production_task_product.material_snapshot
        receipt.save(update_fields=["remaining_quantity", "remaining_box_slots", "material_snapshot", "updated_at"])

    if attachment_ids:
        from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
        files = list(BusinessFile.objects.filter(pk__in=attachment_ids, archived_at__isnull=True,
            uploaded_by_employee=actor_employee, scan_status__in=USABLE_FILE_SCAN_STATUSES,
            storage_key__startswith="inventory/finished-goods-loading/", content_type__startswith="image/"))
        if len(files) != len(set(attachment_ids)):
            raise ValidationError({"attachment_ids": "存在不存在或已归档的文件。"})
        FinishedGoodsOutboundAttachment.objects.bulk_create(
            [FinishedGoodsOutboundAttachment(outbound=outbound, business_file=file) for file in files]
        )

    write_audit_log(
        object_type="FINISHED_GOODS_OUTBOUND", object_id=outbound.pk, action="CREATED",
        actor_employee=actor_employee,
        after_data={"outbound_number": outbound.outbound_number, "line_count": len(items),
                    "responsible_employee_id": str(responsible.pk) if responsible else None,
                    "shipment_date": str(shipment_date), "loading_fee": str(loading_fee), "other_fee": str(other_fee)},
        request=request,
    )
    from .notification_events import finished_outbound_confirmed
    finished_outbound_confirmed(outbound, actor_employee)
    return outbound


def _material_search_text(line):
    return " ".join(
        value.strip()
        for value in (
            line.section_title_snapshot,
            line.category_snapshot,
            line.material_snapshot,
            line.part_name_snapshot,
            line.specification_snapshot,
            line.raw_material_snapshot,
            line.product_name_snapshot,
        )
        if value and value.strip()
    )


def _freeze_public_pipe_values(values, stock_mode):
    if stock_mode != "PUBLIC_V2" or values.get("measurement_kind") != "PIPE":
        return values
    from .public_stock_identity import build_pipe_stock_identity
    material = values["raw_material_information"]
    identity = build_pipe_stock_identity(raw_material=material, unit=material.unit,
                                         raw_bar_length_m=values["raw_bar_length_m"])
    identity["raw_bar_length_m"] = str(identity["raw_bar_length_m"])
    return {**values, "calculation_snapshot": {**values.get("calculation_snapshot", {}),
                                               "public_stock_identity": identity}}


@stock_write_transaction
def create_material_inbound(*, inbound_date, remark, items, actor_employee, request,
                            sample_direct=False, client_request_id=None):
    from apps.procurement.source_access import purchase_order_access
    from apps.production_tasks.selectors import accessible_production_tasks
    if inbound_date > timezone.localdate():
        raise ValidationError({"inbound_date": "入库日期不能晚于今天。"})

    stock_mode = new_stock_mode()
    line_ids = sorted({item["purchase_order_line_id"] for item in items}, key=str)
    # 与采购完成、品质确认统一先锁采购单，避免并发时读到过期状态。
    order_ids = PurchaseOrderLine.objects.filter(pk__in=line_ids).values_list("purchase_order_id", flat=True)
    list(PurchaseOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("id"))
    locked_lines = list(
        PurchaseOrderLine.objects.select_for_update(of=("self",))
        .select_related("purchase_order", "purchase_order__production_task", "supplier", "bom_line")
        .filter(purchase_order_access(accessible_production_tasks(request).values_list("id", flat=True), request, "purchase_order__"),
                pk__in=line_ids, purchase_order__archived_at__isnull=True)
        .order_by("id")
    )
    if len(locked_lines) != len(line_ids):
        raise ValidationError({"items": "部分采购明细不存在。"})
    if any((line.purchase_order.source_type == 'SAMPLE') != sample_direct for line in locked_lines):
        raise Conflict('样品采购请使用全部入库；普通采购仍须收货并完成品质确认。')
    line_map = {line.pk: line for line in locked_lines}
    bom_line_ids = sorted({line.bom_line_id for line in locked_lines if line.bom_line_id}, key=str)
    locked_bom_lines = list(
        BomLine.objects.select_for_update().filter(pk__in=bom_line_ids).order_by("pk")
    )
    bom_line_map = {line.pk: line for line in locked_bom_lines}
    for line in locked_lines:
        if line.bom_line_id:
            line.bom_line = bom_line_map[line.bom_line_id]
    existing_identity_rows = list(
        MaterialInboundLine.objects.filter(
            purchase_order_line_id__in=line_ids,
            raw_material_information__isnull=False,
        ).values_list("purchase_order_line_id", "raw_material_information_id")
    )
    lock_bom_line_material_identities(
        locked_bom_lines,
        extra_raw_material_ids=[raw_material_id for _, raw_material_id in existing_identity_rows]
        + [line.calculation_snapshot.get('raw_material_id') for line in locked_lines if line.calculation_snapshot],
    )
    locked_existing_inbound_lines = list(
        MaterialInboundLine.objects.select_for_update(of=("self",))
        .select_related("raw_material_information", "raw_material_information__unit")
        .filter(purchase_order_line_id__in=line_ids)
        .order_by("id")
    )
    frozen_ids_by_purchase_line = defaultdict(set)
    frozen_materials = {}
    for existing_line in locked_existing_inbound_lines:
        if existing_line.raw_material_information_id:
            frozen_ids_by_purchase_line[existing_line.purchase_order_line_id].add(
                existing_line.raw_material_information_id
            )
            frozen_materials[existing_line.raw_material_information_id] = existing_line.raw_material_information
    conflicting_line_ids = [
        line_id for line_id, material_ids in frozen_ids_by_purchase_line.items() if len(material_ids) > 1
    ]
    if conflicting_line_ids:
        raise Conflict("采购明细存在多个已冻结库存原料身份，请先完成受控数据修复。")
    material_identity_cache = {}
    purchase_order_ids = {line.purchase_order_id for line in locked_lines}
    if len(purchase_order_ids) != 1:
        raise ValidationError({"items": "一次仓库收货只能选择同一张采购单的明细。"})

    zone_ids = sorted({item["zone_id"] for item in items}, key=str)
    lock_public_stock_locations(zone_ids)
    zones = list(
        WarehouseZone.objects.select_for_update()
        .select_related("warehouse")
        .filter(pk__in=zone_ids)
        .order_by("id")
    )
    if len(zones) != len(zone_ids):
        raise ValidationError({"items": "部分入库库区不存在。"})
    zone_map = {zone.pk: zone for zone in zones}

    location_ids = sorted(
        {item["location_id"] for item in items if item.get("location_id")},
        key=str,
    )
    locations = list(
        WarehouseLocation.objects.select_for_update()
        .select_related("zone", "zone__warehouse")
        .filter(pk__in=location_ids)
        .order_by("id")
    )
    if len(locations) != len(location_ids):
        raise ValidationError({"items": "部分入库库位不存在。"})
    location_map = {location.pk: location for location in locations}

    # 待检批次按到货量占用采购余额；已质检批次只按合格量占用，退货数量可重新收货。
    received_totals = material_received_totals(line_ids)
    completed_return_line_ids = set(
        PurchaseReturnLine.objects.filter(
            inbound_line__purchase_order_line_id__in=line_ids,
            return_order__status=PurchaseReturnStatus.COMPLETED,
        ).values_list("inbound_line__purchase_order_line_id", flat=True)
    )
    open_return_line_ids = set(
        PurchaseReturnLine.objects.filter(
            inbound_line__purchase_order_line_id__in=line_ids,
        ).exclude(
            return_order__status=PurchaseReturnStatus.COMPLETED,
        ).values_list("inbound_line__purchase_order_line_id", flat=True)
    )
    open_return_order_ids = set(
        PurchaseReturn.objects.filter(
            purchase_order_id__in={line.purchase_order_id for line in line_map.values()},
        ).exclude(
            status=PurchaseReturnStatus.COMPLETED,
        ).values_list("purchase_order_id", flat=True)
    )
    submitted_totals = {}
    expected_values = {}
    for item in items:
        line_id = item["purchase_order_line_id"]
        line = line_map[line_id]
        if line.purchase_order_id in open_return_order_ids:
            raise Conflict(
                f"采购单 {line.purchase_order.order_number} 的退货仍在等待确认退货或退货完成，暂不能再次办理入库。"
            )
        can_replenish_completed_return = (
            line.purchase_order.status == PurchaseOrderStatus.COMPLETED
            and line_id in completed_return_line_ids
            and line_id not in open_return_line_ids
        )
        if line.purchase_order.status != PurchaseOrderStatus.PURCHASING and not can_replenish_completed_return:
            raise Conflict(
                f"采购单 {line.purchase_order.order_number} 必须处于采购中；已完成单仅允许补收已完成退货的数量。"
            )
        if line.actual_purchase_quantity is None or line.actual_purchase_quantity <= 0:
            raise ValidationError({"items": f"采购单第 {line.line_number} 行缺少有效采购数量。"})
        if not line.source_unit_text.strip():
            raise ValidationError({"items": f"采购单第 {line.line_number} 行缺少单位。"})
        current_received = Decimal(received_totals.get(line_id, 0))
        current_remaining = line.actual_purchase_quantity - current_received
        expected = item["expected_remaining_quantity"]
        if expected != current_remaining:
            raise Conflict(f"采购单第 {line.line_number} 行剩余数量已变化，请刷新后重试。")
        if line_id in expected_values and expected_values[line_id] != expected:
            raise ValidationError({"items": f"采购单第 {line.line_number} 行预期剩余数量不一致。"})
        expected_values[line_id] = expected
        item['_pipe_values'] = _freeze_public_pipe_values(receipt_pipe_values(item, purchase_line=line), stock_mode)
        if item.get('received_quantity') is None:
            raise ValidationError({'received_quantity': '请填写到货数量。'})
        submitted_totals[line_id] = submitted_totals.get(line_id, Decimal("0")) + item["received_quantity"]

        zone = zone_map[item["zone_id"]]
        if (
            zone.status != RecordStatus.ACTIVE
            or zone.warehouse.status != RecordStatus.ACTIVE
            or zone.warehouse.warehouse_type != WarehouseType.MATERIAL
        ):
            raise Conflict("入库库区必须属于正常的材料仓和正常库区。")
        location_id = item.get("location_id")
        if location_id:
            location = location_map[location_id]
            if location.status != RecordStatus.ACTIVE or location.zone_id != zone.pk:
                raise Conflict("入库库位必须是所选库区下的正常库位。")

    for line_id, submitted in submitted_totals.items():
        line = line_map[line_id]
        current_received = Decimal(received_totals.get(line_id, 0))
        if current_received + submitted > line.actual_purchase_quantity:
            remaining = line.actual_purchase_quantity - current_received
            raise ValidationError({"items": f"采购单第 {line.line_number} 行最多还能入库 {remaining}。"})

    inbound = MaterialInbound.objects.create(
        stock_mode=stock_mode,
        inbound_number=next_business_number("MATERIAL_INBOUND", business_date=inbound_date),
        purchase_order_id=purchase_order_ids.pop(),
        inbound_date=inbound_date,
        status=MaterialInboundStatus.CONFIRMED if sample_direct else MaterialInboundStatus.PENDING_QUALITY,
        client_request_id=client_request_id,
        remark=remark,
        received_by_employee=actor_employee,
    )
    created = []
    for item in items:
        line = line_map[item["purchase_order_line_id"]]
        frozen_ids = frozen_ids_by_purchase_line.get(line.pk, set())
        if frozen_ids:
            raw_material = frozen_materials[next(iter(frozen_ids))]
        else:
            raw_material, _ = resolve_bom_line_raw_material(
                line.bom_line,
                cache=material_identity_cache,
            )
        created.append(
            MaterialInboundLine.objects.create(
                inbound=inbound,
                purchase_order_line=line,
                **{key: value for key, value in item.get('_pipe_values', {}).items() if key != 'raw_material_information'},
                raw_material_information=item.get('_pipe_values', {}).get('raw_material_information', raw_material),
                zone=zone_map[item["zone_id"]],
                location=location_map.get(item.get("location_id")),
                received_quantity=item["received_quantity"],
                return_quantity=Decimal("0"),
                accepted_quantity=item["received_quantity"],
                remark=item.get("remark", ""),
                purchase_order_number_snapshot=line.purchase_order.order_number,
                production_task_number_snapshot=line.purchase_order.production_task_number_snapshot,
                sales_order_number_snapshot=line.purchase_order.sales_order_number_snapshot,
                supplier_number_snapshot=line.supplier_number_snapshot,
                supplier_name_snapshot=line.supplier_name_snapshot,
                bom_number_snapshot=line.bom_number_snapshot,
                product_name_snapshot=line.product_name_snapshot,
                section_type_snapshot=line.section_type_snapshot,
                section_title_snapshot=line.section_title_snapshot,
                category_snapshot=line.category_snapshot,
                material_snapshot=line.material_snapshot,
                part_name_snapshot=line.part_name_snapshot,
                specification_snapshot=line.specification_snapshot,
                raw_material_snapshot=line.raw_material_snapshot,
                material_attributes_snapshot=line.material_attributes_snapshot,
                source_unit_text_snapshot=line.source_unit_text,
                purchased_quantity_snapshot=line.actual_purchase_quantity,
                material_pinyin_search=build_pinyin_search(_material_search_text(line)),
            )
        )
    write_audit_log(
        object_type="MATERIAL_INBOUND",
        object_id=inbound.pk,
        action="SAMPLE_DIRECT_CONFIRMED" if sample_direct else "SUBMITTED_FOR_QUALITY",
        actor_employee=actor_employee,
        after_data={
            "inbound_number": inbound.inbound_number,
            "inbound_date": inbound.inbound_date,
            "line_count": len(created),
            "total_quantity": str(sum((line.received_quantity for line in created), Decimal("0"))),
        },
        request=request,
    )
    if not sample_direct:
        from apps.wecom.notification_services import register_business_event
        register_business_event(
            event_code="MATERIAL_RECEIPT_RECORDED", idempotency_key=f"MATERIAL_RECEIPT_RECORDED:{inbound.pk}:1",
            object_type="inventory.MaterialInbound", object_id=inbound.pk, object_version=1,
            context={"document_no": inbound.inbound_number, "operator": actor_employee.display_name,
                     "occurred_at": inbound.created_at.isoformat(), "status": inbound.get_status_display()},
        )
    return inbound


def _manual_inbound_payload_matches(inbound, *, inbound_date, remark, items):
    expected_lines = sorted(
        (
            str(item["raw_material_id"]),
            str(item["zone_id"]),
            str(item.get("location_id") or ""),
            Decimal(item["received_quantity"]),
            item.get('received_bar_count'), item.get('raw_bar_length_m'),
            item.get("remark", ""),
        )
        for item in items
    )
    actual_lines = sorted(
        (
            str(line.raw_material_information_id),
            str(line.zone_id),
            str(line.location_id or ""),
            Decimal(line.received_quantity),
            line.received_bar_count, line.raw_bar_length_m,
            line.remark,
        )
        for line in inbound.lines.all()
    )
    return (
        inbound.purchase_order_id is None
        and inbound.inbound_date == inbound_date
        and inbound.remark == remark
        and actual_lines == expected_lines
    )


@stock_write_transaction
def create_manual_material_inbound(*, client_request_id, inbound_date, remark, items, actor_employee, request):
    """登记无采购单来源的额外材料，并直接作为已确认库存入账。"""
    stock_mode = new_stock_mode()
    items = [dict(item) for item in items]
    for item in items:
        if item.get('received_bar_count') is not None:
            _, item['received_quantity'] = pipe_meters(item['received_bar_count'], item.get('raw_bar_length_m'), field='received_bar_count')
        if item.get('received_quantity') is None:
            raise ValidationError({'received_quantity': '请填写到货数量；管材须同时填写根数和单根长度。'})
    existing = material_inbounds(
        MaterialInbound.objects.filter(client_request_id=client_request_id)
    ).first()
    if existing is not None:
        if not _manual_inbound_payload_matches(
            existing, inbound_date=inbound_date, remark=remark, items=items,
        ):
            raise Conflict("同一提交标识不能用于不同的额外入库内容。")
        return existing
    if inbound_date > timezone.localdate():
        raise ValidationError({"inbound_date": "入库日期不能晚于今天。"})
    if not remark.strip():
        raise ValidationError({"remark": "额外材料入库必须填写备注。"})

    material_ids = sorted({item["raw_material_id"] for item in items}, key=str)
    materials = list(
        RawMaterialInformation.objects.select_for_update(of=("self",))
        .select_related("category", "unit", "color")
        .filter(
            pk__in=material_ids,
            archived_at__isnull=True,
            category__archived_at__isnull=True,
            category__status="ACTIVE",
            unit__archived_at__isnull=True,
            unit__status="ACTIVE",
        )
        .order_by("id")
    )
    if len(materials) != len(material_ids):
        raise ValidationError({"items": "部分原料资料不存在、已停用或已归档。"})
    material_map = {material.pk: material for material in materials}

    zone_ids = sorted({item["zone_id"] for item in items}, key=str)
    lock_public_stock_locations(zone_ids)
    zones = list(
        WarehouseZone.objects.select_for_update()
        .select_related("warehouse")
        .filter(pk__in=zone_ids)
        .order_by("id")
    )
    if len(zones) != len(zone_ids):
        raise ValidationError({"items": "部分入库库区不存在。"})
    zone_map = {zone.pk: zone for zone in zones}

    location_ids = sorted({item["location_id"] for item in items if item.get("location_id")}, key=str)
    locations = list(
        WarehouseLocation.objects.select_for_update()
        .select_related("zone", "zone__warehouse")
        .filter(pk__in=location_ids)
        .order_by("id")
    )
    if len(locations) != len(location_ids):
        raise ValidationError({"items": "部分入库库位不存在。"})
    location_map = {location.pk: location for location in locations}

    for item in items:
        zone = zone_map[item["zone_id"]]
        if (
            zone.status != RecordStatus.ACTIVE
            or zone.warehouse.status != RecordStatus.ACTIVE
            or zone.warehouse.warehouse_type != WarehouseType.MATERIAL
        ):
            raise Conflict("入库库区必须属于正常的材料仓和正常库区。")
        location_id = item.get("location_id")
        if location_id:
            location = location_map[location_id]
            if location.status != RecordStatus.ACTIVE or location.zone_id != zone.pk:
                raise Conflict("入库库位必须是所选库区下的正常库位。")

    try:
        with transaction.atomic():
            inbound = MaterialInbound.objects.create(
                stock_mode=stock_mode,
                inbound_number=next_business_number("MATERIAL_INBOUND", business_date=inbound_date),
                client_request_id=client_request_id,
                purchase_order=None,
                inbound_date=inbound_date,
                status=MaterialInboundStatus.CONFIRMED,
                remark=remark,
                received_by_employee=actor_employee,
            )
    except IntegrityError:
        existing = material_inbounds(
            MaterialInbound.objects.filter(client_request_id=client_request_id)
        ).first()
        if existing is None:
            raise
        if not _manual_inbound_payload_matches(
            existing, inbound_date=inbound_date, remark=remark, items=items,
        ):
            raise Conflict("同一提交标识不能用于不同的额外入库内容。")
        return existing
    created = []
    for item in items:
        material = material_map[item["raw_material_id"]]
        pipe_values = _freeze_public_pipe_values(receipt_pipe_values(item, material=material), stock_mode)
        quantity = item["received_quantity"]
        search_text = " ".join(filter(None, [
            material.material_number,
            material.category.category_name,
            material.material_name,
            material.specification,
            material.material,
            material.color.color_name if material.color_id else material.color_snapshot,
        ]))
        created.append(MaterialInboundLine.objects.create(
            inbound=inbound,
            purchase_order_line=None,
            **{key: value for key, value in pipe_values.items() if key != 'raw_material_information'},
            raw_material_information=material,
            zone=zone_map[item["zone_id"]],
            location=location_map.get(item.get("location_id")),
            received_quantity=quantity,
            return_quantity=Decimal("0"),
            accepted_quantity=quantity,
            remark=item.get("remark", ""),
            purchase_order_number_snapshot="",
            production_task_number_snapshot="",
            sales_order_number_snapshot="",
            supplier_number_snapshot="",
            supplier_name_snapshot="",
            bom_number_snapshot="",
            product_name_snapshot="",
            section_type_snapshot=material.item_type,
            section_title_snapshot=material.category.category_name,
            category_snapshot=material.category.category_name,
            material_snapshot=material.material,
            part_name_snapshot=material.material_name,
            specification_snapshot=material.specification,
            raw_material_snapshot=material.material,
            source_unit_text_snapshot='米' if pipe_values else material.unit.unit_name,
            purchased_quantity_snapshot=quantity,
            material_pinyin_search=build_pinyin_search(search_text),
        ))

    for line in sorted(created, key=lambda item: (str(item.raw_material_information_id), str(item.zone_id), str(item.pk))):
        credit_confirmed_inbound_line(line=line, actor_employee=actor_employee)

    write_audit_log(
        object_type="MATERIAL_INBOUND",
        object_id=inbound.pk,
        action="MANUAL_CONFIRMED",
        actor_employee=actor_employee,
        after_data={
            "inbound_number": inbound.inbound_number,
            "inbound_date": inbound.inbound_date,
            "line_count": len(created),
            "total_quantity": str(sum((line.received_quantity for line in created), Decimal("0"))),
            "remark": remark,
        },
        request=request,
    )
    return inbound


@stock_write_transaction
def confirm_material_quality(*, inbound_id, items, actor_employee, request):
    from apps.procurement.completion_services import generate_quality_returns
    from apps.procurement.source_access import purchase_order_access
    from apps.production_tasks.selectors import accessible_production_tasks
    from apps.samples.models import SampleRequest, SampleMaterialPurchaseSource
    from apps.samples.material_arrival_services import receive_material_arrival

    bindings = list(SampleMaterialPurchaseSource.objects.filter(purchase_order_line__material_inbound_lines__inbound_id=inbound_id))
    sample_ids = SampleMaterialPurchaseSource.objects.filter(pk__in=[b.pk for b in bindings]).values_list("procurement_request__material_request__sample_request_id", flat=True)
    # 与打样建单统一先锁样品，再锁采购单、入库单，避免跨域锁顺序反转。
    list(SampleRequest.objects.select_for_update().filter(pk__in=sample_ids).order_by("id"))

    if MaterialInbound.objects.filter(pk=inbound_id, stock_mode="PUBLIC_V2").exists():
        task_ids = MaterialInboundLine.objects.filter(inbound_id=inbound_id).values_list(
            "purchase_order_line__purchase_order__production_task_id", flat=True)
        # 公共领料先锁订单再锁原料/库区；质检须在上层首次取原料锁前对齐。
        list(ProductionTask.objects.select_for_update(of=("self",)).filter(pk__in=task_ids).order_by("id"))

    order_ids = MaterialInboundLine.objects.filter(inbound_id=inbound_id).values_list("purchase_order_line__purchase_order_id", flat=True)
    list(PurchaseOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("id"))
    candidate_inbound = (
        MaterialInbound.objects
        .select_related("purchase_order")
        .filter(purchase_order_access(accessible_production_tasks(request).values_list("id", flat=True), request, "purchase_order__"), pk=inbound_id)
        .first()
    )
    if candidate_inbound is None:
        raise ValidationError({"inbound_id": "待检批次不存在。"})
    require_document_stock_mode(candidate_inbound)
    if candidate_inbound.status != MaterialInboundStatus.PENDING_QUALITY:
        raise Conflict("该待检批次已经完成品质确认，请勿重复提交。")

    candidate_lines = list(
        MaterialInboundLine.objects
        .select_related(
            "inbound",
            "purchase_order_line",
            "purchase_order_line__purchase_order",
            "purchase_order_line__purchase_order__production_task",
            "purchase_order_line__bom_line",
            "raw_material_information",
            "raw_material_information__unit",
            "zone",
            "zone__warehouse",
        )
        .filter(inbound=candidate_inbound)
        .order_by("id")
    )
    purchase_line_ids = sorted({line.purchase_order_line_id for line in candidate_lines}, key=str)
    unresolved_bom_line_ids = sorted(
        {
            line.purchase_order_line.bom_line_id
            for line in candidate_lines
            if not line.raw_material_information_id and line.purchase_order_line.bom_line_id
        },
        key=str,
    )
    existing_identity_rows = list(
        MaterialInboundLine.objects.filter(
            purchase_order_line_id__in=purchase_line_ids,
            raw_material_information__isnull=False,
        ).values_list("purchase_order_line_id", "raw_material_information_id")
    )
    locked_bom_lines = list(
        BomLine.objects.select_for_update().filter(pk__in=unresolved_bom_line_ids).order_by("pk")
    )
    lock_bom_line_material_identities(
        locked_bom_lines,
        extra_raw_material_ids=[raw_material_id for _, raw_material_id in existing_identity_rows],
    )
    inbound = (
        MaterialInbound.objects.select_for_update(of=("self",))
        .select_related("purchase_order")
        .filter(
            purchase_order_access(
                accessible_production_tasks(request).values_list("id", flat=True),
                request,
                "purchase_order__",
            ),
            pk=inbound_id,
        )
        .first()
    )
    if inbound is None:
        raise ValidationError({"inbound_id": "待检批次不存在。"})
    require_document_stock_mode(inbound)
    if inbound.status != MaterialInboundStatus.PENDING_QUALITY:
        raise Conflict("该待检批次已经完成品质确认，请勿重复提交。")

    locked_purchase_lines = list(
        MaterialInboundLine.objects.select_for_update(of=("self",))
        .select_related(
            "inbound",
            "purchase_order_line",
            "purchase_order_line__purchase_order",
            "purchase_order_line__purchase_order__production_task",
            "purchase_order_line__bom_line",
            "raw_material_information",
            "raw_material_information__unit",
            "zone",
            "zone__warehouse",
        )
        .filter(purchase_order_line_id__in=purchase_line_ids)
        .order_by("id")
    )
    locked_lines = [line for line in locked_purchase_lines if line.inbound_id == inbound.pk]
    line_map = {line.pk: line for line in locked_lines}
    input_ids = [item["line_id"] for item in items]
    if len(input_ids) != len(set(input_ids)):
        raise ValidationError({"items": "同一待检明细不能重复提交。"})
    if set(input_ids) != set(line_map):
        raise ValidationError({"items": "必须完整确认该批次的全部待检明细。"})
    if inbound.stock_mode == "PUBLIC_V2":
        locked_zones = lock_public_stock_locations({line.zone_id for line in locked_lines})
        for line in locked_lines:
            line.zone = locked_zones[line.zone_id]
            if line.zone.status != RecordStatus.ACTIVE or line.zone.warehouse.status != RecordStatus.ACTIVE:
                raise Conflict("入库库区或仓库已停用，请先核对库区状态。")

    bom_line_map = {line.pk: line for line in locked_bom_lines}
    frozen_ids_by_purchase_line = defaultdict(set)
    frozen_materials = {}
    for line in locked_purchase_lines:
        if line.raw_material_information_id:
            frozen_ids_by_purchase_line[line.purchase_order_line_id].add(line.raw_material_information_id)
            frozen_materials[line.raw_material_information_id] = line.raw_material_information
    if any(len(material_ids) > 1 for material_ids in frozen_ids_by_purchase_line.values()):
        raise Conflict("采购明细存在多个已冻结库存原料身份，请先完成受控数据修复。")
    unresolved_lines = [line for line in locked_lines if not line.raw_material_information_id]
    for line in unresolved_lines:
        if line.purchase_order_line.bom_line_id:
            line.purchase_order_line.bom_line = bom_line_map[line.purchase_order_line.bom_line_id]
    material_identity_cache = {}

    prepared = []
    for item in items:
        line = line_map[item["line_id"]]
        if item["expected_received_quantity"] != line.received_quantity:
            raise Conflict(f"第 {line.purchase_order_line.line_number} 行到货数量已变化，请刷新后重试。")
        return_quantity = quality_pipe_quantities(line, item)
        if return_quantity < 0 or return_quantity > line.received_quantity:
            raise ValidationError({"items": f"退货数量不能超过到货数量 {line.received_quantity}。"})
        accepted_quantity = line.received_quantity - return_quantity
        if not line.raw_material_information_id:
            frozen_ids = frozen_ids_by_purchase_line.get(line.purchase_order_line_id, set())
            if frozen_ids:
                raw_material = frozen_materials[next(iter(frozen_ids))]
            else:
                raw_material, _ = resolve_bom_line_raw_material(
                    line.purchase_order_line.bom_line,
                    cache=material_identity_cache,
                )
            if raw_material:
                line.raw_material_information = raw_material
        line.return_quantity = return_quantity
        line.accepted_quantity = accepted_quantity
        line.quality_remark = item.get("quality_remark", "")
        if accepted_quantity > 0 and line.measurement_kind != 'PIPE':
            validate_inbound_stock_identity(line)
        prepared.append(line)

    total_return = Decimal("0")
    total_accepted = Decimal("0")
    for line in prepared:
        line.save(
            update_fields=[
                "raw_material_information",
                "return_bar_count", "accepted_bar_count",
                "return_quantity",
                "accepted_quantity",
                "quality_remark",
                "updated_at",
            ]
        )
        total_return += line.return_quantity
        total_accepted += line.accepted_quantity

    inbound.status = MaterialInboundStatus.CONFIRMED
    inbound.quality_confirmed_by_employee = actor_employee
    inbound.quality_confirmed_at = timezone.now()
    inbound.save(update_fields=["status", "quality_confirmed_by_employee", "quality_confirmed_at", "updated_at"])
    generate_quality_returns(inbound=inbound, lines=locked_lines, actor_employee=actor_employee, request=request)
    binding_by_line = {binding.purchase_order_line_id: binding for binding in bindings}
    for line in sorted(
        locked_lines,
        key=lambda item: (str(item.raw_material_information_id), str(item.zone_id), str(item.pk)),
    ):
        if line.accepted_quantity > 0:
            credit_confirmed_inbound_line(line=line, actor_employee=actor_employee)
        binding = binding_by_line.get(line.purchase_order_line_id)
        if binding and line.accepted_quantity > 0:
            receive_material_arrival(procurement_request_id=binding.procurement_request_id,
                                     line_key=binding.line_key, inbound_line_id=line.pk, request=request)
    write_audit_log(
        object_type="MATERIAL_INBOUND",
        object_id=inbound.pk,
        action="QUALITY_CONFIRMED",
        context_type="PURCHASE_ORDER",
        context_id=inbound.purchase_order_id,
        actor_employee=actor_employee,
        after_data={
            "inbound_number": inbound.inbound_number,
            "return_quantity": str(total_return),
            "accepted_quantity": str(total_accepted),
        },
        request=request,
    )
    if inbound.purchase_order.source_type == 'SAMPLE':
        # 历史待检单确认会改变剩余可收量，同时作废旧的一键入库预览。
        inbound.purchase_order.save(update_fields=['updated_at'])
    from apps.wecom.notification_services import register_business_event
    accepted, returned = _inspection_quantities(locked_lines)
    register_business_event(
        event_code="MATERIAL_INSPECTION_CONFIRMED", idempotency_key=f"MATERIAL_INSPECTION_CONFIRMED:{inbound.pk}:1",
        object_type="inventory.MaterialInbound", object_id=inbound.pk, object_version=1,
        context={"document_no": inbound.inbound_number, "purchase_order_no": inbound.purchase_order.order_number,
                 "accepted_quantity": accepted, "return_quantity": returned,
                 "status": f"合格：{accepted}；退货：{returned}", "operator": actor_employee.display_name,
                 "occurred_at": inbound.quality_confirmed_at.isoformat()},
    )
    return inbound


def _inspection_quantities(lines):
    # 不混加根、米、件等不同单位；历史缺失根数仍按保存的米数说明。
    quantities = {}
    for line in lines:
        if line.measurement_kind == "PIPE" and line.accepted_bar_count is not None and line.return_bar_count is not None:
            unit, accepted, returned = "根", line.accepted_bar_count, line.return_bar_count
        else:
            unit = ("米（历史根数未记录）" if line.measurement_kind == "PIPE"
                    else line.source_unit_text_snapshot or "（原单位未记录）")
            accepted, returned = line.accepted_quantity, line.return_quantity
        totals = quantities.setdefault(unit, [Decimal("0"), Decimal("0")])
        totals[0] += accepted
        totals[1] += returned
    return tuple("、".join(f"{totals[index]:f}{unit}" for unit, totals in sorted(quantities.items())) for index in (0, 1))
