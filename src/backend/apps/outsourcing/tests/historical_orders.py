"""仅为历史单据回归建立 ORM 夹具，不恢复已下线的创建接口或业务校验。"""
import uuid
from decimal import Decimal

from django.db import transaction

from apps.boms.material_attributes import bom_attribute_fields
from apps.boms.material_flow_calculations import cutting_quantity_plan
from apps.boms.models import Bom, BomLine
from apps.inventory.public_stock_identity import build_pipe_stock_identity, build_semi_finished_identity
from apps.inventory.public_stock_mode import new_stock_mode
from apps.material_issues.pipe_requirements import pipe_source_snapshot
from apps.products.material_identity import resolve_bom_line_raw_material
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft

from ..models import (OutsourcingOrder, OutsourcingOrderProduct, OutsourcingProcessingItem,
                      OutsourcingFactory, OutsourcingFactoryAllocation, OutsourcingMaterialItem)
from ..public_stock_services import json_snapshot
from ..services import _current_order_source_snapshot, _json_hash


def flow_snapshot(line):
    raw, _ = resolve_bom_line_raw_material(line.fabric_source_line or line)
    snapshot = {"schema_version": 2, "bom_id": str(line.section.bom_id),
                "bom_line_id": str(line.pk), "component_identity": str(line.component_identity),
                "raw_material_id": str(raw.pk) if raw else None,
                "material_line_id": str(line.fabric_source_line_id or line.pk)}
    if line.cutting_length_mm:
        snapshot.update(pipe_source_snapshot(line, raw), kind="PIPE", input_unit="支", output_unit="支")
    elif line.fabric_source_line_id:
        snapshot.update(cutting_quantity_plan(cutting_pieces_per_set=line.cutting_pieces_per_set,
            cutting_sets_per_product=line.cutting_sets_per_product, order_quantity=line.section.bom.order_quantity),
            kind="FABRIC", quantity_basis="OUTPUT_SETS", input_unit="套", output_unit="套", raw_input_unit="米")
    else:
        # 早期历史单没有换算快照，仅用于详情、删除和作废回归。
        snapshot.update(kind="OTHER", input_unit=line.unit, output_unit=line.unit)
    return snapshot


@transaction.atomic
def create_historical_order(payload, employee):
    craft = Craft.objects.get(pk=payload["craft_id"])
    order = OutsourcingOrder.objects.create(
        stock_mode=new_stock_mode(), order_number=f"HIST-{uuid.uuid4().hex[:20].upper()}",
        schedule_id=payload["schedule_id"], craft=craft, craft_name_snapshot=craft.name,
        craft_code_snapshot=craft.outsourcing_code, delivery_date=payload["delivery_date"],
        remark=payload.get("remark", ""), client_request_id=payload["client_request_id"],
        request_payload_hash=_json_hash(payload), created_by_employee=employee, updated_by_employee=employee,
    )
    for product_index, row in enumerate(payload["products"], 1):
        product = ProductionScheduleProduct.objects.get(pk=row["schedule_product_id"])
        bom = Bom.objects.get(pk=row["bom_id"])
        order_product = OutsourcingOrderProduct.objects.create(
            order=order, schedule_product=product, bom=bom, line_number=product_index,
            product_snapshot=product.product_snapshot, order_quantity_snapshot=product.source_quantity_snapshot,
            planned_quantity_snapshot=product.planned_quantity, bom_number_snapshot=bom.bom_number,
            bom_version_snapshot=bom.version_number, source_revision_hash=product.source_revision_hash,
        )
        allocations = {}
        for index, item in enumerate(row["processing_items"], 1):
            line = BomLine.objects.select_related("section__bom", "fabric_source_line").get(pk=item["bom_line_id"])
            flow = flow_snapshot(line)
            unit = ProductionUnit.objects.get(unit_name=flow["output_unit"])
            component = {"flow": flow, "section_title": line.section.title,
                "part_name": line.part_name or line.material or line.raw_material,
                "category": (line.raw_values or {}).get("cutting_category") or line.category or line.section.title,
                "color": (line.raw_values or {}).get("cutting_color") or (line.raw_values or {}).get("tube_coating_color", ""),
                "specification": line.specification, "bom_attributes": bom_attribute_fields(line),
                "reference_usage": str(line.cutting_sets_per_product) if line.fabric_source_line_id else line.cut_piece_quantity or line.unit_consumption,
                "technical_reference": line.notes}
            if order.stock_mode == "PUBLIC_V2":
                component["public_output_identity"] = json_snapshot(build_semi_finished_identity(
                    bom_line=line, completed_craft=craft, unit=unit))
            processing = OutsourcingProcessingItem.objects.create(
                order_product=order_product, bom_line=line, component_key=str(line.pk), line_number=index,
                quantity=item["quantity"], unit=unit, unit_snapshot=unit.unit_name, component_snapshot=component,
                processing_requirement=item.get("processing_requirement", ""),
            )
            for data in item["allocations"]:
                factory = OutsourcingFactory.objects.get(pk=data["factory_id"])
                allocation = OutsourcingFactoryAllocation.objects.create(
                    processing_item=processing, factory=factory, allocated_quantity=data["allocated_quantity"],
                    input_quantity=data.get("input_quantity"),
                    input_unit_snapshot=flow["input_unit"], conversion_snapshot=flow,
                    unit_price=data["unit_price"], remark=data.get("remark", ""),
                    factory_snapshot={key: getattr(factory, key) for key in
                                      ("factory_number", "name", "contact_name", "contact_phone", "address")},
                )
                allocations[(str(line.pk), str(factory.pk))] = allocation
        for index, data in enumerate(row["materials"], 1):
            allocation = allocations[(data["processing_bom_line_id"], data["factory_id"])]
            line = BomLine.objects.select_related("section__bom").get(pk=data["bom_line_id"])
            raw, _ = resolve_bom_line_raw_material(line)
            flow = dict(allocation.conversion_snapshot)
            if str(line.pk) != flow["material_line_id"]:
                flow = {"schema_version": 2, "kind": "OTHER", "raw_material_id": str(raw.pk) if raw else None,
                        "input_unit": raw.unit.unit_name if raw else line.unit, "material_line_id": str(line.pk)}
            amount = Decimal(data["planned_issue_quantity"])
            is_pipe = flow["kind"] == "PIPE"
            planned = amount / Decimal(flow["pieces_per_bar"]) if is_pipe else amount
            if order.stock_mode == "PUBLIC_V2" and is_pipe:
                flow["public_identity"] = json_snapshot(build_pipe_stock_identity(raw_material=raw,
                    raw_bar_length_m=Decimal(flow["raw_bar_length_m"]), unit=raw.unit))
            if flow["kind"] == "FABRIC":
                flow["input_unit"] = "米"
            consumption = Decimal(line.unit_consumption) if line.unit_consumption else None
            OutsourcingMaterialItem.objects.create(
                allocation=allocation, bom_material_line=line, line_number=index,
                material_snapshot={"section_title": line.section.title,
                    "inventory_raw_material_id": str(raw.pk) if raw else None,
                    "inventory_material_number": raw.material_number if raw else "",
                    "inventory_material_name": raw.material_name if raw else "",
                    "name": line.part_name or line.material or line.raw_material,
                    "specification": line.specification, "bom_attributes": bom_attribute_fields(line),
                    "unit_consumption": line.unit_consumption, "notes": line.notes,
                    "planned_batches": [{**batch, "quantity": format(Decimal(batch["quantity"]), ".4f")}
                                        for batch in data.get("planned_batches", [])]},
                unit_text=raw.unit.unit_name if raw else line.unit,
                planned_piece_count=int(amount) if is_pipe else None,
                planned_meters=planned * Decimal(flow["raw_bar_length_m"]) if is_pipe else None,
                conversion_snapshot=flow, reference_order_quantity_sets=product.source_quantity_snapshot,
                consumption_basis="BOM_USAGE_X_ORDER", consumption_per_set=consumption,
                reference_required_quantity=flow["suggested_bar_count"] if is_pipe else (consumption or 0) * bom.order_quantity,
                planned_issue_quantity=planned, difference_reason=data.get("difference_reason", ""),
                remark=data.get("remark", ""),
            )
    order.source_snapshot = _current_order_source_snapshot(order)
    order.source_revision_hash = _json_hash(order.source_snapshot)
    order.save(update_fields=["source_snapshot", "source_revision_hash"])
    return order
