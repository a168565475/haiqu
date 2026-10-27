from apps.access_control.resource_scopes import require_order_craft
from apps.organizations.selectors import active_department_employees
from apps.inventory.public_stock_cutover import stock_write_transaction
import hashlib
import json
from decimal import Decimal
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.boms.models import Bom, BomLine
from apps.inventory.models import (
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockQuality,
    RecordStatus as InventoryRecordStatus,
    WarehouseType,
    WarehouseZone,
)
from apps.inventory.stock_services import (
    credit_semi_finished_stock,
    debit_material_stock,
    inbound_batch_available_quantities,
    inbound_line_material,
)
from apps.material_issues.models import OrderMaterialRequirement
from apps.material_issues.requirements import sync_order_requirements
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.material_identity import lock_bom_line_material_identities, resolve_bom_line_raw_material
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus

from .models import (
    FactoryStatus,
    OutsourcingFactory,
    OutsourcingFactoryAllocation,
    OutsourcingFactoryCraft,
    OutsourcingMaterialItem,
    OutsourcingOrder,
    OutsourcingOrderProduct,
    OutsourcingOrderStatus,
    OutsourcingProcessingItem,
    OutsourcingDispatch,
    OutsourcingDispatchLine,
    OutsourcingReturn,
    OutsourcingReturnLine,
)

SUPPORTED_OUTSOURCING_CRAFT_CODES = tuple(code for code in OutsourcingCode.values if code != 'EMBROIDERY')
QUANTITY_PRECISION = Decimal("0.0001")


def _factory_number():
    return f"JG-{uuid4().hex[:12].upper()}"


def _snapshot(factory):
    links = getattr(factory, "prefetched_craft_links", None)
    if links is None:
        links = factory.craft_links.select_related("craft").all()
    return {
        "factory_number": factory.factory_number,
        "name": factory.name,
        "craft_ids": [str(link.craft_id) for link in links],
        "processing_type": factory.processing_type,
        "estimated_output": str(factory.estimated_output) if factory.estimated_output is not None else None,
        "estimated_output_unit": factory.estimated_output_unit,
        "estimated_output_period": factory.estimated_output_period,
        "contact_name": factory.contact_name,
        "contact_phone": factory.contact_phone,
        "address": factory.address,
        "remark": factory.remark,
        "payment_cycle": factory.payment_cycle,
        "status": factory.status,
        "version": factory.version,
    }


def _json_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_snapshot(
    schedule,
    craft,
    product_rows,
    bom_map,
    line_map,
    *,
    lock_material_identities=False,
):
    snapshot = {
        "schedule_id": str(schedule.pk),
        "schedule_number": schedule.schedule_number,
        "schedule_status": schedule.record_status,
        "schedule_version": schedule.version,
        "production_task_id": str(schedule.production_task_id),
        "production_task_number": schedule.production_task.task_number,
        "craft_id": str(craft.pk),
        "craft_name": craft.name,
        "craft_code": craft.outsourcing_code,
        "products": [],
    }
    for row in product_rows:
        product = row["schedule_product"]
        bom = bom_map[row["bom_id"]]
        snapshot["products"].append({
            "schedule_product_id": str(product.pk),
            "source_revision_hash": product.source_revision_hash,
            "source_quantity": product.source_quantity_snapshot,
            "planned_quantity": product.planned_quantity,
            "bom_id": str(bom.pk),
            "bom_number": bom.bom_number,
            "bom_version": bom.version_number,
            "bom_updated_at": bom.updated_at.isoformat(),
            "processing_line_ids": sorted(str(item["bom_line_id"]) for item in row["processing_items"]),
            "material_line_ids": sorted(str(item["bom_line_id"]) for item in row["materials"]),
        })
    snapshot["line_updated_at"] = {
        str(line_id): line_map[line_id].updated_at.isoformat()
        for line_id in sorted(line_map, key=str)
    }
    material_identity_cache = {}
    material_inventory_ids = {}
    if lock_material_identities:
        lock_bom_line_material_identities(line_map.values())
    for row in product_rows:
        for item in row["materials"]:
            line_id = item["bom_line_id"]
            material, _ = resolve_bom_line_raw_material(
                line_map[line_id],
                cache=material_identity_cache,
            )
            material_inventory_ids[str(line_id)] = str(material.pk) if material is not None else None
    snapshot["material_inventory_ids"] = material_inventory_ids
    return snapshot


def _current_order_source_snapshot(order):
    """按外发单当前关联的排产、BOM 和明细重建来源快照。"""
    # 发料确认必须把快照涉及的全部来源行锁到事务结束，避免“校验通过后、扣库前”被并发修改。
    schedule = ProductionSchedule.objects.select_for_update(of=("self",)).select_related("production_task").get(pk=order.schedule_id)
    craft = Craft.objects.select_for_update().get(pk=order.craft_id)
    order_products = list(
        order.products.select_for_update()
        .prefetch_related("processing_items__allocations__material_items")
        .order_by("line_number", "id")
    )
    schedule_product_ids = [item.schedule_product_id for item in order_products]
    schedule_products = {
        item.pk: item
        for item in ProductionScheduleProduct.objects.select_for_update()
        .filter(pk__in=schedule_product_ids)
        .order_by("pk")
    }
    bom_ids = [item.bom_id for item in order_products]
    locked_boms = {
        item.pk: item
        for item in Bom.objects.select_for_update().filter(pk__in=bom_ids).order_by("pk")
    }
    if len(schedule_products) != len(set(schedule_product_ids)) or len(locked_boms) != len(set(bom_ids)):
        raise Conflict("排产产品或 BOM 已变化，请重新建立外发单。")
    product_rows = []
    bom_map = {}
    line_ids = set()
    for order_product in order_products:
        processing_items = list(order_product.processing_items.all())
        materials = [
            material
            for processing in processing_items
            for allocation in processing.allocations.all()
            for material in allocation.material_items.all()
        ]
        processing_rows = [{"bom_line_id": item.bom_line_id} for item in processing_items]
        material_rows = [{"bom_line_id": item.bom_material_line_id} for item in materials]
        line_ids.update(item["bom_line_id"] for item in processing_rows)
        line_ids.update(item["bom_line_id"] for item in material_rows)
        bom_map[order_product.bom_id] = locked_boms[order_product.bom_id]
        product_rows.append({
            "schedule_product": schedule_products[order_product.schedule_product_id],
            "bom_id": order_product.bom_id,
            "processing_items": processing_rows,
            "materials": material_rows,
        })
    line_map = {
        line.pk: line
        for line in BomLine.objects.select_for_update().filter(pk__in=line_ids).order_by("pk")
    }
    if len(line_map) != len(line_ids):
        raise Conflict("BOM 明细已变化，请重新建立外发单。")
    return _source_snapshot(
        schedule,
        craft,
        product_rows,
        bom_map,
        line_map,
        lock_material_identities=True,
    )


def _assert_order_source_unchanged(order):
    if _json_hash(_current_order_source_snapshot(order)) != order.source_revision_hash:
        raise Conflict("排产或 BOM 来源已经变化，请作废后重新建立外发单。")


def order_audit_snapshot(order):
    return {
        "order_number": order.order_number,
        "schedule_id": str(order.schedule_id),
        "craft_id": str(order.craft_id),
        "delivery_date": order.delivery_date.isoformat(),
        "status": order.status,
        "version": order.version,
    }


def _validated_crafts(craft_ids):
    unique_ids = list(dict.fromkeys(craft_ids))
    crafts = list(Craft.objects.select_for_update().filter(pk__in=unique_ids))
    if len(crafts) != len(unique_ids):
        raise ValidationError({"craft_ids": "存在无效工艺。"})
    for craft in crafts:
        if craft.craft_type != CraftType.EXTERNAL or craft.status != RecordStatus.ACTIVE:
            raise ValidationError({"craft_ids": f"工艺“{craft.name}”不是可用厂外工艺。"})
        if craft.outsourcing_code not in OutsourcingCode.values:
            raise ValidationError({"craft_ids": f"工艺“{craft.name}”不在本期委外范围。"})
    return crafts


def _apply_fields(factory, data):
    for field in (
        "name", "processing_type", "estimated_output", "estimated_output_unit",
        "estimated_output_period", "contact_name", "contact_phone", "address",
        "remark", "payment_cycle",
    ):
        setattr(factory, field, data.get(field, getattr(factory, field, "")))


@transaction.atomic
def create_factory(*, validated_data, actor_employee, request=None):
    craft_ids = validated_data.pop("craft_ids")
    crafts = _validated_crafts(craft_ids)
    factory = OutsourcingFactory(
        factory_number=_factory_number(),
        created_by_employee=actor_employee,
        updated_by_employee=actor_employee,
        **validated_data,
    )
    factory.full_clean()
    factory.save()
    OutsourcingFactoryCraft.objects.bulk_create([
        OutsourcingFactoryCraft(factory=factory, craft=craft, craft_name_snapshot=craft.name)
        for craft in crafts
    ])
    write_audit_log(
        object_type="OUTSOURCING_FACTORY", object_id=factory.pk, action="CREATED",
        actor_employee=actor_employee, after_data=_snapshot(factory), request=request,
    )
    return factory


@transaction.atomic
def update_factory(*, factory_id, validated_data, actor_employee, request):
    factory = OutsourcingFactory.objects.select_for_update().get(pk=factory_id)
    require_matching_etag(request, factory)
    before = _snapshot(factory)
    craft_ids = validated_data.pop("craft_ids")
    crafts = _validated_crafts(craft_ids)
    _apply_fields(factory, validated_data)
    factory.version += 1
    factory.updated_by_employee = actor_employee
    factory.full_clean()
    factory.save()
    factory.craft_links.all().delete()
    OutsourcingFactoryCraft.objects.bulk_create([
        OutsourcingFactoryCraft(factory=factory, craft=craft, craft_name_snapshot=craft.name)
        for craft in crafts
    ])
    write_audit_log(
        object_type="OUTSOURCING_FACTORY", object_id=factory.pk, action="UPDATED",
        actor_employee=actor_employee, before_data=before, after_data=_snapshot(factory), request=request,
    )
    return factory


@transaction.atomic
def disable_factory(*, factory_id, actor_employee, request):
    factory = OutsourcingFactory.objects.select_for_update().get(pk=factory_id)
    require_matching_etag(request, factory)
    if factory.status == FactoryStatus.DISABLED:
        return factory
    before = _snapshot(factory)
    factory.status = FactoryStatus.DISABLED
    factory.version += 1
    factory.updated_by_employee = actor_employee
    factory.full_clean()
    factory.save()
    write_audit_log(
        object_type="OUTSOURCING_FACTORY", object_id=factory.pk, action="DISABLED",
        actor_employee=actor_employee, before_data=before, after_data=_snapshot(factory), request=request,
    )
    return factory


@stock_write_transaction
def cancel_order(*, order_id, reason, actor_employee, request):
    require_order_craft(request, "outsourcing.cancel_outsourcingorder", order_id)
    order = OutsourcingOrder.objects.select_for_update().get(pk=order_id)
    require_matching_etag(request, order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    if order.status != OutsourcingOrderStatus.PENDING_DISPATCH:
        raise Conflict("只有尚未发料的外发单可以作废。")
    before = order_audit_snapshot(order)
    order.status = OutsourcingOrderStatus.CANCELLED
    order.cancel_reason = reason
    order.cancelled_at = timezone.now()
    order.cancelled_by_employee = actor_employee
    order.updated_by_employee = actor_employee
    order.version += 1
    order.full_clean()
    order.save()
    write_audit_log(
        object_type="OUTSOURCING_ORDER",
        object_id=order.pk,
        action="CANCELLED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=order_audit_snapshot(order),
        context_type="PRODUCTION_SCHEDULE",
        context_id=order.schedule_id,
        request=request,
    )
    return order


@stock_write_transaction
def delete_order(*, order_id, actor_employee, request):
    require_order_craft(request, "outsourcing.delete_outsourcingorder", order_id)
    order = OutsourcingOrder.objects.select_for_update(of=("self",)).get(pk=order_id)
    require_matching_etag(request, order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    if order.status != OutsourcingOrderStatus.PENDING_DISPATCH:
        raise Conflict("只有尚未外发的外发单可以删除。")
    if (
        OutsourcingDispatch.objects.filter(order=order).exists()
        or OutsourcingReturn.objects.filter(order=order).exists()
    ):
        raise Conflict("外发单已经产生发料或回货记录，不能删除。")

    before = order_audit_snapshot(order)
    order_id_value = order.pk
    schedule_id = order.schedule_id

    materials = OutsourcingMaterialItem.objects.filter(
        allocation__processing_item__order_product__order=order,
    )
    allocations = OutsourcingFactoryAllocation.objects.filter(
        processing_item__order_product__order=order,
    )
    processing_items = OutsourcingProcessingItem.objects.filter(order_product__order=order)
    products = OutsourcingOrderProduct.objects.filter(order=order)

    materials.delete()
    allocations.delete()
    processing_items.delete()
    products.delete()
    remaining_order = OutsourcingOrder.objects.filter(pk=order_id_value)
    from apps.material_issues.p4_services import p4_schema_ready
    if not p4_schema_ready() and "metal_processing_original_handoff" not in connection.introspection.table_names():
        # 旧库没有P4表，Django关联收集器仍会按新版模型查询缺失表。
        # 旧子表已依序检查/删除；仅删除当前锁定主键，数据库外键仍负责拒绝真实关联。
        remaining_order._raw_delete(using=remaining_order.db)
    else:
        remaining_order.delete()

    write_audit_log(
        object_type="OUTSOURCING_ORDER",
        object_id=order_id_value,
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before,
        context_type="PRODUCTION_SCHEDULE",
        context_id=schedule_id,
        request=request,
    )


def _raw_material_from_bom_line(line):
    material, _ = resolve_bom_line_raw_material(line)
    return material


def dispatch_context(order):
    from .dispatch_services import flow_dispatch_context
    return flow_dispatch_context(order)


@stock_write_transaction
def confirm_dispatch(*, order_id, request_id, line_inputs, remark, actor_employee, request):
    from .dispatch_services import confirm_flow_dispatch
    return confirm_flow_dispatch(order_id=order_id, request_id=request_id, line_inputs=line_inputs,
        remark=remark, actor_employee=actor_employee, request=request)


def _return_number():
    return next_business_number("OUTSOURCING_RETURN")


@stock_write_transaction
def confirm_return(
    *, order_id, request_id, factory_id, good_zone_id, defective_zone_id,
    received_by_employee_id, return_date, delivery_note_number, line_inputs,
    remark, actor_employee, request, raw_inputs=None,
):
    require_order_craft(request, "outsourcing.confirm_return_outsourcingorder", order_id)
    payload = {
        "order_id": str(order_id),
        "factory_id": str(factory_id),
        "raw_inputs": raw_inputs or [],
        "good_zone_id": str(good_zone_id) if good_zone_id else None,
        "defective_zone_id": str(defective_zone_id) if defective_zone_id else None,
        "received_by_employee_id": str(received_by_employee_id),
        "return_date": str(return_date),
        "delivery_note_number": delivery_note_number,
        "lines": line_inputs,
        "remark": remark,
    }
    from .material_flow import lock_request
    from uuid import UUID, uuid5
    lock_request("return", request_id)
    lock_request("reconciliation", uuid5(UUID(str(request_id)), "return-raw-input"))
    request_hash = _json_hash(payload)
    existing = OutsourcingReturn.objects.select_related("order").filter(client_request_id=request_id).first()
    if existing:
        if existing.order_id != order_id or existing.request_payload_hash != request_hash:
            raise Conflict("相同回厂请求标识已用于不同内容。")
        return existing.order

    order = OutsourcingOrder.objects.select_for_update(of=("self",)).select_related(
        "schedule__production_task", "craft"
    ).get(pk=order_id)
    existing = OutsourcingReturn.objects.select_related("order").filter(client_request_id=request_id).first()
    if existing:
        if existing.order_id != order_id or existing.request_payload_hash != request_hash:
            raise Conflict("相同回厂请求标识已用于不同内容。")
        return existing.order
    require_matching_etag(request, order)
    from apps.material_issues.p4_services import assert_legacy_original_route
    assert_legacy_original_route(order)
    if order.status not in {OutsourcingOrderStatus.PROCESSING, OutsourcingOrderStatus.PARTIAL_RETURN}:
        raise Conflict("只有已确认发料且仍在加工的外发单可以确认回厂。")
    if not hasattr(order, "dispatch_record"):
        raise Conflict("外发单尚无仓库确认发料记录。")
    from apps.inventory.public_stock_mode import require_document_stock_mode
    public = require_document_stock_mode(order)
    if public and any(item["defective_quantity"] > 0 for item in line_inputs):
        raise ValidationError({"lines": "本期公共库存只登记合格半成品，不登记不良品。"})
    public_line_ids = {}
    if public:
        from .public_stock_services import lock_order_sources
        from apps.inventory.public_stock_services import _lock_source
        lock_order_sources(order)
        public_line_ids = {item["allocation_id"]: uuid4() for item in line_inputs}
        for line_id in sorted(public_line_ids.values(), key=str):
            _lock_source({"source_type": "OUTSOURCING_RETURN", "source_line_id": line_id}, "IN")
    from .reconciliation_services import prepare_return_inputs, assert_return_capacity
    prepare_return_inputs(order, request_id, raw_inputs or [], line_inputs, actor_employee)
    zone_ids = sorted({value for value in (good_zone_id, defective_zone_id) if value}, key=str)
    if public:
        from apps.inventory.public_stock_services import lock_public_stock_locations
        zones = lock_public_stock_locations(zone_ids)
    else:
        zones = {
            row.pk: row
            for row in WarehouseZone.objects.select_for_update(of=("self",)).select_related("warehouse")
            .filter(pk__in=zone_ids).order_by("id")
        }
    if len(zones) != len(zone_ids):
        raise ValidationError({"zones": "存在无效回货库区。"})
    for zone in zones.values():
        if zone.status != InventoryRecordStatus.ACTIVE or zone.warehouse.status != InventoryRecordStatus.ACTIVE:
            raise ValidationError({"zones": "所选回货库区已停用。"})
    good_zone = zones.get(good_zone_id)
    defective_zone = zones.get(defective_zone_id)
    if good_zone and good_zone.warehouse.warehouse_type != WarehouseType.SEMI_FINISHED:
        raise ValidationError({"good_zone_id": "合格品只能进入半成品仓库区。"})
    if defective_zone and defective_zone.warehouse.warehouse_type != WarehouseType.DEFECTIVE:
        raise ValidationError({"defective_zone_id": "不良品只能进入不良品仓库区。"})
    received_by = active_department_employees("DEPT_WAREHOUSE").filter(
        pk=received_by_employee_id,
        status=EmployeeStatus.ACTIVE,
        archived_at__isnull=True,
    ).first()
    if received_by is None:
        raise ValidationError({"received_by_employee_id": "接收人不存在、已停用或已归档。"})

    allocation_ids = [item["allocation_id"] for item in line_inputs]
    if len(allocation_ids) != len(set(allocation_ids)):
        raise ValidationError({"lines": "同一加工分配行不能重复填写。"})
    allocations = {
        item.pk: item
        for item in OutsourcingFactoryAllocation.objects.select_for_update(of=("self",)).select_related(
            "processing_item__order_product__schedule_product__product_line__unit",
            "processing_item__bom_line", "processing_item__unit", "factory",
        ).filter(
            pk__in=allocation_ids,
            processing_item__order_product__order=order,
            factory_id=factory_id,
        ).order_by("id")
    }
    if len(allocations) != len(allocation_ids):
        raise ValidationError({"lines": "存在不属于当前外发单的加工分配行。"})
    returned_totals = {
        row["allocation_id"]: row["total"] or 0
        for row in OutsourcingReturnLine.objects.filter(allocation_id__in=allocation_ids)
        .values("allocation_id").annotate(total=Sum("returned_quantity"))
    }
    from apps.material_issues.p4_services import original_handoff_totals, p4_schema_ready
    p4_ready = p4_schema_ready()
    for item in line_inputs:
        allocation = allocations[item["allocation_id"]]
        from .material_flow import quantity
        quantity(item["good_quantity"], "good_quantity", integer=True, allow_zero=True)
        quantity(item["defective_quantity"], "defective_quantity", integer=True, allow_zero=True)
        received_quantity = item["good_quantity"] + item["defective_quantity"]
        # 原单锁同时保护金工直接交接退回，防止同一批管件两条路径重复入库。
        if p4_ready:
            handoff_totals = original_handoff_totals(allocation)
            if handoff_totals["handoff_pieces"] and (
                received_quantity + handoff_totals["returned_pieces"]
                + handoff_totals["returned_unsprayed_pieces"] > handoff_totals["handoff_pieces"]
            ):
                raise ValidationError({"lines": "回货与未喷塑退回合计不能超过金工实际交接支数。"})
        assert_return_capacity(allocation, received_quantity)
        if received_quantity <= 0:
            raise ValidationError({"lines": "本批每条回货明细的实收数量必须大于 0。"})
        if item["good_quantity"] > 0 and good_zone is None:
            raise ValidationError({"good_zone_id": "存在合格数量时必须选择半成品库区。"})
        if item["defective_quantity"] > 0 and defective_zone is None:
            raise ValidationError({"defective_zone_id": "存在不良数量时必须选择不良品库区。"})
        if item["defective_quantity"] > 0 and not item.get("defect_reason", "").strip():
            raise ValidationError({"lines": "存在不良数量时必须填写不良原因。"})
        if returned_totals.get(allocation.pk, Decimal("0")) + received_quantity > allocation.allocated_quantity:
            raise ValidationError({"lines": "回厂数量超过该加工厂分配数量。"})

    before = order_audit_snapshot(order)
    return_record = OutsourcingReturn.objects.create(
        return_number=_return_number(),
        order=order,
        factory_id=factory_id,
        client_request_id=request_id,
        request_payload_hash=request_hash,
        zone=good_zone or defective_zone,
        defective_zone=defective_zone,
        received_by_employee=received_by,
        return_date=return_date,
        delivery_note_number=delivery_note_number,
        factory_snapshot={
            "id": str(factory_id),
            "name": next(iter(allocations.values())).factory_snapshot.get(
                "name", next(iter(allocations.values())).factory.name
            ),
        },
        confirmed_by_employee=actor_employee,
        confirmed_at=timezone.now(),
        remark=remark,
    )
    for item in line_inputs:
        allocation = allocations[item["allocation_id"]]
        processing_item = allocation.processing_item
        order_product = processing_item.order_product
        product_line = order_product.schedule_product.product_line
        for quality, quantity, target_zone in (
            (MaterialStockQuality.AVAILABLE, item["good_quantity"], good_zone),
            (MaterialStockQuality.DEFECTIVE, item["defective_quantity"], defective_zone),
        ):
            if quantity <= 0:
                continue
            line_id = public_line_ids[allocation.pk] if public else uuid4()
            component_snapshot = processing_item.component_snapshot
            output_color = component_snapshot.get("color", "")
            if order.craft_code_snapshot == "POWDER_COATING":
                output_color = next(
                    (field.get("value", "") for field in component_snapshot.get("bom_attributes", [])
                     if field.get("key") == "spray_color" and field.get("value")),
                    output_color,
                )
            snapshot = {
                "return_number": return_record.return_number,
                "order_number": order.order_number,
                "factory": allocation.factory_snapshot.get("name", allocation.factory.name),
                "component": processing_item.component_snapshot.get("part_name", ""),
                "completed_craft": order.craft_name_snapshot,
                "color": output_color,
                "unit": processing_item.unit_snapshot,
                "quality": quality,
                "defect_reason": item.get("defect_reason", "") if quality == MaterialStockQuality.DEFECTIVE else "",
            }
            if public:
                from .public_stock_services import public_output_identity, json_snapshot
                from apps.inventory.public_stock_services import credit_public_stock
                identity = public_output_identity(processing_item, order)
                snapshot["color"] = identity["identity_snapshot"].get("color", snapshot["color"])
                snapshot.update(stock_mode="PUBLIC_V2", public_output_identity=json_snapshot(identity))
                movement = credit_public_stock(identity=identity, zone=target_zone, quantity=quantity,
                    source_type="OUTSOURCING_RETURN", source_id=return_record.pk, source_line_id=line_id,
                    actor_employee=actor_employee, production_task=order.schedule.production_task,
                    product_line=product_line, bom_line=processing_item.bom_line, snapshot=snapshot)
            else:
                movement = credit_semi_finished_stock(
                    production_task=order.schedule.production_task,
                    product_line=product_line,
                    bom_line=processing_item.bom_line,
                    completed_craft=order.craft,
                    color_snapshot=output_color,
                    unit=processing_item.unit,
                    zone=target_zone,
                    quality=quality,
                    quantity=quantity,
                    source_type="OUTSOURCING_RETURN",
                    source_id=return_record.pk,
                    source_line_id=line_id,
                    actor_employee=actor_employee,
                    snapshot=snapshot,
                )
            OutsourcingReturnLine.objects.create(
                id=line_id,
                return_record=return_record,
                allocation=allocation,
                returned_quantity=quantity,
                quality=quality,
                semi_finished_balance=None if public else movement.balance,
                public_stock_movement=movement if public else None,
                snapshot=movement.snapshot,
            )

    order.status = OutsourcingOrderStatus.PARTIAL_RETURN
    order.updated_by_employee = actor_employee
    order.version += 1
    order.save(update_fields=["status", "updated_by_employee", "version", "updated_at"])
    write_audit_log(
        object_type="OUTSOURCING_ORDER",
        object_id=order.pk,
        action="RETURN_CONFIRMED",
        actor_employee=actor_employee,
        before_data=before,
        after_data=order_audit_snapshot(order),
        context_type="PRODUCTION_SCHEDULE",
        context_id=order.schedule_id,
        request=request,
    )
    return order
